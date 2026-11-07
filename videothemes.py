"""Prhyme video background themes — places, drawn procedurally.

A theme is a PLACE behind the video: a gradient sky, a celestial body,
a silhouette (city skyline, dunes, mountain peaks), stars, water — all
drawn with PIL, no external assets, so it renders offline on the phone
exactly like the rest of the video pipeline.

Design: the static part (gradient + sky + silhouette + stars) is built
ONCE per render into a base image; each frame only copies the base and
draws the cheap reactive overlay (pulse glow + the theme's animated
effect: rain, aurora bands, club beams, spotlights). A full-frame
per-frame redraw would cost minutes on a long track; this costs ~1 ms.

Free themes: studio, city, beach. Premium themes (paid tier only,
enforced in app.py): desert, mountains, club, aurora, rain.
"""
import zlib

import numpy as np

# name: label, premium?, sky top/bottom, celestial, silhouette, stars,
# water band, animated effect, glow color (pulse-reactive focal glow).
VIDEO_THEMES = {
    "studio": {
        "label": "Studio", "premium": False,
        "sky_top": (10, 12, 24), "sky_bottom": (26, 30, 52),
        "sun": None, "silhouette": None, "stars": False, "water": False,
        "effect": "spotlights", "glow": (255, 200, 120),
    },
    "city": {
        "label": "City Nights", "premium": False,
        "sky_top": (8, 10, 30), "sky_bottom": (42, 30, 72),
        "sun": "moon", "silhouette": "city", "stars": True, "water": False,
        "effect": None, "glow": (120, 160, 255),
    },
    "beach": {
        "label": "Sunset Beach", "premium": False,
        "sky_top": (62, 32, 82), "sky_bottom": (255, 140, 80),
        "sun": "sun", "silhouette": None, "stars": False, "water": True,
        "effect": None, "glow": (255, 170, 90),
    },
    "desert": {
        "label": "Desert Dunes", "premium": True,
        "sky_top": (92, 52, 22), "sky_bottom": (255, 182, 92),
        "sun": "sun", "silhouette": "dunes", "stars": False, "water": False,
        "effect": None, "glow": (255, 190, 110),
    },
    "mountains": {
        "label": "Mountain Peaks", "premium": True,
        "sky_top": (6, 14, 34), "sky_bottom": (42, 72, 112),
        "sun": "moon", "silhouette": "peaks", "stars": True, "water": False,
        "effect": None, "glow": (180, 220, 255),
    },
    "club": {
        "label": "Club Lights", "premium": True,
        "sky_top": (8, 6, 16), "sky_bottom": (32, 10, 42),
        "sun": None, "silhouette": None, "stars": False, "water": False,
        "effect": "beams", "glow": (255, 60, 180),
    },
    "aurora": {
        "label": "Northern Lights", "premium": True,
        "sky_top": (4, 10, 18), "sky_bottom": (12, 32, 42),
        "sun": None, "silhouette": "peaks", "stars": True, "water": False,
        "effect": "aurora", "glow": (80, 255, 170),
    },
    "rain": {
        "label": "Rooftop Rain", "premium": True,
        "sky_top": (10, 14, 22), "sky_bottom": (32, 42, 62),
        "sun": None, "silhouette": "city", "stars": False, "water": True,
        "effect": "rain", "glow": (140, 180, 220),
    },
}


def theme_list():
    """Public list for the API/page: name, label, premium flag."""
    return [{"name": n, "label": t["label"], "premium": bool(t["premium"])}
            for n, t in VIDEO_THEMES.items()]


def _seed(name):
    return zlib.crc32(name.encode("utf-8")) & 0xFFFFFFFF


