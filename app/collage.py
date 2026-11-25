"""Auto-collage generator: groups sorted photos by day/category and lays them out as magazine pages."""
from __future__ import annotations

import json
import math
import random
from collections import OrderedDict
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps

W, H = 1080, 1920          # Instagram-Story-sized pages
M = 64
CREAM, INK, MUTED, ACCENT, LINE = (250, 247, 242), (43, 38, 32), (138, 127, 112), (224, 112, 58), (234, 223, 207)
COLLAGE_DIR = "Travel_Book_Collages"
CASCADE = Path(__file__).parent / "models" / "haarcascade_frontalface_default.xml"
SKIP_CATEGORIES = {"Needs Review", "Videos", "Top Picks", "Receipts & Tickets"}

_FONT_DIRS = ["C:/Windows/Fonts", "/usr/share/fonts/truetype/dejavu", "/Library/Fonts", "/System/Library/Fonts/Supplemental"]
_FONTS = {
    "serif": ["georgiab.ttf", "Georgia Bold.ttf", "DejaVuSerif-Bold.ttf"],
    "sans": ["segoeui.ttf", "Arial.ttf", "DejaVuSans.ttf"],
    "sansb": ["segoeuib.ttf", "Arial Bold.ttf", "DejaVuSans-Bold.ttf"],
    "hand": ["segoepr.ttf", "Bradley Hand Bold.ttf", "DejaVuSans-Oblique.ttf"],
}
_font_cache: dict = {}
_cascade = None
_faces: dict = {}


def font(kind: str, size: int) -> ImageFont.ImageFont:
    key = (kind, size)
    if key not in _font_cache:
        f = None
        for d in _FONT_DIRS:
            for name in _FONTS[kind]:
                try:
                    f = ImageFont.truetype(str(Path(d) / name), size)
                    break
                except OSError:
                    continue
            if f:
                break
        _font_cache[key] = f or ImageFont.load_default(size)
    return _font_cache[key]


# ------------------------------------------------------------------ smart cropping
def open_rgb(path: str, want: int = 2400) -> Image.Image:
    with Image.open(path) as im:
        im.draft("RGB", (want, want))
        im = ImageOps.exif_transpose(im).convert("RGB")
        im.thumbnail((want, want), Image.LANCZOS)
        return im


def detect_faces(path: str, im: Image.Image) -> list[tuple[float, float, float, float]]:
    """Face boxes (x0, y0, x1, y1) in `im` pixel coords, via OpenCV Haar cascade."""
    global _cascade
    if path in _faces:
        return _faces[path]
    if _cascade is None:
        _cascade = cv2.CascadeClassifier(str(CASCADE))
    faces: list = []
    if not _cascade.empty():
        s = 640 / max(im.size)
        small = im.resize((max(1, int(im.width * min(1, s))), max(1, int(im.height * min(1, s)))))
        gray = cv2.equalizeHist(cv2.cvtColor(np.asarray(small), cv2.COLOR_RGB2GRAY))
        k = im.width / small.width
        for x, y, w, h in _cascade.detectMultiScale(gray, 1.1, 5, minSize=(28, 28)):
            faces.append((x * k, y * k, (x + w) * k, (y + h) * k))
    _faces[path] = faces
    return faces


def smart_crop(path: str, w: int, h: int) -> Image.Image:
    """Crop to w:h keeping faces fully inside; falls back to a centre-weighted (slightly high) crop."""
    im = open_rgb(path, max(w, h) * 2)
    iw, ih = im.size
    ratio = w / h
    cw, ch = (ih * ratio, ih) if iw / ih > ratio else (iw, iw / ratio)
    faces = detect_faces(path, im)
    if faces:
        ux0, uy0 = min(f[0] for f in faces), min(f[1] for f in faces)
        ux1, uy1 = max(f[2] for f in faces), max(f[3] for f in faces)
        fx, fy = (ux0 + ux1) / 2, (uy0 + uy1) / 2
    else:
        fx, fy = iw * 0.5, ih * 0.45
    x0 = min(max(fx - cw / 2, 0), iw - cw)
    y0 = min(max(fy - ch / 2, 0), ih - ch)
    if faces:  # nudge window so the whole face group stays inside whenever it fits
        pad_x, pad_y = (ux1 - ux0) * 0.25, (uy1 - uy0) * 0.35
        if ux1 - ux0 + 2 * pad_x <= cw:
            x0 = min(max(x0, ux1 + pad_x - cw), ux0 - pad_x)
        if uy1 - uy0 + 2 * pad_y <= ch:
            y0 = min(max(y0, uy1 + pad_y - ch), uy0 - pad_y)
        x0 = min(max(x0, 0), iw - cw)
        y0 = min(max(y0, 0), ih - ch)
    return im.crop((int(x0), int(y0), int(x0 + cw), int(y0 + ch))).resize((w, h), Image.LANCZOS)


