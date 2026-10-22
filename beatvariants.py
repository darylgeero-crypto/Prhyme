"""beatvariants — per-genre variant families for lightbeat.

Why this exists (Daryl, 2026-10-21): generated beats came out "the same
beat over and over, just a little bit different each time" because every
genre had exactly ONE fixed pattern in lightbeat._PATTERNS — the seed only
moved the root note, timbre and humanization.

This module gives every canonical genre (all 37 in the app dropdowns) a
family of musical archetypes inspired by the production fingerprints of
current chart hits and all-time classics of that genre — BPM-agnostic
drum programming, chord movement, bass rhythm, swing and lead choice.
Style fingerprints only: no melody, lyric or pattern is copied from any
specific song.

How it plugs in: lightbeat.generate_beat() calls apply_variant() with a
DEDICATED rng stream (seed ^ 0xB17A5EED) so every existing rng stream —
and therefore the classic sound of archetype 0 — stays untouched.
Archetype 0 of each family IS the genre's classic pattern, so a variant
roll can always land on the proven groove.

Anti-repeat: the app rolls a fresh seed for every generation
(new_beat_seed in app.py), and the variant combo is a pure function of
that seed, so back-to-back generations land on different grooves while
the same seed always reproduces the same beat — which the preview →
full-render flow and the app's render cache both rely on.
"""

# ---------------------------------------------------------------- families
# Each family: base = key into lightbeat._PATTERNS used for one-shots and
# any key a variant does not override. names/kicks/progs/swings are
# per-archetype (index-aligned). basses/chats are independent lists the
# roll combines with the archetype, multiplying the distinct grooves.
# snares/mel are optional per-archetype overrides (None = keep base).

def _f(base, names, kicks, progs, swings, basses, chats=None, snares=None,
       mel=None, bass_fifth=None):
    return dict(base=base, names=names, kicks=kicks, progs=progs,
                swings=swings, basses=basses, chats=chats, snares=snares,
                mel=mel, bass_fifth=bass_fifth)


_ALL16 = list(range(16))
_8THS = [0, 2, 4, 6, 8, 10, 12, 14]
_SPARSE = [0, 4, 8, 12]

