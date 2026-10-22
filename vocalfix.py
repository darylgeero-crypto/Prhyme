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


# --- memory-bounded spectral helpers (2026-10-21 crash fix) ---------------
# The full-track float64 STFT chain peaked ~1.3 GB on a 3.5-min track and
# Android's low-memory killer took the whole server down (twice). All
# spectral work below runs in float32 on <=30 s windows, so peak memory is
# bounded no matter how long the track is. Short inputs keep the original
# whole-track float64 path bit-for-bit.
_CHUNK_S = 30.0
_CTX_S = 1.5


def _stft32(x):
    _, _, z = signal.stft(np.asarray(x, dtype=np.float32), fs=SR,
                          window="hann", nperseg=_NFFT,
                          noverlap=_NFFT - _HOP, boundary="zeros")
    return z


def _istft32(z, n_out):
    _, x = signal.istft(z, fs=SR, window="hann", nperseg=_NFFT,
                        noverlap=_NFFT - _HOP)
    x = np.asarray(x, dtype=np.float32)
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

def _gate_segment(seg, floor):
    """The original spectral gate, applied to ONE segment in float32.

    Noise profile comes from the segment's own quietest 15% of frames —
    for a gentle (<=7 dB, floor-limited) gate on vocal material this is
    locally valid and keeps every word audible, exactly like the original.
    """
    seg = np.asarray(seg, dtype=np.float32)
    out = np.empty_like(seg)
    for c in range(seg.shape[1]):
        z = _stft32(seg[:, c])
        mag = np.abs(z)
        frame_e = mag.mean(axis=0)
        q = np.quantile(frame_e, 0.15)
        quiet = frame_e <= max(q, 1e-9)
        if not np.any(quiet):
            out[:, c] = seg[:, c]
            continue
        noise = np.median(mag[:, quiet], axis=1, keepdims=True) + 1e-12
        over = mag / (1.6 * noise)
        gain = np.clip((over - 0.4) / 0.6, floor, 1.0)
        gain = signal.lfilter([0.25, 0.25, 0.25, 0.25], [1.0], gain, axis=1)
        gain = np.clip(gain, floor, 1.0)
        out[:, c] = _istft32(z * gain, seg.shape[0])
        del z, mag, gain
    return out


def reduce_noise(x, max_cut_db=7.0, _return32=False):
    """Gentle spectral gating. Soft mask only — floor keeps every word audible.

    Noise profile per bin = median magnitude of the quietest 15% of frames.
    Gain never drops below max_cut_db, so nothing is ever fully gated out.
    Long inputs are processed in 30 s windows (1.5 s context, discarded) so
    peak memory stays bounded; short inputs use the original whole-track
    float64 path unchanged.
    """
    x = _as_stereo(x) if not (getattr(x, "dtype", None) == np.float32
                              and getattr(x, "ndim", 0) == 2
                              and x.shape[1] == 2) else x
    floor = 10.0 ** (-max_cut_db / 20.0)
    n = x.shape[0]
    chunk = int(_CHUNK_S * SR)
    if n <= chunk * 2:
        out = np.empty_like(x)
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
            over = mag / (1.6 * noise)
            gain = np.clip((over - 0.4) / 0.6, floor, 1.0)
            gain = signal.lfilter([0.25, 0.25, 0.25, 0.25], [1.0], gain, axis=1)
            gain = np.clip(gain, floor, 1.0)
            out[:, c] = _istft(z * gain, x.shape[0])
    else:
        ctx = int(_CTX_S * SR)
        out32 = np.empty((n, x.shape[1]), dtype=np.float32)
        pos = 0
        while pos < n:
            a = max(0, pos - ctx)
            b = min(n, pos + chunk + ctx)
            seg_out = _gate_segment(x[a:b], floor)
            out32[pos:min(n, pos + chunk)] = seg_out[pos - a:pos - a + min(chunk, n - pos)]
            pos += chunk
            del seg_out
        if _return32:
            out = out32
        else:
            out = out32.astype(np.float64)
            del out32
    # keep original peak level so the chain doesn't change loudness staging
    p_in = np.max(np.abs(x)) + 1e-12
    p_out = np.max(np.abs(out)) + 1e-12
    out *= (p_in / p_out)
    return out


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
    if x.dtype == np.float32:
        # keep the filter in float32 so a long track doesn't double in size
        b = b.astype(np.float32)
        a = a.astype(np.float32)
    return signal.lfilter(b, a, x, axis=0)


