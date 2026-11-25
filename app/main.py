"""Trip Studio - local-only AI photo sorter (OpenCLIP on CPU, no paid APIs)."""
from __future__ import annotations

import asyncio
import io
import json
import math
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from PIL import Image, ImageOps

from engine import BASE_CATEGORIES, CLASSIFIER, RECEIPTS, looks_like_screenshot, read_meta
from quality import analyze, group_similar
from collage import COLLAGE_DIR, build_book, build_custom, export_pdf

BASE = Path(__file__).resolve().parent
STATIC = BASE / "static"
SORT_DIR = "Sorted_Trip_Studio"
HISTORY = "sort_history.json"
IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".tif", ".tiff", ".heic", ".heif"}
VIDEO_EXT = {".mp4", ".mov", ".avi", ".mkv", ".webm", ".m4v", ".wmv"}
REVIEW_DIR = "Needs_Review_Duplicates"
HERO_DIR = "Top_Picks_Hero_Shots"
HERO_FRACTION, HERO_CAP = 0.10, 25
THUMB_PX = 200

app = FastAPI(title="Trip Studio")


# --------------------------------------------------------------------------- state
class State:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.folder: Path | None = None
        self.files: list[dict] = []        # {id, path, name, kind, size}
        self.events: list[dict] = []       # append-only, index == event id
        self.running = False
        self.book_running = False
        self.job = 0

    def emit(self, type_: str, **data) -> None:
        with self.lock:
            self.events.append({"type": type_, "job": self.job, **data})


S = State()


# --------------------------------------------------------------------------- helpers
def scan_folder(folder: Path) -> list[dict]:
    found = []
    for dirpath, dirnames, filenames in os.walk(folder):
        dirnames[:] = sorted(d for d in dirnames if d != SORT_DIR and not d.startswith((".", "$")))
        for name in sorted(filenames):
            if name.startswith("."):
                continue
            ext = os.path.splitext(name)[1].lower()
            kind = "image" if ext in IMAGE_EXT else "video" if ext in VIDEO_EXT else None
            if not kind:
                continue
            p = Path(dirpath) / name
            try:
                size = p.stat().st_size
            except OSError:
                continue
            found.append({"id": len(found), "path": p, "name": name, "kind": kind, "size": size})
    return found


BROKEN_SVG = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 200 200"><rect width="200" height="200" fill="#F3E3DD"/>'
              '<path d="M60 140l30-40 20 25 15-18 25 33z" fill="#D9B4A8"/><circle cx="80" cy="75" r="12" fill="#D9B4A8"/>'
              '<path d="M40 40l120 120" stroke="#C0705A" stroke-width="8"/></svg>')
VIDEO_SVG = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 200 200"><rect width="200" height="200" '
             'fill="#EDE6DA"/><path d="M80 70l60 30-60 30z" fill="#B8A98F"/></svg>')


def make_thumb(f: dict) -> bytes | None:
    """Small JPEG thumbnail, cached on the file record. JPEG draft mode makes big photos decode fast."""
    if "_thumb" in f:
        return f["_thumb"]
    if f["kind"] != "image":
        return None
    try:
        with Image.open(f["path"]) as im:
            im.draft("RGB", (THUMB_PX * 2, THUMB_PX * 2))
            im = ImageOps.exif_transpose(im).convert("RGB")
            im.thumbnail((THUMB_PX, THUMB_PX))
            buf = io.BytesIO()
            im.save(buf, "JPEG", quality=76)
            f["_thumb"] = buf.getvalue()
    except Exception:
        f["_thumb"] = None   # corrupted / unsupported: remember so we don't retry on every request
    return f["_thumb"]


def safe_dest(dst: Path) -> Path:
    """Never overwrite: pick a free name."""
    if not dst.exists():
        return dst
    i = 1
    while True:
        cand = dst.with_name(f"{dst.stem}_{i}{dst.suffix}")
        if not cand.exists():
            return cand
        i += 1


def kind_img(f: dict) -> bool:
    return f["kind"] == "image"


