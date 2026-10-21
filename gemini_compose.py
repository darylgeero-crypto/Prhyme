"""Gemini-powered musical composition for Prhyme beats.

Gemini writes the MUSIC (chord progressions, drum patterns, basslines,
melodies as structured JSON). The local V68 engine renders the SOUND.
Compositions are cached by (genre, seed) so the same seed always gives
the same beat and we don't burn API quota.
"""
import json
import os
import re
import urllib.request
import urllib.error
import threading
import time

MODELS = ["gemini-3.8-flash", "gemini-3.7-flash",
          "gemini-3.6-flash", "gemini-3.5-flash"]

_CACHE_DIR = "/storage/emulated/0/djrill/mobile/.gemini_cache"


def _get_key():
    try:
        with open("/storage/emulated/0/djrill/mobile/.gemini_key") as f:
            return f.read().strip()
    except Exception:
        return None


def _cache_path(genre, seed):
    safe = re.sub(r"[^a-z0-9]", "", (genre or "hiphop").lower())
    return os.path.join(_CACHE_DIR, f"{safe}_{int(seed) % 100000000}.json")


_quota_cooldown = [0.0]  # epoch time; Gemini calls pause until then


def _gemini_json(prompt, timeout=12):
    if time.time() < _quota_cooldown[0]:
        return None
    key = _get_key()
    if not key:
        return None
    data = json.dumps({
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"maxOutputTokens": 1024, "temperature": 0.9},
    }).encode()
    for model in MODELS:
        url = (f"https://generativelanguage.googleapis.com/v1beta/models/"
               f"{model}:generateContent?key={key}")
        try:
            req = urllib.request.Request(
                url, data=data, headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                result = json.loads(resp.read())
            text = result["candidates"][0]["content"]["parts"][0]["text"]
            # extract the JSON block
            m = re.search(r"\{.*\}", text, re.DOTALL)
            if not m:
                continue
            return json.loads(m.group(0))
        except urllib.error.HTTPError as e:
            if e.code == 429:
                # Shared project quota: every model will 429 too. Cool
                # down instead of burning calls, and let the caller use
                # the pool / procedural engine meanwhile.
                _quota_cooldown[0] = time.time() + 90
                return None
            continue
        except Exception:
            continue
    return None


_COMPOSE_PROMPT = """You are a professional {genre} beat producer composing a beat at {bpm} BPM.
Write an original 1-bar (16 sixteenth-step) composition. Output STRICT JSON only, no other text.

JSON schema (all arrays are 16 steps unless noted, velocities 0.0-1.0, 0 = rest):
{{
  "key_root": <MIDI note 33-47 for the song key root>,
  "mode": "<minor|major|dorian|phrygian>",
  "progression": [<4 scale degrees 0-6, one per beat of the bar, e.g. [0,5,3,4]>],
  "drums": {{
    "kick":  [<16 velocities>],
    "snare": [<16 velocities>],
    "hihat": [<16 velocities>],
    "openhat": [<16 velocities>]
  }},
  "bass": {{
    "steps": [<steps 0-15 where the bass plays>],
    "degrees": [<scale degree 0-6 for each hit, relative to current chord root>]
  }},
  "chords": {{
    "stabs": [<steps 0-15 where chord stabs hit>],
    "add7": <true|false - add the 7th to chords>
  }},
  "lead": [
    [<step 0-15>, <scale degree 0-6>, <octave offset 0-2>],
    ... 4 to 8 notes forming a memorable melodic motif ...
  ]
}}

Rules for a MUSICAL, professional {genre} beat:
- Drums: strong backbeat (kick on beat 1, snare on beats 2 and 4 for boom-bap; trap/drill use their signature patterns). Ghost notes quiet (<=0.4).
- Bass: lock with the kick drum, use chord roots and fifths, sparse is better.
- Chords: stabs on off-beats or sustained pad feel, diatonic to the mode.
- Lead: a short MEMORABLE motif (4-8 notes), mostly stepwise motion, chord tones on strong beats, repetition with tiny variation.
- Everything must be diatonic to key_root + mode. No random chromatic notes.
- This must sound like a real produced beat, not an exercise.

Output JSON only."""


_POOL_DIR = os.path.join(_CACHE_DIR, "pool")
_POOL_MAX = 6
_pool_fetching = set()
_pool_lock = threading.Lock()


def _pool_path(genre):
    safe = re.sub(r"[^a-z0-9]", "", (genre or "hiphop").lower())
    return os.path.join(_POOL_DIR, safe)


def _pool_pick(genre):
    """Least-recently-used pooled composition for the genre, or None.
    The pool keeps several distinct Gemini compositions per genre warm,
    so a beat never waits on the network once the pool is seeded — and
    rotation keeps consecutive beats from reusing the same skeleton."""
    try:
        d = _pool_path(genre)
        if not os.path.isdir(d):
            return None
        files = [os.path.join(d, f) for f in os.listdir(d)
                 if f.endswith(".json")]
        if not files:
            return None
        files.sort(key=lambda p: os.path.getmtime(p))
        for fp in files:
            try:
                with open(fp) as f:
                    comp = json.load(f)
                if _valid(comp):
                    os.utime(fp, None)  # mark used -> rotates to the back
                    return comp
            except Exception:
                continue
    except Exception:
        pass
    return None


def _pool_add(genre, comp):
    try:
        d = _pool_path(genre)
        os.makedirs(d, exist_ok=True)
        import time as _t
        fp = os.path.join(d, "comp_%d.json" % int(_t.time() * 1000))
        with open(fp, "w") as f:
            json.dump(comp, f)
        files = [os.path.join(d, x) for x in os.listdir(d)
                 if x.endswith(".json")]
        files.sort(key=lambda p: os.path.getmtime(p))
        while len(files) > _POOL_MAX:
            try:
                os.remove(files.pop(0))
            except OSError:
                break
    except Exception:
        pass


def _pool_fetch_worker(genre, bpm):
    try:
        prompt = _COMPOSE_PROMPT.format(genre=genre or "HipHop",
                                        bpm=int(bpm or 92))
        comp = _gemini_json(prompt)
        if comp and _valid(comp):
            _pool_add(genre, comp)
    except Exception:
        pass
    finally:
        with _pool_lock:
            _pool_fetching.discard(genre)


def _kick_pool_fetch(genre, bpm):
    with _pool_lock:
        if genre in _pool_fetching:
            return
        _pool_fetching.add(genre)
    threading.Thread(target=_pool_fetch_worker, args=(genre, bpm),
                     daemon=True).start()


def warm_pools(genres=("Trap", "HipHop", "Drill", "BoomBap")):
    """Preload composition pools at startup (Daryl's preload rule) so the
    first beat of a session is as fast as the rest. Background only."""
    def _w():
        try:
            if not is_online():
                return
            for g in genres:
                d = _pool_path(g)
                n = 0
                if os.path.isdir(d):
                    n = len([x for x in os.listdir(d)
                             if x.endswith(".json")])
                if n < 2:
                    _kick_pool_fetch(g, 92)
        except Exception:
            pass
    threading.Thread(target=_w, daemon=True).start()


def get_composition(genre, bpm, seed):
    """Return composition dict for (genre, seed). Exact-seed cache first,
    then the rotating per-genre pool (instant), and only when the pool is
    empty pay for a synchronous Gemini call. None on failure (the caller
    falls back to the procedural engine)."""
    cp = _cache_path(genre, seed)
    try:
        if os.path.isfile(cp):
            with open(cp) as f:
                comp = json.load(f)
            if _valid(comp):
                return comp
    except Exception:
        pass
    pooled = _pool_pick(genre)
    if pooled is not None:
        _kick_pool_fetch(genre, bpm)  # refresh the pool in the background
        return pooled
    prompt = _COMPOSE_PROMPT.format(genre=genre or "HipHop", bpm=int(bpm or 92))
    comp = _gemini_json(prompt)
    if comp and _valid(comp):
        try:
            os.makedirs(_CACHE_DIR, exist_ok=True)
            with open(cp, "w") as f:
                json.dump(comp, f)
        except Exception:
            pass
        _pool_add(genre, comp)
        return comp
    return None


def _valid(comp):
    try:
        assert isinstance(comp, dict)
        assert 33 <= int(comp["key_root"]) <= 47
        assert comp["mode"] in ("minor", "major", "dorian", "phrygian")
        assert len(comp["progression"]) == 4
        d = comp["drums"]
        for k in ("kick", "snare", "hihat"):
            assert len(d[k]) == 16
        assert isinstance(comp["bass"]["steps"], list)
        assert isinstance(comp["chords"]["stabs"], list)
        assert isinstance(comp["lead"], list) and len(comp["lead"]) >= 2
        return True
    except Exception:
        return False
"""Gemini composition as text files — online only, offline falls back to procedural."""

import json
import os

# Add to gemini_compose.py: explicit text file interface

TEXT_DIR = "/storage/emulated/0/djrill/mobile/compositions"

def save_composition_text(genre, bpm, seed, comp):
    """Save Gemini composition as a readable text file. Returns path."""
    os.makedirs(TEXT_DIR, exist_ok=True)
    safe = "".join(c for c in (genre or "hiphop").lower() if c.isalnum())
    path = os.path.join(TEXT_DIR, f"{safe}_{int(seed) % 100000000}.prhyme.txt")
    text = json.dumps({
        "format": "prhyme-composition-v1",
        "genre": genre,
        "bpm": int(bpm),
        "seed": int(seed),
        "composition": comp,
    }, indent=2)
    with open(path, "w") as f:
        f.write(text)
    return path

def load_composition_text(path):
    """Decode a composition text file. Returns (genre, bpm, seed, comp) or None."""
    try:
        with open(path) as f:
            data = json.load(f)
        if data.get("format") != "prhyme-composition-v1":
            return None
        return data["genre"], data["bpm"], data["seed"], data["composition"]
    except Exception:
        return None

def is_online():
    """Check if Gemini API is reachable."""
    import socket
    try:
        socket.create_connection(("generativelanguage.googleapis.com", 443), timeout=3).close()
        return True
    except OSError:
        return False
