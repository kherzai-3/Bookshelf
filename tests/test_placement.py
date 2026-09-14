"""GPU/CPU placement reporting.

A silently CPU-bound run is the expensive failure this exists to prevent: it
looks exactly like a fast one until several hours have passed. bookrag never
chooses GPU or CPU - Ollama does, when it loads the model - so everything here
is about *reporting* that choice accurately.

The partial-offload case cannot be reproduced on the machine this was written
on (its integrated Radeon 840M is unsupported by Ollama, so real placement is
always 0% GPU), which is exactly why it is pinned with a stubbed server
response rather than left to a live check.
"""

from __future__ import annotations

import json
import io
from pathlib import Path

import pytest

from bookrag.cli import placement_notes
from bookrag.providers.base import ModelPlacement, model_placement
from bookrag.providers.ollama_provider import OllamaProvider


def placement(size: int, vram: int, model: str = "qwen2.5:7b-instruct") -> ModelPlacement:
    return ModelPlacement(model=model, size_bytes=size, vram_bytes=vram)


# --- ModelPlacement arithmetic -------------------------------------------


def test_a_model_wholly_in_vram_is_fully_on_gpu() -> None:
    assert placement(6_000_000_000, 6_000_000_000).is_fully_on_gpu
    assert not placement(6_000_000_000, 6_000_000_000).is_cpu_only


def test_a_model_with_no_vram_is_cpu_only() -> None:
    """Real, measured shape of this project's own machine."""
    resident = placement(5_062_566_870, 0)

    assert resident.is_cpu_only
    assert not resident.is_fully_on_gpu
    assert resident.gpu_fraction == 0.0


def test_a_split_model_is_neither_cpu_only_nor_fully_on_gpu() -> None:
    """The reported real case: `ollama ps` showing 30%/70% CPU/GPU."""
    resident = placement(10_000_000_000, 7_000_000_000)

    assert not resident.is_cpu_only
    assert not resident.is_fully_on_gpu
    assert resident.gpu_fraction == pytest.approx(0.7)


def test_an_almost_complete_offload_counts_as_full() -> None:
    """Runtimes report a little non-layer overhead outside VRAM, so an
    effectively-complete offload lands a shade under 1.0. Reporting that as a
    problem would cry wolf on the good case."""
    assert placement(6_000_000_000, 5_970_000_000).is_fully_on_gpu


def test_a_zero_sized_model_does_not_divide_by_zero() -> None:
    assert placement(0, 0).gpu_fraction == 0.0


# --- the optional-capability probe ---------------------------------------


def test_a_provider_without_the_capability_reports_nothing() -> None:
    """Most test doubles implement extract_facts and nothing else; requiring
    this would break them all for a diagnostic."""

    class Bare:
        pass

    assert model_placement(Bare()) is None


def test_a_capability_that_raises_is_treated_as_unknown() -> None:
    """Diagnostics must never be the thing that takes a run down."""

    class Exploding:
        def model_placement(self):
            raise RuntimeError("ollama went away")

    assert model_placement(Exploding()) is None


def test_a_capability_returning_the_wrong_type_is_ignored() -> None:
    class Confused:
        def model_placement(self):
            return {"size": 1, "vram": 1}

    assert model_placement(Confused()) is None


# --- OllamaProvider reading /api/ps --------------------------------------


def fake_ps(monkeypatch: pytest.MonkeyPatch, payload: dict | None, *, boom: bool = False) -> None:
    import urllib.request

    def fake_urlopen(request, timeout=None):
        if boom:
            raise OSError("connection refused")

        class Response(io.BytesIO):
            def __enter__(self):
                return self

            def __exit__(self, *exc):
                self.close()

        return Response(json.dumps(payload).encode("utf-8"))

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)


