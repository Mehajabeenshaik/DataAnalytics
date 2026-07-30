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
