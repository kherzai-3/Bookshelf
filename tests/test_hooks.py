"""Covers the context-doc enforcement hooks themselves.

These are bash, not part of the package, and had no coverage at all - which is
how `tests/` stayed detected-but-not-blocked long enough for eleven test
context docs to drift. The rule they implement is a project guarantee, so it
gets a test like any other.

Each test runs the real hook script against a throwaway project root, so
nothing here touches this repo's own `.claude/context_state/dirty.txt`.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

HOOKS = Path(__file__).resolve().parents[1] / ".claude" / "hooks"

pytestmark = pytest.mark.skipif(
    shutil.which("bash") is None, reason="hooks are bash scripts"
)


def run_hook(name: str, payload: dict, root: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", str(HOOKS / name)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        env={"CLAUDE_PROJECT_DIR": str(root).replace("\\", "/"), "PATH": _path()},
    )


def _path() -> str:
    import os

    return os.environ.get("PATH", "")


def track(root: Path, edited: Path) -> list[str]:
    """Run track_dirty.sh for an edit to `edited`; return dirty.txt's lines."""
    result = run_hook(
        "track_dirty.sh",
        {"tool_name": "Edit", "tool_input": {"file_path": str(edited)}},
        root,
    )
    assert result.returncode == 0, result.stderr
    dirty = root / ".claude" / "context_state" / "dirty.txt"
    if not dirty.exists():
        return []
    return [line for line in dirty.read_text(encoding="utf-8").splitlines() if line]


def test_editing_a_test_file_is_tracked(tmp_path: Path) -> None:
    """The whole point of the change: a stale test doc must block the turn it
    was created in, not merely get reported at the next session start."""
    assert track(tmp_path, tmp_path / "tests" / "test_query.py") == ["tests/test_query.py"]


def test_editing_a_source_file_is_tracked(tmp_path: Path) -> None:
    assert track(tmp_path, tmp_path / "src" / "bookrag" / "cli.py") == ["src/bookrag/cli.py"]


def test_editing_pyproject_is_tracked(tmp_path: Path) -> None:
    assert track(tmp_path, tmp_path / "pyproject.toml") == ["pyproject.toml"]


def test_a_non_python_file_under_tests_is_not_tracked(tmp_path: Path) -> None:
    """Fixture data has no context doc, so blocking on it would be a dead end."""
    assert track(tmp_path, tmp_path / "tests" / "fixtures" / "sample.json") == []


def test_a_pycache_artifact_is_not_tracked(tmp_path: Path) -> None:
    artifact = tmp_path / "tests" / "__pycache__" / "test_query.cpython-312.pyc"
    assert track(tmp_path, artifact) == []


def test_a_file_outside_src_and_tests_is_not_tracked(tmp_path: Path) -> None:
    assert track(tmp_path, tmp_path / "README.md") == []


def test_a_file_outside_the_project_is_not_tracked(tmp_path: Path) -> None:
    outside = tmp_path.parent / "somewhere-else" / "src" / "thing.py"
    assert track(tmp_path, outside) == []


def test_the_same_file_is_only_recorded_once(tmp_path: Path) -> None:
    edited = tmp_path / "tests" / "test_query.py"
    track(tmp_path, edited)
    assert track(tmp_path, edited) == ["tests/test_query.py"]


def test_stop_hook_is_silent_when_nothing_is_pending(tmp_path: Path) -> None:
    state = tmp_path / ".claude" / "context_state"
    state.mkdir(parents=True)
    (state / "dirty.txt").write_text("", encoding="utf-8")

    result = run_hook("check_dirty.sh", {}, tmp_path)

    assert result.returncode == 0
    assert result.stdout.strip() == ""


def test_stop_hook_blocks_and_names_a_pending_test_file(tmp_path: Path) -> None:
    state = tmp_path / ".claude" / "context_state"
    state.mkdir(parents=True)
    (state / "dirty.txt").write_text("tests/test_query.py\n", encoding="utf-8")

    result = run_hook("check_dirty.sh", {}, tmp_path)

    decision = json.loads(result.stdout)
    assert decision["decision"] == "block"
    assert "tests/test_query.py" in decision["reason"]


def test_stop_hook_still_emits_valid_json_for_a_crlf_dirty_file(tmp_path: Path) -> None:
    """A CR reaching the reason string makes the JSON unparseable, so the block
    decision is dropped and the hook fails *open* - the one failure mode it must
    not have. Found because Python's text mode writes CRLF on Windows.
    """
    state = tmp_path / ".claude" / "context_state"
    state.mkdir(parents=True)
    (state / "dirty.txt").write_bytes(b"tests/test_query.py\r\n")

    result = run_hook("check_dirty.sh", {}, tmp_path)

    decision = json.loads(result.stdout)  # would raise before the CR strip
    assert decision["decision"] == "block"
    assert "tests/test_query.py" in decision["reason"]
    assert "\r" not in decision["reason"]


