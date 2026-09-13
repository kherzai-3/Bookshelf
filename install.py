#!/usr/bin/env python3
"""One-step installer for Book_RAG.

    git clone https://github.com/kherzai-3/Bookshelf.git Book_RAG
    cd Book_RAG
    python install.py          # Windows
    python3 install.py         # macOS/Linux

Creates .venv, installs pinned dependencies, installs bookrag itself in
editable mode, seeds .env and the data/ directories, then reports on the
optional Ollama runtime. Safe to re-run: every step is idempotent, so this
doubles as the "pull latest and re-install" command.

Two deliberate constraints on this file, both grounded in things that have
actually bitten this project:

1. It is written in Python-3.6-compatible *syntax* even though the project
   requires 3.11+. A too-old interpreter must fail with the readable version
   message below, not a SyntaxError from a construct it cannot parse. That is
   why there are no annotations, no walrus, and no f-string quote nesting
   here - deliberately, not by oversight.
2. Output is pure ASCII. A Windows cp1252 console mangles non-ASCII (this is
   a known, documented defect in bookrag's own chat output), and an installer
   that prints mojibake on its first line looks broken before it starts.

It never installs Ollama and never installs Python - both are out of scope
for a script that needs one of them to already be running to execute at all.
"""

import argparse
import json
import os
import shutil
import subprocess
import sys

MIN_PYTHON = (3, 11)

# Only a fallback. The real value is read out of the freshly-installed
# package at check time (see default_model()) so this script cannot drift
# from providers/ollama_provider.py. It is still needed as a literal because
# argparse builds its help text before anything is installed.
DEFAULT_OLLAMA_MODEL = "qwen2.5:7b-instruct"
DEFAULT_OLLAMA_BASE_URL = "http://localhost:11434"

ROOT = os.path.dirname(os.path.abspath(__file__))
VENV = os.path.join(ROOT, ".venv")

# Collected as we go and reprinted at the end, so a warning from step 2 is
# not lost in the scrollback of a long pip install.
WARNINGS = []


# --------------------------------------------------------------------------
# output helpers
# --------------------------------------------------------------------------

def step(message):
    print("\n==> " + message)


def ok(message):
    print("    ok: " + message)


def note(message):
    print("    " + message)


def warn(message):
    WARNINGS.append(message)
    print("    !! " + message)


def fail(message):
    print("\nERROR: " + message, file=sys.stderr)
    sys.exit(1)


# --------------------------------------------------------------------------
# environment checks
# --------------------------------------------------------------------------

def check_python():
    step("Checking Python")
    if sys.version_info < MIN_PYTHON:
        running = ".".join(str(p) for p in sys.version_info[:3])
        needed = ".".join(str(p) for p in MIN_PYTHON)
        fail(
            "Book_RAG needs Python %s or newer; this is Python %s\n"
            "  (%s)\n\n"
            "Install a newer Python from https://www.python.org/downloads/\n"
            "then re-run this script with it explicitly, e.g.\n"
            "  py -3.12 install.py        (Windows)\n"
            "  python3.12 install.py      (macOS/Linux)"
            % (needed, running, sys.executable)
        )
    ok("Python %s at %s" % (
        ".".join(str(p) for p in sys.version_info[:3]), sys.executable))


def check_repo_root():
    step("Checking project layout")
    pyproject = os.path.join(ROOT, "pyproject.toml")
    if not os.path.isfile(pyproject):
        fail(
            "no pyproject.toml next to this script (looked in %s).\n"
            "Run install.py from inside a Book_RAG checkout." % ROOT
        )
    with open(pyproject, "r", encoding="utf-8") as handle:
        if 'name = "bookrag"' not in handle.read():
            fail(
                "%s is not Book_RAG's pyproject.toml - refusing to build a "
                "venv here." % pyproject
            )
    ok("Book_RAG checkout at %s" % ROOT)


