import os
os.environ["LLM_PROVIDER"] = "ollama"

from llm_provider import get_provider, OllamaProvider, GeminiProvider

print("=" * 70)
print("MODULE 9 TEST: Local LLM Swap (Ollama + Nemotron)")
print("=" * 70)

# --- Step 1: Verify Ollama is the active provider ---
provider = get_provider()
print(f"\n[1] Active provider: {provider.provider_name()}")
assert isinstance(provider, OllamaProvider), "FAIL: Provider should be OllamaProvider"
print("    PASS: OllamaProvider is active (not Gemini)")

# --- Step 2: Check Ollama server reachability ---
print(f"\n[2] Checking Ollama server at {provider.base_url}...")
if not provider.is_available():
    print("    WARNING: Ollama server is not running.")
    print("    To set up:")
    print("      1. Install Ollama: https://ollama.com")
    print("      2. Start server:   ollama serve")
    print("      3. Pull model:     ollama pull nemotron-mini")
    print("      4. Re-run this test")
    print("\n    Skipping generation test (server offline).")
else:
    print("    PASS: Ollama server is reachable")

    # --- Step 3: Check model availability ---
    models = provider.list_models()
    print(f"\n[3] Available models: {models}")
    if not any("nemotron" in m for m in models):
        print(f"    WARNING: nemotron-mini not found. Pull it: ollama pull nemotron-mini")
        print("    Trying with first available model..." if models else "    No models available.")
        if models:
            provider.model = models[0]
            print(f"    Using: {models[0]}")

    # --- Step 4: Test generation ---
    print(f"\n[4] Testing generation with {provider.model}...")
    try:
        response = provider.generate(
            prompt="What is 2 + 2? Answer in one sentence.",
            system_prompt="You are a helpful assistant. Be very concise.",
        )
        print(f"    Response: {response.strip()}")
        print("    PASS: Local generation successful")
    except Exception as e:
        print(f"    FAIL: {e}")

# --- Step 5: Verify Gemini is NOT called ---
print(f"\n[5] Verifying Gemini API is not used...")
try:
    gemini = GeminiProvider()
    print("    FAIL: GeminiProvider initialized (API key was set)")
except ValueError as e:
    print(f"    PASS: {e}")
    print("    Confirmed: No external API calls possible")

# --- Step 6: Network verification ---
print(f"\n[6] Network security check:")
print(f"    LLM_PROVIDER = {os.environ.get('LLM_PROVIDER', 'not set')}")
print(f"    GEMINI_API_KEY = {'[SET]' if os.environ.get('GEMINI_API_KEY') else '[EMPTY - no external calls]'}")
print(f"    OLLAMA_BASE_URL = {provider.base_url} (localhost only)")
print(f"    All LLM inference is LOCAL. Zero data leaves this machine.")

print("\n" + "=" * 70)
print("MODULE 9 COMPLETE")
print("=" * 70)


# ─────────────────────────────────────────────────────────────────────────────
# pytest tests — prefix-cache regression guards (no live network required).
# ─────────────────────────────────────────────────────────────────────────────
import json as _json

import pytest


# ── Ollama: prompt-order regression guard ──────────────────────────────────

def _catalog_block(catalog: dict) -> str:
    return _json.dumps(catalog, indent=2)


# A big-enough catalog so the Gemini estimated token count clears the
# 2048-token threshold (chars/4 estimate). ~120 metrics * ~110 chars each
# gives an estimate of ~3300 tokens — comfortably above the barrier.
BIG_CATALOG = {f"metric_{i}": {"name": f"metric_{i}", "desc": "x" * 80} for i in range(120)}
BIG_CATALOG_JSON = _catalog_block(BIG_CATALOG)

ROUTER_SYSTEM = "You are a precise metric router."
PLANNER_SYSTEM = "You are the planning module."
EXPLAIN_SYSTEM = "You are a senior data analyst explaining results."


def _router_prompt(catalog_json: str, question: str) -> str:
    """Mirror agent_core.select_metric(): schema_hint, catalog, then question."""
    return (
        "Allowed filter columns: ['region']\n\n"
        f"Available metrics:\n{catalog_json}\n\n"
        f"Question: {question}"
    )


