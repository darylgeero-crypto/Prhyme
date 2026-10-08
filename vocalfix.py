"""DJRILL vocal fix — clarity enhancement + subtle timing correction.

Only EDITS the real human recording: gentle noise cleanup, presence lift,
de-essing, and small timing nudges toward the beat grid.

HARD RULES (Daryl's standing orders):
- NEVER delete, cut, silence, or drop words — only compress/extend slightly.
- NEVER synthesize, clone, or replace the voice.
- Timing correction is capped at 50 ms and preserves natural feel.
- If the recording is already on beat, do nothing.

Pure numpy/scipy. No new dependencies.
"""
import numpy as np
from scipy import signal

SR = 44100

# ---------------------------------------------------------------- STFT helpers

_NFFT = 2048
_HOP = 512


def _stft(x):
    _, _, z = signal.stft(x, fs=SR, window="hann", nperseg=_NFFT,
                          noverlap=_NFFT - _HOP, boundary="zeros")
    return z


def _istft(z, n_out):
    _, x = signal.istft(z, fs=SR, window="hann", nperseg=_NFFT,
                        noverlap=_NFFT - _HOP)
    x = np.asarray(x, dtype=np.float64)
    if len(x) < n_out:
        x = np.pad(x, (0, n_out - len(x)))
    return x[:n_out]


def _as_stereo(x):
    x = np.asarray(x, dtype=np.float64)
    if x.ndim == 1:
        x = np.column_stack([x, x])
    return x


def _mono(x):
    return _as_stereo(x).mean(axis=1)


# ---------------------------------------------------------------- 1. clarity

def reduce_noise(x, max_cut_db=7.0):
    """Gentle spectral gating. Soft mask only — floor keeps every word audible.

    Noise profile per bin = median magnitude of the quietest 15% of frames.
    Gain never drops below max_cut_db, so nothing is ever fully gated out.
    """
    x = _as_stereo(x)
    out = np.empty_like(x)
    floor = 10.0 ** (-max_cut_db / 20.0)
    for c in range(x.shape[1]):
        z = _stft(x[:, c])
        mag = np.abs(z)
        frame_e = mag.mean(axis=0)
        q = np.quantile(frame_e, 0.15)
        quiet = frame_e <= max(q, 1e-9)
        if not np.any(quiet):
            out[:, c] = x[:, c]
            continue
        noise = np.median(mag[:, quiet], axis=1, keepdims=True) + 1e-12
        # soft mask: full pass well above noise, gentle cut near/below it
        over = mag / (1.6 * noise)
        gain = np.clip((over - 0.4) / 0.6, floor, 1.0)
        # smooth gain over time to avoid musical-noise pumping
        gain = signal.lfilter([0.25, 0.25, 0.25, 0.25], [1.0], gain, axis=1)
        gain = np.clip(gain, floor, 1.0)
        out[:, c] = _istft(z * gain, x.shape[0])
    # keep original peak level so the chain doesn't change loudness staging
    p_in = np.max(np.abs(x)) + 1e-12
    p_out = np.max(np.abs(out)) + 1e-12
    return out * (p_in / p_out)


def presence_boost(x, db=3.0, fc=4000.0, q=0.9):
    """Gentle presence lift ~3-5 kHz for clarity / intelligibility.

    Standard RBJ peaking-EQ biquad: 0 dB far from fc, +db at fc.
    """
    x = _as_stereo(x)
    A = 10.0 ** (db / 40.0)
    w0 = 2.0 * np.pi * fc / SR
    alpha = np.sin(w0) / (2.0 * q)
    b0 = 1.0 + alpha * A
    b1 = -2.0 * np.cos(w0)
    b2 = 1.0 - alpha * A
    a0 = 1.0 + alpha / A
    a1 = -2.0 * np.cos(w0)
    a2 = 1.0 - alpha / A
    b = np.array([b0, b1, b2]) / a0
    a = np.array([1.0, a1 / a0, a2 / a0])
    return signal.lfilter(b, a, x, axis=0)