FAMILIES = {
    "Trap": _f(
        "Trap",
        ["Classic Atlanta", "Dark Piano Trap", "Melodic Guitar Trap",
         "Hard Bounce Trap"],
        [[0, 6, 10], [0, 10], [0, 7, 10], [0, 3, 10]],
        [[0, 3, 10, 8], [0, 10, 8, 3], [0, 7, 10, 5], [0, 8, 3, 10]],
        [0.0, 0.0, 0.04, 0.02],
        [[0, 7, 10], [0, 10, 12], [0, 6, 10], [0, 3, 7, 10]],
        chats=[_ALL16, _ALL16, _8THS, _ALL16],
        mel=["pluck", "darkpiano", "guitar", "bells"]),
    "Drill": _f(
        "Drill",
        ["Classic UK Drill", "NY Drill Bounce", "Dark Slide Drill",
         "Orchestral Drill"],
        [[0, 7, 10], [0, 6, 10], [0, 10, 14], [0, 7, 11]],
        [[0, 8, 3, 10], [0, 3, 8, 10], [0, 10, 3, 8], [0, 5, 8, 3]],
        [0.0, 0.03, 0.0, 0.0],
        [[0, 6, 10, 12], [0, 7, 10], [0, 10, 13], [0, 6, 11]],
        chats=[_8THS, _ALL16, _8THS, _8THS],
        mel=["pluck", "pluck", "bells", "darkpiano"]),
    "HipHop": _f(
        "HipHop",
        ["Classic Boom Bap Soul", "West Coast Bounce", "Southern Soul Hop",
         "Jazzy Underground"],
        [[0, 7, 10], [0, 10], [0, 6, 10], [0, 10, 11]],
        [[0, 8, 10, 7], [0, 5, 7, 10], [0, 7, 5, 10], [0, 9, 5, 7]],
        [0.22, 0.16, 0.24, 0.28],
        [[0, 10], [0, 7, 10], [0, 10, 12], [0, 7, 12]],
        chats=[_8THS, _8THS, _8THS, _SPARSE],
        mel=["pluck", "pluck", "piano", "piano"]),
    "BoomBap": _f(
        "BoomBap",
        ["Golden Era Dust", "Chopped Soul Bap", "Hard Knock Bap",
         "Lo Swing Bap"],
        [[0, 10], [0, 7, 10], [0, 10, 14], [0, 11]],
        [[0, 5, 8, 10], [0, 7, 10, 5], [0, 10, 8, 3], [0, 5, 7, 12]],
        [0.30, 0.26, 0.22, 0.34],
        [[0, 12], [0, 10], [0, 7, 12], [0, 12, 14]],
        chats=[_8THS, _8THS, _8THS, _SPARSE],
        mel=["pluck", "piano", "pluck", "piano"]),
    "RnB": _f(
        "HipHop",
        ["Silky Slow Jam", "Neo-Soul Groove", "Modern Alt RnB",
         "90s Swing RnB"],
        [[0, 10], [0, 7, 11], [0, 10, 14], [0, 6, 10]],
        [[0, 7, 10, 5], [0, 9, 5, 7], [0, 3, 8, 10], [0, 10, 7, 5]],
        [0.26, 0.30, 0.10, 0.32],
        [[0, 10], [0, 7, 12], [0, 10], [0, 6, 12]],
        chats=[_SPARSE, _8THS, _SPARSE, _8THS],
        snares=[[4, 12], [4, 12], [12], [4, 12]],
        mel=["piano", "piano", "bells", "pluck"]),
    "LoFi": _f(
        "BoomBap",
        ["Tape Dust LoFi", "Jazz Cafe LoFi", "Rainy Night LoFi",
         "Vinyl Crackle Bap"],
        [[0, 10], [0, 11], [0, 7, 10], [0, 10]],
        [[0, 7, 10, 5], [2, 7, 0, 9], [0, 9, 5, 10], [0, 5, 10, 7]],
        [0.36, 0.38, 0.34, 0.40],
        [[0, 12], [0, 7, 12], [0, 10], [0, 12]],
        chats=[_SPARSE, _8THS, _SPARSE, _8THS],
        mel=["piano", "piano", "piano", "pluck"]),
    "Soul": _f(
        "HipHop",
        ["Motown Heart", "Chopped Soul Sample", "Modern Soul Revival",
         "Gospel Soul Lift"],
        [[0, 7, 10], [0, 10], [0, 6, 10], [0, 10, 12]],
        [[0, 7, 10, 5], [0, 10, 5, 7], [0, 5, 9, 7], [0, 5, 7, 10]],
        [0.24, 0.28, 0.18, 0.22],
        [[0, 10], [0, 12], [0, 7, 10], [0, 4, 10]],
        chats=[_8THS, _8THS, _8THS, _8THS],
        mel=["piano", "pluck", "piano", "piano"]),
    "Dancehall": _f(
        "Afrobeats",
        ["Classic Dancehall", "Modern Bashment", "Tropical Whine",
         "Ragga Bounce"],
        [[0, 6, 8], [0, 8], [0, 6, 10], [0, 3, 8]],
        [[0, 5, 3, 7], [0, 10, 5, 3], [0, 7, 10, 5], [0, 8, 3, 10]],
        [0.06, 0.04, 0.08, 0.05],
        [[0, 8], [0, 6, 8], [0, 3, 8], [0, 8, 11]],
        chats=[_8THS, _ALL16, _8THS, _ALL16],
        snares=[[4, 12], [4, 12], [4, 12], [4, 12]],
        mel=["pluck", "bells", "pluck", "pluck"]),
    "Afrobeats": _f(
        "Afrobeats",
        ["Lagos Classic", "Alte Cruise", "Amapiano Touch",
         "Festival Afro"],
        [[0, 6, 10], [0, 10], [0, 8], [0, 6, 10, 12]],
        [[0, 5, 3, 7], [0, 7, 10, 5], [0, 3, 10, 8], [0, 10, 7, 5]],
        [0.12, 0.14, 0.10, 0.12],
        [[0, 3, 6, 10, 12], [0, 6, 10], [0, 4, 8, 12], [0, 3, 10]],
        chats=[_ALL16, _8THS, _8THS, _ALL16],
        mel=["pluck", "pluck", "piano", "bells"]),
    "Afroswing": _f(
        "Afrobeats",
        ["UK Afroswing", "Smooth Swing Bounce", "Summer Swing",
         "Club Swing"],
        [[0, 6, 10], [0, 10], [0, 8, 11], [0, 6, 8]],
        [[0, 5, 3, 7], [0, 7, 5, 10], [0, 10, 8, 3], [0, 3, 8, 10]],
        [0.14, 0.16, 0.12, 0.13],
        [[0, 3, 6, 10], [0, 10], [0, 6, 12], [0, 3, 10, 12]],
        chats=[_ALL16, _8THS, _ALL16, _ALL16],
        mel=["pluck", "piano", "bells", "pluck"]),
    "BaileFunk": _f(
        "Afrobeats",
        ["Tamborzao Classic", "Funk Bounce 150", "Bruxaria Dark Funk",
         "Carioca Party"],
        [[0, 6, 10], [0, 8, 10], [0, 3, 10], [0, 6, 8, 12]],
        [[0, 5, 3, 7], [0, 10, 3, 8], [0, 8, 10, 3], [0, 7, 5, 10]],
        [0.02, 0.0, 0.0, 0.04],
        [[0, 8], [0, 6, 10], [0, 10], [0, 3, 8]],
        chats=[_8THS, _ALL16, _8THS, _ALL16],
        snares=[[4, 12], [4, 12], [8], [4, 12]],
        mel=["pluck", "pluck", "bells", "pluck"]),
    "Reggaeton": _f(
        "Reggaeton",
        ["Classic Dembow", "Perreo Hard", "Melodic Reggaeton",
         "Old School Playero"],
        [[0, 6, 8], [0, 8], [0, 6, 8], [0, 3, 8]],
        [[0, 5, 3, 7], [0, 10, 8, 3], [0, 7, 10, 5], [0, 3, 5, 10]],
        [0.0, 0.0, 0.02, 0.04],
        [[0, 8], [0, 8, 11], [0, 6, 8], [0, 8]],
        chats=[_8THS, _ALL16, _8THS, _8THS],
        mel=["pluck", "pluck", "bells", "pluck"]),
    "Phonk": _f(
        "Phonk",
        ["Memphis Classic Phonk", "Drift Phonk", "Dark Cowbell Phonk",
         "Brazilian Phonk Wave"],
        [[0, 7, 10], [0, 10], [0, 6, 10], [0, 3, 10]],
        [[0, 3, 10, 8], [0, 10, 8, 3], [0, 8, 3, 10], [0, 5, 10, 8]],
        [0.0, 0.02, 0.0, 0.03],
        [[0, 6, 10], [0, 10, 12], [0, 7, 10], [0, 3, 10]],
        chats=[_ALL16, _ALL16, _8THS, _ALL16],
        mel=["bells", "bells", "bells", "pluck"]),
    "MemphisRap": _f(
        "Phonk",
        ["90s Memphis Tape", "Underground Memphis", "Horrorcore Memphis",
         "Modern Memphis Revival"],
        [[0, 7, 10], [0, 10, 14], [0, 6, 11], [0, 3, 10]],
        [[0, 3, 10, 8], [0, 8, 10, 3], [0, 10, 3, 8], [0, 5, 8, 3]],
        [0.05, 0.06, 0.0, 0.04],
        [[0, 6, 10], [0, 10], [0, 7, 12], [0, 3, 10]],
        chats=[_ALL16, _8THS, _ALL16, _ALL16],
        mel=["bells", "darkpiano", "bells", "pluck"]),
}