# ------------------------------------------------------------------ drawing helpers
def text_size(draw: ImageDraw.ImageDraw, text: str, f) -> tuple[int, int]:
    l, t, r, b = draw.textbbox((0, 0), text, font=f)
    return r - l, b - t


def shadowed(card: Image.Image, blur: int = 16, offset: int = 12, alpha: int = 85) -> Image.Image:
    pad = blur * 3
    out = Image.new("RGBA", (card.width + 2 * pad, card.height + 2 * pad), (0, 0, 0, 0))
    sh = Image.new("RGBA", out.size, (0, 0, 0, 0))
    mask = Image.new("L", out.size, 0)
    mask.paste(card.getchannel("A").point(lambda v: alpha if v else 0), (pad, pad + offset))
    sh.putalpha(mask.filter(ImageFilter.GaussianBlur(blur)))
    out.alpha_composite(sh)
    out.alpha_composite(card, (pad, pad))
    return out


def frame(photo: Image.Image, border: int, bottom: int | None = None, caption: str = "", sub: str = "") -> Image.Image:
    """White-bordered print (Polaroid when `bottom` is larger) as RGBA."""
    bottom = border if bottom is None else bottom
    card = Image.new("RGBA", (photo.width + 2 * border, photo.height + border + bottom), (255, 255, 255, 255))
    card.paste(photo, (border, border))
    if caption:
        d = ImageDraw.Draw(card)
        f = font("hand", 30)
        tw, _ = text_size(d, caption, f)
        d.text(((card.width - tw) / 2, photo.height + border + 14), caption, font=f, fill=INK)
        if sub:
            f2 = font("sans", 20)
            sw, _ = text_size(d, sub, f2)
            d.text(((card.width - sw) / 2, photo.height + border + 58), sub, font=f2, fill=MUTED)
    return card


def place(canvas: Image.Image, card: Image.Image, cx: float, cy: float, angle: float = 0) -> None:
    c = shadowed(card)
    if angle:
        c = c.rotate(angle, resample=Image.BICUBIC, expand=True)
    canvas.alpha_composite(c, (int(cx - c.width / 2), int(cy - c.height / 2)))


def new_page() -> Image.Image:
    img = Image.new("RGBA", (W, H), CREAM + (255,))
    d = ImageDraw.Draw(img)
    d.rectangle([28, 28, W - 29, H - 29], outline=LINE, width=2)
    return img


def fit_text(d: ImageDraw.ImageDraw, text: str, kind: str, size: int, min_size: int, max_w: int):
    """Largest font <= size that fits max_w; ellipsize if even min_size is too wide."""
    while size > min_size and text_size(d, text, font(kind, size))[0] > max_w:
        size -= 4
    f = font(kind, size)
    while len(text) > 3 and text_size(d, text, f)[0] > max_w:
        text = text[:-2].rstrip() + "…"
    return text, f


def header(canvas: Image.Image, title: str, subtitle: str, label: str = "") -> None:
    d = ImageDraw.Draw(canvas)
    if label:
        d.text((M, 78), label.upper(), font=font("sansb", 24), fill=ACCENT)
    t, f = fit_text(d, title, "serif", 84, 44, W - 2 * M)
    d.text((M, 112), t, font=f, fill=INK)
    s, f2 = fit_text(d, subtitle, "sans", 32, 22, W - 2 * M)
    d.text((M + 2, 222), s, font=f2, fill=MUTED)
    d.line([(M, 292), (M + 90, 292)], fill=ACCENT, width=5)


def footer(canvas: Image.Image, n: int) -> None:
    d = ImageDraw.Draw(canvas)
    t = f"—  {n}  —"
    tw, _ = text_size(d, t, font("sans", 24))
    d.text(((W - tw) / 2, H - 92), t, font=font("sans", 24), fill=MUTED)


def cap(p: dict) -> tuple[str, str]:
    t = p["taken_dt"].strftime("%b %d").replace(" 0", " ") if p["dated"] else "no date"
    return p["category"], t