def deess(x, amount=0.5, band=(5200.0, 9200.0), _return32=False):
    """Tame harsh sibilance only when it spikes — never a static EQ cut.

    Internals run in float32 (2026-10-21 crash fix): the envelope math
    needs no more, and it halves this stage's full-track footprint.
    """
    x = _as_stereo(x)
    xf = x.astype(np.float32)
    sos_lo = signal.butter(4, band[0], btype="lowpass", fs=SR, output="sos").astype(np.float32)
    sos_hi = signal.butter(4, band[1], btype="highpass", fs=SR, output="sos").astype(np.float32)
    sib = signal.sosfilt(sos_hi, signal.sosfilt(sos_lo, xf, axis=0), axis=0)
    # envelopes: sibilance band vs broadband
    def _env(v):
        e = np.abs(v)
        b2, a2 = signal.butter(2, 25.0, fs=SR)
        return signal.lfilter(b2.astype(np.float32), a2.astype(np.float32), e, axis=0) + 1e-9
    e_sib = _env(sib).mean(axis=1, keepdims=True)
    e_all = _env(xf).mean(axis=1, keepdims=True)
    ratio = (e_sib / e_all).ravel()
    # sibilant when the band dominates the spectrum
    over = np.clip((ratio - 0.32) / 0.25, 0.0, 1.0)
    # smooth to avoid pumping
    b3, a3 = signal.butter(2, 12.0, fs=SR)
    over = signal.lfilter(b3.astype(np.float32), a3.astype(np.float32), over)
    cut = 1.0 - amount * 0.55 * over  # max ~ -4.5 dB at amount=1
    cut = cut[:, None]
    sib *= (1.0 - cut)
    xf -= sib
    del sib
    if _return32:
        return xf
    return xf.astype(np.float64)


def polish_vocal_clarity(x, sr=SR):
    """Full clarity chain: gentle denoise -> presence -> de-ess.

    Returns same shape/dtype-family (float64 stereo). Never silences audio.
    """
    assert sr == SR, "vocalfix expects 44.1 kHz"
    x = _as_stereo(x)
    peak_in = np.max(np.abs(x))
    if peak_in < 1e-9:
        return x.copy()
    if x.shape[0] > 60 * SR:
        # Long track: run the whole chain in float32 (2026-10-21 crash fix
        # #2). The float64 chain's copies, stacked on the buffers the
        # master job already holds, were what the low-memory killer ate.
        # DSP is identical; only the working precision halves.
        xf = x.astype(np.float32)
        y = reduce_noise(xf, _return32=True)
        del xf
        y = presence_boost(y, db=3.0)
        y = deess(y, amount=0.5, _return32=True)
        peak_out = np.max(np.abs(y)) + 1e-12
        y *= (peak_in / peak_out)
        np.clip(y, -1.0, 1.0, out=y)
        return y
    y = reduce_noise(x)
    y = presence_boost(y, db=3.0)
    y = deess(y, amount=0.5)
    # restore input peak so downstream staging is unchanged
    peak_out = np.max(np.abs(y)) + 1e-12
    y *= (peak_in / peak_out)
    np.clip(y, -1.0, 1.0, out=y)
    return y


# ---------------------------------------------------------------- 2. timing

