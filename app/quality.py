"""Photo quality + curation: sharpness, exposure, burst grouping, hero-shot scoring."""
from __future__ import annotations

import math
from pathlib import Path

import cv2
import imagehash
import numpy as np
from PIL import Image, ImageOps

ANALYSIS_PX = 1024
BLUR_MIN = 40.0          # tile-based Laplacian variance below this => blurry
DARK_MEAN, DARK_P99 = 25.0, 90.0
BRIGHT_MEAN = 235.0
NEAR_DUP_DIST = 4        # perceptual-hash bits (of 64): same picture, re-saved/resized
BURST_DIST = 14          # looser match allowed when taken within BURST_SECS of each other
BURST_SECS = 5.0

_cache: dict[tuple, dict] = {}


def analyze(path: Path) -> dict:
    st = path.stat()
    key = (str(path), st.st_mtime_ns, st.st_size)
    if key in _cache:
        return _cache[key]
    with Image.open(path) as im:
        im.draft("RGB", (ANALYSIS_PX, ANALYSIS_PX))
        im = ImageOps.exif_transpose(im).convert("RGB")
        im.thumbnail((ANALYSIS_PX, ANALYSIS_PX))
        ph = int(str(imagehash.phash(im)), 16)
        rgb = np.asarray(im)
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)

    # Sharpness: Laplacian variance per tile; average the sharpest quarter so a crisp subject with
    # a soft (bokeh) background is not mistaken for a blurry shot.
    lap = cv2.Laplacian(gray, cv2.CV_64F)
    h, w = lap.shape
    tiles = sorted(float(t.var()) for row in np.array_split(lap, 4, axis=0)
                   for t in np.array_split(row, 4, axis=1) if t.size)
    top = tiles[-4:]
    sharp = sum(top) / len(top)

    mean = float(gray.mean())
    p99 = float(np.percentile(gray, 99))
    clip_lo, clip_hi = float((gray < 8).mean()), float((gray > 247).mean())
    expo = math.exp(-(((mean - 125) / 75) ** 2)) * (1 - min(1.0, (clip_lo + clip_hi) * 2))

    r, g, b = (rgb[..., i].astype(np.float32) for i in range(3))
    rg, yb = r - g, 0.5 * (r + g) - b
    color = math.sqrt(rg.std() ** 2 + yb.std() ** 2) + 0.3 * math.sqrt(rg.mean() ** 2 + yb.mean() ** 2)

    hsv = cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV)
    warm = (hsv[..., 0] >= 5) & (hsv[..., 0] <= 25) & (hsv[..., 1] > 90) & (hsv[..., 2] > 110)
    golden = min(1.0, float(warm.mean()) * 2.5) * 0.7 + float(np.clip((r.mean() - b.mean()) / 60, 0, 1)) * 0.3

    s_n = min(1.0, math.log1p(sharp) / math.log1p(400))
    c_n = min(1.0, color / 80)
    out = {
        "sharp": round(sharp, 1), "brightness": round(mean, 1), "phash": ph,
        "blurry": sharp < BLUR_MIN,
        "dark": mean < DARK_MEAN and p99 < DARK_P99,
        "overexposed": mean > BRIGHT_MEAN,
        "rank": 0.6 * s_n + 0.4 * expo,                                   # best-of-burst choice
        "hero": round(0.35 * s_n + 0.25 * expo + 0.20 * c_n + 0.20 * golden, 4),
        "golden": round(golden, 3),
    }
    _cache[key] = out
    return out


def group_similar(items: list[tuple[int, float, int]]) -> list[list[int]]:
    """items: (id, unix_seconds, phash). Returns groups (size > 1) of near-duplicates / bursts."""
    n = len(items)
    if n < 2:
        return []
    ids = [i for i, _, _ in items]
    ts = np.array([t for _, t, _ in items], dtype=np.float64)
    hs = np.array([h for _, _, h in items], dtype=np.uint64)
    parent = list(range(n))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for i in range(n - 1):
        dist = np.bitwise_count(np.bitwise_xor(hs[i + 1:], hs[i]))
        dt = np.abs(ts[i + 1:] - ts[i])
        hit = (dist <= NEAR_DUP_DIST) | ((dt <= BURST_SECS) & (dist <= BURST_DIST))
        for j in np.nonzero(hit)[0]:
            a, b = find(i), find(i + 1 + int(j))
            if a != b:
                parent[b] = a
    groups: dict[int, list[int]] = {}
    for k in range(n):
        groups.setdefault(find(k), []).append(ids[k])
    return [g for g in groups.values() if len(g) > 1]
