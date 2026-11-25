# ✈️ Trip Studio

**Turn a messy folder of trip photos into a sorted, searchable, flippable travel book — 100% free, 100% on your own computer.**

No cloud. No API keys. No subscriptions. Your photos never leave your machine.

Point it at a folder, watch your photos fly into neat categories, then open a magazine-style Travel Book you can flip through, search, and export as a PDF.

---

## 🚀 Quick Start

Pick **one** of the two options. Both end the same way: Trip Studio opens in your browser at **http://127.0.0.1:8765**.

### Option 1 — 1-Click AI Setup (Recommended)

Paste this prompt into your AI agent:

```text
Clone https://github.com/workanshverma-gif/trip-studio, follow its CLAUDE.md to set it up, and launch the dashboard on my computer (Windows or Mac). Open it in my browser when it's running.
```

> **⚠️ Important: paste this into a *local* AI agent running on your own computer — Claude Code in your Terminal/PowerShell, Cursor, or Antigravity.**
> **Do NOT paste it into regular Claude Web or ChatGPT in your browser.** Browser chats can't access your local photo folders or open `localhost`, so they can't set anything up for you. (If you only have a browser chat, use Option 2.)

### Option 2 — No AI or Terminal Needed (Easiest for Beginners)

1. On this GitHub page, click the green **`Code`** button → **Download ZIP**.
2. **Unzip** the downloaded folder.
3. Start it:
   - **Windows:** double-click **`run.bat`**. (If Windows says *"Windows protected your PC"*, click **More info → Run anyway**.)
   - **Mac:** open **Terminal**, type `bash ` (with a space after it), drag **`run.sh`** from the folder into the Terminal window, and press **Enter**. *(A ZIP download doesn't keep the "executable" flag, so plain double-clicking `run.sh` may not work on a Mac.)*

That's it — the first launch installs everything automatically, and **your browser opens by itself** when it's ready.

**You need Python 3.10 or newer installed first.** Get it free at [python.org/downloads](https://www.python.org/downloads/) (on Windows, tick **"Add python.exe to PATH"** in the installer). If it's missing, the launcher tells you exactly what to install.

<details>
<summary>Prefer the command line?</summary>

```bash
git clone https://github.com/workanshverma-gif/trip-studio.git
cd trip-studio
python run.py          # Windows: py -3 run.py     macOS/Linux: python3 run.py
```

`run.py` checks Python (3.10+), creates a virtual environment, installs everything, starts the server and opens your browser.
</details>

> ⏱️ First run: installing PyTorch takes a few minutes, and your first sort downloads a ~350 MB AI model once. After that it's fast and works without the cloud.

---

## ✨ Features

### 🧠 100% Free & Local AI Sorting
[OpenCLIP](https://github.com/mlfoundations/open_clip) (ViT-B/32) runs on your **CPU** — no GPU, no paid API, complete privacy. Photos are sorted into **Selfies, People & Family, Food & Drinks, Travel & Nature, Night Out** and more. Everything is copied (or moved, your choice) into a fresh `Sorted_Trip_Studio` folder — **originals are never deleted or overwritten.**

### 🎬 Live Animated Dashboard
Watch thumbnails swirl in the center and **fly into their category cards** while animated counters tick up in real time. When it's done: confetti. 🎉
- **Click any category card** → a clean gallery of everything in that folder, plus **Open Folder on Computer**.
- **Click any photo** → a full-size **lightbox** with Next/Previous arrows, file name, and *Open in New Tab*. Keyboard friendly (← → Esc).

### 🔥 Burst & Blur Killer (Best-Shot Picker)
OpenCV measures sharpness (Laplacian variance) and exposure; perceptual hashing plus timestamps groups bursts and near-duplicates. In each group the **sharpest, best-lit shot stays** — the blurry, too-dark and extra frames move to `Needs_Review_Duplicates`. A live **Space Saved (MB)** counter shows what you'd reclaim. One toggle turns the filter on or off.

### 🗓️ Auto-Timeline (Day-by-Day)
Flip on *Sort by Trip Timeline* and photos are organized into `Day 1 - 2025-10-12`, `Day 2 - …` folders with category subfolders inside, plus a **Day-by-Day Timeline** view on the dashboard. Dates come from EXIF (`DateTimeOriginal` → `DateTimeDigitized`) and **fall back to the file's modified date** for WhatsApp/edited images — so every photo lands on a real day.

### 🧾 Receipt, Ticket & Screenshot Vault
Phone screenshots (screen aspect ratio, no camera metadata) and receipts, boarding passes, tickets and UPI confirmations (detected by AI) go to `Tickets_and_Receipts`, keeping your trip photos clean.

### 🌅 Hero Shots & Golden Hour Finder
Every non-blurry photo is scored on sharpness, exposure, colour richness and **warm golden-hour tones**. The top 10% (max 25) are copied into `Top_Picks_Hero_Shots` — your trip's greatest hits — and the #1 shot becomes your book cover.

### 🏷️ Custom Category Creator
Type `Dogs, Coffee, Mountains` into the settings box and those exact labels are added to the AI on the fly — new cards, new folders, no training needed.

### 👀 Visual Dry-Run Preview & One-Click Undo
**Preview Sort** analyzes everything *without touching a single file* and shows exactly how many files will land in each folder. Happy? **Apply Sort.** Changed your mind later? **Undo Last Sort** restores your folder to its exact original state (verified byte-for-byte by the test suite) via a `sort_history.json` log.

### 📖 Interactive Flippable Travel Book
Click **Travel Book** and your trip becomes a realistic page-flipping magazine: a cover with your #1 hero shot, trip name and date range, then auto-generated collage pages (editorial spreads, magazine grids, Polaroid walls with soft shadows and captions). Face-aware cropping keeps people from being cut off. Flip with page corners, swipe, or arrow keys.
- **Built-in search** — type `Food`, `Sunset`, `Day 2` or any custom tag and jump straight to matching pages.
- **Download This Collage** on every page — a PNG sized for Instagram Stories (1080×1920).
- **Export Full Book as PDF** in one click.

### 🎨 Custom Collage Studio
Prefer to curate yourself? Open the **Custom Collage** tab (or tick photos inside any category folder), pick **2, 3, 4 or 6 photos**, choose a layout — *2-Photo Split, 3-Photo Editorial, 4-Photo Polaroid Grid, 6-Photo Grid* — add an optional title, and hit **Create Collage**. Preview it, **Download PNG**, or **Save to Travel Book**.

### 🛡️ Tough on messy folders
iPhone **HEIC** photos, `.mp4`/`.MOV` videos, photos with no EXIF, corrupted files, duplicate filenames, and folders with 1,000+ photos are all handled gracefully — corrupted images are parked for review instead of crashing the app.

---

## 🖥️ Requirements

- **Windows 10/11 or macOS** (Linux works too) — see [Tested on](#-tested-on)
- **Python 3.10+**
- ~3 GB free disk space (PyTorch CPU build + the AI model)
- Internet **only** for the first install and the one-time model download

## 🔒 Privacy

- The server listens on `127.0.0.1` only — nothing is exposed to your network.
- No telemetry, no analytics, no external APIs. All libraries, including the page-flip viewer, are bundled or installed locally.
- Your photos are only ever read from the folder you choose and copied into `Sorted_Trip_Studio` inside it.

## 🧪 Tests

```bash
pip install -r requirements-dev.txt
python tests/run_checks.py            # 65 API / safety / undo / edge-case checks (builds its own sample photos)
python tests/run_checks.py --stress 1200
python tests/ui_check.py              # drives the real UI in Edge/Chrome and fails on any console error
```

## ✅ Tested on

Developed and tested on **Windows 11 with Python 3.14** (exact versions in `requirements-lock.txt`). `requirements.txt` uses version ranges so pip can pick builds that exist for **Python 3.10+ on Windows, macOS and Linux**; macOS-specific code paths (native folder dialog via AppleScript, Finder opening) are included but have had less testing — please open an issue if something misbehaves.

## ⚠️ Honest limitations

- AI categories are best-guess: every clean photo is placed in the closest category, so use **Preview Sort** and custom categories to steer it.
- Blur/dark thresholds are heuristics and may need tuning for your camera.
- Dates fall back to file modified time when EXIF is missing, which can be off for copied/downloaded files.
- GPS coordinates are saved in `sort_history.json`; place-name lookup isn't included (it would need an online service).

## 🆘 Troubleshooting

PowerShell blocking `Activate.ps1`, `python` opening the Microsoft Store, `pillow-heif` install problems, big PyTorch downloads and more are covered in [CLAUDE.md → Troubleshooting](CLAUDE.md#troubleshooting).

## 🧱 Built with

FastAPI · Uvicorn · OpenCLIP · PyTorch (CPU) · OpenCV · Pillow · pillow-heif · imagehash · [StPageFlip](https://github.com/Nodlik/StPageFlip) (MIT) · vanilla HTML/CSS/JS. The bundled `haarcascade_frontalface_default.xml` is from [OpenCV](https://github.com/opencv/opencv) (BSD-style Intel license).

## 📄 License

[MIT](LICENSE) — free to use, change and share.
