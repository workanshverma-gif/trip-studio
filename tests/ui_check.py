"""Real-browser smoke test (Playwright + installed Edge/Chrome): drives the actual UI and fails on ANY console error.

    .venv\\Scripts\\python tests\\ui_check.py
Starts its own server on port 8766 and a throw-away sample folder; "Open Folder" calls are intercepted so no Explorer window pops up.
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "app"))
from run_checks import make_sample  # noqa: E402

PORT = 8766
BASE = f"http://127.0.0.1:{PORT}"
fails: list[str] = []


def check(cond, msg):
    print(("  PASS  " if cond else "  FAIL  ") + msg)
    if not cond:
        fails.append(msg)


def post(path, body):
    req = urllib.request.Request(BASE + path, json.dumps(body).encode(), {"Content-Type": "application/json"})
    return json.load(urllib.request.urlopen(req, timeout=60))


def main():
    work = Path(tempfile.mkdtemp(prefix="trip_studio_ui_"))
    folder = work / "Goa Trip"
    make_sample(folder)
    srv = subprocess.Popen([str(ROOT / ".venv/Scripts/python.exe"), "-m", "uvicorn", "main:app", "--app-dir", str(ROOT / "app"),
                            "--port", str(PORT), "--log-level", "warning"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(60):
            try:
                urllib.request.urlopen(BASE + "/api/state", timeout=1); break
            except Exception:
                time.sleep(0.5)
        post("/api/select-folder", {"path": str(folder)})
        errors: list[str] = []
        with sync_playwright() as pw:
            browser = pw.chromium.launch(channel="msedge")
            ctx = browser.new_context(viewport={"width": 1440, "height": 950}, accept_downloads=True)
            page = ctx.new_page()
            page.on("console", lambda m: errors.append(f"console.{m.type}: {m.text}") if m.type in ("error", "warning") else None)
            page.on("pageerror", lambda e: errors.append(f"pageerror: {e}"))
            page.on("response", lambda r: errors.append(f"HTTP {r.status} {r.url}") if r.status >= 400 else None)
            opened = []
            def fake_open(route):
                opened.append(route.request.post_data)
                route.fulfill(status=200, content_type="application/json", body='{"opened":"(intercepted)"}')
            page.route("**/api/open-folder", fake_open)

            print("\n[A] Dashboard loads")
            page.goto(BASE)
            page.wait_for_selector("#catList .cat")
            check(page.locator("#catList .cat").count() == 6 and page.locator("#specialList .cat").count() == 3, "6 category cards + 3 special cards render")
            check(page.locator(".tab").count() == 3, "tabs: Dashboard | Travel Book | Custom Collage")
            check(page.locator("#btnStart").is_enabled(), "Start Sorting enabled for the selected folder")

            print("\n[B] Sort with Day-by-Day timeline")
            page.click("label.toggle:has(#optTimeline)")
            check(page.is_checked("#optTimeline"), "timeline toggle switches on")
            sent = {}
            page.on("request", lambda rq: sent.update(json.loads(rq.post_data)) if rq.url.endswith("/api/sort") and rq.post_data else None)
            page.click("#btnStart")
            page.wait_for_selector("#summary:not([hidden])", timeout=300_000)
            check(sent.get("timeline_mode") is True, f"frontend sends timeline_mode: true (sent {sent.get('timeline_mode')})")
            days = sorted(p.name for p in (folder / "Sorted_Trip_Studio").iterdir() if p.name.startswith("Day "))
            check(len(days) >= 3 and all(len(d) == len("Day 1 - 2025-10-12") and d[8:11] == " - " or " - 20" in d for d in days), f"day folders on disk: {days}")
            page.click("#btnSumClose")
            page.wait_for_selector("#timelineView:not([hidden])")
            n_days = page.locator(".tl-day").count()
            check(n_days == len(days), f"timeline UI shows {n_days} day sections")
            check(page.locator(".tl-day.open .ph").count() > 0, "first day opens with photos")
            page.click(".tl-day:nth-child(2) .tl-dh")
            check(page.locator(".tl-day:nth-child(2).open .ph").count() > 0, "clicking another day expands its photos")

            print("\n[C] Lightbox")
            page.locator(".tl-day.open .ph").first.click()
            page.wait_for_selector("#lightbox:not([hidden])")
            page.wait_for_selector("#lbStage img")
            first = page.inner_text("#lbName")
            check(page.evaluate("document.querySelector('#lbStage img').naturalWidth") >= 800, "lightbox loads the full-resolution image")
            page.keyboard.press("ArrowRight")
            check(page.inner_text("#lbName") != first or page.locator("#lbMeta").inner_text().startswith("1 /"), "Next arrow works (keyboard)")
            page.click("#lbNext"); page.click("#lbPrev")
            with ctx.expect_page() as pop:
                page.click("#lbTab")
            check("/api/library/" in pop.value.url, "Open in New Tab opens the full-size file")
            pop.value.close()
            page.keyboard.press("Escape")
            check(page.locator("#lightbox").is_hidden(), "Esc closes the lightbox")

            print("\n[D] Category cards -> gallery -> collage from inside a folder")
            idx = page.evaluate("[...document.querySelectorAll('#catList .cat')].findIndex(c => +c.querySelector('.n').textContent > 0)")
            check(idx >= 0, "at least one category card has photos")
            # empty card must give a friendly message, not a broken modal
            empty = page.evaluate("[...document.querySelectorAll('#catList .cat')].findIndex(c => +c.querySelector('.n').textContent === 0)")
            if empty >= 0:
                page.locator("#catList .cat").nth(empty).click()
                page.wait_for_selector("#toast:not([hidden])")
                check(page.locator("#gallery").is_hidden(), "empty folder shows a message instead of an empty gallery")
            card = page.locator("#catList .cat").nth(idx)
            title = card.locator(".cat-head span").first.inner_text()
            card.click()
            page.wait_for_selector("#gallery:not([hidden])")
            n_tiles = page.locator("#galGrid .ph").count()
            check(n_tiles > 0 and title.split()[-1] in page.inner_text("#galTitle"), f"clicking '{title}' opens a gallery with {n_tiles} photos")
            page.click("#galOpenFolder")
            page.wait_for_timeout(300)
            check(opened and json.loads(opened[-1]).get("category"), "Open Folder on Computer calls the backend with this folder")
            page.locator("#galGrid .ph").first.click()
            page.wait_for_selector("#lightbox:not([hidden])")
            page.keyboard.press("Escape")
            # find a gallery with >= 2 photos for the collage-from-folder flow
            if n_tiles < 2:
                page.click("#galClose")
                page.locator("#specialList .cat").first.click()
                page.wait_for_selector("#gallery:not([hidden])")
            sel_n = min(4, page.locator("#galGrid .ph .ck").count())
            for i in range(sel_n):
                page.locator("#galGrid .ph").nth(i).hover()
                page.locator("#galGrid .ph .ck").nth(i).check()
            bar = page.locator("#galBarHost .cbar")
            check(bar.is_visible() and f"{sel_n} photo" in bar.inner_text(), f"floating bar says '{sel_n} photo(s) selected'")
            lay = {2: "split", 3: "editorial", 4: "polaroid"}.get(sel_n)
            if lay:
                bar.locator(f".lbtn[data-k={lay}]").click()
                bar.locator(".ctitle").fill("Folder favourites")
                bar.locator(".create").click()
                page.wait_for_selector("#cpreview:not([hidden])", timeout=60_000)
                page.wait_for_function("document.querySelector('#cpImg').naturalWidth > 500")
                check(True, f"collage created from {sel_n} picked photos and previewed")
                with page.expect_download() as dl:
                    page.click("#cpDownload")
                check(dl.value.suggested_filename.endswith(".png"), f"Download PNG works ({dl.value.suggested_filename})")
                page.click("#cpSave")
                page.wait_for_function("document.querySelector('#cpSave').textContent.includes('Saved')")
                check(True, "Save to Travel Book works")
                page.click("#cpClose")
            page.click("#galClose")

            print("\n[E] Custom Collage tab")
            page.click('.tab[data-tab="collage"]')
            page.wait_for_selector("#ccGrid .ph")
            check(page.locator("#viewDashboard").is_hidden(), "tab switches the view")
            total = page.locator("#ccGrid .ph").count()
            check(total >= 6, f"all sorted photos listed ({total})")
            for i in range(2):
                page.locator("#ccGrid .ph").nth(i).hover()
                page.locator("#ccGrid .ph .ck").nth(i).check()
            bar = page.locator("#ccBarHost .cbar")
            check("2 photos selected" in bar.inner_text(), "bar shows '2 photos selected'")
            check(bar.locator(".lbtn.on").get_attribute("data-k") == "split", "layout auto-picks 2-Photo Split")
            bar.locator(".ctitle").fill("Two of my favourites")
            bar.locator(".create").click()
            page.wait_for_selector("#cpreview:not([hidden])", timeout=60_000)
            page.wait_for_function("document.querySelector('#cpImg').naturalWidth > 500")
            check(True, "2-photo collage preview shown")
            page.click("#cpClose")
            for i in range(2, 6):
                page.locator("#ccGrid .ph").nth(i).hover()
                page.locator("#ccGrid .ph .ck").nth(i).check()
            check("6 photos selected" in bar.inner_text(), "6 photos selected")
            bar.locator(".create").click()
            page.wait_for_selector("#cpreview:not([hidden])", timeout=60_000)
            check(True, "6-photo grid collage created")
            page.click("#cpSave"); page.wait_for_function("document.querySelector('#cpSave').textContent.includes('Saved')")
            page.click("#cpClose")
            bar.locator(".clr").click()
            check(bar.is_hidden(), "Clear hides the bar")

            print("\n[F] Travel Book tab")
            page.click('.tab[data-tab="book"]')
            page.wait_for_selector("#book:not([hidden])")
            page.wait_for_selector("#flip .pg", timeout=120_000)
            n_pages = page.locator("#flip .pg").count()
            book = json.load(urllib.request.urlopen(BASE + "/api/book"))
            check(any(p.get("custom_src") for p in book["pages"]), f"custom collages saved into the book ({n_pages} pages)")
            page.fill("#bookSearch", "custom")
            page.wait_for_selector("#matchChips .chip")
            check(page.locator("#matchChips .chip").count() >= 1, "search finds the custom collage pages")
            page.click("#btnBookClose")
            check("active" in page.locator('.tab[data-tab="collage"]').get_attribute("class"), "closing the book returns to the tab you came from")

            page.click('.tab[data-tab="book"]'); page.wait_for_selector("#flip .pg", timeout=60_000)
            check(page.locator("#flip .pg").count() == n_pages, "book re-opens after closing")
            page.set_viewport_size({"width": 1000, "height": 800}); page.wait_for_timeout(900)
            check(page.locator("#flip .pg").count() == n_pages, "book re-renders after a window resize")
            page.keyboard.press("ArrowRight"); page.wait_for_timeout(900)
            page.click("#btnBookClose")
            page.set_viewport_size({"width": 1440, "height": 950})

            print("\n[G] Undo")
            page.click('.tab[data-tab="dashboard"]')
            page.once("dialog", lambda d: d.accept())
            page.click("#btnUndo")
            page.wait_for_function("document.querySelector('#timelineView').hidden")
            check(not (folder / "Sorted_Trip_Studio").exists(), "undo removed Sorted_Trip_Studio (incl. custom collages)")

            print("\n[H] Console")
            errs = [e for e in errors if "favicon" not in e]
            for e in errs:
                print("     ", e)
            check(not errs, f"no console errors, page errors or failed requests ({len(errs)} found)")
            browser.close()
    finally:
        srv.terminate()
    print(f"\n{'ALL UI CHECKS PASSED' if not fails else str(len(fails)) + ' UI check(s) FAILED'}")
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
