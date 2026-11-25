# CLAUDE.md — set up and launch Trip Studio (for AI coding agents)

You are an AI coding agent (Claude Code, ChatGPT, Cursor, Antigravity, …). Your job: **get Trip Studio running on the user's computer and open it in their browser.** It is a 100% local, free photo sorter + travel-book app (Python/FastAPI backend, vanilla JS frontend). No API keys, no accounts, no paid services.

**Fastest path (works on Windows, macOS and Linux) — do this first:**

```bash
python run.py        # Windows: py -3 run.py      macOS/Linux: python3 run.py
```

`run.py` performs every step below automatically (Python check → venv → install → start → open browser). If it works, you're done: tell the user the app is at http://127.0.0.1:8765. If it fails, follow the manual steps and the troubleshooting section.

---

## Manual steps (use these if `run.py` fails, or to explain what happens)

Work from the repository root (the folder containing `requirements.txt`). Run commands one at a time and check each result before continuing.

### 1. Verify Python 3.10 or newer

Try these in order until one prints `Python 3.10` or higher:

| OS | Commands to try |
|---|---|
| Windows | `py -3 --version` then `python --version` |
| macOS / Linux | `python3 --version` then `python --version` |

- Remember which command worked; call it `PY` below.
- If none works or the version is below 3.10, **stop and tell the user to install Python** (don't try to hack around it):
  - Windows: https://www.python.org/downloads/ → during install tick **"Add python.exe to PATH"**. (If typing `python` opens the Microsoft Store, disable the "App execution alias" for python, or use `py -3`.)
  - macOS: `brew install python` or the installer from python.org.
  - Linux: `sudo apt install python3 python3-venv python3-pip` (Debian/Ubuntu).

### 2. Create the virtual environment

```bash
PY -m venv .venv
```

### 3. Activate it (optional but recommended)

| Shell | Command |
|---|---|
| Windows PowerShell | `.\.venv\Scripts\Activate.ps1` |
| Windows cmd | `.venv\Scripts\activate.bat` |
| macOS / Linux (bash/zsh) | `source .venv/bin/activate` |

> **Agents:** activation does not persist between separate tool calls. Skip it and call the venv's interpreter directly instead — this is always reliable:
> - Windows: `.venv\Scripts\python.exe`
> - macOS/Linux: `.venv/bin/python`
>
> Below, `VENV_PY` means that path.

### 4. Install dependencies

```bash
VENV_PY -m pip install --upgrade pip
VENV_PY -m pip install -r requirements.txt
```

This installs FastAPI, Uvicorn, PyTorch (CPU), OpenCLIP, OpenCV, Pillow, pillow-heif, imagehash, NumPy. PyTorch is the big one — it can take several minutes; that is normal. Want the exact tested versions? Use `requirements-lock.txt` instead.

### 5. Start the server and open the browser

```bash
VENV_PY app/main.py
```

The server listens **only on 127.0.0.1:8765** and opens the user's default browser automatically (set `TRIP_STUDIO_NO_BROWSER=1` to disable that). It prints `Trip Studio is running at http://127.0.0.1:8765`. Leave it running; Ctrl+C stops it.

If a browser didn't open, open **http://127.0.0.1:8765** yourself.

### 6. Verify (do not skip)

```bash
curl http://127.0.0.1:8765/api/state        # expect HTTP 200 and JSON
```

Then tell the user: *"Trip Studio is running at http://127.0.0.1:8765. Click **Select Folder**, choose a folder of photos, press **Preview Sort (Dry Run)** first, then **Start Sorting**."*

Notes for the user to hear:
- The **first sort** downloads the ~350 MB OpenCLIP model once (needs internet that one time). Afterwards everything is local.
- Sorting **copies** files into a new `Sorted_Trip_Studio` folder inside the chosen folder. Originals are never deleted or overwritten. **Undo Last Sort** reverses everything.

---

## Troubleshooting

**Windows PowerShell: "running scripts is disabled on this system" when activating the venv**
Don't activate. Run `python run.py`, or call `.venv\Scripts\python.exe` directly. (Or, for this window only: `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass`.)

**`python` opens the Microsoft Store / "Python was not found"**
Use `py -3 run.py`, or install Python from python.org with *Add to PATH* ticked, or turn off Settings → Apps → Advanced app settings → App execution aliases → python.exe.

**`pillow-heif` fails to install (iPhone HEIC support)**
1. `VENV_PY -m pip install --upgrade pip` and retry — modern pip finds a prebuilt wheel for Windows/macOS/Linux and no compiler is needed.
2. Very new or old Python versions may lack a wheel. Then install the system library and retry: macOS `brew install libheif`; Debian/Ubuntu `sudo apt install libheif-dev build-essential`; Windows: use Python 3.11 or newer (current pillow-heif releases ship wheels for it).
3. Still stuck? Remove the `pillow-heif` line from `requirements.txt` and reinstall. The app keeps working; `.HEIC` photos will simply land in `Needs_Review_Duplicates` as "unreadable" instead of being sorted. Everything else is unaffected.

**PyTorch install is huge / slow / fails**
`requirements.txt` already points at the CPU-only wheel index (`--extra-index-url https://download.pytorch.org/whl/cpu`), which is ~200 MB instead of GBs. If pip still fails, check free disk space (≥ 3 GB total incl. the model) and your internet connection, then retry. Behind a proxy, configure pip's proxy first.

**`error: Microsoft Visual C++ 14.0 required`**
Some package fell back to building from source. Upgrade pip, use Python 3.11 or newer, and retry; prebuilt wheels exist for all dependencies there.

**Port 8765 already in use**
If it's Trip Studio itself, `python run.py` just opens the browser. Otherwise find and stop the other program (`netstat -ano | findstr 8765` on Windows, `lsof -i :8765` on macOS/Linux). Don't change the port without also changing the URLs in `README.md`/`CLAUDE.md`.

**"Select Folder" shows a text prompt instead of a dialog**
That's the built-in fallback — paste the folder path. On Linux install Tk for the native dialog: `sudo apt install python3-tk`. (macOS uses a native AppleScript dialog; no extra install.)

**First sort stalls on "Loading AI engine…"**
It's downloading the model (~350 MB) from Hugging Face. Needs internet once; be patient or check the connection. The model is cached afterwards in `~/.cache/huggingface`.

**Collage text looks plain**
Collages use Georgia/Segoe (Windows) or Georgia/Arial (macOS) when present, and fall back to DejaVu on Linux. Install any of those fonts for the best look.

---

## Project map (for agents modifying the code)

```
run.py / run.bat / run.sh   one-command launcher (venv + install + start)
requirements.txt            dependencies (ranges)   requirements-lock.txt = exact tested versions
app/main.py                 FastAPI app: routes, SSE progress stream, sort job, undo, library, book, custom collage
app/engine.py               OpenCLIP classification, EXIF/GPS/date reading, screenshot detection, HEIC registration
app/quality.py              sharpness (Laplacian), exposure, perceptual-hash burst grouping, hero-shot scoring
app/collage.py              Pillow/OpenCV page layouts, face-aware smart crop, travel-book + custom collages, PDF
app/models/                 Haar cascade XML for face detection (bundled; OpenCV 5 removed it)
app/static/                 index.html, style.css, app.js (dashboard), library.js (gallery/lightbox/timeline/collage tab),
                            book.js (flip book), vendor/page-flip.browser.js (StPageFlip, MIT)
tests/run_checks.py         end-to-end API/safety suite (45+ checks, builds its own sample folder)
tests/ui_check.py           real-browser (Playwright) UI suite; fails on any console error
```

### Run the tests (after `pip install -r requirements-dev.txt`)

```bash
VENV_PY tests/run_checks.py            # API + safety + undo + edge cases
VENV_PY tests/run_checks.py --stress 1200
VENV_PY tests/ui_check.py              # needs Microsoft Edge or Google Chrome installed
```

### Rules to keep when changing code

1. **Never delete or overwrite a user's original photo.** All output goes under `<chosen folder>/Sorted_Trip_Studio/`; `safe_dest()` prevents overwrites; `sort_history.json` makes Undo exact. Run `tests/run_checks.py` after touching sort/undo code — it asserts byte-for-byte restoration.
2. **Stay local.** No telemetry, no paid APIs, no CDN scripts. The server binds to `127.0.0.1` only. Files are served only from paths recorded in `sort_history.json` and verified to be inside `Sorted_Trip_Studio`.
3. **Never commit personal photos or sort output** (`.gitignore` covers `Sorted_Trip_Studio/`, `Travel_Book_Collages/`, images, venvs). Tests generate their own sample images.
4. Keep OpenCV at `<5` (face detector) and keep the frontend dependency-free vanilla JS.