# --------------------------------------------------------------------------
# virtualenv + dependencies
# --------------------------------------------------------------------------

def venv_python():
    """Path to the venv's interpreter, whether or not it exists yet."""
    if os.name == "nt":
        return os.path.join(VENV, "Scripts", "python.exe")
    return os.path.join(VENV, "bin", "python")


def venv_bin(name):
    """Path to a console script inside the venv (e.g. 'bookrag')."""
    if os.name == "nt":
        return os.path.join(VENV, "Scripts", name + ".exe")
    return os.path.join(VENV, "bin", name)


def create_venv(recreate):
    step("Creating the virtual environment")
    if os.path.isdir(VENV) and recreate:
        note("removing the existing .venv (--recreate)")
        shutil.rmtree(VENV)
    if os.path.isfile(venv_python()):
        ok("reusing the existing .venv")
        return
    if os.path.isdir(VENV):
        fail(
            ".venv exists but has no interpreter at %s - it is probably a "
            "half-created or corrupted venv. Re-run with --recreate to "
            "replace it." % venv_python()
        )
    try:
        subprocess.check_call([sys.executable, "-m", "venv", VENV])
    except subprocess.CalledProcessError:
        fail(
            "could not create a virtual environment.\n"
            "On Debian/Ubuntu the venv module ships separately:\n"
            "  sudo apt install python3-venv"
        )
    if not os.path.isfile(venv_python()):
        fail("venv reported success but %s is missing" % venv_python())
    ok("created %s" % VENV)


def pip_install(args, label):
    """Run pip in the venv. Returns True on success, False on failure."""
    command = [venv_python(), "-m", "pip", "install"] + args
    note("pip install " + label)
    try:
        subprocess.check_call(command)
        return True
    except subprocess.CalledProcessError:
        return False


def install_dependencies():
    step("Installing dependencies")
    if not pip_install(["--upgrade", "pip"], "--upgrade pip"):
        warn("could not upgrade pip; continuing with the bundled version")

    # requirements.txt is a pinned lock frozen on one machine, so its exact
    # versions may have no wheel for another OS or Python version. Try it
    # first (reproducible), fall back to the pyproject dependency groups
    # (resolvable anywhere) and say clearly which one was used - a silent
    # fallback would quietly cost the reproducibility the lock exists for.
    lock = os.path.join(ROOT, "requirements.txt")
    if os.path.isfile(lock) and pip_install(["-r", lock], "-r requirements.txt"):
        if not pip_install(["-e", "."], "-e . (bookrag itself)"):
            fail("could not install bookrag itself")
        ok("installed from the pinned lock (requirements.txt)")
        return

    warn(
        "requirements.txt did not install cleanly on this platform; "
        "falling back to unpinned resolution from pyproject.toml"
    )
    if not pip_install(["-e", ".[core,providers,dev]"], "-e .[core,providers,dev]"):
        fail(
            "dependency installation failed. The pip output above has the "
            "real reason; it is usually a missing compiler or a package with "
            "no wheel for this Python version."
        )
    ok("installed from pyproject.toml dependency groups (versions unpinned)")


# --------------------------------------------------------------------------
# local files
# --------------------------------------------------------------------------

def seed_env_file():
    step("Setting up .env")
    target = os.path.join(ROOT, ".env")
    template = os.path.join(ROOT, ".env.example")
    if os.path.isfile(target):
        ok(".env already exists - left untouched")
        return
    if not os.path.isfile(template):
        warn("no .env.example to copy; skipping")
        return
    shutil.copyfile(template, target)
    ok("created .env from .env.example (every setting in it is optional)")


def create_data_dirs():
    step("Creating data directories")
    for relative in ("data/incoming", "data/library"):
        path = os.path.join(ROOT, *relative.split("/"))
        if not os.path.isdir(path):
            os.makedirs(path)
    ok("data/incoming and data/library are ready (both gitignored)")


# --------------------------------------------------------------------------
# verification
# --------------------------------------------------------------------------

