"""DJRILL mastering FX — extended mastering toolkit for the mobile app.

Additive to djrill_master.py (never changes the V8 default profile):
loudness presets, reference-track matching, stem mastering, ceiling/dither
controls, report cards, mono/DC checks, de-essing, multiband polish,
and named master-chain presets.
"""
import numpy as np
from scipy import signal

import djrill_master as M
from audiofx import lookahead_limit

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


def _peak_control(x, sr, ceiling_db, target_lufs=None):
    """Peak control shared by master_with_options and stem_master.

    Limit transients at the ceiling instead of turning the whole track
    down (2026-11-06). True peak (oversampled) can sit above the sample
    peak, so loop: limit, measure TP, lower the limiter ceiling by the
    overshoot until TP complies — capped at 3 dB below the real ceiling,
    because the overshoot is mostly inter-sample (~1 dB) and chasing it
    further just eats loudness. If a loudness target is given and
    limiting shaved energy, make the shortfall back up if headroom
    allows — and re-limit at the REAL ceiling (2026-11-07 fix: the old
    code re-limited at the lowered lim_ceiling, which shaved the makeup
    gain straight back off — Club Punch landed ~3 LU under its target).
    """
    # App vs ffmpeg true-peak meters disagree by ~0.2 dB on inter-sample
    # peaks (app reads lower); every compliance check in here carries
    # this margin so the finished master is inside its ceiling by BOTH
    # meters, not just the app's.
    _TP_MARGIN = 0.3
    lim_ceiling = ceiling_db
    x = lookahead_limit(x, ceiling_db=lim_ceiling)
    for _ in range(3):
        tp_db = 20 * np.log10(max(M.true_peak(x, sr), 1e-9))
        # Break 0.3 dB early, not at the ceiling: the app's true-peak
        # meter reads ~0.2 dB lower than ffmpeg's on inter-sample peaks,
        # and breaking at the ceiling left a master 0.08 dB over it by
        # ffmpeg's measure (2026-11-07 auto bench). The makeup below
        # cannot recover this — it only lifts level, never lowers peaks.
        if tp_db <= ceiling_db - _TP_MARGIN:
            break
        # Lower by the amount TP exceeds the TARGET (ceiling minus the
        # margin), not the ceiling itself: the old step lowered by
        # (tp - ceiling), which is ~0 once TP is already under the
        # ceiling, so the loop stalled with TP stuck between the target
        # and the ceiling and the margin edit changed nothing (proven
        # 2026-11-07: three identical bench runs). TP tracks the limiter
        # ceiling plus a roughly constant inter-sample overshoot, so one
        # jump to the target usually converges.
        lim_ceiling = max(
            lim_ceiling - (tp_db - (ceiling_db - _TP_MARGIN)) - 0.05,
            ceiling_db - 3.0)
        x = lookahead_limit(x, ceiling_db=lim_ceiling)
    if target_lufs is not None:
        lufs2 = M.integrated_lufs(x, sr)
        if np.isfinite(lufs2) and lufs2 < target_lufs - 0.5:
            tp2 = M.true_peak(x, sr)
            # Same 0.3 dB margin as the loop above: the makeup gain lifts
            # the inter-sample peaks with the samples, and the app's meter
            # reads ~0.2 dB low — 0.1 left a master 0.08 dB over its
            # ceiling by ffmpeg's measure (2026-11-07 auto bench).
            headroom_db = ceiling_db - 20 * np.log10(max(tp2, 1e-9)) - _TP_MARGIN
            makeup_db = min(target_lufs - lufs2, max(headroom_db, 0.0))
            if makeup_db > 0.05:
                x = x * 10 ** (makeup_db / 20.0)
                # Re-limit at the ceiling MINUS the TP margin: the limiter
                # caps sample peaks, but inter-sample peaks overshoot
                # ~0.2 dB, so the raw ceiling leaves TP over by ffmpeg.
                x = lookahead_limit(x, ceiling_db=ceiling_db - _TP_MARGIN)
    return x


