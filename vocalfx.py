"""Prhyme vocal separator + SFX layer engine.

ONLINE-ONLY feature: the phone app uploads a track, the cloud (Render)
runs separation, the phone downloads the layers. Nothing heavy runs on-device.

Engines (selected via SEPARATE_ENGINE env: auto | dsp | demucs):
  - demucs: Meta's htdemucs via the `demucs` pip package, when installed.
    Needs ~2GB+ RAM — NOT viable on Render's free tier (512MB).
  - dsp: classical HPSS + center-channel + vocal-band masking (numpy/scipy
    only). Always available; runs anywhere.

`separate_track()` picks Demucs when available, otherwise DSP.
"""
import os
import subprocess
import tempfile

import numpy as np
from scipy import signal
from scipy.io.wavfile import write as wav_write, read as wav_read

try:
    from scipy.ndimage import median_filter as _medfilt
    _HAS_NDIMAGE = True
except ImportError:
    _HAS_NDIMAGE = False

SR = 44100
N_FFT = 4096
HOP = 1024
CHUNK_S = 30.0
OVERLAP_S = 2.0


# ---------------------------------------------------------------- engine pick
def demucs_available():
    try:
        import demucs  # noqa: F401
        return True
    except ImportError:
        return False


def engine_name():
    eng = os.environ.get("SEPARATE_ENGINE", "auto").lower()
    if eng in ("auto", "demucs") and demucs_available():
        return "Demucs (htdemucs)"
    return "Prhyme DSP"


def separate_track(path, sr=SR, progress=None):
    """Separate `path` -> (vocals, instrumental), float64 stereo @sr.

    progress: optional callable(0..100).
    """
    eng = os.environ.get("SEPARATE_ENGINE", "auto").lower()
    if eng in ("auto", "demucs") and demucs_available():
        try:
            return _separate_demucs(path, progress)
        except Exception:
            pass  # fall through to DSP
    return _separate_dsp(path, sr, progress)


def _separate_demucs(path, progress=None):
    """Two-stem Demucs (vocals / no_vocals) via subprocess."""
    if progress:
        progress(5)
    tmp = tempfile.mkdtemp(prefix="sep-demucs-")
    cmd = ["python", "-m", "demucs", "--two-stems=vocals", "-o", tmp,
           "--mp3", "--mp3-bitrate", "192", path]
    subprocess.run(cmd, check=True, capture_output=True, timeout=1800)
    # find outputs: tmp/htdemucs/<stem>/vocals.mp3 etc.
    voc = inst = None
    for root, _ds, fs in os.walk(tmp):
        for fn in fs:
            lp = os.path.join(root, fn)
            if fn.startswith("vocals"):
                voc = lp
            elif fn.startswith("no_vocals"):
                inst = lp
    if not voc or not inst:
        raise RuntimeError("Demucs produced no stems")
    if progress:
        progress(90)
    return _load_stereo(voc, SR), _load_stereo(inst, SR)


def _load_stereo(path, sr):
    r, d = wav_read(path)
    d = d.astype(np.float64)
    if d.ndim == 1:
        d = np.column_stack([d, d])
    peak = np.max(np.abs(d))
    if peak > 1.0:
        d = d / peak
    if r != sr:
        n = int(d.shape[0] * sr / r)
        d = signal.resample(d, n).astype(np.float64)
    return d


# ---------------------------------------------------------------- DSP engine
def _stft(x):
    _, _, Z = signal.stft(x.astype(np.float32), fs=SR, window="hann",
                         nperseg=N_FFT, noverlap=N_FFT - HOP,
                         boundary="zeros", padded=True)
    return Z


def _istft(Z):
    _, x = signal.istft(Z, fs=SR, window="hann",
                       nperseg=N_FFT, noverlap=N_FFT - HOP)
    return x.astype(np.float64)