def folder_name(label: str) -> str:
    if label == RECEIPTS:
        return "Tickets_and_Receipts"
    if label == "Needs Review":
        return REVIEW_DIR
    out = re.sub(r"[^\w\- ]+", "", label.replace("&", "and")).strip()
    return re.sub(r"\s+", "_", out) or "Other"


def status(msg: str) -> None:
    S.emit("status", message=msg)


def read_history(folder: Path) -> list[dict]:
    p = folder / SORT_DIR / HISTORY
    try:
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else []
    except Exception:
        return []


# --------------------------------------------------------------------------- sorting job
def run_job(dry: bool, timeline: bool, custom: list[str], copy_mode: bool, filt: bool) -> None:
    folder, files = S.folder, S.files
    t0 = time.time()
    try:
        custom = list(dict.fromkeys(c for c in custom if c not in BASE_CATEGORIES))
        cats = BASE_CATEGORIES + custom
        S.emit("start", total=len(files), dry=dry, categories=cats)
        names = text = None
        if any(f["kind"] == "image" for f in files):
            CLASSIFIER.load(status)
            names, text = CLASSIFIER.text_matrix(custom)
        imgs = [f for f in files if f["kind"] == "image"]
        metas = {f["id"]: read_meta(f["path"]) for f in imgs}
        taken = {}
        for f in files:
            m = metas.get(f["id"])
            taken[f["id"]] = (m and m["taken"]) or datetime.fromtimestamp(os.path.getmtime(f["path"]))

        # ---- pass 1: quality analysis (sharpness, exposure, colour, golden hour, perceptual hash)
        qual: dict[int, dict] = {}
        for n, f in enumerate(imgs):
            if n % 6 == 0:
                status(f"Checking sharpness & lighting… {n}/{len(imgs)}")
            try:
                qual[f["id"]] = analyze(f["path"])
            except Exception:
                pass
        shots = {fid for fid, m in metas.items() if looks_like_screenshot(m)}
        verdict: dict[int, list[str]] = {}   # fid -> reasons it goes to review
        if filt:
            status("Grouping bursts and near-duplicates…")
            for fid, q in qual.items():
                if fid in shots:
                    continue
                r = [k for k in ("blurry", "dark", "overexposed") if q[k]]
                if r:
                    verdict[fid] = r
            items = [(fid, taken[fid].timestamp(), q["phash"]) for fid, q in qual.items()]
            for g in group_similar(items):
                best = max(g, key=lambda i: qual[i]["rank"])   # sharpest, best-lit survives
                for i in g:
                    if i != best and "duplicate" not in verdict.get(i, []):
                        verdict.setdefault(i, []).append("duplicate")
        exif_dated = {fid for fid, m in metas.items() if m["taken"]}
        days = sorted({t.date() for t in taken.values()})
        day_label = {d: f"Day {i + 1} - {d.isoformat()}" for i, d in enumerate(days)}
        status("Previewing — nothing will be moved…" if dry else "Sorting your photos…")

        root = folder / SORT_DIR
        entries: list[dict] = []
        plan: dict[str, int] = {}
        scored: list[tuple[float, int]] = []
        counts = {"sorted": 0, "review": 0, "receipts": 0, "videos": 0, "saved": 0}

        for f in files:
            fid = f["id"]
            flags, conf, category = [], None, None
            m = metas.get(fid)
            if f["kind"] == "video":
                bucket = "Videos"; counts["videos"] += 1
            else:
                flags = list(verdict.get(fid, []))
                shot = fid in shots
                if fid not in qual:
                    flags = ["unreadable"]        # corrupted / unsupported image: park it, never crash
                if not flags:
                    try:
                        if shot:
                            category, conf = RECEIPTS, 1.0   # phone screenshot
                        else:
                            category, probs = CLASSIFIER.classify(f["path"], names, text)
                            conf = round(probs[category], 3)
                    except Exception as e:
                        status(f"Couldn't read {f['name']}: {e}")
                        flags = ["unreadable"]
                if flags:
                    bucket = "Needs Review"; counts["review"] += 1
                    if flags != ["unreadable"]:
                        counts["saved"] += f["size"]
                else:
                    bucket = category; counts["sorted"] += 1
                    if category == RECEIPTS:
                        counts["receipts"] += 1
                    elif fid in qual:
                        scored.append((qual[fid]["hero"], fid))

            d = taken[fid].date()
            if bucket == "Needs Review":
                rel = Path(REVIEW_DIR)
            elif timeline:
                rel = Path(day_label[d]) / folder_name(bucket)
            else:
                rel = Path(folder_name(bucket))
            dst = safe_dest(root / rel / f["name"])
            if not dry:
                dst.parent.mkdir(parents=True, exist_ok=True)
                (shutil.copy2 if copy_mode else shutil.move)(str(f["path"]), str(dst))
            entries.append({"op": "copy" if copy_mode else "move", "src": str(f["path"]), "dst": str(dst),
                            "category": bucket, "taken": taken[fid].isoformat(),
                            "gps": m["gps"] if m else None, "confidence": conf, "flags": flags,
                            "dated": True, "date_source": "exif" if fid in exif_dated else "file", "fid": fid, "golden": qual.get(fid, {}).get("golden"),
                            "hero_score": qual.get(fid, {}).get("hero"),
                            "sharpness": qual.get(fid, {}).get("sharp"),
                            "brightness": qual.get(fid, {}).get("brightness")})
            if not dry and not copy_mode:
                f["path"] = dst
            key = rel.as_posix()
            plan[key] = plan.get(key, 0) + 1
            S.emit("file", id=fid, name=f["name"], kind=f["kind"], bucket=bucket, category=category,
                   flags=flags, size=f["size"], confidence=conf, folder=key,
                   day=day_label[d] if timeline else None, gps=m["gps"] if m else None)

        # Hero shots: top 10% (max 25) of non-blurry photos by sharpness+exposure+colour+golden hour. Always copies.
        scored.sort(reverse=True)
        picks = scored[: min(HERO_CAP, max(1, math.ceil(len(scored) * HERO_FRACTION)))] if scored else []
        for score, fid in picks:
            f = files[fid]
            dst = safe_dest(root / HERO_DIR / f["name"])
            if not dry:
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(f["path"], dst)
            entries.append({"op": "copy", "src": str(f["path"]), "dst": str(dst), "category": "Top Picks",
                            "hero_score": score, "golden": qual[fid]["golden"], "fid": fid, "taken": taken[fid].isoformat(), "dated": True})
            plan[HERO_DIR] = plan.get(HERO_DIR, 0) + 1
            S.emit("pick", id=fid, name=f["name"], score=score, golden=qual[fid]["golden"])

        if not dry:
            hist = read_history(folder)
            hist.append({"id": len(hist) + 1, "time": datetime.now().isoformat(timespec="seconds"),
                         "mode": "copy" if copy_mode else "move", "timeline": timeline,
                         "custom_categories": custom, "entries": entries})
            (root / HISTORY).write_text(json.dumps(hist, indent=1), encoding="utf-8")
        S.emit("done", dry=dry, copy=copy_mode, seconds=round(time.time() - t0, 1), total=len(files),
               picks=len(picks), plan=sorted(plan.items()), **counts)
    except Exception as e:  # surface failures in the UI instead of dying silently
        import traceback
        traceback.print_exc()
        S.emit("error", message=str(e))
    finally:
        S.running = False


