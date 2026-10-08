"""Djrill Mobile Studio — DAW backend: peaks, projects, mixdown export.

Clips live in mobile/clips/ (uploads + generated beats copied here).
Projects live in mobile/projects/ as sanitized JSON files.
Mixdown renders the timeline server-side and masters through the V8 profile.
"""
import os
import re
import json
import uuid

import numpy as np
from scipy.io.wavfile import write as wav_write

import djrill_master as M
import djrill_convert as C
import studiofx

SR = 44100
CLIPS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "clips")
PROJECT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "projects")
os.makedirs(CLIPS_DIR, exist_ok=True)
os.makedirs(PROJECT_DIR, exist_ok=True)


def sanitize_name(name, default="project"):
    s = re.sub(r"[^A-Za-z0-9 _-]", "_", (name or "")).strip()
    s = "_".join(s.split())
    return s[:60] if s else default


def clip_path(fname):
    """Resolve a clip basename to an absolute path, contained in CLIPS_DIR."""
    from werkzeug.utils import secure_filename
    safe = secure_filename(fname or "")
    if not safe or safe != fname or "/" in fname or "\\" in fname:
        raise ValueError("Bad clip reference")
    p = os.path.join(CLIPS_DIR, safe)
    if os.path.commonpath([os.path.abspath(p), CLIPS_DIR]) != CLIPS_DIR:
        raise ValueError("Bad clip reference")
    if not os.path.isfile(p):
        raise ValueError("Clip not found")
    return p


def store_clip(src_path, display_name):
    """Copy an audio file into CLIPS_DIR. Returns the clip basename."""
    from werkzeug.utils import secure_filename
    ext = os.path.splitext(display_name)[1].lower()
    if ext not in C.SUPPORTED_IN:
        raise ValueError(f"Unsupported audio type {ext or '(none)'}")
    safe = secure_filename(os.path.basename(display_name)) or "clip"
    base = f"{uuid.uuid4().hex[:8]}_{safe}"
    dst = os.path.join(CLIPS_DIR, base)
    if os.path.commonpath([os.path.abspath(dst), CLIPS_DIR]) != CLIPS_DIR:
        raise ValueError("Bad filename")
    with open(src_path, "rb") as fsrc, open(dst, "wb") as fdst:
        fdst.write(fsrc.read())
    return base


def store_clip_bytes(data, display_name):
    """Store raw audio bytes as a clip (for bundle import). Returns basename."""
    from werkzeug.utils import secure_filename
    ext = os.path.splitext(display_name)[1].lower()
    if ext not in C.SUPPORTED_IN:
        raise ValueError(f"Unsupported audio type {ext or '(none)'}")
    safe = secure_filename(os.path.basename(display_name)) or "clip"
    base = f"{uuid.uuid4().hex[:8]}_{safe}"
    dst = os.path.join(CLIPS_DIR, base)
    if os.path.commonpath([os.path.abspath(dst), CLIPS_DIR]) != CLIPS_DIR:
        raise ValueError("Bad filename")
    with open(dst, "wb") as f:
        f.write(data)
    return base


