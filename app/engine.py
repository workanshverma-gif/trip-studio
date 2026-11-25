"""Local AI engine: OpenCLIP classification, screenshot/receipt detection, EXIF timeline data."""
from __future__ import annotations

import threading
from datetime import datetime
from pathlib import Path

from PIL import Image, ImageOps

try:  # iPhone .HEIC/.HEIF support for every Pillow call in the app
    from pillow_heif import register_heif_opener
    register_heif_opener()
except ImportError:
    pass

RECEIPTS = "Receipts & Tickets"
BASE_CATEGORIES = ["Selfies", "People & Family", "Food & Drinks", "Travel & Nature", "Night Out", RECEIPTS]

# Several prompts per class; their text embeddings are averaged.
PROMPTS = {
    "Selfies": ["a selfie of a person holding the camera at arm's length",
                "a close-up selfie portrait of one person's face",
                "a mirror selfie"],
    "People & Family": ["a group photo of family and friends posing together",
                        "a photo of several people smiling",
                        "a family portrait"],
    "Food & Drinks": ["a photo of a plate of food on a table",
                      "a drink, coffee or cocktail on a table",
                      "a restaurant meal"],
    "Travel & Nature": ["a landscape photo of mountains, beach or forest",
                        "a famous landmark or tourist attraction",
                        "a scenic travel photo of a city, temple or lake"],
    "Night Out": ["a photo taken at night at a party, bar or club",
                  "people at a nightclub with colorful lights",
                  "city street lights at night"],
    RECEIPTS: ["a receipt, ticket, boarding pass, or screenshot of text",
               "a photo of a document with lots of printed text",
               "a screenshot of a phone app, payment confirmation or UPI receipt"],
}


def custom_prompts(label: str) -> list[str]:
    return [f"a photo of {label}", f"a picture showing {label}", f"{label}"]


# ------------------------------------------------------------------ EXIF
def read_meta(path: Path) -> dict:
    """Return {taken: datetime|None, gps: (lat, lon)|None, has_camera: bool, w, h, fmt}."""
    meta = {"taken": None, "gps": None, "has_camera": False, "w": 0, "h": 0, "fmt": ""}
    try:
        with Image.open(path) as im:
            meta.update(w=im.width, h=im.height, fmt=(im.format or "").upper())
            ex = im.getexif()
            meta["has_camera"] = bool(ex.get(271) or ex.get(272))
            sub = ex.get_ifd(0x8769)
            for raw in (sub.get(36867), sub.get(36868), ex.get(306)):   # Original, Digitized, DateTime
                if not raw:
                    continue
                try:
                    t = datetime.strptime(str(raw).strip()[:19], "%Y:%m:%d %H:%M:%S")
                except ValueError:
                    continue
                if t.year > 1971:                      # ignore 0000:00:00 / epoch placeholders
                    meta["taken"] = t
                    break
            g = ex.get_ifd(0x8825)
            if g and 2 in g and 4 in g:
                def deg(v, ref):
                    d = float(v[0]) + float(v[1]) / 60 + float(v[2]) / 3600
                    return -d if ref in ("S", "W") else d
                meta["gps"] = (round(deg(g[2], g.get(1, "N")), 5), round(deg(g[4], g.get(3, "E")), 5))
    except Exception:
        pass
    return meta


def looks_like_screenshot(meta: dict) -> bool:
    """Phone-screen aspect ratio and no camera metadata."""
    w, h = meta["w"], meta["h"]
    if not w or not h or meta["has_camera"]:
        return False
    r = max(w, h) / min(w, h)
    phone = 1.7 <= r <= 2.5 or (abs(r - 1.333) < 0.02 and meta["fmt"] == "PNG")  # tablets
    return phone and (meta["fmt"] == "PNG" or meta["taken"] is None)


# ------------------------------------------------------------------ CLIP
class Classifier:
    def __init__(self) -> None:
        self.ready = False
        self._lock = threading.Lock()
        self.cache: dict[tuple, object] = {}   # (path, mtime, size) -> image embedding

    def load(self, status) -> None:
        with self._lock:
            if self.ready:
                return
            status("Loading AI engine (first run downloads the ~350 MB model)…")
            import numpy as np  # noqa: F401
            import open_clip
            import torch
            torch.set_num_threads(max(1, (torch.get_num_threads() or 4)))
            self.torch = torch
            self.model, _, self.preprocess = open_clip.create_model_and_transforms("ViT-B-32-quickgelu", pretrained="openai")
            self.tokenizer = open_clip.get_tokenizer("ViT-B-32-quickgelu")
            self.model.eval()
            self.ready = True
            status("AI engine ready")

    def text_matrix(self, custom: list[str]):
        classes = dict(PROMPTS)
        for c in custom:
            classes[c] = custom_prompts(c)
        names, rows = [], []
        with self.torch.no_grad():
            for name, prompts in classes.items():
                f = self.model.encode_text(self.tokenizer(prompts))
                f = f / f.norm(dim=-1, keepdim=True)
                m = f.mean(0)
                rows.append(m / m.norm())
                names.append(name)
        return names, self.torch.stack(rows)

    def embed(self, path: Path):
        st = path.stat()
        key = (str(path), st.st_mtime_ns, st.st_size)
        if key in self.cache:
            return self.cache[key]
        with Image.open(path) as im:
            im = ImageOps.exif_transpose(im).convert("RGB")
            x = self.preprocess(im).unsqueeze(0)
        with self.torch.no_grad():
            f = self.model.encode_image(x)
            f = (f / f.norm(dim=-1, keepdim=True))[0]
        self.cache[key] = f
        return f

    def classify(self, path: Path, names, text):
        """Return (best_name, {name: prob})."""
        f = self.embed(path)
        probs = (100.0 * f @ text.T).softmax(dim=-1).tolist()
        d = dict(zip(names, probs))
        return max(d, key=d.get), d


CLASSIFIER = Classifier()