def undo_last() -> int:
    folder = S.folder
    hist = read_history(folder)
    if not hist:
        return -1
    run = hist.pop()
    root = (folder / SORT_DIR).resolve()
    restored = 0
    for m in reversed(run["entries"]):
        dst, src = Path(m["dst"]), Path(m["src"])
        if not dst.exists() or root not in dst.resolve().parents:
            continue
        if m["op"] == "copy":
            dst.unlink()  # only ever removes the copies this app itself made
            restored += m.get("category") != "Top Picks"
        else:
            src.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(dst), str(safe_dest(src)))
            restored += 1
    for d in sorted(root.rglob("*"), key=lambda p: len(p.parts), reverse=True):
        if d.is_dir() and not any(d.iterdir()):
            d.rmdir()
    shutil.rmtree(root / COLLAGE_DIR, ignore_errors=True)  # generated book is stale once a sort is undone
    hp = root / HISTORY
    if hist:
        hp.write_text(json.dumps(hist, indent=1), encoding="utf-8")
    else:
        hp.unlink(missing_ok=True)
        if root.exists() and not any(root.iterdir()):
            root.rmdir()
    S.files = scan_folder(folder)
    return restored


# --------------------------------------------------------------------------- API
def folder_info() -> dict:
    return {
        "folder": str(S.folder) if S.folder else None,
        "name": S.folder.name if S.folder else None,
        "images": sum(f["kind"] == "image" for f in S.files),
        "videos": sum(f["kind"] == "video" for f in S.files),
        "total": len(S.files),
        "ids": [f["id"] for f in S.files if f["kind"] == "image"][:60],
        "can_undo": bool(S.folder and read_history(S.folder)),
    }


