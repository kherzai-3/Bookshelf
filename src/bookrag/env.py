"""Reading configuration from the environment - and, via `python-dotenv`,
from `.env`.

One rule, applied at every read site: **a variable set to an empty or
whitespace-only value counts as unset**, not as an override to the empty
string.

That rule exists because of a real failure, not as a nicety. `.env.example`
ships a blank line for every optional setting (`OLLAMA_NUM_CTX=`), README
tells you to copy it to `.env` and fill in only what you actually need, and
`providers/__init__.py` calls `load_dotenv()` at import time - so the
*documented* setup path puts an empty string into the environment for every
setting the user sensibly left alone. Read naively, `os.environ.get(name,
default)` returns that empty string rather than the default, because the
variable is genuinely present. The consequences were:

- `int(os.environ.get("OLLAMA_NUM_CTX", 16384))` became `int("")` - a
  `ValueError` on every single Ollama call, i.e. the whole tool dead.
- every model name silently became `""`, so even after fixing the crash the
  requests would have gone out with no model.

This was found by running `install.py` against a clean checkout and then
running the test suite in the venv it produced: 7 tests failed that pass in a
developer checkout, purely because the installer had created the `.env` the
README asks for. A blank line in a config file is the most likely thing a new
user's environment will have and the least likely thing a developer's will,
which is exactly why it survived this long.
"""

from __future__ import annotations

import os


def env_str(name: str, default: str | None = None) -> str | None:
    """The value of `name`, or `default` if it is unset or blank.

    Surrounding whitespace is stripped, so a stray trailing space in a `.env`
    line can't become part of a model name or URL.
    """
    value = os.environ.get(name)
    if value is None:
        return default
    value = value.strip()
    return value or default


def env_int(name: str, default: int) -> int:
    """The integer value of `name`, or `default` if it is unset or blank.

    A non-numeric value raises naming the variable and its offending value -
    `int()`'s own "invalid literal for int() with base 10: 'lots'" says
    nothing about *which* setting is wrong or where it was read from.
    """
    raw = env_str(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        raise ValueError(
            f"{name} must be a whole number, got {raw!r} "
            f"(checked the environment and .env)"
        ) from None
