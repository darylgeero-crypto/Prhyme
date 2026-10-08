"""DJRILL soundkits — user-uploaded custom drum kits.

Users upload their own WAV one-shots (kick, snare, hats, clap) and map them
to instruments. Kits are stored under <djrill>/soundkits/<name>/ as 16-bit
PCM WAVs plus a kit.json manifest.

Only stdlib + numpy. No new dependencies.
"""

import io
import json
import os
import re
import wave

import numpy as np

SR = 44100
KIT_INSTRUMENTS = ["kick", "snare", "chat", "ohat", "clap"]
MAX_WAV_BYTES = 2 * 1024 * 1024   # 2 MB per sample
MAX_SAMPLE_SEC = 5.0              # one-shots must be short
MAX_KITS = 50

DJRILL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def kits_dir():
    d = os.path.join(DJRILL_DIR, "soundkits")
    os.makedirs(d, exist_ok=True)
    return d


def sanitize_name(name):
    """Clean a kit name: safe chars only, bounded length."""
    name = re.sub(r"[^A-Za-z0-9 _\-]", "", str(name or "")).strip()
    name = re.sub(r"\s+", " ", name)[:40]
    if not name or name in (".", ".."):
        raise ValueError("Invalid kit name")
    return name


def _kit_path(name):
    # name is sanitized; still guard against traversal.
    safe = sanitize_name(name)
    p = os.path.join(kits_dir(), safe)
    if os.path.commonpath([p, kits_dir()]) != kits_dir():
        raise ValueError("Invalid kit name")
    return p, safe


def _manifest_path(name):
    p, safe = _kit_path(name)
    return os.path.join(p, "kit.json"), safe


def list_custom_kits():
    """Return [{name, instruments: {inst: {dur, peak}}, created}] newest first."""
    out = []
    base = kits_dir()
    for entry in sorted(os.listdir(base),
                        key=lambda e: os.path.getmtime(os.path.join(base, e)),
                        reverse=True):
        mp, safe = _manifest_path(entry)
        if not os.path.isfile(mp):
            continue
        try:
            with open(mp) as f:
                meta = json.load(f)
        except (OSError, ValueError):
            continue
        out.append({"name": safe,
                    "instruments": meta.get("instruments", {}),
                    "created": meta.get("created", 0)})
    return out


def get_custom_kit(name):
    mp, safe = _manifest_path(name)
    if not os.path.isfile(mp):
        return None
    with open(mp) as f:
        meta = json.load(f)
    meta["name"] = safe
    return meta


def create_kit(name):
    if len(list_custom_kits()) >= MAX_KITS:
        raise ValueError(f"Too many kits (max {MAX_KITS})")
    p, safe = _kit_path(name)
    if os.path.exists(p):
        raise ValueError("A kit with that name already exists")
    os.makedirs(p)
    import time
    with open(os.path.join(p, "kit.json"), "w") as f:
        json.dump({"created": time.time(), "instruments": {}}, f)
    return safe


def rename_kit(old, new):
    p_old, safe_old = _kit_path(old)
    if not os.path.isdir(p_old):
        raise ValueError("Kit not found")
    p_new, safe_new = _kit_path(new)
    if os.path.exists(p_new):
        raise ValueError("A kit with that name already exists")
    os.rename(p_old, p_new)
    return safe_new


def delete_kit(name):
    import shutil
    p, safe = _kit_path(name)
    if not os.path.isdir(p):
        raise ValueError("Kit not found")
    shutil.rmtree(p)
    return safe


# ------------------------------------------------------------- WAV handling
def _decode_wav(raw):
    """Decode WAV bytes -> (mono float32, sample_rate). Validates format."""
    if len(raw) > MAX_WAV_BYTES:
        raise ValueError(f"Sample too large (max {MAX_WAV_BYTES // 1024} KB)")
    if len(raw) < 44:
        raise ValueError("Not a valid WAV file")
    try:
        w = wave.open(io.BytesIO(raw), "rb")
    except (wave.Error, EOFError):
        raise ValueError("Not a valid WAV file")
    with w:
        nch = w.getnchannels()
        sw = w.getsampwidth()
        fr = w.getframerate()
        nframes = w.getnframes()
        if nch not in (1, 2):
            raise ValueError("WAV must be mono or stereo")
        if sw not in (1, 2, 3, 4):
            raise ValueError("WAV must be 8/16/24/32-bit PCM")
        if fr < 8000 or fr > 192000:
            raise ValueError("Unsupported sample rate")
        dur = nframes / fr if fr else 0
        if dur > MAX_SAMPLE_SEC:
            raise ValueError(f"Sample too long (max {MAX_SAMPLE_SEC:.0f}s)")
        if dur < 0.01:
            raise ValueError("Sample is empty")
        frames = w.readframes(nframes)
    # bytes -> float32
    if sw == 1:
        a = (np.frombuffer(frames, dtype=np.uint8).astype(np.float32) - 128) / 128.0
    elif sw == 2:
        a = np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0
    elif sw == 3:
        b = np.frombuffer(frames, dtype=np.uint8).reshape(-1, 3)
        iv = (b[:, 0].astype(np.int32) | (b[:, 1].astype(np.int32) << 8)
              | (b[:, 2].astype(np.int32) << 16))
        iv = np.where(iv >= 0x800000, iv - 0x1000000, iv)
        a = iv.astype(np.float32) / 8388608.0
    else:  # 32-bit: assume signed PCM int
        a = np.frombuffer(frames, dtype=np.int32).astype(np.float32) / 2147483648.0
    if nch == 2:
        a = a.reshape(-1, 2).mean(axis=1)  # stereo -> mono for storage
    peak = float(np.max(np.abs(a))) if a.size else 0.0
    if peak < 1e-4:
        raise ValueError("Sample is silent")
    return a.astype(np.float32), fr, dur, peak