@app.get("/api/state")
def state():
    with S.lock:
        last = len(S.events) - 1
    return {**folder_info(), "running": S.running, "last_event": last, "categories": BASE_CATEGORIES}


def pick_folder_dialog() -> str:
    """Native folder picker. macOS needs AppleScript (Tk must own the main thread there)."""
    if sys.platform == "darwin":
        r = subprocess.run(["osascript", "-e", 'POSIX path of (choose folder with prompt "Choose your photo folder")'],
                           capture_output=True, text=True)
        return r.stdout.strip() if r.returncode == 0 else ""
    import tkinter as tk
    from tkinter import filedialog
    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    try:
        return filedialog.askdirectory(title="Choose your photo folder") or ""
    finally:
        root.destroy()


def load_folder(path: str) -> dict:
    p = Path(path).expanduser()
    if not p.is_dir():
        raise HTTPException(400, f"Not a folder: {path}")
    S.folder = p.resolve()
    S.files = scan_folder(S.folder)
    return folder_info()


@app.post("/api/select-folder")
async def select_folder(request: Request):
    if S.running:
        raise HTTPException(409, "Sorting is in progress")
    body = await request.json() if request.headers.get("content-length", "0") != "0" else {}
    path = body.get("path")
    if not path:
        try:
            path = await asyncio.to_thread(pick_folder_dialog)
        except Exception:
            return JSONResponse({"dialog_failed": True})
        if not path:
            return JSONResponse({"cancelled": True})
    return await asyncio.to_thread(load_folder, path)


@app.post("/api/sort")
async def sort(request: Request):
    body = await request.json()
    if not S.folder:
        raise HTTPException(400, "Select a folder first")
    if S.running:
        raise HTTPException(409, "Already running")
    if not body.get("dry") and read_history(S.folder):
        raise HTTPException(409, "This folder was already sorted. Click 'Undo Last Sort' first.")
    old = {str(f["path"]): f["_thumb"] for f in S.files if "_thumb" in f}
    S.files = scan_folder(S.folder)  # pick up any changes since selection
    for f in S.files:                 # keep already-made thumbnails
        if str(f["path"]) in old:
            f["_thumb"] = old[str(f["path"])]
    custom = [c.strip() for c in str(body.get("custom", "")).split(",") if c.strip()][:8]
    S.running = True
    S.job += 1
    threading.Thread(target=run_job, daemon=True,
                     args=(bool(body.get("dry")), bool(body.get("timeline_mode", body.get("timeline"))), custom, bool(body.get("copy", True)), bool(body.get("filter", True)))).start()
    return {"job": S.job}


@app.post("/api/undo")
async def undo():
    if S.running:
        raise HTTPException(409, "Sorting is in progress")
    n = await asyncio.to_thread(undo_last)
    if n < 0:
        raise HTTPException(404, "Nothing to undo")
    return {"restored": n, **folder_info()}


# ---- library of sorted photos. Paths come ONLY from sort_history.json, never from the client.
_lib: dict = {"key": None, "data": None}
_lib_files: dict = {}   # (history key, index) -> file record that carries the cached thumbnail
BROWSER_IMG = {".jpg", ".jpeg", ".png", ".webp", ".gif"}


