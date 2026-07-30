import abc
import json
import requests
from config import (
    LLM_PROVIDER, GEMINI_API_KEY,
    OLLAMA_BASE_URL, OLLAMA_MODEL,
)


class LLMProvider(abc.ABC):
    @abc.abstractmethod
    def generate(self, prompt: str, system_prompt: str = "") -> str:
        ...

    @abc.abstractmethod
    def provider_name(self) -> str:
        ...


class OllamaProvider(LLMProvider):
    def __init__(self, base_url: str = OLLAMA_BASE_URL, model: str = OLLAMA_MODEL):
        self.base_url = base_url.rstrip("/")
        self.model = model

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

    def generate(self, prompt: str, system_prompt: str = "") -> str:
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        try:
            r = requests.post(
                f"{self.base_url}/api/chat",
                json={"model": self.model, "messages": messages, "stream": False},
                timeout=120,
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


class GeminiProvider(LLMProvider):
    def __init__(self, api_key: str = GEMINI_API_KEY, model: str = "gemini-2.0-flash"):
        if not api_key:
            raise ValueError(
                "GEMINI_API_KEY not set. Export it or switch LLM_PROVIDER to 'ollama'."
            )
        import google.generativeai as genai
        genai.configure(api_key=api_key)
        self.model = genai.GenerativeModel(
            model_name=model,
            system_instruction=None,
        )
        self._model_name = model

    def provider_name(self) -> str:
        return f"gemini/{self._model_name}"

    def generate(self, prompt: str, system_prompt: str = "") -> str:
        full_prompt = f"{system_prompt}\n\n{prompt}" if system_prompt else prompt
        response = self.model.generate_content(full_prompt)
        return response.text


def get_provider(provider: str | None = None) -> LLMProvider:
    provider = provider or LLM_PROVIDER
    if provider == "ollama":
        return OllamaProvider()
    elif provider == "gemini":
        return GeminiProvider()
    else:
        raise ValueError(f"Unknown LLM provider: '{provider}'. Use 'ollama' or 'gemini'.")
