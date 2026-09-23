"""Shared types every provider (Claude, a local Ollama model, the test
fake) implements against - both the extraction pipeline and the chat REPL
go through this Protocol."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass
class ExtractedFact:
    entity_name: str
    entity_type: str  # fiction: "character"|"setting"|"theme"; nonfiction: "character"|"concept"|"theme"
    category: str
    statement: str
    # Where the fact sits in *story* time, as opposed to the chapter that
    # revealed it. "present" (the chapter's own narrative moment), "past"
    # (recounted backstory, possibly predating the book entirely), "future"
    # (anticipated or planned). Defaults to "present" because that is what
    # the large majority of facts are, and because every fact extracted
    # before this field existed is one.
    when: str = "present"
    # The text's own words for when it happened ("fifteen years ago", "the
    # next morning"), copied verbatim when the chapter states one. Displayed
    # to the reader, never parsed - see parsing.py's context doc.
    time_phrase: str | None = None


class ExtractionParseError(Exception):
    """Raised when a provider's raw output can't be parsed into facts -
    caught by eval.py to score schema-conformance rather than crashing."""


def extraction_identity(provider: object) -> str | None:
    """Which provider+model produced a set of facts, e.g.
    "ollama:qwen2.5:7b-instruct" - recorded in extraction_progress.json so a
    resumed run can refuse to continue someone else's work with a different
    model (see pipeline.ExtractionResumeMismatch).

    Deliberately a free function probing an *optional* method rather than a
    required member of the Provider protocol below. Providers are matched
    structurally, and the test suite passes many minimal stand-ins that
    implement extract_facts and nothing else; making this mandatory would
    break them all to serve a bookkeeping concern. Returns None when the
    provider doesn't offer one, which callers must read as "unknown, so
    unverifiable" - never as "a different model".
    """
    describe = getattr(provider, "extraction_identity", None)
    if not callable(describe):
        return None
    try:
        identity = describe()
    except Exception:  # noqa: BLE001 - see below
        # An identity probe exists only to label a run; it must never be the
        # thing that takes one down. A provider whose identity raises is
        # treated exactly like one that has no identity at all.
        return None
    return str(identity) if identity else None


@dataclass(frozen=True)
class CallUsage:
    """What one provider call actually cost.

    `prompt_tokens` is the whole prompt the model was given; `prompt_seconds`
    is how long evaluating it really took, and the two come apart badly. Ollama
    reuses a cached KV prefix when consecutive requests share one, and it still
    reports the full token count while charging almost no time - measured here,
    an identical 1,439-token system prompt took 34.23s on the first call and
    0.12s on the second. Anything reasoning about cost from the token count
    alone will therefore be wrong, which is exactly the mistake this type
    exists to stop: `prompt_seconds` is the honest number.

    All fields are optional because not every provider can report them.
    """

    prompt_tokens: int | None = None
    output_tokens: int | None = None
    prompt_seconds: float | None = None
    total_seconds: float | None = None


def last_usage(provider: object) -> CallUsage | None:
    """What the provider's most recent call cost, if it tracks that.

    Same optional-capability shape as `extraction_identity` and
    `model_placement` above, and for the same reasons - the Protocol stays
    small, the many minimal test stand-ins keep working, and a diagnostic can
    never be the thing that breaks a run.
    """
    usage = getattr(provider, "last_usage", None)
    if callable(usage):
        try:
            usage = usage()
        except Exception:  # noqa: BLE001 - diagnostics must never break a run
            return None
    return usage if isinstance(usage, CallUsage) else None


def narrow_context_window(provider: object, window: int) -> int | None:
    """Ask a provider to use a smaller context window for this run, returning
    the window actually adopted (None if the provider has no such setting).

    Only ever narrows: a provider whose window is already at or below `window`
    is left alone, so a user who deliberately set a small `$OLLAMA_EXTRACT_NUM_CTX`
    never has it silently raised by a book that would like more room.

    Same optional-capability shape as the probes above - a hosted provider has
    no local window to size, and the test suite's minimal stand-ins must not
    have to grow one.
    """
    current = getattr(provider, "extract_num_ctx", None)
    if not isinstance(current, int):
        return None
    if window < current:
        provider.extract_num_ctx = window
        return window
    return current


@dataclass(frozen=True)
class ModelPlacement:
    """How much of a loaded model is resident on the GPU.

    `vram_bytes` is what the runtime reports as GPU-resident; the remainder of
    `size_bytes` is running on CPU. Partial offload is not proportionally fast:
    the CPU-resident layers gate every token, so "70% on GPU" is far closer to
    CPU speed than to GPU speed.
    """

    model: str
    size_bytes: int
    vram_bytes: int

    @property
    def gpu_fraction(self) -> float:
        if self.size_bytes <= 0:
            return 0.0
        return max(0.0, min(1.0, self.vram_bytes / self.size_bytes))

    @property
    def is_cpu_only(self) -> bool:
        return self.vram_bytes <= 0

    @property
    def is_fully_on_gpu(self) -> bool:
        # Not == 1.0: runtimes report a little non-layer overhead outside VRAM,
        # so an effectively-full offload lands a shade under.
        return self.gpu_fraction >= 0.99


def model_placement(provider: object) -> ModelPlacement | None:
    """Whether the provider's model is running on GPU or CPU, if it can say.

    Same optional-capability shape as extraction_identity() above, and for the
    same reason: this is diagnostics, so it must never be the thing that takes
    a run down, and the many minimal test stand-ins must not have to implement
    it. None means "can't tell" - a hosted provider has no local placement to
    report, and a local one can't answer before the model is loaded.
    """
    describe = getattr(provider, "model_placement", None)
    if not callable(describe):
        return None
    try:
        placement = describe()
    except Exception:  # noqa: BLE001 - diagnostics must never break a run
        return None
    return placement if isinstance(placement, ModelPlacement) else None


class Provider(Protocol):
    def extract_facts(
        self,
        chapter_text: str,
        known_entities: list[str],
        content_type: str = "fiction",
        known_entity_types: dict[str, str] | None = None,
    ) -> list[ExtractedFact]: ...

    def answer_question(self, question: str, context: str, content_type: str = "fiction") -> str: ...

    # Optional, intentionally not declared here: extraction_identity() ->
    # str, and model_placement() -> ModelPlacement. Read them through the
    # module-level functions above, which tolerate their absence.