FAMILIES.update({
    "House": _f(
        "House",
        ["Four Floor Classic", "Deep Soulful House", "Tech House Bounce",
         "Festival House"],
        [[0, 4, 8, 12], [0, 4, 8, 12], [0, 4, 8, 12], [0, 4, 8, 12]],
        [[0, 5, 3, 10], [0, 7, 10, 5], [0, 3, 10, 8], [0, 10, 7, 5]],
        [0.0, 0.08, 0.0, 0.0],
        [[2, 6, 10, 14], [0, 7, 10], [2, 10], [0, 6, 10, 14]],
        chats=[_ALL16, _8THS, _ALL16, _ALL16],
        mel=["none", "piano", "none", "pluck"]),
    "Techno": _f(
        "Techno",
        ["Warehouse Classic", "Minimal Pulse", "Peak Time Driving",
         "Hypnotic Raw"],
        [[0, 4, 8, 12], [0, 4, 8, 12], [0, 4, 8, 12], [0, 4, 8, 12]],
        [[0, 0, 3, 10], [0, 10, 0, 8], [0, 3, 10, 8], [0, 8, 0, 10]],
        [0.0, 0.0, 0.0, 0.0],
        [[0, 2, 4, 6, 8, 10, 12, 14], [0, 4, 8, 12],
         [0, 2, 6, 10, 14], [0, 8]],
        chats=[_ALL16, _8THS, _ALL16, _8THS],
        mel=["none", "none", "none", "bells"]),
    "DetroitTechno": _f(
        "Techno",
        ["Detroit Classic", "Soulful Motor City", "Hi-Tech Funk",
         "Deep Detroit Night"],
        [[0, 4, 8, 12], [0, 4, 8, 12], [0, 4, 8, 12], [0, 4, 8, 12]],
        [[0, 7, 10, 5], [0, 9, 5, 7], [0, 3, 10, 7], [0, 10, 5, 3]],
        [0.06, 0.10, 0.05, 0.08],
        [[0, 4, 8, 12], [0, 7, 14], [0, 2, 6, 10], [0, 10]],
        chats=[_ALL16, _8THS, _ALL16, _8THS],
        mel=["piano", "piano", "pluck", "bells"]),
    "Trance": _f(
        "Techno",
        ["Uplifting Classic", "Progressive Journey", "Psy Pulse",
         "Festival Trance"],
        [[0, 4, 8, 12], [0, 4, 8, 12], [0, 4, 8, 12], [0, 4, 8, 12]],
        [[0, 3, 10, 8], [0, 5, 10, 7], [0, 8, 3, 10], [0, 10, 5, 7]],
        [0.0, 0.0, 0.0, 0.0],
        [[2, 6, 10, 14], [0, 4, 10], [0, 2, 4, 6, 8, 10, 12, 14],
         [2, 6, 10, 14]],
        chats=[_ALL16, _8THS, _ALL16, _ALL16],
        mel=["pluck", "bells", "pluck", "bells"]),
    "Hardstyle": _f(
        "Techno",
        ["Euphoric Hardstyle", "Rawstyle Kick", "Classic Reverse Bass",
         "Festival Hard Dance"],
        [[0, 4, 8, 12], [0, 4, 8, 12], [0, 4, 8, 12], [0, 4, 8, 12]],
        [[0, 3, 10, 8], [0, 10, 8, 3], [0, 5, 3, 10], [0, 7, 10, 5]],
        [0.0, 0.0, 0.0, 0.0],
        [[2, 6, 10, 14], [0, 8], [0, 2, 6, 10, 14], [2, 6, 10, 14]],
        chats=[_ALL16, _8THS, _ALL16, _ALL16],
        mel=["pluck", "bells", "pluck", "bells"]),
    "EDM": _f(
        "House",
        ["Big Room Festival", "Progressive EDM", "Electro Bounce",
         "Mainstage Melodic"],
        [[0, 4, 8, 12], [0, 4, 8, 12], [0, 4, 8, 12], [0, 4, 8, 12]],
        [[0, 3, 10, 8], [0, 5, 7, 10], [0, 10, 3, 8], [0, 7, 10, 5]],
        [0.0, 0.0, 0.0, 0.0],
        [[0, 4, 8, 12], [2, 6, 10, 14], [0, 6, 10], [0, 4, 10]],
        chats=[_ALL16, _8THS, _ALL16, _ALL16],
        mel=["pluck", "bells", "pluck", "piano"]),
    "Pop": _f(
        "House",
        ["Chart Pop Classic", "Dance Pop Shine", "Retro Pop Groove",
         "Modern Pop Bounce"],
        [[0, 4, 8, 12], [0, 8], [0, 4, 8, 12], [0, 6, 10]],
        [[0, 5, 7, 10], [0, 7, 10, 5], [0, 10, 5, 3], [0, 3, 8, 10]],
        [0.02, 0.04, 0.06, 0.03],
        [[2, 6, 10, 14], [0, 10], [0, 4, 8, 12], [0, 7, 10]],
        chats=[_8THS, _8THS, _ALL16, _ALL16],
        snares=[[4, 12], [4, 12], [4, 12], [4, 12]],
        mel=["pluck", "piano", "bells", "pluck"]),
    "Garage": _f(
        "House",
        ["UKG 2-Step Classic", "Speed Garage Bounce", "Soulful Garage",
         "Modern UKG Wave"],
        [[0, 10], [0, 4, 10], [0, 10, 12], [0, 7, 10]],
        [[0, 5, 3, 10], [0, 10, 7, 5], [0, 7, 10, 5], [0, 3, 8, 10]],
        [0.18, 0.12, 0.20, 0.14],
        [[0, 10], [2, 6, 10, 14], [0, 7, 12], [0, 10, 14]],
        chats=[_8THS, _ALL16, _8THS, _ALL16],
        snares=[[4, 12], [4, 12], [4, 12], [4, 12]],
        mel=["none", "pluck", "piano", "bells"]),
    "JerseyClub": _f(
        "House",
        ["Jersey Bounce Classic", "Kick Pattern Chaos", "Club Breaks Wave",
         "Party Jersey"],
        [[0, 6, 10], [0, 3, 6, 10], [0, 10, 12], [0, 6, 8, 11]],
        [[0, 5, 3, 10], [0, 10, 8, 3], [0, 3, 10, 8], [0, 7, 5, 10]],
        [0.04, 0.02, 0.05, 0.03],
        [[0, 6, 10], [0, 3, 10], [2, 6, 10, 14], [0, 8, 10]],
        chats=[_ALL16, _ALL16, _8THS, _ALL16],
        snares=[[4, 12], [4, 12], [4, 12], [4, 12]],
        mel=["none", "bells", "none", "pluck"]),
    "DnB": _f(
        "DnB",
        ["Classic Two-Step", "Jump Up Energy", "Liquid Roller",
         "Neuro Pulse"],
        [[0, 10], [0, 10, 12], [0, 10], [0, 6, 10]],
        [[0, 10, 8, 7], [0, 3, 10, 8], [0, 5, 10, 7], [0, 8, 3, 10]],
        [0.0, 0.0, 0.04, 0.0],
        [[0, 4, 10], [0, 10], [0, 6, 12], [0, 2, 10]],
        chats=[_8THS, _ALL16, _8THS, _ALL16],
        mel=["none", "pluck", "piano", "bells"]),
    "Dubstep": _f(
        "Dubstep",
        ["OG UK Dubstep", "Brostep Smash", "Riddim Groove",
         "Melodic Dubstep"],
        [[0], [0, 10], [0, 7], [0, 8]],
        [[0, 3, 10, 8], [0, 10, 8, 3], [0, 8, 3, 10], [0, 5, 7, 10]],
        [0.0, 0.0, 0.02, 0.0],
        [[0, 8], [0, 10], [0, 7, 12], [0, 8, 14]],
        chats=[[0, 4, 8, 12], _8THS, [0, 4, 8, 12], _8THS],
        snares=[[8], [8], [8], [8]],
        mel=["pluck", "pluck", "bells", "piano"]),
    "Breakbeat": _f(
        "Breakbeat",
        ["Amen Energy Classic", "Big Beat Stomp", "Funky Breaks",
         "Nu Skool Breaks"],
        [[0, 7, 10, 12], [0, 8, 10], [0, 7, 10], [0, 10, 12]],
        [[0, 10, 7, 5], [0, 5, 10, 3], [0, 7, 5, 10], [0, 3, 8, 10]],
        [0.08, 0.04, 0.10, 0.05],
        [[0, 7, 10], [0, 8], [0, 10, 12], [0, 6, 10]],
        chats=[[0, 3, 6, 10, 12, 14], _8THS, _8THS, _ALL16],
        snares=[[4, 12, 15], [4, 12], [4, 12, 15], [4, 12]],
        mel=["pluck", "pluck", "piano", "bells"]),
    "Experimental": _f(
        "Breakbeat",
        ["Odd Meter Lab", "Glitch Groove", "Leftfield Bass",
         "Abstract Pulse"],
        [[0, 5, 11], [0, 7, 13], [0, 3, 10, 14], [0, 9]],
        [[0, 6, 11, 4], [0, 10, 4, 9], [0, 3, 11, 6], [0, 7, 2, 10]],
        [0.06, 0.02, 0.08, 0.0],
        [[0, 5, 11], [0, 13], [0, 7], [0, 9, 14]],
        chats=[[0, 3, 7, 11], [0, 5, 10, 14], _SPARSE, [0, 6, 12]],
        snares=[[7], [4, 13], [10], [6, 14]],
        mel=["bells", "pluck", "bells", "piano"]),
})

