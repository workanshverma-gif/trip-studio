"""End-to-end safety/quality checks for Trip Studio.

    .venv\\Scripts\\python tests\\run_checks.py              # full feature + undo + edge-case suite
    .venv\\Scripts\\python tests\\run_checks.py --stress 1200 # scan/thumbnail speed on a big folder
    .venv\\Scripts\\python tests\\run_checks.py --folder D:\\my\\photos   # dry-run (touches nothing) on your own folder

Everything runs in-process against the real FastAPI app using a throw-away sample folder.
"""
from __future__ import annotations

import argparse
import hashlib
import os
import random
import shutil
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))

from fastapi.testclient import TestClient  # noqa: E402
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter  # noqa: E402

import main  # noqa: E402

client = TestClient(main.app)
results: list[tuple[bool, str]] = []


def check(cond: bool, msg: str) -> None:
    results.append((bool(cond), msg))
    print(("  PASS  " if cond else "  FAIL  ") + msg)


# ------------------------------------------------------------------ sample data
def scene(seed: int, warm: bool = False) -> Image.Image:
    rnd = random.Random(seed)
    base = (230, 140, 60) if warm else tuple(rnd.randint(40, 200) for _ in range(3))
    im = Image.new("RGB", (1200, 800), base)
    d = ImageDraw.Draw(im)
    for _ in range(60):
        x, y = rnd.randint(0, 1000), rnd.randint(0, 600)
        d.rectangle([x, y, x + rnd.randint(30, 200), y + rnd.randint(30, 200)],
                    outline=tuple(rnd.randint(0, 255) for _ in range(3)), width=4)
    return im


def save(im: Image.Image, path: Path, taken: str | None = None, camera: bool = True) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    ex = im.getexif()
    if camera:
        ex[271] = "TestCam"
    if taken:
        ex.get_ifd(0x8769)[36867] = taken
    if camera or taken:
        im.save(path, exif=ex, quality=92)
    else:
        im.save(path, quality=92)


def make_sample(d: Path) -> None:
    shutil.rmtree(d, ignore_errors=True)
    d.mkdir(parents=True)
    for i in range(10):                                   # 10 normal photos over 3 days
        save(scene(100 + i, warm=i % 3 == 0), d / f"IMG_{i:03}.jpg", f"2025:10:{12 + i // 4} 1{i % 10}:15:00")
    b = scene(1)                                          # burst of 3 + exact duplicate
    save(b, d / "burst_a.jpg", "2025:10:12 09:00:10")
    save(b.filter(ImageFilter.GaussianBlur(2)), d / "burst_b.jpg", "2025:10:12 09:00:11")
    save(b.filter(ImageFilter.GaussianBlur(6)), d / "burst_c.jpg", "2025:10:12 09:00:12")
    shutil.copy2(d / "IMG_002.jpg", d / "IMG_002_copy.jpg")
    for i in (1, 2):                                      # blurry
        save(scene(200 + i).filter(ImageFilter.GaussianBlur(14)), d / f"blurry_{i}.jpg", "2025:10:13 12:00:00")
    save(ImageEnhance.Brightness(scene(3)).enhance(0.04), d / "dark.jpg", "2025:10:13 23:30:00")
    for i in (1, 2):                                      # no EXIF at all
        save(scene(300 + i), d / f"no_exif_{i}.jpg", None, camera=False)
    s = Image.new("RGB", (1080, 2340), "white")           # phone screenshot, no metadata
    sd = ImageDraw.Draw(s)
    for y in range(80, 2300, 60):
        sd.text((60, y), "BOARDING PASS AI-203 DEL -> GOA Seat 14A UPI Ref 4839201", fill="black")
    s.save(d / "Screenshot_2025-10-12.png")
    try:                                                  # iPhone HEIC
        import pillow_heif
        pillow_heif.from_pillow(scene(400)).save(d / "IMG_9999.HEIC", quality=80)
    except Exception as e:
        print("  (could not create HEIC sample:", e, ")")
    (d / "corrupt.jpg").write_bytes((d / "IMG_000.jpg").read_bytes()[:3000])   # truncated JPEG
    (d / "zero.jpg").write_bytes(b"")
    (d / "garbage.png").write_bytes(os.urandom(2048))
    (d / "clip.mp4").write_bytes(b"\0" * 5000)
    (d / "iphone.MOV").write_bytes(b"\0" * 7000)
    (d / "notes.txt").write_text("not media - must never be touched")
    save(scene(500), d / "trip" / "day2" / "IMG_000.jpg", "2025:10:14 08:00:00")  # same filename, nested folder
    (d / "empty_dir").mkdir()


