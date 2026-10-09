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
import djrill_lyrics as L
import djrill_convert as C
import djrill_video as V
import daw
import beatfx
import masterfx
import videofx
import audiotools
import lightbeat  # pure-numpy fast beat renderer (no pygame/ffmpeg/samples)
import mixgen  # DJ mix generator: beatmatched original mixes + era styles
import soundkits  # user-uploaded custom drum kits (WAV one-shots)
import audiofx
import vocalfix  # vocal clarity + subtle timing correction (never deletes words)
import vocalfx  # ONLINE-ONLY vocal separator + auto SFX layer (cloud DSP/Demucs)
import trackfx  # creative FX: radio, vinyl, TV, filters, echo (never deletes words)
import rockdabus as RB  # Rockdabus Prhyme — conversational assistant brain

BASE = os.path.dirname(os.path.abspath(__file__))
UPLOAD_DIR = os.path.join(BASE, "uploads")
OUTPUT_DIR = os.path.join(BASE, "outputs")
HISTORY_FILE = os.path.join(BASE, "job_history.json")
os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(OUTPUT_DIR, exist_ok=True)


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


def check_audio_budget(n_samples, channels=2, copies=6, label="audio"):
    """Raise MemoryError with a friendly message if this op is risky."""
    avail = mem_available_mb()
    if avail is None:
        return
    need_mb = n_samples * channels * 4 * copies / (1024 * 1024)
    if avail < need_mb + 150:  # keep 150 MB headroom for OS + app
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
    """Make {{ lite }} available in every template (badge + toggles)."""
    return {"lite": lite_mode()}


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
GENRES = ["HipHop", "Drill", "Trap", "BoomBap", "RnB", "Dancehall",
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
            _real_samples = "/storage/emulated/0/Ai_music_samples"
            if os.path.isdir(_real_samples):
                m.SAMPLE_BASE_DIR = _real_samples
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


threading.Thread(target=_persist_jobs, daemon=True).start()
_restore_jobs()


def safe_name(title, default="djrill"):
    s = "".join(c if c.isalnum() or c in " _-" else "_" for c in (title or "")).strip()
    s = "_".join(s.split())  # no spaces: keeps download URLs simple
    return s[:60] if s else default


def render_beat_progress(m, genre, bpm, n_bars, seed=None, cb=None):
    """Mirror of djrill_master.render_beat with a per-bar progress callback."""
    if seed is None:
        seed = M.new_beat_seed()
    g = m.Generator(seed=seed, genre=genre, hook_name="Hook A")
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
    peak = np.max(np.abs(beat))
    if peak > 0:
        beat = beat / peak * 0.9
    sub_taps = signal.firwin2(255, [0, 60, 120, 200, SR / 2],
                              [2.51, 2.51, 1.78, 1.0, 1.0], fs=SR)
    beat = np.column_stack([signal.fftconvolve(beat[:, ch], sub_taps, mode="same")
                            for ch in range(beat.shape[1])])
    peak = np.max(np.abs(beat))
    if peak > 0:
        beat = beat / peak * 0.9
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


# ---------------------------------------------------------------- master job
def run_master_job(job_id, src_path, genre, bpm_opt, seed, title, mopts=None):
    def prog(p, msg):
        set_job(job_id, progress=p, message=msg)
    try:
        mopts = mopts or {}
        chain = mopts.get("chain", "Streaming")
        prog(3, "Loading your recording…")
        _, vocal = M.load_audio(src_path)
        # 140. corrupt-audio guard: reject silent / NaN / broken files
        if vocal.size == 0 or not np.all(np.isfinite(vocal)):
            raise ValueError("Recording is unreadable (corrupt audio data)")
        if np.max(np.abs(vocal)) < 1e-6:
            raise ValueError("Recording is silent — nothing to master")
        v_dur = vocal.shape[0] / SR

        bpm = bpm_opt or M.detect_bpm(vocal.mean(axis=1), SR) or 90.0
        prog(8, f"Tempo locked: {bpm:.1f} BPM")
        bar_dur = 60.0 / bpm * 4
        intro = bar_dur  # 1 intro bar
        n_bars = int(np.ceil((intro + v_dur + 2 * bar_dur) / bar_dur))

        # Memory guard: vocal + beat + mix buffers.
        check_audio_budget(vocal.shape[0] * 3, channels=2, copies=8,
                           label="master")
        _lite = lite_mode()
        if _lite:
            # Lite: phone-safe lightbeat renderer instead of the V68 engine,
            # capped at 32 bars then tiled to cover long vocals.
            prog(10, f"Rendering backing beat (lite)…")
            _lb_bars = min(n_bars, 32)
            beat = lightbeat.generate_beat(genre, float(bpm), _lb_bars, seed)
            _need = int(np.ceil((intro + v_dur + 2 * bar_dur) * SR))
            if beat.shape[0] < _need:
                _reps = int(np.ceil(_need / beat.shape[0]))
                beat = np.tile(beat, (_reps, 1))[:_need]
        else:
            eng = get_engine()
            prog(10, f"Rendering {n_bars} bars of {genre} beat…")
            beat = render_beat_progress(
                eng, genre, bpm, n_bars, seed,
                lambda b, n: prog(10 + int(45 * b / n), f"Beat bar {b}/{n}…"))

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
        mix = np.zeros((max(need, beat.shape[0]), 2))
        mix[:beat.shape[0]] += beat * 0.9
        s0 = int(intro * SR)
        mix[s0:s0 + vp_fx.shape[0]] += vp_fx * 10 ** (boost_db / 20.0)
        end = min(mix.shape[0], s0 + vp_fx.shape[0] + int(2 * SR))
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
            raise ValueError(
                f"Vocal integrity check failed (corr={vox_corr:.2f}) — refusing")

        prog(80, "Mastering…")
        ref_path = mopts.get("reference_path")
        if ref_path and not _lite:
            # Lite skips reference spectrum matching (heavy FFT analysis).
            mix, ref_lufs, deltas = masterfx.match_reference_spectrum(
                mix, ref_path)
            mopts = dict(mopts, target_lufs=ref_lufs)
        pcm16, report = masterfx.master_with_options(
            mix,
            chain_name=chain,
            target_lufs=mopts.get("target_lufs"),
            ceiling_db=float(mopts.get("ceiling_db", -1.0)),
            dither=bool(mopts.get("dither", True)),
            deess=float(mopts.get("deess", 0.0)),
            multiband=bool(mopts.get("multiband", False)))

        safe = safe_name(title, "djrill-master")
        base = f"{job_id[:8]}_{safe}"
        wav_path = os.path.join(OUTPUT_DIR, base + ".wav")
        mp3_path = os.path.join(OUTPUT_DIR, base + ".mp3")
        # 141. atomic writes: tmp + rename so partial files never surface
        tmp_wav = wav_path + ".tmp"
        prog(86, "Writing WAV…")
        wav_write(tmp_wav, SR, pcm16)
        os.replace(tmp_wav, wav_path)
        prog(92, "Encoding MP3…")
        encode_mp3(wav_path, mp3_path)
        prog(96, "Building A/B previews…")

        set_job(job_id, status="done", progress=100,
                message=f"Done — {report['lufs']} LUFS, "
                        f"{report['true_peak_dbtp']} dBTP",
                result={"mp3": os.path.basename(mp3_path),
                        "wav": os.path.basename(wav_path),
                        "lufs": report["lufs"],
                        "dbtp": report["true_peak_dbtp"],
                        "bpm": round(float(bpm), 1),
                        "duration": report["duration_s"],
                        "fx_applied": fx_applied,
                        "report": report,
                        # 25. A/B compare: 30s excerpts of source vs master
                        "ab_source": _ab_excerpt(src_path, OUTPUT_DIR,
                                                f"{job_id[:8]}_ab-source.mp3"),
                        "ab_master": _ab_excerpt(mp3_path, OUTPUT_DIR,
                                                f"{job_id[:8]}_ab-master.mp3")})
    except Exception as e:
        set_job(job_id, status="error", progress=0, message=f"Error: {e}")


def _ab_excerpt(src_path, out_dir, fname, secs=30):
    """Write a 30s preview MP3 for A/B comparison. Returns basename or None."""
    try:
        _, audio = M.load_audio(src_path)
        n = min(len(audio), int(secs * SR))
        # pick the loudest 30s window
        if len(audio) > n:
            win = SR * 5
            best, best_e = 0, -1
            for s in range(0, len(audio) - n, win):
                e = float(np.mean(audio[s:s + n] ** 2))
                if e > best_e:
                    best, best_e = s, e
            seg = audio[best:best + n]
        else:
            seg = audio[:n]
        peak = np.max(np.abs(seg))
        if peak > 0:
            seg = seg / peak * 0.9
        tmp = os.path.join(out_dir, fname + ".wav")
        wav_write(tmp, SR, (np.clip(seg, -1, 1) * 32767).astype(np.int16))
        dst = os.path.join(out_dir, fname)
        encode_mp3(tmp, dst)
        os.remove(tmp)
        return fname
    except Exception:
        return None


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
            wav_path = os.path.join(OUTPUT_DIR, base + ".wav")
            mp3_path = os.path.join(OUTPUT_DIR, base + ".mp3")
            with open(wav_path, "wb") as f:
                f.write(cached)
            encode_mp3(wav_path, mp3_path)
            _, audio = M.load_audio(wav_path)
            set_job(job_id, status="done", progress=100,
                    message="Beat ready (cached)",
                    result={"mp3": os.path.basename(mp3_path),
                            "wav": os.path.basename(wav_path),
                            "bpm": bpm, "bars": n_bars, "seed": seed,
                            "cached": True,
                            "duration": round(audio.shape[0] / SR, 1)})
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
    wav_path = os.path.join(OUTPUT_DIR, base + ".wav")
    mp3_path = os.path.join(OUTPUT_DIR, base + ".mp3")
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
        prog(94, "Encoding MP3…")
        encode_mp3(wav_path, mp3_path)
    print(f"[FAST] caching...", flush=True)
    prog(98, "Finalizing…")
    _beat_cache_put(ckey, wav_path)  # 101. memoize for reuse
    print(f"[FAST] setting job done", flush=True)
    set_job(job_id, status="done", progress=100, message="Beat ready",
            result={"mp3": os.path.basename(mp3_path),
                    "wav": os.path.basename(wav_path),
                    "bpm": bpm, "bars": n_bars, "seed": seed,
                        "duration": round(beat.shape[0] / SR, 1)})


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


@app.post("/api/master")
def api_master():
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
        os.replace(tmp_wav, wav_path)
        prog(92, "Encoding MP3…")
        encode_mp3(wav_path, mp3_path)
        set_job(job_id, status="done", progress=100,
                message=f"Stems mastered — {report['lufs']} LUFS",
                result={"mp3": os.path.basename(mp3_path),
                        "wav": os.path.basename(wav_path),
                        "report": report})
    except Exception as e:
        set_job(job_id, status="error", progress=0, message=f"Error: {e}")


@app.post("/api/master/stems")
def api_stem_master():
    """Master 2-8 uploaded stems together."""
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


def _start_beat_job(data):
    """Validate beat params and launch the render job.
    Returns (payload_dict, status_code). Shared by /api/beats and Rockdabus."""
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
                            "bpm": style["bpm"], "seed": seed, "cached": True})
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
                        "bpm": style["bpm"], "seed": seed, "cached": False})
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
    Shared by /api/lyrics and Rockdabus."""
    data = data or {}
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
        artist=artist)
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
    return {"ok": True, "seed": seed, "text": txt, "lrc": lrc,
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


def run_mix_job(job_id, genre, style, seed):
    def prog(p, msg):
        set_job(job_id, progress=p, message=msg)
    try:
        _lite = lite_mode()
        # Memory guard: 4 segs x 16 bars or 2 x 8 in lite, stereo float32.
        _bars = 8 if _lite else 16
        _segs = 2 if _lite else 4
        check_audio_budget(int(240 / 140 * _bars * _segs * SR),
                           channels=2, copies=8, label="DJ mix")
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
                        "bpm": meta["bpm"], "duration": meta["duration"],
                        "segments": meta["segments"], "style": meta["style"],
                        "seed": seed})
    except Exception as e:
        set_job(job_id, status="error", progress=0, message=f"Error: {e}")


def _start_mix_job(data):
    """Validate mix params and launch the mix job.
    Returns (payload_dict, status_code). Shared by /api/mix and Rockdabus."""
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
    if ext not in (".mp3", ".wav", ".ogg", ".flac", ".m4a"):
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
    exts = (".wav", ".mp3", ".ogg", ".flac", ".m4a")
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


@app.get("/rockdabus")
def rockdabus_page():
    return render_template("rockdabus.html", active="rockdabus")


# ------------------------------------------------- Rockdabus Prhyme chat
_rb_sessions = {}
_rb_lock = threading.Lock()


def _rb_session(sid):
    """Get-or-create a Rockdabus chat session; prunes stale ones."""
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


@app.post("/api/rockdabus")
def api_rockdabus():
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
        # Rockdabus brain: LLM-enhanced (shared llama-server) with rule-based
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
    and Rockdabus."""
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
    return {"ok": True, "seed": seed, "theme": theme,
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
        base = f"{job_id[:8]}_{safe}"
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
                              "waveform", "collage", "minimal"],
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


@app.get("/download/<path:fname>")
def download(fname):
    safe = secure_filename(fname)
    if safe != fname or "/" in fname or "\\" in fname:
        abort(404)
    p = os.path.join(OUTPUT_DIR, safe)
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


if __name__ == "__main__":
    print("Djrill Mobile — http://127.0.0.1:5000")
    # SECURITY: bind to localhost only — never expose to the network.
    app.run(host="127.0.0.1", port=5000, threaded=True)