FAMILIES.update({
    "RockNRoll": _f(
        "RockNRoll",
        ["50s Classic Rock", "Garage Rock Raw", "Southern Rock Drive",
         "Modern Indie Rock"],
        [[0, 8, 10], [0, 8], [0, 4, 8, 12], [0, 8, 11]],
        [[0, 5, 7, 5], [0, 10, 5, 7], [0, 7, 5, 10], [0, 3, 8, 10]],
        [0.14, 0.08, 0.12, 0.05],
        [[0, 4, 8, 12], [0, 8], [0, 4, 10], [0, 7, 10]],
        chats=[_8THS, _8THS, _ALL16, _8THS],
        mel=["guitar", "guitar", "guitar", "guitar"]),
    "HeavyMetal": _f(
        "HeavyMetal",
        ["Thrash Classic", "Double Kick Assault", "Groove Metal Stomp",
         "Modern Metalcore"],
        [[0, 2, 4, 6, 8, 10, 12, 14], [0, 4, 8, 12],
         [0, 8, 10], [0, 6, 8, 14]],
        [[0, 10, 8, 6], [0, 3, 10, 8], [0, 5, 10, 3], [0, 8, 6, 11]],
        [0.0, 0.0, 0.02, 0.0],
        [[0, 2, 4, 6, 8, 10, 12, 14], [0, 4, 8, 12], [0, 8, 10],
         [0, 6, 10]],
        chats=[_8THS, _ALL16, _8THS, _ALL16],
        mel=["guitar_dist", "guitar_dist", "guitar_dist", "guitar_dist"]),
    "Blues": _f(
        "Blues",
        ["Chicago Shuffle", "Delta Slow Blues", "Texas Boogie",
         "Modern Blues Rock"],
        [[0, 6, 10], [0, 10], [0, 4, 8, 12], [0, 8, 10]],
        [[0, 0, 5, 7], [0, 5, 0, 7], [0, 7, 5, 0], [0, 3, 8, 10]],
        [0.35, 0.38, 0.28, 0.16],
        [[0, 4, 6, 8, 10, 12, 14], [0, 7, 10], [0, 4, 8, 12],
         [0, 6, 10]],
        chats=[[0, 3, 6, 10, 12, 14], _SPARSE, _8THS, _8THS],
        mel=["pluck", "guitar", "guitar", "guitar"]),
    "Jazz": _f(
        "Jazz",
        ["Swing Classic", "Bebop Bounce", "Cool Jazz Night",
         "Jazz Fusion Groove"],
        [[0, 10], [0, 7, 10], [0, 10], [0, 4, 10]],
        [[2, 7, 0, 0], [0, 5, 10, 7], [0, 9, 2, 7], [0, 7, 10, 5]],
        [0.40, 0.34, 0.42, 0.24],
        [[0, 4, 7, 10], [0, 7, 10], [0, 10], [0, 4, 8, 12]],
        chats=[[], _SPARSE, [], _8THS],
        mel=["piano", "piano", "piano", "piano"]),
    "Gospel": _f(
        "Jazz",
        ["Choir Lift Classic", "Praise Groove", "Slow Worship Soul",
         "Gospel Funk Joy"],
        [[0, 10], [0, 4, 8, 12], [0, 10], [0, 6, 10]],
        [[0, 5, 7, 10], [0, 7, 10, 5], [0, 9, 5, 7], [0, 3, 8, 10]],
        [0.30, 0.20, 0.36, 0.18],
        [[0, 4, 7, 10], [0, 8], [0, 10], [0, 4, 10]],
        chats=[_8THS, _8THS, _SPARSE, _ALL16],
        snares=[[4, 12], [4, 12], [4, 12], [4, 12]],
        mel=["piano", "piano", "piano", "piano"]),
    "Country": _f(
        "RockNRoll",
        ["Classic Honky Tonk", "Modern Country Pop", "Outlaw Country Drive",
         "Country Rock Road"],
        [[0, 8], [0, 4, 8, 12], [0, 8, 10], [0, 8]],
        [[0, 5, 7, 5], [0, 7, 10, 5], [0, 3, 8, 5], [0, 5, 10, 7]],
        [0.18, 0.06, 0.10, 0.12],
        [[0, 4, 8, 12], [0, 8], [0, 10], [0, 4, 8, 12]],
        chats=[_8THS, _8THS, _8THS, _ALL16],
        snares=[[4, 12], [4, 12], [4, 12], [4, 12]],
        mel=["guitar", "guitar", "guitar", "guitar"]),
    "Ambient": _f(
        "BoomBap",
        ["Floating Texture", "Deep Space Drift", "Piano Mist",
         "Slow Pulse Ambient"],
        [[0], [], [0, 12], [0, 8]],
        [[0, 5, 7, 10], [0, 10, 3, 8], [0, 9, 5, 2], [0, 7, 12, 5]],
        [0.10, 0.06, 0.14, 0.08],
        [[0], [0, 10], [0], [0, 8]],
        chats=[_SPARSE, [], _SPARSE, _8THS],
        snares=[[], [], [12], []],
        mel=["piano", "bells", "piano", "bells"]),
    "Classical": _f(
        "Jazz",
        ["Baroque Pulse", "Romantic Waltz Feel", "Minimal Strings",
         "Modern Cinematic"],
        [[0, 8], [], [0], [0, 10]],
        [[0, 5, 7, 0], [0, 7, 5, 10], [0, 4, 9, 2], [0, 3, 8, 10]],
        [0.12, 0.16, 0.05, 0.08],
        [[0, 8], [0, 6, 12], [0, 4, 8], [0, 10]],
        chats=[_SPARSE, [], _8THS, _SPARSE],
        snares=[[12], [], [], [12]],
        mel=["piano", "piano", "piano", "piano"]),
    "Synthwave": _f(
        "Techno",
        ["Outrun Night Drive", "Retro Wave Classic", "Dark Synth Chase",
         "Chillwave Sunset"],
        [[0, 4, 8, 12], [0, 4, 8, 12], [0, 4, 8, 12], [0, 8]],
        [[0, 10, 8, 3], [0, 5, 10, 7], [0, 8, 3, 11], [0, 7, 10, 5]],
        [0.0, 0.02, 0.0, 0.06],
        [[0, 2, 4, 6, 8, 10, 12, 14], [0, 4, 8, 12],
         [0, 2, 6, 10, 14], [0, 8]],
        chats=[_8THS, _8THS, _ALL16, _SPARSE],
        snares=[[4, 12], [4, 12], [4, 12], [4, 12]],
        mel=["bells", "pluck", "bells", "piano"]),
})