# ------------------------------------------------------------------ layouts
def layout_feature(canvas, ph):
    w, h = W - 2 * M - 28, 1180
    c, t = cap(ph[0])
    place(canvas, frame(smart_crop(ph[0]["path"], w, h), 14), W / 2, 330 + h / 2 + 20, random.uniform(-1, 1))
    ImageDraw.Draw(canvas).text((M, 1580), f"{c}  ·  {t}", font=font("hand", 34), fill=INK)


def layout_editorial(canvas, ph):
    """2-photo editorial spread: wide hero on top, offset smaller frame + caption block below."""
    a = frame(smart_crop(ph[0]["path"], 940, 780), 14)
    b = frame(smart_crop(ph[1]["path"], 580, 600), 14)
    place(canvas, a, W / 2, 330 + a.height / 2)
    place(canvas, b, W - M - b.width / 2 - 4, 1180 + b.height / 2)
    d = ImageDraw.Draw(canvas)
    (c1, t1), (c2, t2) = cap(ph[0]), cap(ph[1])
    d.text((M, 1230), c2, font=font("serif", 40), fill=INK)
    d.text((M, 1285), t2, font=font("sans", 28), fill=MUTED)
    d.text((M, 1350), f"{c1}", font=font("hand", 30), fill=ACCENT)
    d.text((M, 1392), f"opening shot · {t1}", font=font("sans", 24), fill=MUTED)


def layout_magazine(canvas, ph):
    """3-photo magazine grid: one wide lead image over two portrait tiles."""
    a = frame(smart_crop(ph[0]["path"], 940, 760), 12)
    place(canvas, a, W / 2, 330 + a.height / 2)
    d = ImageDraw.Draw(canvas)
    for i, x in enumerate((M + 4 + 232, M + 4 + 232 + 488)):
        card = frame(smart_crop(ph[i + 1]["path"], 440, 580), 12)
        cy = 1170 + card.height / 2
        place(canvas, card, x, cy)
        c, t = cap(ph[i + 1])
        d.text((x - 232, 1170 + card.height + 22), f"{c} · {t}", font=font("sans", 24), fill=MUTED)


def layout_polaroid(canvas, ph):
    """4-photo Polaroid wall: tilted white-bordered prints with handwritten captions."""
    spots = [(300, 640, -4.5), (780, 740, 3.5), (320, 1280, 3), (770, 1370, -3.5)]
    for p, (cx, cy, ang) in zip(ph, spots):
        c, t = cap(p)
        card = frame(smart_crop(p["path"], 392, 392), 24, 118, c, t)
        place(canvas, card, cx, cy, ang)


def layout_grid6(canvas, ph):
    """6-photo grid: 2 columns x 3 rows of bordered prints."""
    for k, p in enumerate(ph):
        r, c = divmod(k, 2)
        place(canvas, frame(smart_crop(p["path"], 440, 440), 12), 300 + c * 488, 330 + 232 + r * 490)


LAYOUTS = {1: layout_feature, 2: layout_editorial, 3: layout_magazine, 4: layout_polaroid}
LAYOUT_NAMES = {1: "feature", 2: "editorial", 3: "magazine", 4: "polaroid"}


def chunk(photos: list, start_idx: int) -> list[list]:
    pattern, out, i, k = [3, 4, 2], [], 0, start_idx
    while i < len(photos):
        size = min(pattern[k % len(pattern)], len(photos) - i)
        out.append(photos[i:i + size])
        i += size
        k += 1
    return out


