"""DJRILL mastering FX — extended mastering toolkit for the mobile app.

Additive to djrill_master.py (never changes the V8 default profile):
loudness presets, reference-track matching, stem mastering, ceiling/dither
controls, report cards, mono/DC checks, de-essing, multiband polish,
and named master-chain presets.
"""
import numpy as np
from scipy import signal

import djrill_master as M

SR = 44100

# 16. Loudness targets for different destinations
LOUDNESS_PRESETS = {
    "streaming": -14.0,   # Spotify/Apple/YouTube
    "club": -9.0,          # loud, punchy
    "radio": -12.0,
    "v8": None,            # -> V8_PROFILE target (Daryl's reference)
    "dynamic": -18.0,      # dynamic/headroom-first
    "podcast": -16.0,
}

# 30. Named master-chain presets (target, glue, ceiling, boost, fades)
MASTER_CHAINS = {
    "Streaming":   {"lufs": -14.0, "glue": 1.03, "ceiling": -1.0, "boost_db": 2.5,
                    "fade_in": 0.5, "fade_out": 3.0},
    "Club":        {"lufs": -9.0,  "glue": 1.08, "ceiling": -0.8, "boost_db": 2.0,
                    "fade_in": 0.2, "fade_out": 2.0},
    "Radio":       {"lufs": -12.0, "glue": 1.05, "ceiling": -1.0, "boost_db": 3.0,
                    "fade_in": 0.3, "fade_out": 2.5},
    "V8 Reference":{"lufs": None,  "glue": None, "ceiling": -1.0, "boost_db": 2.5,
                    "fade_in": 0.5, "fade_out": 3.0},  # None -> V8 profile values
    "LoFi Tape":   {"lufs": -16.0, "glue": 1.10, "ceiling": -1.5, "boost_db": 2.5,
                    "fade_in": 1.0, "fade_out": 4.0},
    "Dynamic":     {"lufs": -18.0, "glue": 1.01, "ceiling": -1.0, "boost_db": 2.5,
                    "fade_in": 0.5, "fade_out": 3.0},
}


def resolve_chain(name):
    """Return concrete chain params; V8 Reference pulls from V8_PROFILE."""
    c = dict(MASTER_CHAINS.get(name, MASTER_CHAINS["Streaming"]))
    if c["lufs"] is None:
        c["lufs"] = M.V8_PROFILE["target_lufs"]
    if c["glue"] is None:
        c["glue"] = M.V8_PROFILE["glue_drive"]
    return c


def apply_fades(x, fade_in_s=0.5, fade_out_s=3.0, sr=SR):
    """23. Configurable fades."""
    out = x.copy()
    fi = min(len(out), int(max(0.0, fade_in_s) * sr))
    fo = min(len(out), int(max(0.0, fade_out_s) * sr))
    if fi > 1:
        out[:fi] *= np.linspace(0, 1, fi)[:, None]
    if fo > 1:
        out[-fo:] *= np.linspace(1, 0, fo)[:, None]
    return out


def remove_dc(x):
    """27. DC offset removal (per channel)."""
    return x - np.mean(x, axis=0, keepdims=True)


def deesser_lite(x, sr=SR, amount=0.4):
    """28. Gentle de-esser: tame 6-9 kHz sibilance peaks."""
    if amount <= 0.01:
        return x
    sos = signal.butter(2, [6000, 9000], btype="bandpass", fs=sr, output="sos")
    sib = signal.sosfilt(sos, x, axis=0)
    env = np.maximum(np.abs(sib), 1e-6)
    # smooth envelope
    k = int(0.005 * sr)
    ker = np.ones(k) / k
    env_s = np.apply_along_axis(lambda m: np.convolve(m, ker, mode="same"), 0, env)
    thr = np.percentile(env_s, 92, axis=0, keepdims=True)
    over = np.clip((env_s - thr) / (thr + 1e-9), 0, 1)
    gain = 1.0 - amount * 0.5 * over
    return x - sib * (1.0 - gain)


def multiband_polish(x, sr=SR, low_db=0.5, mid_db=0.0, high_db=0.8):
    """29. Gentle 3-band polish: lift lows/highs, keep mids honest."""
    sos_lo = signal.butter(2, 250, btype="lowpass", fs=sr, output="sos")
    sos_hi = signal.butter(2, 6000, btype="highpass", fs=sr, output="sos")
    lo = signal.sosfilt(sos_lo, x, axis=0)
    hi = signal.sosfilt(sos_hi, x, axis=0)
    mid = x - lo - hi
    return (lo * 10 ** (low_db / 20.0) + mid * 10 ** (mid_db / 20.0)
            + hi * 10 ** (high_db / 20.0))


def mono_check(x):
    """26. Mono-compatibility: correlation + mono-fold level loss."""
    if x.shape[1] < 2:
        return {"mono_compatible": True, "correlation": 1.0, "fold_loss_db": 0.0}
    l, r = x[:, 0], x[:, 1]
    l0, r0 = l - l.mean(), r - r.mean()
    denom = np.sqrt(np.sum(l0 ** 2) * np.sum(r0 ** 2)) + 1e-12
    corr = float(np.sum(l0 * r0) / denom)
    stereo_peak = float(np.max(np.abs(x)))
    mono_peak = float(np.max(np.abs((l + r) / 2)))
    loss = 20 * np.log10((mono_peak + 1e-9) / (stereo_peak + 1e-9))
    return {"mono_compatible": bool(corr > 0.3),
            "correlation": round(corr, 3),
            "fold_loss_db": round(float(loss), 2)}


