import abc
import hashlib
import logging
import time
import requests
from config import (
    LLM_PROVIDER, GEMINI_API_KEY,
    OLLAMA_BASE_URL, OLLAMA_MODEL, SESSION_TIMEOUT_MINUTES,
    NVIDIA_API_KEY, NVIDIA_BASE_URL, NVIDIA_MODEL,
)

logger = logging.getLogger(__name__)


class LLMProvider(abc.ABC):
    @abc.abstractmethod
    def generate(self, prompt: str, system_prompt: str = "", temperature: float = 0.1) -> str:
        """Generate text from the LLM.

        Args:
            prompt: The user prompt.
            system_prompt: Optional system instruction.
            temperature: Sampling temperature. Low (0.1) for deterministic
                         routing decisions; higher (0.7+) for natural text.
        """
        ...

    def generate_stream(
        self, prompt: str, system_prompt: str = "", temperature: float = 0.1
    ) -> "abc.Iterator[str]":
        """Stream content chunks from the LLM.

        Default implementation yields the full result of generate() as a
        single chunk, so providers that don't implement true token streaming
        still work with streaming callers. Providers that support real
        streaming (e.g. Ollama /api/chat with stream=true) override this.
        """
        yield self.generate(prompt, system_prompt=system_prompt, temperature=temperature)

    @abc.abstractmethod
    def provider_name(self) -> str:
        ...


class OllamaProvider(LLMProvider):
    def __init__(
        self,
        base_url: str = OLLAMA_BASE_URL,
        model: str = OLLAMA_MODEL,
        keep_alive: float = -1,
    ):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.keep_alive = keep_alive

    def provider_name(self) -> str:
        return f"ollama/{self.model}"

    def is_available(self) -> bool:
        try:
            r = requests.get(f"{self.base_url}/", timeout=3)
            return r.status_code == 200
        except requests.ConnectionError:
            return False

    def list_models(self) -> list[str]:
        try:
            r = requests.get(f"{self.base_url}/api/tags", timeout=5)
            r.raise_for_status()
            return [m["name"] for m in r.json().get("models", [])]
        except Exception:
            return []

    def _build_messages(self, prompt: str, system_prompt: str = "") -> list[dict]:
        """Build the /api/chat messages array.

        IMPORTANT (prefix-caching precondition): the system prompt MUST stay
        first, followed by the full user prompt (which contains the metric
        catalog before the question, as constructed in agent_core.py /
        agent_phase2.py). Ollama v0.32.5 keeps the KV/prefix state in memory
        across consecutive /api/chat calls to the same loaded model (while
        keep_alive keeps it loaded), so the shared system-prompt + catalog
        prefix is computed once and reused. Do NOT interpolate the question
        earlier in the string — that would break the shared prefix.
        """
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})
        return messages

    def _build_payload(
        self, prompt: str, system_prompt: str, temperature: float, stream: bool
    ) -> dict:
        """Build the /api/chat request payload (shared by generate/generate_stream)."""
        messages = self._build_messages(prompt, system_prompt)
        payload = {
            "model": self.model,
            "messages": messages,
            "stream": stream,
            "options": {
                "temperature": temperature,
                "num_predict": 400,
                "num_ctx": 2048,
            },
        }
        # keep_alive keeps the model resident in memory between questions so
        # the shared prefix isn't evicted from the KV cache between calls.
        # -1 = keep loaded indefinitely (per Ollama docs); an eval run can
        # thus reuse the cached prefix across the whole golden set.
        if self.keep_alive is not None:
            payload["keep_alive"] = self.keep_alive
        return payload

    def generate(self, prompt: str, system_prompt: str = "", temperature: float = 0.1) -> str:
        payload = self._build_payload(prompt, system_prompt, temperature, stream=False)

        try:
            r = requests.post(
                f"{self.base_url}/api/chat",
                json=payload,
                timeout=300,
            )
            r.raise_for_status()
            return r.json()["message"]["content"]
        except requests.ConnectionError:
            raise ConnectionError(
                f"Cannot connect to Ollama at {self.base_url}. "
                "Start it with: ollama serve"
            )
        except requests.HTTPError as e:
            if e.response.status_code == 404:
                raise RuntimeError(
                    f"Model '{self.model}' not found. Pull it with: ollama pull {self.model}"
                )
            raise

    def generate_stream(
        self, prompt: str, system_prompt: str = "", temperature: float = 0.1
    ) -> "abc.Iterator[str]":
        """Stream content chunks from Ollama's /api/chat (stream=true).

        Each yielded value is a text chunk as it is generated. The full
        concatenation of chunks equals what generate() would return.
        """
        payload = self._build_payload(prompt, system_prompt, temperature, stream=True)

        try:
            with requests.post(
                f"{self.base_url}/api/chat",
                json=payload,
                stream=True,
                timeout=300,
            ) as r:
                r.raise_for_status()
                for line in r.iter_lines(decode_unicode=True):
                    if not line:
                        continue
                    try:
                        chunk = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if chunk.get("done"):
                        break
                    delta = chunk.get("message", {}).get("content")
                    if delta:
                        yield delta
        except requests.ConnectionError:
            raise ConnectionError(
                f"Cannot connect to Ollama at {self.base_url}. "
                "Start it with: ollama serve"
            )
        except requests.HTTPError as e:
            if e.response.status_code == 404:
                raise RuntimeError(
                    f"Model '{self.model}' not found. Pull it with: ollama pull {self.model}"
                )
            raise


