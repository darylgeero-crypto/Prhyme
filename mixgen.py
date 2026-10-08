"""DJ mix generator — original synthesized DJ-style mixes.

Generates 3-4 original beats (pure numpy synthesis via lightbeat), beatmatched
to a common BPM and joined with equal-power DJ crossfades into one continuous
track. Style presets use the 102-artist production-style database for era feel.

Style emulation only — every sound is synthesized from scratch; no artist's
recordings, melodies, or songs are reproduced.
"""
import numpy as np

import lightbeat
from lightbeat import SR, SUPPORTED_GENRES, normalize_genre

# Style presets: (label, era filter, genre filter, track count)
# era values match lightbeat._ARTIST_ROWS era strings.
STYLE_PRESETS = [
    ("genre", "🎵 Genre mix (no era style)"),
    ("2000s-southern-trap", "🔥 2000s Southern Trap"),
    ("2010s-drill", "🎯 2010s Drill Wave"),
    ("2020s-melodic", "🌊 2020s Melodic"),
    ("surprise", "🎲 Surprise Me"),
]

_STYLE_DEFS = {
    "2000s-southern-trap": dict(era="2006–2010", genre="Trap", n=4),
    "2010s-drill":         dict(era="2011–2015", genre="Drill", n=4),
    "2020s-melodic":       dict(era="2016–2020", genre=None,  n=4, melodic=True),
    "surprise":            dict(era=None, genre=None, n=4),
}

BARS_PER_SEG = 16
XFADE_SECS = 8.0
# Lite mode: 2 segments × 8 bars with 4 s crossfades — much smaller buffers.
LITE_BARS_PER_SEG = 8
LITE_XFADE_SECS = 4.0
LITE_N_SEGS = 2


def list_artists_for_style(style_key):
    """Return candidate (name, row) pairs for a style preset.

    Filters progressively relax: era+genre first, then genre across all
    eras, then era only — so a style always keeps its sonic identity.
    """
    sd = _STYLE_DEFS.get(style_key)
    if not sd:
        return []

    def match(row, era=None, genre=None, melodic=False):
        name, r_era, region, base, bpm, sw, hat, bass, mel, prog, fill, notes = row
        if era and r_era != era:
            return False
        if genre and base != genre:
            return False
        if melodic and mel not in ("pads", "bells", "pluck"):
            return False
        return True

    era, genre, melodic = sd.get("era"), sd.get("genre"), sd.get("melodic", False)
    rows = lightbeat._ARTIST_ROWS
    cands = [r for r in rows if match(r, era, genre, melodic)]
    if len(cands) < 3 and genre:
        cands = [r for r in rows if match(r, None, genre, melodic)]
    if len(cands) < 3 and era:
        cands = [r for r in rows if match(r, era, None, False)]
    if len(cands) < 3:
        cands = list(rows)
    return [(r[0], r) for r in cands]


def _plan_segments(genre, style, seed, rng, lite=False):
    """Return list of (label, artist_or_None, genre) segment plans."""
    n_segs = LITE_N_SEGS if lite else 4
    if style and style != "genre":
        sd = _STYLE_DEFS.get(style, _STYLE_DEFS["surprise"])
        cands = list_artists_for_style(style)
        if len(cands) < 2:
            cands = [(r[0], r) for r in lightbeat._ARTIST_ROWS]
        idx = rng.choice(len(cands), size=min(sd["n"] if not lite else LITE_N_SEGS,
                                              len(cands)),
                         replace=False)
        segs = []
        for i in idx:
            name, row = cands[int(i)]
            segs.append((name, name, row[3]))  # artist name drives style
        return segs
    # plain genre mix
    genre = normalize_genre(genre or "HipHop")
    return [(f"{genre} #{i+1}", None, genre) for i in range(n_segs)]


def _equal_power_xfade(a, b, xf_n):
    """Crossfade tail of a with head of b using equal-power curves."""
    t = np.linspace(0, np.pi / 2, xf_n, dtype=np.float32)
    g_out = np.cos(t) ** 2
    g_in = np.sin(t) ** 2
    mixed = a.copy()
    mixed[-xf_n:] = (a[-xf_n:].T * g_out).T + (b[:xf_n].T * g_in).T
    return np.concatenate([mixed, b[xf_n:]], axis=0)


def generate_mix(genre=None, style=None, seed=None, progress_cb=None,
               lite=False):
    """Render a continuous DJ mix.

    Returns (audio float32 stereo @44100, meta dict).
    All segments are synthesized at one common BPM so the mix is
    perfectly beatmatched; transitions use equal-power crossfades.
    lite=True: 2 segments x 8 bars with 4 s crossfades (phone-safe).
    """
    rng = np.random.default_rng(seed)
    segs = _plan_segments(genre, style, seed, rng, lite=lite)
    bars_per_seg = LITE_BARS_PER_SEG if lite else BARS_PER_SEG
    xfade_secs = LITE_XFADE_SECS if lite else XFADE_SECS

    # common target BPM: mean of artist BPMs (style) or genre default (genre mix)
    if style and style != "genre":
        bpms = [lightbeat.get_artist_style(s[1])["bpm"]
                for s in segs if lightbeat.get_artist_style(s[1])]
        target_bpm = float(np.clip(round(np.mean(bpms) / 5) * 5, 50, 200)) \
            if bpms else 140.0
    else:
        g = normalize_genre(genre or "HipHop")
        # genre-typical BPMs
        _gbpm = {"Drill": 142, "Trap": 140, "HipHop": 92, "BoomBap": 90,
                 "House": 124, "Techno": 130, "DnB": 174, "Afrobeats": 100}
        target_bpm = float(_gbpm.get(g, 120))

    seg_audios = []
    # era flavor: style presets carry an era (2000s/2010s/2020s) so each
    # segment gets decade-appropriate production on top of artist styles.
    _era = lightbeat.normalize_era(style) if style and style != "genre" else None
    for i, (label, artist, g) in enumerate(segs):
        if progress_cb:
            progress_cb(5 + 85 * i / len(segs), f"Synthesizing {label}…")
        seg_seed = int(rng.integers(0, 2 ** 31 - 1))
        audio = lightbeat.generate_beat(g, target_bpm, bars_per_seg,
                                        seed=seg_seed, artist=artist, era=_era)
        seg_audios.append(audio.astype(np.float32))

    if progress_cb:
        progress_cb(92, "Mixing transitions…")
    xf_n = int(xfade_secs * SR)
    mix = seg_audios[0]
    for nxt in seg_audios[1:]:
        # trim both sides to multiple safe length for the xfade window
        n = min(len(mix), len(nxt))
        if len(mix) < xf_n or len(nxt) < xf_n:
            mix = np.concatenate([mix, nxt], axis=0)
        else:
            mix = _equal_power_xfade(mix, nxt, xf_n)

    # gentle master: peak normalize + soft clip
    peak = float(np.max(np.abs(mix))) or 1.0
    mix = mix / peak * 0.95
    mix = np.tanh(mix * 1.1) * 0.98

    meta = {
        "bpm": target_bpm,
        "segments": [{"label": s[0], "genre": s[2]} for s in segs],
        "duration": round(len(mix) / SR, 1),
        "style": style or "genre",
        "genre": genre or "",
        "lite": lite,
    }
    return mix, meta
