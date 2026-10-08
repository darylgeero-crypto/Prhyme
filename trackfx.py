"""DJRILL creative track/vocal FX — radio, vinyl, TV, filters, echo.

Pure DSP transforms of the real recording. HARD RULES (Daryl's standing
orders): never delete, cut, silence, or drop words; never synthesize,
clone, or replace a voice. Every effect here is a filter / saturation /
delay — the performance stays 100% human.

Pure numpy/scipy. No new dependencies.
"""
import numpy as np
from scipy import signal

SR = 44100


def _stereo(x):
    x = np.asarray(x, dtype=np.float64)
    if x.ndim == 1:
        x = np.column_stack([x, x])
    return x


def _match_peak(y, x):
    """Restore input peak so FX don't change loudness staging."""
    p_in = np.max(np.abs(x)) + 1e-12
    p_out = np.max(np.abs(y)) + 1e-12
    return y * (p_in / p_out)


# ---------------------------------------------------------------- character FX

def radio(x, drive=0.35):
    """📻 Radio / telephone voice: band-limited 300 Hz – 3 kHz + grit.

    Classic small-speaker sound. Slight tanh saturation for that
    pushed-radio feel. Envelope preserved — words stay intact.
    """
    x = _stereo(x)
    if np.max(np.abs(x)) < 1e-9:
        return x.copy()
    sos = signal.butter(2, [300.0, 3000.0], btype="bandpass",
                        fs=SR, output="sos")
    y = signal.sosfilt(sos, x, axis=0)
    k = 1.0 + float(drive) * 2.0
    y = np.tanh(y * k) / np.tanh(k)
    return np.clip(_match_peak(y, x), -1.0, 1.0)


def tv(x):
    """📺 Television voice: thin, squashed, slightly harsh.

    High-passed at 250 Hz, a 2 kHz presence bite, and fast gentle
    compression for that broadcast-limiter feel.
    """
    x = _stereo(x)
    if np.max(np.abs(x)) < 1e-9:
        return x.copy()
    sos_hp = signal.butter(2, 250.0, btype="highpass", fs=SR, output="sos")
    y = signal.sosfilt(sos_hp, x, axis=0)
    # 2 kHz bite (+2 dB peaking)
    A = 10.0 ** (2.0 / 40.0)
    w0 = 2.0 * np.pi * 2000.0 / SR
    alpha = np.sin(w0) / 2.0
    b = np.array([1 + alpha * A, -2 * np.cos(w0), 1 - alpha * A]) / (1 + alpha / A)
    a = np.array([1.0, -2 * np.cos(w0) / (1 + alpha / A),
                  (1 - alpha / A) / (1 + alpha / A)])
    y = signal.lfilter(b, a, y, axis=0)
    # fast gentle compression: 3:1 above -18 dBFS
    env = np.abs(y)
    b2, a2 = signal.butter(2, 30.0, fs=SR)
    env = signal.lfilter(b2, a2, env, axis=0) + 1e-9
    thr = 10.0 ** (-18.0 / 20.0)
    over = np.clip(env / thr, 1.0, None)
    gain = over ** (1.0 / 3.0 - 1.0)  # 3:1
    gain = np.clip(gain, 0.25, 1.0)
    y = y * gain
    return np.clip(_match_peak(y, x), -1.0, 1.0)


def vinyl(x, crackle=0.5, seed=None):
    """💿 Old record: rolled-off highs, wow/flutter, crackle + surface hiss.

    Nothing is removed — crackle is *added* texture, wow is sub-1% pitch
    wobble. Words stay fully intelligible.
    """
    x = _stereo(x)
    n = x.shape[0]
    if n < 64 or np.max(np.abs(x)) < 1e-9:
        return x.copy()
    rng = np.random.default_rng(seed)
    # rolled-off highs (dusty old pressing)
    sos = signal.butter(2, 7500.0, btype="lowpass", fs=SR, output="sos")
    y = signal.sosfilt(sos, x, axis=0)
    # wow & flutter: slow pitch wobble via variable delay (±4 ms max)
    t = np.arange(n) / SR
    lfo = (np.sin(2 * np.pi * 0.55 * t)
           + 0.4 * np.sin(2 * np.pi * 5.8 * t + 1.3))
    shift = 0.004 * float(crackle) * lfo * SR  # samples
    idx = np.arange(n)[:, None] + shift[:, None]
    idx = np.clip(idx, 0, n - 1.001)
    i0 = np.floor(idx).astype(np.int64)
    frac = (idx - i0)
    i1 = np.minimum(i0 + 1, n - 1)
    i0f = i0[:, 0].astype(np.int64)
    i1f = i1[:, 0].astype(np.int64)
    fr = frac[:, 0]
    yw = np.empty_like(y)
    for c in range(y.shape[1]):
        yc = y[:, c]
        yw[:, c] = yc[i0f] * (1.0 - fr) + yc[i1f] * fr
    y = yw
    # crackle: sparse random pops, scaled by amount
    n_pop = int(n / SR * 6.0 * float(crackle))
    if n_pop > 0:
        pos = rng.integers(0, n, n_pop)
        amp = rng.uniform(-1.0, 1.0, n_pop) * 0.10 * float(crackle)
        y[pos, 0] += amp
        y[pos, 1] += amp * rng.uniform(0.7, 1.0, n_pop)
    # faint surface hiss
    hiss = rng.standard_normal((n, 2)) * 0.0018 * float(crackle)
    sos_h = signal.butter(1, 6000.0, btype="highpass", fs=SR, output="sos")
    hiss = signal.sosfilt(sos_h, hiss, axis=0)
    y = y + hiss
    return np.clip(_match_peak(y, x), -1.0, 1.0)


