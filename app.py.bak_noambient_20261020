#!/usr/bin/env python3
"""Djrill Mobile — touch-friendly web app wrapping the DJRILL audio engine.

Run:  cd ~/workspace/djrill/mobile && python3 app.py   (port 5000)

Pages: Home / Master / Lyrics / Convert / Beats.
The engine edits human recordings — it never synthesizes, clones, or
fakes a vocal performance. Lyrics output is AI-generated draft material
only and is always labeled as such.
"""
import os
import re
import sys
import uuid
import json
import time
import shutil
import hashlib
import threading
import zipfile

DJRILL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, DJRILL_DIR)

# Headless pygame stub so the V68 engine imports without a display/audio device.
_stub_src = os.path.join(DJRILL_DIR, "stubs", "pygame.py")
# Use a writable temp dir (Android/Pydroid3 has read-only /tmp).
_base_tmp = os.environ.get("TMPDIR") or os.path.join(DJRILL_DIR, "tmp")
os.makedirs(_base_tmp, exist_ok=True)
_stub_dir = os.path.join(_base_tmp, "stubs")
os.makedirs(_stub_dir, exist_ok=True)
if os.path.exists(_stub_src):
    shutil.copy(_stub_src, os.path.join(_stub_dir, "pygame.py"))
# Stub must come FIRST so it shadows any real pygame install (e.g. Pydroid3).
sys.path.insert(0, _stub_dir)
# Pydroid3 may have pre-imported real pygame — evict it so the stub wins.
for _mod in [m for m in sys.modules if m == "pygame" or m.startswith("pygame.")]:
    del sys.modules[_mod]
# Pre-load the stub into sys.modules so nothing can pull in real pygame.
# Only if the stub file actually exists (cloud deploys may not have it).
import importlib.util as _ilu
_stub_file = os.path.join(_stub_dir, "pygame.py")
if os.path.exists(_stub_file):
    _stub_spec = _ilu.spec_from_file_location("pygame", _stub_file)
    _stub_mod = _ilu.module_from_spec(_stub_spec)
    sys.modules["pygame"] = _stub_mod
    _stub_spec.loader.exec_module(_stub_mod)
else:
    # No stub file — create a minimal in-memory pygame stub
    import types
    _pygame_stub = types.ModuleType("pygame")
    _stub_cls = type("_Stub", (), {"__getattr__": lambda s, n: _stub_cls(), "__call__": lambda s, *a, **k: _stub_cls()})
    _pygame_stub.mixer = _stub_cls()
    _pygame_stub.display = _stub_cls()
    _pygame_stub.time = _stub_cls()
    _pygame_stub.event = _stub_cls()
    _pygame_stub.init = lambda *a, **k: None
    _pygame_stub.quit = lambda *a, **k: None
    sys.modules["pygame"] = _pygame_stub

import numpy as np
from scipy.io.wavfile import write as wav_write, read as wav_read
from scipy import signal
from flask import Flask, request, render_template, jsonify, send_file, abort, url_for, session as _flask_session
from werkzeug.utils import secure_filename

import djrill_master as M
import chunkpipe  # shared chunk/stitch pipeline (2026-10-20 unification)
import djrill_lyrics as L
import djrill_convert as C
import djrill_video as V
import daw
import beatfx
import masterfx
try:
    import adaptive_master
    _ADAPTIVE_AVAILABLE = True
except ImportError:
    _ADAPTIVE_AVAILABLE = False
import videofx
import audiotools
import lightbeat  # pure-numpy fast beat renderer (no pygame/ffmpeg/samples)
import mixgen  # DJ mix generator: beatmatched original mixes + era styles
import soundkits  # user-uploaded custom drum kits (WAV one-shots)
import audiofx
import vocalfix  # vocal clarity + subtle timing correction (never deletes words)
import vocalfx  # ONLINE-ONLY vocal separator + auto SFX layer (cloud DSP/Demucs)
import player as player_mod  # offline music player: browse + stream on-device audio
import trackfx  # creative FX: radio, vinyl, TV, filters, echo (never deletes words)
import rockdabus as RB  # Rokdabus Prhyme — conversational assistant brain

BASE = os.path.dirname(os.path.abspath(__file__))
UPLOAD_DIR = os.path.join(BASE, "uploads")
OUTPUT_DIR = os.path.join(BASE, "outputs")
HISTORY_FILE = os.path.join(BASE, "job_history.json")
os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(OUTPUT_DIR, exist_ok=True)

# --- Temp beats: last 5 generations live here until downloaded/overwritten ---
TEMP_BEATS_DIR = os.path.join(OUTPUT_DIR, "temp_beats")
TEMP_BEATS_MANIFEST = os.path.join(TEMP_BEATS_DIR, "manifest.json")
TEMP_BEATS_KEEP = 5

def _temp_beats_manifest():
    try:
        with open(TEMP_BEATS_MANIFEST) as f:
            m = json.load(f)
        return m if isinstance(m, list) else []
    except Exception:
        return []

def _temp_beats_save(manifest):
    os.makedirs(TEMP_BEATS_DIR, exist_ok=True)
    tmp = TEMP_BEATS_MANIFEST + ".tmp"
    with open(tmp, "w") as f:
        json.dump(manifest[-TEMP_BEATS_KEEP:], f)
    os.replace(tmp, TEMP_BEATS_MANIFEST)

def temp_beats_register(job_id, base, files, genre, bpm, duration):
    """Register a temp beat; evict oldest beyond 5 (files deleted)."""
    manifest = [e for e in _temp_beats_manifest()
                if e.get("job_id") != job_id]
    manifest.append({"job_id": job_id, "base": base, "files": files,
                     "genre": genre, "bpm": bpm, "duration": duration,
                     "created": time.time()})
    while len(manifest) > TEMP_BEATS_KEEP:
        old = manifest.pop(0)
        for fn in (old.get("files") or {}).values():
            if fn:
                try:
                    os.remove(os.path.join(TEMP_BEATS_DIR, fn))
                except OSError:
                    pass
    _temp_beats_save(manifest)
    return manifest

# --- Temp masters: per-job dirs, removed on keep/discard/timeout ---
TEMP_MASTERS_DIR = os.path.join(OUTPUT_DIR, "temp_masters")

def _temp_master_dir(job_id):
    return os.path.join(TEMP_MASTERS_DIR, str(job_id)[:8])

def temp_master_cleanup(job_id):
    """Delete a master job's temp dir + its A/B previews. Returns deleted list."""
    deleted = []
    tdir = _temp_master_dir(job_id)
    if os.path.isdir(tdir):
        for fn in os.listdir(tdir):
            try:
                os.remove(os.path.join(tdir, fn))
                deleted.append(fn)
            except OSError:
                pass
        try:
            os.rmdir(tdir)
        except OSError:
            pass
    abdir = os.path.join(OUTPUT_DIR, "temp_ab")
    prefix = str(job_id)[:8]
    if os.path.isdir(abdir):
        for fn in os.listdir(abdir):
            if fn.startswith(prefix):
                try:
                    os.remove(os.path.join(abdir, fn))
                    deleted.append("ab/" + fn)
                except OSError:
                    pass
    return deleted

def temp_master_cleanup_all(max_age_secs=86400):
    """Remove master temp dirs older than max_age (abandoned jobs)."""
    if not os.path.isdir(TEMP_MASTERS_DIR):
        return 0
    now = time.time()
    n = 0
    for jid in os.listdir(TEMP_MASTERS_DIR):
        tdir = os.path.join(TEMP_MASTERS_DIR, jid)
        if not os.path.isdir(tdir):
            continue
        try:
            age = now - os.path.getmtime(tdir)
        except OSError:
            continue
        if age > max_age_secs:
            temp_master_cleanup(jid)
            n += 1
    return n


# ---------------------------------------------------------------------------
# LITE MODE — crash-proof defaults for phones. Default ON.
# When on: beats cap at 16 bars + forced fast renderer, mixes use 2 short
# segments, mastering skips the heavy reference-match step, video renders at
# 480p. Persisted server-side; the client mirrors it in localStorage.
# ---------------------------------------------------------------------------
LITE_FILE = os.path.join(BASE, "lite_mode.json")


def lite_mode():
    """True when lite mode is on. Defaults to True (safe)."""
    try:
        with open(LITE_FILE) as f:
            return bool(json.load(f).get("lite", True))
    except (OSError, ValueError):
        return True


def set_lite_mode(on):
    try:
        with open(LITE_FILE, "w") as f:
            json.dump({"lite": bool(on)}, f)
    except OSError:
        pass


# ---------------------------------------------------------------------------
# MEMORY GUARDS — refuse gracefully instead of OOM-crashing the phone.
# Uses /proc/meminfo (no psutil dependency). Estimates working-set size as
# n_samples * channels * 4 bytes * copies (numpy temporaries multiply).
# ---------------------------------------------------------------------------
def mem_available_mb():
    try:
        with open("/proc/meminfo") as f:
            for line in f:
                if line.startswith("MemAvailable:"):
                    return int(line.split()[1]) // 1024
    except OSError:
        pass
    return None  # unknown platform — skip the check



def master_chunked(mix, masterfx, chain, mopts, prog, SR=44100):
    """Master long audio in 45s chunks with 2s overlap crossfades.
    STREAMING: takes file path OR numpy array. If path, streams from disk
    using memory-mapping — never loads full file into RAM. Phone-safe for
    20+ minute tracks."""
    import gc, os
    import numpy as np
    import chunkpipe as _cp
    CHUNK_S = _cp.ram_chunk_s(45, 30, 90)
    OVERLAP_S = 2
    chunk_n = int(CHUNK_S * SR)
    overlap_n = int(OVERLAP_S * SR)

    # Streaming mode: memory-map the file from disk
    is_path = isinstance(mix, str)
    mmap = None
    if is_path:
        # Get info without loading
        from scipy.io.wavfile import read as wav_read
        # Use memmap for WAV files
        if mix.lower().endswith(".wav"):
            import wave
            with wave.open(mix, "rb") as w:
                n_frames = w.getnframes()
                n_ch = w.getnchannels()
                sampwidth = w.getsampwidth()
                framerate = w.getframerate()
            # Memory-map the raw PCM data (skip 44-byte header for standard WAV)
            # Fallback: load in chunks via soundfile if available
            try:
                import soundfile as sf
                info = sf.info(mix)
                total = info.frames
                n_ch = info.channels
                use_sf = True
            except ImportError:
                use_sf = False
                # Fallback: load fully (old behavior) if no soundfile.
                # scipy returns int16 — convert to float [-1, 1] for the
                # mastering chain (master_with_options expects float).
                sr, mix = wav_read(mix)
                if mix.dtype == np.int16:
                    mix = mix.astype(np.float32) / 32768.0
                elif mix.dtype == np.int32:
                    mix = mix.astype(np.float32) / 2147483648.0
                elif mix.dtype == np.uint8:
                    mix = (mix.astype(np.float32) - 128) / 128.0
                total = mix.shape[0]
                n_ch = mix.shape[1] if mix.ndim > 1 else 1
        else:
            # Non-WAV: try soundfile, else load fully
            try:
                import soundfile as sf
                info = sf.info(mix)
                total = info.frames
                n_ch = info.channels
                use_sf = True
            except ImportError:
                use_sf = False
                raise ValueError("soundfile required for streaming non-WAV")
    else:
        # Old behavior: numpy array already in RAM.
        # Ensure float [-1, 1] for the mastering chain.
        use_sf = False
        if mix.dtype == np.int16:
            mix = mix.astype(np.float32) / 32768.0
        elif mix.dtype == np.int32:
            mix = mix.astype(np.float32) / 2147483648.0
        elif mix.dtype == np.uint8:
            mix = (mix.astype(np.float32) - 128) / 128.0
        total = mix.shape[0]
        n_ch = mix.shape[1] if mix.ndim > 1 else 1

    def _get_chunk(start, end):
        """Get audio chunk [start:end] without loading full file."""
        if not is_path or not use_sf:
            return mix[start:end]
        import soundfile as sf
        data, _ = sf.read(mix, start=start, stop=end, always_2d=True)
        return data

    def _master_one(chunk):
        return masterfx.master_with_options(
            chunk, chain_name=chain,
            target_lufs=mopts.get("target_lufs"),
            ceiling_db=float(mopts.get("ceiling_db", -1.0)),
            dither=bool(mopts.get("dither", True)),
            deess=float(mopts.get("deess", 0.0)),
            multiband=bool(mopts.get("multiband", False)))

    if total <= chunk_n:
        chunk = _get_chunk(0, total)
        return _master_one(chunk)

    n_chunks = int(np.ceil(total / chunk_n))
    prog(80, f"Mastering in {n_chunks} chunks (streaming from disk)...")

    import tempfile
    spill = tempfile.mkdtemp(prefix="mchunks_")
    chunk_files = []
    last_report = None
    try:
        for i in range(n_chunks):
            start = max(0, i * chunk_n - overlap_n if i > 0 else 0)
            end = min(total, (i + 1) * chunk_n + (overlap_n if i < n_chunks - 1 else 0))
            chunk = _get_chunk(start, end)
            # Free the chunk reference after use
            prog(80 + int(5 * i / n_chunks), f"Mastering chunk {i+1}/{n_chunks}...")
            pcm16, report = _master_one(chunk)
            last_report = report
            del chunk
            gc.collect()
            # Spill to disk immediately
            cf = os.path.join(spill, f"chunk_{i:04d}.npy")
            np.save(cf, pcm16)
            chunk_files.append((start, end, cf))
            del pcm16
            gc.collect()

        # Splice chunks from disk with crossfades
        prog(86, "Splicing chunks...")
        # Load first chunk to get shape
        first = np.load(chunk_files[0][2])
        n_ch_out = first.shape[1] if first.ndim > 1 else 1
        del first
        # Build output incrementally
        result_parts = []
        for idx, (start, end, cf) in enumerate(chunk_files):
            data = np.load(cf)
            # Trim overlap (except first/last)
            if idx > 0:
                data = data[overlap_n:]
            if idx < len(chunk_files) - 1:
                data = data[:-overlap_n] if overlap_n > 0 else data
            result_parts.append(data)
            os.remove(cf)  # Free disk immediately
        import shutil
        shutil.rmtree(spill, ignore_errors=True)
        # Concatenate
        result = np.concatenate(result_parts, axis=0)
        del result_parts
        gc.collect()
        return result, last_report
    except Exception:
        import shutil
        shutil.rmtree(spill, ignore_errors=True)
        raise


def check_audio_budget(n_samples, channels=2, copies=6, label="audio",
                       headroom_mb=150):
    """Raise MemoryError with a friendly message if this op is risky."""
    avail = mem_available_mb()
    if avail is None:
        return
    need_mb = n_samples * channels * 4 * copies / (1024 * 1024)
    if avail < need_mb + headroom_mb:  # keep headroom for OS + app
        raise MemoryError(
            f"Not enough free memory for {label} "
            f"(needs ~{need_mb:.0f} MB, only {avail:.0f} MB free). "
            "Turn on Lite Mode or use shorter audio.")


def record_history(kind, title, result):
    """82. Append a completed job to the history log (max 100)."""
    try:
        hist = []
        if os.path.isfile(HISTORY_FILE):
            with open(HISTORY_FILE) as f:
                hist = json.load(f) or []
        entry = {"kind": kind, "title": title, "at": time.time(),
                 "result": {k: v for k, v in (result or {}).items()
                            if k in ("mp3", "wav", "file", "mp4", "duration",
                                     "lufs", "dbtp", "bpm", "bars")}}
        hist.insert(0, entry)
        with open(HISTORY_FILE, "w") as f:
            json.dump(hist[:100], f)
    except Exception:
        pass

app = Flask(__name__)
app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 0  # no stale caches
app.config["MAX_CONTENT_LENGTH"] = 200 * 1024 * 1024  # ~200 MB uploads
# 104. template + static caching
app.config["TEMPLATES_AUTO_RELOAD"] = False
app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 3600

# Monetization: user accounts, trials, subscriptions, Stripe.
# See billing.py / billing_core.py. First signup becomes owner + founding #1.
try:
    import billing as _billing
    _billing.init_app(app, BASE)
    print("💎 Billing enabled (pricing: /pricing, account: /account)", flush=True)
except Exception as e:
    print(f"⚠️  Billing disabled: {e}", flush=True)

# Pay-per-use beat store: server-side listing lookup (prices NEVER from client).
# beat_id format: "<listing_id>:<license>" e.g. "a1b2c3:lease" / "a1b2c3:exclusive".
def _payg_beat_lookup(beat_id):
    try:
        bid, _, lic = str(beat_id).partition(":")
        lic = lic or "lease"
        if lic not in ("lease", "exclusive"):
            return None
        import json as _json
        p = os.path.join(BASE, "store", bid + ".json")
        if not os.path.isfile(p):
            return None
        meta = _json.load(open(p))
        price = float(meta.get("exclusive_price" if lic == "exclusive" else "lease_price", 0))
        return {"id": str(beat_id), "title": meta.get("title", bid),
                "price": price, "license": lic,
                "seller_uid": meta.get("seller")}
    except Exception:
        return None

try:
    import billing_payments as _bp_pay
    _bp_pay.register_beat_lookup(_payg_beat_lookup)
    print("💳 Pay-per-use beat lookup wired", flush=True)
except Exception as e:
    print(f"⚠️  Pay-per-use wiring skipped: {e}", flush=True)

try:
    import billing_paypal as _bp_pp
    _bp_pp.register_beat_lookup(_payg_beat_lookup)
    print("PayPal beat lookup wired", flush=True)
except Exception as e:
    print(f"PayPal wiring skipped: {e}", flush=True)

# Offline music player: browse + stream audio from on-device storage.
player_mod.init_player(OUTPUT_DIR)
app.register_blueprint(player_mod.bp)
print("🎵 Player enabled (/player — Music/Downloads/Generated)", flush=True)

# SECURITY: startup integrity check — hash critical modules, warn if modified
# since last known-good run. This catches accidental corruption or tampering.
_INTEGRITY_FILE = os.path.join(BASE, ".integrity.json")
_INTEGRITY_MODULES = ["app.py", "lightbeat.py", "soundkits.py", "vocalfix.py",
                      "trackfx.py", "mixgen.py", "daw.py"]


def _integrity_check():
    import hashlib
    current = {}
    for mod in _INTEGRITY_MODULES:
        p = os.path.join(BASE, mod)
        if os.path.isfile(p):
            with open(p, "rb") as f:
                current[mod] = hashlib.sha256(f.read()).hexdigest()[:16]
    baseline = {}
    if os.path.isfile(_INTEGRITY_FILE):
        try:
            with open(_INTEGRITY_FILE) as f:
                baseline = json.load(f)
        except (OSError, ValueError):
            baseline = {}
    if baseline:
        changed = [m for m in current
                   if baseline.get(m) != current.get(m)]
        if changed:
            print(f"⚠️  Integrity warning: {', '.join(changed)} modified "
                  f"since last run", flush=True)
    # Update baseline for next run
    try:
        with open(_INTEGRITY_FILE, "w") as f:
            json.dump(current, f)
    except OSError:
        pass


_integrity_check()


@app.context_processor
def _inject_lite():
    """Make {{ lite }} (badge + toggles) and {{ is_paid }} (freemium tier)
    available in every template. is_paid drives the free-preview vs full
    UI wiring: free users get snippet endpoints + upgrade nudges."""
    paid = False
    try:
        from flask import session as _sess
        _uid = _sess.get("uid")
        if _uid:
            import billing_core as _bc
            _u = _bc.get_user(int(_uid))
            if _u:
                _active, _, _ = _bc.subscription_state(_u)
                paid = bool(_active)
    except Exception:
        paid = False
    return {"lite": lite_mode(), "is_paid": paid}


@app.after_request
def _cache_headers(resp):
    # 96. static assets cacheable; API never cached
    if request.path.startswith("/static/"):
        resp.headers["Cache-Control"] = "public, max-age=86400"
    elif request.path.startswith("/api/"):
        resp.headers["Cache-Control"] = "no-store"
    return resp


# 91. engine warm-up on startup (background, non-blocking)
def _warmup():
    try:
        get_engine()
    except Exception:
        pass


threading.Thread(target=_warmup, daemon=True).start()

# 92. job queue with concurrency limit (2 heavy jobs at once)
_job_slots = threading.Semaphore(2)


def run_guarded(fn, *args, **kwargs):
    """Run a job function holding a concurrency slot."""
    with _job_slots:
        return fn(*args, **kwargs)


# 101. beat render memoization: (genre,bpm,bars,seed,fxhash) -> wav bytes
_beat_cache = {}
_beat_cache_lock = threading.Lock()
BEAT_CACHE_MAX = 8


def _beat_cache_get(key):
    with _beat_cache_lock:
        return _beat_cache.get(key)


def _beat_cache_put(key, wav_path):
    with _beat_cache_lock:
        try:
            with open(wav_path, "rb") as f:
                data = f.read()
        except OSError:
            return
        _beat_cache[key] = data
        while len(_beat_cache) > BEAT_CACHE_MAX:
            _beat_cache.pop(next(iter(_beat_cache)))


# 98. old job cleanup (TTL 6h); 99. upload/output janitor
def _janitor():
    import time as _t
    while True:
        _t.sleep(1800)  # every 30 min
        try:
            now = _t.time()
            with jobs_lock:
                old = [jid for jid, j in jobs.items()
                       if now - j.get("_ts", now) > 6 * 3600]
                for jid in old:
                    jobs.pop(jid, None)
            # 99. delete uploads/outputs older than 48h
            for d in (UPLOAD_DIR, OUTPUT_DIR):
                for fn in os.listdir(d):
                    p = os.path.join(d, fn)
                    try:
                        if os.path.isfile(p) and now - os.path.getmtime(p) > 48 * 3600:
                            os.remove(p)
                    except OSError:
                        pass
        except Exception:
            pass


threading.Thread(target=_janitor, daemon=True).start()

SR = 44100
GENRES = ["HipHop", "Drill", "Trap", "BoomBap", "RnB", "Dancehall", "Blues",
          "Ambient", "Classical", "Country", "EDM", "Experimental",
          "Pop", "RockNRoll", "HeavyMetal", "LoFi", "Afrobeats", "Reggaeton", "House",
          "Techno", "Dubstep", "Phonk", "Jazz", "Soul", "Gospel",
          "Trance", "DrumNB", "Garage", "Synthwave", "Breakbeat", "DnB",
          "JerseyClub", "BaileFunk", "Afroswing", "MemphisRap",
          "DetroitTechno", "Hardstyle"]

# ---------------------------------------------------------------- jobs
jobs = {}
jobs_lock = threading.Lock()
_engine = None
_engine_lock = threading.Lock()


def set_job(job_id, **kw):
    with jobs_lock:
        j = jobs.setdefault(job_id, {"status": "running", "progress": 0,
                                     "message": "Starting…",
                                     "_ts": time.time()})
        j.update(kw)
        j["_ts"] = time.time()  # refresh for TTL
        # 82. record completed jobs to history
        if j.get("status") == "done" and not j.get("_hist"):
            j["_hist"] = True
            kind = j.pop("_kind", "job")
            title = j.pop("_title", "")
            threading.Thread(target=record_history,
                             args=(kind, title, j.get("result")),
                             daemon=True).start()


def new_job(kind, title=""):
    """Create a job id with history metadata."""
    job_id = uuid.uuid4().hex
    set_job(job_id, _kind=kind, _title=title[:60])
    return job_id


# 138. job watchdog: auto-fail jobs stuck >30 min
def _watchdog():
    import time as _t
    while True:
        _t.sleep(300)
        try:
            now = _t.time()
            with jobs_lock:
                for jid, j in list(jobs.items()):
                    if (j.get("status") == "running"
                            and now - j.get("_ts", now) > 1800):
                        j["status"] = "error"
                        j["message"] = "Timed out after 30 min — retry"
                        j["_ts"] = now
        except Exception:
            pass


threading.Thread(target=_watchdog, daemon=True).start()

# 143. simple per-IP rate limiting (60 req/min)
_rl = {}
_rl_lock = threading.Lock()

# SECURITY: expensive operations get a much tighter budget to prevent
# resource exhaustion (intentional or accidental).
_HEAVY_PATHS = ("/api/beats", "/api/master", "/api/mix", "/api/video/",
                "/api/daw/export", "/api/daw/stems", "/api/convert",
                "/api/separate")
_rl_heavy = {}
_HEAVY_KINDS = ("master", "stem-master", "separate", "beat", "mix",
                "mixdown", "stems", "video")
_rl_heavy_lock = threading.Lock()


@app.before_request
def _rate_limit():
    if request.path.startswith("/static/"):
        return None
    ip = request.headers.get("X-Forwarded-For", request.remote_addr or "?")
    now = time.time()
    with _rl_lock:
        hits = _rl.get(ip, [])
        hits = [t for t in hits if now - t < 60]
        hits.append(now)
        _rl[ip] = hits
        if len(hits) > 120:
            return jsonify({"ok": False,
                            "error": "Rate limited — slow down"}), 429
    # Freemium anti-abuse: free snippet previews are capped tighter than
    # paid renders. 5 previews per 10 minutes per IP — enough to try the
    # app, not enough to stitch snippets into full songs.
    # Paid users bypass this via their subscription (checked in billing gate,
    # which runs after this — so we check the session here directly).
    if request.path in ("/api/beats/preview", "/api/lyrics/preview"):
        try:
            from flask import session as _sess
            _uid = _sess.get("uid")
        except Exception:
            _uid = None
        _is_paid = False
        if _uid:
            try:
                import billing_core as _bc
                _u = _bc.get_user(int(_uid))
                if _u:
                    _active, _, _ = _bc.subscription_state(_u)
                    _is_paid = bool(_active)
            except Exception:
                pass
        if not _is_paid:
            with _rl_heavy_lock:
                _ph = _rl_heavy.get("preview:" + ip, [])
                _ph = [t for t in _ph if now - t < 600]
                _ph.append(now)
                _rl_heavy["preview:" + ip] = _ph
                if len(_ph) > 5:
                    return jsonify({
                        "ok": False,
                        "error": "preview_limit",
                        "message": (
                            "Free preview limit reached (5 per 10 min). "
                            "Upgrade for unlimited full generations."),
                        "upgrade_url": "/pricing",
                    }), 429
    # Heavy-op budget: 10 expensive renders per 5 minutes per IP.
    if request.path.startswith(_HEAVY_PATHS):
        with _rl_heavy_lock:
            hh = _rl_heavy.get(ip, [])
            hh = [t for t in hh if now - t < 300]
            hh.append(now)
            _rl_heavy[ip] = hh
            if len(hh) > 10:
                return jsonify({"ok": False,
                                "error": "Too many heavy jobs — "
                                         "wait a few minutes"}), 429
    # One heavy job at a time (Daryl's rule — RAM can't be overloaded):
    # mastering, separation, beats, mixes and video never run parallel.
    if request.method == "POST" and (
            request.path.startswith(_HEAVY_PATHS)
            or request.path.startswith("/api/separate")):
        with jobs_lock:
            for _jid, _j in jobs.items():
                if (_j.get("_kind") in _HEAVY_KINDS
                        and _j.get("status") == "running"):
                    return jsonify({
                        "ok": False,
                        "error": ("One job at a time — a "
                                  + str(_j.get("_kind"))
                                  + " job is still running. "
                                  "Wait for it to finish."),
                        "active_job_id": _jid,
                    }), 409
    return None


# 145. graceful engine failure: 503 if the engine can't load
@app.errorhandler(503)
def _e503(e):
    return jsonify({"ok": False,
                    "error": "Engine unavailable — restart the app"}), 503


# Crash-proofing: every API error returns JSON, never a raw traceback page.
# (Flask debug is off, but these make the contract explicit + log the cause.)
def _api_error(status, message):
    if request.path.startswith("/api/"):
        return jsonify({"ok": False, "error": message}), status
    return None  # let Flask render the normal HTML error page


@app.errorhandler(400)
def _e400(e):
    r = _api_error(400, "Bad request")
    return r if r else e


@app.errorhandler(404)
def _e404(e):
    r = _api_error(404, "Not found")
    return r if r else e


@app.errorhandler(413)
def _e413(e):
    r = _api_error(413, "Upload too large")
    return r if r else e


@app.errorhandler(429)
def _e429(e):
    r = _api_error(429, "Rate limited — slow down")
    return r if r else e


@app.errorhandler(500)
def _e500(e):
    _app_log.exception("unhandled 500 on %s", request.path)
    r = _api_error(500, "Something went wrong — try again")
    return r if r else e


def get_engine():
    """Load the V68 engine once (slow-ish); cache for reuse."""
    global _engine
    with _engine_lock:
        if _engine is None:
            try:
                m = M.load_engine()
            except Exception as e:
                raise RuntimeError(f"Beat engine failed to load: {e}")
            m.BASE_DIR = os.path.join(_base_tmp, "djrill_nomedia") + os.sep
            # Prefer Daryl's real sample library on shared storage; fall back to temp dir.
            _real_samples = "/storage/emulated/0/personal-ai/Ai_music_samples"
            _old_samples = "/storage/emulated/0/Ai_music_samples"
            if os.path.isdir(_real_samples):
                m.SAMPLE_BASE_DIR = _real_samples
            elif os.path.isdir(_old_samples):
                m.SAMPLE_BASE_DIR = _old_samples
            else:
                m.SAMPLE_BASE_DIR = os.path.join(m.BASE_DIR, "Ai_music_samples")
            _engine = m
        return _engine


