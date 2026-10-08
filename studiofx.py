"""DJRILL Studio FX — per-track effects for the DAW mixdown.

Additive to daw.py: 3-band EQ, simple compressor, algorithmic reverb send,
tempo-synced delay send, clip fades/gain, and volume automation lanes.
All operate on float64 audio at 44.1k.
"""
import numpy as np
from scipy import signal

SR = 44100


def eq3(x, low_db=0.0, mid_db=0.0, high_db=0.0, sr=SR):
    """51. 3-band track EQ (low shelf 250Hz, high shelf 6kHz)."""
    if not (low_db or mid_db or high_db):
        return x
    sos_lo = signal.butter(2, 250, btype="lowpass", fs=sr, output="sos")
    sos_hi = signal.butter(2, 6000, btype="highpass", fs=sr, output="sos")
    lo = signal.sosfilt(sos_lo, x, axis=0)
    hi = signal.sosfilt(sos_hi, x, axis=0)
    mid = x - lo - hi
    return (lo * 10 ** (low_db / 20.0) + mid * 10 ** (mid_db / 20.0)
            + hi * 10 ** (high_db / 20.0))


def simple_comp(x, sr=SR, thr_db=-18.0, ratio=2.0):
    """52. Gentle per-track compressor."""
    if ratio <= 1.0:
        return x
    det = np.max(np.abs(x), axis=1)
    a_att = np.exp(-1.0 / (0.010 * sr))
    a_rel = np.exp(-1.0 / (0.120 * sr))
    env = np.zeros_like(det)
    e = 0.0
    for i, v in enumerate(det):
        a = a_att if v > e else a_rel
        e = a * e + (1 - a) * v
        env[i] = e
    over = np.maximum(0.0, 20 * np.log10(np.maximum(env, 1e-9)) - thr_db)
    gain = 10 ** (-(over * (1.0 - 1.0 / ratio)) / 20.0)
    return x * gain[:, None]


def algorithmic_reverb(x, sr=SR, amount=0.0, decay=1.8):
    """53. Schroeder-style reverb (4 combs + 2 allpasses), wet only."""
    if amount <= 0.01:
        return np.zeros_like(x)
    def comb(d_ms, g):
        d = int(d_ms * sr / 1000)
        y = np.zeros((len(x) + d * 4, 2))
        y[:len(x)] = x
        for i in range(d, len(y)):
            y[i] += y[i - d] * g
        return y[:len(x)]
    wet = np.zeros_like(x)
    for d_ms, g in [(29.7, 0.75), (33.1, 0.72), (41.1, 0.70), (45.9, 0.68)]:
        wet += comb(d_ms, g) * 0.25
    # two allpasses for diffusion
    for d_ms, g in [(5.0, 0.6), (1.7, 0.6)]:
        d = int(d_ms * sr / 1000)
        y = wet.copy()
        for i in range(d, len(y)):
            y[i] = -g * y[i] + wet[i - d] + g * y[i - d]
        wet = y
    wet = wet * np.exp(-np.arange(len(wet))[:, None] / (decay * sr) * 2)
    peak = np.max(np.abs(wet))
    if peak > 0:
        wet = wet / peak * 0.5
    return wet * amount


def tempo_delay(x, bpm, sr=SR, amount=0.0, beats=0.75, feedback=0.35):
    """54. Tempo-synced delay send (dotted-8th by default), wet only."""
    if amount <= 0.01:
        return np.zeros_like(x)
    d = int(60.0 / bpm * beats * sr)
    if d < 1:
        return np.zeros_like(x)
    wet = np.zeros_like(x)
    # 3 repeats with feedback decay
    for r in range(1, 4):
        s = r * d
        if s >= len(x):
            break
        wet[s:] += x[:len(x) - s] * (feedback ** (r - 1))
    # lowpass the repeats so they sit back
    sos = signal.butter(2, 4000, btype="lowpass", fs=sr, output="sos")
    wet = signal.sosfilt(sos, wet, axis=0)
    peak = np.max(np.abs(wet))
    if peak > 0:
        wet = wet / peak * 0.4
    return wet * amount


def apply_clip_fades(seg, fade_in_s=0.0, fade_out_s=0.0, sr=SR):
    """46. Per-clip fade in/out."""
    out = seg.copy()
    fi = min(len(out), int(max(0.0, fade_in_s) * sr))
    fo = min(len(out), int(max(0.0, fade_out_s) * sr))
    if fi > 1:
        out[:fi] *= np.linspace(0, 1, fi)[:, None]
    if fo > 1:
        out[-fo:] *= np.linspace(1, 0, fo)[:, None]
    return out