def _flux_series(mono):
    """Spectral flux of the whole track, computed in 30 s windows.

    Frame g covers the window starting at sample g*_HOP, exactly as the
    original whole-track STFT indexed it; flux[g] is the positive spectral
    rise into frame g (flux[0] = 0). Segments carry 8192 samples of
    context (>= 16 frames > the 4-frame window reach), so every kept
    frame is computed from real samples, never from a segment's
    zero-boundary. Only one window's spectrogram is ever in memory.
    """
    x = np.asarray(mono, dtype=np.float32).ravel()
    n = len(x)
    core = (int(_CHUNK_S * SR) // _HOP) * _HOP  # HOP-aligned core, samples
    ext = 8192                                  # HOP-aligned context
    total_frames = 1 + int(np.ceil(n / _HOP))
    flux = np.zeros(total_frames, dtype=np.float64)
    pos = 0
    while pos < n:
        a = max(0, pos - ext)
        b = min(n, pos + core + ext)
        z = _stft32(x[a:b])
        mag = np.abs(z)
        d = np.sum(np.maximum(0.0, np.diff(mag, axis=1)), axis=0)
        del z, mag
        base = a // _HOP               # global frame of local frame 0
        lo = pos // _HOP               # first core frame (global)
        hi = total_frames if pos + core >= n else (pos + core) // _HOP
        # d[j] is the rise into local frame j+1 == global frame base+j+1
        j0 = max(0, lo - base - 1)
        j1 = min(len(d), hi - base - 1)
        if j1 > j0:
            flux[base + j0 + 1: base + j0 + 1 + (j1 - j0)] = d[j0:j1]
        del d
        pos += core
    return flux


def detect_onsets(mono, sr=SR, min_gap_s=0.09):
    """Spectral-flux onset detection.

    Returns (times, strengths): onset times in seconds and their
    normalized flux strengths (0..1). Strong onsets = real attacks.
    """
    flux = _flux_series(mono)
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


def _breath_spans(mono, phrases, sr=SR):
    """Find breath/gap regions inside phrases: stretches between words
    whose level sits in the breath band (well below word level, above the
    silence floor) for at least 60 ms. Breaths get translated rigidly by
    the timing warp (anchors around them carry the local shift) — never
    stretched, never gated out. Daryl's rule, 2026-10-21."""
    spans = []
    win = int(0.01 * sr)
    n = max(1, len(mono) // win)
    if n == 0:
        return spans
    rms = np.sqrt(np.mean(mono[:n * win].reshape(n, win) ** 2, axis=1) + 1e-12)
    for (p0, p1) in phrases:
        i0, i1 = int(p0 * sr) // win, min(n, int(p1 * sr) // win)
        if i1 - i0 < 6:
            continue
        seg = rms[i0:i1]
        peak = seg.max()
        if peak <= 0:
            continue
        lo_thr, hi_thr = peak * 0.02, peak * 0.22
        in_b = (seg > lo_thr) & (seg < hi_thr)
        s = None
        for j, b in enumerate(in_b):
            if b and s is None:
                s = j
            elif not b and s is not None:
                if (j - s) * 0.01 >= 0.06:
                    spans.append(((i0 + s) * win / sr, (i0 + j) * win / sr))
                s = None
        if s is not None and (len(in_b) - s) * 0.01 >= 0.06:
            spans.append(((i0 + s) * win / sr, i1 * win / sr))
    return spans


def fix_vocal_timing(x, sr=SR, bpm=90.0, max_shift_s=0.060):
    """Nudge vocal phrases toward the beat grid.

    Piecewise-linear time warp anchored at phrase boundaries (fixed) and
    vocal onsets (nudged toward nearest 8th-note grid line, capped at
    max_shift_s). Only near-misses are touched — deliberate syncopation
    is left alone. Compresses/extends slightly — never cuts, never deletes.
    Returns (warped, info_dict). If already on beat, returns input unchanged.
    """
    assert sr == SR, "vocalfix expects 44.1 kHz"
    if getattr(x, "dtype", None) == np.float32 and getattr(x, "ndim", 0) == 2 \
            and x.shape[1] == 2:
        xs = x  # already float32 stereo: don't double it via _as_stereo
    else:
        xs = _as_stereo(x)
    n = xs.shape[0]
    dur = n / sr
    mono = xs.mean(axis=1)
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
    prev_end = 0.0
    for (p0, p1) in phrases:
        start_idx = len(dst_pts)
        src_pts.append(p0)
        dst_pts.append(p0)  # phrase-start anchor; shifted below if needed
        in_ph = onsets[(onsets >= p0) & (onsets <= p1)]
        shift = 0.0
        if len(in_ph):
            # phrase shift = MEDIAN error of its onsets (robust: one bad
            # onset detection can't yank the whole phrase)
            ph_errs = np.array([t - nearest_grid(t) for t in in_ph])
            med_err = float(np.median(ph_errs))
            if 0.005 < abs(med_err) <= max_shift_s:
                shift = -med_err
            # never eat more than the preceding silence (keep >=30 ms of
            # it) when shifting a phrase earlier
            if shift < 0:
                gap = p0 - prev_end
                shift = max(shift, -(max(0.0, gap - 0.030)))
        # warp interior onsets with monotonic, ratio-limited corrections
        prev_s, prev_d = p0, p0 + shift
        for t in in_ph[1:]:
            err = t - nearest_grid(t)
            if not (0.005 < abs(err) <= max_shift_s):
                corr = 0.0
            else:
                corr = -float(err)
            d = t + corr
            # monotonicity + local stretch ratio within [0.97, 1.03]
            min_d = prev_d + 0.030
            lo = prev_d + (t - prev_s) * 0.97
            hi = prev_d + (t - prev_s) * 1.03
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
        prev_end = p1
    # breaths: anchor pairs around each breath span carrying the local
    # shift, so the warp translates breaths rigidly (rate stays ~1.0
    # across them) instead of stretching them.
    try:
        for (b0, b1) in _breath_spans(mono, phrases, sr):
            for tb in (b0, b1):
                sh = float(np.interp(tb, src_pts, dst_pts)) - tb
                src_pts.append(tb)
                dst_pts.append(tb + sh)
    except Exception:
        pass
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
    """Resample xs so src_pts map to dst_pts. Compress/extend only.

    Quality rebuild (2026-10-21, Daryl: "that fucky sound"): the old warp
    sampled with LINEAR interpolation — a 2-tap blend that low-passes
    everything it touches, smearing consonant attacks, sibilance and
    breaths. This version:
      * smooths the time map with a monotone cubic (PCHIP) through the
        anchors, so the local rate is continuous — no rate kinks sitting
        on word attacks;
      * samples with a 32-tap Hann-windowed sinc (bandlimited), the same
        class of interpolator studio resamplers use — HF content
        survives the warp.
    Same anchors, same output length, same never-delete guarantees.
    Chunked float32 so long tracks stay RAM-flat.
    """
    from scipy.interpolate import PchipInterpolator
    n = xs.shape[0]
    n_out = int(round(dst_pts[-1] * SR))
    n_out = max(n_out, 16)
    xs32 = xs if xs.dtype == np.float32 else xs.astype(np.float32)
    nch = xs32.shape[1]
    out = np.empty((n_out, nch), dtype=np.float32)
    fmap = PchipInterpolator(dst_pts, src_pts, extrapolate=False)
    TAPS = 16  # windowed-sinc half-width (32 taps total)
    taps_off = np.arange(-TAPS + 1, TAPS + 1, dtype=np.float64)
    block = 2 * SR
    pos = 0
    while pos < n_out:
        end = min(n_out, pos + block)
        m = end - pos
        t_out = np.arange(pos, end, dtype=np.float64) / SR
        t_in = fmap(t_out)
        t_in = np.nan_to_num(t_in, nan=0.0)
        np.clip(t_in, 0.0, (n - 1) / SR, out=t_in)
        x = t_in * SR  # fractional source positions
        del t_out, t_in
        base = np.floor(x).astype(np.int64)
        idx = base[:, None] + taps_off[None, :].astype(np.int64)  # (m, 32)
        d = x[:, None] - idx.astype(np.float64)                  # distance
        # Hann-windowed sinc kernel
        w = np.sinc(d) * (0.5 + 0.5 * np.cos(np.pi * d / TAPS))
        w = np.where(np.abs(d) < TAPS, w, 0.0)
        wsum = np.sum(w, axis=1, keepdims=True)
        w = (w / np.maximum(wsum, 1e-12)).astype(np.float32)
        idx_c = np.clip(idx, 0, n - 1)
        gathered = xs32[idx_c]                                    # (m, 32, ch)
        out[pos:end] = np.einsum('mt,mtc->mc', w, gathered).astype(np.float32)
        del x, base, idx, d, w, idx_c, gathered
        pos = end
    return out


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
