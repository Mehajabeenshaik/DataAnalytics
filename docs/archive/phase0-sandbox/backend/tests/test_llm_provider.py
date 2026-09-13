import os
import pytest
from unittest import mock

from backend.app.llm_provider import OllamaProvider, get_llm_provider

# Mock the requests library used inside OllamaProvider
@pytest.fixture(autouse=True)
def mock_requests(monkeypatch):
    class MockResponse:
        def __init__(self, status_code=200, json_data=None):
            self.status_code = status_code
            self._json = json_data or {}
        def raise_for_status(self):
            if self.status_code >= 400:
                raise Exception("HTTP error")
        def json(self):
            return self._json
    # mock get to simulate Ollama server alive
    monkeypatch.setattr('requests.get', lambda url, timeout: MockResponse(200))
    # mock post to return a fixed response
    def mock_post(url, json, timeout):
        return MockResponse(200, {"message": {"content": "mocked reply"}})
    monkeypatch.setattr('requests.post', mock_post)

def test_ollama_provider_instantiation():
    provider = OllamaProvider()
    assert provider.provider_name().startswith('ollama/')

def test_ollama_generate(monkeypatch):
    provider = OllamaProvider()
    reply = provider.generate("test prompt")
    assert reply == "mocked reply"

def test_get_llm_provider_factory(monkeypatch):
    # Ensure env var is set to ollama (default)
    provider = get_llm_provider()
    assert isinstance(provider, OllamaProvider)