def verify_install():
    step("Verifying the install")
    try:
        output = subprocess.check_output(
            [venv_python(), "-m", "bookrag.cli", "--help"],
            stderr=subprocess.STDOUT,
        )
    except (subprocess.CalledProcessError, OSError) as error:
        fail("bookrag did not run after installation: %s" % error)
    if b"ingest" not in output:
        fail("bookrag ran but its help output looks wrong:\n" + output.decode(
            "utf-8", "replace"))
    ok("the bookrag command works")

    script = venv_bin("bookrag")
    if not os.path.isfile(script):
        warn(
            "the 'bookrag' console script is missing from the venv; use "
            "'python -m bookrag.cli ...' instead"
        )


def context_doc_for(relative):
    """context/<path>.md for a source file, or None if there isn't one."""
    doc = os.path.join(ROOT, "context", relative + ".md")
    return doc if os.path.isfile(doc) else None


def recorded_hash(doc_path):
    """The source_hash out of a context doc's frontmatter, or None."""
    with open(doc_path, "r", encoding="utf-8") as handle:
        for line in handle:
            if line.startswith("source_hash:"):
                return line.split(":", 1)[1].strip()
            if line.startswith("## "):
                break  # past the frontmatter
    return None


def source_files():
    """Every .py under src/ and tests/, as repo-relative slash-separated paths."""
    found = []
    for top in ("src", "tests"):
        base = os.path.join(ROOT, top)
        if not os.path.isdir(base):
            continue
        for dirpath, dirnames, filenames in os.walk(base):
            if "__pycache__" in dirnames:
                dirnames.remove("__pycache__")
            for name in filenames:
                if not name.endswith(".py"):
                    continue
                full = os.path.join(dirpath, name)
                found.append(os.path.relpath(full, ROOT).replace(os.sep, "/"))
    return sorted(found)


def check_context_docs():
    """Report source files whose context/<path>.md is out of date.

    This project keeps a mirrored context doc per source file, each recording
    the sha1 of the source it describes. Drift means someone changed code
    without updating the doc that explains it - the docs are meant to be
    readable instead of the source, so a stale one is worse than none.

    The hash is taken over CR-stripped content, matching
    .claude/hooks/check_drift.sh exactly. .gitattributes normalizes to LF on
    commit, so hashing raw bytes reports drift on files a checkout merely
    rewrote - which is most of what an earlier "stale docs" backlog turned out
    to be. The hook stays authoritative; this is the same check for anyone not
    running Claude Code.
    """
    import hashlib

    step("Checking context docs against their sources")
    if not os.path.isdir(os.path.join(ROOT, "context")):
        note("no context/ directory - skipping")
        return

    stale = []
    missing = []
    checked = 0
    for relative in source_files():
        doc = context_doc_for(relative)
        if doc is None:
            missing.append(relative)
            continue
        with open(os.path.join(ROOT, relative), "rb") as handle:
            digest = hashlib.sha1(handle.read().replace(b"\r", b"")).hexdigest()
        checked += 1
        if digest != recorded_hash(doc):
            stale.append(relative)

    if not stale and not missing:
        ok("all %d context docs match their sources" % checked)
        return
    if stale:
        warn("%d context doc(s) are out of date with their source" % len(stale))
        for relative in stale:
            note("  context/%s.md" % relative)
    if missing:
        warn("%d source file(s) have no context doc" % len(missing))
        for relative in missing:
            note("  " + relative)
    note("See CLAUDE.md for the convention. This does not affect the install.")


def run_tests():
    step("Running the test suite")
    note("this takes a couple of minutes")
    try:
        subprocess.check_call([venv_python(), "-m", "pytest", "-q"], cwd=ROOT)
    except subprocess.CalledProcessError:
        warn("the test suite did not pass - see the pytest output above")
        return
    ok("all tests passed")


# --------------------------------------------------------------------------
# Ollama (optional runtime dependency, never a hard failure)
# --------------------------------------------------------------------------