# Canonical app genre (normalized key) -> family key.
_ALIASES = {
    "drill": "Drill", "trap": "Trap", "hiphop": "HipHop",
    "boombap": "BoomBap", "rnb": "RnB", "dancehall": "Dancehall",
    "blues": "Blues", "ambient": "Ambient", "classical": "Classical",
    "country": "Country", "edm": "EDM", "experimental": "Experimental",
    "pop": "Pop", "rocknroll": "RockNRoll", "rockandroll": "RockNRoll",
    "rock": "RockNRoll", "heavymetal": "HeavyMetal", "metal": "HeavyMetal",
    "lofi": "LoFi", "afrobeats": "Afrobeats", "reggaeton": "Reggaeton",
    "dembow": "Reggaeton", "house": "House", "techno": "Techno",
    "dubstep": "Dubstep", "phonk": "Phonk", "jazz": "Jazz",
    "soul": "Soul", "gospel": "Gospel", "trance": "Trance",
    "drumnb": "DnB", "drumandbass": "DnB", "dnb": "DnB",
    "garage": "Garage", "ukgarage": "Garage", "synthwave": "Synthwave",
    "breakbeat": "Breakbeat", "breaks": "Breakbeat",
    "jerseyclub": "JerseyClub", "bailefunk": "BaileFunk",
    "afroswing": "Afroswing", "memphisrap": "MemphisRap",
    "memphisphonk": "MemphisRap", "detroittechno": "DetroitTechno",
    "hardstyle": "Hardstyle",
}