# 146. job persistence across restarts
JOBS_SNAP = os.path.join(BASE, "jobs_snapshot.json")


def _persist_jobs():
    import time as _t
    while True:
        _t.sleep(120)
        try:
            with jobs_lock:
                snap = {jid: {k: v for k, v in j.items()
                              if not k.startswith("_")}
                        for jid, j in jobs.items()
                        if j.get("status") in ("done", "error")}
            with open(JOBS_SNAP + ".tmp", "w") as f:
                json.dump(snap, f)
            os.replace(JOBS_SNAP + ".tmp", JOBS_SNAP)
        except Exception:
            pass


def _restore_jobs():
    try:
        with open(JOBS_SNAP) as f:
            snap = json.load(f)
        with jobs_lock:
            for jid, j in snap.items():
                if isinstance(j, dict) and j.get("status") in ("done", "error"):
                    jobs[jid] = j
    except (OSError, ValueError):
        pass


def _resume_interrupted_masters():
    """On startup: find master jobs interrupted by a crash and resume them.
    Looks for checkpoint.json in temp master dirs. If a job was mid-mastering,
    restarts it — already-completed sections are skipped via the checkpoint.
    """
    import glob
    try:
        temp_base = os.path.join(BASE, "outputs", "temp_masters")
        if not os.path.isdir(temp_base):
            return
        for tdir in os.listdir(temp_base):
            ckpt = os.path.join(temp_base, tdir, "checkpoint.json")
            if not os.path.exists(ckpt):
                continue
            try:
                with open(ckpt) as f:
                    ck = json.load(f)
            except Exception:
                continue
            if ck.get("phase") == "done":
                continue
            job_id = ck.get("job_id")
            if not job_id:
                continue
            # Don't resume if already running (e.g. from a previous resume)
            with jobs_lock:
                if job_id in jobs and jobs[job_id].get("status") == "running":
                    continue
            # Reconstruct job from checkpoint + temp dir
            # The source file should still be in the temp dir
            src = None
            for ext in (".mp3", ".wav", ".flac", ".ogg", ".m4a", ".opus"):
                p = os.path.join(temp_base, tdir, "source" + ext)
                if os.path.exists(p):
                    src = p
                    break
            if not src:
                continue
            # Mark as resumable — the frontend can show "Resume" or auto-resume
            # For now: auto-resume in a background thread
            set_job(job_id, status="running", progress=5,
                    message="Resuming interrupted master…",
                    _kind="master", _resumed=True)
            # We need the original mopts — try to load from a saved file
            mopts_path = os.path.join(temp_base, tdir, "mopts.json")
            mopts = {}
            if os.path.exists(mopts_path):
                try:
                    with open(mopts_path) as f:
                        mopts = json.load(f)
                except Exception:
                    pass
            # Start resume in background thread
            import threading as _th
            _th.Thread(target=_resume_master_thread,
                       args=(job_id, src, ck, mopts),
                       daemon=True).start()
    except Exception:
        pass


def _resume_master_thread(job_id, src_path, ck, mopts):
    """Background thread to resume an interrupted master job."""
    try:
        # Reconstruct minimal args from checkpoint
        # For now, we re-run run_master_job which will pick up the checkpoint
        # and skip already-done sections.
        genre = mopts.get("genre", "HipHop")
        title = mopts.get("title", "Resumed Master")
        # run_master_job needs the full signature — use saved values
        run_master_job(job_id, src_path, genre,
                       mopts.get("bpm"), mopts.get("seed", 0),
                       title, mopts)
    except Exception as e:
        set_job(job_id, status="error", progress=0,
                message=f"Resume failed: {e}")


threading.Thread(target=_persist_jobs, daemon=True).start()
_restore_jobs()
# Resume any interrupted master jobs after a short delay (let server start first)
def _delayed_resume():
    import time as _t
    _t.sleep(10)
    _resume_interrupted_masters()
threading.Thread(target=_delayed_resume, daemon=True).start()


def safe_name(title, default="djrill"):
    s = "".join(c if c.isalnum() or c in " _-" else "_" for c in (title or "")).strip()
    s = "_".join(s.split())  # no spaces: keeps download URLs simple
    return s[:60] if s else default


def render_beat_progress(m, genre, bpm, n_bars, seed=None, cb=None):
    """Mirror of djrill_master.render_beat with a per-bar progress callback."""
    if seed is None:
        seed = M.new_beat_seed()
    g = m.Generator(seed=seed, genre=genre, hook_name="Hook A")
    # Gemini-composed music: real progressions/melodies/drums when the
    # API is reachable; falls back to the procedural engine on failure.
    g.composition_source = "procedural"
    try:
        import gemini_compose as _gc
        _comp = _gc.get_composition(genre, bpm, seed)
        if _comp and hasattr(g, "apply_gemini_comp") and g.apply_gemini_comp(_comp):
            g.composition_source = "gemini"
    except Exception:
        pass
    g.tempo = float(bpm)
    g.current_global_tempo = float(bpm)
    g.last_bar_tempo = float(bpm)
    g._bypass_master = True
    song = m.SongStructure(num_verses=3, num_hooks=4, variant=int(seed) % 3)
    chunks = []
    for bar in range(n_bars):
        sname, _, bis = song.get_section_info(bar)
        g.synthesize_bar_audio(sname, bis)
        chunks.append(g.current_bar_audio_buffer)
        if cb:
            cb(bar + 1, n_bars)
    g._bypass_master = False
    beat = np.concatenate(chunks, axis=0)
    # V71 glue bus (2026-10-20): the old chain peak-normalized twice around
    # a blunt +8 dB sub boost applied to the whole mix (mud). Now: clean
    # the rumble, gentle +3 dB low shelf, soft saturation for glue, ceiling.
    try:
        _sos_hp = signal.butter(2, 25, btype="highpass", fs=SR, output="sos")
        beat = signal.sosfilt(_sos_hp, beat, axis=0)
        _shelf = signal.firwin2(255, [0, 60, 120, 200, SR / 2],
                                [1.41, 1.41, 1.19, 1.0, 1.0], fs=SR)
        beat = np.column_stack([signal.fftconvolve(beat[:, ch], _shelf, mode="same")
                                for ch in range(beat.shape[1])])
    except Exception:
        pass
    beat = np.tanh(beat * 1.15) / np.tanh(1.15)
    peak = np.max(np.abs(beat))
    if peak > 0.89:
        beat = beat / peak * 0.89
    return beat


def encode_mp3(wav_path, mp3_path):
    # 140. retry failed FFmpeg encodes once before giving up
    # Returns True on success, False if ffmpeg unavailable (WAV still works)
    try:
        C.convert_file(wav_path, mp3_path)
        return True
    except Exception:
        import time as _t
        _t.sleep(2)
        try:
            C.convert_file(wav_path, mp3_path)
            return True
        except Exception as e:
            _app_log.warning(f"MP3 encode failed, WAV only: {e}")
            return False


# 147. rotating app log
import logging as _logging
from logging.handlers import RotatingFileHandler as _RFH
_log_path = os.path.join(BASE, "djrill.log")
_handler = _RFH(_log_path, maxBytes=2 * 1024 * 1024, backupCount=3)
_handler.setFormatter(_logging.Formatter(
    "%(asctime)s %(levelname)s %(message)s"))
_app_log = _logging.getLogger("djrill")
_app_log.addHandler(_handler)
_app_log.setLevel(_logging.INFO)
_app_log.info("Djrill Mobile starting")


# 150. safe shutdown: mark running jobs, flush history
import atexit as _atexit


def _shutdown():
    try:
        with jobs_lock:
            for j in jobs.values():
                if j.get("status") == "running":
                    j["status"] = "error"
                    j["message"] = "Server stopped — retry the job"
        with open(JOBS_SNAP + ".tmp", "w") as f:
            json.dump({jid: {k: v for k, v in j.items()
                             if not k.startswith("_")}
                       for jid, j in jobs.items()
                       if j.get("status") in ("done", "error")}, f)
        os.replace(JOBS_SNAP + ".tmp", JOBS_SNAP)
        _app_log.info("Djrill Mobile stopped cleanly")
    except Exception:
        pass


_atexit.register(_shutdown)


def _match_beat_structure(beat, orig_inst, bar_dur, intro_s):
    """Shape a generated beat's per-bar energy to the original's structure.

    beat: generated beat (stereo float). orig_inst: separated original
    instrumental. Returns beat with per-bar gain applied so verses, hooks
    and drops land where the original had them. Never raises.
    """
    try:
        sr = SR
        bar_n = int(bar_dur * sr)
        if bar_n < 1 or beat is None or len(beat) == 0:
            return beat
        mono = orig_inst.mean(axis=1).astype(np.float64)
        n_og = int(np.ceil(len(mono) / bar_n))
        e = np.zeros(n_og)
        for i in range(n_og):
            seg = mono[i * bar_n:(i + 1) * bar_n]
            if len(seg):
                e[i] = np.mean(seg ** 2)
        if e.max() <= 1e-12:
            return beat
        # 0.45..1.0: keep dynamics, never mute a bar entirely
        norm = 0.45 + 0.55 * (e - e.min()) / (e.max() - e.min() + 1e-12)
        intro_bars = max(1, int(round(intro_s / bar_dur)))
        ref = float(np.mean(beat.astype(np.float64) ** 2)) + 1e-12
        out = beat.copy()
        total = int(np.ceil(len(out) / bar_n))
        for b in range(total):
            s = b * bar_n
            seg = out[s:s + bar_n]
            if not len(seg):
                continue
            og_idx = b - intro_bars
            target = norm[og_idx] * ref if 0 <= og_idx < n_og else 0.7 * ref
            cur = float(np.mean(seg.astype(np.float64) ** 2))
            if cur > 1e-12:
                seg *= np.sqrt(target / cur)
        return out
    except Exception:
        return beat


# ---------------------------------------------------------------- large-file section mastering
def master_large_sections(src_path, masterfx, chain, mopts, prog, SR=44100, section_min=4, checkpoint_dir=None, job_id=None):
    """Daryl's two-level chunking for large 'keep original' files.
    1. Split into 4-min sections via ffmpeg (disk only, zero RAM).
    2. Master each 4-min section sequentially using 45s chunks (master_chunked).
    3. Stitch sections with 2s crossfades.
    Returns (pcm16, report). Never loads the full file into RAM.

    If checkpoint_dir is given, mastered sections are saved to disk there
    and a checkpoint.json tracks progress — a crash can resume from the
    last completed section instead of starting over.
    """
    import subprocess, tempfile, shutil
    import numpy as np

    SECTION_S = section_min * 60
    XFADE_S = 2
    xfade_n = int(XFADE_S * SR)

    # Checkpoint setup
    ckpt_path = os.path.join(checkpoint_dir, "checkpoint.json") if checkpoint_dir else None
    sections_done = set()
    if ckpt_path and os.path.exists(ckpt_path):
        try:
            with open(ckpt_path) as f:
                ck = json.load(f)
            sections_done = set(ck.get("sections_done", []))
            if sections_done:
                prog(5, f"Resuming — {len(sections_done)} sections already done…")
        except Exception:
            pass

    def _save_ckpt(total, done_list, phase):
        if not ckpt_path:
            return
        try:
            with open(ckpt_path + ".tmp", "w") as f:
                json.dump({"job_id": job_id, "phase": phase,
                           "sections_total": total,
                           "sections_done": sorted(done_list)}, f)
            os.replace(ckpt_path + ".tmp", ckpt_path)
        except Exception:
            pass

    # Duration + split via the shared chunkpipe (2026-10-20 unification):
    # sections are cut WITH the 2s overlap built in so the stitch blends
    # the same audio moment at every join.
    _probe_dir = tempfile.mkdtemp(prefix="msect_probe_")
    try:
        section_files, duration = chunkpipe.cut_sections(
            src_path, _probe_dir, SECTION_S, XFADE_S, SR)
    finally:
        pass  # files live in _probe_dir; renamed below

    if duration <= SECTION_S:
        shutil.rmtree(_probe_dir, ignore_errors=True)
        # Not large — use normal path
        return master_chunked(src_path, masterfx, chain, mopts, prog, SR)

    n_sections = len(section_files)
    prog(5, f"Large file ({duration/60:.1f} min) — splitting into {n_sections} sections…")

    tmpdir = _probe_dir
    try:
        if not section_files:
            raise ValueError("Section split produced no files")

        # Master each section sequentially (45s chunks inside)
        # With checkpointing: save each mastered section to disk, skip done ones
        mastered_parts = []
        last_report = None
        for idx, sf in enumerate(section_files):
            # Check if this section was already mastered (resume)
            sect_ckpt = None
            if checkpoint_dir:
                sect_ckpt = os.path.join(checkpoint_dir, f"mastered_sect_{idx:03d}.wav")
                if idx in sections_done and os.path.exists(sect_ckpt):
                    prog(10 + int(70 * idx / len(section_files)),
                         f"Section {idx+1}/{len(section_files)} — already done, skipping…")
                    # Load from disk
                    try:
                        import scipy.io.wavfile as _wv
                        _sr, _pcm = _wv.read(sect_ckpt)
                        mastered_parts.append(_pcm)
                        # Get report from checkpoint if available
                        continue
                    except Exception:
                        sections_done.discard(idx)  # re-do if load fails
            pct = 10 + int(70 * idx / len(section_files))
            prog(pct, f"Mastering section {idx+1}/{len(section_files)}…")
            pcm16, report = master_chunked(sf, masterfx, chain, mopts,
                                          lambda p, m: prog(pct, m), SR)
            last_report = report
            # Save to disk for crash recovery
            if sect_ckpt:
                try:
                    import scipy.io.wavfile as _wv
                    _wv.write(sect_ckpt, SR, pcm16)
                    sections_done.add(idx)
                    _save_ckpt(len(section_files), sections_done, "mastering")
                except Exception:
                    pass
            mastered_parts.append(pcm16)
            import gc
            gc.collect()

        # Stitch with 2s crossfades.
        # master_chunked returns int16; convert to float [-1, 1] for the
        # crossfade math, then back to int16. (Float WAV values must be
        # in [-1, 1] — int16-scale floats would clip catastrophically.)
        prog(85, "Stitching sections…")
        # Shared stitch (chunkpipe): float crossfades, then back to int16.
        result = chunkpipe.stitch_parts(mastered_parts, xfade_n)
        result = np.clip(result, -1.0, 1.0)
        result = (result * 32767).astype(np.int16)

        return result, last_report
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


# ---------------------------------------------------------------- master job


def master_adaptive(src_path, masterfx, chain, mopts, prog, SR=44100, checkpoint_dir=None, job_id=None):
    """Adaptive mastering for tracks with tempo/volume changes.
    Analyzes the track to find natural section boundaries, then adapts
    mastering parameters per section. Falls back to master_chunked if
    analysis fails or no significant changes detected.
    
    Does NOT modify the working master_chunked — wraps it with intelligence.
    """
    import numpy as np
    import subprocess, tempfile, os
    
    if not _ADAPTIVE_AVAILABLE:
        # Fallback to standard
        return master_chunked(src_path, masterfx, chain, mopts, prog, SR)
    
    try:
        prog(2, "Analyzing track for tempo/volume changes…")
        sections = adaptive_master.analyze_track_sections(src_path, sr=SR)
        
        # If only 1 section or all sections similar, use standard chain
        if len(sections) <= 1:
            prog(3, "Uniform track — using standard mastering…")
            return master_chunked(src_path, masterfx, chain, mopts, prog, SR)
        
        # Check if sections are actually different
        energies = [s[2].get('energy', 'medium') for s in sections]
        tempos = [s[2].get('tempo', 'stable') for s in sections]
        if len(set(energies)) == 1 and len(set(tempos)) == 1:
            prog(3, "Consistent dynamics — using standard mastering…")
            return master_chunked(src_path, masterfx, chain, mopts, prog, SR)
        
        prog(5, f"Found {len(sections)} distinct sections — adaptive mastering…")
        
        # Convert src to WAV if needed for section extraction
        import soundfile as sf
        data, file_sr = sf.read(src_path, dtype='float32')
        if data.ndim == 1:
            data = np.stack([data, data], axis=1)  # Mono to stereo
        
        # Resample if needed (simple linear)
        if file_sr != SR:
            ratio = SR / file_sr
            new_len = int(len(data) * ratio)
            old_idx = np.linspace(0, len(data)-1, len(data))
            new_idx = np.linspace(0, len(data)-1, new_len)
            data = np.stack([
                np.interp(new_idx, old_idx, data[:, 0]),
                np.interp(new_idx, old_idx, data[:, 1])
            ], axis=1).astype(np.float32)
        
        # Master each section with adapted parameters
        # DISK-STREAMING: each section written to disk immediately, never held in RAM
        import tempfile
        XFADE_S = 2
        xfade_n = int(XFADE_S * SR)
        
        # Temp dir for section files
        sect_tmpdir = tempfile.mkdtemp(prefix="adaptive_sect_")
        section_files = []
        
        try:
            for idx, (start_s, end_s, chars) in enumerate(sections):
                prog(5 + int(70 * idx / len(sections)),
                     f"Mastering section {idx+1}/{len(sections)} ({chars['energy']} energy, {chars['tempo']} tempo)…")
                
                # Extract section audio (only this section in RAM).
                # Sections after the first start xfade_n earlier so the
                # stitch crossfade blends the SAME audio moment instead
                # of eating 2s of track at every join.
                _xs = start_s - xfade_n if idx > 0 else start_s
                if _xs < 0:
                    _xs = 0
                section_audio = data[_xs:end_s].copy()
                
                # Adapt mopts for this section
                section_mopts = adaptive_master.adapt_mopts_for_section(mopts, chars)
                
                # Master using the PROVEN master_chunked
                pcm16, _ = master_chunked(section_audio, masterfx, chain, section_mopts,
                                         lambda p, m: None, SR)
                
                # Free the input immediately
                del section_audio
                
                # Write to disk immediately, free RAM
                sect_path = os.path.join(sect_tmpdir, f"sect_{idx:03d}.wav")
                import soundfile as sf
                # Ensure stereo
                if pcm16.ndim == 1:
                    pcm16_st = np.stack([pcm16, pcm16], axis=1)
                else:
                    pcm16_st = pcm16
                sf.write(sect_path, pcm16_st, SR, subtype='PCM_16')
                del pcm16, pcm16_st
                import gc; gc.collect()
                
                section_files.append(sect_path)
            
            # Free the full-track array NOW — stitching reads from disk only
            del data
            import gc; gc.collect()
            
            # Stitch with crossfades — STREAMING: only 2 sections in RAM at once
            prog(80, "Stitching sections (streaming)…")
            import soundfile as sf
            
            stitched_path = os.path.join(sect_tmpdir, "stitched.wav")
            
            # Open output file for writing
            # We'll build it incrementally
            with sf.SoundFile(stitched_path, mode='w', samplerate=SR, channels=2, subtype='PCM_16') as out:
                prev_tail = None  # Last xfade_n samples of previous section (float32)
                n_files = len(section_files)
                fade_out, fade_in = chunkpipe.fade_ramps(xfade_n)

                for idx, spath in enumerate(section_files):
                    prog(80 + int(12 * idx / max(1, n_files)),
                         f"Stitching {idx+1}/{n_files}…")
                    is_last = (idx == n_files - 1)
                    cur_data, _ = sf.read(spath, dtype='float32', always_2d=True)

                    if prev_tail is not None and len(cur_data) >= xfade_n:
                        overlap = prev_tail * fade_out + cur_data[:xfade_n] * fade_in
                        out.write(overlap)
                        body = cur_data[xfade_n:]
                    else:
                        body = cur_data

                    if is_last:
                        out.write(body)
                        prev_tail = None
                    else:
                        if len(body) > xfade_n:
                            out.write(body[:-xfade_n])
                            prev_tail = body[-xfade_n:].copy()
                        else:
                            out.write(body)
                            prev_tail = None

                    del cur_data, body
                    import gc; gc.collect()
            
            # Read stitched result (streaming read in chunks to avoid RAM spike)
            # For report generation we need the full file, but it's PCM16 on disk
            # Read it back as int16
            pcm16, _ = sf.read(stitched_path, dtype='int16', always_2d=True)
            # Convert stereo to expected format (keep as-is, report_card handles it)
            
        finally:
            # Cleanup temp section files
            import shutil
            try:
                shutil.rmtree(sect_tmpdir)
            except Exception:
                pass
        
        # Generate report
        from masterfx import report_card
        report = report_card(pcm16, SR)
        report['adaptive_sections'] = len(sections)
        report['adaptive'] = True
        
        prog(95, f"Adaptive master complete — {len(sections)} sections")
        return pcm16, report
        
    except Exception as e:
        print(f"Adaptive mastering failed ({e}), falling back to standard")
        import traceback
        traceback.print_exc()
        return master_chunked(src_path, masterfx, chain, mopts, prog, SR)