def report_card(pcm16, sr=SR):
    """24. Detailed mastering report: LUFS, TP, dynamic range, width, DC."""
    x = pcm16.astype(np.float64) / 32768.0
    lufs = M.integrated_lufs(x, sr)
    tp = M.true_peak(x, sr)
    tp_db = 20 * np.log10(tp + 1e-12)
    # dynamic range: peak-to-loudness
    peak_db = 20 * np.log10(np.max(np.abs(x)) + 1e-12)
    dr = peak_db - (lufs if np.isfinite(lufs) else peak_db)
    # stereo width: mid/side energy ratio
    if x.shape[1] > 1:
        mid = (x[:, 0] + x[:, 1]) / 2
        side = (x[:, 0] - x[:, 1]) / 2
        width = 20 * np.log10((np.sqrt(np.mean(side ** 2)) + 1e-9)
                              / (np.sqrt(np.mean(mid ** 2)) + 1e-9))
    else:
        width = float("-inf")
    dc = float(np.max(np.abs(np.mean(x, axis=0))))
    ok_tp, _ = M.verify_no_clipping(pcm16, sr)
    mono = mono_check(x)
    return {
        "lufs": round(float(lufs), 1) if np.isfinite(lufs) else None,
        "true_peak_dbtp": round(float(tp_db), 2),
        "dynamic_range_db": round(float(dr), 1),
        "stereo_width_db": round(float(width), 1) if np.isfinite(width) else None,
        "dc_offset": round(dc, 5),
        "no_clipping": bool(ok_tp),
        "mono": mono,
        "duration_s": round(len(x) / sr, 1),
    }


def match_reference_spectrum(mix, ref_path, sr=SR, max_corr_db=7.0):
    """17. Bend mix spectrum + loudness toward an uploaded reference track."""
    _, ref = M.load_audio(ref_path)
    ref_bands = M.spectral_bands(ref.mean(axis=1), sr)
    ref_lufs = M.integrated_lufs(ref, sr)
    mix_bands = M.spectral_bands(mix.mean(axis=1), sr)
    taps, deltas = M.design_match_eq(mix_bands, ref_bands, sr,
                                     max_corr_db=max_corr_db)
    mix = M.apply_fir(mix, taps)
    target = float(ref_lufs) if np.isfinite(ref_lufs) else -14.0
    return mix, target, [round(float(d), 1) for d in deltas]


def stem_master(stems, sr=SR, target_lufs=-14.0, ceiling_db=-1.0,
                glue_drive=1.03, dither=True):
    """18. Master N stems: gentle per-stem polish, sum, glue, limit.

    stems: list of (name, audio) float64 stereo arrays.
    Returns (pcm16, report)."""
    polished = []
    for name, audio in stems:
        a = M.highpass(audio, sr, 70)
        a = M.gentle_compress(a, sr)
        peak = np.max(np.abs(a))
        if peak > 0:
            a = a / peak * 0.8
        polished.append(a)
    n = max(a.shape[0] for a in polished)
    mix = np.zeros((n, 2))
    for a in polished:
        mix[:a.shape[0]] += a / max(1, len(polished) ** 0.5)
    # bus glue
    mix = np.tanh(mix * glue_drive) / np.tanh(glue_drive)
    lufs = M.integrated_lufs(mix, sr)
    if np.isfinite(lufs):
        mix = mix * 10 ** ((target_lufs - lufs) / 20.0)
    tp = M.true_peak(mix, sr)
    ceiling = 10 ** (ceiling_db / 20.0)
    if tp > ceiling and tp > 0:
        mix = mix * (ceiling / tp)
    mix = np.clip(mix, -1.0, 1.0)
    if dither:
        dith = ((np.random.rand(*mix.shape) - np.random.rand(*mix.shape))
                * (0.5 / 32768.0))
        mix = np.clip(mix + dith, -1.0, 1.0)
    pcm16 = (mix * 32767).astype(np.int16)
    ok, tp_db = M.verify_no_clipping(pcm16, sr)
    if not ok:
        raise ValueError(f"Stem master clips at {tp_db:.1f} dBTP — refusing")
    return pcm16, report_card(pcm16, sr)


def master_with_options(mix, chain_name="Streaming", target_lufs=None,
                        ceiling_db=-1.0, glue_drive=None, dither=True,
                        deess=0.0, multiband=False, sr=SR):
    """Full option-aware master. V8 Reference chain keeps V8 defaults."""
    c = resolve_chain(chain_name)
    tl = target_lufs if target_lufs is not None else c["lufs"]
    gd = glue_drive if glue_drive is not None else c["glue"]
    x = remove_dc(mix)
    if deess > 0:
        x = deesser_lite(x, sr, deess)
    if multiband:
        x = multiband_polish(x, sr)
    x = np.tanh(x * gd) / np.tanh(gd)
    lufs = M.integrated_lufs(x, sr)
    if np.isfinite(lufs):
        x = x * 10 ** ((tl - lufs) / 20.0)
    tp = M.true_peak(x, sr)
    ceiling = 10 ** (ceiling_db / 20.0)
    if tp > ceiling and tp > 0:
        x = x * (ceiling / tp)
    x = np.clip(x, -1.0, 1.0)
    if dither:
        x = np.clip(x + (np.random.rand(*x.shape) - np.random.rand(*x.shape))
                    * (0.5 / 32768.0), -1.0, 1.0)
    pcm16 = (x * 32767).astype(np.int16)
    ok, tp_db = M.verify_no_clipping(pcm16, sr, ceiling_db=ceiling_db)
    if not ok:
        raise ValueError(f"Master clips at {tp_db:.1f} dBTP — refusing")
    return pcm16, report_card(pcm16, sr)