def deess(x, amount=0.5, band=(5200.0, 9200.0)):
    """Tame harsh sibilance only when it spikes — never a static EQ cut."""
    x = _as_stereo(x)
    sos_lo = signal.butter(4, band[0], btype="lowpass", fs=SR, output="sos")
    sos_hi = signal.butter(4, band[1], btype="highpass", fs=SR, output="sos")
    sib = signal.sosfilt(sos_hi, signal.sosfilt(sos_lo, x, axis=0), axis=0)
    # envelopes: sibilance band vs broadband
    def _env(v):
        e = np.abs(v)
        b2, a2 = signal.butter(2, 25.0, fs=SR)
        return signal.lfilter(b2, a2, e, axis=0) + 1e-9
    e_sib = _env(sib).mean(axis=1, keepdims=True)
    e_all = _env(x).mean(axis=1, keepdims=True)
    ratio = (e_sib / e_all).ravel()
    # sibilant when the band dominates the spectrum
    over = np.clip((ratio - 0.32) / 0.25, 0.0, 1.0)
    # smooth to avoid pumping
    b3, a3 = signal.butter(2, 12.0, fs=SR)
    over = signal.lfilter(b3, a3, over)
    cut = 1.0 - amount * 0.55 * over  # max ~ -4.5 dB at amount=1
    cut = cut[:, None]
    return x - sib * (1.0 - cut)


def polish_vocal_clarity(x, sr=SR):
    """Full clarity chain: gentle denoise -> presence -> de-ess.

    Returns same shape/dtype-family (float64 stereo). Never silences audio.
    """
    assert sr == SR, "vocalfix expects 44.1 kHz"
    x = _as_stereo(x)
    peak_in = np.max(np.abs(x))
    if peak_in < 1e-9:
        return x.copy()
    y = reduce_noise(x)
    y = presence_boost(y, db=3.0)
    y = deess(y, amount=0.5)
    # restore input peak so downstream staging is unchanged
    peak_out = np.max(np.abs(y)) + 1e-12
    y = y * (peak_in / peak_out)
    return np.clip(y, -1.0, 1.0)


# ---------------------------------------------------------------- 2. timing