def test_stop_hook_asks_for_a_lockfile_review_for_pyproject(tmp_path: Path) -> None:
    """pyproject.toml's follow-up is different in kind - requirements.txt and
    README, not a context doc."""
    state = tmp_path / ".claude" / "context_state"
    state.mkdir(parents=True)
    (state / "dirty.txt").write_text("pyproject.toml\n", encoding="utf-8")

    result = run_hook("check_dirty.sh", {}, tmp_path)

    reason = json.loads(result.stdout)["reason"]
    assert "requirements.txt" in reason
    assert "README.md" in reason


# --------------------------------------------------------------------------
# check_drift.sh - the session-start safety net for edits track_dirty.sh
# never saw. Informational only: it reports, it never blocks.
# --------------------------------------------------------------------------


def sha1_of(text: str) -> str:
    """The hash the convention actually records: CR-stripped, like
    `tr -d '\\r' < <file> | sha1sum`."""
    import hashlib

    return hashlib.sha1(text.encode("utf-8").replace(b"\r", b"")).hexdigest()


def seed(root: Path, relative: str, body: str, *, doc_hash: str | None = "match") -> None:
    """Write a source file and, unless doc_hash is None, its context doc.

    `doc_hash="match"` records the real hash (in sync); any other string is
    recorded verbatim (drifted).
    """
    source = root / relative
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text(body, encoding="utf-8")
    if doc_hash is None:
        return
    doc = root / "context" / (relative + ".md")
    doc.parent.mkdir(parents=True, exist_ok=True)
    recorded = sha1_of(body) if doc_hash == "match" else doc_hash
    doc.write_text(
        f"---\nsource: {relative}\nsource_hash: {recorded}\n---\n\n## Purpose\nx.\n",
        encoding="utf-8",
    )


def drift(root: Path) -> str:
    """Run check_drift.sh; return its additionalContext, or "" when silent."""
    result = run_hook("check_drift.sh", {}, root)
    assert result.returncode == 0, result.stderr
    if not result.stdout.strip():
        return ""
    payload = json.loads(result.stdout)
    return payload["hookSpecificOutput"]["additionalContext"]


def test_drift_hook_is_silent_when_every_doc_matches(tmp_path: Path) -> None:
    seed(tmp_path, "src/bookrag/cli.py", "print('hi')\n")
    seed(tmp_path, "tests/test_cli.py", "def test_x(): pass\n")

    assert drift(tmp_path) == ""


def test_drift_hook_reports_a_source_that_changed_without_its_doc(tmp_path: Path) -> None:
    seed(tmp_path, "src/bookrag/cli.py", "print('new')\n", doc_hash="0" * 40)

    assert "src/bookrag/cli.py" in drift(tmp_path)


def test_drift_hook_reports_a_source_with_no_doc_at_all(tmp_path: Path) -> None:
    seed(tmp_path, "src/bookrag/new_thing.py", "x = 1\n", doc_hash=None)

    assert "src/bookrag/new_thing.py (no context doc)" in drift(tmp_path)


def test_drift_hook_ignores_crlf_so_a_checkout_is_not_reported_as_drift(
    tmp_path: Path,
) -> None:
    """`.gitattributes` stores LF, so a checkout that rewrites a file can leave
    CRLF in the working tree with no content change. Hashing raw bytes reported
    seven such files at once; the CR strip is what makes the check trustworthy.
    """
    body = "print('hi')\n"
    seed(tmp_path, "src/bookrag/cli.py", body)
    (tmp_path / "src" / "bookrag" / "cli.py").write_bytes(body.replace("\n", "\r\n").encode())

    assert drift(tmp_path) == ""


def test_drift_hook_ignores_pycache(tmp_path: Path) -> None:
    """A .pyc can have no context doc, so reporting one buries the real findings."""
    seed(tmp_path, "src/bookrag/cli.py", "print('hi')\n")
    cache = tmp_path / "src" / "bookrag" / "__pycache__"
    cache.mkdir(parents=True)
    (cache / "cli.cpython-312.pyc").write_bytes(b"\x00\x01")

    assert drift(tmp_path) == ""


def test_drift_hook_covers_install_py(tmp_path: Path) -> None:
    """install.py sits outside src/ and tests/ and is deliberately not tracked by
    track_dirty.sh, so this hook is the *only* thing watching it. It matters
    because install.py re-implements this hook's own check for contributors not
    running Claude Code, and hand-copies values from pyproject.toml."""
    seed(tmp_path, "install.py", "print('installer')\n", doc_hash="0" * 40)

    assert "install.py" in drift(tmp_path)


def test_drift_hook_does_not_sweep_other_root_files(tmp_path: Path) -> None:
    """Only a named list, never a root-level scan - the repo root is where
    throwaway scripts land, and each would otherwise be reported as missing a
    doc, which is the noise the __pycache__ exclusion already had to fix once."""
    seed(tmp_path, "src/bookrag/cli.py", "print('hi')\n")
    (tmp_path / "scratch.py").write_text("temp = 1\n", encoding="utf-8")
    (tmp_path / "conftest.py").write_text("temp = 2\n", encoding="utf-8")

    assert drift(tmp_path) == ""