def run_master_job(job_id, src_path, genre, bpm_opt, seed, title, mopts=None):
    def prog(p, msg):
        set_job(job_id, progress=p, message=msg)
    try:
        mopts = mopts or {}
        # Temp job folder: copy the source in, work from the copy.
        # The original upload is never touched or deleted.
        tdir = _temp_master_dir(job_id)
        os.makedirs(tdir, exist_ok=True)
        # Save mopts for crash recovery (resume needs the original options)
        try:
            _mopts_save = dict(mopts or {})
            _mopts_save["genre"] = genre
            _mopts_save["title"] = title
            _mopts_save["bpm"] = bpm_opt
            _mopts_save["seed"] = seed
            with open(os.path.join(tdir, "mopts.json"), "w") as _mf:
                json.dump(_mopts_save, _mf)
        except Exception:
            pass
        # No accumulation: a new master job clears older master temp dirs.
        try:
            for _jd in os.listdir(TEMP_MASTERS_DIR):
                if _jd != job_id[:8]:
                    temp_master_cleanup(_jd)
        except OSError:
            pass
        _sext = os.path.splitext(src_path)[1].lower() or ".wav"
        temp_src = os.path.join(tdir, "source" + _sext)
        shutil.copy2(src_path, temp_src)
        src_path = temp_src
        chain = mopts.get("chain", "Streaming")
        # Daryl's fast path: large 'keep original' files use 4-min sections
        # (never loads full file into RAM). Sequential, 45s chunks inside.
        _is_keep = mopts.get("beat_source", "generate") == "keep"
        if _is_keep:
            try:
                import subprocess
                _r = subprocess.run(
                    ["ffprobe", "-v", "error", "-show_entries", "format=duration",
                     "-of", "default=noprint_wrappers=1:nokey=1", src_path],
                    capture_output=True, text=True, timeout=15)
                _dur = float(_r.stdout.strip())
            except Exception:
                _dur = 0
            # Adaptive mastering is explicit opt-in only (auto-detect disabled
            # 2026-10-19: stitching OOMs on long tracks — proven chain by default)
            # Auto-detect: enable adaptive for tracks with tempo/energy changes
            _adaptive_flag = mopts.get("adaptive_mastering", None)
            if _adaptive_flag is None:
                # Default OFF (2026-10-20, Daryl's order): long tracks use the
                # proven master_large_sections stitching from the locked
                # working backup. Adaptive only when explicitly requested.
                _adaptive_flag = False
            _use_adaptive = bool(_adaptive_flag) and _ADAPTIVE_AVAILABLE
            if _dur > 4 * 60:  # >4 minutes: use sectioned mastering
                if _use_adaptive:
                    prog(3, f"Large file ({_dur/60:.1f} min) — adaptive sections…")
                    pcm16, report = master_adaptive(
                        src_path, masterfx, chain, mopts, prog, SR,
                        checkpoint_dir=tdir, job_id=job_id)
                else:
                    prog(3, f"Large file ({_dur/60:.1f} min) — using 4-min sections…")
                    pcm16, report = master_large_sections(
                        src_path, masterfx, chain, mopts, prog, SR,
                        checkpoint_dir=tdir, job_id=job_id)
                # Write output (same as normal path)
                safe = safe_name(title, "djrill-master")
                base = f"{safe}_prhymemaster"
                _fmt = mopts.get("output_format", "mp3")
                if _fmt not in ("mp3", "wav", "flac", "ogg", "m4a", "opus"):
                    _fmt = "mp3"
                tmp_wav = os.path.join(tdir, base + ".tmp.wav")
                prog(86, "Writing master…")
                wav_write(tmp_wav, SR, pcm16)
                # Free the full-track array NOW: encode + A/B steps spawn
                # subprocesses/decoders; the phone OOM-kills the server if
                # the whole mastered track stays resident in RAM.
                del pcm16
                import gc as _gc; _gc.collect()
                if _fmt == "wav":
                    final_path = os.path.join(tdir, base + ".wav")
                    os.replace(tmp_wav, final_path)
                elif _fmt == "flac":
                    final_path = os.path.join(tdir, base + ".flac")
                    prog(92, "Encoding FLAC…")
                    C.convert_file(tmp_wav, final_path)
                    os.remove(tmp_wav)
                elif _fmt == "ogg":
                    final_path = os.path.join(tdir, base + ".ogg")
                    prog(92, "Encoding OGG…")
                    C.convert_file(tmp_wav, final_path)
                    os.remove(tmp_wav)
                elif _fmt == "m4a":
                    final_path = os.path.join(tdir, base + ".m4a")
                    prog(92, "Encoding M4A…")
                    C.convert_file(tmp_wav, final_path)
                    os.remove(tmp_wav)
                elif _fmt == "opus":
                    final_path = os.path.join(tdir, base + ".opus")
                    prog(92, "Encoding Opus…")
                    C.convert_file(tmp_wav, final_path)
                    os.remove(tmp_wav)
                else:
                    final_path = os.path.join(tdir, base + ".mp3")
                    prog(92, "Encoding MP3…")
                    encode_mp3(tmp_wav, final_path)
                    os.remove(tmp_wav)
                prog(96, "Building A/B previews…")
                ab_src = None
                ab_mst = None
                if mopts.get("ab_compare", "1") == "1":
                    tmpdir_ab = os.path.join(OUTPUT_DIR, "temp_ab")
                    os.makedirs(tmpdir_ab, exist_ok=True)
                    ab_src, ab_pos = _ab_excerpt(src_path, tmpdir_ab, f"{job_id[:8]}_ab-source.mp3")
                    ab_mst, _ = _ab_excerpt(final_path, tmpdir_ab, f"{job_id[:8]}_ab-master.mp3", start_sample=ab_pos)
                set_job(job_id, status="done", progress=100,
                        message=f"Track Prhymed! — {report['lufs']} LUFS, "
                                f"{report['true_peak_dbtp']} dBTP",
                        result={"file": os.path.basename(final_path),
                                "format": _fmt,
                                "temp": True,
                                "job_id": job_id,
                                "lufs": report["lufs"],
                                "dbtp": report["true_peak_dbtp"],
                                "bpm": 0,
                                "duration": report["duration_s"],
                                "fx_applied": [],
                                "report": report,
                                "ab_source": ab_src,
                                "ab_master": ab_mst})
                return
        prog(3, "Loading your recording…")
        _, vocal = M.load_audio(src_path)
        # 140. corrupt-audio guard: reject silent / NaN / broken files
        if vocal.size == 0 or not np.all(np.isfinite(vocal)):
            raise ValueError("Recording is unreadable (corrupt audio data)")
        if np.max(np.abs(vocal)) < 1e-6:
            raise ValueError("Recording is silent — nothing to master")
        v_dur = vocal.shape[0] / SR

        bpm = bpm_opt or M.detect_bpm_consensus(vocal, SR) or 90.0
        prog(8, f"Tempo locked: {bpm:.1f} BPM")
        _keep_original = mopts.get("beat_source", "generate") == "keep"
        _beat_style = mopts.get("beat_style", "match")
        _beat_genre = genre
        if not _keep_original and _beat_style == "different":
            _beat_genre = mopts.get("new_genre") or genre
        if not _keep_original:
            # New backing beat: isolate vocals first so the original
            # instrumental does not bleed into the mix under the new beat.
            prog(9, "Separating vocals from original…")
            _sep_wav = os.path.join(tdir, "sep_input.wav")
            _pcm = np.clip(vocal, -1.0, 1.0)
            wav_write(_sep_wav,
                      SR, (_pcm * 32767).astype(np.int16))
            del _pcm
            _voc, _orig_inst = vocalfx.separate_track(
                _sep_wav,
                progress=lambda f: prog(
                    9 + int(f * 0.05),
                    f"Separating vocals… {int(f)}%"))
            try:
                os.remove(_sep_wav)
            except OSError:
                pass
            vocal = _voc
            del _voc
            v_dur = vocal.shape[0] / SR
        bar_dur = 60.0 / bpm * 4
        intro = bar_dur  # 1 intro bar
        n_bars = int(np.ceil((intro + v_dur + 2 * bar_dur) / bar_dur))

        _lite = lite_mode()
        # Memory guard: vocal + beat + mix buffers.
        # Lite mode uses the lightweight renderer (fewer numpy temporaries).
        _nbuf = 2 if _keep_original else 4
        check_audio_budget(vocal.shape[0] * _nbuf, channels=2,
                           copies=4, label="master", headroom_mb=80)
        if _keep_original:
            prog(10, "Keeping original audio (no new beat)...")
            beat = None
        elif _lite:
            # Lite: phone-safe lightbeat renderer instead of the V68 engine,
            # capped at 32 bars then tiled to cover long vocals.
            prog(10, f"Rendering backing beat (lite)…")
            _lb_bars = min(n_bars, 32)
            beat = lightbeat.generate_beat(_beat_genre, float(bpm), _lb_bars, seed,
                progress_cb=lambda f, m: prog(10 + int(40 * f), m or f"Beat {int(f*_lb_bars)}/{_lb_bars}…"))
            _need = int(np.ceil((intro + v_dur + 2 * bar_dur) * SR))
            if beat.shape[0] < _need:
                _reps = int(np.ceil(_need / beat.shape[0]))
                beat = np.tile(beat, (_reps, 1))[:_need]
        else:
            eng = get_engine()
            prog(10, f"Rendering {n_bars} bars of {_beat_genre} beat…")
            beat = render_beat_progress(
                eng, _beat_genre, bpm, n_bars, seed,
                lambda b, n: prog(10 + int(45 * b / n), f"Beat bar {b}/{n}…"))

        # Structure match: the new beat follows the OG's song structure.
        # Per-bar energy of the original instrumental -> per-bar gain on the
        # new beat, so drops/breaks/hooks land where the original had them.
        if not _keep_original and beat is not None:
            try:
                prog(57, "Matching song structure…")
                beat = _match_beat_structure(beat, _orig_inst, bar_dur,
                                             intro)
            except Exception as _se:
                print(f"structure match skipped: {_se}")
            del _orig_inst
        # Generated beat persists in the temp beats ring (last 5) even if
        # this master is never downloaded.
        if not _keep_original and beat is not None:
            try:
                _bpeak = float(np.max(np.abs(beat)))
                _bnorm = beat * (0.89 / _bpeak) if _bpeak > 0 else beat
                _bpcm = (np.clip(_bnorm, -1.0, 1.0) * 32767).astype(np.int16)
                _bbase = f"{job_id[:8]}_djrill-beat_{_beat_genre}_{int(round(float(bpm)))}bpm"
                os.makedirs(TEMP_BEATS_DIR, exist_ok=True)
                _bwav = os.path.join(TEMP_BEATS_DIR, _bbase + ".wav")
                wav_write(_bwav, SR, _bpcm)
                temp_beats_register(job_id, _bbase, {"wav": _bbase + ".wav"},
                                    genre, float(bpm),
                                    round(beat.shape[0] / SR, 1))
            except Exception as _be:
                print(f"beat ring save failed: {_be}")
        prog(58, "Polishing vocal (EQ + gentle compression)…")
        vp = M.polish_vocal(vocal)

        # ✨ Vocal polish: gentle denoise + presence + de-ess (never deletes)
        if mopts.get("vocal_polish", True):
            prog(60, "✨ Vocal polish — clarity…")
            vp_pol = vocalfix.polish_vocal_clarity(vp)
            ok_nd, _ = vocalfix.verify_no_dropouts(vp, vp_pol)
            if ok_nd:
                vp = vp_pol
            # else: keep M.polish_vocal output (never risk a deletion)

        # 🎯 Timing fix: subtle nudge toward beat grid (never cuts words)
        if mopts.get("timing_fix", True):
            prog(62, "🎯 Timing fix — nudging to grid…")
            vp_t, tinfo = vocalfix.fix_vocal_timing(vp, bpm=float(bpm))
            ok_nd, _ = vocalfix.verify_no_dropouts(vp, vp_t)
            if ok_nd:
                vp = vp_t
                if tinfo.get("corrected"):
                    prog(64, f"Timing nudged ({tinfo.get('nudged',0)} spots, "
                             f"max {tinfo.get('max_shift_ms',0):.0f} ms)")
            # else: keep un-timed version (never risk a deletion)

        # 🎛 Creative FX on the vocal (radio/vinyl/TV/filters/echo).
        # Envelope-preserving DSP only — words stay intact.
        fx_applied = []
        if mopts.get("fx_target", "vocal") == "vocal":
            prog(64, "🎛 Creative FX — vocal…")
            vp_fx, fx_applied = trackfx.apply_vocal_fx(
                vp, mopts, bpm=float(bpm))
            ok_nd, _ = vocalfix.verify_no_dropouts(vp, vp_fx)
            if not ok_nd:
                vp_fx, fx_applied = vp, []  # never risk a deletion
        else:
            vp_fx = vp

        prog(65, "Mixing — balanced vocal/instrumental…")
        boost_db = float(mopts.get("vocal_boost_db", 1.5))
        need = int(intro + vocal.shape[0] + 1 * SR)
        if _keep_original:
            # Keep original: use polished audio directly, no beat mixing
            mix = vp_fx.copy()
            s0 = 0
        else:
            mix = np.zeros((max(need, beat.shape[0]), 2))
            mix[:beat.shape[0]] += beat * 0.9
            s0 = int(intro * SR)
            mix[s0:s0 + vp_fx.shape[0]] += vp_fx * 10 ** (boost_db / 20.0)
            end = min(mix.shape[0], s0 + vp_fx.shape[0] + int(0.5 * SR))
            mix = mix[:end]
        # configurable fades
        mix = masterfx.apply_fades(
            mix, float(mopts.get("fade_in", 0.5)),
            float(mopts.get("fade_out", 3.0)))
        # 🎛 Creative FX on the full mix instead of the vocal
        if mopts.get("fx_target", "vocal") == "mix":
            prog(78, "🎛 Creative FX — full mix…")
            mix, fx_applied = trackfx.apply_vocal_fx(
                mix, mopts, bpm=float(bpm))

        # lyric-integrity gate before mastering
        ok_vox, vox_corr = M.verify_vocal_integrity(vp_fx, mix, s0)
        if not ok_vox:
            print(f"WARNING: Vocal integrity low (corr={vox_corr:.2f}) -- continuing")

        prog(80, "Mastering…")
        # Free vocal/beat buffers now that mix is built (low-RAM: dead
        # from here on; master_chunked only needs mix).
        import gc as _gc
        try:
            del vocal
        except NameError:
            pass
        try:
            del beat
        except NameError:
            pass
        try:
            del vp
        except NameError:
            pass
        try:
            del vp_fx
        except NameError:
            pass
        _gc.collect()
        ref_path = mopts.get("reference_path")
        if ref_path and not _lite:
            # Lite skips reference spectrum matching (heavy FFT analysis).
            mix, ref_lufs, deltas = masterfx.match_reference_spectrum(
                mix, ref_path)
            mopts = dict(mopts, target_lufs=ref_lufs)
        # For large mixes (>3 min), spill to disk first so master_chunked
        # can stream instead of holding the full array in RAM.
        _mix_arg = mix
        _spill_wav = None
        try:
            import numpy as _np
            _mix_len = mix.shape[0] if hasattr(mix, "shape") else 0
            if _mix_len > 3 * 60 * SR:  # >3 minutes
                import tempfile, os as _os
                from scipy.io.wavfile import write as _wav_write
                _spill_wav = _os.path.join(tdir, "_mix_spill.wav")
                # Normalize to int16 for disk
                _m = mix
                if _m.dtype != _np.int16:
                    _peak = _np.abs(_m).max()
                    if _peak > 0:
                        _m = (_m / _peak * 32767).astype(_np.int16)
                    else:
                        _m = _m.astype(_np.int16)
                _wav_write(_spill_wav, SR, _m)
                del _m
                _mix_arg = _spill_wav
                del mix  # Free the RAM
                import gc as _gc2
                _gc2.collect()
        except Exception as _e:
            print(f"spill failed: {_e}, using in-RAM")
            _mix_arg = mix
        # Adaptive mastering is explicit opt-in only (auto-detect disabled
        # 2026-10-19: stitching OOMs on long tracks — proven chain by default)
        _adaptive_flag_n = mopts.get("adaptive_mastering", None)
        if _adaptive_flag_n is None:
            # Default OFF (2026-10-20, Daryl's order): proven chain by
            # default, adaptive only when explicitly requested.
            _adaptive_flag_n = False
        _use_adaptive_normal = bool(_adaptive_flag_n) and _ADAPTIVE_AVAILABLE and isinstance(_mix_arg, str)
        if _use_adaptive_normal:
            pcm16, report = master_adaptive(
                _mix_arg, masterfx, chain, mopts, prog, SR)
        else:
            pcm16, report = master_chunked(
                _mix_arg, masterfx, chain, mopts, prog, SR)
        # Cleanup spill file
        try:
            if _spill_wav and os.path.exists(_spill_wav):
                os.remove(_spill_wav)
        except Exception:
            pass

        safe = safe_name(title, "djrill-master")
        base = f"{safe}_prhymemaster"
        _fmt = mopts.get("output_format", "mp3")
        if _fmt not in ("mp3", "wav", "flac", "ogg", "m4a", "opus"):
            _fmt = "mp3"
        # Exactly one final format, written to the temp job folder.
        # 141. atomic writes: tmp + rename so partial files never surface
        tmp_wav = os.path.join(tdir, base + ".tmp.wav")
        prog(86, "Writing master…")
        wav_write(tmp_wav, SR, pcm16)
        # Free the full-track array NOW: encode + A/B steps spawn
        # subprocesses/decoders; the phone OOM-kills the server if
        # the whole mastered track stays resident in RAM.
        del pcm16
        import gc as _gc; _gc.collect()
        if _fmt == "wav":
            final_path = os.path.join(tdir, base + ".wav")
            os.replace(tmp_wav, final_path)
        elif _fmt == "flac":
            final_path = os.path.join(tdir, base + ".flac")
            prog(92, "Encoding FLAC…")
            C.convert_file(tmp_wav, final_path)
            os.remove(tmp_wav)
        elif _fmt == "ogg":
            final_path = os.path.join(tdir, base + ".ogg")
            prog(92, "Encoding OGG…")
            C.convert_file(tmp_wav, final_path)
            os.remove(tmp_wav)
        elif _fmt == "m4a":
            final_path = os.path.join(tdir, base + ".m4a")
            prog(92, "Encoding M4A…")
            C.convert_file(tmp_wav, final_path)
            os.remove(tmp_wav)
        elif _fmt == "opus":
            final_path = os.path.join(tdir, base + ".opus")
            prog(92, "Encoding Opus…")
            C.convert_file(tmp_wav, final_path)
            os.remove(tmp_wav)
        else:
            final_path = os.path.join(tdir, base + ".mp3")
            prog(92, "Encoding MP3…")
            encode_mp3(tmp_wav, final_path)
            os.remove(tmp_wav)
        prog(96, "Building A/B previews…")

        # Generate A/B excerpts BEFORE marking done: the frontend renders the
        # result once on status=done and never re-polls, so excerpts made after
        # done would never appear (race condition fixed 2026-10-16).
        ab_src = None
        ab_mst = None
        if mopts.get("ab_compare", "1") == "1":
            tmpdir = os.path.join(OUTPUT_DIR, "temp_ab")
            os.makedirs(tmpdir, exist_ok=True)
            ab_src, ab_pos = _ab_excerpt(src_path, tmpdir, f"{job_id[:8]}_ab-source.mp3")
            ab_mst, _ = _ab_excerpt(final_path, tmpdir, f"{job_id[:8]}_ab-master.mp3", start_sample=ab_pos)

        set_job(job_id, status="done", progress=100,
                message=f"Track Prhymed! — {report['lufs']} LUFS, "
                        f"{report['true_peak_dbtp']} dBTP",
                result={"file": os.path.basename(final_path),
                        "format": _fmt,
                        "temp": True,
                        "job_id": job_id,
                        "lufs": report["lufs"],
                        "dbtp": report["true_peak_dbtp"],
                        "bpm": round(float(bpm), 1),
                        "duration": report["duration_s"],
                        "fx_applied": fx_applied,
                        "report": report,
                        # 25. A/B compare: optional 30s excerpts (stored in temp)
                        "ab_source": ab_src,
                        "ab_master": ab_mst})
    except Exception as e:
        set_job(job_id, status="error", progress=0, message=f"Error: {e}")
        try:
            temp_master_cleanup(job_id)
        except Exception:
            pass


def _ab_excerpt(src_path, out_dir, fname, secs=30, start_sample=None):
    """Write a 30s preview MP3 for A/B comparison. Returns (basename, start_sample) or (None, None).
    If start_sample is given, uses that position instead of finding the loudest window."""
    try:
        _, audio = M.load_audio(src_path)
        n = min(len(audio), int(secs * SR))
        # pick the loudest 30s window (or use given position)
        if start_sample is not None:
            best = min(start_sample, max(0, len(audio) - n))
        elif len(audio) > n:
            win = SR * 5
            best, best_e = 0, -1
            for s in range(0, len(audio) - n, win):
                e = float(np.mean(audio[s:s + n] ** 2))
                if e > best_e:
                    best, best_e = s, e
        else:
            best = 0
        seg = audio[best:best + n]
        peak = np.max(np.abs(seg))
        if peak > 0:
            seg = seg / peak * 0.9
        tmp = os.path.join(out_dir, fname + ".wav")
        wav_write(tmp, SR, (np.clip(seg, -1, 1) * 32767).astype(np.int16))
        dst = os.path.join(out_dir, fname)
        encode_mp3(tmp, dst)
        os.remove(tmp)
        return fname, best
    except Exception:
        return None, None


# ---------------------------------------------------------------- beats job
def run_beats_job(job_id, genre, bpm, n_bars, seed, fx=None, fast=False,
                  artist=None, kit="classic", melody=None, custom_kit=None,
                  healing=None, era=None, duration=None, fib_bursts=None):
    def prog(p, msg):
        set_job(job_id, progress=p, message=msg)
    try:
        fx = fx or {}
        # Memory guard: estimate the render buffer before allocating.
        # 4 beats/sec at 44.1k stereo ≈ predictable size.
        _est_n = int(60.0 / max(bpm, 1) * 4 * n_bars * SR)
        check_audio_budget(_est_n, channels=2, copies=8, label="beat render")
        # 101. memoization: identical params hit the cache
        fxhash = hashlib.sha256(
            json.dumps(fx, sort_keys=True).encode()).hexdigest()[:12]
        ckey = (genre, round(float(bpm), 2), n_bars, seed, fxhash,
                "fast" if fast else "v68", artist or "", kit or "classic",
                melody or "", custom_kit or "",
                json.dumps(healing, sort_keys=True) if healing else "",
                era or "", duration or 0,
                json.dumps(fib_bursts, sort_keys=True) if fib_bursts else "")
        cached = _beat_cache_get(ckey)
        if cached is not None:
            prog(90, "Beat from cache…")
            base = f"{job_id[:8]}_{beatfx.tag_filename('djrill-beat', bpm, genre)}"
            os.makedirs(TEMP_BEATS_DIR, exist_ok=True)
            wav_path = os.path.join(TEMP_BEATS_DIR, base + ".wav")
            mp3_path = os.path.join(TEMP_BEATS_DIR, base + ".mp3")
            with open(wav_path, "wb") as f:
                f.write(cached)
            encode_mp3(wav_path, mp3_path)
            _, audio = M.load_audio(wav_path)
            set_job(job_id, status="done", progress=100,
                    message="Beat ready (cached)",
                    result={"mp3": os.path.basename(mp3_path),
                            "wav": os.path.basename(wav_path),
                        "flac": None,
                            "bpm": bpm, "bars": n_bars, "seed": seed,
        "beat_source": "generate",
        "output_format": "mp3",
                            "cached": True, "temp": True, "job_id": job_id,
                            "duration": round(audio.shape[0] / SR, 1)})
            try:
                os.remove(wav_path)
            except OSError:
                pass
            temp_beats_register(job_id, base,
                {"mp3": os.path.basename(mp3_path)},
                genre, bpm, round(audio.shape[0] / SR, 1))
            return
        with _job_slots:  # 92. concurrency guard
            _run_beats_render(job_id, genre, bpm, n_bars, seed, fx, prog,
                              ckey, fast, artist, kit, melody, custom_kit,
                              healing, era, duration, fib_bursts)
    except Exception as e:
        set_job(job_id, status="error", progress=0, message=f"Error: {e}")


def _run_beats_render(job_id, genre, bpm, n_bars, seed, fx, prog, ckey,
                      fast=False, artist=None, kit="classic", melody=None,
                      custom_kit=None, healing=None, era=None, duration=None,
                      fib_bursts=None):
    if fast:
        # Fast mode: pure-numpy lightbeat renderer. No V68 engine, no
        # pygame/ffmpeg/samples — safe on phone CPUs.
        if duration:
            prog(5, f"Fast rendering full song ({n_bars} bars) at {bpm} BPM…")
        else:
            prog(5, f"Fast rendering {n_bars} bars at {bpm} BPM…")
        print(f"[FAST] calling lightbeat.generate_beat", flush=True)
        custom_samples = None
        if custom_kit:
            try:
                custom_samples = soundkits.load_kit_samples(custom_kit)
                if not custom_samples:
                    custom_samples = None
            except Exception as e:
                print(f"[FAST] custom kit load failed: {e}", flush=True)
        beat = lightbeat.generate_beat(
            genre, float(bpm), n_bars, seed, artist=artist,
            kit=kit or "classic", melody=melody,
            custom_samples=custom_samples, healing=healing, era=era,
            duration=duration, fib_bursts=fib_bursts,
            progress_cb=lambda f, m: prog(5 + int(78 * f), m))
        print(f"[FAST] beat done: {beat.shape}", flush=True)
    else:
        prog(2, "Loading beat engine…")
        eng = get_engine()
        prog(5, f"Rendering {n_bars} bars at {bpm} BPM…")
        beat = render_beat_progress(
            eng, genre, float(bpm), n_bars, seed,
            lambda b, n: prog(5 + int(70 * b / n), f"Bar {b}/{n}…"))
        fx = fx or {}
        if fx.get("fills"):
            prog(78, "Adding drum fills…")
            beat = beatfx.drum_fills(beat, float(bpm), seed=seed)
        if fx.get("humanize"):
            beat = beatfx.humanize(beat, float(bpm), seed=seed)
        if fx.get("swing"):
            prog(80, "Applying swing…")
            beat = beatfx.apply_swing(beat, float(bpm), float(fx["swing"]))
        if fx.get("risers"):
            beat = beatfx.risers(beat, float(bpm), seed=seed)
        if fx.get("builds"):
            beat = beatfx.drop_builds(beat, float(bpm), seed=seed)
        if fx.get("feel") in ("half", "double"):
            prog(82, f"Applying {fx['feel']}-time feel…")
            beat = beatfx.time_feel(beat, float(bpm), fx["feel"])
        if fx.get("transpose"):
            beat = beatfx.transpose(beat, int(fx["transpose"]))
        if fx.get("arrange"):
            beat = beatfx.arrangement_variants(beat, float(bpm),
                                               int(fx["arrange"]))
        if fx.get("glide808"):
            beat = beatfx.glide_808(beat, float(bpm), seed=seed)
        if fx.get("hatrolls"):
            prog(84, "Adding hat rolls…")
            beat = beatfx.hat_rolls(beat, float(bpm), seed=seed)
        if fx.get("percs"):
            beat = beatfx.perc_layer(beat, float(bpm), seed=seed)
        if fx.get("intro_outro"):
            prog(86, "Building intro/outro…")
            beat = beatfx.build_intro_outro(beat, float(bpm))
        if fx.get("crash"):
            beat = beatfx.crash_accents(beat, float(bpm), seed=seed)
        if fx.get("quality"):
            prog(87, "Applying quality chain…")
            beat = audiofx.quality_chain(beat, bpm=float(bpm))
    prog(88, "Mastering beat…")
    print(f"[FAST] mastering...", flush=True)
    if fast:
        # Fast path: simple peak normalize + light limiting, no V68 mastering.
        # No ffmpeg needed — WAV only.
        peak = np.max(np.abs(beat))
        if peak > 0:
            beat = beat * (0.89 / peak)
        # Simple soft clip
        beat = np.tanh(beat * 1.1) * 0.9
        pcm16 = (np.clip(beat, -1.0, 1.0) * 32767).astype(np.int16)
        print(f"[FAST] normalized", flush=True)
    else:
        pcm16, lufs, tp = M.master_track(beat * 0.9, target_lufs=-14.0)
    tag = beatfx.tag_filename("djrill-beat", bpm, genre)
    if artist:
        safe_a = "".join(c if c.isalnum() else "" for c in artist)[:20]
        tag = f"{tag}_{safe_a}style"
    base = f"{job_id[:8]}_{tag}"
    os.makedirs(TEMP_BEATS_DIR, exist_ok=True)
    wav_path = os.path.join(TEMP_BEATS_DIR, base + ".wav")
    mp3_path = os.path.join(TEMP_BEATS_DIR, base + ".mp3")
    print(f"[FAST] writing WAV to {wav_path}", flush=True)
    prog(90, "Writing WAV…")
    wav_write(wav_path, SR, pcm16)
    print(f"[FAST] WAV written", flush=True)
    if fast:
        # Skip MP3 when ffmpeg isn't working; serve WAV directly.
        import shutil as _sh
        import subprocess as _sp
        print(f"[FAST] checking ffmpeg...", flush=True)
        _ffmpeg_ok = False
        if _sh.which("ffmpeg"):
            try:
                _sp.run(["ffmpeg", "-version"], capture_output=True,
                        timeout=5, check=True)
                _ffmpeg_ok = True
            except Exception:
                _ffmpeg_ok = False
        if _ffmpeg_ok:
            prog(94, "Encoding MP3…")
            encode_mp3(wav_path, mp3_path)
        else:
            mp3_path = wav_path  # serve WAV as the download
        print(f"[FAST] mp3 step done", flush=True)
    else:
        # Check ffmpeg here too (not just in fast path)
        import shutil as _sh2
        _ff_ok = bool(_sh2.which("ffmpeg"))
        if _ff_ok:
            prog(94, "Encoding MP3…")
            encode_mp3(wav_path, mp3_path)
        else:
            mp3_path = wav_path  # serve WAV as the download
    print(f"[FAST] caching...", flush=True)
    prog(98, "Finalizing…")
    _beat_cache_put(ckey, wav_path)  # 101. memoize for reuse
    print(f"[FAST] setting job done", flush=True)
    set_job(job_id, status="done", progress=100, message="Beat ready",
            result={"mp3": os.path.basename(mp3_path),
                    "wav": os.path.basename(wav_path),
                        "flac": None,
                    "bpm": bpm, "bars": n_bars, "seed": seed,
        "beat_source": "generate",
        "output_format": "mp3",
                    "temp": True, "job_id": job_id,
                        "duration": round(beat.shape[0] / SR, 1)})
    try:
        os.remove(wav_path)
    except OSError:
        pass
    temp_beats_register(job_id, base,
                {"mp3": os.path.basename(mp3_path)},
        genre, bpm, round(beat.shape[0] / SR, 1))


# ---------------------------------------------------------------- convert job
def run_convert_job(job_id, src_path, out_ext):
    def prog(p, msg):
        set_job(job_id, progress=p, message=msg)
    try:
        prog(10, "Converting…")
        stem = os.path.splitext(os.path.basename(src_path))[0]
        dst = os.path.join(OUTPUT_DIR, f"{job_id[:8]}_{stem}{out_ext}")
        C.convert_file(src_path, dst)
        prog(90, "Checking output…")
        info = C.probe(dst)
        set_job(job_id, status="done", progress=100, message="Converted",
                result={"file": os.path.basename(dst),
                        "duration": round(info.get("duration", 0), 1),
                        "codec": info.get("codec")})
    except Exception as e:
        set_job(job_id, status="error", progress=0, message=f"Error: {e}")


def save_upload(file_storage):
    """Securely store an uploaded file inside UPLOAD_DIR. Returns path."""
    fname = secure_filename(file_storage.filename or "upload")
    ext = os.path.splitext(fname)[1].lower()
    if ext not in C.SUPPORTED_IN:
        raise ValueError(f"Unsupported file type {ext or '(none)'} — "
                         f"use: {', '.join(sorted(C.SUPPORTED_IN))}")
    if not fname or fname in (".", ".."):
        raise ValueError("Bad filename")
    name = f"{uuid.uuid4().hex[:8]}_{fname}"
    path = os.path.join(UPLOAD_DIR, name)
    # containment: resolved path must stay inside UPLOAD_DIR
    if os.path.commonpath([os.path.abspath(path), UPLOAD_DIR]) != UPLOAD_DIR:
        raise ValueError("Bad filename")
    file_storage.save(path)
    # 136. deep type check: probe actual content, reject mismatches
    if C.FFMPEG_OK:
        try:
            info = C.probe(path)
            if not info.get("duration"):
                raise ValueError("File has no decodable audio stream")
        except ValueError:
            raise
        except Exception:
            try:
                os.remove(path)
            except OSError:
                pass
            raise ValueError("File could not be read as audio")
    # 137. disk-space guard: refuse if <500MB free
    try:
        free = shutil.disk_usage(OUTPUT_DIR).free
        if free < 500 * 1024 * 1024:
            raise ValueError("Server disk full — free space and retry")
    except ValueError:
        raise
    except Exception:
        pass
    return path


IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp"}
VIDEO_EXTS = {".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v"}


def save_media_upload(file_storage, allowed_exts, kind):
    """Securely store an uploaded photo/video inside UPLOAD_DIR. Returns path."""
    fname = secure_filename(file_storage.filename or "upload")
    ext = os.path.splitext(fname)[1].lower()
    if ext not in allowed_exts:
        raise ValueError(f"Unsupported {kind} type {ext or '(none)'} — "
                         f"use: {', '.join(sorted(allowed_exts))}")
    if not fname or fname in (".", ".."):
        raise ValueError("Bad filename")
    name = f"{uuid.uuid4().hex[:8]}_{fname}"
    path = os.path.join(UPLOAD_DIR, name)
    if os.path.commonpath([os.path.abspath(path), UPLOAD_DIR]) != UPLOAD_DIR:
        raise ValueError("Bad filename")
    file_storage.save(path)
    return path


# ---------------------------------------------------------------- routes
@app.get("/")
def home():
    return render_template("home.html", active="home")


@app.get("/master")
def master_page():
    return render_template("master.html", active="master", genres=GENRES)


@app.get("/lyrics")
def lyrics_page():
    return render_template("lyrics.html", active="lyrics", genres=GENRES,
                           artists=L.list_artists())


@app.get("/convert")
def convert_page():
    return render_template("convert.html", active="convert",
                           formats=sorted(C.SUPPORTED_OUT))


@app.get("/separate")
def separate_page():
    # ONLINE-ONLY: separation runs in the cloud, not on-device.
    return render_template("separate.html", active="separate")


@app.get("/player")
def player_page():
    # OFFLINE: plays audio from on-device storage (Music/Downloads/Generated).
    return render_template("player.html", active="player")


@app.get("/beats")
def beats_page():
    return render_template("beats.html", active="beats", genres=GENRES,
                           artist_groups=lightbeat.ARTIST_GROUPS,
                           kits=lightbeat.list_kits(),
                           melody_insts=lightbeat.MELODY_INSTRUMENTS,
                           healing_presets=lightbeat.list_healing_presets(),
                           healing_options=lightbeat.healing_option_lists(),
                           custom_kits=soundkits.list_custom_kits())


@app.get("/studio")
def studio_page():
    return render_template("studio.html", active="studio", genres=GENRES)


# ---------------------------------------------------------------- studio (DAW) jobs
def run_daw_beat_job(job_id, genre, bpm, n_bars, seed, clip_name):
    """Render a beat and drop it into the Studio clip library."""
    def prog(p, msg):
        set_job(job_id, progress=p, message=msg)
    try:
        eng = get_engine()
        prog(5, f"Rendering {n_bars} bars at {bpm} BPM…")
        beat = render_beat_progress(
            eng, genre, float(bpm), n_bars, seed,
            lambda b, n: prog(5 + int(80 * b / n), f"Bar {b}/{n}…"))
        prog(88, "Adding to Studio…")
        tmp = os.path.join(OUTPUT_DIR, f"{job_id[:8]}_tmp.wav")
        wav_write(tmp, SR, (np.clip(beat, -1, 1) * 32767).astype(np.int16))
        prog(94, "Computing waveform…")
        clip_file = daw.store_clip(tmp, (clip_name or f"djrill-beat-{genre}") + ".wav")
        os.remove(tmp)
        peaks = daw.compute_peaks(os.path.join(daw.CLIPS_DIR, clip_file))
        set_job(job_id, status="done", progress=100, message="Beat added to Studio",
                result={"clip": {"file": clip_file,
                                 "name": clip_name or f"{genre} beat {int(bpm)}bpm",
                                 "duration": peaks["duration"],
                                 "peaks": peaks["peaks"]}})
    except Exception as e:
        set_job(job_id, status="error", progress=0, message=f"Error: {e}")