def compute_peaks(path, n_buckets=600):
    """Peak waveform data for the browser. Returns dict with peaks list.
    94. Fast path: peak-decimate long files before bucketing."""
    _, audio = M.load_audio(path)
    mono = audio.mean(axis=1).astype(np.float64)
    dur = len(mono) / SR
    if len(mono) > 200000:
        step = len(mono) // 200000
        cut = (len(mono) // step) * step
        mono = np.max(np.abs(mono[:cut].reshape(-1, step)), axis=1)
    n = max(1, min(n_buckets, len(mono)))
    idx = np.linspace(0, len(mono), n + 1).astype(int)
    peaks = []
    for i in range(n):
        seg = mono[idx[i]:idx[i + 1]]
        peaks.append(float(np.max(np.abs(seg))) if seg.size else 0.0)
    return {"peaks": [round(p, 4) for p in peaks],
            "duration": round(float(dur), 3)}


# ---------------------------------------------------------------- projects
def save_project(name, data):
    safe = sanitize_name(name)
    path = os.path.join(PROJECT_DIR, safe + ".json")
    if os.path.commonpath([os.path.abspath(path), PROJECT_DIR]) != PROJECT_DIR:
        raise ValueError("Bad project name")
    # validate shape lightly
    if not isinstance(data, dict) or "tracks" not in data:
        raise ValueError("Bad project data")
    with open(path, "w") as f:
        json.dump(data, f)
    return safe


def list_projects():
    out = []
    for fn in sorted(os.listdir(PROJECT_DIR)):
        if fn.endswith(".json"):
            p = os.path.join(PROJECT_DIR, fn)
            out.append({"name": fn[:-5],
                        "modified": round(os.path.getmtime(p), 0)})
    return out


def load_project(name):
    safe = sanitize_name(name)
    path = os.path.join(PROJECT_DIR, safe + ".json")
    if os.path.commonpath([os.path.abspath(path), PROJECT_DIR]) != PROJECT_DIR:
        raise ValueError("Bad project name")
    if not os.path.isfile(path):
        raise ValueError("Project not found")
    with open(path) as f:
        return json.load(f)


# ---------------------------------------------------------------- mixdown
def _pan_gains(pan):
    """Constant-power stereo gains for pan in [-1, 1]."""
    pan = max(-1.0, min(1.0, float(pan)))
    ang = (pan + 1.0) * np.pi / 4.0
    return float(np.cos(ang)), float(np.sin(ang))


def render_mixdown(project, output_dir, tag):
    """Render the timeline to WAV + MP3 through the V8 mastering profile.
    project: dict with bpm, tracks[{name,volume,pan,mute,solo,clips[],fx{}}].
    clip: {file, start, offset, duration, gain, fade_in, fade_out}.
    fx: {eq:{low,mid,high}, comp:{thr_db,ratio}, reverb, delay, automation[]}.
    Returns (wav, mp3, stats)."""
    tracks = project.get("tracks", [])
    if not tracks:
        raise ValueError("Project has no tracks")
    bpm = float(project.get("bpm") or 90.0)

    any_solo = any(bool(t.get("solo")) for t in tracks)

    # total length
    total = 0.0
    for t in tracks:
        for c in t.get("clips", []):
            total = max(total, float(c.get("start", 0)) + float(c.get("duration", 0)))
    if total <= 0:
        raise ValueError("Project is empty")
    total = min(total, 1200.0)  # 20-minute safety cap
    n = int(total * SR)

    def render_track_audio(t):
        """Render one track's clips (pre-fader) into a stereo buffer.
        102. float32 fast path for the accumulation buffer."""
        buf = np.zeros((n, 2), dtype=np.float32)
        for c in t.get("clips", []):
            try:
                src = clip_path(c["file"])
            except (ValueError, KeyError):
                continue
            _, audio = M.load_audio(src)
            off = int(max(0.0, float(c.get("offset", 0))) * SR)
            dur = int(max(0.0, float(c.get("duration", 0))) * SR)
            seg = audio[off:off + dur].astype(np.float32)
            if seg.shape[0] == 0:
                continue
            # 47. per-clip gain; 46. per-clip fades
            seg = seg * max(0.0, min(4.0, float(c.get("gain", 1.0))))
            seg = studiofx.apply_clip_fades(
                seg, float(c.get("fade_in", 0.0)), float(c.get("fade_out", 0.0))
            ).astype(np.float32)
            s0 = int(max(0.0, float(c.get("start", 0))) * SR)
            s1 = min(n, s0 + seg.shape[0])
            if s1 <= s0:
                continue
            seg = seg[:s1 - s0]
            buf[s0:s1] += seg
        # 51-55. per-track FX chain (upcast for precision)
        buf = studiofx.process_track(buf.astype(np.float64), t.get("fx") or {},
                                     bpm=bpm)
        return buf

    mix = np.zeros((n, 2), dtype=np.float64)
    track_buffers = {}
    for ti, t in enumerate(tracks):
        if t.get("mute"):
            continue
        if any_solo and not t.get("solo"):
            continue
        buf = render_track_audio(t)
        track_buffers[ti] = buf
        vol = max(0.0, min(2.0, float(t.get("volume", 1.0))))
        gl, gr = _pan_gains(t.get("pan", 0.0))
        mix[:, 0] += buf[:, 0] * vol * gl
        mix[:, 1] += buf[:, 1] * vol * gr

    peak = np.max(np.abs(mix))
    if peak <= 1e-9:
        raise ValueError("Mixdown is silent — check mutes/solos")

    # master fader (project.master, default 1.0)
    master = max(0.0, min(2.0, float(project.get("master", 1.0))))
    if master != 1.0:
        mix = mix * master

    # V8 mastering profile: spectral match + V8 loudness + glue + true-peak limit
    mix_bands = M.spectral_bands(mix.mean(axis=1), SR)
    taps, _ = M.design_match_eq(mix_bands, M.V8_PROFILE["bands"], SR)
    mix = M.apply_fir(mix, taps)
    pcm16, lufs, tp = M.master_track(
        mix,
        target_lufs=M.V8_PROFILE["target_lufs"],
        glue_drive=M.V8_PROFILE["glue_drive"])
    ok_tp, tp_db = M.verify_no_clipping(pcm16, SR)
    if not ok_tp:
        raise ValueError(f"Mixdown clips at {tp_db:.1f} dBTP — refusing")

    base = f"{tag}_studio-mixdown"
    wav_path = os.path.join(output_dir, base + ".wav")
    mp3_path = os.path.join(output_dir, base + ".mp3")
    wav_write(wav_path, SR, pcm16)
    C.convert_file(wav_path, mp3_path)
    return wav_path, mp3_path, {"lufs": round(float(lufs), 1),
                                "dbtp": round(float(tp_db), 2),
                                "duration": round(float(total), 1)}


def render_stems(project, output_dir, tag):
    """60. Export each audible track as its own mastered WAV + MP3 stem."""
    tracks = project.get("tracks", [])
    if not tracks:
        raise ValueError("Project has no tracks")
    bpm = float(project.get("bpm") or 90.0)
    any_solo = any(bool(t.get("solo")) for t in tracks)
    total = 0.0
    for t in tracks:
        for c in t.get("clips", []):
            total = max(total, float(c.get("start", 0)) + float(c.get("duration", 0)))
    total = min(max(total, 1.0), 1200.0)
    n = int(total * SR)
    out = []
    for ti, t in enumerate(tracks):
        if t.get("mute"):
            continue
        if any_solo and not t.get("solo"):
            continue
        buf = np.zeros((n, 2), dtype=np.float64)
        for c in t.get("clips", []):
            try:
                src = clip_path(c["file"])
            except (ValueError, KeyError):
                continue
            _, audio = M.load_audio(src)
            off = int(max(0.0, float(c.get("offset", 0))) * SR)
            dur = int(max(0.0, float(c.get("duration", 0))) * SR)
            seg = audio[off:off + dur]
            if seg.shape[0] == 0:
                continue
            seg = seg * max(0.0, min(4.0, float(c.get("gain", 1.0))))
            seg = studiofx.apply_clip_fades(
                seg, float(c.get("fade_in", 0.0)), float(c.get("fade_out", 0.0)))
            s0 = int(max(0.0, float(c.get("start", 0))) * SR)
            s1 = min(n, s0 + seg.shape[0])
            if s1 <= s0:
                continue
            buf[s0:s1] += seg[:s1 - s0]
        buf = studiofx.process_track(buf, t.get("fx") or {}, bpm=bpm)
        vol = max(0.0, min(2.0, float(t.get("volume", 1.0))))
        gl, gr = _pan_gains(t.get("pan", 0.0))
        buf[:, 0] *= vol * gl
        buf[:, 1] *= vol * gr
        peak = np.max(np.abs(buf))
        if peak <= 1e-9:
            continue
        pcm16, _, _ = M.master_track(buf, target_lufs=-14.0)
        safe = sanitize_name(t.get("name", f"track{ti + 1}"), f"track{ti + 1}")
        base = f"{tag}_stem-{safe}"
        wav_path = os.path.join(output_dir, base + ".wav")
        mp3_path = os.path.join(output_dir, base + ".mp3")
        wav_write(wav_path, SR, pcm16)
        C.convert_file(wav_path, mp3_path)
        out.append({"track": t.get("name", safe),
                    "wav": os.path.basename(wav_path),
                    "mp3": os.path.basename(mp3_path)})
    if not out:
        raise ValueError("No audible tracks to export")
    return out