def automation_envelope(n, sr, points, default=1.0):
    """55. Volume automation lane: [(time_s, value)] -> gain envelope."""
    if not points:
        return np.full(n, default)
    pts = sorted([(float(t), float(v)) for t, v in points])[:200]
    times = np.array([p[0] for p in pts])
    vals = np.array([p[1] for p in pts])
    grid = np.arange(n) / sr
    return np.interp(grid, times, vals,
                     left=vals[0], right=vals[-1]).clip(0, 2)


def _creative_fx(audio, cr, bpm=90.0, sr=SR):
    """Character FX rack (radio/tv/vinyl/filters/echo) via trackfx.
    cr: {bypass, radio, tv, vinyl, hp_on, hp_cut, lp_on, lp_cut,
         echo_on, echo_ms, echo_fb, echo_mix, echo_sync}.
    No-op when empty or bypassed. Never deletes audio."""
    if not cr or cr.get("bypass"):
        return audio
    import trackfx
    mopts = {
        "fx_hp_on": bool(cr.get("hp_on")), "fx_hp_cut": float(cr.get("hp_cut", 120.0)),
        "fx_lp_on": bool(cr.get("lp_on")), "fx_lp_cut": float(cr.get("lp_cut", 8000.0)),
        "fx_radio": bool(cr.get("radio")), "fx_tv": bool(cr.get("tv")),
        "fx_vinyl": bool(cr.get("vinyl")),
        "fx_echo_on": bool(cr.get("echo_on")),
        "fx_echo_sync": bool(cr.get("echo_sync", True)),
        "fx_echo_ms": float(cr.get("echo_ms", 375.0)),
        "fx_echo_fb": float(cr.get("echo_fb", 0.35)),
        "fx_echo_mix": float(cr.get("echo_mix", 0.30)),
    }
    if not any([mopts["fx_hp_on"], mopts["fx_lp_on"], mopts["fx_radio"],
                mopts["fx_tv"], mopts["fx_vinyl"], mopts["fx_echo_on"]]):
        return audio
    out, _applied = trackfx.apply_vocal_fx(audio, mopts, bpm=bpm)
    return out


def process_track(audio, fx, bpm=90.0, sr=SR):
    """Apply a track's FX chain. fx: {eq:{low,mid,high}, comp:{thr,ratio},
    reverb: 0-1, delay: 0-1, creative:{...}, automation: [(t,v)]}."""
    out = audio.copy()
    eq = fx.get("eq") or {}
    out = eq3(out, eq.get("low", 0), eq.get("mid", 0), eq.get("high", 0), sr)
    comp = fx.get("comp") or {}
    if comp.get("ratio", 1) > 1:
        out = simple_comp(out, sr, comp.get("thr_db", -18), comp.get("ratio", 2))
    # character FX rack sits after comp, before time-based sends
    out = _creative_fx(out, fx.get("creative"), bpm=bpm, sr=sr)
    dry = out
    wet = np.zeros_like(out)
    if fx.get("reverb", 0) > 0:
        wet += algorithmic_reverb(dry, sr, fx["reverb"])
    if fx.get("delay", 0) > 0:
        wet += tempo_delay(dry, bpm, sr, fx["delay"])
    out = dry + wet
    auto = fx.get("automation")
    if auto:
        env = automation_envelope(len(out), sr, auto)
        out = out * env[:, None]
    return np.clip(out, -1.5, 1.5)


def metronome_click(bpm, bars=4, sr=SR, accent_db=0.0):
    """58. Click track: accented downbeat + quarter clicks."""
    beat = 60.0 / bpm
    n = int(bars * 4 * beat * sr)
    out = np.zeros((n, 2))
    def click(f, t0, gain):
        nn = int(0.05 * sr)
        s = int(t0 * sr)
        if s + nn > n:
            return
        tt = np.arange(nn) / sr
        env = np.exp(-tt / 0.008)
        sig = np.sin(2 * np.pi * f * tt) * env * gain
        out[s:s + nn] += np.column_stack([sig, sig])
    for b in range(bars * 4):
        t0 = b * beat
        if b % 4 == 0:
            click(2000, t0, 10 ** (accent_db / 20.0) * 0.8)
        else:
            click(1200, t0, 0.5)
    return out
