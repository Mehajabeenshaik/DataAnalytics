import abc
import json
import requests
from config import (
    LLM_PROVIDER, GEMINI_API_KEY,
    OLLAMA_BASE_URL, OLLAMA_MODEL,
    NVIDIA_API_KEY, NVIDIA_BASE_URL, NVIDIA_MODEL,
)


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

    def generate(self, prompt: str, system_prompt: str = "", temperature: float = 0.1) -> str:
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        try:
            r = requests.post(
                f"{self.base_url}/api/chat",
                json={
                    "model": self.model,
                    "messages": messages,
                    "stream": False,
                    "options": {"temperature": temperature},
                },
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
        from google import genai
        self.client = genai.Client(api_key=api_key)
        self._model_name = model

    def provider_name(self) -> str:
        return f"gemini/{self._model_name}"

    def generate(self, prompt: str, system_prompt: str = "", temperature: float = 0.1) -> str:
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


class NvidiaNimProvider(LLMProvider):
    """NVIDIA NIM / Nemotron provider using the OpenAI-compatible endpoint.

    Uses the OpenAI Python client pointed at NVIDIA's integrate API.
    Requires NVIDIA_API_KEY in the environment.
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
        from openai import OpenAI
        self.client = OpenAI(api_key=api_key, base_url=base_url)
        self._model_name = model

    def provider_name(self) -> str:
        return f"nvidia/{self._model_name}"

    def generate(self, prompt: str, system_prompt: str = "", temperature: float = 0.1) -> str:
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        response = self.client.chat.completions.create(
            model=self._model_name,
            messages=messages,
            temperature=temperature,
            stream=False,
        )
        return response.choices[0].message.content


def get_provider(provider: str | None = None) -> LLMProvider:
    provider = provider or LLM_PROVIDER
    if provider == "ollama":
        return OllamaProvider()
    elif provider == "gemini":
        return GeminiProvider()
    elif provider == "nvidia":
        return NvidiaNimProvider()
    else:
        raise ValueError(f"Unknown LLM provider: '{provider}'. Use 'ollama', 'gemini', or 'nvidia'.")