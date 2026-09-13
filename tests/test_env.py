"""Environment/`.env` reading, including the blank-value case that the
documented setup path actually produces."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from bookrag.env import env_int, env_str
from bookrag.providers.ollama_provider import (
    DEFAULT_ANSWER_MODEL,
    DEFAULT_BASE_URL,
    DEFAULT_MODEL,
    DEFAULT_NUM_CTX,
    OllamaProvider,
)
from bookrag.providers.registry import DEFAULT_PROVIDER, get_provider

ENV_EXAMPLE = Path(__file__).resolve().parents[1] / ".env.example"


def test_env_str_returns_the_default_when_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("BOOKRAG_TEST_VALUE", raising=False)

    assert env_str("BOOKRAG_TEST_VALUE", "fallback") == "fallback"


def test_env_str_returns_the_value_when_set(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BOOKRAG_TEST_VALUE", "real")

    assert env_str("BOOKRAG_TEST_VALUE", "fallback") == "real"


def test_a_blank_env_var_counts_as_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    """`.env.example` ships `OLLAMA_MODEL=` and friends, so a user who fills in
    only what they need leaves the rest present-but-empty."""
    monkeypatch.setenv("BOOKRAG_TEST_VALUE", "")

    assert env_str("BOOKRAG_TEST_VALUE", "fallback") == "fallback"


def test_a_whitespace_only_env_var_counts_as_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BOOKRAG_TEST_VALUE", "   ")

    assert env_str("BOOKRAG_TEST_VALUE", "fallback") == "fallback"


def test_env_str_strips_surrounding_whitespace(monkeypatch: pytest.MonkeyPatch) -> None:
    """A trailing space in a .env line must not become part of a model name."""
    monkeypatch.setenv("BOOKRAG_TEST_VALUE", "  real  ")

    assert env_str("BOOKRAG_TEST_VALUE", "fallback") == "real"


def test_env_str_defaults_to_none(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BOOKRAG_TEST_VALUE", "")

    assert env_str("BOOKRAG_TEST_VALUE") is None


def test_env_int_parses_a_real_value(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BOOKRAG_TEST_NUMBER", "32768")

    assert env_int("BOOKRAG_TEST_NUMBER", 16384) == 32768


def test_a_blank_int_env_var_falls_back_instead_of_crashing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The exact crash a freshly-installed .env caused: int("")."""
    monkeypatch.setenv("BOOKRAG_TEST_NUMBER", "")

    assert env_int("BOOKRAG_TEST_NUMBER", 16384) == 16384


def test_a_non_numeric_int_env_var_names_the_variable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("BOOKRAG_TEST_NUMBER", "lots")

    with pytest.raises(ValueError) as error:
        env_int("BOOKRAG_TEST_NUMBER", 16384)

    message = str(error.value)
    assert "BOOKRAG_TEST_NUMBER" in message
    assert "lots" in message


def blank_settings_in_env_example() -> list[str]:
    """Every `SOME_VAR=` line in .env.example - i.e. every setting a user is
    invited to leave alone."""
    names = []
    for line in ENV_EXAMPLE.read_text(encoding="utf-8").splitlines():
        match = re.match(r"^([A-Z][A-Z0-9_]*)=\s*$", line)
        if match:
            names.append(match.group(1))
    return names


def test_env_example_declares_blank_settings() -> None:
    """Guards the test below from silently passing on an empty list if
    .env.example's format ever changes."""
    assert len(blank_settings_in_env_example()) >= 5


def test_the_documented_setup_path_leaves_every_default_intact(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Copying .env.example to .env verbatim - what README says to do and what
    install.py does - must not change any default.

    This is the regression test for the real failure: `load_dotenv()` runs at
    import time in providers/__init__.py, so those blank lines become empty
    strings in os.environ, and a naive `os.environ.get(name, default)` returns
    the empty string rather than the default. It killed every Ollama call with
    `int("")` and would have sent requests with an empty model name.
    """
    for name in blank_settings_in_env_example():
        monkeypatch.setenv(name, "")

    provider = OllamaProvider()

    assert provider._model == DEFAULT_MODEL
    assert provider._answer_model == DEFAULT_ANSWER_MODEL
    assert provider._base_url == DEFAULT_BASE_URL
    assert provider._num_ctx == DEFAULT_NUM_CTX
    assert isinstance(get_provider(), OllamaProvider)


def test_a_blank_provider_env_var_falls_back_to_the_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("BOOKRAG_PROVIDER", "")

    assert DEFAULT_PROVIDER == "ollama"
    assert isinstance(get_provider(), OllamaProvider)
