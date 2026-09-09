import pytest

from bookrag.providers.fake_provider import FakeProvider
from bookrag.providers.ollama_provider import DEFAULT_NUM_CTX, OllamaProvider
from bookrag.providers.registry import get_provider


def test_fake_provider_ignores_a_model_override() -> None:
    provider = get_provider("fake", model="some-model")

    assert isinstance(provider, FakeProvider)


def test_unknown_provider_name_raises() -> None:
    with pytest.raises(ValueError):
        get_provider("not-a-real-provider")


def test_ollama_model_override_is_used(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OLLAMA_MODEL", raising=False)

    provider = get_provider("ollama", model="qwen2.5:7b-instruct")

    assert isinstance(provider, OllamaProvider)
    assert provider._model == "qwen2.5:7b-instruct"


def test_ollama_falls_back_to_env_var_then_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OLLAMA_MODEL", "llama3.1:8b")

    provider = get_provider("ollama")

    assert provider._model == "llama3.1:8b"


def test_ollama_num_ctx_defaults_when_no_env_var(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OLLAMA_NUM_CTX", raising=False)

    provider = OllamaProvider()

    assert provider._num_ctx == DEFAULT_NUM_CTX


def test_ollama_num_ctx_falls_back_to_env_var(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OLLAMA_NUM_CTX", "32768")

    provider = OllamaProvider()

    assert provider._num_ctx == 32768