_LAST = {}  # family -> last (archetype, bass, hat) combo served


def family_for(raw_genre):
    """Map any genre spelling to its variant family key (default HipHop)."""
    key = "".join(ch for ch in str(raw_genre or "").lower() if ch.isalnum())
    return _ALIASES.get(key, "HipHop")


def base_for(raw_genre):
    """lightbeat._PATTERNS key that supplies this family's base sounds."""
    return FAMILIES[family_for(raw_genre)]["base"]


def apply_variant(pat, raw_genre, rng):
    """Roll a variant for raw_genre and apply it onto pat (in place).

    rng must be a dedicated stream owned by the caller for variants only.
    Returns (label, melody_inst_or_None, combo). Pure function of the
    caller's seed: the same seed always yields the same variant.
    """
    fam_key = family_for(raw_genre)
    fam = FAMILIES[fam_key]
    n_arch = len(fam["names"])
    arch = int(rng.integers(0, n_arch))
    bass_i = int(rng.integers(0, len(fam["basses"])))
    hat_i = (int(rng.integers(0, len(fam["chats"])))
             if fam["chats"] else -1)
    combo = (arch, bass_i, hat_i)
    _LAST[fam_key] = combo

    pat["kick"] = list(fam["kicks"][arch])
    pat["prog"] = list(fam["progs"][arch])
    pat["swing"] = float(fam["swings"][arch])
    pat["bass"] = list(fam["basses"][bass_i])
    if fam["chats"]:
        pat["chat"] = list(fam["chats"][hat_i])
    if fam["snares"]:
        pat["snare"] = list(fam["snares"][arch])
    label = fam["names"][arch]
    mel = fam["mel"][arch] if fam["mel"] else None
    return label, mel, combo
