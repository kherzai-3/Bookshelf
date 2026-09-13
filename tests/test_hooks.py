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