def snapshot(d: Path) -> dict:
    snap = {}
    for p in sorted(d.rglob("*")):
        rel = p.relative_to(d).as_posix()
        snap[rel] = ("dir",) if p.is_dir() else ("file", hashlib.sha256(p.read_bytes()).hexdigest(), p.stat().st_mtime_ns)
    return snap


def diff(a: dict, b: dict) -> str:
    miss, extra = sorted(set(a) - set(b)), sorted(set(b) - set(a))
    changed = sorted(k for k in set(a) & set(b) if a[k] != b[k])
    return f"missing={miss[:5]} extra={extra[:5]} changed={changed[:5]}"


# ------------------------------------------------------------------ helpers
def select(d: Path) -> dict:
    r = client.post("/api/select-folder", json={"path": str(d)})
    assert r.status_code == 200, r.text
    return r.json()


def run_sort(body: dict, timeout: float = 600) -> dict:
    start = len(main.S.events)
    r = client.post("/api/sort", json=body)
    if r.status_code != 200:
        return {"http": r.status_code, "detail": r.json().get("detail")}
    t0 = time.time()
    while main.S.running and time.time() - t0 < timeout:
        time.sleep(0.2)
    evs = main.S.events[start:]
    done = next((e for e in evs if e["type"] == "done"), None)
    err = next((e for e in evs if e["type"] == "error"), None)
    return {"http": 200, "done": done, "error": err, "files": [e for e in evs if e["type"] == "file"],
            "picks": [e for e in evs if e["type"] == "pick"], "events": evs}


def where(d: Path, name: str) -> list[str]:
    sd = d / main.SORT_DIR
    return [p.parent.relative_to(sd).as_posix() for p in sd.rglob(name)] if sd.exists() else []


