"""DJRILL beat FX — post-processing for rendered beats.

Operates on finished stereo beat audio (float64, 44.1k): drum fills,
humanization, swing, risers, builds, time-feel, key transpose, arrangement
helpers, 808 enhancement, hat rolls, percussion layers, intro/outro
building, crash accents, and filename tagging.

All functions are pure (input -> new array) and seeded for reproducibility.
"""
import numpy as np
from scipy import signal

SR = 44100


def _rng(seed):
    return np.random.default_rng(abs(int(seed)) % (2 ** 63 - 1))


def _noise_hit(dur, sr=SR, decay=0.02, seed=1):
    """Short synthesized percussive hit (for fills/rolls)."""
    n = int(dur * sr)
    r = _rng(seed)
    x = r.standard_normal(n) * np.exp(-np.arange(n) / (decay * sr))
    # band-limit to snare-ish region
    sos = signal.butter(2, [1200, 8000], btype="bandpass", fs=sr, output="sos")
    return signal.sosfilt(sos, x)


def _sine_drop(f0, f1, dur, sr=SR, decay=0.3, seed=1):
    """Pitch-dropping sine (808-style boom for fills)."""
    n = int(dur * sr)
    t = np.arange(n) / sr
    f = f0 + (f1 - f0) * (t / dur)
    ph = 2 * np.pi * np.cumsum(f) / sr
    return np.sin(ph) * np.exp(-t / decay)


def drum_fills(beat, bpm, every_bars=4, seed=1, level=0.5):
    """#2 Insert a snare-roll fill in the last beat before every Nth bar end."""
    out = beat.copy()
    bar = 60.0 / bpm * 4
    beat16 = bar / 4
    n_bars = int(len(out) / SR / bar)
    for b in range(every_bars, n_bars + 1, every_bars):
        fill_start = int((b * bar - beat16) * SR)
        if fill_start + int(beat16 * SR) > len(out):
            continue
        # 4 accelerating snare hits + final accent
        for i in range(4):
            s = fill_start + int(i * beat16 / 4 * SR)
            hit = _noise_hit(0.09, decay=0.015, seed=seed + b * 10 + i)
            e = min(len(out), s + len(hit))
            g = level * (0.5 + 0.5 * i / 3)
            out[s:e] += np.column_stack([hit, hit])[:e - s] * g
        # low boom on the downbeat
        s = int(b * bar * SR)
        boom = _sine_drop(120, 45, 0.35, seed=seed + b)
        e = min(len(out), s + len(boom))
        out[s:e] += np.column_stack([boom, boom])[:e - s] * level * 0.7
    return np.clip(out, -1.0, 1.0)


def humanize(beat, bpm, amount=0.5, seed=1):
    """#3 Subtle timing + level wander so the beat breathes like a player."""
    r = _rng(seed)
    out = beat.copy().astype(np.float64)
    bar = 60.0 / bpm * 4
    n_bars = max(1, int(len(out) / SR / bar))
    for b in range(n_bars):
        s0 = int(b * bar * SR)
        s1 = min(len(out), int((b + 1) * bar * SR))
        if s1 <= s0:
            continue
        # tiny timing nudge (±6ms) and level wander (±1.5dB)
        shift = int(r.normal(0, 0.006 * amount) * SR)
        gain = 10 ** (r.normal(0, 1.5 * amount) / 20.0)
        seg = out[s0:s1] * gain
        if shift > 0 and s0 + shift < len(out):
            out[s0:s1] = 0
            e = min(len(out), s0 + shift + (s1 - s0))
            out[s0 + shift:e] = seg[:e - s0 - shift]
        elif shift < 0:
            e = min(len(out), s1 + shift)
            out[s0:s1] = 0
            out[s0:max(s0, e - (s1 - s0) + (s1 - s0)):e] = seg[:max(0, e - s0)]
        else:
            out[s0:s1] = seg
    return np.clip(out, -1.0, 1.0)