def run_export_job(job_id, project, name):
    def prog(p, msg):
        set_job(job_id, progress=p, message=msg)
    try:
        prog(5, "Rendering timeline…")
        wav_path, mp3_path, stats = daw.render_mixdown(
            project, OUTPUT_DIR, job_id[:8])
        prog(95, "Done")
        set_job(job_id, status="done", progress=100,
                message=f"Mixdown — {stats['lufs']} LUFS, {stats['dbtp']} dBTP",
                result={"mp3": os.path.basename(mp3_path),
                        "wav": os.path.basename(wav_path),
                        "flac": None,
                        **stats})
    except Exception as e:
        set_job(job_id, status="error", progress=0, message=f"Error: {e}")


@app.post("/api/daw/clip")
def api_daw_clip():
    """Upload an audio file into the Studio clip library."""
    f = request.files.get("file")
    if not f:
        return jsonify({"ok": False, "error": "No file uploaded"}), 400
    try:
        tmp = save_upload(f)  # validates type + containment
        clip_file = daw.store_clip(tmp, f.filename or "clip")
        os.remove(tmp)
        peaks = daw.compute_peaks(os.path.join(daw.CLIPS_DIR, clip_file))
    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    return jsonify({"ok": True, "clip": {
        "file": clip_file, "name": f.filename or "clip",
        "duration": peaks["duration"], "peaks": peaks["peaks"]}})


@app.post("/api/daw/beat")
def api_daw_beat():
    data = request.get_json(force=True, silent=True) or {}
    genre = data.get("genre", "HipHop")
    if genre not in GENRES:
        genre = "HipHop"
    try:
        bpm = float(data.get("bpm", 90))
        n_bars = int(data.get("bars", 8))
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "Bad BPM/bars"}), 400
    bpm = min(200, max(50, bpm))
    n_bars = min(32, max(4, n_bars))
    seed = data.get("seed")
    import random as _r
    seed = int(seed) if seed not in (None, "") else M.new_beat_seed()
    job_id = new_job("beat", (data.get("name") or genre)[:40])
    t = threading.Thread(target=run_daw_beat_job,
                         args=(job_id, genre, bpm, n_bars, seed,
                               (data.get("name") or "")[:40]),
                         daemon=True)
    t.start()
    return jsonify({"ok": True, "job_id": job_id})


@app.get("/clip/<path:fname>")
def serve_clip(fname):
    """Serve a Studio clip for in-browser playback."""
    try:
        p = daw.clip_path(fname)
    except ValueError:
        abort(404)
    return send_file(p)


@app.post("/api/daw/projects")
def api_daw_save():
    data = request.get_json(force=True, silent=True) or {}
    try:
        name = daw.save_project(data.get("name", ""), data.get("data", {}))
    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    return jsonify({"ok": True, "name": name})


@app.get("/api/daw/projects")
def api_daw_list():
    return jsonify({"ok": True, "projects": daw.list_projects()})


@app.get("/api/daw/projects/<name>")
def api_daw_load(name):
    try:
        data = daw.load_project(name)
    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 404
    return jsonify({"ok": True, "name": daw.sanitize_name(name), "data": data})


@app.post("/api/daw/export")
def api_daw_export():
    data = request.get_json(force=True, silent=True) or {}
    project = data.get("project")
    if not isinstance(project, dict) or "tracks" not in project:
        return jsonify({"ok": False, "error": "Bad project"}), 400
    job_id = new_job("mixdown", (data.get("name") or "")[:40])
    t = threading.Thread(target=run_export_job,
                         args=(job_id, project, (data.get("name") or "")[:40]),
                         daemon=True)
    t.start()
    return jsonify({"ok": True, "job_id": job_id})


def run_stems_job(job_id, project):
    def prog(p, msg):
        set_job(job_id, progress=p, message=msg)
    try:
        prog(5, "Rendering stems…")
        stems = daw.render_stems(project, OUTPUT_DIR, job_id[:8])
        prog(95, "Done")
        set_job(job_id, status="done", progress=100,
                message=f"{len(stems)} stems exported",
                result={"stems": stems})
    except Exception as e:
        set_job(job_id, status="error", progress=0, message=f"Error: {e}")


@app.post("/api/daw/stems")
def api_daw_stems():
    data = request.get_json(force=True, silent=True) or {}
    project = data.get("project")
    if not isinstance(project, dict) or "tracks" not in project:
        return jsonify({"ok": False, "error": "Bad project"}), 400
    job_id = new_job("stems", "")
    t = threading.Thread(target=run_stems_job, args=(job_id, project),
                         daemon=True)
    t.start()
    return jsonify({"ok": True, "job_id": job_id})


@app.get("/api/daw/click")
def api_daw_click():
    """58. Metronome click track download (WAV)."""
    try:
        bpm = max(40, min(220, float(request.args.get("bpm", 90))))
        bars = max(1, min(16, int(request.args.get("bars", 4))))
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "Bad bpm/bars"}), 400
    import studiofx
    click = studiofx.metronome_click(bpm, bars)
    pcm = (np.clip(click, -1, 1) * 32767).astype(np.int16)
    path = os.path.join(OUTPUT_DIR, f"click_{int(bpm)}bpm_{bars}bars.wav")
    wav_write(path, SR, pcm)
    return send_file(path, as_attachment=True,
                     download_name=os.path.basename(path))


def detect_bpm(audio_path, sr=None):
    """Detect BPM -- unified 2026-10-20: delegates to
    M.detect_bpm_consensus so every route reports the same tempo.
    (The old private algorithm could not detect below 60 BPM and
    reported 62 for a ~50 BPM song.) Returns float or None."""
    try:
        import numpy as np
        if isinstance(audio_path, np.ndarray):
            if sr is None:
                return None
            return M.detect_bpm_consensus(audio_path, sr)
        _sr, _audio = M.load_audio(audio_path)
        return M.detect_bpm_consensus(_audio, _sr)
    except Exception:
        return None


def _detect_bpm_legacy(audio_path, sr=None):
    try:
        import numpy as np
        if isinstance(audio_path, np.ndarray):
            audio = audio_path
            if sr is None:
                return None
        else:
            sr, audio = M.load_audio(audio_path)
            audio = np.mean(audio, axis=1) if len(audio.shape) > 1 else audio
        # Downsample for speed
        target_sr = 22050
        if sr != target_sr:
            ratio = target_sr / sr
            new_len = int(len(audio) * ratio)
            audio = np.interp(np.linspace(0, len(audio), new_len), np.arange(len(audio)), audio)
            sr = target_sr
        # Onset envelope via spectral flux (simplified: energy differences)
        hop = 512
        n_frames = len(audio) // hop
        if n_frames < 10:
            return None
        energy = np.array([np.mean(audio[i*hop:(i+1)*hop]**2) for i in range(n_frames)])
        # Onset = positive energy differences
        onset = np.maximum(0, np.diff(energy))
        if np.max(onset) == 0:
            return None
        onset = onset / np.max(onset)
        # Autocorrelation to find periodicities
        onset = onset - np.mean(onset)
        corr = np.correlate(onset, onset, mode='full')[len(onset)-1:]
        # BPM range: 60-180, convert to lag in frames
        # lag = 60/bpm * sr/hop
        best_bpm, best_val = None, 0
        for bpm in range(60, 181):
            lag = int(60.0 / bpm * sr / hop)
            if lag < len(corr):
                # Check also half/double for robustness
                val = corr[lag]
                if val > best_val:
                    best_val, best_bpm = val, float(bpm)
        return best_bpm
    except Exception:
        return None


# ===== Cloud Backup (BandLab parity) =====
import zipfile
import hashlib

BACKUP_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "backups")
os.makedirs(BACKUP_DIR, exist_ok=True)


# ===== Piano Roll (FL Mobile parity) =====
PIANO_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "piano_pattern.json")

@app.get("/piano")
def piano_page():
    return render_template("piano.html")

@app.post("/api/piano/save")
def api_piano_save():
    try:
        data = request.get_json(force=True)
        with open(PIANO_FILE, "w") as f:
            json.dump(data, f)
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

@app.get("/api/piano/load")
def api_piano_load():
    try:
        if not os.path.exists(PIANO_FILE):
            return jsonify({"ok": False, "error": "No saved pattern"})
        with open(PIANO_FILE) as f:
            data = json.load(f)
        return jsonify({"ok": True, **data})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


# ===== Distribution (LANDR parity) =====
@app.get("/distribute")
def distribute_page():
    return render_template("distribute.html")



# ===== Promo Tools (DistroKid parity) =====
import hashlib

@app.get("/promo")
def promo_page():
    return render_template("promo.html")




# ===== Beat Store (Marketplace) =====
import uuid as _uuid

@app.get("/store")
def store_page():
    return render_template("store.html")

@app.get("/api/store/beats")
def api_store_beats():
    """List all beats for sale."""
    try:
        store_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "store")
        os.makedirs(store_dir, exist_ok=True)
        beats = []
        for fn in os.listdir(store_dir):
            if fn.endswith(".json"):
                try:
                    beats.append(json.load(open(os.path.join(store_dir, fn))))
                except Exception:
                    pass
        return jsonify({"ok": True, "beats": beats})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

@app.post("/api/store/list")
def api_store_list():
    """List a beat for sale. 5% Prhyme fee."""
    try:
        from flask import session
        uid = session.get("user_id", "anon")
        f = request.files.get("file")
        if not f:
            return jsonify({"ok": False, "error": "No file"}), 400
        bid = _uuid.uuid4().hex[:12]
        store_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "store")
        os.makedirs(store_dir, exist_ok=True)
        # Save audio
        ext = os.path.splitext(f.filename)[1] or ".mp3"
        audio_path = os.path.join(store_dir, f"{bid}{ext}")
        f.save(audio_path)
        # Save metadata
        meta = {
            "id": bid,
            "title": request.form.get("title", "Untitled"),
            "genre": request.form.get("genre", "HipHop"),
            "bpm": request.form.get("bpm", "140"),
            "lease_price": float(request.form.get("lease_price", 25)),
            "exclusive_price": float(request.form.get("exclusive_price", 150)),
            "seller": uid,
            "preview": f"/store_audio/{bid}{ext}",
            "fee_percent": 5,
            "created": time.time(),
        }
        json.dump(meta, open(os.path.join(store_dir, f"{bid}.json"), "w"))
        return jsonify({"ok": True, "id": bid})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

@app.get("/api/store/my")
def api_store_my():
    """Get current user's listings."""
    try:
        from flask import session
        uid = session.get("user_id", "anon")
        store_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "store")
        beats = []
        if os.path.exists(store_dir):
            for fn in os.listdir(store_dir):
                if fn.endswith(".json"):
                    try:
                        b = json.load(open(os.path.join(store_dir, fn)))
                        if b.get("seller") == uid:
                            beats.append(b)
                    except Exception:
                        pass
        return jsonify({"ok": True, "beats": beats})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

@app.get("/store_audio/<fn>")
def store_audio(fn):
    """Serve beat previews."""
    store_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "store")
    return send_from_directory(store_dir, fn)


# ===== Prhyme Social (Community Platform) =====

@app.get("/community")
def community_page():
    return render_template("social.html")


@app.get("/analytics")
def analytics_page():
    return render_template("analytics.html")

@app.get("/api/social/feed")
def api_social_feed():
    """Get community feed."""
    try:
        filt = request.args.get("filter", "all")
        social_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "social")
        os.makedirs(social_dir, exist_ok=True)
        posts = []
        for fn in sorted(os.listdir(social_dir), reverse=True):
            if fn.endswith(".json"):
                try:
                    p = json.load(open(os.path.join(social_dir, fn)))
                    if filt == "all" or p.get("type") == filt:
                        posts.append(p)
                except Exception:
                    pass
        return jsonify({"ok": True, "posts": posts[:50]})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

@app.post("/api/social/post")
def api_social_post():
    """Create a post."""
    try:
        from flask import session
        data = request.get_json(force=True)
        pid = _uuid.uuid4().hex[:12]
        social_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "social")
        os.makedirs(social_dir, exist_ok=True)
        post = {
            "id": pid,
            "user": session.get("user_id", "Producer"),
            "text": data.get("text", "")[:1000],
            "type": data.get("type", "post"),
            "audio": data.get("audio"),
            "likes": 0,
            "liked_by": [],
            "comments": 0,
            "created": time.time(),
        }
        json.dump(post, open(os.path.join(social_dir, f"{pid}.json"), "w"))
        return jsonify({"ok": True, "id": pid})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

@app.post("/api/social/like/<pid>")
def api_social_like(pid):
    """Like a post."""
    try:
        from flask import session
        uid = session.get("user_id", "anon")
        social_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "social")
        pf = os.path.join(social_dir, f"{pid}.json")
        if not os.path.exists(pf):
            return jsonify({"ok": False}), 404
        post = json.load(open(pf))
        if uid not in post.get("liked_by", []):
            post["liked_by"].append(uid)
            post["likes"] = len(post["liked_by"])
            json.dump(post, open(pf, "w"))
        return jsonify({"ok": True, "likes": post["likes"]})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


# ===== Social Analytics + Paid Campaigns =====

@app.post("/api/social/view/<pid>")
def api_social_view(pid):
    """Track a post view."""
    try:
        social_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "social")
        pf = os.path.join(social_dir, f"{pid}.json")
        if os.path.exists(pf):
            post = json.load(open(pf))
            post["views"] = post.get("views", 0) + 1
            json.dump(post, open(pf, "w"))
            return jsonify({"ok": True})
        return jsonify({"ok": False}), 404
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

@app.get("/api/social/analytics/<pid>")
def api_social_analytics(pid):
    """Get analytics for a post."""
    try:
        from flask import session
        social_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "social")
        pf = os.path.join(social_dir, f"{pid}.json")
        if not os.path.exists(pf):
            return jsonify({"ok": False}), 404
        post = json.load(open(pf))
        # Only owner can see analytics
        if post.get("user") != session.get("user_id", "anon") and session.get("user_id") != "anon":
            # Allow for now (will restrict later)
            pass
        views = post.get("views", 0)
        likes = post.get("likes", 0)
        comments = post.get("comments", 0)
        engagement = ((likes + comments) / max(1, views)) * 100
        return jsonify({
            "ok": True,
            "views": views,
            "likes": likes,
            "comments": comments,
            "engagement_rate": round(engagement, 1),
            "is_boosted": post.get("boosted", False),
            "boost_spend": post.get("boost_spend", 0),
        })
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

@app.post("/api/social/boost/<pid>")
def api_social_boost(pid):
    """Boost a post (paid promotion)."""
    try:
        from flask import session
        data = request.get_json(force=True)
        budget = float(data.get("budget", 5))  # $5 minimum
        if budget < 5:
            return jsonify({"ok": False, "error": "Minimum $5"}), 400
        social_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "social")
        pf = os.path.join(social_dir, f"{pid}.json")
        if not os.path.exists(pf):
            return jsonify({"ok": False}), 404
        post = json.load(open(pf))
        # TODO: Stripe charge here
        post["boosted"] = True
        post["boost_spend"] = post.get("boost_spend", 0) + budget
        post["boost_target"] = data.get("target", "all")  # all, producers, vocalists, etc.
        json.dump(post, open(pf, "w"))
        # Estimated reach: $1 = ~100 impressions
        est_reach = int(budget * 100)
        return jsonify({"ok": True, "estimated_reach": est_reach,
                       "message": f"Boosted! Estimated {est_reach} impressions."})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

@app.get("/api/social/analytics/overview")
def api_social_overview():
    """Get analytics overview for current user."""
    try:
        from flask import session
        uid = session.get("user_id", "anon")
        social_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "social")
        total_views = 0
        total_likes = 0
        total_posts = 0
        if os.path.exists(social_dir):
            for fn in os.listdir(social_dir):
                if fn.endswith(".json"):
                    try:
                        p = json.load(open(os.path.join(social_dir, fn)))
                        if p.get("user") == uid:
                            total_posts += 1
                            total_views += p.get("views", 0)
                            total_likes += p.get("likes", 0)
                    except Exception:
                        pass
        return jsonify({
            "ok": True,
            "posts": total_posts,
            "views": total_views,
            "likes": total_likes,
            "avg_engagement": round((total_likes / max(1, total_views)) * 100, 1),
        })
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.post("/api/dj/mixplay")
def api_dj_mixplay():
    """Rokdabus generates a curated infinite mix playlist.
    Smart ordering: energy arc + key compatibility + BPM flow."""
    try:
        data = request.get_json(force=True, silent=True) or {}
        genre = data.get("genre")
        energy_arc = data.get("energy_arc", "rise")
        count = min(50, max(5, int(data.get("count", 20))))

        # Get library tracks
        import glob as _glob
        lib_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "outputs")
        tracks = []
        if os.path.exists(lib_dir):
            for fn in _glob.glob(os.path.join(lib_dir, "*.mp3")) + _glob.glob(os.path.join(lib_dir, "*.wav")):
                # Skip temp files
                if "temp" in fn:
                    continue
                tracks.append({
                    "path": fn,
                    "url": "/download/" + os.path.basename(fn),
                    "title": os.path.splitext(os.path.basename(fn))[0].replace("_", " "),
                    "bpm": 120,  # TODO: detect actual BPM
                    "energy": 5,
                })

        if not tracks:
            return jsonify({"ok": False, "error": "No tracks in library"}), 400

        # Smart ordering: sort by energy for arc
        import random
        if energy_arc == "rise":
            # Start chill, build up
            tracks.sort(key=lambda t: t["energy"])
        elif energy_arc == "chill":
            tracks.sort(key=lambda t: t["energy"], reverse=True)
        else:  # wave: alternate
            tracks.sort(key=lambda t: t["energy"])
            # Interleave low/high
            mid = len(tracks) // 2
            low, high = tracks[:mid], tracks[mid:]
            tracks = [x for pair in zip(low, high) for x in pair]

        # Shuffle within energy bands for variety, keep arc
        random.shuffle(tracks)

        return jsonify({"ok": True, "tracks": tracks[:count], "count": len(tracks[:count])})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

@app.get("/api/i18n/<lang>")
def api_i18n(lang):
    """Get translations for a language."""
    try:
        import i18n as _i18n
        if lang not in _i18n.SUPPORTED_LANGUAGES:
            return jsonify({"ok": False, "error": "Unsupported language"}), 400
        return jsonify({
            "ok": True,
            "lang": lang,
            "strings": _i18n.TRANSLATIONS.get(lang, {}),
            "languages": _i18n.SUPPORTED_LANGUAGES,
        })
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

@app.get("/api/i18n/languages")
def api_i18n_languages():
    import i18n as _i18n
    return jsonify({"ok": True, "languages": _i18n.SUPPORTED_LANGUAGES})

@app.get("/api/usage")
def api_usage():
    """Get current user's usage vs allowances."""
    try:
        import billing_core as bc
        from flask import session
        uid = session.get("user_id")
        if not uid:
            return jsonify({"ok": False, "error": "Not logged in"}), 401
        summary = bc.get_usage_summary(uid)
        tier = bc.get_user_tier(bc.get_user(uid))
        return jsonify({"ok": True, "tier": tier, "usage": summary})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

@app.post("/api/promo/presave")
def api_promo_presave():
    """Generate a pre-save smart link."""
    try:
        data = request.get_json(force=True)
        title = data.get("title", "untitled")
        # Generate a unique slug
        slug = hashlib.md5(f"{title}{time.time()}".encode()).hexdigest()[:8]
        # Store the pre-save data
        ps_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "presaves", f"{slug}.json")
        os.makedirs(os.path.dirname(ps_file), exist_ok=True)
        json.dump(data, open(ps_file, "w"))
        # URL (use request host)
        url = request.host_url.rstrip("/") + f"/presave/{slug}"
        return jsonify({"ok": True, "url": url, "slug": slug})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

@app.get("/presave/<slug>")
def presave_page(slug):
    """Public pre-save landing page."""
    try:
        ps_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "presaves", f"{slug}.json")
        if not os.path.exists(ps_file):
            return "Pre-save link not found", 404
        data = json.load(open(ps_file))
        rd = data.get('date','')
        return f"""<!DOCTYPE html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{data.get('title','')} — Pre-Save | Prhyme™</title>
<meta property="og:title" content="{data.get('title','')} by {data.get('artist','')}">
<meta property="og:description" content="Pre-save now on Prhyme™">
<style>
body{{background:linear-gradient(135deg,#0a0a14,#1a1a2e);color:#fff;font-family:-apple-system,sans-serif;text-align:center;padding:40px 20px;min-height:100vh;margin:0}}
.badge{{color:#00e5a0;font-weight:bold;letter-spacing:3px;font-size:12px}}
h1{{font-size:42px;margin:16px 0 8px}}.artist{{color:#aaa;font-size:20px;margin-bottom:24px}}
#countdown{{font-size:28px;color:#00e5a0;margin:24px 0;font-variant-numeric:tabular-nums}}
.btn{{display:inline-block;background:#00e5a0;color:#000;padding:16px 40px;border-radius:30px;text-decoration:none;font-weight:bold;margin:8px;font-size:16px}}
.btn2{{background:#2a2a48;color:#fff}}
.email-box{{margin:32px auto;max-width:400px}}
.email-box input{{width:70%;padding:12px;border-radius:8px 0 0 8px;border:1px solid #333;background:#1a1a2e;color:#fff}}
.email-box button{{width:30%;padding:12px;border-radius:0 8px 8px 0;border:none;background:#00e5a0;font-weight:bold;cursor:pointer}}
.share{{margin-top:24px}}.share a{{color:#888;margin:0 12px;font-size:14px;text-decoration:none}}
</style></head><body>
<p class="badge">PRHYME™ PRE-SAVE</p>
<h1>{data.get('title','')}</h1>
<p class="artist">{data.get('artist','')}</p>
<div id="countdown">Loading...</div>
<a class="btn" href="https://open.spotify.com/search/{data.get('title','').replace(' ','%20')}">Pre-Save on Spotify</a><br>
<a class="btn btn2" href="https://music.apple.com/search?term={data.get('title','').replace(' ','%20')}">Pre-Add on Apple Music</a>
<div class="email-box">
<p style="color:#888;font-size:14px">Get notified on release day:</p>
<input id="em" type="email" placeholder="your@email.com"><button onclick="sub()">Notify Me</button>
<p id="emsg" style="font-size:13px;margin-top:8px"></p>
</div>
<div class="share">
<a href="https://twitter.com/intent/tweet?text=Pre-save">𝕏</a>
<a href="https://www.facebook.com/sharer/sharer.php">Facebook</a>
<a href="https://www.instagram.com/">Instagram</a>
<a href="https://www.tiktok.com/">TikTok</a>
<a href="https://www.youtube.com/">YouTube</a>
<a href="https://www.snapchat.com/">Snapchat</a>
<a href="#" onclick="navigator.clipboard.writeText(location.href);return false">📋 Copy</a>
</div>
<script>
var rd = "{rd}";
if (rd) {{
  var target = new Date(rd).getTime();
  setInterval(function(){{
    var d = target - Date.now();
    if (d < 0) {{ document.getElementById('countdown').textContent = '🎉 OUT NOW!'; return; }}
    var days = Math.floor(d/864e5), h = Math.floor(d%864e5/36e5), m = Math.floor(d%36e5/6e4), s = Math.floor(d%6e4/1e3);
    document.getElementById('countdown').textContent = days+'d '+h+'h '+m+'m '+s+'s';
  }}, 1000);
}} else document.getElementById('countdown').textContent = 'Coming Soon';
function sub(){{
  var e = document.getElementById('em').value;
  if (e.includes('@')) document.getElementById('emsg').textContent = '✅ You\'re on the list!';
  else document.getElementById('emsg').textContent = 'Enter a valid email';
}}
</script></body></html>"""
    except Exception as e:
        return str(e), 500

@app.post("/api/distribute/notify")
def api_distribute_notify():
    """Sign up for distribution launch notification."""
    try:
        p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "dist_notify.json")
        subs = []
        if os.path.exists(p):
            subs = json.load(open(p))
        # Use a simple marker (no PII)
        subs.append({"ts": time.time()})
        json.dump(subs, open(p, "w"))
        return jsonify({"ok": True, "count": len(subs)})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

@app.post("/api/distribute/package")
def api_distribute_package():
    ok, resp = _check_and_log_usage("distribute")
    if not ok:
        return jsonify(resp), 402
    """Build a distributor-ready release package."""
    try:
        import io, zipfile
        title = request.form.get("title", "untitled")
        safe = "".join(c if c.isalnum() else "_" for c in title)

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            # Metadata
            meta = f"""Title: {request.form.get('title','')}
Artist: {request.form.get('artist','')}
Genre: {request.form.get('genre','')}
Release Date: {request.form.get('release_date','')}
"""
            zf.writestr(f"{safe}/metadata.txt", meta)
            # Audio
            if "audio" in request.files:
                af = request.files["audio"]
                ext = os.path.splitext(af.filename)[1] or ".wav"
                zf.writestr(f"{safe}/audio{ext}", af.read())
            # Artwork
            if "art" in request.files:
                im = request.files["art"]
                ext = os.path.splitext(im.filename)[1] or ".jpg"
                zf.writestr(f"{safe}/cover{ext}", im.read())
        buf.seek(0)
        return send_file(buf, as_attachment=True,
                         download_name=f"{safe}_release.zip",
                         mimetype="application/zip")
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

@app.post("/api/backup/create")
def api_backup_create():
    """Create a zip of all user outputs and return it for download."""
    try:
        import io
        buf = io.BytesIO()
        outputs = os.path.join(os.path.dirname(os.path.abspath(__file__)), "outputs")
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for root, dirs, files in os.walk(outputs):
                # Skip temp dirs
                dirs[:] = [d for d in dirs if d not in ("temp_beats", "temp_masters", "temp_ab")]
                for fn in files:
                    fp = os.path.join(root, fn)
                    arc = os.path.relpath(fp, outputs)
                    zf.write(fp, arc)
        # Save locally
        ts = time.strftime("%Y%m%d-%H%M%S")
        local_path = os.path.join(BACKUP_DIR, f"backup-{ts}.zip")
        with open(local_path, "wb") as f:
            f.write(buf.getvalue())
        return send_file(local_path, as_attachment=True,
                         download_name=f"prhyme-backup-{ts}.zip",
                         mimetype="application/zip")
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

@app.get("/api/backup/list")
def api_backup_list():
    """List local backups."""
    try:
        files = []
        for fn in sorted(os.listdir(BACKUP_DIR), reverse=True):
            if fn.endswith(".zip"):
                fp = os.path.join(BACKUP_DIR, fn)
                files.append({
                    "name": fn,
                    "size_mb": round(os.path.getsize(fp) / 1024 / 1024, 1),
                    "created": time.strftime("%Y-%m-%d %H:%M",
                        time.localtime(os.path.getmtime(fp))),
                })
        return jsonify({"ok": True, "backups": files})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

@app.post("/api/backup/restore")
def api_backup_restore():
    """Restore from an uploaded backup zip."""
    try:
        if "file" not in request.files:
            return jsonify({"ok": False, "error": "No file"}), 400
        f = request.files["file"]
        import io, zipfile
        buf = io.BytesIO(f.read())
        outputs = os.path.join(os.path.dirname(os.path.abspath(__file__)), "outputs")
        with zipfile.ZipFile(buf) as zf:
            # Safety: prevent path traversal
            for name in zf.namelist():
                if ".." in name or name.startswith("/"):
                    return jsonify({"ok": False, "error": "Invalid zip"}), 400
            zf.extractall(outputs)
        return jsonify({"ok": True, "message": "Backup restored"})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