# ── Gemini explicit context caching ─────────────────────────────────────────
#
# Uses google.genai.caches (google-genai>=1.0, already in requirements.txt).
#
# Verified facts (research performed 2026-08-05, before implementation):
#
# * Ollama (side note for parity, since we must not change prompt ordering):
#   Ollama v0.32.5's /api/chat endpoint has NO `context` parameter — that only
#   exists on the deprecated /api/generate endpoint. Consecutive /api/chat
#   calls to the same loaded model reuse the in-memory KV/prefix state while
#   the model stays loaded; `keep_alive` controls residency. Therefore the
#   only required change on the Ollama path is passing `keep_alive` so the
#   prefix survives between questions inside an eval run — no explicit
#   context threading is possible or needed here.
#   Source: https://github.com/ollama/ollama/blob/v0.32.5/docs/api.md
#           https://github.com/ollama/ollama/blob/v0.32.5/docs/faq.mdx
#
# * Gemini explicit context caching:
#   - Min cached-token threshold (official caching docs, updated 2026-07-30):
#        Gemini 2.5 Flash / 2.5 Pro            : 2048 tokens
#        Gemini 3.5 Flash / 3.1 Pro Preview    : 4096 tokens
#     2048 is the lowest current limit, so it is the conservative barrier
#     used below; prompts under it fall back to uncached generate_content.
#   - gemini-2.5-flash (current default in __init__) is the supported
#     default model; the previous default (gemini-2.0-flash) was shut down
#     2026-06-01 per the official pricing page. The new default now
#     resolves at runtime.
#   - Cached-content storage: $1.00 / 1M tokens per hour (gemini-2.5-flash,
#     paid tier). A typical metric catalog is 1-5K tokens, so per-session
#     storage cost is negligible while the cache is alive.
#   Sources: https://ai.google.dev/gemini-api/docs/caching
#            https://ai.google.dev/gemini-api/docs/pricing
#
# Cache key = (system_prompt, catalog_json): one cache per
# (call type × dataset/catalog). METRIC_ROUTER_SYSTEM, PLANNER_SYSTEM and
# EXPLAIN_SYSTEM are distinct prompts; the catalog changes per DataSource.
# EXPLAIN_SYSTEM calls carry no catalog — their prefix is too short to be
# worth caching, so they are never cached.
#
# TTL is tied to the existing SESSION_TIMEOUT_MINUTES config (matches the
# agent's session lifetime), so no new config value is introduced.

GEMINI_CACHE_MIN_TOKENS = 2048