def default_model():
    """The installed package's own DEFAULT_MODEL.

    Asked of the venv rather than duplicated here, so this script can never
    recommend pulling a model the tool no longer defaults to. By the time the
    Ollama check runs, bookrag is installed, so the import works.
    """
    try:
        output = subprocess.check_output(
            [venv_python(), "-c",
             "from bookrag.providers.ollama_provider import DEFAULT_MODEL;"
             "print(DEFAULT_MODEL)"],
            stderr=subprocess.DEVNULL,
        )
    except (subprocess.CalledProcessError, OSError):
        return DEFAULT_OLLAMA_MODEL
    name = output.decode("utf-8", "replace").strip()
    return name or DEFAULT_OLLAMA_MODEL


def ollama_base_url():
    value = os.environ.get("OLLAMA_BASE_URL", "").strip()
    return (value or DEFAULT_OLLAMA_BASE_URL).rstrip("/")


def ollama_get(path, timeout=5):
    """GET a JSON endpoint on the Ollama server, or None if unreachable."""
    import urllib.request

    try:
        request = urllib.request.Request(ollama_base_url() + path)
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except Exception:
        return None


def model_is_present(tags, wanted):
    """True if `wanted` is among the server's pulled models.

    Ollama stores a tagless name as ':latest', so 'llama3.2' must match a
    stored 'llama3.2:latest'.
    """
    names = [entry.get("name", "") for entry in tags.get("models", [])]
    if wanted in names:
        return True
    if ":" not in wanted:
        return (wanted + ":latest") in names
    return False


def install_ollama_hint():
    if sys.platform == "win32":
        return "  winget install Ollama.Ollama"
    if sys.platform == "darwin":
        return "  brew install ollama"
    return "  curl -fsSL https://ollama.com/install.sh | sh"


def pull_model(model):
    """Stream a model pull over the HTTP API.

    Deliberately not 'ollama pull' - the CLI is frequently absent from PATH
    (real case on this project's own Windows machine: the ollama binary is
    not on PATH under Git Bash, yet the server answers fine). The HTTP API is
    reachable under exactly the condition bookrag itself needs, so it is the
    honest thing to test and use.
    """
    import urllib.request

    payload = json.dumps({"model": model, "stream": True}).encode("utf-8")
    request = urllib.request.Request(
        ollama_base_url() + "/api/pull",
        data=payload,
        headers={"Content-Type": "application/json"},
    )
    note("pulling %s - this is a multi-GB download" % model)
    last = ""
    try:
        with urllib.request.urlopen(request, timeout=None) as response:
            for line in response:
                line = line.strip()
                if not line:
                    continue
                try:
                    update = json.loads(line.decode("utf-8"))
                except ValueError:
                    continue
                if update.get("error"):
                    print("")
                    warn("Ollama refused the pull: %s" % update["error"])
                    return False
                status = update.get("status", "")
                total = update.get("total")
                completed = update.get("completed")
                if total:
                    percent = 100.0 * (completed or 0) / total
                    text = "    %s %5.1f%% (%.1f/%.1f GB)" % (
                        status, percent,
                        (completed or 0) / 1e9, total / 1e9,
                    )
                else:
                    text = "    " + status
                if text != last:
                    sys.stdout.write("\r" + text.ljust(len(last)))
                    sys.stdout.flush()
                    last = text
    except KeyboardInterrupt:
        print("")
        warn("model pull interrupted; re-run install.py to resume it")
        return False
    except Exception as error:
        print("")
        warn("model pull failed: %s" % error)
        return False
    print("")
    return True