# ------------------------------------------------------------------ the suite
def suite() -> None:
    work = Path(tempfile.mkdtemp(prefix="trip_studio_test_"))
    d = work / "Goa Trip"
    make_sample(d)
    original = snapshot(d)
    n_media = sum(1 for k, v in original.items() if v[0] == "file" and Path(k).suffix.lower() in main.IMAGE_EXT | main.VIDEO_EXT)
    print(f"\nSample folder: {d}  ({len([k for k, v in original.items() if v[0] == 'file'])} files)")

    print("\n[1] Folder scan & thumbnails")
    info = select(d)
    check(info["total"] == n_media, f"scan finds all {n_media} media files (found {info['total']}); .txt ignored")
    check(any(f["name"].lower().endswith(".heic") for f in main.S.files), "HEIC photo is recognised")
    bad = []
    for f in main.S.files:
        r = client.get(f"/api/thumb/{f['id']}")
        if r.status_code != 200:
            bad.append(f["name"])
    check(not bad, f"every thumbnail request returns 200, incl. corrupted/zero-byte/video/HEIC (bad: {bad})")
    heic = next((f for f in main.S.files if f["name"].lower().endswith(".heic")), None)
    check(heic is None or client.get(f"/api/thumb/{heic['id']}").headers["content-type"] == "image/jpeg", "HEIC renders a real JPEG thumbnail")
    check(snapshot(d) == original, "scanning/thumbnails touched nothing")

    print("\n[2] Preview (dry run) must not touch files")
    r = run_sort({"dry": True, "timeline": True, "custom": "Dogs, Coffee", "copy": True, "filter": True})
    check(r["error"] is None and r["done"] is not None, f"dry run completes without error ({r['error']})")
    check(not (d / main.SORT_DIR).exists() and snapshot(d) == original, "dry run created no folders and changed no files")
    plan_total = sum(n for _, n in r["done"]["plan"])
    check(plan_total == len(r["files"]) + len(r["picks"]), "preview breakdown adds up to files + hero copies")
    check(len(r["files"]) == info["total"], "every file produced a live progress event")
    check(any(e["type"] == "status" for e in r["events"]), "live status messages streamed")
    start = next(e for e in r["events"] if e["type"] == "start")
    check(start["categories"][-2:] == ["Dogs", "Coffee"], "custom categories 'Dogs, Coffee' added as live categories")

    print("\n[3] Real sort, COPY mode + timeline")
    r = run_sort({"dry": False, "timeline": True, "custom": "Dogs", "copy": True, "filter": True})
    check(r["error"] is None and r["done"], f"copy sort completes ({r['error']})")
    for rel, v in original.items():
        if v[0] == "file":
            if (d / rel).exists() and snapshot_file(d / rel) == v:
                continue
            check(False, f"original intact: {rel}")
            break
    else:
        check(True, "all originals untouched (same bytes + timestamps) in copy mode")
    sd = d / main.SORT_DIR
    check((sd / main.HISTORY).exists(), "sort_history.json written")
    names = {f["name"]: f for f in r["files"]}
    check("Needs_Review_Duplicates" in where(d, "blurry_1.jpg"), "blurry photo -> Needs_Review_Duplicates")
    check("Needs_Review_Duplicates" in where(d, "dark.jpg"), "too-dark photo -> Needs_Review_Duplicates")
    check("Needs_Review_Duplicates" in where(d, "corrupt.jpg") and "Needs_Review_Duplicates" in where(d, "zero.jpg")
          and "Needs_Review_Duplicates" in where(d, "garbage.png"), "corrupted/zero-byte/garbage images parked in review (no crash)")
    shot = where(d, "Screenshot_2025-10-12.png")
    check(any(s.endswith("Tickets_and_Receipts") for s in shot), f"screenshot -> Tickets_and_Receipts ({shot})")
    burst = [n for n in ("burst_a.jpg", "burst_b.jpg", "burst_c.jpg") if not any("Needs_Review" in w for w in where(d, n))]
    check(burst == ["burst_a.jpg"], f"burst keeps only the sharpest shot (kept: {burst})")
    dupes = [n for n in ("IMG_002.jpg", "IMG_002_copy.jpg") if not any("Needs_Review" in w for w in where(d, n))]
    check(len(dupes) == 1, f"exact duplicate: exactly one copy stays in main folders (kept: {dupes})")
    check(any(w.endswith("/Videos") for w in where(d, "clip.mp4")) and any(w.endswith("/Videos") for w in where(d, "iphone.MOV")), ".mp4 and .MOV videos -> Day N - date/Videos")
    und = where(d, "no_exif_1.jpg")
    import re as _re
    check(und and _re.match(r"Day \d+ - \d{4}-\d{2}-\d{2}/", und[0]), f"photo without EXIF falls back to file modified date -> Day N - YYYY-MM-DD ({und})")
    mt = __import__("datetime").datetime.fromtimestamp(os.path.getmtime(d / "no_exif_1.jpg")).date().isoformat()
    check(und and und[0].split("/")[0].endswith(mt), f"...and it is the file's own date ({mt})")
    if heic:
        check(not any("Needs_Review" in w for w in where(d, heic["name"])), "HEIC photo analysed and sorted normally")
    check(len(where(d, "IMG_000.jpg")) >= 2, "same filename from two folders both kept (no overwrite)")
    check(any(w.startswith("Day 1 - 2025-10-12/") for w in where(d, "IMG_000.jpg")), f"Day-by-Day: IMG_000 filed under 'Day 1 - 2025-10-12/<category>' ({where(d, 'IMG_000.jpg')})")
    check((sd / "Top_Picks_Hero_Shots").exists() and len(list((sd / "Top_Picks_Hero_Shots").iterdir())) <= 25, "hero shots copied (<= 25)")
    check(any(p.name.startswith("Day ") for p in sd.iterdir()), "timeline folders are named 'Day N - YYYY-MM-DD'")
    r2 = run_sort({"dry": False, "timeline": True, "copy": True})
    check(r2.get("http") == 409, "a second sort without undo is refused (409), nothing duplicated")

    print("\n[3b] Library, safe file serving, custom collage")
    lib = client.get("/api/library").json()
    items = lib["items"]
    check(lib["timeline"] is True and len(items) > 10 and all("path" not in it and not any(k.startswith("_") for k in it) for it in items),
          "/api/library lists sorted photos (no server paths leaked)")
    img = next(it for it in items if it["kind"] == "image" and it["category"] not in ("Top Picks", "Needs Review"))
    r = client.get(f"/api/library/{img['i']}/thumb")
    r = client.get(f"/api/library/{img['i']}/file")
    check(r.status_code == 200 and r.headers["content-type"].startswith("image/"), "full-resolution file endpoint serves a sorted photo")
    check(client.get("/api/library").status_code == 200, "/api/library still OK after thumbnails were requested")
    check(client.get("/api/library/99999/file").status_code == 404 and client.get("/api/library/-1/file").status_code in (404, 422), "unknown library index -> 404")
    heic_it = next((it for it in items if it["name"].lower().endswith(".heic")), None)
    if heic_it:
        check(client.get(f"/api/library/{heic_it['i']}/file").headers["content-type"] == "image/jpeg", "HEIC is converted to JPEG for the lightbox")
    for bad in ("..%2F..%2Fnotes.txt", "custom_1.png%2F..%2F..%2Fx", "x.png"):
        check(client.get(f"/api/collage/custom/{bad}").status_code == 404, f"custom collage name '{bad}' rejected")
    launched = []
    main.launch_folder = lambda path: launched.append(path)
    r = client.post("/api/open-folder", json={"category": img["category"]})
    root_dir = (d / main.SORT_DIR).resolve()
    check(r.status_code == 200 and launched and (launched[-1] == root_dir or root_dir in launched[-1].parents), "Open Folder opens a directory inside Sorted_Trip_Studio only")
    r = client.post("/api/open-folder", json={"category": "../../Windows"})
    check(r.status_code == 200 and launched[-1] == root_dir, "forged category can't escape: falls back to the Sorted root")
    imgs = [it["i"] for it in items if it["kind"] == "image" and it["category"] not in ("Top Picks", "Needs Review")]
    for lay, n in (("split", 2), ("editorial", 3), ("polaroid", 4), ("grid6", 6)):
        r = client.post("/api/collage/custom", json={"items": imgs[:n], "layout": lay, "title": "A very long custom title for my amazing trip to the mountains and the sea"})
        ok = r.status_code == 200 and client.get(r.json()["url"]).content[:4] == b"\x89PNG"
        check(ok, f"custom '{lay}' collage built from exactly {n} chosen photos")
    check(client.post("/api/collage/custom", json={"items": imgs[:3], "layout": "polaroid"}).status_code == 400, "wrong photo count for a layout -> clean 400")
    vid = next(it["i"] for it in items if it["kind"] == "video")
    check(client.post("/api/collage/custom", json={"items": [vid, imgs[0]], "layout": "split"}).status_code == 400, "videos can't be used in collages -> 400")
    made = client.post("/api/collage/custom", json={"items": imgs[:2], "layout": "split", "title": "Pair"}).json()
    add = client.post("/api/book/add-custom", json={"name": made["name"]})
    check(add.status_code == 200, "Save to Travel Book adds the collage (building the book first if needed)")
    pages = client.get("/api/book").json()["pages"]
    check(sum(1 for p in pages if p.get("custom_src")) == 1 and pages[-1]["kind"] == "end", "custom page inserted before the closing page")
    check(client.post("/api/book/add-custom", json={"name": made["name"]}).json().get("already"), "saving the same collage twice doesn't duplicate it")

    print("\n[4] Travel Book")
    b = client.post("/api/book/build", json={}).json()
    t0 = time.time()
    while not b.get("ready") and main.S.book_running and time.time() - t0 < 300:
        time.sleep(0.3)
    book = client.get("/api/book")
    check(book.status_code == 200 and len(book.json()["pages"]) >= 3, "book built (cover + collage pages + end)")
    pages = book.json()["pages"]
    check(all(client.get(f"/api/book/page/{i}").status_code == 200 for i in range(len(pages))), "every page image is served")
    dl = client.get("/api/book/page/1?download=1")
    check("attachment" in dl.headers.get("content-disposition", "") and dl.content[:4] == b"\x89PNG", "page download is a PNG attachment")
    pdf = client.get("/api/book/pdf")
    check(pdf.status_code == 200 and pdf.content[:4] == b"%PDF", "PDF export works")
    check(any("day 1" in p["search"] for p in pages if p["kind"] == "collage"), "pages carry searchable tags (Day N, categories)")

    print("\n[5] Undo (copy mode)")
    u = client.post("/api/undo", json={})
    check(u.status_code == 200, "undo succeeds")
    after = snapshot(d)
    check(after == original, "folder is byte-for-byte, timestamp-for-timestamp the original" + ("" if after == original else " -> " + diff(original, after)))
    check(not sd.exists(), "Sorted_Trip_Studio (incl. empty subfolders, book, history) fully removed")
    check(client.post("/api/undo", json={}).status_code == 404, "undo with nothing to undo -> clean 404")

    print("\n[6] Real sort, MOVE mode, filter OFF")
    select(d)
    r = run_sort({"dry": False, "timeline": False, "custom": "", "copy": False, "filter": False})
    check(r["error"] is None and r["done"], f"move sort completes ({r['error']})")
    check(not (d / "IMG_001.jpg").exists() and not (d / "clip.mp4").exists(), "files were really moved out of the source folder")
    left = [p.name for p in d.iterdir() if p.is_file()]
    check(set(left) <= {"notes.txt"}, f"only the non-media file remains in place ({left})")
    check((d / "notes.txt").read_text() == "not media - must never be touched", "non-media file untouched")
    check(where(d, "blurry_1.jpg") and "Needs_Review_Duplicates" not in where(d, "blurry_1.jpg"), "filter OFF: blurry photos are sorted normally")
    check("Needs_Review_Duplicates" in where(d, "corrupt.jpg"), "filter OFF: unreadable files still safely parked")
    u = client.post("/api/undo", json={})
    after = snapshot(d)
    check(u.status_code == 200 and after == original, "undo after MOVE restores every file to its exact original path" + ("" if after == original else " -> " + diff(original, after)))
    check(not (d / main.SORT_DIR).exists(), "no leftover sorted folders")
    shutil.rmtree(work, ignore_errors=True)


