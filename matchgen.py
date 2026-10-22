"""Match engine: beats <-> lyrics that fit each other (2026-10-22).

Daryl's order: generate beats from generated lyrics and lyrics from
generated beats, matched on tempo, energy and melody "more or less" —
derived parameters only, nothing copied from any original work.

A song-DNA profile is extracted from either side:

  lyrics -> {bpm, energy, melody_inst, genre, bars}
    * tempo: the BPM at which the verses' syllable density sits in
      the comfortable flow zone (the inverse of the lyrics engine's
      own tempo-fit rule: ~12 syllables/bar at 90 BPM).
    * energy: syllable density + stress load, normalised 0..1.
    * melody/genre: from the song's theme via a fixed character map
      (dark themes -> minor-feel instruments, bright -> bells/pluck).

  beat -> {bpm, energy, cadence_set, rhyme_scheme, theme, syl_target}
    * tempo: the beat's own BPM, handed to the lyrics engine's
      tempo fit (cadence + syllable ceiling scale to it).
    * energy: genre character + BPM, drives cadence and scheme.
    * theme: from the beat's melody instrument character.

Everything is deterministic for a given input — same lyrics always
ask for the same beat shape, same beat always asks for the same
writing shape.
"""
import re

import djrill_lyrics as L

# ---------------------------------------------------------------------------
# character maps (style parameters only — no copied material)
# ---------------------------------------------------------------------------

# genre -> base energy 0..1 (production character, not any song)
GENRE_ENERGY = {
    "Drill": 0.9, "Trap": 0.85, "Dubstep": 0.95, "DnB": 0.95,
    "HeavyMetal": 0.95, "Punk": 0.9, "Techno": 0.85, "House": 0.8,
    "Breakbeat": 0.85, "Afrobeats": 0.75, "HipHop": 0.7,
    "RockNRoll": 0.8, "BoomBap": 0.6, "Jazz": 0.45, "Blues": 0.4,
    "RnB": 0.45, "Soul": 0.5, "Funk": 0.7, "Country": 0.5,
    "Folk": 0.35, "Gospel": 0.65, "Reggae": 0.5, "Dancehall": 0.8,
    "Grime": 0.9, "EDM": 0.9, "Pop": 0.65, "LoFi": 0.3,
}

# theme -> (genre, melody instrument): the writing's character picks
# the production's character.
THEME_PRODUCTION = {
    "street": ("HipHop", "darkpiano"),
    "hustle": ("Trap", "pluck"),
    "pain": ("HipHop", "strings"),
    "introspective": ("BoomBap", "grandpiano"),
    "love": ("RnB", "epiano"),
    "faith": ("Gospel", "organ"),
    "gospel": ("Gospel", "organ"),
    "victory": ("HipHop", "brass"),
    "party": ("Afrobeats", "bells"),
    "rock": ("RockNRoll", "guitar"),
    "country": ("Country", "guitar"),
    "metal": ("HeavyMetal", "synthlead"),
    "punk": ("Punk", "guitar"),
    "emo": ("RockNRoll", "violin"),
}

# melody instrument -> theme: the beat's voice picks the writing's world
MELODY_THEME = {
    "darkpiano": "street", "strings": "pain", "cello": "pain",
    "violin": "emo", "grandpiano": "introspective", "epiano": "love",
    "organ": "gospel", "brass": "victory", "trumpet": "victory",
    "bells": "party", "pluck": "hustle", "kalimba": "party",
    "synthlead": "party", "guitar": "rock", "harp": "introspective",
    "musicbox": "introspective", "vibraphone": "love",
    "flute": "faith", "marimba": "party", "koto": "introspective",
    "sitar": "introspective", "steelpan": "party",
}


def _clean(line):
    return line and not line.startswith("(")


