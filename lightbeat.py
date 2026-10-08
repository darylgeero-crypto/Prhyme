"""DJRILL lightbeat — lightweight synthesized beat generator for mobile.

Pure numpy. No pygame, no ffmpeg, no sample files, no other dependencies.
Designed to render a full beat in seconds on a phone CPU, where the V68
engine is too heavy.

    generate_beat(genre, bpm, bars, seed=None) -> np.ndarray

Returns stereo float32 @ 44100 Hz. Deterministic when seed is provided.
"""

import numpy as np

try:
    import soundx as _soundx
    _SOUNDX_AVAILABLE = True
except ImportError:
    _soundx = None
    _SOUNDX_AVAILABLE = False

SR = 44100

# Standard full-song durations: label -> seconds. Passed as duration="3:00"
# (or seconds) to generate_beat() to enable song mode with a structured
# intro/verse/hook/bridge/outro arrangement instead of a plain loop.
STANDARD_DURATIONS = {"2:30": 150, "3:00": 180, "3:30": 210}


def get_song_structure(total_bars):
    """Song-section layout scaled to fit total_bars.

    Returns a list of (name, start_bar, num_bars, intensity). The 8-section
    layout is scaled from the 80-bar baseline (8/16/8/16/8/8/8/8), each
    section rounded to 4-bar multiples; rounding drift is absorbed by the
    outro (kept >= 4 bars, verses trimmed only for tiny totals).
    """
    _BASE = [
        ("intro", 8, 0.30),
        ("verse1", 16, 0.65),
        ("hook1", 8, 1.00),
        ("verse2", 16, 0.65),
        ("hook2", 8, 1.00),
        ("bridge", 8, 0.45),
        ("final", 8, 1.15),
        ("outro", 8, 0.25),
    ]
    total_bars = max(16, int(total_bars))
    _wsum = sum(b for _, b, _ in _BASE)
    alloc = [int(round(b * total_bars / _wsum / 4.0)) * 4
             for _, b, _ in _BASE]
    # Fix rounding drift via the outro.
    alloc[-1] += total_bars - sum(alloc)
    if alloc[-1] < 4:
        # Tiny totals: hold outro at 4, trim the roomiest sections first.
        short = 4 - alloc[-1]
        alloc[-1] = 4
        for i in (3, 1, 4, 2, 6, 5, 0):  # verse2, verse1, hook2, ...
            while short > 0 and alloc[i] > 4:
                take = min(4, short, alloc[i] - 4)
                alloc[i] -= take
                short -= take
            if short <= 0:
                break
    structure, start = [], 0
    for (name, _, intensity), n in zip(_BASE, alloc):
        structure.append((name, start, max(0, n), intensity))
        start += max(0, n)
    return structure


def get_bar_section(bar, structure):
    """Return (name, intensity) for a 0-based bar index."""
    for name, start, n, intensity in structure:
        if n > 0 and start <= bar < start + n:
            return name, intensity
    name, _, _, intensity = structure[-1]
    return name, intensity

SUPPORTED_GENRES = ["Drill", "Trap", "HipHop", "BoomBap",
                    "House", "Techno", "DnB", "Afrobeats",
                    "RockNRoll", "HeavyMetal",
                    "Breakbeat", "Dubstep", "Reggaeton", "Phonk"]

_ALIASES = {
    "drill": "Drill", "trap": "Trap", "hiphop": "HipHop",
    "boombap": "BoomBap", "house": "House", "techno": "Techno",
    "dnb": "DnB", "drumnb": "DnB", "drumandbass": "DnB",
    "afrobeats": "Afrobeats", "dancehall": "Afrobeats",
    "afroswing": "Afrobeats", "bailefunk": "Afrobeats",
    "reggaeton": "Reggaeton", "dembow": "Reggaeton",
    "phonk": "Phonk", "memphisrap": "Phonk", "memphisphonk": "Phonk",
    "breakbeat": "Breakbeat", "bigbeat": "Breakbeat", "breaks": "Breakbeat",
    "dubstep": "Dubstep", "brostep": "Dubstep", "riddim": "Dubstep",
    "lofi": "BoomBap", "rnb": "HipHop", "soul": "HipHop",
    "jerseyclub": "House", "garage": "House", "pop": "House",
    "hardstyle": "Techno", "detroittechno": "Techno",
    "rocknroll": "RockNRoll", "rockandroll": "RockNRoll",
    "rock": "RockNRoll", "rockroll": "RockNRoll",
    "heavymetal": "HeavyMetal", "metal": "HeavyMetal",
}

# 16 steps per bar. Each genre: drum hits, 808 rhythm, chord progression
# (semitone offsets from root, one chord per bar, cycled), swing feel.
# Extra layers: cowbell/conga steps, shaker (16ths), ride steps,
# crash (phrase-start accent), toms (fill-bar runs), melody_inst (lead).
_PATTERNS = {
    "Drill": dict(
        kick=[0, 7, 10], snare=[8], chat=[0, 2, 4, 6, 8, 10, 12, 14],
        ohat=[14], clap=[],
        bass=[0, 6, 10, 12], bass_fifth=[12],
        prog=[0, 8, 3, 10], swing=0.0, melody=True, melody_inst="pluck",
        cowbell=[], conga=[], shaker=False, ride=[], crash=True, toms=True),
    "Trap": dict(
        kick=[0, 6, 10], snare=[8], chat=list(range(16)),
        ohat=[], clap=[],
        bass=[0, 7, 10], bass_fifth=[],
        prog=[0, 3, 10, 8], swing=0.0, melody=True, melody_inst="pluck",
        cowbell=[6], conga=[], shaker=False, ride=[], crash=True, toms=False),
    "HipHop": dict(
        kick=[0, 7, 10], snare=[4, 12], chat=[0, 2, 4, 6, 8, 10, 12, 14],
        ohat=[15], clap=[],
        bass=[0, 10], bass_fifth=[],
        prog=[0, 8, 10, 7], swing=0.22, melody=True, melody_inst="pluck",
        cowbell=[], conga=[], shaker=False, ride=[0, 4, 8, 12],
        crash=True, toms=False),
    "BoomBap": dict(
        kick=[0, 10], snare=[4, 12], chat=[0, 2, 4, 6, 8, 10, 12, 14],
        ohat=[], clap=[],
        bass=[0, 12], bass_fifth=[],
        prog=[0, 5, 8, 10], swing=0.3, melody=True, melody_inst="pluck",
        cowbell=[], conga=[], shaker=False, ride=[], crash=False, toms=True),
    "House": dict(
        kick=[0, 4, 8, 12], snare=[], chat=list(range(16)),
        ohat=[2, 6, 10, 14], clap=[4, 12],
        bass=[2, 6, 10, 14], bass_fifth=[],
        prog=[0, 5, 3, 10], swing=0.0, melody=False, melody_inst="none",
        cowbell=[], conga=[], shaker=True, ride=[], crash=True, toms=False),
    "Techno": dict(
        kick=[0, 4, 8, 12], snare=[], chat=list(range(16)),
        ohat=[2, 6, 10, 14], clap=[4, 12],
        bass=list(range(16)), bass_fifth=[],
        prog=[0, 0, 3, 10], swing=0.0, melody=False, melody_inst="none",
        cowbell=[], conga=[], shaker=True, ride=[0, 4, 8, 12],
        crash=True, toms=False),
    "DnB": dict(
        kick=[0, 10], snare=[4, 12], chat=[0, 2, 4, 6, 8, 10, 12, 14],
        ohat=[3, 7, 11, 15], clap=[],
        bass=[0, 4, 10], bass_fifth=[4],
        prog=[0, 10, 8, 7], swing=0.0, melody=False, melody_inst="none",
        cowbell=[], conga=[], shaker=False, ride=[0, 2, 4, 6, 8, 10, 12, 14],
        crash=True, toms=True),
    "Afrobeats": dict(
        kick=[0, 6, 10], snare=[4, 12], chat=list(range(16)),
        ohat=[14], clap=[4, 12],
        bass=[0, 3, 6, 10, 12], bass_fifth=[3, 12],
        prog=[0, 5, 3, 7], swing=0.12, melody=True, melody_inst="pluck",
        cowbell=[], conga=[0, 3, 6, 10, 12], shaker=True, ride=[],
        crash=True, toms=False),
    "RockNRoll": dict(
        kick=[0, 8, 10], snare=[4, 12], chat=[0, 2, 4, 6, 8, 10, 12, 14],
        ohat=[15], clap=[],
        bass=[0, 4, 8, 12], bass_fifth=[5],
        prog=[0, 5, 7, 5], swing=0.14, melody=True, melody_inst="guitar",
        cowbell=[], conga=[], shaker=False, ride=[0, 4, 8, 12],
        crash=True, toms=True),
    "HeavyMetal": dict(
        kick=[0, 2, 4, 6, 8, 10, 12, 14], snare=[4, 12],
        chat=[0, 2, 4, 6, 8, 10, 12, 14],
        ohat=[], clap=[],
        bass=[0, 2, 4, 6, 8, 10, 12, 14], bass_fifth=[],
        prog=[0, 10, 8, 6], swing=0.0, melody=True, melody_inst="guitar_dist",
        cowbell=[], conga=[], shaker=False, ride=[],
        crash=True, toms=True),
    "Breakbeat": dict(
        kick=[0, 7, 10, 12], snare=[4, 12, 15],
        chat=[0, 3, 6, 10, 12, 14],
        ohat=[7], clap=[],
        bass=[0, 7, 10], bass_fifth=[10],
        prog=[0, 10, 7, 5], swing=0.08, melody=True, melody_inst="pluck",
        cowbell=[], conga=[], shaker=False, ride=[0, 4, 8, 12],
        crash=True, toms=True),
    "Dubstep": dict(
        kick=[0], snare=[8],
        chat=[0, 4, 8, 12],
        ohat=[], clap=[8],
        bass=[0, 8], bass_fifth=[],
        prog=[0, 3, 10, 8], swing=0.0, melody=True, melody_inst="pluck",
        cowbell=[], conga=[], shaker=False, ride=[],
        crash=True, toms=False),
    "Reggaeton": dict(
        kick=[0, 6, 8], snare=[4, 12],
        chat=[0, 2, 4, 6, 8, 10, 12, 14],
        ohat=[15], clap=[],
        bass=[0, 8], bass_fifth=[],
        prog=[0, 5, 3, 7], swing=0.0, melody=True, melody_inst="pluck",
        cowbell=[], conga=[0, 3, 6, 10, 12], shaker=True, ride=[],
        crash=True, toms=False),
    "Phonk": dict(
        kick=[0, 7, 10], snare=[8],
        chat=list(range(16)),
        ohat=[], clap=[],
        bass=[0, 6, 10], bass_fifth=[],
        prog=[0, 3, 10, 8], swing=0.0, melody=True, melody_inst="bells",
        cowbell=[0, 3, 6, 10, 12, 14], conga=[], shaker=False, ride=[],
        crash=True, toms=False),
}

_PENTA = [0, 3, 5, 7, 10, 12, 15]  # minor pentatonic


# ---------------------------------------------------------------- healing mode
# Optional "Fibonacci healing" tuning for wellness-vibe beats. Descriptors
# only ("healing tones") — no health claims anywhere in the UI.
#
# Fibonacci scale: stack consecutive Fibonacci ratios, reduce mod octave:
#   2/1 -> 2.0 -> 1.0 | x3/2 -> 3 -> 1.5 | x5/3 -> 5 -> 1.25
#   x8/5 -> 8 -> 1.0 | x13/8 -> 13 -> 1.625 | x21/13 -> 21 -> 1.3125
# Unique degrees (+octave): exact frequency ratios, no semitone rounding.
FIB_RATIOS = [1.0, 1.25, 1.3125, 1.5, 1.625, 2.0]

# Fibonacci melodic bursts (opt-in per-beat, not just healing mode).
# Short musical phrases where the scale-degree walk follows the Fibonacci
# sequence. Mapped onto the minor pentatonic so it always stays in key.
_FIB_BURST_SEQ = [1, 1, 2, 3, 5, 8, 13, 21]


