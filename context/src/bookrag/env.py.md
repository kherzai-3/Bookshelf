---
source: src/bookrag/env.py
last_synced: 2026-09-13T20:30:00Z
source_hash: a77c5c73a70dd1dda501b6c097c7d06c1e6a59d1
---

## Purpose
The single place configuration is read from the environment (and, via
`python-dotenv`, from `.env`). It exists to enforce one rule everywhere: a
variable that is set but empty counts as **unset**, not as an override to the
empty string. Without that rule, following the project's own documented setup
instructions breaks the tool.

## Public Interface
- `env_str(name, default=None) -> str | None` — value of `name`, stripped;
  `default` if unset, empty, or whitespace-only.
- `env_int(name, default) -> int` — same, parsed as an integer; a non-numeric
  value raises a `ValueError` naming both the variable and the bad value.
- `env_optional_int(name) -> int | None` — an integer setting with no default
  worth inventing. `OLLAMA_NUM_GPU` is the case it exists for: absent means
  "let Ollama decide how many layers fit", a judgement the runtime makes from
  actual free VRAM at load time, which this process cannot see. Returning a
  number here would silently override it.

## Key Decisions
- **Blank means unset.** `.env.example` ships a blank line for every optional
  setting (`OLLAMA_NUM_CTX=`), README tells the user to fill in only what they
  need, and `providers/__init__.py` calls `load_dotenv()` at import time. So
  the documented path puts `""` into `os.environ` for every setting left
  alone, and `os.environ.get(name, default)` returns that `""` — the variable
  really is present. Concretely this made `int(os.environ.get("OLLAMA_NUM_CTX",
  16384))` evaluate `int("")` and raise on *every* Ollama call, and would have
  sent requests with an empty model name even after that crash was fixed.
- **Found by the installer, not by the test suite.** `install.py` creates the
  `.env` README asks for; running the suite inside the venv it produced failed
  7 tests that pass in a developer checkout. A blank config line is the most
  likely thing a new user's environment has and the least likely thing a
  developer's has, which is why it survived this long. The regression test
  (`tests/test_env.py`) reads `.env.example` itself, so it keeps covering new
  settings as they are added rather than freezing today's list.
- **Whitespace is stripped**, so a stray trailing space in a `.env` line can't
  become part of a model name or a URL.
- **`env_int` names the variable in its error.** `int()`'s own "invalid
  literal for int() with base 10: 'lots'" says nothing about which setting is
  wrong or that `.env` was even consulted.
- Deliberately a top-level module, not part of `providers/`: `storage.py` also
  reads env vars, and storage must not depend on the providers package.

## Dependencies
- Internal: none (imported by `storage.py`, `providers/registry.py`,
  `providers/ollama_provider.py`, `providers/anthropic_provider.py`).
- External: none — stdlib `os` only. `python-dotenv` populates `os.environ`
  beforehand but is not imported here.

## Open Questions / TODOs
- Nothing outstanding. If a future setting needs a boolean, it wants an
  `env_bool` here (with an explicit truthy-value list) rather than an ad-hoc
  comparison at the call site.