def test_ollama_reports_placement_for_the_loaded_model(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_ps(monkeypatch, {"models": [
        {"name": "qwen2.5:7b-instruct", "size": 10_000_000_000, "size_vram": 7_000_000_000},
    ]})

    resident = OllamaProvider(model="qwen2.5:7b-instruct").model_placement()

    assert resident is not None
    assert resident.gpu_fraction == pytest.approx(0.7)


def test_ollama_reports_nothing_when_no_model_is_loaded(monkeypatch: pytest.MonkeyPatch) -> None:
    """/api/ps lists only what is loaded right now, so this is the normal
    answer before the first real call - not an error."""
    fake_ps(monkeypatch, {"models": []})

    assert OllamaProvider(model="qwen2.5:7b-instruct").model_placement() is None


def test_ollama_ignores_a_different_model(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_ps(monkeypatch, {"models": [
        {"name": "llama3.2:3b", "size": 2_000_000_000, "size_vram": 2_000_000_000},
    ]})

    assert OllamaProvider(model="qwen2.5:7b-instruct").model_placement() is None


def test_ollama_tolerates_an_unreachable_server(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_ps(monkeypatch, None, boom=True)

    assert OllamaProvider(model="qwen2.5:7b-instruct").model_placement() is None


def test_ollama_tolerates_a_payload_missing_the_size_fields(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_ps(monkeypatch, {"models": [{"name": "qwen2.5:7b-instruct"}]})

    assert OllamaProvider(model="qwen2.5:7b-instruct").model_placement() is None


# --- what the user actually reads ----------------------------------------


class Stub:
    def __init__(self, resident: ModelPlacement | None) -> None:
        self._resident = resident

    def model_placement(self) -> ModelPlacement | None:
        return self._resident


def test_a_cpu_only_run_says_so_plainly() -> None:
    notes = "\n".join(placement_notes(Stub(placement(5_000_000_000, 0))))

    assert "CPU only" in notes
    assert "hours" in notes
    assert "OLLAMA_BASE_URL" in notes


def test_a_partial_offload_reports_the_percentage_and_why_it_matters() -> None:
    notes = "\n".join(placement_notes(Stub(placement(10_000_000_000, 7_000_000_000))))

    assert "70%" in notes
    # The non-obvious half: 70% on GPU is not 70% of GPU speed.
    assert "gate every token" in notes
    assert "OLLAMA_NUM_CTX" in notes


def test_a_full_offload_says_one_reassuring_line_and_no_warning() -> None:
    notes = placement_notes(Stub(placement(6_000_000_000, 6_000_000_000)))

    assert len(notes) == 1
    assert "fully on the GPU" in notes[0]
    assert "NOTE" not in notes[0]


def test_nothing_is_printed_when_placement_cannot_be_determined() -> None:
    """A hosted provider has no local placement, and neither does a local one
    before its model is loaded. Silence beats a misleading guess."""
    assert placement_notes(Stub(None)) == []
    assert placement_notes(object()) == []


# --- forcing layer placement with num_gpu --------------------------------


def sent_options(monkeypatch: pytest.MonkeyPatch, provider: OllamaProvider) -> dict:
    """The `options` dict the provider actually POSTs to Ollama."""
    import urllib.request

    captured: dict = {}

    def fake_urlopen(request, timeout=None):
        captured.update(json.loads(request.data.decode("utf-8")))

        class Response(io.BytesIO):
            def __enter__(self):
                return self

            def __exit__(self, *exc):
                self.close()

        return Response(json.dumps({"message": {"content": "answer"}}).encode("utf-8"))

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    provider.answer_question("q", "context")
    return captured["options"]


def test_num_gpu_is_omitted_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ollama decides how many layers fit using free VRAM at load time, which
    this process cannot see. Sending a number by default would replace a
    better-informed decision with a worse one."""
    monkeypatch.delenv("OLLAMA_NUM_GPU", raising=False)

    assert "num_gpu" not in sent_options(monkeypatch, OllamaProvider())


def test_num_gpu_is_sent_when_the_env_var_asks_for_it(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OLLAMA_NUM_GPU", "28")

    assert sent_options(monkeypatch, OllamaProvider())["num_gpu"] == 28


def test_a_blank_num_gpu_env_var_still_means_let_ollama_decide(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`.env.example` ships it blank, same as every other optional setting."""
    monkeypatch.setenv("OLLAMA_NUM_GPU", "")

    assert "num_gpu" not in sent_options(monkeypatch, OllamaProvider())


def test_an_explicit_num_gpu_argument_beats_the_env_var(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OLLAMA_NUM_GPU", "10")

    assert sent_options(monkeypatch, OllamaProvider(num_gpu=28))["num_gpu"] == 28


def test_num_gpu_zero_is_honoured_not_treated_as_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    """0 means "no layers on the GPU" - a legitimate way to force CPU, and the
    value most easily lost to a falsy check."""
    monkeypatch.setenv("OLLAMA_NUM_GPU", "0")

    assert sent_options(monkeypatch, OllamaProvider())["num_gpu"] == 0


def test_a_non_numeric_num_gpu_names_the_variable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OLLAMA_NUM_GPU", "all")

    with pytest.raises(ValueError) as error:
        OllamaProvider()

    assert "OLLAMA_NUM_GPU" in str(error.value)