def analyze_mix(x, sr=SR):
    """Measure what the auto master needs to decide: loudness, true peak,
    crest factor, spectral tilt, sibilance, stereo width. Works on a
    representative excerpt (the caller picks the loudest slice) — cheap
    enough to run once per job."""
    if x.ndim == 1:
        x = x[:, None]
    mono = x.mean(axis=1)
    lufs = M.integrated_lufs(x, sr)
    tp = M.true_peak(x, sr)
    tp_db = 20 * np.log10(max(tp, 1e-9))
    peak_db = 20 * np.log10(max(np.max(np.abs(x)), 1e-9))
    crest = peak_db - lufs if np.isfinite(lufs) else 0.0
    # Spectral tilt on a mono excerpt (<= 30 s, Hann-windowed).
    n = min(len(mono), 30 * sr)
    seg = mono[:n]
    spec = np.abs(np.fft.rfft(seg * np.hanning(len(seg)))) ** 2
    freqs = np.fft.rfftfreq(len(seg), 1.0 / sr)

    def band(lo, hi):
        m = (freqs >= lo) & (freqs < hi)
        return float(np.sum(spec[m])) + 1e-12

    low = band(20, 200)
    mid = band(200, 2000)
    high = band(2000, 8000)
    air = band(8000, 16000)
    total = low + mid + high + air
    mid_sig = (x[:, 0] + x[:, 1]) / 2 if x.shape[1] > 1 else mono
    side_sig = (x[:, 0] - x[:, 1]) / 2 if x.shape[1] > 1 else np.zeros_like(mono)
    width = 20 * np.log10((np.sqrt(np.mean(side_sig ** 2)) + 1e-9)
                          / (np.sqrt(np.mean(mid_sig ** 2)) + 1e-9))
    mono_info = mono_check(x)
    return {
        "lufs": round(float(lufs), 1) if np.isfinite(lufs) else None,
        "true_peak_dbtp": round(float(tp_db), 2),
        "crest_db": round(float(crest), 1),
        "low_pct": round(100 * low / total, 1),
        "mid_pct": round(100 * mid / total, 1),
        "high_pct": round(100 * high / total, 1),
        "air_pct": round(100 * air / total, 1),
        "sibilance_ratio": round(float(band(5000, 8000) / high), 2),
        "stereo_width_db": round(float(width), 1) if np.isfinite(width) else None,
        "mono_compatible": bool(mono_info["mono_compatible"]),
    }


# How much peak-to-loudness each chain tolerates before compression is
# needed to reach its loudness target. Louder chains need a tighter crest.
CHAIN_TARGET_CREST = {
    "Streaming": 10.0, "Club": 8.0, "Radio": 9.0,
    "V8 Reference": 12.0, "LoFi Tape": 12.0, "Dynamic": 14.0,
}
LOUD_GENRES = {"Trap", "Drill", "EDM", "House", "Techno", "Dubstep",
               "Phonk", "Dancehall", "Reggaeton", "Afrobeats"}
DYNAMIC_GENRES = {"Classical", "Jazz", "Ambient", "Blues", "Soul",
                  "Gospel", "Country", "LoFi"}