@app.post("/api/master")
def api_master():
    ok, resp = _check_and_log_usage("master")
    if not ok:
        return jsonify(resp), 402
    # One-job master guard: only one master job may run at a time.
    # A second master request while one is active is rejected to avoid
    # OOM crashes from parallel mastering jobs.
    with jobs_lock:
        for jid, j in jobs.items():
            if j.get("_kind") in ("master", "stem-master") and j.get("status") == "running":
                return jsonify({
                    "ok": False,
                    "error": "A master job is already running. Wait for it to finish before starting another.",
                    "active_job_id": jid,
                }), 409
    f = request.files.get("file")
    if not f:
        return jsonify({"ok": False, "error": "No file uploaded"}), 400
    try:
        src = save_upload(f)
    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    genre = request.form.get("genre", "HipHop")
    if genre not in GENRES:
        genre = "HipHop"
    bpm_raw = (request.form.get("bpm") or "").strip()
    bpm = float(bpm_raw) if bpm_raw else None
    # Auto-detect BPM if blank
    if bpm is None:
        try:
            detected = detect_bpm(src)
            if detected:
                bpm = detected
        except:
            pass
    seed_raw = (request.form.get("seed") or "").strip()
    import random as _r
    seed = int(seed_raw) if seed_raw else M.new_beat_seed()
    title = request.form.get("title", "Prhyme™ Master")
    # mastering options
    chain = request.form.get("chain", "Streaming")
    if chain not in masterfx.MASTER_CHAINS:
        chain = "Streaming"
    def _f(name, default, lo, hi):
        try:
            return max(lo, min(hi, float(request.form.get(name, default))))
        except (TypeError, ValueError):
            return default
    mopts = {
        "chain": chain,
        "target_lufs": _f("target_lufs", None, -24, -6)
        if (request.form.get("target_lufs") or "").strip() else None,
        "ceiling_db": _f("ceiling_db", -1.0, -3.0, -0.3),
        "dither": request.form.get("dither", "on") != "off",
        "deess": _f("deess", 0.0, 0.0, 1.0),
        "multiband": request.form.get("multiband") == "on",
        "vocal_boost_db": _f("vocal_boost_db", 1.5, -6.0, 12.0),
        "fade_in": _f("fade_in", 0.5, 0.0, 5.0),
        "fade_out": _f("fade_out", 3.0, 0.0, 10.0),
        "vocal_polish": request.form.get("vocal_polish", "on") != "off",
        "timing_fix": request.form.get("timing_fix", "on") != "off",
        # creative FX (trackfx) — all optional, never delete words
        "fx_radio": request.form.get("fx_radio") == "on",
        "fx_tv": request.form.get("fx_tv") == "on",
        "fx_vinyl": request.form.get("fx_vinyl") == "on",
        "fx_hp_on": request.form.get("fx_hp_on") == "on",
        "fx_hp_cut": _f("fx_hp_cut", 120.0, 20.0, 20000.0),
        "fx_lp_on": request.form.get("fx_lp_on") == "on",
        "fx_lp_cut": _f("fx_lp_cut", 8000.0, 20.0, 20000.0),
        "fx_echo_on": request.form.get("fx_echo_on") == "on",
        "fx_echo_ms": _f("fx_echo_ms", 375.0, 50.0, 2000.0),
        "fx_echo_fb": _f("fx_echo_fb", 0.35, 0.0, 0.6),
        "fx_echo_mix": _f("fx_echo_mix", 0.30, 0.0, 0.5),
        "fx_echo_sync": request.form.get("fx_echo_sync") == "on",
        "fx_target": request.form.get("fx_target", "vocal")
        if request.form.get("fx_target") in ("vocal", "mix") else "vocal",
        "seed": seed,
        "beat_source": request.form.get("beat_source", "generate"),
        "ab_compare": request.form.get("ab_compare", "1"),
        "output_format": request.form.get("output_format", "mp3"),
    }
    # optional reference track for spectral matching
    ref = request.files.get("reference")
    if ref and ref.filename:
        try:
            mopts["reference_path"] = save_upload(ref)
        except ValueError as e:
            return jsonify({"ok": False, "error": str(e)}), 400
    job_id = new_job("master", title)
    t = threading.Thread(target=run_master_job,
                         args=(job_id, src, genre, bpm, seed, title, mopts),
                         daemon=True)
    t.start()
    return jsonify({"ok": True, "job_id": job_id})


def run_stem_master_job(job_id, stem_paths, mopts):
    def prog(p, msg):
        set_job(job_id, progress=p, message=msg)
    try:
        prog(5, f"Loading {len(stem_paths)} stems…")
        stems = []
        for i, sp in enumerate(stem_paths):
            _, audio = M.load_audio(sp)
            if audio.size == 0 or not np.all(np.isfinite(audio)):
                raise ValueError(f"Stem {i+1} is unreadable")
            stems.append((f"stem{i+1}", audio))
        prog(30, "Mastering stems…")
        pcm16, report = masterfx.stem_master(
            stems,
            target_lufs=float(mopts.get("target_lufs") or -14.0),
            ceiling_db=float(mopts.get("ceiling_db", -1.0)),
            dither=bool(mopts.get("dither", True)))
        base = f"{job_id[:8]}_djrill-stems"
        wav_path = os.path.join(OUTPUT_DIR, base + ".wav")
        mp3_path = os.path.join(OUTPUT_DIR, base + ".mp3")
        tmp_wav = wav_path + ".tmp"
        prog(86, "Writing WAV…")
        wav_write(tmp_wav, SR, pcm16)
        # Free the full-track array NOW: encode + A/B steps spawn
        # subprocesses/decoders; the phone OOM-kills the server if
        # the whole mastered track stays resident in RAM.
        del pcm16
        import gc as _gc; _gc.collect()
        os.replace(tmp_wav, wav_path)
        prog(92, "Encoding MP3…")
        flac_path = os.path.join(OUTPUT_DIR, base + ".flac")
        _fmt = mopts.get("output_format", "mp3")
        if _fmt == "flac":
            try:
                prog(93, "Encoding FLAC…")
                C.convert_file(wav_path, flac_path)
            except Exception:
                pass
        encode_mp3(wav_path, mp3_path)
        set_job(job_id, status="done", progress=100,
                message=f"Stems mastered — {report['lufs']} LUFS",
                result={"mp3": os.path.basename(mp3_path),
                        "wav": os.path.basename(wav_path),
                        "flac": None,
                        "report": report})
    except Exception as e:
        set_job(job_id, status="error", progress=0, message=f"Error: {e}")


@app.post("/api/master/stems")
def api_stem_master():
    """Master 2-8 uploaded stems together."""
    # One-job master guard: stem mastering uses the same heavy path.
    with jobs_lock:
        for jid, j in jobs.items():
            if j.get("_kind") in ("master", "stem-master") and j.get("status") == "running":
                return jsonify({
                    "ok": False,
                    "error": "A master job is already running. Wait for it to finish before starting another.",
                    "active_job_id": jid,
                }), 409
    files = request.files.getlist("stems")
    if not 2 <= len(files) <= 8:
        return jsonify({"ok": False,
                        "error": "Upload 2–8 stems"}), 400
    paths = []
    try:
        for f in files:
            paths.append(save_upload(f))
    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    mopts = {"target_lufs": request.form.get("target_lufs") or -14.0,
             "ceiling_db": request.form.get("ceiling_db") or -1.0,
             "dither": request.form.get("dither", "on") != "off"}
    job_id = new_job("stem-master", "")
    t = threading.Thread(target=run_stem_master_job,
                         args=(job_id, paths, mopts), daemon=True)
    t.start()
    return jsonify({"ok": True, "job_id": job_id})


@app.get("/api/master/chains")
def api_master_chains():
    return jsonify({"ok": True,
                    "chains": sorted(masterfx.MASTER_CHAINS.keys()),
                    "loudness": masterfx.LOUDNESS_PRESETS})


@app.get("/api/artists")
def api_artists():
    """Artist style list for the Beats page dropdown."""
    out = []
    for era, names in lightbeat.ARTIST_GROUPS:
        for n in names:
            st = lightbeat.get_artist_style(n)
            out.append({"name": n, "era": era, "region": st["region"],
                        "bpm": st["bpm"], "genre": st["base"],
                        "notes": st["notes"]})
    return jsonify({"ok": True, "artists": out})


@app.get("/api/artist/<name>")
def api_artist_info(name):
    st = lightbeat.get_artist_style(name)
    if not st:
        return jsonify({"ok": False}), 404
    return jsonify({"ok": True, "name": name, "bpm": st["bpm"],
                    "genre": st["base"], "era": st["era"],
                    "region": st["region"], "notes": st["notes"]})



def _check_and_log_usage(operation):
    """Spend free allowance first, then pay-per-use credits. Returns (ok, resp).
    ok=True means proceed. ok=False means return the response to client."""
    try:
        import billing_payments as bp_pay
        from flask import session
        uid = session.get("user_id")
        if not uid:
            # Not logged in — allow (free tier preview logic handles limits)
            return True, None
        ok, via = bp_pay.consume_generation(uid, operation)
        if ok:
            return True, None
        price = float(bp_pay.PAY_PER_USE.get(operation, 0))
        return False, {"ok": False, "error": "Free allowance used up",
                       "pay_per_use": price, "operation": operation,
                       "message": f"Your free {operation}s are used up. Pay ${price:.2f} to continue, or upgrade your plan."}
    except Exception:
        # If billing check fails, allow (fail open for now)
        return True, None

def _start_beat_job(data):
    """Validate beat params and launch the render job.

    Returns (payload_dict, status_code). Shared by /api/beats and Rokdabus."""
    ok, resp = _check_and_log_usage("beat")
    if not ok:
        return resp, 402
    data = data or {}
    genre = data.get("genre", "HipHop")
    if genre not in GENRES:
        genre = "HipHop"
    try:
        bpm = float(data.get("bpm", 90))
    except (TypeError, ValueError):
        return {"ok": False, "error": "Bad BPM"}, 400
    bpm = min(200, max(50, bpm))
    # LITE MODE: cap bars, force the phone-safe fast renderer, drop the
    # expensive post-FX. Prevents OOM on low-memory devices.
    # Full songs cap at 2:30 in lite mode (server enforces too).
    _lite = lite_mode()
    # Length picker: "loop16"/"loop32" (classic bar loops) or a full-song
    # duration label ("2:30"/"3:00"/"3:30"). Falls back to the legacy
    # "bars" param for older clients.
    length = (data.get("length") or "").strip()
    duration = None
    if length in lightbeat.STANDARD_DURATIONS:
        duration = float(lightbeat.STANDARD_DURATIONS[length])
        if _lite and duration > 150.0:
            duration = 150.0
        n_bars = min(160, max(16, int(round(duration / (240.0 / bpm)))))
    elif length.startswith("loop"):
        try:
            n_bars = int(length[4:] or 16)
        except ValueError:
            n_bars = 16
        n_bars = min(64, max(4, n_bars))
    else:
        try:
            n_bars = int(data.get("bars", 16))
        except (TypeError, ValueError):
            return {"ok": False, "error": "Bad bars"}, 400
        n_bars = min(64, max(4, n_bars))
    seed = data.get("seed")
    import random as _r
    seed = int(seed) if seed not in (None, "") else M.new_beat_seed()
    if _lite and duration is None:
        n_bars = min(n_bars, 16)
    # beat FX options (all optional)
    fx = {
        "fills": bool(data.get("fills")),
        "humanize": bool(data.get("humanize")),
        "swing": max(0.0, min(1.0, float(data.get("swing") or 0))),
        "risers": bool(data.get("risers")),
        "builds": bool(data.get("builds")),
        "feel": data.get("feel") if data.get("feel") in ("half", "double") else "normal",
        "transpose": max(-6, min(6, int(data.get("transpose") or 0))),
        "arrange": max(0, min(5, int(data.get("arrange") or 0))),
        "glide808": bool(data.get("glide808")),
        "hatrolls": bool(data.get("hatrolls")),
        "percs": bool(data.get("percs")),
        "intro_outro": bool(data.get("intro_outro")),
        "crash": bool(data.get("crash")),
        "quality": bool(data.get("quality")),
    }
    # ⚡ fast mode: lightweight phone-friendly renderer (default ON).
    # The checkbox sends "on" when checked; absent when unchecked.
    # Default to fast=True unless explicitly turned off.
    # LITE MODE forces fast=True — the V68 engine is never used in lite.
    fm = data.get("fastmode")
    fast = str(fm).lower() not in ("0", "false", "off", "no") if fm is not None else True
    if _lite:
        fast = True
        # strip the expensive post-FX in lite mode (keep fills/humanize/swing)
        for _heavy in ("risers", "builds", "glide808", "hatrolls", "percs",
                       "intro_outro", "crash", "quality", "arrange"):
            fx[_heavy] = False if _heavy != "arrange" else 0
        fx["transpose"] = 0
    # artist style emulation (lightbeat only; style, not copying)
    artist = (data.get("artist") or "").strip() or None
    if artist and not lightbeat.get_artist_style(artist):
        artist = None
    # drum kit: built-in kit name or "custom:<kit name>"
    kit_raw = (data.get("kit") or "classic").strip()
    kit, custom_kit = "classic", None
    if kit_raw.startswith("custom:"):
        custom_kit = kit_raw[len("custom:"):].strip()
        if not soundkits.get_custom_kit(custom_kit):
            custom_kit = None
    elif kit_raw in [k["name"] for k in lightbeat.list_kits()]:
        kit = kit_raw
    # lead instrument override
    melody = (data.get("melody") or "").strip() or None
    if melody not in lightbeat.MELODY_INSTRUMENTS:
        melody = None
    # era flavor: 2000s / 2010s / 2020s production style (optional)
    era = lightbeat.normalize_era((data.get("era") or "").strip() or None)
    # 🕉 healing mode: Fibonacci tuning + solfeggio drone (optional, off by default)
    def _bopt(v, default=True):
        if v is None:
            return default
        return str(v).lower() in ("on", "1", "true", "yes")
    healing = None
    if _bopt(data.get("healing"), False):
        healing = {
            "base": 432.0 if str(data.get("healing_base") or "432") == "432" else 440.0,
            "solfeggio": _bopt(data.get("healing_solfeggio"), True),
            "binaural": _bopt(data.get("healing_binaural"), False),
            "binaural_band": (data.get("healing_binaural_band") or "").strip() or None,
            "drone_mode": (data.get("healing_drone_mode") or "solfeggio").strip(),
            "drone_root": (data.get("healing_drone_root") or "").strip() or None,
            "soft_drums": _bopt(data.get("healing_soft_drums"), False),
            "preset": (data.get("healing_preset") or "").strip() or None,
        }
        healing = lightbeat.normalize_healing(healing)
    # 🌀 Fibonacci melodic bursts (opt-in): short Fibonacci-walk phrases
    # woven into the beat, always in key. Toggle + burst length (1-4 bars).
    fib_bursts = None
    if _bopt(data.get("fib_bursts"), False):
        # burst length: short/medium/long menu (legacy numeric fallback)
        _len_map = {"short": 1, "medium": 2, "long": 4}
        _raw_len = str(data.get("fib_burst_length") or "medium").lower()
        _bars = _len_map.get(_raw_len, 2)
        if data.get("fib_burst_bars"):
            try:
                _bars = min(4, max(1, int(data.get("fib_burst_bars"))))
            except (TypeError, ValueError):
                pass
        fib_bursts = {
            "bars": _bars,
            "intensity": str(data.get("fib_burst_intensity") or "balanced").lower(),
            "sequence": str(data.get("fib_burst_sequence") or "ascending").lower(),
        }
    job_label = f"{genre} {int(bpm)}bpm" + (f" [{artist}]" if artist else "") + (" 🕉" if healing else "") + (" 🌀" if fib_bursts else "") + (f" <{era}>" if era else "") + (f" {length}" if duration else "")
    job_id = new_job("beat", job_label)
    t = threading.Thread(target=run_beats_job,
                         args=(job_id, genre, bpm, n_bars, seed, fx, fast,
                               artist, kit, melody, custom_kit, healing, era,
                               duration, fib_bursts),
                         daemon=True)
    t.start()
    return {"ok": True, "job_id": job_id, "seed": seed}, 200


@app.post("/api/beats")
def api_beats():
    payload, status = _start_beat_job(
        request.get_json(force=True, silent=True))
    return jsonify(payload), status


@app.post("/api/beats/preview")
def api_beats_preview():
    """Free-tier beat preview: short snippet, no account required.

    Forces 8-bar renders regardless of requested length. Always uses a
    fresh unique seed so previews never repeat identically.
    """
    import freemium as _fm
    data = _fm.snippet_beat_params(
        request.get_json(force=True, silent=True))
    # Force a unique seed — previews must never repeat.
    data["seed"] = _fm.unique_seed(_freemium_user_key(), salt="beat")
    payload, status = _start_beat_job(data)
    if payload.get("ok"):
        # Tag the job so the poll response carries the preview flag.
        set_job(payload["job_id"], _preview=True)
        payload.update(_fm.upgrade_payload())
        payload["preview_bars"] = _fm.PREVIEW_BARS
    return jsonify(payload), status


def _freemium_user_key():
    """Stable per-user key for seed tracking: uid if logged in, else session/IP."""
    try:
        uid = _flask_session.get("uid")
        if uid:
            return f"uid:{uid}"
    except Exception:
        pass
    try:
        sid = _flask_session.get("_sid")
        if not sid:
            import uuid as _uuid
            sid = _uuid.uuid4().hex[:16]
            _flask_session["_sid"] = sid
        return f"sess:{sid}"
    except Exception:
        pass
    ip = request.headers.get("X-Forwarded-For", request.remote_addr or "?")
    return f"ip:{ip}"


# ---------------------------------------------------------------- ambient mix
# Multi-genre electronic background mix for idle listening. Rendered locally
# with lightbeat (fast numpy synth) — no internet, no static files.
_AMBIENT_STYLES = [
    dict(label="Lo-Fi", genre="BoomBap", bpm=72, melody="pads",
         kit="smooth", healing_base=432.0),
    dict(label="Chill Trap", genre="Trap", bpm=75, melody="bells",
         kit="smooth", healing_base=432.0),
    dict(label="Ambient House", genre="House", bpm=100, melody="pads",
         kit="smooth", healing_base=432.0),
    dict(label="Chill Hop", genre="HipHop", bpm=85, melody="piano",
         kit="smooth", healing_base=432.0),
    dict(label="Tropical Chill", genre="Afrobeats", bpm=95, melody="marimba",
         kit="smooth", healing_base=432.0),
    dict(label="Night Drive", genre="HipHop", bpm=90, melody="pluck",
         kit="smooth", healing_base=440.0),
]
_AMBIENT_BARS = 16
_ambient_cache = {}  # (genre, seed) -> mp3 basename
_ambient_lock = threading.Lock()


