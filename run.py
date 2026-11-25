#!/usr/bin/env python3
"""One-command launcher for Trip Studio (Windows, macOS, Linux).

    python run.py          (Windows: py -3 run.py     macOS/Linux: python3 run.py)

Checks Python >= 3.10, creates .venv, installs requirements.txt (only when it changed),
starts the server on http://127.0.0.1:8765 and opens your browser.
"""
import hashlib
import os
import subprocess
import sys
import venv
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VENV = ROOT / ".venv"
REQ = ROOT / "requirements.txt"
STAMP = VENV / ".requirements.sha256"
WIN = os.name == "nt"
VENV_PY = VENV / ("Scripts/python.exe" if WIN else "bin/python")


def die(msg: str) -> None:
    print(f"\n[Trip Studio] {msg}\n", file=sys.stderr)
    sys.exit(1)


def run(cmd: list[str], **kw) -> None:
    if subprocess.call([str(c) for c in cmd], **kw) != 0:
        die(f"Command failed: {' '.join(str(c) for c in cmd)}\nSee the Troubleshooting section in CLAUDE.md / README.md.")


def main() -> None:
    if sys.version_info < (3, 10):
        die(f"Python 3.10 or newer is required (found {sys.version.split()[0]}).\n"
            "Install it from https://www.python.org/downloads/ (tick 'Add python.exe to PATH' on Windows)\n"
            "or with Homebrew on macOS:  brew install python")

    if not VENV_PY.exists():
        print("[Trip Studio] Creating virtual environment (.venv) ...")
        venv.create(VENV, with_pip=True, clear=True)

    digest = hashlib.sha256(REQ.read_bytes()).hexdigest()
    if not STAMP.exists() or STAMP.read_text().strip() != digest:
        print("[Trip Studio] Installing dependencies (first run only; PyTorch is a large download) ...")
        run([VENV_PY, "-m", "pip", "install", "--upgrade", "pip"])
        run([VENV_PY, "-m", "pip", "install", "-r", REQ])
        STAMP.write_text(digest)

    print("[Trip Studio] Starting ... (the first sort downloads the ~350 MB AI model once)")
    try:
        sys.exit(subprocess.call([str(VENV_PY), str(ROOT / "app" / "main.py")], cwd=ROOT))
    except KeyboardInterrupt:
        print("\n[Trip Studio] Stopped.")


if __name__ == "__main__":
    main()