def should_pull(model, pull_flag):
    if pull_flag == "yes":
        return True
    if pull_flag == "no":
        return False
    if not sys.stdin.isatty():
        note("not an interactive terminal - skipping the download")
        note("re-run with --pull-model to download it")
        return False
    prompt = "    Download %s now? It is several GB. [y/N] " % model
    try:
        answer = input(prompt).strip().lower()
    except (EOFError, KeyboardInterrupt):
        # isatty() is not decisive on Windows - stdin redirected from NUL
        # reports as a tty because NUL is a character device - so a
        # non-interactive run can still reach the prompt and hit EOF here.
        print("")
        note("no answer available - skipping the download")
        return False
    return answer in ("y", "yes")


def check_ollama(model, pull_flag):
    step("Checking Ollama (optional - the default provider)")
    version = ollama_get("/api/version")
    if version is None:
        warn("no Ollama server answering at %s" % ollama_base_url())
        note("Install it from https://ollama.com/download, or:")
        note(install_ollama_hint())
        note("Everything else is installed - 'bookrag ingest' and")
        note("'--provider fake' work without Ollama.")
        return
    ok("Ollama %s at %s" % (version.get("version", "?"), ollama_base_url()))

    tags = ollama_get("/api/tags")
    if tags is None:
        warn("could not list Ollama's models; skipping the model check")
        return
    if model_is_present(tags, model):
        ok("the %s model is already pulled" % model)
        return

    note("the %s model is not pulled yet" % model)
    if not should_pull(model, pull_flag):
        note("Pull it later with:  ollama pull %s" % model)
        WARNINGS.append(
            "the %s model is not pulled - 'bookrag extract' and 'bookrag "
            "chat' will fail until it is" % model
        )
        return
    if pull_model(model):
        ok("pulled %s" % model)


# --------------------------------------------------------------------------

def print_next_steps():
    if os.name == "nt":
        activate = ".venv\\Scripts\\activate"
    else:
        activate = "source .venv/bin/activate"

    print("\n" + "-" * 68)
    if WARNINGS:
        print("Installed, with %d warning(s):" % len(WARNINGS))
        for message in WARNINGS:
            print("  - " + message)
    else:
        print("Installed.")
    print("-" * 68)
    print("\nActivate the environment:")
    print("  " + activate)
    print("\nThen try a book end to end (--provider fake needs no model):")
    print("  bookrag ingest path/to/some-book.epub")
    print("  bookrag extract <book-id> --provider fake")
    print("  bookrag chat <book-id> --chapter 3 --question \"Who is who?\"")
    print("\nSee README.md for the full reference.")


def parse_args(argv):
    parser = argparse.ArgumentParser(
        description="One-step installer for Book_RAG.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--recreate", action="store_true",
        help="delete and rebuild .venv from scratch",
    )
    parser.add_argument(
        "--model", default=None,
        help="Ollama model to check for (default: whatever the installed "
             "bookrag uses, currently " + DEFAULT_OLLAMA_MODEL + ")",
    )
    parser.add_argument(
        "--pull-model", dest="pull", action="store_const", const="yes",
        help="download the model without asking",
    )
    parser.add_argument(
        "--no-pull-model", dest="pull", action="store_const", const="no",
        help="never download the model, do not even ask",
    )
    parser.add_argument(
        "--skip-ollama", action="store_true",
        help="skip the Ollama check entirely",
    )
    parser.add_argument(
        "--run-tests", action="store_true",
        help="run the test suite after installing",
    )
    parser.add_argument(
        "--skip-doc-check", action="store_true",
        help="skip the context-doc freshness check",
    )
    parser.set_defaults(pull="ask")
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    print("Book_RAG installer")

    check_python()
    check_repo_root()
    create_venv(args.recreate)
    install_dependencies()
    seed_env_file()
    create_data_dirs()
    verify_install()
    if not args.skip_doc_check:
        check_context_docs()
    if args.run_tests:
        run_tests()
    if args.skip_ollama:
        step("Skipping the Ollama check (--skip-ollama)")
    else:
        check_ollama(args.model or default_model(), args.pull)
    print_next_steps()
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\nInterrupted. Re-run install.py to pick up where it stopped.")
        sys.exit(130)