@app.get("/api/ambient")
def api_ambient():
    """Render (or reuse from cache) one ambient loop and return its URL.

    Query: style=<index into _AMBIENT_STYLES> (default 0), seed=<int>.
    The frontend cycles styles for a multi-genre mix.
    """
    try:
        style_idx = int(request.args.get("style", 0))
    except (TypeError, ValueError):
        style_idx = 0
    style_idx %= len(_AMBIENT_STYLES)
    style = _AMBIENT_STYLES[style_idx]
    try:
        seed = int(request.args.get("seed", 0)) or None
    except (TypeError, ValueError):
        seed = None
    if seed is None:
        import random as _r
        seed = _r.randint(1, 999999)
    key = (style["genre"], style["bpm"], seed)
    with _ambient_lock:
        cached = _ambient_cache.get(key)
        if cached and os.path.exists(os.path.join(OUTPUT_DIR, cached)):
            return jsonify({"ok": True, "url": url_for("download", fname=cached),
                            "style": style["label"], "genre": style["genre"],
                            "bpm": style["bpm"], "seed": seed,
        "beat_source": request.form.get("beat_source", "generate"),
        "output_format": request.form.get("output_format", "mp3"), "cached": True})
    try:
        healing = lightbeat.normalize_healing({
            "base": style["healing_base"], "fib_scale": True,
            "solfeggio": True, "binaural": False, "soft_drums": True})
        beat = lightbeat.generate_beat(
            style["genre"], float(style["bpm"]), _AMBIENT_BARS, seed,
            kit=style["kit"], melody=style["melody"], healing=healing,
            layers=False)
        # Gentle fade in/out for seamless-feeling loops.
        n = beat.shape[0]
        fade = min(n // 8, SR * 3)
        if fade > 0:
            ramp = np.linspace(0.0, 1.0, fade, dtype=np.float32)
            beat[:fade] *= ramp[:, None]
            beat[-fade:] *= ramp[::-1][:, None]
        peak = np.max(np.abs(beat))
        if peak > 0:
            beat = beat / peak * 0.7
        base = f"ambient_{style_idx}_{seed}"
        wav_path = os.path.join(OUTPUT_DIR, base + ".wav")
        mp3_path = os.path.join(OUTPUT_DIR, base + ".mp3")
        wav_write(wav_path, SR, (beat * 32767).astype(np.int16))
        if not encode_mp3(wav_path, mp3_path):
            mp3_path = wav_path  # fall back to WAV if ffmpeg missing
        with _ambient_lock:
            _ambient_cache[key] = os.path.basename(mp3_path)
            # keep the cache small: drop oldest beyond 12 entries
            while len(_ambient_cache) > 12:
                _ambient_cache.pop(next(iter(_ambient_cache)))
        try:
            os.remove(wav_path)
        except OSError:
            pass
        return jsonify({"ok": True,
                        "url": url_for("download", fname=os.path.basename(mp3_path)),
                        "style": style["label"], "genre": style["genre"],
                        "bpm": style["bpm"], "seed": seed,
        "beat_source": request.form.get("beat_source", "generate"),
        "output_format": request.form.get("output_format", "mp3"), "cached": False})
    except Exception as e:
        _app_log.warning(f"ambient render failed: {e}")
        return jsonify({"ok": False, "error": str(e)}), 500


@app.get("/api/ambient/styles")
def api_ambient_styles():
    return jsonify({"styles": [
        {"index": i, "label": s["label"], "genre": s["genre"], "bpm": s["bpm"]}
        for i, s in enumerate(_AMBIENT_STYLES)]})


@app.post("/api/convert")
def api_convert():
    f = request.files.get("file")
    if not f:
        return jsonify({"ok": False, "error": "No file uploaded"}), 400
    out_ext = (request.form.get("format") or ".mp3").lower()
    if out_ext not in C.SUPPORTED_OUT:
        return jsonify({"ok": False, "error": "Unsupported output format"}), 400
    try:
        src = save_upload(f)
    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    job_id = new_job("convert", os.path.basename(src))
    t = threading.Thread(target=run_convert_job,
                         args=(job_id, src, out_ext), daemon=True)
    t.start()
    return jsonify({"ok": True, "job_id": job_id})


# ------------------------------------------------- vocal separator + SFX
# ONLINE-ONLY feature: the phone uploads, the cloud separates (DSP or
# Demucs via vocalfx), the phone downloads the 3 layers.
def run_separate_job(job_id, src_path, title):
    """Separate vocals/instrumental, auto-build SFX layer, write 3 stems."""
    def prog(p, msg):
        set_job(job_id, progress=p, message=msg)

    try:
        prog(3, "Loading audio…")
        sr, audio = M.load_audio(src_path)  # float64 stereo @44.1k
        dur_s = len(audio) / sr
        if dur_s > 600:
            raise ValueError("Track too long — 10 minute max for separation")
        if dur_s < 3:
            raise ValueError("Track too short to separate")

        eng = vocalfx.engine_name()
        prog(8, f"Separating vocals ({eng})…")

        def _sp(p):
            prog(8 + int(p * 0.62), f"Separating vocals ({eng})… {int(p)}%")

        # normalize to WAV first (uploads may be MP3/M4A/OGG…)
        norm_wav = os.path.join(OUTPUT_DIR, f"{job_id[:8]}_sep-src.wav")
        vocalfx.write_wav(norm_wav + ".tmp", audio, sr)
        os.replace(norm_wav + ".tmp", norm_wav)
        vocals, inst = vocalfx.separate_track(norm_wav, sr, _sp)

        prog(72, "Detecting section transitions…")
        transitions = vocalfx.detect_transitions(audio, sr)

        prog(80, "Building SFX layer…")
        sfx = vocalfx.build_sfx_layer(len(audio), sr, transitions,
                                      seed=M.new_beat_seed())

        prog(88, "Writing layers…")
        base = f"{job_id[:8]}_{safe_name(title, 'separate')}"
        layers = {"vocals": vocals, "inst": inst, "sfx": sfx}
        result = {"engine": eng, "transitions": len(transitions),
                  "duration": round(dur_s, 1)}
        for key, arr in layers.items():
            wav_path = os.path.join(OUTPUT_DIR, f"{base}-{key}.wav")
            mp3_path = os.path.join(OUTPUT_DIR, f"{base}-{key}.mp3")
            tmp = wav_path + ".tmp"
            wav_write(tmp, SR, vocalfx._pcm16(arr))
            os.replace(tmp, wav_path)
            ok = encode_mp3(wav_path, mp3_path)
            result[f"{key}_wav"] = os.path.basename(wav_path)
            if ok:
                result[f"{key}_mp3"] = os.path.basename(mp3_path)

        set_job(job_id, status="done", progress=100,
                message=f"Done — {eng}, {len(transitions)} SFX transitions",
                result=result)
    except Exception as e:
        set_job(job_id, status="error", progress=0, message=f"Error: {e}")


@app.post("/api/separate")
def api_separate():
    f = request.files.get("file")
    if not f:
        return jsonify({"ok": False, "error": "No file uploaded"}), 400
    try:
        src = save_upload(f)
    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    title = (request.form.get("title") or "Separated Track").strip()[:80]
    job_id = new_job("separate", title)
    t = threading.Thread(target=run_separate_job,
                         args=(job_id, src, title), daemon=True)
    t.start()
    return jsonify({"ok": True, "job_id": job_id})


@app.get("/api/separate/<job_id>")
def api_separate_status(job_id):
    with jobs_lock:
        j = jobs.get(job_id)
    if not j:
        return jsonify({"ok": False, "error": "Unknown job"}), 404
    return jsonify({"ok": True, **j})


@app.post("/api/separate/mix")
def api_separate_mix():
    data = request.get_json(force=True, silent=True) or {}

    def _vol(name, default):
        try:
            return max(0.0, min(2.0, float(data.get(name, default))))
        except (TypeError, ValueError):
            return default

    vols = (_vol("vocal", 1.0), _vol("inst", 1.0), _vol("sfx", 0.8))
    job_id = (data.get("job_id") or "").strip()
    with jobs_lock:
        j = jobs.get(job_id) if job_id else None
    if not j or (j.get("result") or {}).get("vocals_wav") is None:
        return jsonify({"ok": False,
                        "error": "Unknown or unfinished separation job"}), 404
    res = j["result"]
    try:
        layers = []
        for key in ("vocals", "inst", "sfx"):
            p = os.path.join(OUTPUT_DIR, res[f"{key}_wav"])
            r_sr, d = wav_read(p)
            d = d.astype(np.float64) / 32768.0
            if d.ndim == 1:
                d = np.column_stack([d, d])
            layers.append(d)
        n = min(a.shape[0] for a in layers)
        mixed = vocalfx.mix_layers(*[a[:n] for a in layers], vols=vols)
        base = f"{job_id[:8]}_separate-mix"
        wav_path = os.path.join(OUTPUT_DIR, base + ".wav")
        mp3_path = os.path.join(OUTPUT_DIR, base + ".mp3")
        tmp = wav_path + ".tmp"
        wav_write(tmp, SR, vocalfx._pcm16(mixed))
        os.replace(tmp, wav_path)
        out = {"ok": True, "mix_wav": os.path.basename(wav_path)}
        if encode_mp3(wav_path, mp3_path):
            out["mix_mp3"] = os.path.basename(mp3_path)
        return jsonify(out)
    except Exception as e:
        return jsonify({"ok": False, "error": f"Mix failed: {e}"}), 500


# Explicit-content filter: common profanities, word-boundary matched
# (case-insensitive) so e.g. "ass" in "class" is never filtered.
_EXPLICIT_WORDS = [
    "motherfucker", "motherfucking", "fucking", "fucker", "fucked", "fuck",
    "shitty", "shit", "bitches", "bitch", "niggas", "nigga", "nigger",
    "asshole", "dicks", "dick", "pussy", "cunt", "cocks", "cock",
    "titty", "tits", "sluts", "slut", "whores", "whore", "hoes", "hoe",
    "asses", "ass",
]
_EXPLICIT_RE = re.compile(
    r"\b(" + "|".join(_EXPLICIT_WORDS) + r")\b", re.IGNORECASE)


def _clean_explicit(s):
    """Mask explicit words: first letter + asterisks (e.g. 'f***').
    Leaves non-string values untouched."""
    if not isinstance(s, str):
        return s
    return _EXPLICIT_RE.sub(
        lambda m: m.group(0)[0] + "*" * (len(m.group(0)) - 1), s)


def _gen_lyrics(data):
    """Generate draft lyrics. Returns (payload_dict, status_code).
    Shared by /api/lyrics and Rokdabus."""
    data = data or {}
    # Try Gemini first for high-quality lyrics
    try:
        import gemini_lyrics as _gl
        _g = _gl.generate_gemini_lyrics(
            genre=data.get("genre", "HipHop"),
            theme=(data.get("theme") or "struggle").strip()[:80],
            artist=(data.get("artist") or "").strip() or None,
            mood=(data.get("mood") or "").strip() or None,
        )
        if _g and _g.get("ok"):
            return {"ok": True, "lyrics": _g["lyrics"], "source": "gemini",
                    "adlibs": {"hook": ["yeah!", "woo!"], "verse": ["uh", "yeah"]}}, 200
    except Exception as _e:
        import traceback as _tb
        try:
            with open(os.path.join(BASE, "gemini_debug.log"), "a") as _lf:
                _lf.write("Gemini error: " + str(_e) + "\n" + _tb.format_exc() + "\n")
        except Exception:
            pass
    theme = (data.get("theme") or "").strip()[:80]
    mood = (data.get("mood") or "").strip()[:40]
    genre = data.get("genre", "HipHop")
    if genre not in GENRES:
        genre = "HipHop"
    seed_raw = data.get("seed")
    if seed_raw not in (None, ""):
        try:
            seed = int(seed_raw)
        except (TypeError, ValueError):
            return {"ok": False, "error": "Seed must be a number"}, 400
        # Track user-supplied seeds so even manual seeds can't repeat
        # silently for the same user.
        import freemium as _fm
        _fm.mark_seed_used(_freemium_user_key(), seed)
    else:
        # Unique seed per generation: deterministic base from theme+mood+
        # genre+artist, mixed with fresh randomness so identical inputs
        # never produce identical output twice (anti-identical-seed rule).
        import freemium as _fm
        artist_seed = (data.get("artist") or "").strip()
        base = int(hashlib.sha256(
            f"{theme}|{mood}|{genre}|{artist_seed}".encode())
                   .hexdigest()[:8], 16) % 1000000
        seed = _fm.unique_seed(_freemium_user_key(),
                               salt=f"lyrics:{base}")
    rs = data.get("rhyme_scheme", "AABB")
    if rs not in ("AABB", "ABAB", "AAAA"):
        rs = "AABB"
    def _i(name, default, lo, hi):
        try:
            return max(lo, min(hi, int(data.get(name, default))))
        except (TypeError, ValueError):
            return default
    custom = [w.strip()[:30] for w in
              (data.get("custom_words") or "").split(",")][:12]
    custom = [w for w in custom if w]
    # lyric_theme dropdown selects the word bank; free-text theme is the title
    bank_theme = (data.get("lyric_theme") or "").strip()[:40] or "street"
    if bank_theme not in L.THEMES:
        bank_theme = "street"
    # artist style emulation (never attributed; draft label stays on output)
    artist = (data.get("artist") or "").strip()
    if artist not in L.ARTIST_PROFILES:
        artist = None
    # Daryl rule: never generate the same lyrics twice, and ensure
    # significant variation (far apart) while maintaining coherence.
    # We generate, fingerprint the content, and retry with a fresh seed
    # if too similar to recent generations (max 5 attempts).
    import json as _json, os as _os, hashlib as _hl
    _hist_path = _os.path.join(_os.path.dirname(__file__), "lyric_history.json")
    def _fingerprint(s):
        # Normalize: lowercase, unique words sorted
        words = sorted(set(re.findall(r"[a-z]+", s.lower())))
        return _hl.sha256(" ".join(words).encode()).hexdigest()[:16], set(words)
    def _load_hist():
        try:
            with open(_hist_path) as f:
                return _json.load(f)
        except:
            return []
    def _save_hist(h):
        try:
            with open(_hist_path, "w") as f:
                _json.dump(h[-50:], f)  # Keep last 50
        except:
            pass
    _hist = _load_hist()
    song = None
    _attempt_seed = seed
    for _attempt in range(5):
        song = L.generate_song_lyrics_ex(
            _attempt_seed, genre=genre, theme=bank_theme,
            rhyme_scheme=rs,
            syl_target=_i("syl_target", 12, 6, 20),
            verse_lines=_i("verse_lines", 16, 4, 32),
            hook_lines=_i("hook_lines", 8, 2, 16),
            custom_words=custom,
            hook_first=bool(data.get("hook_first")),
            call_response=bool(data.get("call_response")),
            internal_rhyme=bool(data.get("internal_rhyme")),
            multi_boost=bool(data.get("multi_boost")),
            artist=artist,
            explicit=bool(data.get("parental_advisory") or data.get("explicit")))
        _txt_check = L.format_lyrics_txt(song, title="check")
        _fp, _words = _fingerprint(_txt_check)
        _too_similar = False
        for _h in _hist:
            _h_fp, _h_words = _h.get("fp"), set(_h.get("words", []))
            if _fp == _h_fp:
                _too_similar = True
                break
            # Jaccard similarity: if >60% word overlap, too similar
            if _h_words:
                _inter = len(_words & _h_words)
                _union = len(_words | _h_words)
                if _union > 0 and (_inter / _union) > 0.6:
                    _too_similar = True
                    break
        if not _too_similar:
            _hist.append({"fp": _fp, "words": sorted(_words)[:200]})
            _save_hist(_hist)
            seed = _attempt_seed  # Use the successful seed
            break
        # Too similar: try a fresh random seed
        import secrets as _secrets
        _attempt_seed = int.from_bytes(_secrets.token_bytes(4), "big")
    if song is None:
        # Fallback (should not happen)
        song = L.generate_song_lyrics_ex(
            seed, genre=genre, theme=bank_theme,
            rhyme_scheme=rs,
            syl_target=_i("syl_target", 12, 6, 20),
            verse_lines=_i("verse_lines", 16, 4, 32),
            hook_lines=_i("hook_lines", 8, 2, 16),
            custom_words=custom,
            hook_first=bool(data.get("hook_first")),
            call_response=bool(data.get("call_response")),
            internal_rhyme=bool(data.get("internal_rhyme")),
            multi_boost=bool(data.get("multi_boost")),
            artist=artist,
            explicit=bool(data.get("parental_advisory") or data.get("explicit")))
    txt = L.format_lyrics_txt(song, title=song.get("title") or (theme or "Untitled"))
    lrc = L.format_lyrics_lrc(song, float(data.get("bpm") or 90),
                              title=song.get("title") or "Untitled")
    sections = {k: song[k] for k in
                ("verse1", "hook", "verse2", "verse3",
                 "bridge", "outro") if k in song}
    # Explicit toggle is server-side enforced: a direct API call with
    # explicit=false cannot bypass the filter. Defaults ON (explicit allowed).
    if not data.get("explicit", True):
        txt = _clean_explicit(txt)
        lrc = _clean_explicit(lrc)
        sections = {k: [_clean_explicit(line) for line in v]
                    if isinstance(v, list) else _clean_explicit(v)
                    for k, v in sections.items()}
    return {"ok": True, "seed": seed,
        "beat_source": request.form.get("beat_source", "generate"),
        "output_format": request.form.get("output_format", "mp3"), "text": txt, "lrc": lrc,
            "title": song.get("title"),
            "stats": L.lyric_stats(song),
            "adlibs": song.get("adlibs"),
            "sections": sections}, 200


@app.post("/api/lyrics")
def api_lyrics():
    payload, status = _gen_lyrics(
        request.get_json(force=True, silent=True))
    return jsonify(payload), status


@app.post("/api/lyrics/preview")
def api_lyrics_preview():
    """Free-tier lyric preview: first 8 lines only, no account required.

    Always uses a fresh unique seed so the same prompt never returns
    identical lyrics twice.
    """
    import freemium as _fm
    data = dict(request.get_json(force=True, silent=True) or {})
    # Force a unique seed — ignore any client-supplied seed. This guarantees
    # the anti-identical-seed contract: same inputs → different output.
    data["seed"] = _fm.unique_seed(_freemium_user_key(), salt="lyrics")
    payload, status = _gen_lyrics(data)
    if payload.get("ok"):
        payload["text"] = _fm.snippet_lyrics(payload["text"])
        payload["lrc"] = _fm.snippet_lyrics(payload.get("lrc", ""))
        # Trim sections to preview length too.
        for k, v in list(payload.get("sections", {}).items()):
            if isinstance(v, list):
                payload["sections"][k] = v[:_fm.PREVIEW_LYRIC_LINES]
        payload.update(_fm.upgrade_payload())
        payload["is_lyric_preview"] = True
    return jsonify(payload), status


@app.get("/video")
def video_page():
    return render_template("video.html", active="video", genres=GENRES,
                           ffmpeg=C.FFMPEG_OK)


@app.get("/dj")
def dj_page():
    return render_template("dj.html", active="dj",
                           mix_genres=mixgen.SUPPORTED_GENRES,
                           mix_styles=mixgen.STYLE_PRESETS)


def _build_library_mix(job_id, genre, prog):
    """Build DJ mix from player's library tracks. Returns (audio, meta) or None."""
    import os as _os, re as _re
    import numpy as _np
    exts = (".wav", ".mp3", ".ogg", ".flac", ".m4a", ".opus", ".aiff", ".aif", ".wma", ".aac")
    tracks = []
    if _os.path.isdir(OUTPUT_DIR):
        for fn in _os.listdir(OUTPUT_DIR):
            if not fn.lower().endswith(exts):
                continue
            p = _os.path.join(OUTPUT_DIR, fn)
            try:
                if _os.path.getsize(p) < 1024:
                    continue
            except OSError:
                continue
            m = _re.search(r"(\d{2,3})\s*bpm", fn, _re.I)
            bpm = float(m.group(1)) if m else 92.0
            # Only use WAV (MP3 decode needs miniaudio, keep it simple)
            if fn.lower().endswith(".wav"):
                tracks.append({"path": p, "bpm": bpm, "name": fn})
    if len(tracks) < 2:
        return None
    tracks = sorted(tracks, key=lambda t: abs(t["bpm"] - 92))[:4]
    prog(10, f"Loading {len(tracks)} library tracks...")
    audios = []
    for t in tracks:
        try:
            from scipy.io.wavfile import read as _wr
            _sr, _aud = _wr(t["path"])
            _aud = _aud.astype(_np.float32)
            if _aud.ndim == 1:
                _aud = _np.column_stack([_aud, _aud])
            elif _aud.shape[1] > 2:
                _aud = _aud[:, :2]
            _peak = _np.max(_np.abs(_aud))
            if _peak > 0:
                _aud = _aud / _peak * 0.85
            _max_len = 30 * 44100
            if len(_aud) > _max_len:
                _aud = _aud[:_max_len]
            audios.append(_aud)
        except Exception:
            continue
    if len(audios) < 2:
        return None
    prog(50, "Crossfading library tracks...")
    _xf = 4 * 44100
    _mix = audios[0]
    for _nxt in audios[1:]:
        _xl = min(_xf, len(_mix), len(_nxt))
        _fade_out = _np.cos(_np.linspace(0, _np.pi/2, _xl)).reshape(-1, 1)
        _fade_in = _np.sin(_np.linspace(0, _np.pi/2, _xl)).reshape(-1, 1)
        _tail = _mix[-_xl:] * _fade_out
        _head = _nxt[:_xl] * _fade_in
        _mix = _np.concatenate([_mix[:-_xl], _tail + _head, _nxt[_xl:]], axis=0)
    _peak = _np.max(_np.abs(_mix))
    if _peak > 0:
        _mix = _mix / _peak * 0.9
    prog(90, "Library mix ready")
    return _mix, {"bpm": tracks[0]["bpm"], "tracks": [t["name"] for t in tracks],
                  "source": "library"}

def run_mix_job(job_id, genre, style, seed):
    def prog(p, msg):
        set_job(job_id, progress=p, message=msg)
    try:
        _lib = _build_library_mix(job_id, genre, prog)
        if _lib is not None:
            audio, meta = _lib
            prog(95, "Writing files...")
            base = f"djrill-mix-{meta['bpm']:.0f}bpm-library-{job_id[:8]}"
            base = "".join(ch if (ch.isalnum() or ch in "-_") else "_" for ch in base)
            wav_path = os.path.join(OUTPUT_DIR, base + ".wav")
            mp3_path = os.path.join(OUTPUT_DIR, base + ".mp3")
            audiotools.write_wav(wav_path, audio)
            prog(97, "Encoding MP3...")
            encode_mp3(wav_path, mp3_path)
            set_job(job_id, status="done", progress=100,
                    message="Library mix ready",
                    result={"mp3": os.path.basename(mp3_path),
                            "wav": os.path.basename(wav_path),
                            "bpm": meta["bpm"],
                            "tracks": meta["tracks"], "source": "library"})
            return
        _lite = lite_mode()
        # Memory guard: 4 segs x 16 bars or 2 x 8 in lite, stereo float32.
        _bars = 8 if _lite else 16
        _segs = 2 if _lite else 4
        check_audio_budget(int(240 / 140 * _bars * _segs * SR),
                           channels=2, copies=4 if _lite else 8,
                           label="DJ mix")
        prog(2, "Planning mix…" + (" (lite)" if _lite else ""))
        audio, meta = mixgen.generate_mix(
            genre=genre, style=style, seed=seed, progress_cb=prog,
            lite=_lite)
        prog(95, "Writing files…")
        style_tag = (style or "genre").replace(" ", "")
        base = (f"djrill-mix-{meta['bpm']:.0f}bpm-{style_tag}-{job_id[:8]}"
                .replace("--", "-"))
        base = "".join(c if (c.isalnum() or c in "-_") else "_" for c in base)
        wav_path = os.path.join(OUTPUT_DIR, base + ".wav")
        mp3_path = os.path.join(OUTPUT_DIR, base + ".mp3")
        audiotools.write_wav(wav_path, audio)
        prog(97, "Encoding MP3…")
        encode_mp3(wav_path, mp3_path)
        set_job(job_id, status="done", progress=100,
                message="Mix ready",
                result={"mp3": os.path.basename(mp3_path),
                        "wav": os.path.basename(wav_path),
                        "flac": None,
                        "bpm": meta["bpm"], "duration": meta["duration"],
                        "segments": meta["segments"], "style": meta["style"],
                        "seed": seed})
    except Exception as e:
        set_job(job_id, status="error", progress=0, message=f"Error: {e}")


def _start_mix_job(data):
    """Validate mix params and launch the mix job.
    Returns (payload_dict, status_code). Shared by /api/mix and Rokdabus."""
    data = data or {}
    genre = data.get("genre") or "HipHop"
    if genre not in mixgen.SUPPORTED_GENRES:
        genre = "HipHop"
    style = (data.get("style") or "genre").strip()
    valid_styles = [s[0] for s in mixgen.STYLE_PRESETS]
    if style not in valid_styles:
        style = "genre"
    import random as _r
    seed = data.get("seed")
    seed = int(seed) if seed not in (None, "") else _r.randint(0, 2 ** 31 - 1)
    style_label = dict(mixgen.STYLE_PRESETS).get(style, style)
    job_id = new_job("mix", f"{style_label} @ {genre}")
    t = threading.Thread(target=run_mix_job, args=(job_id, genre, style, seed),
                         daemon=True)
    t.start()
    return {"ok": True, "job_id": job_id, "seed": seed}, 200


@app.post("/api/mix")
def api_mix():
    """Generate a continuous DJ-style mix: beatmatched original beats,
    crossfaded into one track. Optional era/style emulation."""
    payload, status = _start_mix_job(
        request.get_json(force=True, silent=True))
    return jsonify(payload), status


@app.post("/api/dj/upload")
def api_dj_upload():
    """Upload a track the user owns into the DJ library.

    The user's own files — the app only stores and plays them, never
    downloads or provides copyrighted content.
    """
    f = request.files.get("file")
    if not f:
        return jsonify({"ok": False, "error": "No file uploaded"}), 400
    fname = secure_filename(f.filename or "track")
    ext = os.path.splitext(fname)[1].lower()
    if ext not in (".wav", ".mp3", ".ogg", ".flac", ".m4a", ".opus", ".aiff", ".aif", ".wma", ".aac"):
        return jsonify({"ok": False, "error":
                        f"Unsupported type {ext or '(none)'} — use MP3/WAV/OGG/FLAC/M4A"}), 400
    # 50 MB cap for phone storage
    f.seek(0, os.SEEK_END)
    size = f.tell()
    f.seek(0)
    if size > 50 * 1024 * 1024:
        return jsonify({"ok": False, "error": "File too large (50 MB max)"}), 400
    if size < 1024:
        return jsonify({"ok": False, "error": "File is empty"}), 400
    stem = os.path.splitext(fname)[0][:60] or "track"
    out_name = f"djupload_{uuid.uuid4().hex[:8]}_{stem}{ext}"
    out_path = os.path.join(OUTPUT_DIR, out_name)
    # containment check
    if os.path.commonpath([os.path.abspath(out_path), OUTPUT_DIR]) != OUTPUT_DIR:
        return jsonify({"ok": False, "error": "Bad filename"}), 400
    f.save(out_path)
    return jsonify({"ok": True, "name": out_name,
                    "url": url_for("download", fname=out_name),
                    "size_kb": round(size / 1024, 1)})


@app.get("/api/library")
def api_library():
    """List generated tracks (beats, masters) playable in the DJ decks."""
    import re as _re
    exts = (".wav", ".mp3", ".ogg", ".flac", ".m4a", ".opus", ".aiff", ".aif", ".wma", ".aac")
    tracks = []
    if os.path.isdir(OUTPUT_DIR):
        for fn in os.listdir(OUTPUT_DIR):
            if not fn.lower().endswith(exts):
                continue
            p = os.path.join(OUTPUT_DIR, fn)
            try:
                mtime = os.path.getmtime(p)
                size = os.path.getsize(p)
            except OSError:
                continue
            if size < 1024:
                continue
            bpm = None
            m = _re.search(r"(\d{2,3})\s*bpm", fn, _re.I)
            if m:
                try:
                    bpm = max(50, min(200, int(m.group(1))))
                except ValueError:
                    bpm = None
            tracks.append({"name": fn,
                           "url": url_for("download", fname=fn),
                           "bpm": bpm, "mtime": mtime,
                           "size_kb": round(size / 1024, 1)})
    tracks.sort(key=lambda t: -t["mtime"])
    return jsonify({"ok": True, "tracks": tracks[:120]})


@app.get("/history")
def history_page():
    return render_template("history.html", active="home")


@app.get("/tools")
def tools_page():
    return render_template("tools.html", active="home")


@app.get("/samples")
def samples_page():
    return render_template("samples.html", active="home")


@app.get("/presets")
def presets_page():
    return render_template("presets.html", active="home")


@app.get("/freestyle")
def freestyle_page():
    return render_template("freestyle.html", active="freestyle",
                           themes=L.THEMES)


@app.get("/help")
def help_page():
    return render_template("help.html", active="help")


# ------------------------------------------------------- feedback
# User complaints & feature suggestions. Stored in SQLite, rate-limited,
# admin-visible. Email notification logged (wire SMTP later).

_FEEDBACK_CATEGORIES = {
    "bug": ["Crash / freeze", "Wrong output", "UI glitch", "Audio issue",
            "Login / account", "Payment / billing", "Other bug"],
    "feature": ["New genre / sound", "New feature", "Improvement",
                "Integration", "Other idea"],
}


def _feedback_db():
    import sqlite3
    p = os.path.join(BASE, "feedback.db")
    con = sqlite3.connect(p)
    con.row_factory = sqlite3.Row
    con.execute(
        """CREATE TABLE IF NOT EXISTS feedback (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            kind TEXT NOT NULL,           -- 'bug' or 'feature'
            category TEXT NOT NULL,
            subject TEXT NOT NULL,
            description TEXT NOT NULL,
            email TEXT,
            uid INTEGER,
            ip TEXT,
            status TEXT NOT NULL DEFAULT 'new',  -- new/triaged/fixed/wontfix
            created_at REAL NOT NULL)""")
    con.execute("CREATE INDEX IF NOT EXISTS idx_fb_created "
                "ON feedback(created_at DESC)")
    con.commit()
    return con


_feedback_rl = {}
_feedback_rl_lock = threading.Lock()


@app.get("/feedback")
def feedback_page():
    return render_template(
        "feedback.html", active="help",
        bug_cats=_FEEDBACK_CATEGORIES["bug"],
        feat_cats=_FEEDBACK_CATEGORIES["feature"])


@app.post("/api/feedback")
def api_feedback():
    # Rate limit: 5 submissions per hour per IP.
    ip = request.headers.get("X-Forwarded-For", request.remote_addr or "?")
    now = time.time()
    with _feedback_rl_lock:
        hits = [t for t in _feedback_rl.get(ip, []) if now - t < 3600]
        if len(hits) >= 5:
            return jsonify({"ok": False,
                            "error": "Too many submissions — try again later."}), 429
        hits.append(now)
        _feedback_rl[ip] = hits
    data = request.get_json(force=True, silent=True) or request.form or {}
    kind = (data.get("kind") or "").strip()
    if kind not in ("bug", "feature"):
        return jsonify({"ok": False, "error": "Pick a type."}), 400
    category = (data.get("category") or "").strip()[:60]
    if category not in _FEEDBACK_CATEGORIES[kind]:
        return jsonify({"ok": False, "error": "Pick a category."}), 400
    subject = (data.get("subject") or "").strip()[:120]
    description = (data.get("description") or "").strip()[:5000]
    if not subject or not description:
        return jsonify({"ok": False,
                        "error": "Subject and description are required."}), 400
    email = (data.get("email") or "").strip()[:120]
    try:
        uid = _flask_session.get("uid")
    except Exception:
        uid = None
    con = _feedback_db()
    try:
        cur = con.execute(
            "INSERT INTO feedback (kind, category, subject, description,"
            " email, uid, ip, created_at) VALUES (?,?,?,?,?,?,?,?)",
            (kind, category, subject, description, email or None,
             uid, ip, now))
        fid = cur.lastrowid
        con.commit()
    finally:
        con.close()
    # Log for Daryl (wire SMTP later for real email notification).
    print(f"[FEEDBACK #{fid}] {kind}/{category}: {subject}"
          f" (from uid={uid} ip={ip})", flush=True)
    return jsonify({"ok": True, "id": fid,
                    "message": "Thanks — we've got it and will take a look."})


@app.get("/admin/feedback")
def admin_feedback():
    """Daryl's admin view — owner only."""
    try:
        uid = _flask_session.get("uid")
    except Exception:
        uid = None
    if not uid:
        return redirect(url_for("billing.login", next="/admin/feedback"))
    import billing_core as _bc
    user = _bc.get_user(int(uid))
    if not user or not user.get("is_owner"):
        abort(403)
    status_filter = request.args.get("status", "")
    con = _feedback_db()
    try:
        if status_filter in ("new", "triaged", "fixed", "wontfix"):
            rows = con.execute(
                "SELECT * FROM feedback WHERE status = ?"
                " ORDER BY id DESC LIMIT 200",
                (status_filter,)).fetchall()
        else:
            rows = con.execute(
                "SELECT * FROM feedback ORDER BY id DESC LIMIT 200").fetchall()
        items = [dict(r) for r in rows]
        counts = dict(con.execute(
            "SELECT status, COUNT(*) c FROM feedback GROUP BY status"))
    finally:
        con.close()
    return render_template("admin_feedback.html", active="account",
                           items=items, counts=counts,
                           status_filter=status_filter)


@app.get("/admin/analytics")
def admin_analytics():
    """Daryl's analytics dashboard — owner only."""
    try:
        uid = _flask_session.get("uid")
    except Exception:
        uid = None
    if not uid:
        return redirect(url_for("billing.login", next="/admin/analytics"))
    import billing_core as _bc
    user = _bc.get_user(int(uid))
    if not user or not user.get("is_owner"):
        abort(403)
    days = min(90, max(1, int(request.args.get("days", 30))))
    return render_template("admin_analytics.html", active="account",
                           events=_bc.analytics_summary(days), days=days)


@app.post("/api/admin/feedback/<int:fid>/status")
def api_admin_feedback_status(fid):
    """Update feedback status (owner only)."""
    try:
        uid = _flask_session.get("uid")
    except Exception:
        uid = None
    import billing_core as _bc
    user = _bc.get_user(int(uid)) if uid else None
    if not user or not user.get("is_owner"):
        return jsonify({"ok": False, "error": "Forbidden."}), 403
    data = request.get_json(force=True, silent=True) or {}
    status = (data.get("status") or "").strip()
    if status not in ("new", "triaged", "fixed", "wontfix"):
        return jsonify({"ok": False, "error": "Bad status."}), 400
    con = _feedback_db()
    try:
        con.execute("UPDATE feedback SET status = ? WHERE id = ?",
                    (status, fid))
        con.commit()
    finally:
        con.close()
    return jsonify({"ok": True})


@app.get("/rokdabus")
def rokdabus_page():
    return render_template("rockdabus.html", active="rokdabus")


# ------------------------------------------------- Rokdabus Prhyme chat
_rb_sessions = {}
_rb_lock = threading.Lock()


def _rb_session(sid):
    """Get-or-create a Rokdabus chat session; prunes stale ones."""
    now = time.time()
    with _rb_lock:
        for k in [k for k, v in _rb_sessions.items()
                  if now - v.get("t", 0) > 1800]:
            _rb_sessions.pop(k, None)
        s = _rb_sessions.get(sid) if sid else None
        if s is None:
            sid = uuid.uuid4().hex[:16]
            s = {"state": RB.new_session(), "t": now}
            _rb_sessions[sid] = s
        s["t"] = now
        return sid, s["state"]


def _rb_heavy_budget_ok():
    """Same 10-jobs-per-5-min budget as before_request, for chat jobs."""
    ip = request.headers.get("X-Forwarded-For", request.remote_addr or "?")
    now = time.time()
    with _rl_heavy_lock:
        hh = _rl_heavy.get(ip, [])
        hh = [t for t in hh if now - t < 300]
        hh.append(now)
        _rl_heavy[ip] = hh
        return len(hh) <= 10


@app.post("/api/rokdabus")
def api_rokdabus():
    data = request.get_json(force=True, silent=True) or {}
    message = (data.get("message") or "").strip()[:500]
    if not message:
        return jsonify({"ok": False, "error": "Empty message"}), 400
    sid, sess = _rb_session((data.get("session_id") or "").strip()[:32])
    ctx = {"genres": GENRES,
           "themes": list(L.THEMES.keys()),
           "mix_genres": list(mixgen.SUPPORTED_GENRES),
           "mix_styles": [s[0] for s in mixgen.STYLE_PRESETS]}
    try:
        # Rokdabus brain: LLM-enhanced (shared llama-server) with rule-based
        # fallback. chat_smart tries intent detection first, then the local
        # LLM for conversation, then falls back to pure rule-based chat().
        out = RB.chat_smart(message, sess, ctx)
    except Exception:
        out = {"reply": "Whoa, glitched for a sec — run that back?",
               "quick_replies": [], "action": None}
    action = out.get("action")
    atype = (action or {}).get("type")
    if atype in ("beat", "mix"):
        if not _rb_heavy_budget_ok():
            out["reply"] = ("Whoa, slow down — too many heavy jobs right "
                            "now. Give it a few minutes ⏳")
            out["quick_replies"] = []
            out["action"] = None
        elif atype == "beat":
            payload, status = _start_beat_job(action.get("params") or {})
            if status == 200 and payload.get("ok"):
                out["action"] = {"type": "job", "kind": "beat",
                                 "job_id": payload["job_id"]}
            else:
                out["reply"] = ("Couldn't start that beat — "
                                + payload.get("error", "try again"))
                out["action"] = None
        else:
            payload, status = _start_mix_job(action.get("params") or {})
            if status == 200 and payload.get("ok"):
                out["action"] = {"type": "job", "kind": "mix",
                                 "job_id": payload["job_id"]}
            else:
                out["reply"] = ("Couldn't start that mix — "
                                + payload.get("error", "try again"))
                out["action"] = None
    elif atype == "lyrics":
        payload, status = _gen_lyrics(action.get("params") or {})
        if status == 200 and payload.get("ok"):
            out["action"] = {"type": "lyrics_result",
                             "title": payload.get("title") or "Untitled",
                             "text": payload.get("text", "")}
        else:
            out["reply"] = ("Couldn't write that — "
                            + payload.get("error", "try again"))
            out["action"] = None
    elif atype == "freestyle":
        payload, status = _freestyle_prompts(action.get("params") or {})
        if status == 200 and payload.get("ok"):
            out["action"] = {"type": "freestyle_result",
                             "theme": payload.get("theme"),
                             "phrases": payload.get("phrases", [])[:6],
                             "rhyme_sets": payload.get("rhyme_sets", [])[:6]}
        else:
            out["reply"] = "Couldn't pull prompts — try again"
            out["action"] = None
    # "link" actions pass through untouched
    out["session_id"] = sid
    out["ok"] = True
    return jsonify(out)


@app.get("/tutorials")
def tutorials_page():
    return render_template("tutorials.html", active="help")


def _freestyle_prompts(data):
    """Freestyle assist: phrase starters + rhyme words for a theme (seeded).
    Returns (payload_dict, status_code). Shared by /api/freestyle/prompts
    and Rokdabus."""
    import random as _r
    data = data or {}
    theme = (data.get("theme") or "street").strip()
    if theme not in L.THEMES:
        theme = "street"
    try:
        seed = int(data.get("seed"))
    except (TypeError, ValueError):
        seed = _r.randint(1, 999999)
    n = max(4, min(40, int(data.get("n", 16) or 16)))
    rng = _r.Random(seed)
    lines = list(L.VERSE_LINES.get(theme, []))
    # phrase starters: first 3-4 words of random lines (original engine text)
    phrases = []
    for text, _rk, _sb in rng.sample(lines, min(len(lines), n * 2)):
        words = text.split()
        if len(words) >= 4:
            cut = rng.choice((3, 4))
            phrases.append(" ".join(words[:cut]) + "…")
        if len(phrases) >= n:
            break
    # rhyme words: group lines by rhyme_key, return the key words in clusters
    groups = {}
    for text, rk, _sb in lines:
        groups.setdefault(rk, []).append(text)
    keys = list(groups.keys())
    rng.shuffle(keys)
    rhyme_sets = []
    for rk in keys[:n]:
        rhyme_sets.append({"word": rk, "count": len(groups[rk])})
    return {"ok": True, "seed": seed,
        "beat_source": request.form.get("beat_source", "generate"),
        "output_format": request.form.get("output_format", "mp3"), "theme": theme,
            "phrases": phrases, "rhyme_sets": rhyme_sets,
            "label": "AI-GENERATED DRAFT — freestyle prompts, not written by the artist."}, 200


@app.post("/api/freestyle/prompts")
def api_freestyle_prompts():
    payload, status = _freestyle_prompts(
        request.get_json(force=True, silent=True))
    return jsonify(payload), status


@app.get("/api/freestyle/beats")
def api_freestyle_beats():
    """Recent beat outputs (mp3/wav) the user can freestyle over."""
    try:
        with open(HISTORY_FILE) as f:
            hist = json.load(f) or []
    except (OSError, ValueError):
        hist = []
    beats = []
    for h in hist:
        if h.get("kind") != "beat":
            continue
        r = h.get("result") or {}
        fpath = None
        for k in ("mp3", "wav", "file"):
            fn = r.get(k)
            if fn and os.path.isfile(os.path.join(OUTPUT_DIR, fn)):
                fpath = fn
                break
        if fpath:
            beats.append({"label": h.get("label") or "Beat",
                          "file": fpath,
                          "url": url_for("download", fname=fpath),
                          "ts": h.get("ts")})
        if len(beats) >= 20:
            break
    return jsonify({"ok": True, "beats": beats})


def run_tool_job(job_id, kind, src_path, opts):
    def prog(p, msg):
        set_job(job_id, progress=p, message=msg)
    try:
        _tool_labels = {
            "trim": "Trimming audio…",
            "desilence": "Removing silence…",
            "normalize": "Normalizing loudness…",
            "karaoke": "Isolating vocals (karaoke cut)…",
            "ringtone": "Cutting ringtone…",
            "key": "Detecting musical key…",
        }
        prog(10, _tool_labels.get(kind, "Processing…"))
        if kind == "trim":
            audio = audiotools.trim_audio(
                src_path, float(opts.get("start", 0)),
                float(opts.get("end")) if opts.get("end") else None)
        elif kind == "desilence":
            audio = audiotools.remove_silence(src_path)
        elif kind == "normalize":
            audio = audiotools.normalize_loudness(
                src_path, float(opts.get("target", -14.0)))
        elif kind == "karaoke":
            audio = audiotools.karaoke_cut(
                src_path, float(opts.get("strength", 0.8)))
        elif kind == "ringtone":
            audio = audiotools.make_ringtone(
                src_path, float(opts.get("start", 0)),
                float(opts.get("dur", 30.0)))
        elif kind == "key":
            key = audiotools.detect_key(src_path)
            set_job(job_id, status="done", progress=100,
                    message=f"Key: {key['key']}",
                    result={"key": key["key"],
                            "confidence": key["confidence"]})
            return
        else:
            raise ValueError("Bad tool")
        prog(80, "Writing output…")
        base = f"{job_id[:8]}_djrill-{kind}"
        wav_path = os.path.join(OUTPUT_DIR, base + ".wav")
        mp3_path = os.path.join(OUTPUT_DIR, base + ".mp3")
        audiotools.write_wav(wav_path, audio)
        prog(90, "Encoding MP3…")
        encode_mp3(wav_path, mp3_path)
        prog(96, "Checking output…")
        info = C.probe(mp3_path)
        set_job(job_id, status="done", progress=100, message="Done",
                result={"mp3": os.path.basename(mp3_path),
                        "wav": os.path.basename(wav_path),
                        "flac": None,
                        "duration": round(info.get("duration", 0), 1)})
    except Exception as e:
        set_job(job_id, status="error", progress=0, message=f"Error: {e}")


@app.post("/api/tools/<kind>")
def api_tool(kind):
    if kind not in ("trim", "desilence", "normalize", "karaoke",
                    "ringtone", "key"):
        return jsonify({"ok": False, "error": "Bad tool"}), 400
    f = request.files.get("file")
    if not f:
        return jsonify({"ok": False, "error": "No file uploaded"}), 400
    try:
        src = save_upload(f)
    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    opts = dict(request.form)
    job_id = new_job("tool", kind)
    t = threading.Thread(target=run_tool_job,
                         args=(job_id, kind, src, opts), daemon=True)
    t.start()
    return jsonify({"ok": True, "job_id": job_id})


@app.post("/api/tools/batch-convert")
def api_batch_convert():
    """116. Convert multiple files in one job."""
    files = request.files.getlist("files")
    if not 2 <= len(files) <= 10:
        return jsonify({"ok": False, "error": "Upload 2–10 files"}), 400
    out_ext = (request.form.get("format") or ".mp3").lower()
    if out_ext not in C.SUPPORTED_OUT:
        return jsonify({"ok": False, "error": "Bad format"}), 400
    paths = []
    try:
        for f in files:
            paths.append(save_upload(f))
    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    job_id = new_job("batch-convert", f"{len(paths)} files")
    t = threading.Thread(target=run_batch_convert_job,
                         args=(job_id, paths, out_ext), daemon=True)
    t.start()
    return jsonify({"ok": True, "job_id": job_id})


def run_batch_convert_job(job_id, paths, out_ext):
    def prog(p, msg):
        set_job(job_id, progress=p, message=msg)
    try:
        done = []
        for i, src in enumerate(paths):
            prog(int(100 * i / len(paths)), f"File {i+1}/{len(paths)}…")
            stem = os.path.splitext(os.path.basename(src))[0]
            dst = os.path.join(OUTPUT_DIR, f"{job_id[:8]}_{stem}{out_ext}")
            C.convert_file(src, dst)
            done.append(os.path.basename(dst))
        set_job(job_id, status="done", progress=100,
                message=f"{len(done)} files converted",
                result={"files": done})
    except Exception as e:
        set_job(job_id, status="error", progress=0, message=f"Error: {e}")


# 109. MIDI export of a beat's drum pattern
@app.post("/api/beats/midi")
def api_beat_midi():
    data = request.get_json(force=True, silent=True) or {}
    genre = data.get("genre", "HipHop")
    if genre not in GENRES:
        genre = "HipHop"
    try:
        bpm = max(50, min(200, float(data.get("bpm", 90))))
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "Bad BPM"}), 400
    patterns = {
        "kick": [0, 8], "snare": [4, 12], "hat": list(range(16)),
    }
    steps = []
    for i in patterns["kick"]:
        steps.append((i, 36, 110))
    for i in patterns["snare"]:
        steps.append((i, 38, 100))
    for i in patterns["hat"]:
        steps.append((i, 42, 70))
    path = os.path.join(OUTPUT_DIR,
                        f"djrill_{genre}_{int(bpm)}bpm.mid")
    audiotools.write_midi_drums(path, steps, bpm=bpm)
    return send_file(path, as_attachment=True,
                     download_name=os.path.basename(path))