def _resample_to_44k(mono, sr):
    if sr == SR:
        return mono
    n_out = int(len(mono) * SR / sr)
    x_old = np.linspace(0, 1, len(mono))
    x_new = np.linspace(0, 1, n_out)
    return np.interp(x_new, x_old, mono).astype(np.float32)


def _trim_silence(mono, thresh_db=-48.0):
    thresh = 10.0 ** (thresh_db / 20.0)
    mag = np.abs(mono)
    idx = np.nonzero(mag > thresh)[0]
    if idx.size == 0:
        return mono
    # keep 5ms guard on each side
    guard = int(SR * 0.005)
    s = max(0, idx[0] - guard)
    e = min(len(mono), idx[-1] + guard + 1)
    return mono[s:e]


def _write_wav16(path, mono):
    peak = float(np.max(np.abs(mono))) if mono.size else 0.0
    if peak > 0:
        mono = mono / peak * 0.9  # normalize on import
    pcm = np.clip(mono, -1.0, 1.0)
    pcm = (pcm * 32767.0).astype(np.int16)
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(pcm.tobytes())


def save_sample(kit_name, instrument, raw_bytes, original_filename=""):
    """Validate, normalize and store an uploaded WAV one-shot."""
    if instrument not in KIT_INSTRUMENTS:
        raise ValueError(f"Unknown instrument (choose: {', '.join(KIT_INSTRUMENTS)})")
    ext = os.path.splitext(original_filename or "")[1].lower()
    if ext not in ("", ".wav"):
        raise ValueError("Only WAV files are accepted")
    p, safe = _kit_path(kit_name)
    if not os.path.isdir(p):
        raise ValueError("Kit not found")
    mono, sr, dur, peak = _decode_wav(raw_bytes)
    mono = _resample_to_44k(mono, sr)
    mono = _trim_silence(mono)
    out_path = os.path.join(p, f"{instrument}.wav")
    _write_wav16(out_path, mono)
    # update manifest
    mp = os.path.join(p, "kit.json")
    try:
        with open(mp) as f:
            meta = json.load(f)
    except (OSError, ValueError):
        meta = {"instruments": {}}
    meta.setdefault("instruments", {})[instrument] = {
        "dur": round(len(mono) / SR, 3),
        "peak": round(float(np.max(np.abs(mono))), 3),
    }
    with open(mp, "w") as f:
        json.dump(meta, f)
    return safe, instrument


def delete_sample(kit_name, instrument):
    p, safe = _kit_path(kit_name)
    fp = os.path.join(p, f"{instrument}.wav")
    if os.path.isfile(fp):
        os.remove(fp)
    mp = os.path.join(p, "kit.json")
    if os.path.isfile(mp):
        try:
            with open(mp) as f:
                meta = json.load(f)
            meta.get("instruments", {}).pop(instrument, None)
            with open(mp, "w") as f:
                json.dump(meta, f)
        except (OSError, ValueError):
            pass
    return safe


def preview_path(kit_name, instrument):
    """Filesystem path of a stored sample (for serving previews)."""
    p, _ = _kit_path(kit_name)
    fp = os.path.join(p, f"{instrument}.wav")
    return fp if os.path.isfile(fp) else None


def _stereo(mono):
    mono = np.asarray(mono, dtype=np.float32)
    return np.column_stack([mono, mono])


def load_sample(kit_name, instrument):
    """Load a stored sample -> stereo float32 @ 44100, or None."""
    fp = preview_path(kit_name, instrument)
    if not fp:
        return None
    with open(fp, "rb") as f:
        raw = f.read()
    mono, sr, _, _ = _decode_wav(raw)  # our own files always validate
    mono = _resample_to_44k(mono, sr)
    return _stereo(mono)


def load_kit_samples(kit_name):
    """Load all stored samples -> {instrument: stereo float32} for generate_beat."""
    out = {}
    for inst in KIT_INSTRUMENTS:
        s = load_sample(kit_name, instrument=inst)
        if s is not None:
            out[inst] = s
    return out