def auto_decide(analysis, genre=None):
    """LANDR-style judgment: pick chain, loudness target, compression,
    deess and multiband from the measured track. Returns (settings,
    reasons). In auto mode the engine owns the target — the form's -14
    default is not a real choice — and the chain it picks. Manual mode
    never calls this."""
    crest = float(analysis.get("crest_db") or 0.0)
    lufs = analysis.get("lufs")
    if genre in LOUD_GENRES and crest <= 16.0:
        chain = "Club"
    elif genre in DYNAMIC_GENRES:
        # Genuinely dynamic music (classical, jazz, ambient...) keeps its
        # headroom — Dynamic (-18) is the right call there.
        chain = "Dynamic"
    else:
        # Peaky or not, a loud/regular genre targets -14 (Streaming).
        # The compression below tames the crest so the makeup gain can
        # reach -14 without squashing the body. Perfect = -14.
        chain = "Streaming"
    c = resolve_chain(chain)
    target_crest = CHAIN_TARGET_CREST[chain]
    excess = crest - target_crest
    comp_ratio = comp_threshold_db = None
    if excess > 1.0 and lufs is not None:
        # Transient tamer (2026-11-07, proven on the rig): the threshold
        # sits ~8 dB above the track's loudness, so it catches kick/snare
        # transients and spares the body — a low threshold + slow release
        # ducks the whole body after every hit and costs as much LUFS as
        # peak (crest barely moves). Ratio grows with the excess, capped
        # at 4:1. On material whose energy lives in its peaks (sustained
        # bursts, no real transients) this shaves little — the limiter +
        # makeup then do what they can, and the target stays a target,
        # not a promise.
        comp_ratio = round(min(6.0, 2.0 + excess / 3.0), 1)
        comp_threshold_db = round(float(lufs) + 8.0, 1)
    deess = 0.4 if float(analysis.get("sibilance_ratio") or 0.0) > 0.45 else 0.0
    # Dull mix (little high-band energy) gets the polish lift; boomy mixes
    # get none — the polish adds low end, which is the wrong direction.
    multiband = bool(float(analysis.get("high_pct") or 0.0) < 12.0)
    reasons = [
        f"chain {chain} (crest {crest:.1f} dB, genre {genre or 'n/a'})",
        (f"compress {comp_ratio}:1 @ {comp_threshold_db} dB"
         if comp_ratio else "no compression needed"),
        f"deess {deess}" if deess else "no deess",
        "multiband polish" if multiband else "no polish",
    ]
    settings = {
        "chain": chain,
        "target_lufs": c["lufs"],
        "ceiling_db": c["ceiling"],
        "comp_ratio": comp_ratio,
        "comp_threshold_db": comp_threshold_db,
        "deess": deess,
        "multiband": multiband,
    }
    return settings, reasons


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


def _report_card_long(pcm16, sr):
    """Block-wise report_card for long masters (>4 min): identical numbers,
    but never holds a full-track float64 copy (2026-10-21 overhaul — the
    one-shot version needs >1 GB on a 20-min track and got servers killed)."""
    n = len(pcm16)
    blk = 60 * sr
    nch = pcm16.shape[1] if pcm16.ndim > 1 else 1
    sum_l = sum_r = sum_l2 = sum_r2 = sum_lr = 0.0
    mid_ms = side_ms = 0.0
    stereo_peak = mono_peak = 0.0
    cnt = 0
    for i in range(0, n, blk):
        xb = pcm16[i:i + blk].astype(np.float64) / 32768.0
        if xb.ndim == 1:
            xb = xb[:, None]
        l = xb[:, 0]; r = xb[:, 1] if xb.shape[1] > 1 else xb[:, 0]
        sum_l += float(np.sum(l)); sum_r += float(np.sum(r))
        sum_l2 += float(np.sum(l * l)); sum_r2 += float(np.sum(r * r))
        sum_lr += float(np.sum(l * r)); cnt += len(l)
        mid = (l + r) / 2; side = (l - r) / 2
        mid_ms += float(np.sum(mid * mid)); side_ms += float(np.sum(side * side))
        stereo_peak = max(stereo_peak, float(np.max(np.abs(xb))))
        mono_peak = max(mono_peak, float(np.max(np.abs(mid))))
    def gen():
        for i in range(0, n, blk):
            yield pcm16[i:i + blk].astype(np.float64) / 32768.0
    lufs = M.lufs_from_blocks(gen(), sr)
    tp = M.true_peak_from_blocks(gen(), sr)
    tp_db = 20 * np.log10(tp + 1e-12)
    peak_db = 20 * np.log10(stereo_peak + 1e-12)
    dr = peak_db - (lufs if np.isfinite(lufs) else peak_db)
    if nch > 1:
        width = 20 * np.log10((np.sqrt(side_ms / cnt) + 1e-9) / (np.sqrt(mid_ms / cnt) + 1e-9))
        ml = sum_l / cnt; mr = sum_r / cnt
        cov = sum_lr - cnt * ml * mr
        vl = sum_l2 - cnt * ml * ml; vr = sum_r2 - cnt * mr * mr
        corr = float(cov / (np.sqrt(vl * vr) + 1e-12))
        loss = 20 * np.log10((mono_peak + 1e-9) / (stereo_peak + 1e-9))
        mono = {"mono_compatible": bool(corr > 0.3), "correlation": round(corr, 3),
                "fold_loss_db": round(float(loss), 2)}
        dc = float(max(abs(ml), abs(mr)))
    else:
        width = float("-inf")
        mono = {"mono_compatible": True, "correlation": 1.0, "fold_loss_db": 0.0}
        dc = float(abs(sum_l / cnt))
    return {
        "lufs": round(float(lufs), 1) if np.isfinite(lufs) else None,
        "true_peak_dbtp": round(float(tp_db), 2),
        "dynamic_range_db": round(float(dr), 1),
        "stereo_width_db": round(float(width), 1) if np.isfinite(width) else None,
        "dc_offset": round(dc, 5),
        "no_clipping": bool(tp_db <= -1.0 + 0.05),
        "mono": mono,
        "duration_s": round(n / sr, 1),
    }