# ---------------------------------------------------------------- filters

def highpass(x, cutoff=120.0):
    """Adjustable high-pass (20 Hz – 20 kHz). Cleans mud / thins creatively."""
    x = _stereo(x)
    fc = float(np.clip(cutoff, 20.0, 20000.0))
    sos = signal.butter(2, fc, btype="highpass", fs=SR, output="sos")
    return signal.sosfilt(sos, x, axis=0)


def lowpass(x, cutoff=8000.0):
    """Adjustable low-pass (20 Hz – 20 kHz). Darkens / lo-fi's the sound."""
    x = _stereo(x)
    fc = float(np.clip(cutoff, 20.0, 20000.0))
    sos = signal.butter(2, fc, btype="lowpass", fs=SR, output="sos")
    return signal.sosfilt(sos, x, axis=0)


# ---------------------------------------------------------------- echo

def echo(x, delay_ms=375.0, feedback=0.35, mix=0.30):
    """Tape-style echo: one feedback delay line. Never swallows the dry word.

    feedback < 1 always (stable). mix blends echoes under the dry signal.
    """
    x = _stereo(x)
    n = x.shape[0]
    d = int(np.clip(float(delay_ms), 20.0, 2000.0) / 1000.0 * SR)
    fb = float(np.clip(feedback, 0.0, 0.85))
    mx = float(np.clip(mix, 0.0, 0.7))
    if n < d + 8 or mx <= 0.0:
        return x.copy()
    a = np.zeros(d + 1)
    a[0] = 1.0
    a[d] = -fb
    wet = signal.lfilter([1.0], a, x, axis=0)  # dry + decaying echoes
    out = x * (1.0 - mx) + wet * mx
    return np.clip(_match_peak(out, x), -1.0, 1.0)


def dotted_eighth_ms(bpm):
    """Pro touch: echo synced to a dotted 8th at the track BPM."""
    return 60000.0 / max(float(bpm), 1.0) * 0.75


# ---------------------------------------------------------------- orchestrator

def apply_vocal_fx(x, mopts, bpm=90.0):
    """Apply the creative FX chain to a vocal (or any stereo track).

    Order: filters -> character (radio/tv/vinyl) -> echo.
    Returns (processed, applied_names). Never deletes audio.
    """
    x = _stereo(x)
    applied = []
    if mopts.get("fx_hp_on"):
        x = highpass(x, mopts.get("fx_hp_cut", 120.0))
        applied.append(f"HP {mopts.get('fx_hp_cut', 120.0):.0f}Hz")
    if mopts.get("fx_lp_on"):
        x = lowpass(x, mopts.get("fx_lp_cut", 8000.0))
        applied.append(f"LP {mopts.get('fx_lp_cut', 8000.0):.0f}Hz")
    if mopts.get("fx_radio"):
        x = radio(x)
        applied.append("📻 Radio")
    if mopts.get("fx_tv"):
        x = tv(x)
        applied.append("📺 TV")
    if mopts.get("fx_vinyl"):
        seed = mopts.get("seed")
        x = vinyl(x, seed=seed)
        applied.append("💿 Vinyl")
    if mopts.get("fx_echo_on"):
        if mopts.get("fx_echo_sync"):
            dms = dotted_eighth_ms(bpm)
        else:
            dms = mopts.get("fx_echo_ms", 375.0)
        x = echo(x, delay_ms=dms,
                 feedback=mopts.get("fx_echo_fb", 0.35),
                 mix=mopts.get("fx_echo_mix", 0.30))
        tag = f"{dms:.0f}ms" if not mopts.get("fx_echo_sync") else "sync"
        applied.append(f"Echo {tag}")
    # peak safety: never let FX push past unity before the mix stage
    peak = np.max(np.abs(x)) + 1e-12
    if peak > 1.0:
        x = x / peak
    return x, applied
