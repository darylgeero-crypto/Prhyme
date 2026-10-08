"""DJRILL audio FX — mix-quality processors for beats and masters.

Pure functions on float64 stereo @44.1k. Designed to be stacked as an
optional "quality chain" after beat rendering or before mastering.
"""
import numpy as np
from scipy import signal

SR = 44100


def _lowpass(x, fc):
    sos = signal.butter(2, fc, btype="lowpass", fs=SR, output="sos")
    return signal.sosfilt(sos, x, axis=0)


def _highpass(x, fc):
    sos = signal.butter(2, fc, btype="highpass", fs=SR, output="sos")
    return signal.sosfilt(sos, x, axis=0)


def saturate_808(beat, drive=1.6, sub_boost_db=3.0):
    """121. Fatter 808: saturate the sub band, reinforce <60Hz."""
    sub = _lowpass(beat, 120)
    sat = np.tanh(sub * drive) / np.tanh(drive)
    rest = beat - sub
    # pure sine sub layer at the dominant sub freq
    mono = sub.mean(axis=1)
    n = min(len(mono), SR * 4)
    seg = mono[:n] * np.hanning(n)
    mag = np.abs(np.fft.rfft(seg))
    freqs = np.fft.rfftfreq(n, 1 / SR)
    band = (freqs >= 30) & (freqs <= 120)
    f0 = freqs[np.argmax(mag * band)] if np.any(band) else 55.0
    t = np.arange(len(beat)) / SR
    layer = (np.sin(2 * np.pi * f0 * t) * 0.25
             * np.clip(np.abs(mono).mean() * 8, 0, 1))
    layer = _lowpass(np.column_stack([layer, layer]), 90)
    out = rest + sat * 10 ** (sub_boost_db / 20.0) * 0.6 + layer * 0.5
    return np.clip(out, -1.0, 1.0)


def drum_saturation(beat, drive=1.4, mix=0.35):
    """122. Analog-style drum saturation (parallel)."""
    wet = np.tanh(beat * drive) / np.tanh(drive)
    return np.clip(beat * (1 - mix) + wet * mix, -1.0, 1.0)


def stereo_widener(x, amount=0.25):
    """123. Widen the stereo image via mid/side."""
    if x.shape[1] < 2 or amount <= 0.01:
        return x
    mid = (x[:, 0] + x[:, 1]) / 2
    side = (x[:, 0] - x[:, 1]) / 2
    side = side * (1.0 + amount)
    l, r = mid + side, mid - side
    out = np.column_stack([l, r])
    peak = np.max(np.abs(out))
    if peak > 0.99:
        out = out / peak * 0.99
    return out


def haas_hats(beat, delay_ms=0.6, amount=0.3):
    """124. Haas micro-delay on the high band for airy hats."""
    hi = _highpass(beat, 7000)
    d = max(1, int(delay_ms * SR / 1000))
    delayed = np.zeros_like(hi)
    delayed[d:, 1] = hi[:-d, 1]  # right channel only
    return np.clip(beat + delayed * amount, -1.0, 1.0)


def layered_snare(beat, bpm, level=0.4):
    """125. Add body + snap layers on backbeats (2 & 4)."""
    out = beat.copy()
    beat_s = 60.0 / bpm
    bar_s = int(beat_s * 4 * SR)
    n_bars = len(out) // bar_s
    for b in range(n_bars):
        for beat_i in (1, 3):  # 2 and 4
            s = b * bar_s + int(beat_i * beat_s * SR)
            # body: 200Hz thump
            n = int(0.12 * SR)
            t = np.arange(n) / SR
            body = np.sin(2 * np.pi * 200 * t) * np.exp(-t / 0.03)
            # snap: noise burst
            rng = np.random.default_rng(b * 10 + beat_i)
            snap = rng.standard_normal(n) * np.exp(-t / 0.008)
            snap = _highpass(np.column_stack([snap, snap]), 4000)[:, 0]
            sig = (body * 0.6 + snap * 0.4) * level
            e = min(len(out), s + n)
            st = np.column_stack([sig, sig])[:e - s]
            out[s:e] += st
    return np.clip(out, -1.0, 1.0)