def _fib_burst_notes(rng, root_midi, chord_semi, sequence="ascending",
                   phrase_idx=0):
    """Build one 2-bar Fibonacci burst: 16 eighth-notes.

    The walk starts on the chord root (2 octaves up, like normal leads),
    then steps through Fibonacci numbers mapped to pentatonic degrees.
    Octave jumps are clamped to +/-1 so it stays musical, never shrill.
    sequence: "ascending" (upward walk), "descending" (downward walk),
      "alternating" (up on even phrases, down on odd — call & response).
    Returns [(step_16ths, midi_note), ...] within a 32-step (2-bar) window.
    """
    notes = []
    if sequence == "descending":
        direction = -1
    elif sequence == "alternating":
        direction = 1 if phrase_idx % 2 == 0 else -1
    else:  # ascending
        direction = 1
    start_deg = int(rng.integers(0, 7))
    # downbeat anchor: chord root, 2 octaves above the bass
    base_oct = root_midi + 24 + (chord_semi % 12)
    notes.append((0, base_oct))
    for i in range(1, 16):
        f = _FIB_BURST_SEQ[i % len(_FIB_BURST_SEQ)]
        deg_total = start_deg + direction * f
        deg = deg_total % 7
        oct_shift = max(-1, min(1, deg_total // 7))
        semis = root_midi + 24 + _PENTA[deg] + 12 * oct_shift
        # keep it in a singable range: 1-3 octaves above bass root
        semis = max(root_midi + 12, min(root_midi + 48, semis))
        notes.append((i * 2, semis))
    return notes


# Burst intensity → mix level for the Fibonacci lead.
_FIB_BURST_LEVELS = {"subtle": 0.3, "balanced": 0.5, "bold": 0.8}


def normalize_fib_bursts(fib_bursts):
    """Normalize the fib_bursts option.

    Returns None (off) or a dict {"bars": 1-4, "intensity": str,
    "sequence": str}. Accepts True (= defaults), an int 1-4 (bars),
    or a dict with any subset of keys.
    """
    if not fib_bursts:
        return None
    if isinstance(fib_bursts, dict):
        d = fib_bursts
    elif isinstance(fib_bursts, bool):
        d = {}
    else:
        try:
            d = {"bars": int(fib_bursts)}
        except (TypeError, ValueError):
            d = {}
    try:
        bars = min(4, max(1, int(d.get("bars", 2))))
    except (TypeError, ValueError):
        bars = 2
    intensity = str(d.get("intensity", "balanced")).lower()
    if intensity not in _FIB_BURST_LEVELS:
        intensity = "balanced"
    sequence = str(d.get("sequence", "ascending")).lower()
    if sequence not in ("ascending", "descending", "alternating"):
        sequence = "ascending"
    return {"bars": bars, "intensity": intensity, "sequence": sequence}

# Solfeggio frequencies (Hz) used for the optional drone bed.
SOLFEGGIO_FREQS = [396.0, 417.0, 528.0, 639.0, 741.0, 852.0]
# Phrase-by-phrase drone order (starts on 528, the most requested one).
_SOLFEGGIO_CYCLE = [528.0, 396.0, 639.0, 417.0, 741.0, 852.0]

# Binaural beat bands: the L/R channel offset targets a brainwave band.
# Descriptors only ("wellness tones") — no health claims anywhere in the UI.
BINAURAL_BANDS = {
    "delta": dict(label="Delta (1–4 Hz)", beat_hz=2.0,
                  desc="Deep rest — the slowest band, for winding down."),
    "theta": dict(label="Theta (4–8 Hz)", beat_hz=6.0,
                  desc="Meditation & daydream — inward, creative focus."),
    "alpha": dict(label="Alpha (8–13 Hz)", beat_hz=10.0,
                  desc="Relaxed awareness — calm, easy focus."),
    "beta": dict(label="Beta (13–30 Hz)", beat_hz=18.0,
                  desc="Active focus — alert, get-things-done energy."),
    "gamma": dict(label="Gamma (30–100 Hz)", beat_hz=40.0,
                  desc="Peak concentration — intense mental clarity."),
}

# Chakra frequencies (Hz): the traditional seven-chakra tone set.
# (name, freq, description)
CHAKRA_FREQS = [
    ("Root — Muladhara", 396.0, "Grounding & security — your foundation."),
    ("Sacral — Svadhisthana", 417.0, "Creativity & emotion — go with the flow."),
    ("Solar Plexus — Manipura", 528.0, "Confidence & willpower — personal power."),
    ("Heart — Anahata", 639.0, "Love & compassion — connection."),
    ("Throat — Vishuddha", 741.0, "Expression & truth — speak up."),
    ("Third Eye — Ajna", 852.0, "Intuition & insight — inner vision."),
    ("Crown — Sahasrara", 963.0, "Stillness & awareness — the top of the journey."),
]
_CHAKRA_CYCLE = [f for _, f, _ in CHAKRA_FREQS]

# Planetary frequencies (Hz): orbital "cosmic octave" tones.
# (name, freq, description)
PLANETARY_FREQS = [
    ("Earth Year", 136.10, "The classic 'OM' tone — deeply calming."),
    ("Sun", 126.22, "Warmth & life force — steady strength."),
    ("Mercury", 141.27, "Communication & quick thinking."),
    ("Mars", 144.72, "Drive & courage — forward motion."),
    ("Saturn", 147.85, "Discipline & structure — stay grounded."),
    ("Jupiter", 183.58, "Expansion & optimism — think big."),
    ("Earth Day", 194.18, "Vitality & movement — wake up."),
    ("Moon", 210.42, "Emotional balance — unwind."),
    ("Venus", 221.23, "Harmony & affection — feel good."),
]
_PLANETARY_CYCLE = [f for _, f, _ in PLANETARY_FREQS]

# Drone bed modes: which frequency set the drone cycles through.
DRONE_MODES = {
    "solfeggio": dict(label="Solfeggio cycle",
                      desc="Cycles the six solfeggio tones (396–852 Hz)."),
    "chakra": dict(label="Chakra journey",
                   desc="Rises root → crown (396–963 Hz), one chakra per phrase."),
    "planetary": dict(label="Planetary cycle",
                      desc="Orbits planetary tones (126–221 Hz), deep and slow."),
}

HEALING_PRESETS = {
    "deep_healing": dict(
        label="Deep Healing",
        desc="Slow 432 Hz tones with a solfeggio drone bed — calm and spacious.",
        bpm=65, genre="HipHop", melody="pads",
        healing=dict(base=432.0, fib_scale=True, solfeggio=True,
                     binaural=True, soft_drums=False)),
    "energy_cleanse": dict(
        label="Energy Cleanse",
        desc="Mid-tempo Fibonacci plucks over a light groove — bright and uplifting.",
        bpm=100, genre="Afrobeats", melody="pluck",
        healing=dict(base=432.0, fib_scale=True, solfeggio=True,
                     binaural=False, soft_drums=False)),
    "meditation": dict(
        label="Meditation",
        desc="Very slow, minimal drums, airy pads and drone — for stillness.",
        bpm=55, genre="BoomBap", melody="choir",
        healing=dict(base=432.0, fib_scale=True, solfeggio=True,
                     binaural=True, soft_drums=True)),
    "chakra_journey": dict(
        label="Chakra Journey",
        desc="Drone rises root → crown while Fibonacci pads float — a full ascent.",
        bpm=70, genre="HipHop", melody="pads",
        healing=dict(base=432.0, fib_scale=True, solfeggio=True,
                     drone_mode="chakra", binaural=False, soft_drums=True)),
    "deep_sleep": dict(
        label="Deep Sleep",
        desc="Delta-wave binaural bed under soft drums — for winding down.",
        bpm=55, genre="BoomBap", melody="choir",
        healing=dict(base=432.0, fib_scale=True, solfeggio=True,
                     binaural=True, binaural_band="delta", soft_drums=True)),
}


def list_healing_presets():
    """Return [{name, label, desc, bpm, genre, melody, healing}] for the UI."""
    return [{"name": n, "label": p["label"], "desc": p["desc"],
             "bpm": p["bpm"], "genre": p["genre"], "melody": p["melody"],
             "healing": p["healing"]}
            for n, p in HEALING_PRESETS.items()]


def get_healing_preset(name):
    """Return the preset dict for name, or None."""
    if not name:
        return None
    return HEALING_PRESETS.get(str(name).strip().lower())


def normalize_healing(healing):
    """Normalize the healing option into a dict, or None when disabled.

    Accepts True (= defaults) or a dict with any of: base (432.0|440.0),
    fib_scale, solfeggio, solfeggio_root (one of SOLFEGGIO_FREQS or None),
    binaural, binaural_band (delta|theta|alpha|beta|gamma — sets the
    binaural beat rate), drone_mode (solfeggio|chakra|planetary — which
    tone set the drone bed cycles), drone_root (explicit drone freq),
    soft_drums, preset (a HEALING_PRESETS name whose options are
    used as defaults under any explicit keys).
    """
    if not healing:
        return None
    if healing is True:
        healing = {}
    if not isinstance(healing, dict):
        return None
    h = {"base": 432.0, "fib_scale": True, "solfeggio": True,
         "solfeggio_root": None, "binaural": False, "binaural_band": None,
         "drone_mode": "solfeggio", "drone_root": None, "soft_drums": False}
    preset = healing.get("preset")
    if preset:
        p = get_healing_preset(preset)
        if p:
            h.update(p["healing"])
    for k in h:
        if k in healing and healing[k] is not None:
            h[k] = healing[k]
    # base tuning: only 432 or 440 allowed (nearest wins)
    try:
        b = float(h["base"])
    except (TypeError, ValueError):
        b = 432.0
    h["base"] = 432.0 if abs(b - 432.0) <= abs(b - 440.0) else 440.0
    h["fib_scale"] = bool(h["fib_scale"])
    h["solfeggio"] = bool(h["solfeggio"])
    h["binaural"] = bool(h["binaural"])
    h["soft_drums"] = bool(h["soft_drums"])
    # binaural band: validated name or None (legacy binaural=True → 3 Hz)
    bb = h["binaural_band"]
    h["binaural_band"] = (str(bb).strip().lower()
                          if isinstance(bb, str) and
                          str(bb).strip().lower() in BINAURAL_BANDS else None)
    h["beat_hz"] = (BINAURAL_BANDS[h["binaural_band"]]["beat_hz"]
                    if h["binaural_band"] else 3.0)
    # drone mode: validated or falls back to solfeggio
    dm = str(h["drone_mode"] or "solfeggio").strip().lower()
    h["drone_mode"] = dm if dm in DRONE_MODES else "solfeggio"
    try:
        rf = float(h["solfeggio_root"])
        h["solfeggio_root"] = (rf if any(abs(rf - s) < 0.5
                                         for s in SOLFEGGIO_FREQS) else None)
    except (TypeError, ValueError):
        h["solfeggio_root"] = None
    try:
        dr = float(h["drone_root"])
        h["drone_root"] = dr if 20.0 <= dr <= 1200.0 else None
    except (TypeError, ValueError):
        h["drone_root"] = None
    return h


def healing_option_lists():
    """UI-friendly option lists with descriptions for the healing panel."""
    return {
        "binaural_bands": [
            {"name": n, "label": v["label"], "desc": v["desc"]}
            for n, v in BINAURAL_BANDS.items()],
        "chakras": [
            {"name": n, "freq": f, "desc": d} for n, f, d in CHAKRA_FREQS],
        "planets": [
            {"name": n, "freq": f, "desc": d} for n, f, d in PLANETARY_FREQS],
        "drone_modes": [
            {"name": n, "label": v["label"], "desc": v["desc"]}
            for n, v in DRONE_MODES.items()],
        "solfeggio": [
            {"freq": f} for f in SOLFEGGIO_FREQS],
    }


# ---------------------------------------------------------------- artist styles
# Style emulation for ORIGINAL beat creation — every sound is synthesized
# from scratch; nothing is copied from any artist's recordings.
# Row format: (name, era, region, base_genre, bpm, swing,
#              hat, bass, melody, prog, fill, notes)
#   hat:    8ths | 16ths | sparse | swung | rolls
#   bass:   glide | distorted | subby | sparse | punchy
#   melody: pluck | darkpiano | bells | pads | none
#   fill:   rolls | minimal | none
_ARTIST_ROWS = [
    # ---------------- 2006-2010 ----------------
    ("T.I.", "2006–2010", "South", "Trap", 130, 0.0, "16ths", "punchy", "darkpiano", [0, 8, 10, 7], "rolls", "Southern trap anthems"),
    ("Jeezy", "2006–2010", "South", "Trap", 135, 0.0, "16ths", "distorted", "darkpiano", [0, 5, 10, 8], "rolls", "Snowman-era street anthems"),
    ("Gucci Mane", "2006–2010", "South", "Trap", 140, 0.0, "16ths", "glide", "pluck", [0, 10, 8, 7], "rolls", "Brick Squad-era bubbly trap"),
    ("Lil Wayne", "2006–2010", "South", "HipHop", 90, 0.08, "8ths", "punchy", "pluck", [0, 5, 7, 3], "rolls", "Carter-era rap"),
    ("Kanye West", "2006–2010", "Midwest", "HipHop", 92, 0.25, "swung", "subby", "darkpiano", [0, 5, 8, 10], "minimal", "Soul-sampling chipmunk era"),
    ("Jay-Z", "2006–2010", "East", "HipHop", 94, 0.05, "8ths", "punchy", "darkpiano", [0, 3, 10, 8], "minimal", "Blueprint-era luxury rap"),
    ("OutKast", "2006–2010", "South", "HipHop", 96, 0.18, "swung", "subby", "pluck", [0, 7, 5, 3], "rolls", "ATLiens funk"),
    ("Bun B", "2006–2010", "Texas", "HipHop", 88, 0.05, "8ths", "subby", "pluck", [0, 5, 3, 7], "minimal", "UGK Texas trunk music"),
    ("Rick Ross", "2006–2010", "South", "Trap", 128, 0.0, "16ths", "subby", "darkpiano", [0, 8, 5, 10], "minimal", "Maybach Music lush trap"),
    ("Drake", "2006–2010", "Canada", "HipHop", 90, 0.05, "8ths", "subby", "pads", [0, 8, 10, 7], "minimal", "So Far Gone-era moody R&B rap"),
    ("Kid Cudi", "2006–2010", "Midwest", "HipHop", 88, 0.05, "sparse", "subby", "pads", [0, 3, 8, 10], "none", "Spacey hum-along rap"),
    ("Wiz Khalifa", "2006–2010", "East", "HipHop", 92, 0.08, "8ths", "punchy", "pluck", [0, 5, 8, 3], "rolls", "Taylor Gang stoner rap"),
    ("Big Sean", "2006–2010", "Midwest", "HipHop", 94, 0.05, "16ths", "punchy", "bells", [0, 8, 3, 10], "rolls", "Finally Famous-era playful"),
    ("Meek Mill", "2006–2010", "East", "Trap", 135, 0.0, "16ths", "distorted", "darkpiano", [0, 5, 10, 8], "rolls", "Dreamchasers aggressive"),
    ("2 Chainz", "2006–2010", "South", "Trap", 130, 0.0, "16ths", "glide", "pluck", [0, 10, 7, 5], "rolls", "Playaz Circle-era bouncy"),
    ("Yo Gotti", "2006–2010", "Memphis", "Trap", 132, 0.0, "16ths", "punchy", "darkpiano", [0, 8, 10, 5], "rolls", "Memphis street trap"),
    ("Juicy J", "2006–2010", "Memphis", "Trap", 140, 0.0, "rolls", "distorted", "bells", [0, 10, 8, 5], "rolls", "Three 6 dark Memphis"),
    ("Future", "2006–2010", "South", "Trap", 138, 0.0, "16ths", "glide", "pads", [0, 10, 8, 7], "rolls", "Early Pluto-era melodic trap"),
    # ---------------- 2011-2015 ----------------
    ("Chief Keef", "2011–2015", "Midwest", "Drill", 140, 0.0, "8ths", "glide", "bells", [0, 8, 10, 7], "rolls", "GBE Chicago drill"),
    ("Young Thug", "2011–2015", "South", "Trap", 140, 0.0, "16ths", "glide", "pluck", [0, 3, 10, 8], "rolls", "Barter 6-era eccentric"),
    ("Migos", "2011–2015", "South", "Trap", 140, 0.0, "rolls", "glide", "bells", [0, 8, 5, 3], "rolls", "QC triplet-flow trap"),
    ("Travis Scott", "2011–2015", "Texas", "Trap", 140, 0.0, "16ths", "distorted", "pads", [0, 8, 3, 10], "rolls", "Rodeo-era dark psychedelic"),
    ("A$AP Rocky", "2011–2015", "East", "HipHop", 92, 0.08, "8ths", "subby", "darkpiano", [0, 5, 8, 10], "minimal", "Cloud-rap Harlem"),
    ("Kendrick Lamar", "2011–2015", "West", "HipHop", 94, 0.18, "swung", "punchy", "pluck", [0, 7, 5, 10], "minimal", "GKMC jazz-rap"),
    ("J. Cole", "2011–2015", "East", "BoomBap", 90, 0.22, "swung", "subby", "darkpiano", [0, 5, 3, 8], "minimal", "Conscious boom-bap"),
    ("Nicki Minaj", "2011–2015", "East", "HipHop", 96, 0.05, "16ths", "punchy", "bells", [0, 8, 10, 5], "rolls", "Pink Friday pop-rap"),
    ("Waka Flocka", "2011–2015", "South", "Trap", 140, 0.0, "16ths", "distorted", "none", [0, 0, 5, 3], "rolls", "Lex Luger brick-squad"),
    ("Rae Sremmurd", "2011–2015", "South", "Trap", 135, 0.0, "16ths", "glide", "pluck", [0, 8, 10, 7], "rolls", "EarDrummers party trap"),
    ("Fetty Wap", "2011–2015", "East", "Trap", 135, 0.0, "16ths", "subby", "bells", [0, 5, 8, 10], "rolls", "1738 melodic trap"),
    ("Lil Uzi Vert", "2011–2015", "East", "Trap", 140, 0.0, "rolls", "glide", "bells", [0, 10, 8, 5], "rolls", "Luv Is Rage-era emo trap"),
    ("21 Savage", "2011–2015", "South", "Trap", 140, 0.0, "sparse", "subby", "darkpiano", [0, 10, 8, 7], "minimal", "Slaughter Gang minimal"),
    ("Kodak Black", "2011–2015", "Florida", "Trap", 138, 0.0, "16ths", "punchy", "darkpiano", [0, 8, 5, 3], "rolls", "Project Baby Florida"),
    ("Lil Yachty", "2011–2015", "South", "Trap", 135, 0.0, "16ths", "glide", "bells", [0, 3, 8, 10], "rolls", "Lil Boat bubbly"),
    ("Playboi Carti", "2011–2015", "South", "Trap", 140, 0.0, "16ths", "glide", "pluck", [0, 10, 7, 8], "rolls", "Early Carti baby-voice"),
    ("XXXTentacion", "2011–2015", "Florida", "Trap", 140, 0.0, "sparse", "distorted", "darkpiano", [0, 8, 5, 3], "none", "Dark lo-fi emo"),
    ("Lil Pump", "2011–2015", "Florida", "Trap", 140, 0.0, "16ths", "distorted", "bells", [0, 10, 8, 7], "rolls", "Gucci Gang-era turnt"),
    # ---------------- 2016-2020 ----------------
    ("Drake", "2016–2020", "Canada", "Trap", 140, 0.0, "16ths", "subby", "pads", [0, 8, 10, 7], "minimal", "Views/Scorpion-era moody"),
    ("Cardi B", "2016–2020", "East", "Trap", 135, 0.0, "16ths", "punchy", "bells", [0, 5, 8, 3], "rolls", "Invasion of Privacy bounce"),
    ("Megan Thee Stallion", "2016–2020", "Texas", "Trap", 140, 0.0, "16ths", "punchy", "darkpiano", [0, 8, 10, 5], "rolls", "Hot Girl Houston"),
    ("DaBaby", "2016–2020", "South", "Trap", 138, 0.0, "16ths", "punchy", "pluck", [0, 10, 8, 5], "rolls", "Kirk-era bouncy minimal"),
    ("Roddy Ricch", "2016–2020", "West", "Trap", 140, 0.0, "16ths", "glide", "pads", [0, 3, 10, 8], "rolls", "Please Excuse melodic"),
    ("Lil Baby", "2016–2020", "South", "Trap", 140, 0.0, "16ths", "glide", "darkpiano", [0, 8, 5, 10], "rolls", "My Turn-era ATL"),
    ("Gunna", "2016–2020", "South", "Trap", 140, 0.0, "16ths", "glide", "pluck", [0, 10, 8, 7], "rolls", "Wheezy drip-season"),
    ("YoungBoy NBA", "2016–2020", "South", "Trap", 140, 0.0, "16ths", "distorted", "darkpiano", [0, 8, 5, 3], "rolls", "Baton Rouge pain"),
    ("Polo G", "2016–2020", "Midwest", "Trap", 140, 0.0, "16ths", "glide", "darkpiano", [0, 3, 8, 10], "rolls", "Piano-driven Chicago pain"),
    ("Lil Durk", "2016–2020", "Midwest", "Drill", 142, 0.0, "8ths", "glide", "darkpiano", [0, 8, 10, 7], "rolls", "OTF Chicago drill"),
    ("Pop Smoke", "2016–2020", "East", "Drill", 142, 0.0, "8ths", "distorted", "bells", [0, 10, 8, 5], "rolls", "Woo UK/NY drill"),
    ("Juice WRLD", "2016–2020", "Midwest", "Trap", 140, 0.0, "16ths", "glide", "pads", [0, 5, 8, 10], "rolls", "Emo-rap melodic"),
    ("Trippie Redd", "2016–2020", "Midwest", "Trap", 140, 0.0, "rolls", "glide", "bells", [0, 10, 7, 8], "rolls", "1400 melodic rage"),
    ("Lil Tecca", "2016–2020", "East", "Trap", 140, 0.0, "16ths", "subby", "pluck", [0, 8, 3, 10], "rolls", "We Love You Tecca bounce"),
    ("Rod Wave", "2016–2020", "Florida", "Trap", 135, 0.0, "16ths", "subby", "darkpiano", [0, 5, 3, 8], "minimal", "Soul-trap pain"),
    ("Moneybagg Yo", "2016–2020", "Memphis", "Trap", 140, 0.0, "16ths", "punchy", "darkpiano", [0, 8, 10, 7], "rolls", "Memphis heavyweight"),
    ("Jack Harlow", "2016–2020", "Midwest", "HipHop", 94, 0.05, "8ths", "punchy", "pluck", [0, 5, 8, 10], "minimal", "Louisville pop-rap"),
    ("Doja Cat", "2016–2020", "West", "HipHop", 96, 0.05, "16ths", "subby", "bells", [0, 3, 10, 8], "rolls", "Planet Her playful"),
    ("Tyler, The Creator", "2016–2020", "West", "HipHop", 92, 0.18, "swung", "punchy", "darkpiano", [0, 7, 5, 3], "minimal", "Odd Future jazz-funk"),
    ("Denzel Curry", "2016–2020", "Florida", "Trap", 140, 0.0, "rolls", "distorted", "none", [0, 10, 8, 5], "rolls", "Aggressive South Florida"),
    ("JID", "2016–2020", "South", "HipHop", 94, 0.15, "swung", "punchy", "pluck", [0, 5, 7, 10], "rolls", "Dreamville technical"),
    ("Freddie Gibbs", "2016–2020", "Midwest", "HipHop", 92, 0.05, "8ths", "punchy", "darkpiano", [0, 8, 5, 3], "minimal", "Gangsta Gibbs coke rap"),
    ("Pusha T", "2016–2020", "East", "HipHop", 90, 0.0, "sparse", "subby", "darkpiano", [0, 10, 8, 5], "none", "Minimal luxury coke rap"),
    ("Westside Gunn", "2016–2020", "East", "BoomBap", 90, 0.08, "8ths", "punchy", "bells", [0, 5, 8, 3], "minimal", "Griselda luxury boom-bap"),
    ("Conway the Machine", "2016–2020", "East", "BoomBap", 88, 0.08, "8ths", "punchy", "darkpiano", [0, 3, 8, 10], "minimal", "Griselda gritty"),
    ("Benny the Butcher", "2016–2020", "East", "BoomBap", 90, 0.08, "8ths", "punchy", "darkpiano", [0, 8, 5, 10], "minimal", "Butcher coming"),
    ("Earl Sweatshirt", "2016–2020", "West", "HipHop", 90, 0.2, "swung", "subby", "pads", [0, 7, 3, 10], "none", "Abstract lo-fi"),
    ("Smino", "2016–2020", "Midwest", "HipHop", 94, 0.2, "swung", "subby", "pluck", [0, 5, 3, 7], "rolls", "St. Louis funk-rap"),
    ("Vince Staples", "2016–2020", "West", "HipHop", 96, 0.05, "8ths", "punchy", "pads", [0, 10, 8, 5], "minimal", "Long Beach deadpan"),
    ("Isaiah Rashad", "2016–2020", "South", "HipHop", 90, 0.15, "swung", "subby", "pads", [0, 5, 8, 3], "minimal", "TDE smoked-out"),
    ("ScHoolboy Q", "2016–2020", "West", "HipHop", 94, 0.05, "8ths", "punchy", "darkpiano", [0, 8, 10, 5], "rolls", "TDE West Coast"),
    ("Ab-Soul", "2016–2020", "West", "HipHop", 92, 0.15, "swung", "subby", "pluck", [0, 3, 7, 10], "minimal", "TDE conscious"),
    # ---------------- 2021-2026 ----------------
    ("Yeat", "2021–2026", "West", "Trap", 140, 0.0, "rolls", "distorted", "bells", [0, 10, 8, 5], "rolls", "Rage dystopian"),
    ("Ken Carson", "2021–2026", "South", "Trap", 142, 0.0, "rolls", "distorted", "bells", [0, 8, 10, 7], "rolls", "Opium rage"),
    ("Destroy Lonely", "2021–2026", "South", "Trap", 140, 0.0, "16ths", "glide", "pads", [0, 3, 10, 8], "rolls", "Opium vamp"),
    ("Playboi Carti", "2021–2026", "South", "Trap", 142, 0.0, "rolls", "distorted", "pads", [0, 10, 7, 5], "rolls", "Whole Lotta Red rage"),
    ("Don Toliver", "2021–2026", "Texas", "Trap", 140, 0.0, "16ths", "glide", "pads", [0, 8, 3, 10], "rolls", "Cactus Jack melodic"),
    ("Central Cee", "2021–2026", "UK", "Drill", 142, 0.0, "8ths", "glide", "darkpiano", [0, 8, 10, 5], "rolls", "UK drill"),
    ("Dave", "2021–2026", "UK", "HipHop", 92, 0.05, "8ths", "subby", "darkpiano", [0, 5, 3, 8], "minimal", "UK conscious rap"),
    ("Stormzy", "2021–2026", "UK", "HipHop", 94, 0.05, "8ths", "punchy", "darkpiano", [0, 8, 5, 10], "minimal", "UK grime-rap"),
    ("Skepta", "2021–2026", "UK", "HipHop", 140, 0.0, "8ths", "punchy", "none", [0, 10, 8, 5], "rolls", "Grime 140 BPM"),
    ("Headie One", "2021–2026", "UK", "Drill", 142, 0.0, "8ths", "glide", "darkpiano", [0, 10, 8, 7], "rolls", "UK drill"),
    ("Ice Spice", "2021–2026", "East", "Drill", 142, 0.0, "8ths", "subby", "bells", [0, 8, 10, 7], "rolls", "Bronx drill"),
    ("Sexyy Red", "2021–2026", "Midwest", "Trap", 140, 0.0, "16ths", "punchy", "bells", [0, 5, 8, 3], "rolls", "St. Louis ratchet"),
    ("GloRilla", "2021–2026", "Memphis", "Trap", 140, 0.0, "16ths", "punchy", "darkpiano", [0, 8, 10, 5], "rolls", "Memphis crunk-trap"),
    ("Latto", "2021–2026", "South", "Trap", 138, 0.0, "16ths", "punchy", "bells", [0, 3, 8, 10], "rolls", "ATL pop-trap"),
    ("Doechii", "2021–2026", "Florida", "HipHop", 96, 0.12, "swung", "punchy", "pluck", [0, 7, 5, 10], "rolls", "TDE eclectic"),
    ("Baby Keem", "2021–2026", "West", "HipHop", 96, 0.05, "8ths", "punchy", "pluck", [0, 5, 8, 3], "rolls", "pgLang playful"),
    ("Lil Nas X", "2021–2026", "South", "HipHop", 94, 0.05, "8ths", "subby", "pluck", [0, 8, 10, 7], "minimal", "Pop-rap crossover"),
    ("Coi Leray", "2021–2026", "East", "Trap", 140, 0.0, "16ths", "subby", "bells", [0, 3, 10, 8], "rolls", "Jersey-Bronx melodic"),
    ("Flo Milli", "2021–2026", "South", "Trap", 140, 0.0, "16ths", "punchy", "bells", [0, 8, 5, 3], "rolls", "Alabama princess"),
    ("EST Gee", "2021–2026", "Midwest", "Trap", 140, 0.0, "sparse", "distorted", "darkpiano", [0, 10, 8, 7], "minimal", "Louisville street"),
    ("42 Dugg", "2021–2026", "Detroit", "Trap", 140, 0.0, "16ths", "glide", "pluck", [0, 8, 10, 5], "rolls", "Detroit wheezy"),
    ("BigXthaPlug", "2021–2026", "Texas", "Trap", 135, 0.0, "16ths", "punchy", "darkpiano", [0, 5, 8, 10], "rolls", "Dallas soul-trap"),
    ("BossMan Dlow", "2021–2026", "Florida", "Trap", 140, 0.0, "16ths", "punchy", "bells", [0, 10, 8, 5], "rolls", "Florida slide"),
    ("Skilla Baby", "2021–2026", "Detroit", "Trap", 140, 0.0, "16ths", "glide", "darkpiano", [0, 8, 3, 10], "rolls", "Detroit melodic"),
    ("Tee Grizzley", "2021–2026", "Detroit", "Trap", 140, 0.0, "16ths", "punchy", "darkpiano", [0, 5, 10, 8], "rolls", "Detroit gritty"),
    ("BabyTron", "2021–2026", "Detroit", "HipHop", 94, 0.05, "8ths", "punchy", "pluck", [0, 8, 5, 3], "rolls", "ShittyBoyz scam-rap"),
    ("Veeze", "2021–2026", "Detroit", "Trap", 140, 0.0, "sparse", "subby", "none", [0, 10, 8, 7], "none", "Detroit minimal cool"),
    ("Lazer Dim 700", "2021–2026", "East", "Trap", 142, 0.0, "rolls", "distorted", "none", [0, 10, 8, 5], "rolls", "Underground rage"),
    ("Nettspend", "2021–2026", "East", "Trap", 140, 0.0, "rolls", "distorted", "pads", [0, 3, 10, 8], "rolls", "Digicore rage"),
    ("OsamaSon", "2021–2026", "South", "Trap", 142, 0.0, "rolls", "distorted", "bells", [0, 10, 7, 5], "rolls", "Rage underground"),
    ("Summrs", "2021–2026", "South", "Trap", 140, 0.0, "16ths", "glide", "pads", [0, 8, 3, 10], "rolls", "Plugg melodic"),
    ("Autumn!", "2021–2026", "South", "Trap", 138, 0.0, "16ths", "subby", "pads", [0, 5, 8, 3], "rolls", "Pluggnb"),
    ("Cash Cobain", "2021–2026", "East", "Drill", 142, 0.0, "8ths", "subby", "pluck", [0, 8, 10, 7], "rolls", "Sexy drill NYC"),
    ("Kyle Richh", "2021–2026", "East", "Drill", 142, 0.0, "8ths", "punchy", "darkpiano", [0, 8, 5, 10], "rolls", "NY drill 41"),
]

_ARTIST_STYLES = {}
for _r in _ARTIST_ROWS:
    _d = dict(era=_r[1], region=_r[2], base=_r[3], bpm=_r[4],
              swing=_r[5], hat=_r[6], bass=_r[7], melody=_r[8],
              prog=list(_r[9]), fill=_r[10], notes=_r[11])
    _ARTIST_STYLES[_r[0]] = _d
    _ARTIST_STYLES[_r[0].lower()] = _d
del _r, _d

ARTIST_GROUPS = []
for _era in ("2006–2010", "2011–2015", "2016–2020", "2021–2026"):
    ARTIST_GROUPS.append(
        (_era, [_r[0] for _r in _ARTIST_ROWS if _r[1] == _era]))
del _era


def get_artist_style(name):
    """Return the production-style dict for an artist, or None."""
    if not name:
        return None
    return _ARTIST_STYLES.get(str(name).strip().lower())


def artist_suggested_bpm(name):
    st = get_artist_style(name)
    return st["bpm"] if st else None


def artist_count():
    return len(_ARTIST_ROWS)




# ---------------------------------------------------------------- synthesis
def _stereo(mono):
    mono = np.asarray(mono, dtype=np.float32)
    return np.column_stack([mono, mono])


# ------------------------------------------------------- drum kit variants
# Each instrument has several synthesized variants. "classic" reproduces the
# original synthesis exactly (bit-identical) so the default kit never changes.
_KICK_VARIANTS = {
    "classic": dict(dur=0.32, f0=46.0, sweep=120.0, sweep_decay=32.0,
                    body_decay=10.0, click_decay=260.0, click_level=0.4,
                    level=0.95),
    "punchy": dict(dur=0.28, f0=50.0, sweep=150.0, sweep_decay=40.0,
                   body_decay=14.0, click_decay=320.0, click_level=0.62,
                   level=0.95),
    "boomy": dict(dur=0.42, f0=40.0, sweep=90.0, sweep_decay=22.0,
                  body_decay=6.0, click_decay=200.0, click_level=0.18,
                  level=0.95),
    "clicky": dict(dur=0.22, f0=55.0, sweep=140.0, sweep_decay=48.0,
                   body_decay=22.0, click_decay=420.0, click_level=0.7,
                   level=0.92),
    "sub": dict(dur=0.45, f0=48.0, sweep=40.0, sweep_decay=18.0,
                body_decay=5.0, click_decay=300.0, click_level=0.08,
                level=0.95),
    "trap": dict(dur=0.30, f0=44.0, sweep=160.0, sweep_decay=36.0,
                 body_decay=12.0, click_decay=380.0, click_level=0.55,
                 level=0.97),
    "drill": dict(dur=0.26, f0=52.0, sweep=170.0, sweep_decay=44.0,
                  body_decay=16.0, click_decay=400.0, click_level=0.66,
                  level=0.95),
    "lofi": dict(dur=0.36, f0=42.0, sweep=70.0, sweep_decay=20.0,
                 body_decay=8.0, click_decay=150.0, click_level=0.22,
                 level=0.88),
    "acoustic": dict(dur=0.34, f0=48.0, sweep=100.0, sweep_decay=28.0,
                     body_decay=11.0, click_decay=240.0, click_level=0.45,
                     level=0.92),
    "hardstyle": dict(dur=0.24, f0=58.0, sweep=190.0, sweep_decay=52.0,
                      body_decay=18.0, click_decay=460.0, click_level=0.75,
                      level=0.98),
    "jersey": dict(dur=0.28, f0=47.0, sweep=130.0, sweep_decay=34.0,
                   body_decay=13.0, click_decay=300.0, click_level=0.5,
                   level=0.94),
    "soft808": dict(dur=0.40, f0=45.0, sweep=60.0, sweep_decay=24.0,
                    body_decay=7.0, click_decay=220.0, click_level=0.12,
                    level=0.92),
}

_SNARE_VARIANTS = {
    "classic": dict(dur=0.22, noise_decay=26.0, noise_level=0.55,
                    body_freq=190.0, body_decay=34.0, body_level=0.5),
    "crisp": dict(dur=0.18, noise_decay=32.0, noise_level=0.68,
                  body_freq=210.0, body_decay=40.0, body_level=0.45),
    "deep": dict(dur=0.28, noise_decay=20.0, noise_level=0.5,
                 body_freq=150.0, body_decay=24.0, body_level=0.6),
    "rimmy": dict(dur=0.12, noise_decay=60.0, noise_level=0.35,
                  body_freq=420.0, body_decay=70.0, body_level=0.55),
    "trashy": dict(dur=0.30, noise_decay=16.0, noise_level=0.7,
                   body_freq=180.0, body_decay=28.0, body_level=0.4),
    "trap": dict(dur=0.20, noise_decay=30.0, noise_level=0.62,
                 body_freq=200.0, body_decay=36.0, body_level=0.48),
    "drill": dict(dur=0.16, noise_decay=38.0, noise_level=0.70,
                  body_freq=220.0, body_decay=44.0, body_level=0.42),
    "lofi": dict(dur=0.26, noise_decay=22.0, noise_level=0.48,
                 body_freq=165.0, body_decay=28.0, body_level=0.52),
    "acoustic": dict(dur=0.24, noise_decay=24.0, noise_level=0.52,
                     body_freq=185.0, body_decay=30.0, body_level=0.55),
    "marching": dict(dur=0.32, noise_decay=18.0, noise_level=0.58,
                     body_freq=140.0, body_decay=22.0, body_level=0.62),
    "snap": dict(dur=0.10, noise_decay=70.0, noise_level=0.45,
                 body_freq=800.0, body_decay=90.0, body_level=0.35),
    "gunshot": dict(dur=0.34, noise_decay=14.0, noise_level=0.78,
                    body_freq=170.0, body_decay=26.0, body_level=0.38),
}

_HAT_VARIANTS = {
    "classic": dict(dur=0.055, decay=150.0, level=0.5),
    "bright": dict(dur=0.050, decay=170.0, level=0.55),
    "dark": dict(dur=0.070, decay=110.0, level=0.45),
    "tight": dict(dur=0.035, decay=220.0, level=0.5),
    "loose": dict(dur=0.090, decay=90.0, level=0.48),
    "trap": dict(dur=0.045, decay=190.0, level=0.55),
    "drill": dict(dur=0.040, decay=200.0, level=0.52),
    "lofi": dict(dur=0.075, decay=100.0, level=0.42),
}

_OHAT_VARIANTS = {
    "classic": dict(dur=0.28, decay=16.0, level=0.42),
    "bright": dict(dur=0.30, decay=18.0, level=0.45),
    "dark": dict(dur=0.32, decay=12.0, level=0.38),
    "trap": dict(dur=0.34, decay=14.0, level=0.44),
    "drill": dict(dur=0.26, decay=20.0, level=0.46),
    "lofi": dict(dur=0.36, decay=10.0, level=0.36),
}

_CLAP_VARIANTS = {
    "classic": dict(bursts=(0.0, 0.012, 0.026), burst_decay=60.0,
                    tail_decay=22.0, level=0.5),
    "tight": dict(bursts=(0.0, 0.010), burst_decay=80.0,
                  tail_decay=30.0, level=0.5),
    "roomy": dict(bursts=(0.0, 0.012, 0.026, 0.040), burst_decay=45.0,
                  tail_decay=12.0, level=0.48),
    "layered": dict(bursts=(0.0, 0.008, 0.016, 0.026, 0.038),
                    burst_decay=55.0, tail_decay=20.0, level=0.45),
    "trap": dict(bursts=(0.0, 0.010, 0.022, 0.034), burst_decay=65.0,
                 tail_decay=24.0, level=0.48),
    "drill": dict(bursts=(0.0, 0.008, 0.018), burst_decay=75.0,
                  tail_decay=28.0, level=0.5),
    "stadium": dict(bursts=(0.0, 0.014, 0.030, 0.048, 0.066),
                    burst_decay=40.0, tail_decay=10.0, level=0.46),
    "snap": dict(bursts=(0.0, 0.006), burst_decay=95.0,
                 tail_decay=38.0, level=0.42),
}

# ------------------------------------------------- percussion variants
# One-shot percussion using the synth functions below (_tom, _rimshot, etc.)
# Each entry: (function_name, kwargs). Rendered by _perc().
_PERC_VARIANTS = {
    "shaker": ("shaker", dict(dur=0.12)),
    "shaker_long": ("shaker", dict(dur=0.20)),
    "tambourine": ("shaker", dict(dur=0.16)),
    "rimshot": ("rimshot", dict()),
    "cowbell": ("cowbell", dict(freq=560.0, dur=0.25)),
    "cowbell_high": ("cowbell", dict(freq=740.0, dur=0.20)),
    "conga_lo": ("conga", dict(freq=196.0, dur=0.25)),
    "conga_hi": ("conga", dict(freq=262.0, dur=0.22)),
    "tom_hi": ("tom", dict(freq=165.0, dur=0.32)),
    "tom_mid": ("tom", dict(freq=130.0, dur=0.34)),
    "tom_lo": ("tom", dict(freq=98.0, dur=0.38)),
    "crash": ("crash", dict(dur=1.2)),
    "crash_short": ("crash", dict(dur=0.6)),
    "ride": ("ride", dict(dur=0.8)),
    "ride_bell": ("ride", dict(dur=0.5)),
    "snap": ("rimshot", dict()),
}

# ------------------------------------------------------ 808/bass presets
# Named 808 presets: (dur, drive, glide_time). Rendered by _808_preset()
# at a given pitch via _bass808().
_808_VARIANTS = {
    "deep": dict(dur=0.60, drive=1.8, glide_time=0.040),
    "glide": dict(dur=0.55, drive=2.0, glide_time=0.045),
    "distorted": dict(dur=0.50, drive=3.5, glide_time=0.035),
    "subby": dict(dur=0.60, drive=1.2, glide_time=0.050),
    "punchy": dict(dur=0.42, drive=2.8, glide_time=0.030),
    "wobble": dict(dur=0.70, drive=2.4, glide_time=0.060),
    "reese": dict(dur=0.80, drive=1.5, glide_time=0.080),
    "short": dict(dur=0.30, drive=2.2, glide_time=0.025),
}

# ------------------------------------------------------ melodic presets
# Named melodic instruments: (function_name, default_dur).
# Rendered by _melodic() at a given pitch.
_MELODIC_VARIANTS = {
    "piano": ("piano", 0.5),
    "piano_dark": ("piano", 0.7),
    "bells": ("bells", 1.1),
    "bells_soft": ("bells", 1.4),
    "pad": ("pad", 1.8),
    "pad_dark": ("pad", 2.2),
    "pluck": ("pluck", 0.45),
    "pluck_soft": ("pluck", 0.60),
    "flute": ("flute", 0.6),
    "brass": ("brass", 0.4),
    "brass_stab": ("brass", 0.25),
    "choir": ("choir", 1.5),
    "marimba": ("marimba", 0.5),
    "koto": ("koto", 0.7),
}

# ----------------------------------------------------------- FX presets
# Transition FX: risers, impacts, downshifters. Rendered by _fx().
_FX_VARIANTS = {
    "riser_short": dict(kind="riser", dur=1.0),
    "riser_med": dict(kind="riser", dur=2.0),
    "riser_long": dict(kind="riser", dur=4.0),
    "impact": dict(kind="impact", dur=0.8),
    "impact_huge": dict(kind="impact", dur=1.5),
    "downshifter": dict(kind="downshifter", dur=1.2),
    "vinyl_stop": dict(kind="vinyl_stop", dur=0.6),
    "siren": dict(kind="siren", dur=1.5),
    "airhorn": dict(kind="airhorn", dur=0.9),
}

# Named kits: pick one variant per instrument. "classic" = original sounds.
_KITS = {
    "classic": dict(label="Classic", desc="The original Prhyme™ drums",
                    kick="classic", snare="classic", chat="classic",
                    ohat="classic", clap="classic", bass="glide"),
    "punchy": dict(label="Punchy", desc="Hard-hitting, aggressive",
                   kick="punchy", snare="crisp", chat="bright",
                   ohat="bright", clap="tight", bass="punchy"),
    "boomy": dict(label="Boomy", desc="Deep, heavy low end",
                  kick="boomy", snare="deep", chat="dark",
                  ohat="dark", clap="roomy", bass="subby"),
    "street": dict(label="Street", desc="Raw, clicky Memphis edge",
                   kick="clicky", snare="rimmy", chat="tight",
                   ohat="classic", clap="tight", bass="distorted"),
    "smooth": dict(label="Smooth", desc="Soft, rounded, mellow",
                   kick="sub", snare="deep", chat="loose",
                   ohat="dark", clap="roomy", bass="subby"),
    "hard": dict(label="Hard", desc="Maximum aggression",
                 kick="punchy", snare="trashy", chat="bright",
                 ohat="bright", clap="layered", bass="distorted"),
}

# Genre-organized full kits. Each kit picks variants for every instrument
# plus preferred percussion, 808, melodic, and FX flavors.
_GENRE_KITS = {
    "hiphop": dict(label="Hip-Hop", desc="Boom-bap, classic rap drums",
                   kick="classic", snare="crisp", chat="tight",
                   ohat="classic", clap="tight", bass="glide",
                   perc="rimshot", b808="deep", melodic="piano",
                   fx="impact"),
    "trap": dict(label="Trap", desc="Hard 808s, rolling hats",
                 kick="trap", snare="trap", chat="trap",
                 ohat="trap", clap="trap", bass="distorted",
                 perc="shaker", b808="distorted", melodic="bells",
                 fx="riser_med"),
    "drill": dict(label="Drill", desc="Dark, sliding 808s, militant",
                  kick="drill", snare="drill", chat="drill",
                  ohat="drill", clap="drill", bass="punchy",
                  perc="cowbell", b808="punchy", melodic="choir",
                  fx="downshifter"),
    "rnb": dict(label="R&B", desc="Smooth, silky, late-night",
                kick="sub", snare="deep", chat="loose",
                ohat="dark", clap="roomy", bass="subby",
                perc="shaker_long", b808="subby", melodic="pad",
                fx="riser_short"),
    "lofi": dict(label="Lo-Fi", desc="Dusty, mellow, vinyl warmth",
                 kick="lofi", snare="lofi", chat="lofi",
                 ohat="lofi", clap="roomy", bass="subby",
                 perc="tambourine", b808="deep", melodic="piano_dark",
                 fx="vinyl_stop"),
    "jersey": dict(label="Jersey Club", desc="Bouncy, high-energy club",
                   kick="jersey", snare="snap", chat="bright",
                   ohat="bright", clap="layered", bass="punchy",
                   perc="cowbell_high", b808="punchy", melodic="brass_stab",
                   fx="airhorn"),
    "rage": dict(label="Rage", desc="Distorted, blown-out, aggressive",
                 kick="hardstyle", snare="gunshot", chat="bright",
                 ohat="bright", clap="stadium", bass="distorted",
                 perc="crash", b808="wobble", melodic="brass",
                 fx="impact_huge"),
    "afrobeats": dict(label="Afrobeats", desc="Warm percussion, bounce",
                      kick="soft808", snare="snap", chat="loose",
                      ohat="classic", clap="snap", bass="glide",
                      perc="conga_hi", b808="glide", melodic="marimba",
                      fx="riser_short"),
    "rocknroll": dict(label="Rock 'n' Roll", desc="Driving backbeat, twangy guitar",
                      kick="acoustic", snare="acoustic", chat="loose",
                      ohat="classic", clap="roomy", bass="punchy",
                      perc="tambourine", b808="punchy", melodic="guitar",
                      fx="impact"),
    "heavymetal": dict(label="Heavy Metal", desc="Double kick, distorted guitars",
                       kick="hardstyle", snare="gunshot", chat="tight",
                       ohat="bright", clap="stadium", bass="distorted",
                       perc="crash", b808="distorted", melodic="guitar_dist",
                       fx="impact_huge"),
    "breakbeat": dict(label="Breakbeat", desc="Chopped breaks, big beat energy",
                      kick="punchy", snare="crisp", chat="tight",
                      ohat="classic", clap="layered", bass="punchy",
                      perc="tambourine", b808="punchy", melodic="piano",
                      fx="impact"),
    "dubstep": dict(label="Dubstep", desc="Half-time, wobble bass, heavy drops",
                    kick="hardstyle", snare="gunshot", chat="tight",
                    ohat="dark", clap="stadium", bass="distorted",
                    perc="crash", b808="wobble", melodic="brass",
                    fx="downshifter"),
    "reggaeton": dict(label="Reggaeton", desc="Dembow rhythm, latin bounce",
                      kick="punchy", snare="snap", chat="loose",
                      ohat="classic", clap="snap", bass="glide",
                      perc="conga_hi", b808="glide", melodic="marimba",
                      fx="riser_short"),
    "phonk": dict(label="Phonk", desc="Dark Memphis, cowbells, distorted 808s",
                  kick="trap", snare="trap", chat="trap",
                  ohat="dark", clap="trap", bass="distorted",
                  perc="cowbell", b808="distorted", melodic="bells",
                  fx="riser_med"),
}

# Merge genre kits into the main kit registry (character kits keep priority).
_KITS.update(_GENRE_KITS)


def list_kits():
    """Return [{name, label, desc, group}] for the built-in drum kits."""
    return [{"name": k, "label": v["label"], "desc": v["desc"],
             "group": "genre" if k in _GENRE_KITS else "character"}
            for k, v in _KITS.items()]


def get_kit(name):
    """Return the kit dict for name, falling back to classic."""
    return _KITS.get(name or "classic", _KITS["classic"])


def list_kit_variants():
    """Return {instrument: [variant names]} for UI selectors."""
    return {
        "kick": list(_KICK_VARIANTS),
        "snare": list(_SNARE_VARIANTS),
        "chat": list(_HAT_VARIANTS),
        "ohat": list(_OHAT_VARIANTS),
        "clap": list(_CLAP_VARIANTS),
        "bass": ["glide", "distorted", "subby", "sparse", "punchy"],
        "perc": list(_PERC_VARIANTS),
        "808": list(_808_VARIANTS),
        "melodic": list(_MELODIC_VARIANTS),
        "fx": list(_FX_VARIANTS),
    }


def _kick(sr, rng, variant="classic"):
    p = _KICK_VARIANTS.get(variant, _KICK_VARIANTS["classic"])
    n = int(sr * p["dur"])
    t = np.arange(n) / sr
    f = p["f0"] + p["sweep"] * np.exp(-t * p["sweep_decay"])
    phase = 2 * np.pi * np.cumsum(f) / sr
    body = np.sin(phase) * np.exp(-t * p["body_decay"])
    click = (rng.standard_normal(n) * np.exp(-t * p["click_decay"])
             * p["click_level"])
    return _stereo((body + click) * p["level"])


def _snare(sr, rng, variant="classic"):
    p = _SNARE_VARIANTS.get(variant, _SNARE_VARIANTS["classic"])
    n = int(sr * p["dur"])
    t = np.arange(n) / sr
    noise = (rng.standard_normal(n) * np.exp(-t * p["noise_decay"])
             * p["noise_level"])
    body = (np.sin(2 * np.pi * p["body_freq"] * t)
            * np.exp(-t * p["body_decay"]) * p["body_level"])
    return _stereo(noise + body)


def _hat(sr, rng, dur=None, decay=None, level=None, variant="classic"):
    p = _HAT_VARIANTS.get(variant, _HAT_VARIANTS["classic"])
    dur = p["dur"] if dur is None else dur
    decay = p["decay"] if decay is None else decay
    level = p["level"] if level is None else level
    n = int(sr * dur)
    t = np.arange(n) / sr
    noise = rng.standard_normal(n)
    hp = np.diff(noise, prepend=noise[0])  # crude highpass, no scipy needed
    return _stereo(hp * np.exp(-t * decay) * level)


def _ohat(sr, rng, variant="classic"):
    p = _OHAT_VARIANTS.get(variant, _OHAT_VARIANTS["classic"])
    return _hat(sr, rng, dur=p["dur"], decay=p["decay"], level=p["level"])


def _clap(sr, rng, variant="classic"):
    p = _CLAP_VARIANTS.get(variant, _CLAP_VARIANTS["classic"])
    n = int(sr * 0.2)
    t = np.arange(n) / sr
    out = np.zeros(n)
    for d in p["bursts"]:
        k = int(d * sr)
        m = n - k
        out[k:] += (rng.standard_normal(m)
                    * np.exp(-np.arange(m) / sr * p["burst_decay"]))
    hp = np.diff(out, prepend=out[0])
    return _stereo(hp * np.exp(-t * p["tail_decay"]) * p["level"])


def _bass808(sr, freq, glide_from=None, dur=0.55, drive=2.0,
             glide_time=0.045):
    """808 with click-free pitch glide via phase accumulation.

    glide_from: previous note's frequency (portamento between notes).
    Bigger intervals get a longer slide for that trap glide feel; the
    phase-accumulated sine never clicks, and tanh saturation adds warmth.
    """
    n = int(sr * dur)
    t = np.arange(n) / sr
    f0 = glide_from if glide_from else freq * 1.6
    interval = abs(np.log2(max(f0, 1.0) / max(freq, 1.0)))
    gt = glide_time * (1.0 + min(2.0, interval))  # wide jump = longer slide
    f = freq + (f0 - freq) * np.exp(-t / max(0.008, gt))
    phase = 2 * np.pi * np.cumsum(f) / sr
    sig = np.tanh(drive * np.sin(phase)) * np.exp(-t * 5.5)
    return _stereo(sig * 0.85)


def _bass_sub(sr, freq, dur=0.6):
    """Clean sub-bass: pure sine + whisper of 2nd harmonic, slow decay."""
    n = int(sr * dur)
    t = np.arange(n) / sr
    sig = (np.sin(2 * np.pi * freq * t)
           + 0.12 * np.sin(2 * np.pi * 2 * freq * t))
    return _stereo(sig * np.exp(-t * 4.0) * 0.8)


def _piano(sr, freq, dur=0.5):
    """Dark piano-ish stab: percussive attack, fast-decaying harmonics."""
    n = int(sr * dur)
    t = np.arange(n) / sr
    sig = (np.sin(2 * np.pi * freq * t) * np.exp(-t * 6.0)
           + 0.45 * np.sin(2 * np.pi * 2 * freq * t) * np.exp(-t * 11.0)
           + 0.2 * np.sin(2 * np.pi * 3 * freq * t) * np.exp(-t * 18.0))
    return _stereo(sig * 0.42)


def _bells(sr, freq, dur=1.1):
    """Bright bell: inharmonic partial, long shimmering decay."""
    n = int(sr * dur)
    t = np.arange(n) / sr
    sig = (np.sin(2 * np.pi * freq * t) * np.exp(-t * 3.2)
           + 0.35 * np.sin(2 * np.pi * 2.76 * freq * t) * np.exp(-t * 5.0)
           + 0.12 * np.sin(2 * np.pi * 5.4 * freq * t) * np.exp(-t * 8.0))
    return _stereo(sig * 0.38)


def _pad(sr, freqs, dur=1.8):
    """Ethereal pad chord: slow attack, detuned shimmer, soft release."""
    n = int(sr * dur)
    t = np.arange(n) / sr
    sig = np.zeros(n)
    for f in freqs:
        for det in (0.998, 1.0, 1.003):
            sig += np.sin(2 * np.pi * f * det * t)
    sig /= max(1, len(freqs) * 3)
    atk = np.minimum(1.0, t / (dur * 0.35))
    rel = np.exp(-np.maximum(0.0, t - dur * 0.7) * 6.0)
    return _stereo(sig * atk * rel * 0.5)


def _bass_note(sr, freq, glide_from, style, staccato=False):
    """Dispatch 808/bass texture by artist style.

    staccato=True cuts the note short (0.18s with a quick fade) — mixing
    short and long 808s gives groove through length contrast, not just pitch.
    """
    if style == "distorted":
        note = _bass808(sr, freq, glide_from, dur=0.5, drive=3.5)
    elif style == "subby":
        note = _bass_sub(sr, freq, dur=0.6)
    elif style == "sparse":
        note = _bass808(sr, freq, None, dur=0.30, drive=2.2)
    elif style == "punchy":
        note = _bass808(sr, freq, glide_from, dur=0.42, drive=2.8)
    else:
        note = _bass808(sr, freq, glide_from, dur=0.55, drive=2.0)  # glide
    if staccato:
        cut = int(sr * 0.18)
        if note.shape[0] > cut:
            note = note[:cut].copy()
            fl = min(cut, int(sr * 0.03))
            fade = np.linspace(1.0, 0.0, fl, dtype=np.float32)
            note[-fl:] *= fade[:, None]
    return note


def _pluck(sr, freq, dur=0.45):
    n = int(sr * dur)
    t = np.arange(n) / sr
    sig = (np.sin(2 * np.pi * freq * t)
           + 0.4 * np.sin(2 * np.pi * 2 * freq * t)
           + 0.18 * np.sin(2 * np.pi * 3 * freq * t))
    return _stereo(sig * np.exp(-t * 7.0) * 0.4)


# ------------------------------------------------------- extra instruments
# All pure-numpy synthesis. New percussive layers use a separate RNG stream
# (rng2) so the core groove's random sequence stays bit-identical.
def _tom(sr, rng, freq=130.0, dur=0.32):
    """Pitch-swept drum tom."""
    n = int(sr * dur)
    t = np.arange(n) / sr
    f = freq + freq * 0.8 * np.exp(-t * 28.0)
    phase = 2 * np.pi * np.cumsum(f) / sr
    body = np.sin(phase) * np.exp(-t * 9.0)
    click = rng.standard_normal(n) * np.exp(-t * 180.0) * 0.25
    return _stereo((body + click) * 0.8)


def _rimshot(sr, rng):
    """Woody rim click."""
    n = int(sr * 0.09)
    t = np.arange(n) / sr
    body = np.sin(2 * np.pi * 420.0 * t) * np.exp(-t * 90.0) * 0.6
    click = rng.standard_normal(n) * np.exp(-t * 400.0) * 0.5
    return _stereo((body + click) * 0.7)


def _shaker(sr, rng, dur=0.12):
    """Grainy shaker: bright noise with a pulsing envelope."""
    n = int(sr * dur)
    t = np.arange(n) / sr
    noise = rng.standard_normal(n)
    hp = np.diff(noise, prepend=noise[0])
    env = np.exp(-t * 40.0) * (0.6 + 0.4 * np.sin(2 * np.pi * 30.0 * t) ** 2)
    return _stereo(hp * env * 0.35)


def _cowbell(sr, freq=560.0, dur=0.25):
    """Classic 808 cowbell: two detuned square waves."""
    n = int(sr * dur)
    t = np.arange(n) / sr
    sig = np.sign(np.sin(2 * np.pi * freq * t))
    sig += np.sign(np.sin(2 * np.pi * freq * 1.49 * t))
    return _stereo(sig * np.exp(-t * 18.0) * 0.28)


def _crash(sr, rng, dur=1.2):
    """Long bright crash cymbal."""
    n = int(sr * dur)
    t = np.arange(n) / sr
    noise = rng.standard_normal(n)
    hp = np.diff(noise, prepend=noise[0])
    return _stereo(hp * np.exp(-t * 4.5) * 0.4)


def _ride(sr, rng, dur=0.8):
    """Metallic ride ping: inharmonic partials + stick noise."""
    n = int(sr * dur)
    t = np.arange(n) / sr
    sig = (np.sin(2 * np.pi * 310.0 * t)
           + 0.6 * np.sin(2 * np.pi * 417.0 * t)
           + 0.4 * np.sin(2 * np.pi * 521.0 * t)) * np.exp(-t * 7.0)
    noise = rng.standard_normal(n) * np.exp(-t * 30.0) * 0.2
    return _stereo((sig + noise) * 0.3)


def _conga(sr, rng, freq=210.0, dur=0.25):
    """Open conga tone: pitch-swept membrane."""
    n = int(sr * dur)
    t = np.arange(n) / sr
    f = freq + freq * 0.5 * np.exp(-t * 35.0)
    phase = 2 * np.pi * np.cumsum(f) / sr
    sig = (np.sin(phase) * np.exp(-t * 14.0)
           + 0.3 * np.sin(2 * phase) * np.exp(-t * 22.0))
    return _stereo(sig * 0.6)


def _flute(sr, freq, dur=0.6):
    """Breathy flute lead with vibrato."""
    n = int(sr * dur)
    t = np.arange(n) / sr
    vib = 1.0 + 0.006 * np.sin(2 * np.pi * 5.5 * t)
    sig = (np.sin(2 * np.pi * freq * vib * t)
           + 0.25 * np.sin(2 * np.pi * 2 * freq * vib * t))
    atk = np.minimum(1.0, t / 0.06)
    rel = np.exp(-np.maximum(0.0, t - dur * 0.7) * 8.0)
    return _stereo(sig * atk * rel * 0.35)


def _brass(sr, freq, dur=0.4):
    """Brass stab: stacked detuned saws, smoothed, fast attack."""
    n = int(sr * dur)
    t = np.arange(n) / sr
    saw = lambda f: 2.0 * ((f * t) % 1.0) - 1.0
    sig = saw(freq) + 0.6 * saw(freq * 1.005) + 0.4 * saw(freq * 2.0)
    k = 24
    sig = np.convolve(sig, np.ones(k) / k, mode="same")
    atk = np.minimum(1.0, t / 0.03)
    return _stereo(sig * np.exp(-t * 6.0) * atk * 0.3)


def _choir(sr, freqs, dur=1.5):
    """Choir-ish pad: detuned octave-doubled sines, slow attack."""
    n = int(sr * dur)
    t = np.arange(n) / sr
    sig = np.zeros(n)
    for f in freqs:
        for det in (0.997, 1.0, 1.004):
            sig += (np.sin(2 * np.pi * f * det * t)
                    + 0.3 * np.sin(2 * np.pi * 2 * f * det * t))
    sig /= max(1, len(freqs) * 3)
    atk = np.minimum(1.0, t / 0.4)
    rel = np.exp(-np.maximum(0.0, t - dur * 0.75) * 4.0)
    return _stereo(sig * atk * rel * 0.3)


def _marimba(sr, freq, dur=0.5):
    """Warm marimba: sine + 4th/10th partials, medium decay."""
    n = int(sr * dur)
    t = np.arange(n) / sr
    sig = (np.sin(2 * np.pi * freq * t) * np.exp(-t * 9.0)
           + 0.35 * np.sin(2 * np.pi * 4 * freq * t) * np.exp(-t * 20.0)
           + 0.12 * np.sin(2 * np.pi * 9.8 * freq * t) * np.exp(-t * 30.0))
    return _stereo(sig * 0.4)


def _koto(sr, freq, dur=0.7):
    """Bright koto-like pluck: long sustain + sharp attack transient."""
    n = int(sr * dur)
    t = np.arange(n) / sr
    sig = (np.sin(2 * np.pi * freq * t)
           + 0.5 * np.sin(2 * np.pi * 2 * freq * t)
           + 0.3 * np.sin(2 * np.pi * 3.01 * freq * t)) * np.exp(-t * 5.0)
    sig += 0.3 * np.sin(2 * np.pi * 5 * freq * t) * np.exp(-t * 40.0)
    return _stereo(sig * 0.35)


# Melodic instrument dispatch: name -> function taking (sr, freq).
_MEL_INST = {
    "pluck": _pluck,
    "darkpiano": _piano,
    "bells": _bells,
    "flute": _flute,
    "brass": _brass,
    "marimba": _marimba,
    "koto": _koto,
}
# Pad-style instruments take (sr, freqs) instead.
_MEL_PAD_INST = {"pads": _pad, "choir": _choir}

MELODY_INSTRUMENTS = sorted(set(_MEL_INST) | set(_MEL_PAD_INST) | {"none"})


def _midi_to_freq(m):
    return 440.0 * 2.0 ** ((m - 69) / 12.0)


def _solfeggio_drone(sr, freq, dur, binaural=False, beat_hz=3.0):
    """Soft drone bed: slow attack, gentle harmonics, quiet level.

    Deterministic (pure sines, no RNG). With binaural=True the right channel
    runs beat_hz sharp for a spacious headphone feel (3 Hz default, or a
    brainwave-band rate like 10 Hz alpha).
    """
    n = int(sr * dur)
    t = np.arange(n) / sr

    def voice(f):
        return (np.sin(2 * np.pi * f * t)
                + 0.30 * np.sin(2 * np.pi * 2 * f * t)
                + 0.12 * np.sin(2 * np.pi * 3 * f * t))

    atk = np.minimum(1.0, t / max(0.5, dur * 0.15))
    rel = np.exp(-np.maximum(0.0, t - dur * 0.80) * 3.0)
    env = atk * rel * 0.10
    if binaural:
        left, right = voice(freq) * env, voice(freq + beat_hz) * env
    else:
        left = right = voice(freq) * env
    return np.column_stack([left, right]).astype(np.float32)


def _healing_drone_into(out, sr, bar_dur, bars, heal):
    """Lay the drone bed under the beat, cycling per 4-bar phrase.

    The tone set follows heal['drone_mode'] (solfeggio / chakra / planetary);
    heal['drone_root'] pins a single frequency; otherwise the mode's cycle
    plays phrase by phrase.
    """
    phrase = 4
    root = heal.get("drone_root") or heal.get("solfeggio_root")
    mode = heal.get("drone_mode") or "solfeggio"
    cycle = {"chakra": _CHAKRA_CYCLE,
             "planetary": _PLANETARY_CYCLE}.get(mode, _SOLFEGGIO_CYCLE)
    beat_hz = float(heal.get("beat_hz") or 3.0)
    for p0 in range(0, bars, phrase):
        nb = min(phrase, bars - p0)
        if root:
            f = float(root)
        else:
            f = cycle[(p0 // phrase) % len(cycle)]
        d = _solfeggio_drone(sr, f, nb * bar_dur,
                             binaural=heal["binaural"], beat_hz=beat_hz)
        _place(out, d, int(p0 * bar_dur * sr))


# ---------------------------------------------------------------- placement
def _place(out, sound, pos):
    """Add a stereo one-shot into the output buffer at sample position."""
    total = out.shape[0]
    if pos >= total:
        return
    n = sound.shape[0]
    end = pos + n
    if end > total:
        sound = sound[:total - pos]
        end = total
    out[pos:end] += sound


# ------------------------------------------------- Gemini redesign helpers
# Micro-timing, velocity-coupled filtering, and low-end mono — all pure
# numpy, deterministic per seed (draws come from the caller's rng streams).


def _jit(pos, step_dur, rng, amt_ms=0.8):
    """Micro-timing: Gaussian jitter on a trigger position (samples).

    amt_ms ~0.8ms keeps the groove human without smearing the grid.
    Clamped at 0 so early first-bar hits can't go negative.
    """
    return max(0, int(pos) + int(rng.normal(0.0, amt_ms / 1000.0 * SR)))


def _darken(hit, velocity):
    """Velocity-coupled filtering: quieter hits get darker, not just softer.

    One-pole lowpass with cutoff mapped from velocity (0.3..0.9 ->
    2.5kHz..12kHz). Full-velocity hits pass through untouched.
    """
    if velocity >= 0.9:
        return hit
    cutoff = 2500.0 + (velocity - 0.3) / 0.6 * 9500.0
    cutoff = min(12000.0, max(1200.0, cutoff))
    alpha = 1.0 - np.exp(-2.0 * np.pi * cutoff / SR)
    y = np.empty_like(hit)
    for ch in range(hit.shape[1]):
        acc = 0.0
        x = hit[:, ch]
        o = y[:, ch]
        a = alpha
        for i in range(x.shape[0]):
            acc += a * (x[i] - acc)
            o[i] = acc
    return y


def _pitch_shift(sound, factor):
    """Resample-based pitch shift (factor < 1 = lower pitch, longer)."""
    n = sound.shape[0]
    new_n = max(8, int(n / factor))
    old_idx = np.linspace(0, n - 1, new_n)
    out = np.empty((new_n, sound.shape[1]), dtype=np.float32)
    for ch in range(sound.shape[1]):
        out[:, ch] = np.interp(old_idx, np.arange(n), sound[:, ch])
    return out


def _haas(stereo, delay_ms=12.0):
    """Haas widening: delay the right channel 8-15ms for stereo width.

    Apply to hats and pluck melody only — kick and 808 stay mono.
    """
    d = int(delay_ms / 1000.0 * SR)
    out = np.zeros_like(stereo)
    out[:, 0] = stereo[:, 0]
    if d < stereo.shape[0]:
        out[d:, 1] = stereo[:stereo.shape[0] - d, 1]
    return out


def _riser(sr, rng, dur):
    """1-bar filtered noise sweep: lowpass cutoff rises into the drop."""
    n = int(sr * dur)
    t = np.arange(n) / sr
    noise = rng.standard_normal(n)
    cutoff = 400.0 * (8000.0 / 400.0) ** (t / dur)
    y = np.zeros(n, dtype=np.float32)
    acc = 0.0
    for i in range(n):
        a = 1.0 - np.exp(-2.0 * np.pi * cutoff[i] / sr)
        acc += a * (noise[i] - acc)
        y[i] = acc
    env = np.minimum(1.0, t / (dur * 0.1))
    env = env * np.minimum(1.0, (dur - t) / (dur * 0.05) + 0.2)
    return _stereo(y * env * 0.5)


def _impact(sr, rng, dur=0.8):
    """Big cinematic impact: sub boom + noise crash."""
    n = int(sr * dur)
    t = np.arange(n) / sr
    boom = np.sin(2 * np.pi * 55.0 * t) * np.exp(-t * 6.0)
    boom += 0.5 * np.sin(2 * np.pi * 110.0 * t) * np.exp(-t * 9.0)
    noise = rng.standard_normal(n)
    hp = np.diff(noise, prepend=noise[0])
    crash = hp * np.exp(-t * 5.0) * 0.4
    return _stereo((boom + crash) * np.exp(-t * 3.0) * 0.7)


def _downshifter(sr, dur=1.2):
    """Pitch-falling sweep (drop-out effect)."""
    n = int(sr * dur)
    t = np.arange(n) / sr
    f = 800.0 * (60.0 / 800.0) ** (t / dur)
    phase = 2 * np.pi * np.cumsum(f) / sr
    sig = np.sin(phase) * np.minimum(1.0, (dur - t) / (dur * 0.3))
    return _stereo(sig * 0.5)


def _vinyl_stop(sr, dur=0.6):
    """Record-stop spin-down: pitch dives to zero."""
    n = int(sr * dur)
    t = np.arange(n) / sr
    f = 440.0 * np.maximum(0.0, 1.0 - (t / dur) ** 1.5)
    phase = 2 * np.pi * np.cumsum(f) / sr
    sig = np.sin(phase) * np.exp(-t * 2.0)
    return _stereo(sig * 0.45)


def _siren(sr, dur=1.5):
    """Air-raid style siren wail."""
    n = int(sr * dur)
    t = np.arange(n) / sr
    f = 600.0 + 300.0 * np.sin(2 * np.pi * 1.2 * t)
    phase = 2 * np.pi * np.cumsum(f) / sr
    sig = np.sign(np.sin(phase)) * 0.6 + np.sin(phase) * 0.4
    env = np.minimum(1.0, t / 0.1) * np.minimum(1.0, (dur - t) / 0.2)
    return _stereo(sig * env * 0.3)


def _airhorn(sr, dur=0.9):
    """Stadium airhorn blast."""
    n = int(sr * dur)
    t = np.arange(n) / sr
    f = 440.0
    sig = (np.sign(np.sin(2 * np.pi * f * t))
           + 0.7 * np.sign(np.sin(2 * np.pi * f * 1.26 * t))
           + 0.5 * np.sign(np.sin(2 * np.pi * f * 1.5 * t)))
    env = np.minimum(1.0, t / 0.03) * np.minimum(1.0, (dur - t) / 0.15)
    return _stereo(sig * env * 0.25)


# ------------------------------------------------- sound dispatchers
# Render any single kit sound by category + variant name.
# Used by the /api/kit/sound preview endpoint and the sound browser UI.

_PERC_FUNCS = {
    "shaker": _shaker, "rimshot": _rimshot, "cowbell": _cowbell,
    "conga": _conga, "tom": _tom, "crash": _crash, "ride": _ride,
}

_MELODIC_FUNCS = {
    "piano": _piano, "bells": _bells, "pluck": _pluck,
    "flute": _flute, "brass": _brass, "marimba": _marimba,
    "koto": _koto,
}

_MELODIC_CHORD_FUNCS = {
    "pad": _pad, "choir": _choir,
}

_FX_FUNCS = {
    "riser": _riser, "impact": _impact, "downshifter": _downshifter,
    "vinyl_stop": _vinyl_stop, "siren": _siren, "airhorn": _airhorn,
}


def _perc(sr, rng, variant="shaker"):
    """Render a percussion one-shot by variant name."""
    fn_name, kw = _PERC_VARIANTS.get(variant, _PERC_VARIANTS["shaker"])
    fn = _PERC_FUNCS[fn_name]
    if fn_name in ("shaker",):
        return fn(sr, rng, **kw)
    if fn_name in ("rimshot",):
        return fn(sr, rng)
    return fn(sr, **kw) if fn_name in ("cowbell",) else fn(sr, rng, **kw)


def _808_preset(sr, freq=55.0, variant="deep", glide_from=None):
    """Render an 808 bass note by preset name at a given pitch."""
    p = _808_VARIANTS.get(variant, _808_VARIANTS["deep"])
    return _bass808(sr, freq, glide_from, dur=p["dur"],
                    drive=p["drive"], glide_time=p["glide_time"])


def _melodic(sr, freq=220.0, variant="piano", freqs=None):
    """Render a melodic one-shot by variant name at a given pitch."""
    base = variant.split("_")[0]
    if base in _MELODIC_CHORD_FUNCS:
        fn = _MELODIC_CHORD_FUNCS[base]
        chord = freqs or (freq, freq * 1.25, freq * 1.5)
        _, dur = _MELODIC_VARIANTS.get(variant, ("pad", 1.8))
        return fn(sr, chord, dur=dur)
    fn_name, dur = _MELODIC_VARIANTS.get(variant, ("piano", 0.5))
    return _MELODIC_FUNCS[fn_name](sr, freq, dur=dur)


def _fx(sr, rng, variant="impact"):
    """Render a transition FX one-shot by variant name."""
    p = _FX_VARIANTS.get(variant, _FX_VARIANTS["impact"])
    kind, dur = p["kind"], p["dur"]
    if kind == "riser":
        return _riser(sr, rng, dur)
    fn = _FX_FUNCS[kind]
    try:
        return fn(sr, rng, dur)
    except TypeError:
        return fn(sr, dur)


def _bass(sr, freq=55.0, variant="reese"):
    """Render a bass one-shot by variant name at a given pitch."""
    fname, dur = _BASS_VARIANTS.get(variant, ("reese_bass", 0.6))
    return _BASS_FUNCS[fname](sr, freq, dur=dur)


def _loop(sr, rng, variant="boom_bap"):
    """Render a drum loop by variant name."""
    p = _LOOP_VARIANTS.get(variant, _LOOP_VARIANTS["boom_bap"])
    pattern = p["pattern"]
    bars = p.get("bars", 2)
    bpm_shift = p.get("bpm_shift", 0)
    # Render kit one-shots for this pattern's kit
    kit_name = _soundx._LOOP_KIT_MAP.get(pattern, "classic")
    kit = get_kit(kit_name)
    kit_sounds = {
        "kick": _kick(sr, rng, kit.get("kick", "classic")),
        "snare": _snare(sr, rng, kit.get("snare", "classic")),
        "chat": _hat(sr, rng, variant=kit.get("chat", "classic")),
        "ohat": _ohat(sr, rng, kit.get("ohat", "classic")),
        "clap": _clap(sr, rng, kit.get("clap", "classic")),
    }
    # percussion if pattern uses it
    if "perc" in _soundx._LOOP_PATTERNS[pattern]:
        kit_sounds["perc"] = _perc(sr, rng, kit.get("perc", "shaker"))
    out = _soundx.render_drum_loop(sr, rng, pattern, kit_sounds, bars=bars)
    if bpm_shift:
        # simple resample for BPM shift (not pitch-preserving, but fine for preview)
        factor = 1.0 + bpm_shift / _soundx._LOOP_PATTERNS[pattern]["bpm"]
        n_new = int(len(out) / factor)
        idx = (np.arange(n_new) * factor).astype(int)
        idx = np.clip(idx, 0, len(out) - 1)
        out = out[idx]
    return out


# Expand the sound library to 1500+ parametric variations (originals untouched).
if _SOUNDX_AVAILABLE:
    import sys as _sys
    _SOUNDX_COUNTS = _soundx.build_expanded_library(_sys.modules[__name__])
else:
    _SOUNDX_COUNTS = {}
    _BASS_VARIANTS = {}
    _BASS_FUNCS = {}
    _LOOP_VARIANTS = {}


def render_kit_sound(category, variant, freq=220.0, seed=7):
    """Render a single kit sound -> stereo float32 @ 44100.

    category: kick|snare|chat|ohat|clap|perc|808|melodic|fx|bass|loops
    """
    sr = SR
    rng = np.random.default_rng(seed)
    if category == "kick":
        return _kick(sr, rng, variant)
    if category == "snare":
        return _snare(sr, rng, variant)
    if category == "chat":
        return _hat(sr, rng, variant=variant)
    if category == "ohat":
        return _ohat(sr, rng, variant)
    if category == "clap":
        return _clap(sr, rng, variant)
    if category == "perc":
        return _perc(sr, rng, variant)
    if category == "808":
        return _808_preset(sr, freq, variant)
    if category == "melodic":
        return _melodic(sr, freq, variant)
    if category == "fx":
        return _fx(sr, rng, variant)
    if category == "bass":
        return _bass(sr, freq, variant)
    if category == "loops":
        return _loop(sr, rng, variant)
    raise ValueError(f"Unknown category: {category}")


def list_all_sounds():
    """Return {category: [variant names]} for the full sound browser."""
    out = {
        "kick": sorted(_KICK_VARIANTS),
        "snare": sorted(_SNARE_VARIANTS),
        "chat": sorted(_HAT_VARIANTS),
        "ohat": sorted(_OHAT_VARIANTS),
        "clap": sorted(_CLAP_VARIANTS),
        "perc": sorted(_PERC_VARIANTS),
        "808": sorted(_808_VARIANTS),
        "melodic": sorted(_MELODIC_VARIANTS),
        "fx": sorted(_FX_VARIANTS),
    }
    if _BASS_VARIANTS:
        out["bass"] = sorted(_BASS_VARIANTS)
    if _LOOP_VARIANTS:
        out["loops"] = sorted(_LOOP_VARIANTS)
    return out


def count_all_sounds():
    """Total number of individual sounds across all categories."""
    return sum(len(v) for v in list_all_sounds().values())


def _bus_glue(drums, thresh=0.4, ratio=3.0, attack_ms=5.0, release_ms=80.0):
    """Feedforward compressor for drum-bus glue (before soft clipping)."""
    mono = np.abs(drums).mean(axis=1)
    atk = np.exp(-1.0 / (attack_ms / 1000.0 * SR))
    rel = np.exp(-1.0 / (release_ms / 1000.0 * SR))
    env = np.zeros_like(mono)
    acc = 0.0
    for i in range(len(mono)):
        c = atk if mono[i] > acc else rel
        acc = c * acc + (1.0 - c) * mono[i]
        env[i] = acc
    over = np.maximum(0.0, env - thresh)
    gain = 1.0 - (over * (1.0 - 1.0 / ratio) / np.maximum(env, 1e-6))
    gain = np.clip(gain, 0.25, 1.0)
    return drums * gain[:, None]


def _mono_lows(stereo, cutoff_hz=120.0):
    """Force everything below cutoff_hz to mono (simple one-pole crossover).

    Keeps club systems and phone speakers happy: sub energy stays centered
    while the highs keep their stereo width.
    """
    alpha = 1.0 - np.exp(-2.0 * np.pi * cutoff_hz / SR)
    lows = np.empty_like(stereo)
    for ch in range(stereo.shape[1]):
        acc = 0.0
        x = stereo[:, ch]
        o = lows[:, ch]
        a = alpha
        for i in range(x.shape[0]):
            acc += a * (x[i] - acc)
            o[i] = acc
    mono_low = lows.mean(axis=1, keepdims=True)
    mono_low = np.repeat(mono_low, stereo.shape[1], axis=1)
    return (stereo - lows) + mono_low


# ---------------------------------------------------------------- main
def normalize_genre(genre):
    if not genre:
        return "HipHop"
    key = "".join(ch for ch in str(genre).lower() if ch.isalnum())
    return _ALIASES.get(key, "HipHop")


def normalize_era(era):
    """Normalize an era tag to '2000s', '2010s' or '2020s', else None.

    Accepts plain decade names, artist-era strings ('2006–2010'),
    and mix style keys ('2010s-drill').
    """
    if not era:
        return None
    s = str(era).strip().lower()
    if s in ("2000s", "2000", "00s", "2006–2010", "2006-2010",
             "2000s-southern-trap"):
        return "2000s"
    if s in ("2010s", "2010", "10s", "2011–2015", "2011-2015",
             "2010s-drill"):
        return "2010s"
    if s in ("2020s", "2020", "20s", "2016–2020", "2016-2020",
             "2021–2026", "2021-2026", "2020s-melodic"):
        return "2020s"
    return None


def generate_beat(genre, bpm, bars, seed=None, artist=None, progress_cb=None,
                  kit="classic", melody=None, custom_samples=None,
                  layers=True, healing=None, era=None, duration=None,
                  fib_bursts=None):
    """Render a synthesized beat.

    Returns stereo float32 @ 44100 Hz. Deterministic for a given seed.
    When artist is provided, its production style overrides genre defaults —
    style emulation only; every sound is synthesized from scratch.
    progress_cb(frac, msg) is called occasionally when provided.
    duration: None = classic loop mode (bars used as-is). A number of
      seconds, or a "M:SS" label from STANDARD_DURATIONS, enables song mode:
      bars are derived from the duration and the arrangement follows a
      full intro/verse/hook/bridge/outro structure (see get_song_structure).
    kit: built-in drum kit name (see list_kits()); "classic" reproduces the
      original drum sounds exactly.
    melody: lead instrument name (see MELODY_INSTRUMENTS); None = genre/artist
      default.
    custom_samples: {instrument: stereo float32 @44100} user WAV one-shots
      for kick/snare/chat/ohat/clap — replaces synthesis for those slots.
    layers: when False, skips the extra percussive layers (crash, cowbell,
      congas, shaker, ride, toms) for a pure-classic arrangement.
    healing: None/False = standard 440 Hz tuning (default, unchanged sound).
      True or a dict enables "healing mode": Fibonacci-ratio melodic
      intervals, optional 432 Hz base tuning, and a soft solfeggio-frequency
      drone bed. Dict keys: base (432.0|440.0), fib_scale, solfeggio,
      solfeggio_root (one of SOLFEGGIO_FREQS or None), binaural,
      soft_drums, preset (a HEALING_PRESETS name). See normalize_healing().
      Wellness-vibe descriptors only — no health claims.
    era: None/'2000s'/'2010s'/'2020s' — era-specific production flavor
      (swing, hat density, 808 texture, melody texture tuned per decade).
      Accepts artist-era strings and mix style keys too. Explicit era
      overrides artist-era flavor when both are given.
    fib_bursts: None/False = off (default). True, an int 1-4, or a dict
      enables Fibonacci melodic bursts: short musical phrases whose
      scale-degree walk follows the Fibonacci sequence, injected every
      8 bars (last N bars of each phrase). Always in the genre's key via
      the minor pentatonic — subtle, musical, never random. Dict keys:
      bars (1-4), intensity ("subtle"/"balanced"/"bold"),
      sequence ("ascending"/"descending"/"alternating").
    """
    genre = normalize_genre(genre)
    bpm = min(200.0, max(50.0, float(bpm)))
    step_dur = 60.0 / bpm / 4.0
    bar_dur = step_dur * 16
    # Song mode: derive bars from the requested duration and use a full
    # song structure. Loop mode keeps the legacy bars clamp exactly.
    _song_mode = duration is not None
    if _song_mode:
        _dur = duration
        if isinstance(_dur, str):
            _dur = STANDARD_DURATIONS.get(_dur.strip(), 180)
        try:
            _dur = float(_dur)
        except (TypeError, ValueError):
            _dur = 180.0
        bars = min(160, max(16, int(round(_dur / bar_dur))))
    else:
        bars = min(64, max(1, int(bars)))
    rng = np.random.default_rng(seed)
    # Separate stream for the extra layers so the core groove's random
    # sequence (and the classic kit sound) stays bit-identical.
    rng2 = np.random.default_rng((seed or 0) ^ 0x9E3779B9)
    # Dedicated stream for Fibonacci bursts: enabling bursts must not
    # alter any existing layer's output.
    rng3 = np.random.default_rng((seed or 0) ^ 0xF1B0457)
    _fib_cfg = normalize_fib_bursts(fib_bursts)
    _fib_burst_bars = _fib_cfg["bars"] if _fib_cfg else 0
    _fib_level = _FIB_BURST_LEVELS[_fib_cfg["intensity"]] if _fib_cfg else 0.0
    _fib_seq = _fib_cfg["sequence"] if _fib_cfg else "ascending"
    kitd = get_kit(kit)

    st = get_artist_style(artist)
    if st:
        pat = dict(_PATTERNS[st["base"]])
        pat["swing"] = st["swing"]
        pat["prog"] = list(st["prog"])
        pat["melody"] = st["melody"] != "none"
        hat_style = st["hat"]
        bass_style = st["bass"]
        melody_style = st["melody"]
        fill_style = st["fill"]
    else:
        pat = dict(_PATTERNS[genre])  # copy: era flavors mutate below
        hat_style = "pattern"
        bass_style = kitd["bass"]
        melody_style = pat["melody_inst"] if pat["melody"] else "none"
        fill_style = "rolls"
    if melody is not None and melody in MELODY_INSTRUMENTS:
        melody_style = melody

    # ---- era-specific production flavor (2000s/2010s/2020s) ----
    # Style emulation only — everything stays synthesized from scratch.
    era = normalize_era(era)
    if era == "2000s":
        pat["swing"] = min(0.32, pat["swing"] + 0.06)
        if genre in ("HipHop", "BoomBap"):
            pat["kick"] = sorted(set(pat["kick"]) | {11})
            if melody_style in ("pluck", "none"):
                melody_style = "darkpiano"
        bass_style = "punchy"
    elif era == "2010s":
        if genre in ("Trap", "Drill"):
            fill_style = "rolls"   # triplet hat rolls on every 4th bar
            hat_style = "16ths"
        bass_style = "glide"
        pat["clap"] = sorted(set(pat["clap"]) | set(pat["snare"]))
    elif era == "2020s":
        hat_style = "sparse"
        bass_style = "subby"
        if melody_style == "pluck":
            melody_style = "bells"

    # hat density per style
    if hat_style == "16ths":
        chat_pos = list(range(16))
    elif hat_style == "8ths":
        chat_pos = [0, 2, 4, 6, 8, 10, 12, 14]
    elif hat_style == "sparse":
        chat_pos = [0, 4, 8, 12]
    elif hat_style in ("swung",):
        chat_pos = [0, 2, 4, 6, 8, 10, 12, 14]
    elif hat_style == "rolls":
        chat_pos = list(range(16))
    else:
        chat_pos = list(pat["chat"])

    total = int(bars * bar_dur * SR)
    out = np.zeros((total, 2), dtype=np.float32)
    mel = np.zeros((total, 2), dtype=np.float32)    # melodic bus (pumped)
    drums = np.zeros((total, 2), dtype=np.float32)  # drum bus (soft-clipped)
    sb = np.zeros((total, 2), dtype=np.float32)     # 808 bus (ducked)

    # one-shots (synthesized once, reused for every hit).
    # custom_samples maps kick/snare/chat/ohat/clap -> stereo float32 @ SR
    # (user-uploaded WAVs); when present it replaces synthesis for that slot.
    cs = custom_samples or {}
    kick_s = cs["kick"] if cs.get("kick") is not None else _kick(SR, rng, kitd["kick"])
    snare_s = cs["snare"] if cs.get("snare") is not None else _snare(SR, rng, kitd["snare"])
    chat_s = cs["chat"] if cs.get("chat") is not None else _hat(SR, rng, variant=kitd["chat"])
    ohat_s = cs["ohat"] if cs.get("ohat") is not None else _ohat(SR, rng, kitd["ohat"])
    clap_s = cs["clap"] if cs.get("clap") is not None else _clap(SR, rng, kitd["clap"])
    # extra percussive layers (separate RNG stream — core groove untouched)
    crash_s = _crash(SR, rng2)
    cowbell_s = _cowbell(SR)
    conga_lo = _conga(SR, rng2, 196.0)
    conga_hi = _conga(SR, rng2, 262.0)
    shaker_s = _shaker(SR, rng2)
    ride_s = _ride(SR, rng2)
    tom_hi = _tom(SR, rng2, 165.0)
    tom_mid = _tom(SR, rng2, 130.0)
    tom_lo = _tom(SR, rng2, 98.0)
    # Haas-widened hats (stereo width; kick/808 stay mono)
    chat_haas = _haas(chat_s)
    ohat_haas = _haas(ohat_s)

    root_midi = int(rng.integers(33, 40))  # A1..G#2 area
    prog = pat["prog"]

    # healing mode: normalize options; m2f maps MIDI -> Hz at the chosen
    # base tuning. Standard mode keeps _midi_to_freq itself, so output is
    # bit-identical to before when healing is off.
    heal = normalize_healing(healing)
    soft = bool(heal and heal["soft_drums"])
    if heal:
        _hb = heal["base"]

        def m2f(m):
            return _hb * 2.0 ** ((m - 69) / 12.0)
    else:
        m2f = _midi_to_freq

    def bar_root(bar):
        return root_midi + prog[bar % len(prog)]

    # 4-bar call-and-response hook: motif A on bars 1-2, a varied motif B
    # on bars 3-4 (octave jumps + rhythmic shifts) — catchier than one
    # looping motif. Steps are 16ths within a 4-bar window (0..63).
    # In healing mode the walk is on exact Fibonacci ratios, not semitones.
    motifA, motifB = [], []
    if pat["melody"]:
        _steps = (0, 7, 12, 18, 22, 28, 34, 39, 44, 50, 55, 60)
        if heal and heal["fib_scale"]:
            idx = int(rng.integers(1, 4))
            _seq = []
            for s in _steps:
                idx = max(0, min(len(FIB_RATIOS) - 1,
                                 idx + int(rng.integers(-2, 3))))
                _seq.append((s, idx))  # idx into FIB_RATIOS
            motifA = [(s, v) for (s, v) in _seq if s < 32]
            motifB = [(s, v) for (s, v) in _seq if s >= 32]
        else:
            idx = int(rng.integers(2, 5))
            _seq = []
            for s in _steps:
                idx = max(0, min(len(_PENTA) - 1,
                                 idx + int(rng.integers(-2, 3))))
                _seq.append((s, _PENTA[idx] + 24))  # +2 octaves above bass
            motifA = [(s, v) for (s, v) in _seq if s < 32]
            # motif B: the "answer" — occasional octave jumps and nudges
            motifB = []
            for (s, v) in _seq:
                if s < 32:
                    continue
                v2 = v + (12 if rng.random() < 0.3 else 0)
                s2 = s + (2 if rng.random() < 0.25 else 0)
                motifB.append((min(s2, 63), v2))
    # counter-melody only on plucky lead instruments (tasteful echo)
    _counter_ok = melody_style in ("pluck", "bells", "koto", "marimba")

    # Fibonacci burst patterns: one 2-bar phrase per 8-bar block, drawn
    # from the dedicated rng3 stream (existing output untouched when off).
    _fib_phrases = {}
    if _fib_burst_bars:
        for _p in range((bars + 7) // 8 + 1):
            _pb = min(_p * 8, bars - 1)
            _fib_phrases[_p] = _fib_burst_notes(
                rng3, root_midi, prog[_pb % len(prog)],
                sequence=_fib_seq, phrase_idx=_p)

    # separate melodic bus: kick-driven sidechain pump applied after the
    # bar loop (skipped in soft/healing mode)
    kick_times = []

    prev_bass_freq = None
    _structure = get_song_structure(bars) if _song_mode else None
    _HOOK_SECTIONS = ("hook1", "hook2", "final")
    for bar in range(bars):
        if _song_mode:
            _section, _intensity = get_bar_section(bar, _structure)
        else:
            _section, _intensity = "loop", 1.0
        if progress_cb and bar % 4 == 0:
            if _song_mode:
                progress_cb(bar / bars, f"{_section} — Bar {bar+1}/{bars}…")
            else:
                progress_cb(bar / bars, f"Bar {bar + 1}/{bars}…")
        base = int(bar * bar_dur * SR)
        chord = bar_root(bar)
        phrase_bar = bar % 4
        is_fill_bar = (phrase_bar == 3)
        # song mode: low-intensity sections (intro/bridge/outro) stay sparse
        sparse = (_intensity < 0.5) if _song_mode else (bar < 2)

        vel_j = lambda v: v * float(rng.uniform(0.9, 1.1))
        vel2 = lambda v: v * float(rng2.uniform(0.9, 1.1))  # extra layers
        # song mode: extra percussive layers breathe with section intensity
        _ls = (0.4 + 0.6 * _intensity) if _song_mode else 1.0
        _lv = (lambda v, _s=_ls: vel2(v) * _s) if _song_mode else vel2
        _is_bridge = _song_mode and _section == "bridge"

        # --- drums -> drums bus (micro-timing, velocity-coupled filtering) ---
        # kick/808 call-and-response: on fill bars the kick thins out, so
        # the 808 gets busier to fill the space (see 808 section below).
        _ksteps = [s for s in pat["kick"]
                   if not (is_fill_bar and s >= 10)]
        for s in _ksteps:
            _kp = _jit(base + int(s * step_dur * SR), step_dur, rng)
            _kv = vel_j(1.0) * (0.55 if soft else 1.0)
            _place(drums, _darken(kick_s * _kv, _kv), _kp)
            if not soft:
                kick_times.append(_kp)
        for s in pat["snare"]:
            _sp = _jit(base + int(s * step_dur * SR), step_dur, rng)
            _sv = vel_j(0.9) * (0.55 if soft else 1.0)
            # layered crack: rimshot transient 7ms before backbeats
            if not soft and s in (4, 12):
                _place(drums, _rimshot(SR, rng2) * _sv * 0.6,
                       max(0, _sp - int(0.007 * SR)))
            _place(drums, _darken(snare_s * _sv, _sv), _sp)
        for s in chat_pos:
            pos = s * step_dur
            if s % 2 == 1:  # swung off-16ths push late (16th-note swing)
                pos += pat["swing"] * step_dur * 0.6
            if _is_bridge and s % 2:
                continue  # bridge breakdown: 8ths only, half density
            if sparse and s % 4:
                continue
            if soft and s % 4:  # healing: quarters only
                continue
            _hp = _jit(base + int(pos * SR), step_dur, rng)
            _hv = vel_j(0.5) * (0.6 if soft else 1.0)
            _place(drums, _darken(chat_haas * _hv, _hv), _hp)
        # --- fill-bar arrangement mask: hat + 808 rolls with decay ---
        if is_fill_bar and not sparse and not soft:
            for k in range(8):  # 32nd-note hat roll: pitch decays as it
                # accelerates (classic trap), velocity decays too
                _rp = _jit(base + int((14 + k * 0.25) * step_dur * SR),
                           step_dur, rng2)
                _rv = 0.38 * (1.0 - k * 0.09)
                _rh = _haas(_pitch_shift(chat_s, 1.0 - k * 0.035))
                _place(drums, _darken(_rh * _rv, _rv), _rp)
            _rf = m2f(chord)  # 808 triplet roll, decaying
            for k, _rs in enumerate((14, 14.5, 15)):
                _rn = _bass_note(SR, _rf, None, bass_style)
                _place(sb, _rn * (0.7 - k * 0.15),
                       base + int(_rs * step_dur * SR))
        # riser: loop mode hits every 8th bar; song mode builds into hooks
        if layers and not soft:
            _do_riser = False
            if _song_mode:
                _next_sec = get_bar_section(bar + 1, _structure)[0] \
                    if bar + 1 < bars else ""
                # last bar before a hook (or final) gets the build — even
                # out of a sparse section, since it's transitional
                if _next_sec in _HOOK_SECTIONS and \
                        _section not in _HOOK_SECTIONS:
                    _do_riser = True
            elif not sparse and bar % 8 == 7:
                _do_riser = True
            if _do_riser:
                _place(drums, _riser(SR, rng2, bar_dur), base)
        if not sparse and not soft:
            for s in pat["ohat"]:
                _op = _jit(base + int(s * step_dur * SR), step_dur, rng)
                _ov = vel_j(0.55)
                _place(drums, _darken(ohat_haas * _ov, _ov), _op)
            for s in pat["clap"]:
                _cp = _jit(base + int(s * step_dur * SR), step_dur, rng)
                _cv = vel_j(0.7)
                _place(drums, _darken(clap_s * _cv, _cv), _cp)
        # --- extra percussive layers (tasteful accents; skip in intro) ---
        if layers and not sparse and not soft:
            if pat.get("crash") and phrase_bar == 0:
                _place(drums, crash_s * 0.5 * _ls, base)
            for s in pat.get("cowbell", []):
                _place(drums, cowbell_s * _lv(0.4),
                       _jit(base + int(s * step_dur * SR), step_dur, rng2))
            for i, s in enumerate(pat.get("conga", [])):
                _place(drums, (conga_lo if i % 2 == 0 else conga_hi)
                       * _lv(0.5),
                       _jit(base + int(s * step_dur * SR), step_dur, rng2))
            if pat.get("shaker"):
                for s in range(0, 16, 2):
                    _place(drums, shaker_s * _lv(0.3),
                           _jit(base + int(s * step_dur * SR),
                                step_dur, rng2))
            for s in pat.get("ride", []):
                _place(drums, ride_s * _lv(0.35),
                       _jit(base + int(s * step_dur * SR), step_dur, rng2))
            if pat.get("toms") and is_fill_bar and fill_style != "none":
                for i, s in enumerate((12, 13, 14, 15)):
                    _place(drums, (tom_hi, tom_mid, tom_lo, tom_lo)[i]
                           * (0.4 + 0.1 * i) * _ls,
                           _jit(base + int(s * step_dur * SR),
                                step_dur, rng2))
        if is_fill_bar and fill_style != "none" and not soft:  # snare roll into next phrase
            steps = (14, 15) if fill_style == "minimal" else (12, 13, 14, 15)
            for i, s in enumerate(steps):
                _place(drums, snare_s * (0.5 + 0.15 * i),
                       _jit(base + int(s * step_dur * SR), step_dur, rng))

        # --- ghost hits on odd phrase bars: seeded, subtle, human feel ---
        if layers and not sparse and not soft and phrase_bar in (1, 3) \
                and genre in ("Drill", "Trap", "HipHop", "BoomBap"):
            if rng.random() < 0.7:
                gs = 3 if rng.random() < 0.5 else 11
                _gv = vel_j(0.45)
                _place(drums, _darken(kick_s * _gv, _gv),
                       _jit(base + int(gs * step_dur * SR), step_dur, rng))
            if rng.random() < 0.5:
                gs = 7 if rng.random() < 0.5 else 15
                _gv = vel_j(0.35)
                _place(drums, _darken(snare_s * _gv, _gv),
                       _jit(base + int(gs * step_dur * SR), step_dur, rng))

        # --- 808 bass follows the chord root (style-textured) -> sb bus ---
        # call-and-response: on fill bars the kick thins, so the 808 gets
        # busier; on normal bars the 808 stays off the kick's steps (except
        # the downbeat anchor) so they trade off instead of stacking.
        _bstep_set = set(pat["bass"])
        if is_fill_bar and not soft:
            _bstep_set |= ({2, 7, 11, 14} - set(_ksteps))
        _bsteps = sorted(_bstep_set)
        if not is_fill_bar:
            _bsteps = [s for s in _bsteps if s not in _ksteps or s == 0]
        for s in _bsteps:
            semis = chord + (7 if s in pat["bass_fifth"] else 0)
            freq = m2f(semis)
            # length contrast: downbeat 808s sustain, off-beats staccato
            # on even bars (groove comes from length, not just pitch)
            _stacc = (s % 4 != 0) and (bar % 2 == 0) and not soft
            note = _bass_note(SR, freq, prev_bass_freq, bass_style,
                              staccato=_stacc)
            prev_bass_freq = freq
            _place(sb, note * vel_j(0.95),
                   _jit(base + int(s * step_dur * SR), step_dur, rng))

        # --- melodic layer (style-textured) -> melodic bus (kick pump) ---
        # song mode: lead motifs live on hooks (intensity >= 0.9); verses
        # get pads. Pad-style beats keep their pads on hooks too (no lead
        # exists to take over, so silence would leave hooks empty).
        _has_lead = bool(motifA or motifB) and \
            melody_style not in _MEL_PAD_INST and melody_style != "none"
        _pad_ok = not sparse and (
            not _song_mode or _intensity < 0.9 or not _has_lead)
        _lead_ok = not sparse and (
            not _song_mode or _intensity >= 0.9)
        if melody_style in _MEL_PAD_INST and _pad_ok:
            if heal and heal["fib_scale"]:
                # Fibonacci pad: root x 1.0, 1.25, 1.5 (pure ratios)
                _rf = m2f(chord)
                freqs = [_rf * r for r in (1.0, 1.25, 1.5)]
            else:
                # sustained chord pad per bar: root + minor 3rd + 5th
                freqs = [m2f(chord + iv) for iv in (0, 3, 7)]
            _place(mel, _MEL_PAD_INST[melody_style](
                SR, freqs, dur=bar_dur * 0.95) * 0.55, base)
        elif (motifA or motifB) and _lead_ok and melody_style != "none":
            mel_fn = _MEL_INST.get(melody_style, _pluck)
            # final-hook lift: lead sits a touch hotter on the biggest hook
            _lead_boost = 1.15 if (_song_mode and _intensity > 1.0) else 1.0
            mel_step = 2 if melody_style == "bells" else 1  # bells: sparser
            w4 = bar % 4
            _mot = motifA if w4 < 2 else motifB  # call on 1-2, answer on 3-4
            for i, (s, v) in enumerate(_mot):
                if i % mel_step:
                    continue
                if s // 16 != w4:
                    continue
                if heal and heal["fib_scale"]:
                    # exact Fibonacci ratio off the root, +2 octaves
                    f = m2f(root_midi) * FIB_RATIOS[v] * 4.0
                else:
                    f = m2f(root_midi + v)
                _mp = base + int((s % 16) * step_dur * SR)
                _mn = mel_fn(SR, f) * 0.8 * _lead_boost
                if melody_style == "pluck":  # Haas width on pluck leads
                    _mn = _haas(_mn)
                _place(mel, _mn, _mp)
                # counter-melody: sparse echo an octave up, half level
                if _counter_ok and layers and not soft and i % 2 == 0:
                    _place(mel, mel_fn(SR, f * 2.0) * 0.4,
                           _mp + int(8 * step_dur * SR))

        # --- Fibonacci melodic bursts (opt-in) ---
        # Last N bars of each 8-bar phrase get a short Fibonacci-walk
        # phrase: pentatonic-mapped so it stays in key, at a subtle
        # level under the main lead. Silent when the lead is (sparse
        # sections, pad-only textures) to keep it tasteful.
        if _fib_burst_bars and _lead_ok and not sparse:
            _ph = bar // 8
            _slot = (bar % 8) - (8 - _fib_burst_bars)
            if 0 <= _slot and _ph in _fib_phrases:
                _fib_notes = _fib_phrases[_ph]
                _fib_inst = melody_style
                if _fib_inst in _MEL_PAD_INST or _fib_inst == "none":
                    _fib_inst = "pluck"  # bursts need a plucky lead
                _fib_fn = _MEL_INST.get(_fib_inst, _pluck)
                for (_s, _sm) in _fib_notes:
                    if (_s // 16) % 2 != _slot % 2:
                        continue  # this note belongs to another burst bar
                    _fmp = base + int((_s % 16) * step_dur * SR)
                    _fmn = _fib_fn(SR, m2f(_sm)) * _fib_level
                    if _fib_inst == "pluck":
                        _fmn = _haas(_fmn)
                    _place(mel, _fmn, _fmp)

    # --- Gemini redesign: bus processing ---
    # Muse extra: feedforward glue compressor on the drum bus first
    drums = _bus_glue(drums)
    # soft clip the drum bus for warmth and loudness
    drums = np.tanh(1.6 * drums) / np.tanh(1.6)
    # 808 sidechain: kick-triggered ducking, deeper than the melodic pump
    if kick_times:
        _rel = int(0.12 * SR)
        _dec = np.exp(-np.arange(_rel, dtype=np.float32) / (_rel / 2.5))
        _senv = np.ones(total, dtype=np.float32)
        for _kt in kick_times:
            _e = min(_rel, total - _kt)
            if _e > 0:
                _senv[_kt:_kt + _e] *= (1.0 - 0.55 * _dec[:_e])
        sb *= _senv[:, None]
    sb = np.tanh(2.0 * sb) / np.tanh(2.0) * 0.95  # 808 warmth
    out = drums + sb

    # kick sidechain pump on the melodic bus: gentle ducking so the drums
    # hit harder and the mix breathes (skipped in soft/healing mode)
    if kick_times and not soft:
        _rel = int(0.15 * SR)
        _dec = np.exp(-np.arange(_rel, dtype=np.float32) / (_rel / 3.0))
        _env = np.ones(total, dtype=np.float32)
        for _kt in kick_times:
            _e = min(_rel, total - _kt)
            if _e > 0:
                _env[_kt:_kt + _e] *= (1.0 - 0.35 * _dec[:_e])
        mel *= _env[:, None]
    out += mel

    # healing: solfeggio drone bed under the whole beat (before the glue)
    if heal and heal["solfeggio"]:
        _healing_drone_into(out, SR, bar_dur, bars, heal)

    # low-end mono: sub-120Hz stays centered for club/phone playback
    out = _mono_lows(out)

    # gentle glue: soft clip + normalize (keeps transients, no pumping)
    peak = float(np.max(np.abs(out)))
    if peak > 0:
        out = np.tanh(out / peak * 1.2) * 0.89
    # song mode: linear fade over the last 4 bars (1.0 -> 0.1) so the
    # outro lands instead of stopping cold
    if _song_mode and bars >= 4:
        _fs = max(0, total - int(4 * bar_dur * SR))
        _fl = total - _fs
        if _fl > 0:
            _fade = 1.0 - np.arange(_fl, dtype=np.float32) / _fl * 0.9
            out[_fs:] *= _fade[:, None]
    if progress_cb:
        progress_cb(1.0, "Done")
    return out.astype(np.float32)


if __name__ == "__main__":
    import time
    t0 = time.time()
    b = generate_beat("Drill", 140, 16, seed=7)
    dt = time.time() - t0
    print(f"loop: shape={b.shape} dtype={b.dtype} "
          f"dur={b.shape[0] / SR:.1f}s time={dt:.1f}s "
          f"peak={np.max(np.abs(b)):.3f}")
    # song mode demo: full 3:00 structured instrumental
    t0 = time.time()
    s = generate_beat("Drill", 140, 16, seed=7, duration="3:00")
    dt = time.time() - t0
    print(f"song: shape={s.shape} dur={s.shape[0] / SR:.1f}s time={dt:.1f}s "
          f"peak={np.max(np.abs(s)):.3f}")
    print("structure:",
          [(n, sb, nb) for n, sb, nb, _ in get_song_structure(105)])