def theme_base(W, H, name):
    """Build the static background for a theme (once per render)."""
    from PIL import Image, ImageDraw
    th = VIDEO_THEMES.get(name) or VIDEO_THEMES["studio"]
    rng = np.random.default_rng(_seed(name))
    # Vertical gradient sky.
    top = np.array(th["sky_top"], dtype=np.float64)
    bot = np.array(th["sky_bottom"], dtype=np.float64)
    f = np.linspace(0, 1, H)[:, None, None]
    grad = (top[None, None, :] * (1 - f) + bot[None, None, :] * f)
    grad = np.repeat(grad, W, axis=1)
    img = Image.fromarray(grad.astype(np.uint8), "RGB")
    dr = ImageDraw.Draw(img)

    if th["stars"]:
        for _ in range(120):
            x = int(rng.integers(0, W))
            y = int(rng.integers(0, int(H * 0.55)))
            b = int(rng.integers(140, 256))
            s = 1 if rng.random() < 0.8 else 2
            dr.ellipse([x, y, x + s, y + s], fill=(b, b, min(255, b + 10)))

    if th["sun"] == "sun":
        sx, sy, sr = int(W * 0.72), int(H * 0.42), max(28, H // 12)
        for k, col in ((2.6, (255, 150, 70)), (1.6, (255, 180, 100))):
            r = int(sr * k)
            dr.ellipse([sx - r, sy - r, sx + r, sy + r],
                       outline=col, width=3)
        dr.ellipse([sx - sr, sy - sr, sx + sr, sy + sr],
                   fill=(255, 200, 110))
    elif th["sun"] == "moon":
        mx, my, mr = int(W * 0.78), int(H * 0.18), max(18, H // 22)
        dr.ellipse([mx - mr * 2, my - mr * 2, mx + mr * 2, my + mr * 2],
                   outline=(200, 210, 240), width=2)
        dr.ellipse([mx - mr, my - mr, mx + mr, my + mr],
                   fill=(235, 240, 255))

    sil = th["silhouette"]
    horizon = int(H * 0.68)
    if sil == "city":
        x = 0
        while x < W:
            bw = int(rng.integers(42, 110))
            bh = int(rng.integers(60, 260))
            by = horizon + int(H * 0.32) - bh
            dr.rectangle([x, by, x + bw, H], fill=(12, 14, 26))
            # Lit windows (deterministic per theme).
            for wy in range(by + 12, H - 14, 18):
                for wx in range(x + 8, x + bw - 10, 14):
                    if rng.random() < 0.12:
                        warm = rng.random() < 0.75
                        col = (255, 190, 90) if warm else (150, 200, 255)
                        dr.rectangle([wx, wy, wx + 6, wy + 8], fill=col)
            x += bw + int(rng.integers(2, 10))
    elif sil == "dunes":
        for ridge, col, amp, base in (
                (0, (150, 90, 40), 46, 0.78), (1, (120, 66, 28), 60, 0.86)):
            pts = [(0, H)]
            for px in range(0, W + 40, 40):
                py = int(H * base + amp * np.sin(px * 0.004 + ridge * 2.1))
                pts.append((px, py))
            pts.append((W, H))
            dr.polygon(pts, fill=col)
    elif sil == "peaks":
        x = 0
        while x < W:
            pw = int(rng.integers(160, 320))
            ph = int(rng.integers(140, 300))
            px = x + pw // 2
            py = horizon + int(H * 0.32) - ph
            dr.polygon([(x, H), (px, py), (x + pw, H)], fill=(16, 24, 44))
            # Snow cap.
            cap = 0.32
            dr.polygon([(px - int(pw * cap / 2), py + int(ph * cap)),
                        (px, py),
                        (px + int(pw * cap / 2), py + int(ph * cap))],
                       fill=(225, 235, 245))
            x += pw - int(rng.integers(20, 60))

    if th["water"]:
        wy0 = int(H * 0.78)
        dr.rectangle([0, wy0, W, H], fill=(18, 22, 44))
        glow = th["glow"]
        for _ in range(26):
            wx = int(rng.integers(0, W - 90))
            wy = int(rng.integers(wy0 + 6, H - 6))
            wl = int(rng.integers(30, 110))
            dr.line([wx, wy, wx + wl, wy], fill=glow, width=2)
    return img


def _glow_ellipse(dr, cx, cy, r, color, pulse):
    """Pulse-reactive focal glow: concentric outlines, radius follows
    the beat (pulse 0..1). Cheap — three ellipses, no fill."""
    rr = int(r * (1.0 + 0.45 * pulse))
    for k, w in ((1.0, 3), (0.72, 2), (0.45, 2)):
        r2 = int(rr * k)
        dr.ellipse([cx - r2, cy - r2, cx + r2, cy + r2],
                   outline=color, width=w)


def theme_frame(base, fi, t, pulse, name, W, H):
    """One frame: copy the static base, draw the theme's animated
    effect + pulse glow on top. Returns a new image."""
    from PIL import ImageDraw
    th = VIDEO_THEMES.get(name) or VIDEO_THEMES["studio"]
    img = base.copy()
    dr = ImageDraw.Draw(img)
    eff = th["effect"]
    glow = th["glow"]

    if eff == "spotlights":
        # Two stage beams from the top corners to the floor + floor glow.
        for bx in (int(W * 0.12), int(W * 0.88)):
            dr.polygon([(bx - 45, 0), (bx + 45, 0),
                        (W // 2 + 22, int(H * 0.78)),
                        (W // 2 - 22, int(H * 0.78))],
                       fill=(44, 40, 30))
        _glow_ellipse(dr, W // 2, int(H * 0.78), 90, glow, pulse)
    elif eff == "beams":
        # Three colored beams sweeping from the floor, angles follow time.
        cols = [(255, 60, 180), (0, 220, 255), (160, 255, 80)]
        for i, col in enumerate(cols):
            ang = np.sin(t * 0.9 + i * 2.1) * 0.55
            tx = int(W // 2 + np.tan(ang) * H * 0.9)
            dr.line([W // 2, H, tx, 0], fill=col, width=16)
        _glow_ellipse(dr, W // 2, H - 30, 110, glow, pulse)
    elif eff == "aurora":
        # Sine bands across the sky, phase drifts with time, amplitude
        # breathes with the beat. No extra glow — the bands are the light.
        cols = [(80, 255, 170), (120, 120, 255), (200, 80, 255)]
        for b, col in enumerate(cols):
            y0 = int(H * (0.16 + 0.09 * b))
            pts = []
            for px in range(0, W + 16, 16):
                py = int(y0 + (34 + 22 * pulse)
                         * np.sin(px * 0.004 + t * 0.7 + b * 1.3))
                pts.append((px, py))
            dr.line(pts, fill=col, width=14, joint="curve")
    elif eff == "rain":
        # Deterministic falling drops: position is a hash of (drop, frame)
        # so they fall steadily instead of flickering.
        for i in range(70):
            x = (i * 173 + fi * 2) % W
            y = (i * 97 + fi * 18) % H
            dr.line([x, y, x - 4, y + 16], fill=(150, 170, 200), width=1)
        # Distant city glow on the horizon.
        _glow_ellipse(dr, W // 2, int(H * 0.68), 70, glow, pulse)
    else:
        # No animated effect: the pulse glow rings the actual celestial
        # body (sun low right, moon high right) — never a floating
        # target in an empty sky.
        if th["sun"] == "sun":
            fx, fy = int(W * 0.72), int(H * 0.42)
        elif th["sun"] == "moon":
            fx, fy = int(W * 0.78), int(H * 0.18)
        else:
            fx, fy = W // 2, H // 2
        _glow_ellipse(dr, fx, fy, 80, glow, pulse)
    return img