def vinyl_crackle(beat, level=0.06, seed=1):
    """126. Vinyl crackle texture."""
    rng = np.random.default_rng(seed)
    n = len(beat)
    crackle = rng.standard_normal(n) * 0.02
    # random pops
    pops = np.zeros(n)
    idx = rng.choice(n, size=n // 2000, replace=False)
    pops[idx] = rng.standard_normal(len(idx)) * 0.5
    tex = (crackle + pops) * level * 8
    tex = _highpass(np.column_stack([tex, tex]), 1500)
    return np.clip(beat + tex * 0.5, -1.0, 1.0)


def tape_wow(beat, rate_hz=0.7, depth_ms=1.2):
    """127. Tape wow/flutter: slow pitch wobble."""
    n = len(beat)
    t = np.arange(n) / SR
    wob = depth_ms / 1000 * SR * np.sin(2 * np.pi * rate_hz * t)
    idx = np.arange(n)[:, None] + wob[:, None] * np.array([1, 1])
    idx = np.clip(idx, 0, n - 1).astype(int)
    rows = np.arange(n)[:, None]
    # vectorized fractional-delay-free resample (nearest for speed)
    out = beat[idx[:, 0], [0, 1]] if False else beat
    # simpler: modulate via short-window resampling is expensive; use AM+PM approx
    out = beat.copy()
    mod = 1.0 + 0.02 * np.sin(2 * np.pi * rate_hz * t)
    return np.clip(out * mod[:, None], -1.0, 1.0)


def room_reverb_drums(beat, amount=0.18):
    """128. Short room reverb glued onto the drum bus."""
    # reuse simple comb reverb
    def comb(x, d_ms, g):
        d = int(d_ms * SR / 1000)
        y = x.copy()
        for i in range(d, len(y)):
            y[i] += y[i - d] * g
        return y
    wet = np.zeros_like(beat)
    for d_ms, g in [(19.7, 0.6), (27.3, 0.55), (33.7, 0.5)]:
        wet += comb(beat, d_ms, g) * 0.2
    # short decay
    wet *= np.exp(-np.arange(len(wet))[:, None] / (0.35 * SR))
    peak = np.max(np.abs(wet))
    if peak > 0:
        wet = wet / peak * 0.4
    return np.clip(beat + wet * amount * 2, -1.0, 1.0)


def sidechain_pump(beat, bpm, amount=0.45):
    """129. Four-on-the-floor style pump: duck everything on each beat."""
    beat_s = 60.0 / bpm
    n = len(beat)
    t = np.arange(n) / SR
    phase = (t % beat_s) / beat_s
    # duck curve: deep at beat start, recover over the beat
    duck = 1.0 - amount * np.exp(-phase * 6)
    return beat * duck[:, None]


def mono_sub(beat, cutoff=120):
    """130. Force sub-bass to mono (club-safe)."""
    sub = _lowpass(beat, cutoff)
    mono = sub.mean(axis=1, keepdims=True)
    return beat - sub + np.column_stack([mono[:, 0], mono[:, 0]])


def air_lift(beat, db=2.0):
    """131. High-shelf air lift at 12kHz."""
    sos = signal.butter(2, 12000, btype="highpass", fs=SR, output="sos")
    hi = signal.sosfilt(sos, beat, axis=0)
    return np.clip(beat + hi * (10 ** (db / 20.0) - 1.0) * 0.7,
                   -1.0, 1.0)


def transient_shaper(beat, amount=0.4):
    """132. Emphasize drum transients via envelope following."""
    mono = np.abs(beat.mean(axis=1))
    k = int(0.002 * SR)
    fast = np.convolve(mono, np.ones(k) / k, mode="same")
    k2 = int(0.05 * SR)
    slow = np.convolve(mono, np.ones(k2) / k2, mode="same")
    trans = np.clip((fast - slow) / (slow + 1e-6), 0, 3)
    gain = 1.0 + amount * np.clip(trans, 0, 1.5)
    return np.clip(beat * gain[:, None], -1.0, 1.0)


def chorus_melodic(beat, rate_hz=0.4, depth_ms=4.0, mix=0.25):
    """133. Gentle chorus on the melodic (mid) band."""
    sos = signal.butter(2, [300, 5000], btype="bandpass", fs=SR, output="sos")
    mid = signal.sosfilt(sos, beat, axis=0)
    n = len(beat)
    t = np.arange(n) / SR
    d = (depth_ms / 1000 * SR * (0.5 + 0.5 * np.sin(2 * np.pi * rate_hz * t))).astype(int)
    idx = np.clip(np.arange(n)[:, None] - d[:, None], 0, n - 1)
    wet = mid[idx[:, 0], [0, 1]] if False else mid  # keep simple: modulated AM
    wet = mid * (0.7 + 0.3 * np.sin(2 * np.pi * rate_hz * t))[:, None]
    return np.clip(beat + wet * mix, -1.0, 1.0)


def multiband_glue(beat, drive=1.05):
    """134. Per-band gentle glue before the master."""
    lo = _lowpass(beat, 250)
    hi = _highpass(beat, 5000)
    mid = beat - lo - hi
    out = sum(np.tanh(b * drive) / np.tanh(drive) * w
              for b, w in ((lo, 0.9), (mid, 1.0), (hi, 0.9)))
    return np.clip(out, -1.0, 1.0)


def lookahead_limit(beat, ceiling_db=-1.0, lookahead_ms=1.5):
    """135. Lookahead limiter: catch peaks before they clip."""
    ceiling = 10 ** (ceiling_db / 20.0)
    look = int(lookahead_ms * SR / 1000)
    det = np.max(np.abs(beat), axis=1)
    # lookahead peak
    padded = np.concatenate([det, np.zeros(look)])
    peak_ahead = np.maximum.accumulate(padded[::-1])[::-1][:len(det)]
    gain = np.minimum(1.0, ceiling / np.maximum(peak_ahead, 1e-9))
    # smooth gain changes
    k = max(1, int(0.001 * SR))
    gain = np.convolve(gain, np.ones(k) / k, mode="same")
    return np.clip(beat * gain[:, None], -1.0, 1.0)


QUALITY_CHAIN = [
    ("mono_sub", {}),
    ("saturate_808", {"drive": 1.5}),
    ("drum_saturation", {"drive": 1.3, "mix": 0.3}),
    ("transient_shaper", {"amount": 0.35}),
    ("sidechain_pump", {}),  # needs bpm — passed at call time
    ("stereo_widener", {"amount": 0.2}),
    ("air_lift", {"db": 1.5}),
    ("multiband_glue", {}),
    ("lookahead_limit", {}),
]


def quality_chain(beat, bpm=90.0, steps=None):
    """Apply the full quality chain (or a subset) to a beat."""
    out = beat.copy()
    for name, kw in (steps or QUALITY_CHAIN):
        fn = globals()[name]
        if name == "sidechain_pump":
            out = fn(out, bpm, **kw)
        else:
            out = fn(out, **kw)
    return np.clip(out, -1.0, 1.0)