# ------------------------------------------------------------------ cover / end / book
def cover_page(photo_path: str, title: str, date_range: str, stats: str) -> Image.Image:
    img = smart_crop(photo_path, W, H).convert("RGBA")
    grad = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    gd = ImageDraw.Draw(grad)
    for y in range(H // 2, H):
        gd.line([(0, y), (W, y)], fill=(25, 18, 10, int(215 * ((y - H // 2) / (H / 2)) ** 1.5)))
    img.alpha_composite(grad)
    d = ImageDraw.Draw(img)
    d.rectangle([40, 40, W - 41, H - 41], outline=(255, 255, 255, 230), width=3)
    f = font("serif", 112)
    words, lines, cur = title.split(), [], ""
    for w in words:
        trial = (cur + " " + w).strip()
        if text_size(d, trial, f)[0] > W - 2 * M - 20 and cur:
            lines.append(cur); cur = w
        else:
            cur = trial
    lines.append(cur)
    y = H - 520 - 120 * (len(lines) - 1)
    d.text((M + 6, y - 90), "A TRAVEL BOOK", font=font("sansb", 28), fill=(255, 190, 140))
    for ln in lines[-3:]:
        d.text((M + 6, y), ln, font=f, fill="white")
        y += 124
    d.text((M + 8, y + 18), date_range, font=font("sans", 40), fill=(255, 255, 255, 235))
    d.text((M + 8, y + 76), stats, font=font("sans", 28), fill=(255, 255, 255, 190))
    return img


def end_page(stats: str) -> Image.Image:
    img = new_page()
    d = ImageDraw.Draw(img)
    for i, line in enumerate(("Until the", "next trip.")):
        tw, _ = text_size(d, line, font("serif", 96))
        d.text(((W - tw) / 2, 760 + i * 120), line, font=font("serif", 96), fill=INK)
    d.line([(W / 2 - 45, 1050), (W / 2 + 45, 1050)], fill=ACCENT, width=5)
    tw, _ = text_size(d, stats, font("sans", 30))
    d.text(((W - tw) / 2, 1090), stats, font=font("sans", 30), fill=MUTED)
    t = "Made locally with Trip Studio"
    tw, _ = text_size(d, t, font("sans", 24))
    d.text(((W - tw) / 2, H - 120), t, font=font("sans", 24), fill=MUTED)
    return img


def build_book(entries: list[dict], title: str, out_root: Path, run_id: int, progress=lambda d, t: None) -> dict:
    """entries: sort_history entries. Writes PNG pages + book.json into out_root/Travel_Book_Collages."""
    random.seed(7)
    out = out_root / COLLAGE_DIR
    out.mkdir(parents=True, exist_ok=True)
    photos = []
    for e in entries:
        if e["category"] in SKIP_CATEGORIES or not Path(e["dst"]).exists():
            continue
        dt = datetime.fromisoformat(e["taken"]) if e.get("taken") else datetime.fromtimestamp(Path(e["dst"]).stat().st_mtime)
        photos.append({"path": e["dst"], "category": e["category"], "taken_dt": dt, "dated": e.get("dated", True),
                       "golden": e.get("golden") or 0, "name": Path(e["dst"]).name})
    if not photos:
        raise ValueError("No sorted photos to build a book from.")
    photos.sort(key=lambda p: p["taken_dt"])

    use_days = sum(p["dated"] for p in photos) >= len(photos) / 2
    days = sorted({p["taken_dt"].date() for p in photos if p["dated"]})
    day_no = {d: i + 1 for i, d in enumerate(days)}
    groups: "OrderedDict[str, dict]" = OrderedDict()
    for p in photos:
        if use_days and not p["dated"]:
            key, head, sub = "undated", "Undated", "Photos without a capture date"
        elif use_days:
            d = p["taken_dt"].date()
            key, head, sub = f"day{day_no[d]}", f"Day {day_no[d]}", d.strftime("%A, %B ") + str(d.day)
        else:
            key, head, sub = p["category"], p["category"], "Collected moments"
        g = groups.setdefault(key, {"title": head, "sub": sub, "photos": []})
        g["photos"].append(p)
        p["day"] = head if use_days else None
    if "undated" in groups:
        groups.move_to_end("undated")

    hero = next((e for e in sorted((e for e in entries if e["category"] == "Top Picks" and Path(e["dst"]).exists()),
                                   key=lambda e: -(e.get("hero_score") or 0))), None)
    cover_src = hero["dst"] if hero else max(photos, key=lambda p: p["golden"])["path"]
    ref = [p for p in photos if p["dated"]] or photos
    first, last = ref[0]["taken_dt"], ref[-1]["taken_dt"]
    date_range = (f"{first.strftime('%b')} {first.day}" if first.date() == last.date()
                  else f"{first.strftime('%b')} {first.day} – {last.strftime('%b')} {last.day}") + f", {last.year}"
    stats = f"{len(photos)} photos" + (f" · {len(days)} days" if use_days else "")

    total_pages = sum(len(chunk(g["photos"], 0)) for g in groups.values()) + 2
    pages: list[dict] = []
    done = 0

    def save(img: Image.Image, name: str) -> str:
        nonlocal done
        img.convert("RGB").save(out / name, "PNG", optimize=False)
        done += 1
        progress(done, total_pages)
        return name

    nice_title = title.replace("_", " ").replace("-", " ").strip() or "My Trip"
    pages.append({"kind": "cover", "title": nice_title, "file": save(cover_page(cover_src, nice_title, date_range, stats), "page_000_cover.png"),
                  "search": [nice_title.lower(), "cover", date_range.lower()], "categories": [], "tags": []})
    n = 1
    layout_i = 0
    for g in groups.values():
        for part in chunk(g["photos"], layout_i):
            canvas = new_page()
            header(canvas, g["title"], g["sub"], "Trip Studio" if use_days else "Collection")
            LAYOUTS[len(part)](canvas, part)
            footer(canvas, n)
            cats = sorted({p["category"] for p in part})
            phrases = {g["title"].lower(), g["sub"].lower(), *(c.lower() for c in cats)}
            for p in part:
                phrases.add(p["name"].lower())
                if p["dated"]:
                    phrases.update({p["taken_dt"].strftime("%b ") + str(p["taken_dt"].day),
                                    p["taken_dt"].strftime("%B ").lower() + str(p["taken_dt"].day)})
                else:
                    phrases.add("undated")
                if p["golden"] >= 0.55:
                    phrases.update({"sunset", "golden hour", "sunrise"})
            if use_days:
                phrases.update({g["title"].lower() + " - " + g["sub"].lower()})
            tags = sorted({t for t in phrases if t in ("sunset", "golden hour", "sunrise")})
            pages.append({"kind": "collage", "title": g["title"], "sub": g["sub"], "layout": LAYOUT_NAMES[len(part)],
                          "file": save(canvas, f"page_{n:03}.png"), "categories": cats, "tags": tags,
                          "photos": [p["name"] for p in part], "search": sorted(phrases)})
            n += 1
            layout_i += 1
    pages.append({"kind": "end", "title": "The End", "file": save(end_page(stats), "page_999_end.png"),
                  "search": ["the end"], "categories": [], "tags": []})
    book = {"run_id": run_id, "title": nice_title, "date_range": date_range, "stats": stats,
            "grouped_by": "day" if use_days else "category", "pages": pages}
    (out / "book.json").write_text(json.dumps(book, indent=1), encoding="utf-8")
    return book


CUSTOM_LAYOUTS = {"split": (2, layout_editorial), "editorial": (3, layout_magazine),
                  "polaroid": (4, layout_polaroid), "grid6": (6, layout_grid6)}


def build_custom(items: list[dict], layout: str, title: str, caption: str) -> Image.Image:
    """Collage from exactly the photos the user picked. items: {path, category, taken(iso)}."""
    if layout not in CUSTOM_LAYOUTS:
        raise ValueError("Unknown layout")
    n, fn = CUSTOM_LAYOUTS[layout]
    if len(items) != n:
        raise ValueError(f"This layout needs exactly {n} photos (you picked {len(items)}).")
    random.seed(len(title) + n)
    photos = []
    for it in items:
        try:
            dt = datetime.fromisoformat(it["taken"])
        except Exception:
            dt = datetime.now()
        photos.append({"path": it["path"], "category": it["category"], "taken_dt": dt, "dated": True,
                       "golden": 0, "name": Path(it["path"]).name})
    if not caption.strip():
        dts = sorted(p["taken_dt"] for p in photos)
        caption = dts[0].strftime("%B ") + str(dts[0].day) if dts[0].date() == dts[-1].date() else \
            f"{dts[0].strftime('%b')} {dts[0].day} – {dts[-1].strftime('%b')} {dts[-1].day}"
    canvas = new_page()
    header(canvas, title.strip() or "Custom Collage", caption.strip(), "Custom Collage")
    fn(canvas, photos)
    t = "Trip Studio"
    d = ImageDraw.Draw(canvas)
    tw, _ = text_size(d, t, font("sans", 24))
    d.text(((W - tw) / 2, H - 92), t, font=font("sans", 24), fill=MUTED)
    return canvas.convert("RGB")


def export_pdf(book: dict, out_dir: Path) -> Path:
    imgs = [Image.open(out_dir / p["file"]).convert("RGB") for p in book["pages"]]
    pdf = out_dir / "Travel_Book.pdf"
    imgs[0].save(pdf, "PDF", save_all=True, append_images=imgs[1:], resolution=150.0, quality=92)
    return pdf