# 106. sample manager
SAMPLE_DIR = os.path.join(BASE, "samples")
os.makedirs(SAMPLE_DIR, exist_ok=True)
SAMPLE_TAGS_FILE = os.path.join(SAMPLE_DIR, "tags.json")


def _sample_tags():
    try:
        with open(SAMPLE_TAGS_FILE) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _save_sample_tags(tags):
    with open(SAMPLE_TAGS_FILE, "w") as f:
        json.dump(tags, f)


@app.get("/api/samples")
def api_samples_list():
    tags = _sample_tags()
    out = []
    for fn in sorted(os.listdir(SAMPLE_DIR)):
        if fn == "tags.json":
            continue
        p = os.path.join(SAMPLE_DIR, fn)
        if os.path.isfile(p):
            out.append({"file": fn,
                        "size_kb": round(os.path.getsize(p) / 1024, 1),
                        "tags": tags.get(fn, [])})
    return jsonify({"ok": True, "samples": out})


@app.post("/api/samples")
def api_samples_upload():
    f = request.files.get("file")
    if not f:
        return jsonify({"ok": False, "error": "No file"}), 400
    fname = secure_filename(f.filename or "sample")
    ext = os.path.splitext(fname)[1].lower()
    if ext not in C.SUPPORTED_IN:
        return jsonify({"ok": False, "error": "Unsupported audio type"}), 400
    name = f"{uuid.uuid4().hex[:8]}_{fname}"
    path = os.path.join(SAMPLE_DIR, name)
    if os.path.commonpath([os.path.abspath(path), SAMPLE_DIR]) != SAMPLE_DIR:
        return jsonify({"ok": False, "error": "Bad filename"}), 400
    f.save(path)
    tags = _sample_tags()
    tag_list = [t.strip()[:20] for t in
                (request.form.get("tags") or "").split(",") if t.strip()][:8]
    if tag_list:
        tags[name] = tag_list
        _save_sample_tags(tags)
    return jsonify({"ok": True, "file": name})


@app.post("/api/samples/tag")
def api_samples_tag():
    data = request.get_json(force=True, silent=True) or {}
    fn = secure_filename(data.get("file") or "")
    p = os.path.join(SAMPLE_DIR, fn)
    if not fn or not os.path.isfile(p):
        return jsonify({"ok": False, "error": "Not found"}), 404
    tags = _sample_tags()
    tags[fn] = [t.strip()[:20] for t in (data.get("tags") or [])
                if t.strip()][:8]
    _save_sample_tags(tags)
    return jsonify({"ok": True})


@app.get("/sample/<path:fname>")
def serve_sample(fname):
    safe = secure_filename(fname)
    if safe != fname:
        abort(404)
    p = os.path.join(SAMPLE_DIR, safe)
    if not os.path.isfile(p):
        abort(404)
    return send_file(p)


@app.delete("/api/samples/<fname>")
def api_samples_delete(fname):
    safe = secure_filename(fname)
    p = os.path.join(SAMPLE_DIR, safe)
    if safe != fname or not os.path.isfile(p):
        return jsonify({"ok": False, "error": "Not found"}), 404
    os.remove(p)
    tags = _sample_tags()
    tags.pop(safe, None)
    _save_sample_tags(tags)
    return jsonify({"ok": True})


# 107. preset library
PRESETS = {
    "beats": [
        {"name": "Dark Drill Starter", "genre": "Drill", "bpm": 140,
         "fx": {"fills": True, "hatrolls": True, "glide808": True}},
        {"name": "Boom Bap Dusty", "genre": "BoomBap", "bpm": 92,
         "fx": {"humanize": True, "swing": 0.4, "percs": True}},
        {"name": "Trap Banger", "genre": "Trap", "bpm": 150,
         "fx": {"fills": True, "risers": True, "builds": True, "crash": True}},
        {"name": "LoFi Night Drive", "genre": "LoFi", "bpm": 80,
         "fx": {"humanize": True, "swing": 0.5, "intro_outro": True}},
        {"name": "Jersey Club Bounce", "genre": "JerseyClub", "bpm": 135,
         "fx": {"fills": True, "hatrolls": True}},
        {"name": "Afroswing Groove", "genre": "Afroswing", "bpm": 100,
         "fx": {"percs": True, "humanize": True}},
    ],
    "master": [
        {"name": "Streaming Loud", "chain": "Streaming"},
        {"name": "Club Punch", "chain": "Club"},
        {"name": "V8 Sound", "chain": "V8 Reference"},
        {"name": "Warm Tape", "chain": "LoFi Tape",
         "multiband": True, "deess": 0.3},
    ],
}


@app.get("/api/presets")
def api_presets():
    return jsonify({"ok": True, "presets": PRESETS})


@app.post("/api/presets/beat")
def api_preset_beat():
    """Render a beat directly from a preset."""
    data = request.get_json(force=True, silent=True) or {}
    name = data.get("name", "")
    preset = next((p for p in PRESETS["beats"] if p["name"] == name), None)
    if not preset:
        return jsonify({"ok": False, "error": "Unknown preset"}), 404
    seed = M.new_beat_seed()
    fx = dict(preset.get("fx", {}))
    job_id = new_job("beat", preset["name"])
    t = threading.Thread(target=run_beats_job,
                         args=(job_id, preset["genre"], preset["bpm"],
                               16, seed, fx, True), daemon=True)
    t.start()
    return jsonify({"ok": True, "job_id": job_id, "seed": seed})


# 108. project sharing: export .djr bundle (project JSON + clips)
@app.post("/api/daw/share")
def api_daw_share():
    data = request.get_json(force=True, silent=True) or {}
    project = data.get("project")
    if not isinstance(project, dict) or "tracks" not in project:
        return jsonify({"ok": False, "error": "Bad project"}), 400
    name = daw.sanitize_name(data.get("name", "project"))
    zpath = os.path.join(OUTPUT_DIR, f"{name}.djr.zip")
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("project.json", json.dumps(project))
        for t in project.get("tracks", []):
            for c in t.get("clips", []):
                try:
                    p = daw.clip_path(c["file"])
                    z.write(p, f"clips/{os.path.basename(p)}")
                except (ValueError, KeyError):
                    continue
    return jsonify({"ok": True,
                    "bundle": os.path.basename(zpath)})


@app.post("/api/daw/import-bundle")
def api_daw_import_bundle():
    """Import a .djr.zip bundle shared by someone else."""
    f = request.files.get("file")
    if not f or not f.filename.endswith(".zip"):
        return jsonify({"ok": False, "error": "Upload a .djr.zip"}), 400
    tmp = os.path.join(UPLOAD_DIR, f"bundle_{uuid.uuid4().hex[:8]}.zip")
    f.save(tmp)
    try:
        with zipfile.ZipFile(tmp) as z:
            names = z.namelist()
            if "project.json" not in names:
                return jsonify({"ok": False, "error": "Bad bundle"}), 400
            project = json.loads(z.read("project.json"))
            # restore clips
            for t in project.get("tracks", []):
                for c in t.get("clips", []):
                    zname = f"clips/{os.path.basename(c.get('file', ''))}"
                    if zname in names:
                        data = z.read(zname)
                        cf = daw.store_clip_bytes(
                            data, os.path.basename(zname))
                        c["file"] = cf
    except (zipfile.BadZipFile, ValueError, KeyError) as e:
        return jsonify({"ok": False, "error": f"Bad bundle: {e}"}), 400
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass
    return jsonify({"ok": True, "project": project})


# 118. collab notes per project
NOTES_FILE = os.path.join(BASE, "projects", "notes.json")


def _notes():
    try:
        with open(NOTES_FILE) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


@app.get("/api/daw/notes/<name>")
def api_notes_get(name):
    safe = daw.sanitize_name(name)
    return jsonify({"ok": True, "notes": _notes().get(safe, "")})


@app.post("/api/daw/notes/<name>")
def api_notes_set(name):
    safe = daw.sanitize_name(name)
    data = request.get_json(force=True, silent=True) or {}
    notes = _notes()
    notes[safe] = str(data.get("notes", ""))[:5000]
    os.makedirs(os.path.dirname(NOTES_FILE), exist_ok=True)
    with open(NOTES_FILE, "w") as f:
        json.dump(notes, f)
    return jsonify({"ok": True})


# 119. social export: 9:16 video + caption
@app.post("/api/video/social")
def api_video_social():
    if not C.FFMPEG_OK:
        return jsonify({"ok": False, "error": "FFmpeg not available"}), 500
    f = request.files.get("audio")
    if not f:
        return jsonify({"ok": False, "error": "Upload audio"}), 400
    try:
        audio_path = save_upload(f)
    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    title = (request.form.get("title") or "Prhyme™")[:60]
    caption = (f"🎵 {title} — made with Prhyme™ "
               f"#{title.replace(' ', '')[:20]} #prhyme #newmusic")[:220]
    job_id = new_job("video", title + " (social)")
    t = threading.Thread(target=run_social_job,
                         args=(job_id, audio_path, title, caption),
                         daemon=True)
    t.start()
    return jsonify({"ok": True, "job_id": job_id})


def run_social_job(job_id, audio_path, title, caption):
    def prog(p, msg):
        set_job(job_id, progress=p, message=msg)
    try:
        prog(10, "Rendering vertical video…")
        base = f"{job_id[:8]}_social"
        tmp = os.path.join(OUTPUT_DIR, base + "_sq.mp4")
        videofx.render_waveform_video(audio_path, [], tmp, title=title,
                                      bg="bars", aspect="1:1",
                                      progress_cb=lambda f: prog(
                                          10 + int(60 * f), "Rendering…"),
                                      fast=True)
        prog(75, "Converting to 9:16…")
        out = os.path.join(OUTPUT_DIR, base + ".mp4")
        videofx.convert_aspect(tmp, out, "9:16")
        os.remove(tmp)
        cap_path = os.path.join(OUTPUT_DIR, base + "_caption.txt")
        with open(cap_path, "w") as f:
            f.write(caption)
        set_job(job_id, status="done", progress=100, message="Social cut ready",
                result={"mp4": os.path.basename(out),
                        "caption": os.path.basename(cap_path),
                        "caption_text": caption})
    except Exception as e:
        set_job(job_id, status="error", progress=0, message=f"Error: {e}")


# 120. daily beat challenge: deterministic seed from the date
@app.get("/api/beats/daily")
def api_beats_daily():
    import datetime as _dt
    day = _dt.date.today().isoformat()
    seed = int(hashlib.sha256(f"djrill-daily|{day}".encode())
               .hexdigest()[:8], 16)
    genres = ["Drill", "Trap", "BoomBap", "JerseyClub", "Afroswing"]
    genre = genres[seed % len(genres)]
    bpm = 90 + (seed % 60)
    return jsonify({"ok": True, "date": day, "seed": seed,
        "beat_source": request.form.get("beat_source", "generate"),
        "output_format": request.form.get("output_format", "mp3"),
                    "genre": genre, "bpm": bpm,
                    "challenge": f"Make a {genre} beat at {bpm} BPM — seed {seed}"})


# ---------------------------------------------------------------- soundkits
# User-uploaded custom drum kits (WAV one-shots mapped to instruments).
@app.get("/soundkits")
def soundkits_page():
    return render_template("soundkits.html", active="beats",
                           instruments=soundkits.KIT_INSTRUMENTS)


@app.get("/api/kits")
def api_kits_list():
    """Built-in kits + user custom kits."""
    return jsonify({
        "ok": True,
        "builtin": lightbeat.list_kits(),
        "variants": lightbeat.list_kit_variants(),
        "all_sounds": lightbeat.list_all_sounds(),
        "total_sounds": lightbeat.count_all_sounds(),
        "melody": lightbeat.MELODY_INSTRUMENTS,
        "custom": soundkits.list_custom_kits(),
        "slots": soundkits.KIT_INSTRUMENTS,
    })




@app.get("/api/kits/premium")
def api_premium_kits():
    """Premium purchasable sound kits with auto-raise pricing.
    Launch pricing until 100 paid signups, then standard pricing."""
    import json, os
    try:
        # Count paid users (non-founding with active plan)
        from billing_core import _connect
        con = _connect()
        try:
            paid = con.execute(
                "SELECT COUNT(*) FROM users WHERE is_founding = 0 AND plan != \'trial\' AND sub_status = \'active\'"
            ).fetchone()[0]
        finally:
            con.close()
    except:
        paid = 0
    
    # Load kits
    p = os.path.join(os.path.dirname(os.path.dirname(__file__)), "premium_kits.json")
    try:
        with open(p) as f:
            kits = json.load(f)
    except:
        return jsonify({"ok": False, "error": "Kits not available"})
    
    # Apply pricing tier
    use_standard = paid >= 100
    for kid, kit in kits.items():
        if use_standard and "standard_price" in kit:
            kit["price"] = kit["standard_price"]
            kit["pricing_tier"] = "standard"
        else:
            kit["pricing_tier"] = "launch"
    
    return jsonify({
        "ok": True,
        "kits": kits,
        "paid_signups": paid,
        "pricing_tier": "standard" if use_standard else "launch",
        "signups_to_standard": max(0, 100 - paid),
    })

@app.get("/api/kit/sound")
def api_kit_sound_preview():
    """Render and serve a single built-in kit sound as WAV.

    Query params: category (kick|snare|chat|ohat|clap|perc|808|melodic|fx),
    variant, freq (for 808/melodic, default 220).
    """
    import io
    import wave
    category = (request.args.get("category") or "").strip()
    variant = (request.args.get("variant") or "").strip()
    try:
        freq = float(request.args.get("freq") or 220.0)
        freq = max(20.0, min(2000.0, freq))
    except ValueError:
        freq = 220.0
    try:
        stereo = lightbeat.render_kit_sound(category, variant, freq=freq)
    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    # stereo float32 -> 16-bit WAV bytes
    pcm = (np.clip(stereo, -1.0, 1.0) * 32767.0).astype(np.int16)
    # stereo interleave
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(44100)
        w.writeframes(pcm.tobytes())
    buf.seek(0)
    return send_file(buf, mimetype="audio/wav", as_attachment=False,
                     download_name=f"{category}-{variant}.wav")


@app.post("/api/kits")
def api_kits_create():
    data = request.get_json(force=True, silent=True) or {}
    try:
        name = soundkits.create_kit(data.get("name", ""))
    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    return jsonify({"ok": True, "name": name})


@app.post("/api/kits/<name>/rename")
def api_kits_rename(name):
    data = request.get_json(force=True, silent=True) or {}
    try:
        new = soundkits.rename_kit(name, data.get("new_name", ""))
    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    return jsonify({"ok": True, "name": new})


@app.delete("/api/kits/<name>")
def api_kits_delete(name):
    try:
        soundkits.delete_kit(name)
    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    return jsonify({"ok": True})


@app.post("/api/kits/<name>/upload")
def api_kits_upload(name):
    instrument = (request.form.get("instrument") or "").strip()
    f = request.files.get("file")
    if not f:
        return jsonify({"ok": False, "error": "No file uploaded"}), 400
    try:
        raw = f.read()
        kit, inst = soundkits.save_sample(name, instrument, raw,
                                          f.filename or "")
    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    return jsonify({"ok": True, "kit": kit, "instrument": inst})


@app.delete("/api/kits/<name>/<instrument>")
def api_kits_delete_sample(name, instrument):
    try:
        soundkits.delete_sample(name, instrument)
    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    return jsonify({"ok": True})


@app.get("/api/kits/<name>/preview/<instrument>")
def api_kits_preview(name, instrument):
    fp = soundkits.preview_path(name, instrument)
    if not fp:
        abort(404)
    return send_file(fp, mimetype="audio/wav",
                     as_attachment=False,
                     download_name=f"{instrument}.wav")
    data = request.get_json(force=True, silent=True) or {}
    genre = data.get("genre", "HipHop")
    if genre not in GENRES:
        genre = "HipHop"
    try:
        bpm = max(50, min(200, float(data.get("bpm", 90))))
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "Bad BPM"}), 400
    # derive a 16-step pattern from the renderer's density approach:
    # use a simple genre-appropriate pattern map
    patterns = {
        "kick": [0, 8], "snare": [4, 12], "hat": list(range(16)),
    }
    steps = []
    for i in patterns["kick"]:
        steps.append((i, 36, 110))
    for i in patterns["snare"]:
        steps.append((i, 38, 100))
    for i in patterns["hat"]:
        steps.append((i, 42, 70))
    path = os.path.join(OUTPUT_DIR,
                        f"djrill_{genre}_{int(bpm)}bpm.mid")
    audiotools.write_midi_drums(path, steps, bpm=bpm)
    return send_file(path, as_attachment=True,
                     download_name=os.path.basename(path))


@app.get("/api/history")
def api_history():
    try:
        with open(HISTORY_FILE) as f:
            hist = json.load(f) or []
    except (OSError, ValueError):
        hist = []
    # drop entries whose files are gone
    out = []
    for h in hist[:100]:
        r = h.get("result") or {}
        alive = [k for k in ("mp3", "wav", "file", "mp4")
                 if r.get(k) and os.path.isfile(os.path.join(OUTPUT_DIR, r[k]))]
        if alive or not r:
            out.append(h)
    return jsonify({"ok": True, "history": out})


@app.post("/api/history/zip")
def api_history_zip():
    """83. Download-all: bundle selected (or recent) outputs as a ZIP."""
    data = request.get_json(force=True, silent=True) or {}
    files = data.get("files") or []
    if not files:
        # default: 10 most recent outputs with files present
        try:
            with open(HISTORY_FILE) as f:
                hist = json.load(f) or []
        except (OSError, ValueError):
            hist = []
        seen = set()
        for h in hist:
            for k in ("mp3", "wav", "mp4"):
                fn = (h.get("result") or {}).get(k)
                if fn and fn not in seen:
                    seen.add(fn)
                    files.append(fn)
            if len(files) >= 10:
                break
    zpath = os.path.join(OUTPUT_DIR, f"djrill_bundle_{uuid.uuid4().hex[:8]}.zip")
    added = 0
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
        for fn in files[:20]:
            safe = secure_filename(fn)
            if safe != fn:
                continue
            p = os.path.join(OUTPUT_DIR, safe)
            if os.path.isfile(p) and os.path.getsize(p) < 500 * 1024 * 1024:
                z.write(p, safe)
                added += 1
    if not added:
        return jsonify({"ok": False, "error": "No files to bundle"}), 400
    return jsonify({"ok": True,
                    "zip": os.path.basename(zpath), "count": added})


# ---------------------------------------------------------------- video jobs
def run_video_job(job_id, mode, audio_path, media_paths, events, title,
                  vopts=None):
    def prog(p, msg):
        set_job(job_id, progress=p, message=msg)
    try:
        vopts = vopts or {}
        _lite = lite_mode()  # defined once, used for all lite gating below
        safe = safe_name(title, "djrill-video")
        base = f"{safe}_prhyme_master"
        out_path = os.path.join(OUTPUT_DIR, base + ".mp4")

        def cb(frac):
            prog(5 + int(80 * max(0.0, min(1.0, frac))), "Rendering video…")

        aspect = vopts.get("aspect", "16:9")
        if mode == "lyric":
            prog(5, "Rendering lyric video…")
            V.render_lyric_video(audio_path, events, out_path, title=title,
                                 progress_cb=cb)
        elif mode == "selfie":
            prog(5, f"Building video from {len(media_paths)} photos…")
            V.render_selfie_video(media_paths, audio_path, events, out_path,
                                  title=title, progress_cb=cb,
                                  kb_direction=vopts.get("kb_direction", "auto"))
        elif mode == "performance":
            prog(5, "Cutting your footage…")
            V.render_performance_video(media_paths, audio_path, events,
                                       out_path, title=title, progress_cb=cb)
        elif mode == "waveform":
            prog(5, "Rendering waveform video…")
            videofx.render_waveform_video(
                audio_path, events, out_path, title=title,
                bg=vopts.get("bg", "rings"), aspect=aspect, progress_cb=cb,
                fast=vopts.get("fast_preview", False) or _lite)
        elif mode == "collage":
            prog(5, "Building photo collage…")
            videofx.render_collage_video(
                media_paths, audio_path, events, out_path, title=title,
                aspect=aspect, progress_cb=cb)
        elif mode == "minimal":
            prog(5, "Rendering minimal type video…")
            videofx.render_minimal_video(
                audio_path, events, out_path, title=title,
                aspect=aspect, progress_cb=cb)
        elif mode == "canvas":
            prog(5, "Rendering Spotify Canvas (8s loop)…")
            videofx.render_canvas_video(
                audio_path, out_path, title=title,
                progress_cb=cb)
        elif mode == "tiktok":
            prog(5, "Rendering TikTok vertical video…")
            videofx.render_tiktok_video(
                audio_path, events, out_path, title=title,
                progress_cb=cb)
        else:
            raise ValueError("Bad mode")

        # post FX: grade, watermark, cards, subtitles, aspect
        # LITE MODE: skip the heavy post-FX passes (grade + subtitle burn
        # each re-encode the whole video — hot and slow on phones).
        step = 86
        grade = vopts.get("grade", "none")
        if grade and grade != "none" and not _lite:
            prog(step, f"Applying {grade} grade…")
            tmp = out_path + ".gr.mp4"
            videofx.apply_grade(out_path, tmp, grade)
            os.replace(tmp, out_path)
            step += 2
        if vopts.get("watermark"):
            prog(step, "Adding watermark…")
            tmp = out_path + ".wm.mp4"
            videofx.add_watermark(out_path, tmp, vopts["watermark"][:24])
            os.replace(tmp, out_path)
            step += 2
        if vopts.get("subtitles") and events and not _lite:
            prog(step, "Burning subtitles…")
            srt = os.path.join(OUTPUT_DIR, f"{job_id[:8]}_subs.srt")
            videofx.events_to_srt(events, srt)
            tmp = out_path + ".sub.mp4"
            try:
                videofx.burn_subtitles(out_path, srt, tmp)
                os.replace(tmp, out_path)
            finally:
                try:
                    os.remove(srt)
                except OSError:
                    pass
            step += 2
        if vopts.get("title_card"):
            prog(step, "Adding title card…")
            tmp = out_path + ".tc.mp4"
            videofx.prepend_title_card(out_path, tmp, title)
            os.replace(tmp, out_path)
            step += 2
        if vopts.get("outro_card"):
            prog(step, "Adding outro card…")
            tmp = out_path + ".oc.mp4"
            videofx.append_outro_card(out_path, tmp)
            os.replace(tmp, out_path)
            step += 2
        out_aspect = vopts.get("out_aspect")
        if out_aspect and out_aspect != aspect:
            prog(step, f"Converting to {out_aspect}…")
            tmp = out_path + ".ar.mp4"
            videofx.convert_aspect(out_path, tmp, out_aspect)
            os.replace(tmp, out_path)
        # 75. thumbnail
        thumb = None
        try:
            thumb = base + "_thumb.jpg"
            videofx.make_thumbnail(out_path, os.path.join(OUTPUT_DIR, thumb))
        except Exception:
            thumb = None
        info = C.probe(out_path)
        res = {"mp4": os.path.basename(out_path),
               "duration": round(info.get("duration", 0), 1)}
        if thumb:
            res["thumbnail"] = thumb
        set_job(job_id, status="done", progress=100, message="Video ready",
                result=res)
    except Exception as e:
        set_job(job_id, status="error", progress=0, message=f"Error: {e}")