def get_library() -> dict | None:
    if not S.folder:
        return None
    hp = S.folder / SORT_DIR / HISTORY
    try:
        st = hp.stat()
    except OSError:
        return None
    key = (str(hp), st.st_mtime_ns, st.st_size)
    if _lib["key"] != key:
        hist = read_history(S.folder)
        if not hist:
            return None
        run, root, items = hist[-1], (S.folder / SORT_DIR).resolve(), []
        for i, e in enumerate(run["entries"]):
            dst = Path(e["dst"])
            try:
                rel = dst.resolve().parent.relative_to(root)
            except ValueError:
                continue
            day = rel.parts[0] if rel.parts and rel.parts[0].startswith("Day ") else None
            items.append({"i": i, "name": dst.name, "category": e["category"], "folder": rel.as_posix() or ".",
                          "day": day, "date": e.get("taken"), "fid": e.get("fid"),
                          "kind": "video" if dst.suffix.lower() in VIDEO_EXT else "image", "path": str(dst)})
        _lib.update(key=key, data={"run_id": run["id"], "timeline": bool(run.get("timeline")), "items": items,
                                   "by_i": {it["i"]: it for it in items}})
    return _lib["data"]


def lib_item(i: int) -> dict:
    lib = get_library()
    it = lib["by_i"].get(i) if lib else None
    if not it:
        raise HTTPException(404, "Not found")
    p = Path(it["path"]).resolve()
    root = (S.folder / SORT_DIR).resolve()
    if root not in p.parents or not p.is_file():    # path-traversal / deleted-file guard
        raise HTTPException(404, "File is no longer in the sorted folder")
    return {**it, "_p": p}


@app.get("/api/library")
def library():
    lib = get_library()
    if not lib:
        return {"empty": True, "run_id": None, "timeline": False, "items": []}   # 200 so the browser console stays clean
    return {"run_id": lib["run_id"], "timeline": lib["timeline"],
            "items": [{k: v for k, v in it.items() if k != "path" and not k.startswith("_")} for it in lib["items"]]}


@app.get("/api/library/{i}/thumb")
def library_thumb(i: int):
    it = lib_item(i)
    f = _lib_files.setdefault((_lib["key"], i), {"id": -1, "path": it["_p"], "kind": it["kind"]})
    data = make_thumb(f)
    hdr = {"Cache-Control": "private, max-age=300"}
    if data:
        return Response(data, media_type="image/jpeg", headers=hdr)
    return Response(VIDEO_SVG if it["kind"] == "video" else BROKEN_SVG, media_type="image/svg+xml", headers=hdr)


@app.get("/api/library/{i}/file")
def library_file(i: int):
    """Full-resolution file. Formats browsers can't show (HEIC, TIFF...) are converted to JPEG on the fly."""
    p = lib_item(i)["_p"]
    ext = p.suffix.lower()
    if ext in BROWSER_IMG or ext in VIDEO_EXT:
        return FileResponse(p)
    try:
        with Image.open(p) as im:
            im = ImageOps.exif_transpose(im).convert("RGB")
            im.thumbnail((3200, 3200))
            buf = io.BytesIO()
            im.save(buf, "JPEG", quality=90)
        return Response(buf.getvalue(), media_type="image/jpeg")
    except Exception:
        return Response(BROKEN_SVG, media_type="image/svg+xml")


def launch_folder(path: Path) -> None:
    if sys.platform.startswith("win"):
        os.startfile(str(path))  # noqa: S606 - local desktop app, path is server-derived
    else:
        subprocess.Popen(["open" if sys.platform == "darwin" else "xdg-open", str(path)])


@app.post("/api/open-folder")
async def open_folder(request: Request):
    body = await request.json()
    lib = get_library()
    if not lib:
        raise HTTPException(404, "Nothing sorted yet")
    cat, day = body.get("category"), body.get("day")
    sel = [it for it in lib["items"] if (not cat or it["category"] == cat) and (not day or it["day"] == day)]
    root = (S.folder / SORT_DIR).resolve()
    dirs = {Path(it["path"]).resolve().parent for it in sel}
    target = next(iter(dirs)) if len(dirs) == 1 else root
    if root != target and root not in target.parents or not target.is_dir():
        target = root
    try:
        launch_folder(target)
    except Exception as e:
        raise HTTPException(500, f"Couldn't open the folder: {e}")
    return {"opened": str(target)}