def _estimate_tokens(*texts: str) -> int:
    """Rough token estimate (chars / 4) used only for the cache threshold."""
    return sum(max(1, len(t) // 4) for t in texts)


class _GeminiCacheHelper:
    """Thin wrapper around google.genai.caches for testability."""

    def __init__(self, client):
        self._client = client

    def create(self, model: str, ttl_seconds: int, system_prompt: str, contents: str) -> str:
        from google.genai import types
        config = types.CreateCachedContentConfig(
            ttl=f"{ttl_seconds}s",
            display_name=f"dataagent:{hashlib.sha256((system_prompt + contents).encode()).hexdigest()[:12]}",
            system_instruction=system_prompt if system_prompt else None,
            contents=contents,
        )
        cached = self._client.caches.create(model=model, config=config)
        return cached.name


class GeminiProvider(LLMProvider):
    def __init__(self, api_key: str = GEMINI_API_KEY, model: str = "gemini-2.5-flash"):
        if not api_key:
            raise ValueError(
                "GEMINI_API_KEY not set. Export it or switch LLM_PROVIDER to 'ollama'."
            )
        from google import genai
        self.client = genai.Client(api_key=api_key)
        self._model_name = model
        self._cache_helper = _GeminiCacheHelper(self.client)
        # cache_key -> (cached_content_name, expiry_epoch, exact_prefix_text)
        self._cache_handles: dict[str, tuple[str, float, str]] = {}

    def provider_name(self) -> str:
        return f"gemini/{self._model_name}"

    # ── context-cache internals ────────────────────────────────────────────

    @staticmethod
    def _cache_key(system_prompt: str, catalog_json: str) -> str:
        """Deterministic key derived from (system_prompt, catalog_json)."""
        raw = f"{system_prompt}\x1f{catalog_json}"
        return hashlib.sha256(raw.encode()).hexdigest()

    @staticmethod
    def _is_cache_missing_error(exc: BaseException) -> bool:
        """True when the error means a CachedContent handle is gone/expired."""
        code = getattr(exc, "code", None)
        if code == 404:
            return True
        msg = str(exc).lower()
        return "cachedcontent" in msg and any(
            s in msg for s in ("not found", "expired", "does not exist")
        )

    @staticmethod
    def _extract_catalog(prompt: str) -> str | None:
        """Return the metrics-catalog JSON block from a prompt, or None.

        Looks for the 'Available metrics:' marker (used by both
        agent_core.select_metric() and agent_phase2.plan()) and scans the
        balanced braces that follow. This is purely for cache keying — the
        prompt text itself is never altered here.
        """
        idx = prompt.find("Available metrics:")
        if idx == -1:
            return None
        start = prompt.find("{", idx)
        if start == -1:
            return None
        depth = 0
        in_str = False
        escaped = False
        for i in range(start, len(prompt)):
            ch = prompt[i]
            if in_str:
                if escaped:
                    escaped = False
                elif ch == "\\":
                    escaped = True
                elif ch == '"':
                    in_str = False
                continue
            if ch == '"':
                in_str = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    return prompt[start:i + 1]
        return None

    @staticmethod
    def _split_question_suffix(prompt: str) -> tuple[str | None, str | None]:
        """Split (shared_prefix, per-question_suffix) at the trailing 'Question:'.

        Returns (None, None) when there is no 'Question:' marker or no
        metrics catalog in the prefix — those calls are never cached.
        """
        idx = prompt.rfind("Question:")
        if idx == -1:
            return None, None
        prefix = prompt[:idx]
        if GeminiProvider._extract_catalog(prefix) is None:
            return None, None
        return prefix, prompt[idx:]

    def _get_or_create_cache(
        self,
        key: str,
        system_prompt: str,
        cached_prefix: str,
        catalog_json: str,
    ) -> str | None:
        """Return a cached-content name for `key`, (re)creating if needed.

        Returns None when below the token threshold or cache creation fails
        (caller then falls back to the uncached path). Never raises.
        """
        est_tokens = _estimate_tokens(system_prompt, catalog_json)
        if est_tokens < GEMINI_CACHE_MIN_TOKENS:
            logger.debug(
                "Gemini cache: prefix below %d tokens (est %d), uncached call",
                GEMINI_CACHE_MIN_TOKENS, est_tokens,
            )
            return None

        now = time.time()
        ttl_seconds = max(1, int(SESSION_TIMEOUT_MINUTES * 60))

        cached = self._cache_handles.get(key)
        if cached is not None:
            name, exp, stored_prefix = cached
            if exp > now and cached_prefix == stored_prefix:
                logger.debug("Gemini cache: hit %s", name)
                return name
            # TTL expired locally, or the shared prefix changed (e.g. a
            # different DataSource with an identical catalog): recreate.
            self._cache_handles.pop(key, None)

        try:
            name = self._cache_helper.create(
                model=self._model_name,
                ttl_seconds=ttl_seconds,
                system_prompt=system_prompt,
                contents=cached_prefix,
            )
            logger.debug(
                "Gemini cache: created %s (est %d tokens, ttl %ds)",
                name, est_tokens, ttl_seconds,
            )
            self._cache_handles[key] = (name, now + ttl_seconds, cached_prefix)
            return name
        except Exception as e:  # noqa: BLE001 — cache is best-effort
            logger.warning(
                "Gemini cache creation failed, falling back to uncached: %s", e
            )
            return None

    def _generate_with_cache(
        self, cache_name: str, suffix: str, temperature: float
    ) -> str:
        """Call generate_content sending only the non-cached question suffix."""
        from google.genai import types
        config = types.GenerateContentConfig(
            temperature=temperature,
            cached_content=cache_name,
            # NOTE: system_instruction is intentionally NOT repeated here —
            # it is already part of the cached content; repeating it would
            # duplicate the system prompt.
        )
        response = self.client.models.generate_content(
            model=self._model_name,
            contents=suffix,
            config=config,
        )
        usage = getattr(response, "usage", None)
        if usage is not None and getattr(usage, "total_cached_tokens", None):
            logger.debug(
                "Gemini cache: %s tokens served from cache %s",
                usage.total_cached_tokens, cache_name,
            )
        return response.text

    def _generate_uncached(
        self, prompt: str, system_prompt: str, temperature: float
    ) -> str:
        from google.genai import types
        config = types.GenerateContentConfig(
            temperature=temperature,
            system_instruction=system_prompt if system_prompt else None,
        )
        response = self.client.models.generate_content(
            model=self._model_name,
            contents=prompt,
            config=config,
        )
        return response.text

    # ── public interface (signature unchanged, always returns str) ─────────

    def generate(self, prompt: str, system_prompt: str = "", temperature: float = 0.1) -> str:
        cached_prefix, suffix = self._split_question_suffix(prompt)

        if cached_prefix is not None and suffix is not None:
            catalog_json = self._extract_catalog(cached_prefix)
            if catalog_json is not None:
                key = self._cache_key(system_prompt, catalog_json)
                cache_name = self._get_or_create_cache(
                    key, system_prompt, cached_prefix, catalog_json
                )
                if cache_name is not None:
                    try:
                        return self._generate_with_cache(cache_name, suffix, temperature)
                    except Exception as e:  # noqa: BLE001
                        if self._is_cache_missing_error(e):
                            # CachedContent expired/gone server-side — recreate
                            # transparently and retry exactly once.
                            logger.debug(
                                "Gemini cache: %s invalid (%s), recreating",
                                cache_name, e,
                            )
                            self._cache_handles.pop(key, None)
                            retry_name = self._get_or_create_cache(
                                key, system_prompt, cached_prefix, catalog_json
                            )
                            if retry_name is not None:
                                try:
                                    return self._generate_with_cache(
                                        retry_name, suffix, temperature
                                    )
                                except Exception as e2:  # noqa: BLE001
                                    if self._is_cache_missing_error(e2):
                                        # Still unavailable — fall back to a
                                        # plain uncached call rather than crash.
                                        logger.warning(
                                            "Gemini cache: retry also invalid (%s), "
                                            "falling back to uncached", e2,
                                        )
                                        return self._generate_uncached(
                                            prompt, system_prompt, temperature
                                        )
                                    raise
                        # Not a cache-missing error: preserve original
                        # behavior and let the caller see the real failure.
                        raise

        # Fallback: full uncached call (identical to pre-caching behavior).
        return self._generate_uncached(prompt, system_prompt, temperature)


class NvidiaProvider(LLMProvider):
    """NVIDIA NIM — OpenAI-compatible /chat/completions endpoint.

    Cloud-hosted catalog (Nemotron/DeepSeek/Qwen etc). Docs:
    https://build.nvidia.com — get an API key there.
    """

    def __init__(
        self,
        api_key: str = NVIDIA_API_KEY,
        base_url: str = NVIDIA_BASE_URL,
        model: str = NVIDIA_MODEL,
    ):
        if not api_key:
            raise ValueError(
                "NVIDIA_API_KEY not set. Export it or switch LLM_PROVIDER to 'ollama'."
            )
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model

    def provider_name(self) -> str:
        return f"nvidia/{self.model}"

    def generate(self, prompt: str, system_prompt: str = "", temperature: float = 0.1) -> str:
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": 400,
            "stream": False,
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        try:
            r = requests.post(
                f"{self.base_url}/chat/completions",
                json=payload,
                headers=headers,
                timeout=300,
            )
            r.raise_for_status()
            return r.json()["choices"][0]["message"]["content"]
        except requests.ConnectionError:
            raise ConnectionError(
                f"Cannot connect to NVIDIA NIM at {self.base_url}."
            )
        except requests.HTTPError as e:
            if e.response is not None and e.response.status_code == 401:
                raise RuntimeError("NVIDIA NIM rejected the API key (401 Unauthorized).")
            raise


def get_provider(provider: str | None = None) -> LLMProvider:
    provider = provider or LLM_PROVIDER
    if provider == "ollama":
        return OllamaProvider()
    elif provider == "gemini":
        return GeminiProvider()
    elif provider == "nvidia":
        return NvidiaProvider()
    else:
        raise ValueError(
            f"Unknown LLM provider: '{provider}'. Use 'ollama', 'gemini', or 'nvidia'."
        )