def snapshot_file(p: Path) -> tuple:
    return ("file", hashlib.sha256(p.read_bytes()).hexdigest(), p.stat().st_mtime_ns)


def stress(n: int) -> None:
    work = Path(tempfile.mkdtemp(prefix="trip_studio_stress_"))
    d = work / "big"
    d.mkdir()
    print(f"\nGenerating {n} photos…")
    tpl = [scene(i) for i in range(8)]
    for i in range(n):
        im = tpl[i % 8].copy()
        ImageDraw.Draw(im).text((10, 10), str(i), fill="white")
        im.save(d / f"IMG_{i:05}.jpg", quality=88)
    t = time.time(); info = select(d); t_scan = time.time() - t
    check(info["total"] == n, f"scanned {n} photos in {t_scan:.2f}s")
    check(t_scan < 5, "folder selection responds in < 5s")
    t = time.time(); client.get("/api/state"); t_state = time.time() - t
    check(t_state < 0.5, f"/api/state returns instantly ({t_state * 1000:.0f} ms)")
    t = time.time()
    for fid in info["ids"][:60]:
        assert client.get(f"/api/thumb/{fid}").status_code == 200
    t_sw = time.time() - t
    check(t_sw < 6, f"first 60 swirl thumbnails ready in {t_sw:.2f}s")
    t = time.time()
    with ThreadPoolExecutor(16) as ex:
        codes = list(ex.map(lambda i: client.get(f"/api/thumb/{i}").status_code, range(min(n, 400))))
    t_par = time.time() - t
    check(all(c == 200 for c in codes), f"400 thumbnails fetched in parallel in {t_par:.2f}s")
    t = time.time(); client.get("/api/thumb/0"); check(time.time() - t < 0.05, "cached thumbnail is served in < 50 ms")
    shutil.rmtree(work, ignore_errors=True)


def user_folder(path: str) -> None:
    d = Path(path)
    before = snapshot(d) if sum(1 for _ in d.rglob("*")) < 20000 else None
    info = select(d)
    print(f"{info['images']} photos, {info['videos']} videos")
    r = run_sort({"dry": True, "timeline": True, "copy": True, "filter": True})
    check(r["error"] is None and r["done"], f"dry run on your folder completed ({r['error']})")
    if r["done"]:
        for k, v in r["done"]["plan"]:
            print(f"    {v:5}  {k}")
    check(before is None or snapshot(d) == before, "your folder was not modified")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--stress", type=int, metavar="N")
    ap.add_argument("--folder")
    a = ap.parse_args()
    if a.stress:
        stress(a.stress)
    elif a.folder:
        user_folder(a.folder)
    else:
        suite()
    failed = [m for ok, m in results if not ok]
    print(f"\n{len(results) - len(failed)}/{len(results)} checks passed")
    sys.exit(1 if failed else 0)