# ---- custom (hand-picked) collages
def custom_dir() -> Path:
    d = book_dir() / "custom"
    d.mkdir(parents=True, exist_ok=True)
    return d


@app.post("/api/collage/custom")
async def collage_custom(request: Request):
    body = await request.json()
    ids = [int(x) for x in body.get("items", [])][:6]
    items = []
    for i in ids:
        it = lib_item(i)
        if it["kind"] != "image":
            raise HTTPException(400, "Collages can only use photos, not videos.")
        items.append({"path": str(it["_p"]), "category": it["category"], "taken": it["date"]})
    layout, title, caption = str(body.get("layout", "")), str(body.get("title", ""))[:80], str(body.get("caption", ""))[:120]
    try:
        img = await asyncio.to_thread(build_custom, items, layout, title, caption)
    except ValueError as e:
        raise HTTPException(400, str(e))
    name = f"custom_{int(time.time() * 1000)}.png"
    out = custom_dir()
    img.save(out / name, "PNG")
    meta = {"title": title.strip() or "Custom Collage", "caption": caption, "layout": layout,
            "categories": sorted({i["category"] for i in items}), "photos": [Path(i["path"]).name for i in items]}
    (out / (name + ".json")).write_text(json.dumps(meta), encoding="utf-8")
    return {"name": name, "url": f"/api/collage/custom/{name}", **meta}


@app.get("/api/collage/custom/{name}")
def collage_custom_get(name: str, download: int = 0):
    if not re.fullmatch(r"custom_\d+\.png", name) or not S.folder:
        raise HTTPException(404)
    p = custom_dir() / name
    if not p.is_file():
        raise HTTPException(404)
    return FileResponse(p, media_type="image/png", filename=name if download else None,
                        content_disposition_type="attachment" if download else "inline")


@app.post("/api/book/add-custom")
async def book_add_custom(request: Request):
    name = (await request.json()).get("name", "")
    if not re.fullmatch(r"custom_\d+\.png", name) or not S.folder:
        raise HTTPException(400, "Bad collage name")
    src, side = custom_dir() / name, custom_dir() / (name + ".json")
    if not src.is_file() or not side.is_file():
        raise HTTPException(404, "Collage not found")
    if S.running or S.book_running:
        raise HTTPException(409, "Busy - try again in a moment")
    if not load_book():                                  # make sure the book exists first
        hist = read_history(S.folder)
        if not hist:
            raise HTTPException(400, "Sort your photos first")
        S.book_running = True
        try:
            await asyncio.to_thread(build_book, hist[-1]["entries"], S.folder.name, S.folder / SORT_DIR, hist[-1]["id"])
        finally:
            S.book_running = False
    book, meta = load_book(), json.loads(side.read_text(encoding="utf-8"))
    if any(p.get("custom_src") == name for p in book["pages"]):
        return {"page": next(i for i, p in enumerate(book["pages"]) if p.get("custom_src") == name) + 1, "already": True}
    fname = "page_c" + name[len("custom_"):]
    shutil.copy2(src, book_dir() / fname)
    phrases = {"custom", "custom collage", meta["title"].lower(), *(c.lower() for c in meta["categories"]),
               *(n.lower() for n in meta["photos"])}
    page = {"kind": "collage", "title": meta["title"], "sub": meta["caption"], "layout": meta["layout"], "file": fname,
            "categories": meta["categories"], "tags": ["custom"], "photos": meta["photos"], "search": sorted(phrases),
            "custom_src": name}
    book["pages"].insert(len(book["pages"]) - 1, page)   # before the closing page
    (book_dir() / "book.json").write_text(json.dumps(book, indent=1), encoding="utf-8")
    return {"page": len(book["pages"]) - 1}


# ---- travel book
def book_dir() -> Path:
    return S.folder / SORT_DIR / COLLAGE_DIR