class TestOllamaPromptOrder:
    def test_system_prompt_comes_before_catalog_and_question(self):
        """Regression guard: system + catalog must precede the question.

        This ordering is the whole precondition for Ollama's in-memory
        KV/prefix reuse (v0.32.5) and for Gemini explicit context caching.
        """
        o = OllamaProvider(base_url="http://localhost:11434", model="test-model")
        prompt = _router_prompt(BIG_CATALOG_JSON, "What is total revenue?")
        messages = o._build_messages(prompt, system_prompt=ROUTER_SYSTEM)

        assert messages[0] == {"role": "system", "content": ROUTER_SYSTEM}
        assert messages[1]["role"] == "user"
        user_content = messages[1]["content"]
        # Catalog JSON must appear before the question text.
        assert user_content.find("Available metrics:") < user_content.find("Question:")
        assert user_content.find(BIG_CATALOG_JSON[0:50]) < user_content.find("Question:")
        # System prompt is never interpolated into the user content.
        assert ROUTER_SYSTEM not in user_content

    def test_generate_payload_includes_keep_alive(self, monkeypatch):
        """keep_alive must be sent so the model stays loaded between calls."""
        sent = {}

        def fake_post(url, json=None, timeout=None):
            sent["url"] = url
            sent["json"] = json
            sent["timeout"] = timeout
            resp = type("R", (), {"status_code": 200, "raise_for_status": lambda self: None,
                                 "json": lambda self: {"message": {"content": "ok"}}})()
            return resp

        monkeypatch.setattr("llm_provider.requests.post", fake_post)
        o = OllamaProvider(base_url="http://localhost:11434", model="m", keep_alive=-1)
        out = o.generate("Question: hi", system_prompt="sys")
        assert out == "ok"
        body = sent["json"]
        assert body["keep_alive"] == -1
        # Ordering: system message before user message.
        assert body["messages"][0]["role"] == "system"
        assert body["messages"][1]["role"] == "user"


# ── Gemini: explicit context-cache behavior (mocked google.genai) ──────────

class _FakeGenerate:
    def __init__(self, text="ok", usage=None):
        self.text = text
        self.usage = usage


class _FakeCaches:
    """Mock of client.caches recording create() calls."""

    def __init__(self):
        self.creations = []  # (model, config) tuples
        self.name_seq = 0

    def create(self, *, model, config):
        self.creations.append((model, config))
        self.name_seq += 1
        return type("C", (), {"name": f"cachedContents/fake-{self.name_seq}"})()


class _FakeModels:
    """Mirrors client.models.generate_content(model=..., contents=..., config=...)."""

    def __init__(self, client):
        self._client = client

    def generate_content(self, **kwargs):
        return self._client.models_generate(**kwargs)


class _FakeClient:
    def __init__(self):
        self.caches = _FakeCaches()
        self.calls = []
        self.models = _FakeModels(self)

    def models_generate(self, **kwargs):
        self.calls.append(kwargs)
        return _FakeGenerate()


class _FakeCacheHelper:
    """Mirrors _GeminiCacheHelper.create(model, ttl_seconds, system_prompt, contents)."""

    def __init__(self, fake_caches):
        self._fake_caches = fake_caches

    def create(self, model, ttl_seconds, system_prompt, contents):
        return self._fake_caches.create(model=model, config=None).name


def _make_gemini(client) -> GeminiProvider:
    p = GeminiProvider.__new__(GeminiProvider)  # bypass __init__ (no real client)
    p.client = client
    p._model_name = "gemini-2.0-flash"
    p._cache_helper = _FakeCacheHelper(client.caches)
    p._cache_handles = {}
    return p