def _median_time(mag):
    # harmonic: median across time -> sustained tones (vocals, pads)
    if _HAS_NDIMAGE:
        return _medfilt(mag, size=(1, 31))
    k = 31
    pad = np.pad(mag, ((0, 0), (k // 2, k // 2)), mode="edge")
    out = np.empty_like(mag)
    for t in range(mag.shape[1]):
        out[:, t] = np.median(pad[:, t:t + k], axis=1)
    return out


def _median_freq(mag):
    # percussive: median across frequency -> transients (drums)
    if _HAS_NDIMAGE:
        return _medfilt(mag, size=(31, 1))
    k = 31
    pad = np.pad(mag, ((k // 2, k // 2), (0, 0)), mode="edge")
    out = np.empty_like(mag)
    for f in range(mag.shape[0]):
        out[f, :] = np.median(pad[f:f + k, :], axis=0)
    return out


def _vocal_band_weight(n_bins):
    """Smooth band emphasis: vocals live ~200Hz-4kHz; kill sub & air."""
    freqs = np.fft.rfftfreq(N_FFT, 1.0 / SR)[:n_bins]
    w = np.ones(n_bins)
    # highpass below 150Hz (kick/bass live here)
    lo = np.clip((freqs - 90.0) / 120.0, 0, 1)
    lo = lo * lo * (3 - 2 * lo)  # smoothstep
    # lowpass above 5kHz (cymbals/air)
    hi = np.clip((9000.0 - freqs) / 4000.0, 0, 1)
    hi = hi * hi * (3 - 2 * hi)
    w = np.minimum(lo, hi)
    # gentle presence lift 1-3kHz
    band = np.clip(1 - np.abs(freqs - 2000.0) / 1500.0, 0, 1)
    w = w * (1 + 0.35 * band)
    return w.astype(np.float32)[:, None]


def _separate_chunk(L, R):
    """One chunk (float32 stereo) -> (vocals, instrumental) float64 stereo."""
    mid = ((L.astype(np.float64) + R.astype(np.float64)) / 2).astype(np.float32)
    ZL, ZR, ZM = _stft(L), _stft(R), _stft(mid)
    mag = np.abs(ZM).astype(np.float32)

    # 1. HPSS: keep harmonic content (vocals are harmonic)
    H = _median_time(mag)
    P = _median_freq(mag)
    h_mask = (H * H) / (H * H + P * P + 1e-10)

    # 2. Centeredness: vocals are panned center
    num = np.abs(ZL - ZR)
    den = np.abs(ZL) + np.abs(ZR) + 1e-10
    center = (1.0 - num / den).astype(np.float32)
    if _HAS_NDIMAGE:
        center = _medfilt(center, size=(3, 5))

    # 3. Vocal band weight
    w = _vocal_band_weight(mag.shape[0])

    Mv = h_mask * np.power(np.clip(center, 0, 1), 1.5) * w

    # 4. Spectral gate: drop bins 60dB below chunk peak
    peak = mag.max() + 1e-12
    gate = (mag > peak * 1e-3).astype(np.float32)
    Mv = Mv * gate
    Mv = np.clip(Mv, 0.0, 1.0).astype(np.float32)

    v_mono = _istft(Mv * ZM)
    iL = _istft((1.0 - Mv) * ZL)
    iR = _istft((1.0 - Mv) * ZR)

    n = min(len(v_mono), len(iL), len(iR), len(L))
    vocals = np.column_stack([v_mono[:n], v_mono[:n]])  # centered dual-mono
    inst = np.column_stack([iL[:n], iR[:n]])
    return vocals, inst


def _separate_dsp(path, sr=SR, progress=None):
    r, d = wav_read(path)
    if d.dtype == np.int16:
        d = d.astype(np.float64) / 32768.0
    elif d.dtype == np.int32:
        d = d.astype(np.float64) / 2147483648.0
    else:
        d = d.astype(np.float64)
    if d.ndim == 1:
        d = np.column_stack([d, d])
    if r != sr:
        n = int(d.shape[0] * sr / r)
        d = signal.resample(d, n).astype(np.float64)
    d = d.astype(np.float32)

    chunk_n = int(CHUNK_S * sr)
    ov_n = int(OVERLAP_S * sr)
    step = chunk_n - ov_n
    total = d.shape[0]
    vocals = np.zeros((total, 2), dtype=np.float64)
    inst = np.zeros((total, 2), dtype=np.float64)

    n_chunks = max(1, int(np.ceil((total - ov_n) / step)))
    fade = np.linspace(0, 1, ov_n)[:, None]
    for ci in range(n_chunks):
        s = ci * step
        e = min(s + chunk_n, total)
        v_c, i_c = _separate_chunk(d[s:e, 0], d[s:e, 1])
        m = e - s
        v_c, i_c = v_c[:m], i_c[:m]
        if ci > 0:  # crossfade the overlap region
            vocals[s:s + ov_n] = (vocals[s:s + ov_n] * (1 - fade)
                                  + v_c[:ov_n] * fade)
            inst[s:s + ov_n] = (inst[s:s + ov_n] * (1 - fade)
                                + i_c[:ov_n] * fade)
            vocals[s + ov_n:e] = v_c[ov_n:]
            inst[s + ov_n:e] = i_c[ov_n:]
        else:
            vocals[s:e] = v_c
            inst[s:e] = i_c
        if progress:
            progress(100.0 * (ci + 1) / n_chunks)

    for a in (vocals, inst):
        peak = np.max(np.abs(a))
        if peak > 0:
            a *= 0.89 / peak
    return vocals, inst


# ------------------------------------------------------- transition detection
def detect_transitions(audio, sr=SR, min_gap_s=4.0):
    """Find section transitions -> [(time_s, kind)].

    kind: 'drop' (big energy jump), 'break' (big energy fall),
          'build' (moderate rise).
    """
    mono = audio.mean(axis=1).astype(np.float64)
    win, hop = int(sr * 0.5), int(sr * 0.25)
    n_fr = max(1, 1 + (len(mono) - win) // hop)
    e = np.empty(n_fr)
    for i in range(n_fr):
        seg = mono[i * hop:i * hop + win]
        e[i] = np.mean(seg * seg)
    e_db = 10 * np.log10(e + 1e-12)
    k = 3  # light smoothing: keep abrupt section changes sharp
    es = np.convolve(e_db, np.ones(k) / k, mode="same")
    d = np.diff(es)

    cands = []
    for i, dd in enumerate(d):
        t = (i + 1) * hop / sr
        if t < 3.0 or t > len(mono) / sr - 3.0:
            continue
        if dd >= 4.0:
            cands.append((t, "drop", dd))
        elif dd <= -4.0:
            cands.append((t, "break", -dd))
        elif dd >= 2.0:
            cands.append((t, "build", dd))
    # strongest first, enforce min gap
    cands.sort(key=lambda c: -c[2])
    kept = []
    for t, kind, _s in cands:
        if all(abs(t - kt) >= min_gap_s for kt, _k in kept):
            kept.append((t, kind))
    kept.sort()
    return kept


# ------------------------------------------------------------------ SFX synths
def _fade(a, ms=10, sr=SR):
    n = int(sr * ms / 1000.0)
    n = min(n, len(a) // 2)
    if n > 0:
        f = np.linspace(0, 1, n)[:, None]
        a = a.copy()
        a[:n] *= f
        a[-n:] *= f[::-1]
    return a


def _s_riser(sr, dur=1.5, seed=0):
    rng = np.random.default_rng(seed)
    n = int(sr * dur)
    t = np.arange(n) / sr
    env = np.exp(4.0 * (t / dur - 1.0))  # swell into the hit
    noise = rng.standard_normal(n) * env * 0.5
    f0, f1 = 200.0, 6000.0
    sweep = np.sin(2 * np.pi * (f0 * t + (f1 - f0) * t * t / (2 * dur)))
    y = noise + 0.25 * sweep * env
    return _fade(np.column_stack([y, y]))


def _s_impact(sr, dur=0.9, seed=1):
    rng = np.random.default_rng(seed)
    n = int(sr * dur)
    t = np.arange(n) / sr
    boom = np.sin(2 * np.pi * 55.0 * t) * np.exp(-t * 6.0)
    boom += 0.5 * np.sin(2 * np.pi * 110.0 * t) * np.exp(-t * 9.0)
    noise = rng.standard_normal(n)
    crash = np.diff(noise, prepend=noise[0]) * np.exp(-t * 5.0) * 0.4
    y = (boom + crash) * np.exp(-t * 3.0) * 0.7
    return _fade(np.column_stack([y, y]))


def _s_downshifter(sr, dur=1.2):
    n = int(sr * dur)
    t = np.arange(n) / sr
    f = 800.0 * (60.0 / 800.0) ** (t / dur)
    phase = 2 * np.pi * np.cumsum(f) / sr
    y = np.sin(phase) * np.minimum(1.0, (dur - t) / (dur * 0.3)) * 0.5
    return _fade(np.column_stack([y, y]))


def _s_whoosh(sr, dur=0.8, seed=2):
    rng = np.random.default_rng(seed + 7)
    n = int(sr * dur)
    noise = rng.standard_normal(n)
    b, a = signal.butter(2, [800 / (sr / 2), 6000 / (sr / 2)], btype="band")
    y = signal.lfilter(b, a, noise)
    env = np.sin(np.pi * np.arange(n) / n) ** 2  # swell in the middle
    y = y * env * 0.6
    return _fade(np.column_stack([y, y]))


def build_sfx_layer(n_samples, sr=SR, transitions=(), seed=0):
    """Third layer: risers before drops, impacts on drops, downshifter on
    breaks, whoosh on builds — placed at detected transitions."""
    sfx = np.zeros((n_samples, 2), dtype=np.float64)

    def _place(clip, at_s, gain=1.0):
        s = int(at_s * sr)
        if s >= n_samples:
            return
        e = min(n_samples, s + len(clip))
        sfx[s:e] += clip[:e - s] * gain

    for t, kind in transitions:
        if kind == "drop":
            _place(_s_riser(sr, 1.5, seed + int(t)), t - 1.5, 0.9)
            _place(_s_impact(sr, 0.9, seed + int(t) + 1), t, 1.0)
        elif kind == "break":
            _place(_s_downshifter(sr, 1.2), t - 0.2, 0.8)
        else:  # build
            _place(_s_whoosh(sr, 0.8, seed + int(t) + 2), t - 0.8, 0.7)

    peak = np.max(np.abs(sfx))
    if peak > 0:
        sfx *= 0.89 / peak
    return sfx


# ------------------------------------------------------------------------ mix
def mix_layers(vocals, instrumental, sfx, vols=(1.0, 1.0, 0.8)):
    """Final mix of the 3 layers with per-layer gains. Peak-normalized."""
    n = min(a.shape[0] for a in (vocals, instrumental, sfx))
    mix = (vols[0] * vocals[:n] + vols[1] * instrumental[:n]
           + vols[2] * sfx[:n])
    peak = np.max(np.abs(mix))
    if peak > 0:
        mix = mix * (0.89 / peak)
    return mix


def _pcm16(audio):
    a = np.clip(audio, -1.0, 1.0)
    return (a * 32767.0).astype(np.int16)


def write_wav(path, audio, sr=SR):
    wav_write(path, sr, _pcm16(audio))