def load_book() -> dict | None:
    p = book_dir() / "book.json" if S.folder else None
    try:
        return json.loads(p.read_text(encoding="utf-8")) if p and p.exists() else None
    except Exception:
        return None


def run_book_job(run: dict) -> None:
    try:
        build_book(run["entries"], S.folder.name, S.folder / SORT_DIR, run["id"],
                   progress=lambda d, t: S.emit("book_progress", done=d, total=t))
        S.emit("book_done")
    except Exception as e:
        import traceback
        traceback.print_exc()
        S.emit("book_error", message=str(e))
    finally:
        S.book_running = False


@app.post("/api/book/build")
async def book_build(request: Request):
    if not S.folder:
        raise HTTPException(400, "Select a folder first")
    hist = read_history(S.folder)
    if not hist:
        raise HTTPException(400, "Sort your photos first - the Travel Book is made from the sorted folders.")
    if S.running or S.book_running:
        raise HTTPException(409, "Busy - try again in a moment")
    body = await request.json()
    book = load_book()
    if book and book.get("run_id") == hist[-1]["id"] and not body.get("force"):
        return {"ready": True}
    S.book_running = True
    threading.Thread(target=run_book_job, args=(hist[-1],), daemon=True).start()
    return {"ready": False}


@app.get("/api/book")
def book_get():
    book = load_book()
    if not book:
        raise HTTPException(404, "No book yet")
    return book


@app.get("/api/book/page/{n}")
def book_page(n: int, download: int = 0):
    book = load_book()
    if not book or not 0 <= n < len(book["pages"]):
        raise HTTPException(404)
    p = book["pages"][n]
    name = f"{book['title'].replace(' ', '_')}_collage_{n:02}.png"
    return FileResponse(book_dir() / p["file"], media_type="image/png",
                        filename=name if download else None,
                        content_disposition_type="attachment" if download else "inline")


@app.get("/api/book/pdf")
def book_pdf():
    book = load_book()
    if not book:
        raise HTTPException(404, "No book yet")
    pdf = export_pdf(book, book_dir())
    return FileResponse(pdf, media_type="application/pdf", filename=f"{book['title'].replace(' ', '_')}_Travel_Book.pdf")


@app.get("/api/thumb/{fid}")
def thumb(fid: int):
    if not 0 <= fid < len(S.files):
        raise HTTPException(404)
    f = S.files[fid]
    data = make_thumb(f)
    if data:
        return Response(data, media_type="image/jpeg", headers={"Cache-Control": "private, max-age=300"})
    return Response(VIDEO_SVG if f["kind"] == "video" else BROKEN_SVG, media_type="image/svg+xml",
                    headers={"Cache-Control": "private, max-age=300"})


@app.get("/api/stream")
async def stream(request: Request, after: int = -1):
    last = int(request.headers.get("last-event-id", after))

    async def gen():
        nonlocal last
        idle = 0
        while not await request.is_disconnected():
            with S.lock:
                batch = S.events[last + 1:last + 201]
            if batch:
                idle = 0
                for ev in batch:
                    last += 1
                    yield f"id: {last}\ndata: {json.dumps(ev)}\n\n"
            else:
                idle += 1
                if idle % 150 == 0:
                    yield ": keepalive\n\n"
                await asyncio.sleep(0.1)

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html", headers={"Cache-Control": "no-store"})


app.mount("/static", StaticFiles(directory=STATIC), name="static")

def main() -> None:
    import socket
    import webbrowser
    import uvicorn

    host, port = "127.0.0.1", 8765          # localhost only: nothing is exposed to the network
    url = f"http://{host}:{port}"
    with socket.socket() as probe:
        if probe.connect_ex((host, port)) == 0:
            print(f"Trip Studio is already running at {url} - opening it in your browser.")
            webbrowser.open(url)
            return
    if not os.environ.get("TRIP_STUDIO_NO_BROWSER"):
        threading.Timer(1.5, lambda: webbrowser.open(url)).start()
    print(f"\n  Trip Studio is running at {url}\n  (your browser should open automatically - press Ctrl+C here to stop)\n")
    uvicorn.run(app, host=host, port=port, log_level="warning")


if __name__ == "__main__":
    main()