def report_card(pcm16, sr=SR):
    """24. Detailed mastering report: LUFS, TP, dynamic range, width, DC."""
    if len(pcm16) > 240 * sr:
        return _report_card_long(pcm16, sr)
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
    # Peak control (2026-11-07): the old one-shot whole-track scale-down
    # (mix * ceiling/tp) made every peaky stem master come out quieter
    # than its source — same fix as the main chain (limit + TP loop +
    # makeup at the real ceiling).
    mix = _peak_control(mix, sr, ceiling_db, target_lufs=target_lufs)
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
                        deess=0.0, multiband=False, sr=SR,
                        compress_ratio=None, compress_threshold_db=None):
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
    if compress_ratio is not None and compress_threshold_db is not None:
        # Auto-master compression (2026-11-07): the limiter alone cannot
        # reach a loud target on peaky material — the peaks cap the RMS.
        # Compression shaves the crest BEFORE the gain-to-target, so the
        # limiter doesn't have to eat the gain. Fast attack (0.3 ms) and
        # short release (40 ms) make it a transient tamer: it catches
        # kick/snare peaks and recovers before the body, instead of
        # ducking the whole track. Manual mode never sets this; the auto
        # engine computes ratio/threshold from the measured crest.
        x = M.gentle_compress(x, sr, thr_db=float(compress_threshold_db),
                              ratio=float(compress_ratio),
                              attack_ms=0.3, release_ms=40.0)
    lufs = M.integrated_lufs(x, sr)
    if np.isfinite(lufs):
        x = x * 10 ** ((tl - lufs) / 20.0)
    # Peak control (2026-11-06): limit transients at the ceiling instead of
    # turning the whole track down. LUFS and true peak measure different
    # things — a track can sit at -14 LUFS while single transients exceed
    # -1 dBTP, and the old whole-track attenuation made every peaky track
    # come out quieter than its source.
    x = _peak_control(x, sr, ceiling_db, target_lufs=tl)
    x = np.clip(x, -1.0, 1.0)
    if dither:
        x = np.clip(x + (np.random.rand(*x.shape) - np.random.rand(*x.shape))
                    * (0.5 / 32768.0), -1.0, 1.0)
    pcm16 = (x * 32767).astype(np.int16)
    ok, tp_db = M.verify_no_clipping(pcm16, sr, ceiling_db=ceiling_db)
    if not ok:
        raise ValueError(f"Master clips at {tp_db:.1f} dBTP — refusing")
    return pcm16, report_card(pcm16, sr)