def profile_from_lyrics(sections, theme="street"):
    """Song-DNA from generated lyrics sections."""
    verses = []
    for k in ("verse1", "verse2", "verse3"):
        verses += [l for l in sections.get(k, []) if _clean(l)]
    hook = [l for l in sections.get("hook", []) if _clean(l)]
    all_lines = verses + hook
    if not all_lines:
        return {"bpm": 90, "energy": 0.6, "melody_inst": "darkpiano",
                "genre": "HipHop", "bars": 32, "mean_syl": 12.0}
    syl = [L.count_syllables(l) for l in all_lines]
    mean_syl = sum(syl) / len(syl)
    # tempo: BPM at which this density is a comfortable flow
    bpm = int(round(90.0 * mean_syl / 12.0))
    bpm = max(60, min(160, bpm))
    # energy: density above/below the 12-syl centre + stress load
    stress = sum(L._stress_count(l) for l in all_lines) / len(all_lines)
    energy = 0.5 + (mean_syl - 12.0) * 0.06 + (stress - 3.0) * 0.08
    energy = round(max(0.1, min(1.0, energy)), 2)
    genre, inst = THEME_PRODUCTION.get(theme, ("HipHop", "darkpiano"))
    # one lyric line rides roughly one bar; hooks repeat, count once
    bars = len(verses) + len(set(hook))
    bars = max(16, min(160, bars))
    return {"bpm": bpm, "energy": energy, "melody_inst": inst,
            "genre": genre, "bars": bars, "mean_syl": round(mean_syl, 1)}


def profile_from_beat(genre="HipHop", bpm=90, melody_inst=None):
    """Song-DNA from beat parameters."""
    try:
        bpm = float(bpm)
    except (TypeError, ValueError):
        bpm = 90.0
    base = GENRE_ENERGY.get(genre, 0.65)
    energy = base * 0.75 + max(0.0, min(1.0, (bpm - 60) / 140.0)) * 0.25
    energy = round(max(0.1, min(1.0, energy)), 2)
    if genre in ("Trap", "Drill", "Grime") and energy >= 0.5:
        cadence = "triplet"  # the genre's signature subdivision wins
    elif energy >= 0.78:
        cadence = "rapid"
    elif energy <= 0.38:
        cadence = "sparse"
    else:
        cadence = "steady"
    scheme = "AAAA" if energy >= 0.75 else ("ABAB" if energy <= 0.42
                                            else "AABB")
    theme = MELODY_THEME.get(melody_inst or "", "street")
    return {"bpm": int(bpm), "energy": energy, "cadence_set": cadence,
            "rhyme_scheme": scheme, "theme": theme,
            "syl_target": max(7, min(18, int(round(12.0 * 90.0 / bpm))))}


def beat_spec_from_lyrics(sections, theme="street", seed=None):
    """_start_beat_job data for a beat that fits these lyrics."""
    p = profile_from_lyrics(sections, theme)
    secs = p["bars"] * 240.0 / p["bpm"]  # bars * beats/bar * sec/beat
    length = None
    for label, s in (("2:30", 150), ("3:00", 180), ("3:30", 210)):
        if abs(secs - s) <= 25:
            length = label
            break
    spec = {"genre": p["genre"], "bpm": p["bpm"],
            "melody": p["melody_inst"], "seed": seed}
    if length:
        spec["length"] = length
    else:
        spec["bars"] = p["bars"]
    return spec, p


def lyrics_spec_from_beat(genre="HipHop", bpm=90, melody_inst=None,
                          seed=None, artist=None):
    """_gen_lyrics data for lyrics that fit this beat."""
    p = profile_from_beat(genre, bpm, melody_inst)
    spec = {"genre": genre, "theme": p["theme"], "bpm": p["bpm"],
            "rhyme_scheme": p["rhyme_scheme"],
            "syl_target": p["syl_target"],
            "cadence_set": p["cadence_set"],
            "internal_rhyme": p["energy"] >= 0.6,
            "multi_boost": p["energy"] >= 0.6}
    if seed is not None:
        spec["seed"] = seed
    if artist:
        spec["artist"] = artist
    return spec, p


def sections_to_text(sections):
    """Flatten song sections to prompter text (one line per bar)."""
    order = ("verse1", "hook", "verse2", "hook", "verse3", "bridge",
             "outro")
    out = []
    for k in order:
        out += [l for l in sections.get(k, [])]
    return "\n".join(out)