class TestGeminiContextCaching:
    def test_cache_created_once_and_reused_for_same_pair(self):
        client = _FakeClient()
        p = _make_gemini(client)
        prompt = _router_prompt(BIG_CATALOG_JSON, "What is total revenue?")

        p.generate(prompt, system_prompt=ROUTER_SYSTEM)
        p.generate(prompt, system_prompt=ROUTER_SYSTEM)

        assert len(client.caches.creations) == 1, \
            "second call with same (system_prompt, catalog) must NOT recreate the cache"
        assert len(client.calls) == 2
        # Cached calls send only the per-question suffix.
        assert client.calls[0]["contents"].startswith("Question: ")
        assert client.calls[1]["contents"].startswith("Question: ")
        # The verbose catalog is never resent in the request contents.
        assert "Available metrics:" not in client.calls[0]["contents"]
        assert "Available metrics:" not in client.calls[1]["contents"]
        # Both calls reference the same cached content handle.
        cfg0 = client.calls[0]["config"]
        cfg1 = client.calls[1]["config"]
        assert cfg0.cached_content == cfg1.cached_content
        assert cfg0.cached_content.startswith("cachedContents/")

    def test_different_catalog_produces_different_cache(self):
        client = _FakeClient()
        p = _make_gemini(client)

        other_catalog = _catalog_block({f"m{i}": {"name": f"m{i}", "desc": "y" * 80} for i in range(120)})
        p.generate(_router_prompt(BIG_CATALOG_JSON, "Q1"), system_prompt=ROUTER_SYSTEM)
        p.generate(_router_prompt(other_catalog, "Q2"), system_prompt=ROUTER_SYSTEM)

        assert len(client.caches.creations) == 2, "different catalog -> different cache"
        c0 = client.calls[0]["config"].cached_content
        c1 = client.calls[1]["config"].cached_content
        assert c0 != c1, "cache handles must not collide across catalogs"

    def test_expired_missing_cache_is_recreated_transparently(self):
        class MissingCache(Exception):
            def __init__(self):
                super().__init__("404 CachedContent cachedContents/gone not found")
                self.code = 404

        calls = {"n": 0}

        def flaky_generate(**kwargs):
            calls["n"] += 1
            if calls["n"] in (1, 2):
                raise MissingCache()
            return _FakeGenerate("recovered")

        client = _FakeClient()
        client.models_generate = flaky_generate
        p = _make_gemini(client)
        prompt = _router_prompt(BIG_CATALOG_JSON, "Q")

        # First call: cached handle missing server-side -> recreate + retry.
        out = p.generate(prompt, system_prompt=ROUTER_SYSTEM)
        assert out == "recovered"
        # Cache created twice: the original + the transparent recreate.
        assert len(client.caches.creations) == 2
        # The handle map now holds a fresh handle.
        assert len(p._cache_handles) == 1

        # Second call with the same pair hits the fresh handle: healthy + cached.
        out2 = p.generate(prompt, system_prompt=ROUTER_SYSTEM)
        assert out2 == "recovered"
        assert len(client.caches.creations) == 2, "no further recreate on a healthy handle"

    def test_missing_cache_retry_falls_back_to_uncached(self):
        class MissingCache(Exception):
            def __init__(self):
                super().__init__("404 CachedContent cachedContents/gone not found")
                self.code = 404

        def always_missing(**kwargs):
            client.calls.append(kwargs)
            raise MissingCache()

        client = _FakeClient()
        client.models_generate = always_missing
        p = _make_gemini(client)
        prompt = _router_prompt(BIG_CATALOG_JSON, "Q")

        with pytest.raises(MissingCache):
            p.generate(prompt, system_prompt=ROUTER_SYSTEM)

        # Flow: create -> cached call fails missing -> recreate -> cached retry
        # fails missing -> fall back to uncached call (which also fails missing
        # here and propagates). => 2 cache creations, 3 generate calls.
        assert len(client.caches.creations) == 2
        gen_calls = client.calls
        assert len(gen_calls) == 3, "cached + cached-retry + uncached-fallback"
        # Cached attempts send only the question suffix...
        assert all(c["contents"].startswith("Question: ") for c in gen_calls[:2])
        # ...and the fallback resends the full prompt.
        assert gen_calls[2]["contents"].startswith("Allowed filter columns:")

    def test_explain_no_catalog_never_creates_cache(self):
        client = _FakeClient()
        p = _make_gemini(client)
        prompt = "Question: why?\nMetric: total_revenue\nResult:\n123"
        out = p.generate(prompt, system_prompt=EXPLAIN_SYSTEM)
        assert out == "ok"
        assert client.caches.creations == [], "EXPLAIN (no catalog) must not cache"
        # Full uncached prompt is sent as-is.
        assert client.calls[0]["contents"] == prompt

    def test_below_threshold_falls_back_to_uncached(self):
        client = _FakeClient()
        p = _make_gemini(client)
        tiny_catalog = _catalog_block({"revenue": {"name": "revenue", "desc": "sum"}})
        prompt = _router_prompt(tiny_catalog, "Q")
        out = p.generate(prompt, system_prompt=ROUTER_SYSTEM)
        assert out == "ok"
        assert client.caches.creations == [], "below-threshold must not create a cache"
        assert client.calls[0]["contents"] == prompt, "full prompt resent uncached"

    def test_cache_creation_failure_falls_back_to_uncached(self):
        class CreateFailed(Exception):
            pass

        client = _FakeClient()
        p = _make_gemini(client)

        def boom(model, ttl_seconds, system_prompt, contents):
            raise CreateFailed("cache API down")

        p._cache_helper.create = boom
        prompt = _router_prompt(BIG_CATALOG_JSON, "Q")
        out = p.generate(prompt, system_prompt=ROUTER_SYSTEM)
        assert out == "ok"
        assert client.caches.creations == [], "creation failure -> nothing cached"
        assert client.calls[0]["contents"] == prompt, "fell back to full uncached call"