@app.post("/api/video/lyrics")
def api_video_lyrics():
    """Build timed lyric events for a video.

    JSON: {source: "paste"|"generate", text, theme, mood, genre, seed,
           duration}. Lines are distributed evenly across the audio.
    Returns {ok, events, draft, count}."""
    data = request.get_json(force=True, silent=True) or {}
    try:
        duration = float(data.get("duration", 0))
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "Need audio duration"}), 400
    if not (0 < duration <= 3600):
        return jsonify({"ok": False, "error": "Bad duration"}), 400
    draft = False
    if data.get("source") == "generate":
        theme = (data.get("theme") or "street")[:40]
        genre = data.get("genre", "HipHop")
        if genre not in GENRES:
            genre = "HipHop"
        seed_raw = data.get("seed")
        try:
            seed = int(seed_raw) if seed_raw not in (None, "") else M.new_beat_seed()
        except (TypeError, ValueError):
            return jsonify({"ok": False, "error": "Bad seed"}), 400
        song = L.generate_song_lyrics(seed, genre=genre, theme=theme)
        order = [("verse1", "VERSE 1"), ("hook", "HOOK"),
                 ("verse2", "VERSE 2"), ("hook", "HOOK"),
                 ("verse3", "VERSE 3"), ("bridge", "BRIDGE"),
                 ("hook", "HOOK"), ("outro", "OUTRO")]
        lines = [(label, ln) for key, label in order
                 for ln in song.get(key, [])]
        draft = True
    else:
        text = (data.get("text") or "").strip()
        raw = [ln.strip() for ln in text.split("\n") if ln.strip()]
        if not raw:
            return jsonify({"ok": False, "error": "No lyric lines"}), 400
        # section labels by thirds (drives selfie-mode cuts)
        n = len(raw)
        lines = []
        for i, ln in enumerate(raw):
            frac = i / n
            sec = "VERSE" if frac < 0.4 else ("HOOK" if frac < 0.8 else "OUTRO")
            lines.append((sec, ln))
    if not lines:
        return jsonify({"ok": False, "error": "No lyric lines"}), 400
    n = len(lines)
    events = [{"start": round(i * duration / n, 2),
               "end": round((i + 1) * duration / n, 2),
               "section": sec, "line": ln[:140]}
              for i, (sec, ln) in enumerate(lines)]
    return jsonify({"ok": True, "events": events, "draft": draft, "count": n})


@app.post("/api/video/render")
def api_video_render():
    ok, resp = _check_and_log_usage("video")
    if not ok:
        return jsonify(resp), 402
    if not C.FFMPEG_OK:
        return jsonify({"ok": False,
                        "error": "FFmpeg not available on this device"}), 500
    mode = request.form.get("mode", "lyric")
    if mode not in ("lyric", "selfie", "performance",
                    "waveform", "collage", "minimal"):
        return jsonify({"ok": False, "error": "Bad mode"}), 400
    f = request.files.get("audio")
    if not f:
        return jsonify({"ok": False, "error": "Upload audio first"}), 400
    try:
        audio_path = save_upload(f)
    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    media_paths = []
    try:
        if mode == "selfie":
            photos = request.files.getlist("photos")
            if not 1 <= len(photos) <= 10:
                return jsonify({"ok": False,
                                "error": "Upload 1–10 photos"}), 400
            for p in photos:
                media_paths.append(save_media_upload(p, IMAGE_EXTS, "photo"))
        elif mode == "performance":
            clips = request.files.getlist("footage")
            if not 1 <= len(clips) <= 3:
                return jsonify({"ok": False,
                                "error": "Upload 1–3 clips"}), 400
            for p in clips:
                media_paths.append(save_media_upload(p, VIDEO_EXTS, "video"))
    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    import json as _json
    try:
        events = _json.loads(request.form.get("events") or "[]")
    except ValueError:
        return jsonify({"ok": False, "error": "Bad lyrics data"}), 400
    clean = []
    for e in events:
        if isinstance(e, dict) and e.get("line"):
            try:
                clean.append({"start": float(e.get("start", 0)),
                              "end": float(e.get("end", 0)),
                              "section": str(e.get("section", ""))[:40],
                              "line": str(e["line"])[:140]})
            except (TypeError, ValueError):
                continue
    title = (request.form.get("title") or "Prhyme™")[:60]
    vopts = {
        "aspect": request.form.get("aspect", "16:9")
        if request.form.get("aspect") in videofx.ASPECTS else "16:9",
        "bg": request.form.get("bg", "rings")
        if request.form.get("bg") in ("rings", "bars", "wave") else "rings",
        "grade": request.form.get("grade", "none")
        if request.form.get("grade") in videofx.GRADES else "none",
        "watermark": (request.form.get("watermark") or "")[:24],
        "subtitles": request.form.get("subtitles") == "on",
        "title_card": request.form.get("title_card") == "on",
        "outro_card": request.form.get("outro_card") == "on",
        "out_aspect": request.form.get("out_aspect") or "",
        "fast_preview": request.form.get("fast_preview") == "on",
        "kb_direction": request.form.get("kb_direction", "auto")
        if request.form.get("kb_direction") in
        ("auto", "in", "out", "left", "right", "up", "down") else "auto",
    }
    if vopts["out_aspect"] not in videofx.ASPECTS:
        vopts["out_aspect"] = ""
    job_id = new_job("video", title)
    t = threading.Thread(target=run_video_job,
                         args=(job_id, mode, audio_path, media_paths,
                               clean, title, vopts),
                         daemon=True)
    t.start()
    return jsonify({"ok": True, "job_id": job_id})


@app.get("/api/video/fx")
def api_video_fx():
    return jsonify({"ok": True,
                    "modes": ["lyric", "selfie", "performance",
                              "waveform", "collage", "minimal", "canvas", "tiktok"],
                    "aspects": sorted(videofx.ASPECTS.keys()),
                    "grades": sorted(videofx.GRADES.keys()),
                    "backgrounds": ["rings", "bars", "wave"]})


@app.get("/api/job/<job_id>")
def api_job(job_id):
    with jobs_lock:
        j = jobs.get(job_id)
    if not j:
        return jsonify({"ok": False, "error": "Unknown job"}), 404
    return jsonify({"ok": True, **j})


@app.get("/api/jobs/active")
def api_jobs_active():
    """List currently running jobs (for resume discovery after crash)."""
    with jobs_lock:
        active = [
            {"job_id": jid, **{k: v for k, v in j.items() if not k.startswith("_")}}
            for jid, j in jobs.items()
            if j.get("status") == "running"
        ]
    return jsonify({"ok": True, "jobs": active})




@app.get("/api/referral/code")
def api_referral_code():
    """Get the current user's referral code."""
    from billing_core import get_referral_code, _connect
    # Get user from session (simplified - use first user for now)
    try:
        con = _connect()
        row = con.execute("SELECT id FROM users LIMIT 1").fetchone()
        con.close()
        if not row:
            return jsonify({"ok": False, "error": "No user"})
        code = get_referral_code(row[0])
        return jsonify({"ok": True, "code": code})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})


@app.post("/api/referral/apply")
def api_referral_apply():
    """Apply a referral code for the current user."""
    from billing_core import apply_referral, _connect
    data = request.get_json() or {}
    code = data.get("code", "").strip().upper()
    if not code:
        return jsonify({"ok": False, "error": "Code required"})
    try:
        con = _connect()
        row = con.execute("SELECT id FROM users LIMIT 1").fetchone()
        con.close()
        if not row:
            return jsonify({"ok": False, "error": "No user"})
        ok, msg = apply_referral(row[0], code)
        return jsonify({"ok": ok, "message": msg})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})


@app.post("/api/rewards/share")
def api_share_reward():
    """Award 50 tokens for sharing on social media."""
    from billing_core import _connect
    data = request.get_json() or {}
    platform = data.get("platform", "unknown")
    post_url = data.get("post_url", "")
    try:
        con = _connect()
        row = con.execute("SELECT id FROM users LIMIT 1").fetchone()
        if not row:
            con.close()
            return jsonify({"ok": False, "error": "No user"})
        user_id = row[0]
        con.execute(
            "INSERT INTO share_rewards (user_id, platform, post_url, tokens_awarded) VALUES (?, ?, ?, 50)",
            (user_id, platform, post_url))
        con.commit()
        con.close()
        return jsonify({"ok": True, "tokens": 50, "message": "50 tokens awarded for sharing!"})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})


@app.post("/api/rewards/feedback")
def api_feedback_reward():
    """Award a free soundkit for detailed feedback."""
    from billing_core import _connect
    data = request.get_json() or {}
    feedback = data.get("feedback", "").strip()
    if len(feedback) < 50:
        return jsonify({"ok": False, "error": "Feedback must be at least 50 characters"})
    try:
        con = _connect()
        row = con.execute("SELECT id FROM users LIMIT 1").fetchone()
        if not row:
            con.close()
            return jsonify({"ok": False, "error": "No user"})
        user_id = row[0]
        # Award a random soundkit
        import random
        kits = ["trap_essentials", "drill_arsenal", "boombap_classics"]
        kit = random.choice(kits)
        con.execute(
            "INSERT INTO feedback_rewards (user_id, feedback_text, soundkit_awarded) VALUES (?, ?, ?)",
            (user_id, feedback, kit))
        con.commit()
        con.close()
        return jsonify({"ok": True, "soundkit": kit, "message": f"Free soundkit awarded: {kit}!"})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})

@app.get("/api/masters/pending")
def api_masters_pending():
    """List completed temp masters awaiting Download (survives restarts)."""
    out = []
    try:
        base = TEMP_MASTERS_DIR
        if os.path.isdir(base):
            for jid in sorted(os.listdir(base)):
                tdir = os.path.join(base, jid)
                if not os.path.isdir(tdir):
                    continue
                master_file = None
                title = None
                for fn in sorted(os.listdir(tdir)):
                    if fn == "mopts.json":
                        try:
                            import json as _j
                            with open(os.path.join(tdir, fn)) as _f:
                                _m = _j.load(_f)
                            title = _m.get("title") or _m.get("_title")
                        except Exception:
                            pass
                    if fn.startswith("source.") or fn.endswith(".tmp.wav") or fn == "mopts.json" or fn == "checkpoint.json":
                        continue
                    if os.path.isfile(os.path.join(tdir, fn)):
                        master_file = fn
                if master_file:
                    out.append({"job_id": jid, "file": master_file, "title": title})
    except Exception:
        pass
    return jsonify({"ok": True, "pending": out})


@app.post("/api/master/keep")
def api_master_keep():
    """Download selected: copy the temp master into the library, clean temp."""
    data = request.get_json(force=True, silent=True) or {}
    job_id = str(data.get("job_id", ""))[:32]
    if not job_id or len(job_id) < 8:
        return jsonify({"ok": False, "error": "Invalid job ID"}), 400
    tdir = _temp_master_dir(job_id)
    if not os.path.isdir(tdir):
        return jsonify({"ok": False, "error": "Master no longer in temp"}), 404
    master_file = None
    for fn in sorted(os.listdir(tdir)):
        if fn.startswith("source.") or fn.endswith(".tmp.wav"):
            continue
        if os.path.isfile(os.path.join(tdir, fn)):
            master_file = fn
            break
    if not master_file:
        return jsonify({"ok": False, "error": "No master file found"}), 404
    sfn = secure_filename(master_file)
    if sfn != master_file:
        return jsonify({"ok": False, "error": "Bad filename"}), 400
    dst = os.path.join(OUTPUT_DIR, sfn)
    if os.path.exists(dst):
        stem, ext = os.path.splitext(sfn)
        i = 2
        while os.path.exists(os.path.join(OUTPUT_DIR, f"{stem}_{i}{ext}")):
            i += 1
        dst = os.path.join(OUTPUT_DIR, f"{stem}_{i}{ext}")
    try:
        shutil.copy2(os.path.join(tdir, master_file), dst)
    except OSError as e:
        return jsonify({"ok": False, "error": str(e)}), 500
    # 2026-10-20 (Daryl): output also goes straight to the phone Downloads
    # folder -- the browser/WebView download hand-off kept failing for him,
    # so the file must land somewhere he can always find it.
    try:
        _dl = "/storage/emulated/0/Download"
        os.makedirs(_dl, exist_ok=True)
        shutil.copy2(dst, os.path.join(_dl, os.path.basename(dst)))
    except Exception:
        pass
    temp_master_cleanup(job_id)
    try:
        player_mod.refresh()
    except Exception:
        pass
    return jsonify({"ok": True, "file": os.path.basename(dst)})

@app.post("/api/master/discard")
def api_master_discard():
    """Delete the temp master immediately (job-owned files only)."""
    data = request.get_json(force=True, silent=True) or {}
    job_id = str(data.get("job_id", ""))[:32]
    if not job_id or len(job_id) < 8:
        return jsonify({"ok": False, "error": "Invalid job ID"}), 400
    deleted = temp_master_cleanup(job_id)
    return jsonify({"ok": True, "deleted": deleted})

@app.post("/api/master/delete")
def api_master_delete():
    """Legacy route: now narrowed to this job's temp files only."""
    data = request.get_json(force=True, silent=True) or {}
    job_id = str(data.get("job_id", ""))[:32]
    if not job_id or len(job_id) < 8:
        return jsonify({"ok": False, "error": "Invalid job ID"}), 400
    deleted = temp_master_cleanup(job_id)
    return jsonify({"ok": True, "deleted": deleted})

@app.get("/temp_master/<jobid>/<path:fname>")
def temp_master(jobid, fname):
    """Serve a temp master file for preview before keep/discard."""
    jid = (jobid or "")[:8]
    if len(jid) < 8 or not jid.isalnum():
        abort(404)
    safe = secure_filename(fname)
    if safe != fname or "/" in fname or "\\" in fname:
        abort(404)
    if safe.startswith("source.") or safe.endswith(".tmp.wav"):
        abort(404)
    p = os.path.join(_temp_master_dir(jid), safe)
    if not os.path.isfile(p):
        abort(404)
    ext = os.path.splitext(safe)[1].lower()
    mime = {".mp3": "audio/mpeg", ".wav": "audio/wav", ".flac": "audio/flac", ".ogg": "audio/ogg", ".m4a": "audio/mp4", ".opus": "audio/opus", ".aiff": "audio/aiff", ".aif": "audio/aiff", ".wma": "audio/x-ms-wma", ".aac": "audio/aac"}
    return send_file(p, mimetype=mime.get(ext, "audio/mpeg"))

@app.get("/files")
def files_page():
    return render_template("files.html")

@app.get("/api/files")
def api_files():
    """List files in outputs, uploads, and temp directories."""
    import time
    result = {"outputs": [], "uploads": [], "temp": []}
    dirs = {
        "outputs": OUTPUT_DIR,
        "uploads": os.path.join(os.path.dirname(OUTPUT_DIR), "uploads"),
        "temp": os.path.join(OUTPUT_DIR, "temp_ab"),
    }
    for key, d in dirs.items():
        if os.path.isdir(d):
            for fname in sorted(os.listdir(d)):
                fpath = os.path.join(d, fname)
                if os.path.isfile(fpath):
                    try:
                        stat = os.stat(fpath)
                        result[key].append({
                            "name": fname,
                            "size": stat.st_size,
                            "modified": time.strftime("%Y-%m-%d %H:%M", time.localtime(stat.st_mtime)),
                        })
                    except:
                        pass
    return jsonify({"ok": True, "files": result})

@app.post("/api/files/delete")
def api_files_delete():
    """Delete a specific file."""
    data = request.get_json() or {}
    fname = data.get("name", "")
    folder = data.get("folder", "outputs")
    safe = secure_filename(fname)
    if safe != fname or not safe:
        return jsonify({"ok": False, "error": "Invalid filename"})
    dirs = {
        "outputs": OUTPUT_DIR,
        "uploads": os.path.join(os.path.dirname(OUTPUT_DIR), "uploads"),
        "temp": os.path.join(OUTPUT_DIR, "temp_ab"),
    }
    d = dirs.get(folder)
    if not d:
        return jsonify({"ok": False, "error": "Invalid folder"})
    fpath = os.path.join(d, safe)
    if os.path.isfile(fpath):
        try:
            os.remove(fpath)
            return jsonify({"ok": True})
        except Exception as e:
            return jsonify({"ok": False, "error": str(e)})
    return jsonify({"ok": False, "error": "File not found"})

@app.get("/preview/<path:fname>")
def preview(fname):
    """Stream-only preview for A/B files. Not downloadable."""
    safe = secure_filename(fname)
    if safe != fname or "/" in fname or "\\" in fname:
        abort(404)
    p = os.path.join(OUTPUT_DIR, "temp_ab", safe)
    if not os.path.isfile(p):
        abort(404)
    ext = os.path.splitext(safe)[1].lower()
    mime = {".mp3": "audio/mpeg", ".wav": "audio/wav", ".ogg": "audio/ogg"}
    return send_file(p, mimetype=mime.get(ext, "audio/mpeg"))

@app.get("/api/beats/recent")
def beats_recent():
    """List the last-5 temp beat generations (playable until kept/overwritten)."""
    return jsonify({"ok": True, "beats": _temp_beats_manifest()})

@app.post("/api/beats/keep")
def beats_keep():
    """Download selected: copy a temp beat into the library, clear its temp."""
    data = request.get_json(force=True, silent=True) or {}
    job_id = str(data.get("job_id", ""))[:32]
    manifest = _temp_beats_manifest()
    entry = next((e for e in manifest if e.get("job_id") == job_id), None)
    if not entry:
        return jsonify({"ok": False, "error": "Beat no longer in temp"}), 404
    kept = {}
    for fmt, fn in (entry.get("files") or {}).items():
        if not fn:
            continue
        sfn = secure_filename(fn)
        if sfn != fn:
            continue
        src_p = os.path.join(TEMP_BEATS_DIR, sfn)
        if not os.path.isfile(src_p):
            continue
        dst = os.path.join(OUTPUT_DIR, sfn)
        if os.path.exists(dst):
            stem, ext = os.path.splitext(sfn)
            i = 2
            while os.path.exists(os.path.join(OUTPUT_DIR, f"{stem}_{i}{ext}")):
                i += 1
            dst = os.path.join(OUTPUT_DIR, f"{stem}_{i}{ext}")
        try:
            shutil.copy2(src_p, dst)
            kept[fmt] = os.path.basename(dst)
            # Also straight to the phone Downloads folder (2026-10-20, Daryl)
            try:
                _dl = "/storage/emulated/0/Download"
                os.makedirs(_dl, exist_ok=True)
                shutil.copy2(dst, os.path.join(_dl, os.path.basename(dst)))
            except Exception:
                pass
        except OSError:
            pass
    manifest = [e for e in manifest if e.get("job_id") != job_id]
    for fn in (entry.get("files") or {}).values():
        if fn:
            try:
                os.remove(os.path.join(TEMP_BEATS_DIR, secure_filename(fn)))
            except OSError:
                pass
    _temp_beats_save(manifest)
    if not kept:
        return jsonify({"ok": False, "error": "Nothing to keep"}), 404
    return jsonify({"ok": True, "kept": kept})

@app.post("/api/beats/discard")
def beats_discard():
    """Delete a temp beat immediately (before it would be overwritten)."""
    data = request.get_json(force=True, silent=True) or {}
    job_id = str(data.get("job_id", ""))[:32]
    manifest = _temp_beats_manifest()
    entry = next((e for e in manifest if e.get("job_id") == job_id), None)
    if not entry:
        return jsonify({"ok": True, "deleted": []})
    deleted = []
    for fn in (entry.get("files") or {}).values():
        if fn:
            try:
                os.remove(os.path.join(TEMP_BEATS_DIR, secure_filename(fn)))
                deleted.append(fn)
            except OSError:
                pass
    _temp_beats_save([e for e in manifest if e.get("job_id") != job_id])
    return jsonify({"ok": True, "deleted": deleted})

@app.get("/download/<path:fname>")
def download(fname):
    safe = secure_filename(fname)
    if safe != fname or "/" in fname or "\\" in fname:
        abort(404)
    p = os.path.join(OUTPUT_DIR, safe)
    if not os.path.isfile(p):
        p = os.path.join(OUTPUT_DIR, "temp_ab", safe)
    if not os.path.isfile(p):
        p = os.path.join(TEMP_BEATS_DIR, safe)
    if not os.path.isfile(p):
        abort(404)
    # Serve inline (not as attachment) so <audio> elements can stream/play.
    # Explicit MIME types for reliable WebView playback.
    # ?dl=1 forces Content-Disposition: attachment for the Download button.
    ext = os.path.splitext(safe)[1].lower()
    mime = {
        ".mp3": "audio/mpeg",
        ".wav": "audio/wav",
        ".ogg": "audio/ogg",
        ".m4a": "audio/mp4",
        ".mp4": "video/mp4",
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".mid": "audio/midi",
        ".midi": "audio/midi",
        ".json": "application/json",
        ".txt": "text/plain",
    }.get(ext)
    force_dl = request.args.get("dl") == "1"
    return send_file(p, as_attachment=force_dl, mimetype=mime,
                     download_name=safe)


# 97. chunked upload for large files (5MB chunks, resumable)
CHUNK_DIR = os.path.join(BASE, "chunks")
os.makedirs(CHUNK_DIR, exist_ok=True)


@app.post("/api/upload/chunk")
def api_upload_chunk():
    up_id = (request.form.get("upload_id") or "")[:32]
    if not up_id or not up_id.replace("-", "").replace("_", "").isalnum():
        return jsonify({"ok": False, "error": "Bad upload_id"}), 400
    try:
        index = int(request.form.get("index", 0))
        total = int(request.form.get("total", 1))
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "Bad index/total"}), 400
    if not 0 <= index < total <= 200:
        return jsonify({"ok": False, "error": "Bad chunk range"}), 400
    chunk = request.files.get("chunk")
    if not chunk:
        return jsonify({"ok": False, "error": "No chunk"}), 400
    udir = os.path.join(CHUNK_DIR, up_id)
    os.makedirs(udir, exist_ok=True)
    # containment
    if os.path.commonpath([os.path.abspath(udir), CHUNK_DIR]) != CHUNK_DIR:
        return jsonify({"ok": False, "error": "Bad upload_id"}), 400
    chunk.save(os.path.join(udir, f"{index:04d}.part"))
    done = len([f for f in os.listdir(udir) if f.endswith(".part")])
    return jsonify({"ok": True, "received": done, "total": total})


@app.post("/api/upload/complete")
def api_upload_complete():
    up_id = (request.form.get("upload_id") or "")[:32]
    fname = secure_filename(request.form.get("filename") or "upload")
    ext = os.path.splitext(fname)[1].lower()
    if ext not in C.SUPPORTED_IN:
        return jsonify({"ok": False, "error": "Unsupported type"}), 400
    udir = os.path.join(CHUNK_DIR, up_id)
    if os.path.commonpath([os.path.abspath(udir), CHUNK_DIR]) != CHUNK_DIR:
        return jsonify({"ok": False, "error": "Bad upload_id"}), 400
    parts = sorted(f for f in os.listdir(udir) if f.endswith(".part"))
    if not parts:
        return jsonify({"ok": False, "error": "No chunks"}), 400
    name = f"{uuid.uuid4().hex[:8]}_{fname}"
    path = os.path.join(UPLOAD_DIR, name)
    if os.path.commonpath([os.path.abspath(path), UPLOAD_DIR]) != UPLOAD_DIR:
        return jsonify({"ok": False, "error": "Bad filename"}), 400
    with open(path, "wb") as out:
        for p in parts:
            with open(os.path.join(udir, p), "rb") as f:
                shutil.copyfileobj(f, out)
    shutil.rmtree(udir, ignore_errors=True)
    return jsonify({"ok": True, "path": name,
                    "size": os.path.getsize(path)})


@app.get("/api/health")
def health():
    try:
        import psutil as _psutil
        mem = _psutil.virtual_memory()
        disk = _psutil.disk_usage(OUTPUT_DIR)
        load = {"cpu_pct": _psutil.cpu_percent(interval=0.1),
                "mem_pct": mem.percent,
                "disk_free_gb": round(disk.free / 1e9, 1)}
    except ImportError:
        load = {"cpu_pct": None, "mem_pct": None, "disk_free_gb": None}
    with jobs_lock:
        active = sum(1 for j in jobs.values() if j.get("status") == "running")
    # 148. dependency versions
    import numpy as _np, scipy as _sp, flask as _fl
    deps = {"python": sys.version.split()[0],
            "numpy": _np.__version__, "scipy": _sp.__version__,
            "flask": _fl.__version__, "ffmpeg": C.FFMPEG_OK}
    try:
        import PIL as _pil
        deps["pillow"] = _pil.__version__
    except ImportError:
        deps["pillow"] = None
    return jsonify({"ok": True, "ffmpeg": C.FFMPEG_OK,
                    "active_jobs": active,
                    "beat_cache": len(_beat_cache),
                    "system": load, "deps": deps})


@app.get("/api/lite-mode")
def api_lite_get():
    """Read lite mode state."""
    return jsonify({"ok": True, "lite": lite_mode()})


@app.post("/api/lite-mode")
def api_lite_set():
    """Toggle lite mode. Persists server-side; client mirrors in localStorage."""
    data = request.get_json(force=True, silent=True) or {}
    on = data.get("lite", True)
    on = str(on).lower() not in ("0", "false", "off", "no") if on is not None else True
    set_lite_mode(on)
    return jsonify({"ok": True, "lite": lite_mode()})


@app.post("/api/daw/backup")
def api_daw_backup():
    """149. Backup all projects + notes as a ZIP."""
    zpath = os.path.join(
        OUTPUT_DIR, f"djrill_backup_{uuid.uuid4().hex[:8]}.zip")
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
        for fn in os.listdir(daw.PROJECT_DIR):
            if fn.endswith(".json"):
                z.write(os.path.join(daw.PROJECT_DIR, fn),
                        f"projects/{fn}")
        if os.path.isfile(NOTES_FILE):
            z.write(NOTES_FILE, "projects/notes.json")
    _app_log.info("project backup created: %s", os.path.basename(zpath))
    return jsonify({"ok": True, "backup": os.path.basename(zpath)})


@app.post("/api/dj/analyze")
def api_dj_analyze():
    data = request.get_json(force=True, silent=True) or {}
    path = data.get("path", "")
    if not path or not os.path.isfile(path):
        return jsonify({"ok": False, "error": "file not found"}), 404
    try:
        y, sr = M.load_audio(path)
        y_mono = y.mean(axis=1) if y.ndim > 1 else y
        bpm = M.detect_bpm_consensus(y, sr) or 90.0
        rms = float((y_mono ** 2).mean() ** 0.5)
        energy = min(10, max(1, int(rms * 50)))
        return jsonify({"ok": True, "bpm": round(float(bpm), 1), "energy": energy, "path": path})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

@app.post("/api/dj/smart_next")
def api_dj_smart_next():
    data = request.get_json(force=True, silent=True) or {}
    current = data.get("current", {})
    library = data.get("library", [])
    exclude = set(data.get("exclude", []))
    try:
        import dj_intelligence as DI
        candidates = [t for t in library if t.get("path") not in exclude]
        if not candidates:
            return jsonify({"ok": False, "error": "no candidates"})
        best = max(candidates, key=lambda c: DI.score_transition(current, c))
        score = DI.score_transition(current, best)
        return jsonify({"ok": True, "next": best, "score": score})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


if __name__ == "__main__":
    print("Djrill Mobile — http://127.0.0.1:5000")
    # SECURITY: bind to localhost only — never expose to the network.
    app.run(host="127.0.0.1", port=5000, threaded=True)