def apply_swing(beat, bpm, swing=0.0):
    """#4 Delay off-beat 16th notes (swing 0.0=straight, 1.0=triplet feel)."""
    if swing <= 0.01:
        return beat
    out = beat.copy()
    sixteenth = 60.0 / bpm / 4
    n16 = int(len(out) / SR / sixteenth)
    # delay odd 16ths by swing * half a 16th
    delay_s = swing * sixteenth * 0.5
    d = int(delay_s * SR)
    if d < 1:
        return beat
    for i in range(1, n16, 2):
        s = int(i * sixteenth * SR)
        e = min(len(out), s + int(sixteenth * SR))
        if e <= s or s + d >= len(out):
            continue
        seg = out[s:e].copy()
        out[s:e] *= 0.15  # duck original position
        e2 = min(len(out), s + d + (e - s))
        out[s + d:e2] += seg[:e2 - s - d] * 0.85
    return np.clip(out, -1.0, 1.0)


def risers(beat, bpm, sections=(8, 16, 24), seed=1, level=0.35):
    """#5 White-noise riser sweeping up into each section change (bar #)."""
    out = beat.copy()
    bar = 60.0 / bpm * 4
    rise_len = int(bar * SR)
    for b in sections:
        end = int(b * bar * SR)
        start = max(0, end - rise_len)
        if start >= len(out):
            continue
        n = end - start
        r = _rng(seed + b)
        noise = r.standard_normal(n)
        env = np.linspace(0.02, 1.0, n) ** 2
        # upward sweep: simple one-pole highpass with rising cutoff
        t = np.arange(n) / SR
        sweep = signal.sosfilt(
            signal.butter(2, 400 + 7600 * (t / max(t[-1], 1e-6)),
                          btype="highpass", fs=SR, output="sos"),
            noise)
        rise = (sweep * env * level)
        out[start:end] += np.column_stack([rise, rise])
    return np.clip(out, -1.0, 1.0)


def drop_builds(beat, bpm, at_bars=(16,), seed=1, level=0.5):
    """#6 Snare roll build-up (doubling rate) into the drop bar."""
    out = beat.copy()
    bar = 60.0 / bpm * 4
    for b in at_bars:
        end = int(b * bar * SR)
        start = max(0, end - int(bar * SR))
        if start >= len(out):
            continue
        # 8 hits accelerating: intervals shrink geometrically
        total = end - start
        times = np.cumsum([total * 0.5 ** (i + 1) for i in range(8)])
        times = times[times < total]
        for i, ts in enumerate(times):
            s = start + int(ts)
            hit = _noise_hit(0.06, decay=0.01, seed=seed + b * 20 + i)
            e = min(len(out), s + len(hit))
            g = level * (0.4 + 0.6 * i / max(1, len(times) - 1))
            out[s:e] += np.column_stack([hit, hit])[:e - s] * g
    return np.clip(out, -1.0, 1.0)