def detect_onsets(mono, sr=SR, min_gap_s=0.09):
    """Spectral-flux onset detection.

    Returns (times, strengths): onset times in seconds and their
    normalized flux strengths (0..1). Strong onsets = real attacks.
    """
    z = _stft(mono)
    mag = np.abs(z)
    flux = np.sum(np.maximum(0.0, np.diff(mag, axis=1)), axis=0)
    flux = np.concatenate([[0.0], flux])
    # adaptive threshold: local median + scaled MAD
    k = 43  # ~0.5 s window at 86 fps
    med = signal.medfilt(flux, kernel_size=k * 2 + 1)
    mad = signal.medfilt(np.abs(flux - med), kernel_size=k * 2 + 1)
    thr = med + 2.2 * (mad + 1e-9)
    cand = np.where(flux > thr)[0]
    # peak-pick with minimum gap
    min_gap = int(min_gap_s * SR / _HOP)
    picks = []
    for i in cand:
        lo = max(0, i - min_gap // 2)
        hi = min(len(flux), i + min_gap // 2 + 1)
        if flux[i] >= flux[lo:hi].max() - 1e-12:
            if not picks or i - picks[-1] >= min_gap:
                picks.append(i)
    picks = np.array(picks, dtype=np.int64)
    fmax = flux.max() + 1e-12
    strengths = flux[picks] / fmax if len(picks) else np.array([])
    return picks.astype(np.float64) * _HOP / SR, strengths


def _phrase_bounds(mono, sr=SR, min_gap_s=0.22, min_len_s=0.15):
    """Split vocal into phrases at silence gaps. Returns [(start,end)] in sec."""
    win = int(0.02 * sr)
    n = max(1, len(mono) // win)
    rms = np.sqrt(np.mean(mono[:n * win].reshape(n, win) ** 2, axis=1) + 1e-12)
    peak = rms.max()
    thr = max(peak * 0.06, 1e-4)  # ~-24 dB below peak
    active = rms > thr
    bounds, s = [], None
    for i, a in enumerate(active):
        if a and s is None:
            s = i
        elif not a and s is not None:
            bounds.append((s * win / sr, i * win / sr))
            s = None
    if s is not None:
        bounds.append((s * win / sr, len(mono) / sr))
    # merge across short gaps, drop tiny blips
    merged = []
    for b0, b1 in bounds:
        if merged and b0 - merged[-1][1] < min_gap_s:
            merged[-1] = (merged[-1][0], b1)
        elif b1 - b0 >= min_len_s:
            merged.append((b0, b1))
        elif merged:
            merged[-1] = (merged[-1][0], b1)
    return merged


def _estimate_grid_offset(onsets, bpm, dur):
    """Find the beat-grid phase (0..beat) that best explains the onsets."""
    beat = 60.0 / bpm
    if len(onsets) < 3:
        return 0.0
    best, best_off = -1.0, 0.0
    sig = 0.03  # 30 ms coincidence window
    for off in np.linspace(0, beat, 24, endpoint=False):
        d = np.abs(((onsets - off) % beat))
        d = np.minimum(d, beat - d)
        score = np.sum(np.exp(-(d ** 2) / (2 * sig ** 2)))
        if score > best:
            best, best_off = score, off
    return best_off


def fix_vocal_timing(x, sr=SR, bpm=90.0, max_shift_s=0.050):
    """Nudge vocal phrases toward the beat grid.

    Piecewise-linear time warp anchored at phrase boundaries (fixed) and
    vocal onsets (nudged toward nearest 8th-note grid line, capped at
    max_shift_s). Only near-misses are touched — deliberate syncopation
    is left alone. Compresses/extends slightly — never cuts, never deletes.
    Returns (warped, info_dict). If already on beat, returns input unchanged.
    """
    assert sr == SR, "vocalfix expects 44.1 kHz"
    xs = _as_stereo(x)
    n = xs.shape[0]
    dur = n / sr
    mono = _mono(xs)
    if np.max(np.abs(mono)) < 1e-9 or dur < 1.0:
        return xs.copy(), {"corrected": False, "reason": "too_short_or_silent"}

    onsets, strengths = detect_onsets(mono, sr)
    if len(onsets) < 3:
        return xs.copy(), {"corrected": False, "reason": "no_onsets"}
    # strong onsets drive the grid + warping; weak ones are likely noise
    strong = strengths >= 0.35
    if np.sum(strong) >= 3:
        onsets = onsets[strong]
    grid_off = _estimate_grid_offset(onsets, bpm, dur)
    eighth = 60.0 / bpm / 2.0

    def nearest_grid(t):
        g = grid_off + np.round((t - grid_off) / eighth) * eighth
        return g

    # median absolute error -> already-on-beat shortcut
    errs = np.array([t - nearest_grid(t) for t in onsets])
    # already-on-beat shortcut (15 ms dead zone: below this, timing error
    # is imperceptible and within the detector's own resolution)
    if np.median(np.abs(errs)) < 0.015:
        return xs.copy(), {"corrected": False, "reason": "already_on_beat",
                            "median_err_ms": float(np.median(np.abs(errs)) * 1000)}

    phrases = _phrase_bounds(mono, sr)
    # anchor points: (src_time, dst_time); boundaries pinned, onsets nudged.
    # Only near-misses (|err| <= max_shift_s) are touched — deliberate
    # syncopation or off-grid subdivisions are left alone.
    src_pts = [0.0]
    dst_pts = [0.0]
    n_fixed = 0
    for (p0, p1) in phrases:
        start_idx = len(dst_pts)
        src_pts.append(p0)
        dst_pts.append(p0)  # phrase-start anchor; shifted below if needed
        in_ph = onsets[(onsets >= p0) & (onsets <= p1)]
        shift = 0.0
        if len(in_ph):
            err = in_ph[0] - nearest_grid(in_ph[0])
            if 0.005 < abs(err) <= max_shift_s:
                shift = -float(err)
        # warp interior onsets with monotonic, ratio-limited corrections
        prev_s, prev_d = p0, p0 + shift
        for t in in_ph[1:]:
            err = t - nearest_grid(t)
            if not (0.005 < abs(err) <= max_shift_s):
                corr = 0.0
            else:
                corr = -float(err)
            d = t + corr
            # monotonicity + local stretch ratio within [0.92, 1.08]
            min_d = prev_d + 0.030
            lo = prev_d + (t - prev_s) * 0.92
            hi = prev_d + (t - prev_s) * 1.08
            d = min(max(d, min_d, lo), hi)
            # global cap: never move any point more than max_shift_s
            d = min(max(d, t - max_shift_s), t + max_shift_s)
            src_pts.append(t)
            dst_pts.append(d)
            prev_s, prev_d = t, d
            if abs(d - t) > 0.005:
                n_fixed += 1
        if abs(shift) > 0.005:
            dst_pts[start_idx] = p0 + shift
            n_fixed += 1
        src_pts.append(p1)
        dst_pts.append(p1 + shift)
    src_pts.append(dur)
    dst_pts.append(dur)

    src_pts = np.array(src_pts)
    dst_pts = np.array(dst_pts)
    # sort by src, enforce strictly increasing dst
    order = np.argsort(src_pts, kind="stable")
    src_pts, dst_pts = src_pts[order], dst_pts[order]
    for i in range(1, len(dst_pts)):
        if dst_pts[i] <= dst_pts[i - 1]:
            dst_pts[i] = dst_pts[i - 1] + 1e-4

    warped = _piecewise_warp(xs, src_pts, dst_pts)
    info = {"corrected": True, "onsets": int(len(onsets)),
            "nudged": int(n_fixed),
            "median_err_ms": float(np.median(np.abs(errs)) * 1000),
            "max_shift_ms": float(np.max(np.abs(dst_pts - src_pts)) * 1000)}
    return warped, info


def _piecewise_warp(xs, src_pts, dst_pts):
    """Resample xs so src_pts map to dst_pts. Compress/extend only."""
    n = xs.shape[0]
    n_out = int(round(dst_pts[-1] * SR))
    n_out = max(n_out, 16)
    t_out = np.arange(n_out) / SR
    # output time -> input time via inverse piecewise-linear map
    t_in = np.interp(t_out, dst_pts, src_pts)
    t_in = np.clip(t_in, 0, (n - 1) / SR)
    idx = t_in * SR
    i0 = np.floor(idx).astype(np.int64)
    i1 = np.minimum(i0 + 1, n - 1)
    frac = (idx - i0)[:, None]
    return xs[i0] * (1.0 - frac) + xs[i1] * frac


# ---------------------------------------------------------------- QA

def verify_no_dropouts(x_in, x_out, win_s=0.1, tol=0.40):
    """Every voiced input window must keep most of its energy in the output.

    Shift-tolerant: energy may move to an adjacent window (timing nudges
    shift content by up to 50 ms), so each input window is compared against
    the best of its 3 neighboring output windows. Guards the no-deletion rule.
    Returns (ok, worst_ratio).
    """
    a = _mono(x_in)
    b = _mono(x_out)
    w = int(win_s * SR)
    m = min(len(a), len(b))
    if m < w:
        return True, 1.0
    na, nb = len(a) // w, len(b) // w
    n = min(na, nb)
    ea = np.sqrt(np.mean(a[:n * w].reshape(n, w) ** 2, axis=1) + 1e-12)
    eb = np.sqrt(np.mean(b[:n * w].reshape(n, w) ** 2, axis=1) + 1e-12)
    peak = ea.max()
    voiced = ea > (peak * 0.05)
    if not np.any(voiced):
        return True, 1.0
    worst = 1.0
    for i in np.where(voiced)[0]:
        lo, hi = max(0, i - 1), min(n, i + 2)
        best = eb[lo:hi].max() / max(ea[i], 1e-12)
        worst = min(worst, best)
    return worst >= tol, float(worst)
