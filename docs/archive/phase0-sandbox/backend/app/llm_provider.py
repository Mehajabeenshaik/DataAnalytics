"""
LLM provider abstraction — Phase 0 & Phase 1.

The model is an untrusted component. This module only provides a clean
interface for text generation. No planning, no tool calling, and certainly
no SQL/Python execution belongs here.
"""

from __future__ import annotations

import abc
import json
import logging
from typing import Iterator

import requests

from .config import (
    LLM_PROVIDER,
    OLLAMA_BASE_URL,
    OLLAMA_MODEL,
)

logger = logging.getLogger("daana.llm")


class LLMProvider(abc.ABC):
    @abc.abstractmethod
    def generate(
        self, prompt: str, system_prompt: str = "", temperature: float = 0.1
    ) -> str:
        """Generate a completion. Low temperature is the system default."""
        ...

    def generate_stream(
        self, prompt: str, system_prompt: str = "", temperature: float = 0.1
    ) -> Iterator[str]:
        """Default: yield the full response as a single chunk."""
        yield self.generate(prompt, system_prompt=system_prompt, temperature=temperature)

    @abc.abstractmethod
    def provider_name(self) -> str:
        ...


class OllamaProvider(LLMProvider):
    def __init__(
        self,
        base_url: str = OLLAMA_BASE_URL,
        model: str = OLLAMA_MODEL,
        keep_alive: float | int = -1,
    ):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.keep_alive = keep_alive

    def provider_name(self) -> str:
        return f"ollama/{self.model}"

    def is_available(self) -> bool:
        try:
            r = requests.get(f"{self.base_url}/", timeout=2)
            return r.status_code == 200
        except Exception:
            return False

    def _payload(
        self, prompt: str, system_prompt: str, temperature: float, stream: bool
    ) -> dict:
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})
        return {
            "model": self.model,
            "messages": messages,
            "stream": stream,
            "options": {
                "temperature": temperature,
                "num_predict": 512,
                "num_ctx": 2048,
            },
            "keep_alive": self.keep_alive,
        }

    def generate(
        self, prompt: str, system_prompt: str = "", temperature: float = 0.1
    ) -> str:
        if not self.is_available():
            raise RuntimeError(
                f"Ollama is not reachable at {self.base_url}. "
                "Start it with `ollama serve` and pull the model."
            )
        payload = self._payload(prompt, system_prompt, temperature, stream=False)
        try:
            r = requests.post(
                f"{self.base_url}/api/chat", json=payload, timeout=120
            )
            r.raise_for_status()
            data = r.json()
            return data.get("message", {}).get("content", "")
        except requests.RequestException as exc:
            logger.exception("Ollama generate failed")
            raise RuntimeError(f"Ollama request failed: {exc}") from exc


class MockLLMProvider(LLMProvider):
    """Deterministic fallback mock provider for testing/offline execution."""

    def provider_name(self) -> str:
        return "mock/deterministic"

    def generate(
        self, prompt: str, system_prompt: str = "", temperature: float = 0.1
    ) -> str:
        # Planner prompt detection
        if "STRICT JSON plan" in prompt or "Catalog" in prompt:
            if "total revenue" in prompt.lower() or "revenue" in prompt.lower():
                return json.dumps({"plan_type": "single_metric", "metric_name": "total_revenue"})
            return json.dumps({"plan_type": "single_metric", "metric_name": "total_revenue"})
        # Synthesizer prompt detection
        if "Produce a JSON response" in prompt or "Tool result:" in prompt:
            return json.dumps({
                "answer": "The total revenue across all regions is 5700.",
                "confidence": "high",
                "lineage": ["total_revenue"],
                "caveats": [],
            })
        return json.dumps({"plan_type": "single_metric", "metric_name": "total_revenue"})


def get_llm_provider() -> LLMProvider:
    """Factory — returns configured LLM provider or fallback mock if unavailable."""
    if LLM_PROVIDER == "mock":
        return MockLLMProvider()
    elif LLM_PROVIDER == "ollama":
        provider = OllamaProvider()
        if provider.is_available():
            return provider
        return MockLLMProvider()
    return MockLLMProvider()