def time_feel(beat, bpm, feel="normal"):
    """#7 Half-time (heavier) or double-time (urgent) feel via resample."""
    if feel == "half":
        # stretch 2x then we keep same length by crossfading looped halves
        n = len(beat)
        stretched = signal.resample(beat, n * 2, axis=0)[:n]
        return np.clip(stretched * 0.9, -1.0, 1.0)
    if feel == "double":
        n = len(beat)
        # play twice as fast, tile to fill
        fast = signal.resample(beat, n // 2, axis=0)
        tiled = np.tile(fast, (2, 1))[:n]
        return np.clip(tiled * 0.9, -1.0, 1.0)
    return beat


def transpose(beat, semitones=0):
    """#8 Key transpose of the whole beat (resample pitch-shift)."""
    if semitones == 0:
        return beat
    ratio = 2.0 ** (semitones / 12.0)
    n = len(beat)
    shifted = signal.resample(beat, int(n / ratio), axis=0)
    # restore original length by tiling/cropping (keeps BPM grid)
    if len(shifted) < n:
        rep = int(np.ceil(n / len(shifted)))
        shifted = np.tile(shifted, (rep, 1))[:n]
    else:
        shifted = shifted[:n]
    return np.clip(shifted, -1.0, 1.0)


def arrangement_variants(beat, bpm, variant=0):
    """#9 Reorder 8-bar phrases for alternate song shapes (0-5)."""
    bar = 60.0 / bpm * 4
    bar_s = int(bar * SR)
    n_bars = len(beat) // bar_s
    if n_bars < 8:
        return beat
    n8 = (n_bars // 8) * 8
    phrases = [beat[i * 8 * bar_s:(i + 1) * 8 * bar_s] for i in range(n8 // 8)]
    orders = {
        0: None,  # original
        1: list(reversed(range(len(phrases)))),
        2: sorted(range(len(phrases)), key=lambda i: (i % 2, i)),
        3: [len(phrases) - 1] + list(range(len(phrases) - 1)),
        4: list(range(1, len(phrases))) + [0],
        5: sorted(range(len(phrases)), key=lambda i: -i if i % 2 else i),
    }
    order = orders.get(variant % 6)
    if not order:
        return beat
    out = np.concatenate([phrases[i] for i in order], axis=0)
    tail = beat[len(out):]
    return np.concatenate([out, tail], axis=0) if len(tail) else out


def glide_808(beat, bpm, amount=0.5, seed=1):
    """#10 Pitch-glide flavor on the sub: slow downward bends each bar."""
    if amount <= 0.01:
        return beat
    out = beat.copy()
    # isolate sub, bend it, blend back
    sos = signal.butter(2, 120, btype="lowpass", fs=SR, output="sos")
    sub = signal.sosfilt(sos, out, axis=0)
    bar = 60.0 / bpm * 4
    bar_s = int(bar * SR)
    n_bars = len(out) // bar_s
    r = _rng(seed)
    for b in range(n_bars):
        s0, s1 = b * bar_s, min(len(out), (b + 1) * bar_s)
        if s1 - s0 < SR // 4 or r.random() > 0.6:
            continue
        # pitch envelope: dip down a semitone-ish over 300ms at bar start
        n = min(int(0.3 * SR), s1 - s0)
        bend = np.linspace(0, -0.06 * amount, n)  # fractional delay in samples
        seg = sub[s0:s0 + n].copy()
        idx = np.arange(n) + bend * SR / 100  # subtle
        idx = np.clip(idx, 0, n - 1)
        sub[s0:s0 + n] = seg[idx.astype(int)] * 0.9 + seg * 0.1
    # replace sub region
    out = out - signal.sosfilt(sos, out, axis=0) + sub
    return np.clip(out, -1.0, 1.0)


def hat_rolls(beat, bpm, density=0.5, seed=1):
    """#11 Extra hi-hat roll flourishes at random bar ends."""
    if density <= 0.01:
        return beat
    out = beat.copy()
    r = _rng(seed)
    bar = 60.0 / bpm * 4
    sixteenth = bar / 4
    bar_s = int(bar * SR)
    n_bars = len(out) // bar_s
    for b in range(n_bars):
        if r.random() > density * 0.5:
            continue
        # 32nd-note roll over the last 16th of the bar
        roll_start = (b + 1) * bar_s - int(sixteenth * SR)
        n_hits = 4
        for i in range(n_hits):
            s = roll_start + int(i * sixteenth / 4 * SR)
            hit = _noise_hit(0.03, decay=0.008, seed=seed + b * 30 + i)
            # highpass harder for hat-like tick
            sos = signal.butter(2, 6000, btype="highpass", fs=SR, output="sos")
            hit = signal.sosfilt(sos, hit)
            e = min(len(out), s + len(hit))
            out[s:e] += np.column_stack([hit, hit])[:e - s] * 0.25
    return np.clip(out, -1.0, 1.0)


def perc_layer(beat, bpm, seed=1, level=0.3):
    """#12 Add a shaker/percussion groove layer on top."""
    out = beat.copy()
    r = _rng(seed)
    sixteenth = 60.0 / bpm / 4
    n16 = int(len(out) / SR / sixteenth)
    # syncopated shaker pattern
    pat = [0.9, 0.3, 0.6, 0.3, 0.7, 0.3, 0.9, 0.4,
           0.9, 0.3, 0.6, 0.5, 0.7, 0.3, 0.8, 0.3]
    for i in range(n16):
        v = pat[i % 16] * (0.85 + 0.3 * r.random())
        if v < 0.25:
            continue
        s = int(i * sixteenth * SR)
        hit = _noise_hit(0.05, decay=0.012, seed=seed + i)
        sos = signal.butter(2, [3000, 10000], btype="bandpass", fs=SR, output="sos")
        hit = signal.sosfilt(sos, hit)
        e = min(len(out), s + len(hit))
        # alternate pan slightly
        pan = 0.3 if i % 2 else -0.3
        gl, gr = np.cos((pan + 1) * np.pi / 4), np.sin((pan + 1) * np.pi / 4)
        st = np.column_stack([hit * gl, hit * gr])
        out[s:e] += st[:e - s] * v * level
    return np.clip(out, -1.0, 1.0)


def build_intro_outro(beat, bpm, intro_bars=2, outro_bars=2):
    """#13 Filtered intro (lowpass sweep in) + faded outro."""
    out = beat.copy()
    bar_s = int(60.0 / bpm * 4 * SR)
    # intro: lowpass opens up over intro_bars
    n_intro = min(len(out), intro_bars * bar_s)
    if n_intro > SR:
        t = np.linspace(0, 1, n_intro)
        # crude sweep: blend lowpassed version with full
        sos_lo = signal.butter(2, 400, btype="lowpass", fs=SR, output="sos")
        lo = signal.sosfilt(sos_lo, out[:n_intro], axis=0)
        blend = t[:, None] ** 1.5
        out[:n_intro] = lo * (1 - blend) + out[:n_intro] * blend
        # fade in first half-bar
        fi = min(int(0.5 * SR), n_intro)
        out[:fi] *= np.linspace(0, 1, fi)[:, None]
    # outro: fade + lowpass close over outro_bars
    n_out = min(len(out), outro_bars * bar_s)
    if n_out > SR:
        seg = out[-n_out:]
        t = np.linspace(1, 0, n_out)
        sos_lo = signal.butter(2, 400, btype="lowpass", fs=SR, output="sos")
        lo = signal.sosfilt(sos_lo, seg, axis=0)
        blend = t[:, None] ** 1.5
        out[-n_out:] = (lo * (1 - blend) + seg * blend) * (t ** 0.7)[:, None]
    return np.clip(out, -1.0, 1.0)


def crash_accents(beat, bpm, every_bars=8, seed=1, level=0.4):
    """#14 Crash cymbal wash on section downbeats."""
    out = beat.copy()
    r = _rng(seed)
    bar = 60.0 / bpm * 4
    bar_s = int(bar * SR)
    n_bars = len(out) // bar_s
    for b in range(0, n_bars, every_bars):
        s = b * bar_s
        n = int(1.2 * SR)
        crash = r.standard_normal(n) * np.exp(-np.arange(n) / (0.5 * SR))
        sos = signal.butter(2, 5000, btype="highpass", fs=SR, output="sos")
        crash = signal.sosfilt(sos, crash)
        e = min(len(out), s + n)
        out[s:e] += np.column_stack([crash, crash])[:e - s] * level * 0.5
    return np.clip(out, -1.0, 1.0)


def tag_filename(base, bpm, genre, key=""):
    """#15 Descriptive filename: genre, BPM, key, seed baked in."""
    parts = [base, genre, f"{int(round(bpm))}bpm"]
    if key:
        parts.append(key.replace("#", "s"))
    return "_".join(parts)
