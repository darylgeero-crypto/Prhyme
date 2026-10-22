"""Prhyme(tm) sound library expansion — 1500+ synthesized sounds.

Parametric variation engine: takes the base variant dicts from lightbeat.py
and generates hundreds of audibly-distinct variations by sweeping synthesis
parameters. All rendering stays on-demand (no pre-rendered files).

The 93 original named variants are NEVER modified — expansions use
systematic `{base}_x{nn}` names.

Only stdlib + numpy.
"""

import numpy as np
import zlib

SR = 44100


def _dhash(s):
    """Deterministic string hash (Python's hash() is randomized per run)."""
    return zlib.crc32(s.encode("utf-8"))


def _stereo(mono):
    """Mono -> stereo float32."""
    s = np.asarray(mono, dtype=np.float32)
    return np.stack([s, s], axis=1)


# ---------------------------------------------------------------------------
# New percussion synth functions
# ---------------------------------------------------------------------------

def _bp_fft(x, sr, lo, hi, peak_hz=None, peak_gain=0.0):
    """FFT bandpass with raised-cosine edges (numpy only) — gives
    noise voices the body bands real instruments have."""
    n = len(x)
    if n < 16:
        return x
    X = np.fft.rfft(x)
    f = np.fft.rfftfreq(n, 1.0 / sr)
    edge = 0.35
    def _ramp(freqs, a, b):
        return np.clip((freqs - a) / max(b - a, 1.0), 0.0, 1.0)
    rise = 0.5 - 0.5 * np.cos(np.pi * _ramp(f, lo * (1 - edge), lo))
    fall = 0.5 + 0.5 * np.cos(np.pi * _ramp(f, hi, hi * (1 + edge)))
    w = rise * fall
    if peak_hz:
        w = w * (1.0 + peak_gain * np.exp(-0.5 * ((f - peak_hz) / (peak_hz * 0.35)) ** 2))
    return np.fft.irfft(X * w, n).astype(np.float32)


def _cap_peak(x, cap=0.98):
    pk = float(np.max(np.abs(x))) if len(x) else 0.0
    return x * (cap / pk) if pk > cap else x


def _bongo(sr, rng, freq=220.0, dur=0.22):
    n = int(sr * dur); t = np.arange(n) / sr
    body = (np.sin(2*np.pi*freq*t) * np.exp(-t*28.0)
            + 0.4*np.sin(2*np.pi*freq*1.5*t) * np.exp(-t*40.0)
            + 0.15*np.sin(2*np.pi*freq*2.32*t) * np.exp(-t*52.0))
    # fingertip slap: band-limited smack, not raw noise
    click = (_bp_fft(rng.standard_normal(n).astype(np.float32), sr,
                     900, 2600)
             * np.exp(-t*300.0) * 0.5)
    return _cap_peak(_stereo((body + click) * 0.7))


def _timbale(sr, rng, freq=330.0, dur=0.28):
    n = int(sr * dur); t = np.arange(n) / sr
    body = (np.sin(2*np.pi*freq*t) * np.exp(-t*22.0)
            + 0.5*np.sin(2*np.pi*freq*1.33*t) * np.exp(-t*30.0))
    rim = (_bp_fft(rng.standard_normal(n).astype(np.float32), sr,
                   1800, 4200)
           * np.exp(-t*180.0) * 0.45)
    # steel shell ring
    shell = 0.18*np.sin(2*np.pi*freq*3.9*t) * np.exp(-t*36.0)
    return _cap_peak(_stereo((body + shell + rim) * 0.65))


def _agogo(sr, rng, freq=740.0, dur=0.30):
    n = int(sr * dur); t = np.arange(n) / sr
    sig = (np.sin(2*np.pi*freq*t)
           + 0.6*np.sin(2*np.pi*freq*1.19*t)
           + 0.3*np.sin(2*np.pi*freq*2.0*t))
    return _stereo(sig * np.exp(-t*14.0) * 0.4)


def _woodblock(sr, rng, freq=880.0, dur=0.12):
    n = int(sr * dur); t = np.arange(n) / sr
    sig = (np.sin(2*np.pi*freq*t) * np.exp(-t*90.0)
           + 0.3*np.sin(2*np.pi*freq*2.7*t) * np.exp(-t*120.0))
    return _stereo(sig * 0.55)


def _triangle(sr, rng, freq=1244.0, dur=0.8):
    n = int(sr * dur); t = np.arange(n) / sr
    sig = (np.sin(2*np.pi*freq*t)
           + 0.25*np.sin(2*np.pi*freq*2.76*t)
           + 0.1*np.sin(2*np.pi*freq*5.4*t))
    return _stereo(sig * np.exp(-t*4.0) * 0.35)


def _cabasa(sr, rng, dur=0.18):
    n = int(sr * dur); t = np.arange(n) / sr
    noise = _bp_fft(rng.standard_normal(n).astype(np.float32), sr,
                    4800, 9800)
    # rhythmic chatter: amplitude modulation
    am = 0.6 + 0.4*np.sin(2*np.pi*28*t)
    return _cap_peak(_stereo(noise * np.exp(-t*25.0) * am * 0.55))


def _vibraslap(sr, rng, dur=0.5):
    n = int(sr * dur); t = np.arange(n) / sr
    # rattling metallic buzz
    carrier = np.sin(2*np.pi*2100*t)
    rattle = np.abs(np.sin(2*np.pi*47*t))  # 47 Hz rattle
    sig = (carrier + 0.4*np.sin(2*np.pi*2870*t)) * rattle * np.exp(-t*8.0)
    return _cap_peak(_stereo(sig * 0.55))


def _guiro(sr, rng, dur=0.3):
    n = int(sr * dur); t = np.arange(n) / sr
    noise = _bp_fft(rng.standard_normal(n).astype(np.float32), sr,
                    2600, 7200, peak_hz=4200, peak_gain=0.5)
    scrape = 0.5 + 0.5*np.sign(np.sin(2*np.pi*18*t))  # scrape ridges
    return _cap_peak(_stereo(noise * np.exp(-t*12.0) * scrape * 0.55))


def _clave(sr, rng, freq=2500.0, dur=0.09):
    n = int(sr * dur); t = np.arange(n) / sr
    # A clave is a woody "tok": fundamental + a fast-dying upper mode
    # + the stick's band click. A bare sine reads as a synth beep.
    sig = (np.sin(2*np.pi*freq*t) * np.exp(-t*110.0)
           + 0.45*np.sin(2*np.pi*freq*1.68*t) * np.exp(-t*180.0)
           + 0.2*np.sin(2*np.pi*freq*2.91*t) * np.exp(-t*260.0))
    click = (_bp_fft(rng.standard_normal(n).astype(np.float32), sr,
                     1500, 3800)
             * np.exp(-t*500.0) * 0.5)
    return _cap_peak(_stereo((sig + click) * 0.65))


def _tamborim(sr, rng, freq=440.0, dur=0.15):
    n = int(sr * dur); t = np.arange(n) / sr
    body = np.sin(2*np.pi*freq*t) * np.exp(-t*45.0)
    snap = (_bp_fft(rng.standard_normal(n).astype(np.float32), sr,
                    1400, 3600)
            * np.exp(-t*250.0) * 0.5)
    return _cap_peak(_stereo((body + snap) * 0.6))


# ---------------------------------------------------------------------------
# New melodic synth functions
# ---------------------------------------------------------------------------

def _rhodes(sr, freq, dur=0.8):
    n = int(sr * dur); t = np.arange(n) / sr
    sig = (np.sin(2*np.pi*freq*t) * np.exp(-t*4.5)
           + 0.35*np.sin(2*np.pi*2*freq*t) * np.exp(-t*9.0)
           + 0.12*np.sin(2*np.pi*4*freq*t) * np.exp(-t*16.0)
           # the tine's metallic bark: high inharmonic partial, dies fast
           + 0.16*np.sin(2*np.pi*freq*13.2*t) * np.exp(-t*26.0)
           + 0.09*np.sin(2*np.pi*freq*3.98*t) * np.exp(-t*20.0))
    # gentle tremolo
    trem = 0.85 + 0.15*np.sin(2*np.pi*4.5*t)
    return _cap_peak(_stereo(sig * trem * 0.45))


def _organ(sr, freq, dur=0.7):
    n = int(sr * dur); t = np.arange(n) / sr
    sig = (np.sin(2*np.pi*freq*t)
           + 0.5*np.sin(2*np.pi*2*freq*t)
           + 0.3*np.sin(2*np.pi*3*freq*t)
           + 0.2*np.sin(2*np.pi*4*freq*t))
    # Hammond keys land in ~5 ms WITH a click — the old 58 ms swell
    # read as a synth pad. Click is a short high burst at note-on.
    click = 0.35*np.sin(2*np.pi*2300*t) * np.exp(-t*260.0)
    sig = sig + 0.08*np.sin(2*np.pi*6*freq*t) + 0.05*np.sin(2*np.pi*8*freq*t)
    env = np.minimum(1.0, t/0.005) * np.minimum(1.0, (dur-t)/0.06)
    return _cap_peak(_stereo((sig + click) * env * 0.24))


def _strings(sr, freq, dur=1.2):
    n = int(sr * dur); t = np.arange(n) / sr
    # Real bow envelope: ~8% attack to near-full, gentle swell,
    # late vibrato, bow hair noise underneath. The old version
    # ramped for a quarter of the note and PEAKED at the end
    # (measured attack 1088 ms — the note never "arrived").
    vib_depth = 0.004 * np.clip((t - dur*0.25) / (dur*0.2), 0, 1)
    vib = 1.0 + vib_depth * np.sin(2*np.pi*5.2*t)
    sig = np.zeros(n)
    for det in (0.9985, 1.0, 1.002):
        for mult, amp in ((1, 0.5), (2, 0.25), (3, 0.12), (4, 0.06), (5, 0.03)):
            sig += amp * np.sin(2*np.pi*freq*mult*det*vib*t)
    sig /= 3.0
    _rng = np.random.default_rng(int(freq) % 997 + 3)
    bow = (_bp_fft(_rng.standard_normal(n).astype(np.float32), sr,
                   2400, 6000) * 0.05)
    a = np.clip(t / (dur*0.08), 0, 1)
    swell = 0.85 + 0.15*np.clip(t / (dur*0.35), 0, 1)
    rel = np.clip((dur - t) / (dur*0.12), 0, 1)
    # gentle decay after the bow lands, so the note's weight sits at
    # the attack like a real stroke (not at a random beating peak)
    settle = 0.8 + 0.2*np.exp(-t*1.6)
    env = a * swell * rel * settle
    return _cap_peak(_stereo((sig + bow) * env * 0.42))


def _guitar_pluck(sr, freq, dur=0.6):
    n = int(sr * dur); t = np.arange(n) / sr
    # Karplus-Strong-ish: filtered noise burst through decaying comb
    # True Karplus-Strong: a short noise excitation recirculating
    # through a pitch-period feedback lowpass — bright pick attack
    # that warms as it decays, like a real string. (The old version
    # layered raw noise over a sine: measured as fizz, centroid
    # 5.8 kHz, flatness 0.71.)
    from scipy.signal import lfilter
    _rng = np.random.default_rng(int(freq) % 997 + 11)
    p = max(2, int(round(sr / max(freq, 20.0))))
    exc = _rng.standard_normal(n).astype(np.float64)
    exc = np.convolve(exc, np.ones(4) / 4.0, mode="same")  # pick softness
    exc[int(0.012 * sr):] = 0.0
    rho = float(np.exp(-2.2 / max(dur, 0.05) * (p / sr)))
    a_fb = np.zeros(p + 2)
    a_fb[0] = 1.0
    a_fb[p] = -0.5 * rho
    a_fb[p + 1] = -0.5 * rho
    ks = lfilter([1.0], a_fb, exc).astype(np.float32)
    body = np.sin(2*np.pi*freq*t) * np.exp(-t*7.0) * 0.25
    return _cap_peak(_stereo((ks * 0.9 + body) * 0.55))


def _guitar_dist(sr, freq, dur=0.7):
    n = int(sr * dur); t = np.arange(n) / sr
    # High-gain metal rhythm guitar: square-ish wave through hard-clip
    # waveshaper, fast attack bite, palm-muted sustain.
    sig = (0.55 * np.sign(np.sin(2*np.pi*freq*t))
           + 0.35 * np.sin(2*np.pi*freq*t)
           + 0.25 * np.sign(np.sin(2*np.pi*2*freq*t))
           + 0.12 * np.sign(np.sin(2*np.pi*3*freq*t)))
    sig = np.tanh(sig * 3.2)  # hard-clip distortion
    sig = _bp_fft(sig.astype(np.float32), sr, 65, 7800)  # tame the fizz
    env = np.exp(-t*4.0) * (0.35 + 0.65*np.exp(-t*28.0))
    return _cap_peak(_stereo(sig * env * 0.55))


def _musicbox(sr, freq, dur=1.0):
    n = int(sr * dur); t = np.arange(n) / sr
    # A music box tine rings HIGH: strong inharmonic partials with
    # long ring times. The old balance buried them under the
    # fundamental (measured centroid 382 Hz — a dull thud).
    # In a real music box the fundamental is the QUIETEST part —
    # the tine's high modes carry the note. Rebalanced accordingly.
    sig = (0.5*np.sin(2*np.pi*freq*t) * np.exp(-t*4.2)
           + 0.85*np.sin(2*np.pi*freq*3.01*t) * np.exp(-t*11.0)
           + 0.35*np.sin(2*np.pi*freq*5.4*t) * np.exp(-t*13.0)
           + 0.4*np.sin(2*np.pi*freq*9.2*t) * np.exp(-t*18.0))
    return _cap_peak(_stereo(sig * 0.4))


def _steeldrum(sr, freq, dur=0.9):
    n = int(sr * dur); t = np.arange(n) / sr
    # Steelpan modes are tuned 1 : 2 : ~3 (octave + fifth above the
    # octave), with a bright mallet tick — not the old 1.5x wash.
    sig = (np.sin(2*np.pi*freq*t) * np.exp(-t*6.0)
           + 0.55*np.sin(2*np.pi*freq*2.0*t) * np.exp(-t*9.0)
           + 0.28*np.sin(2*np.pi*freq*2.99*t) * np.exp(-t*14.0)
           + 0.12*np.sin(2*np.pi*freq*4.2*t) * np.exp(-t*22.0)
           + 0.3*np.sin(2*np.pi*freq*5.9*t) * np.exp(-t*60.0))
    return _cap_peak(_stereo(sig * 0.42))


def _sitar(sr, freq, dur=0.8):
    n = int(sr * dur); t = np.arange(n) / sr
    # buzzy: saw-ish via additive + sympathetic shimmer
    sig = np.zeros(n)
    for k in range(1, 15):
        sig += (1.0/k) * (0.6 if k > 8 else 1.0) * np.sin(2*np.pi*freq*k*t + 0.1*k)
    sig /= 4.0
    # jawari buzz: the string rattles against the curved bridge,
    # pulsing brightness at the note's own rate
    buzz = 0.85 + 0.3*np.abs(np.sin(np.pi*freq*0.5*t)) * np.exp(-t*2.0)
    return _cap_peak(_stereo(sig * np.exp(-t*5.0) * buzz * 0.85))


def _epiano(sr, freq, dur=0.7):
    n = int(sr * dur); t = np.arange(n) / sr
    sig = (np.sin(2*np.pi*freq*t) * np.exp(-t*5.5)
           + 0.3*np.sin(2*np.pi*freq*2.01*t) * np.exp(-t*10.0)
           + 0.1*np.sin(2*np.pi*freq*3.98*t) * np.exp(-t*18.0)
           + 0.14*np.sin(2*np.pi*freq*11.9*t) * np.exp(-t*30.0))
    return _cap_peak(_stereo(sig * 0.42))


def _wurlie(sr, freq, dur=0.6):
    n = int(sr * dur); t = np.arange(n) / sr
    sig = (np.sin(2*np.pi*freq*t) + 0.25*np.tanh(2.0*np.sin(2*np.pi*freq*t))
           + 0.16*np.sin(2*np.pi*freq*3.0*t) * np.exp(-t*8.0)
           + 0.07*np.sin(2*np.pi*freq*5.1*t) * np.exp(-t*14.0))
    return _cap_peak(_stereo(sig * np.exp(-t*6.5) * 0.4))


def _lead_saw(sr, freq, dur=0.5):
    n = int(sr * dur); t = np.arange(n) / sr
    sig = np.zeros(n)
    for det in (0.998, 1.002):
        for k in range(1, 12):
            sig += (1.0/k) * np.sin(2*np.pi*freq*k*det*t)
    sig /= 5.0
    env = np.minimum(1.0, t/0.015) * np.exp(-t*4.0)
    rel = np.minimum(1.0, np.maximum(0.0, (dur - t) / 0.04))
    return _cap_peak(_stereo(np.tanh(1.5*sig) * env * rel * 0.55), 0.85)


def _lead_square(sr, freq, dur=0.5):
    n = int(sr * dur); t = np.arange(n) / sr
    # odd-partial stack (a true square's recipe) instead of sign()
    sig = np.zeros(n)
    for k in range(1, 12, 2):
        sig += (1.0/k) * np.sin(2*np.pi*freq*k*t)
    sig = sig / 1.6 + 0.25*np.sin(2*np.pi*freq*t)
    env = np.minimum(1.0, t/0.015) * np.exp(-t*4.5)
    rel = np.minimum(1.0, np.maximum(0.0, (dur - t) / 0.04))
    return _cap_peak(_stereo(sig * env * rel * 0.5), 0.85)


def _reese_bass(sr, freq, dur=0.6):
    n = int(sr * dur); t = np.arange(n) / sr
    sig = np.zeros(n)
    for det in (0.99, 1.01):
        for k in range(1, 6):
            sig += (1.0/k) * np.sin(2*np.pi*freq*det*k*t)
    sig /= 6.0
    return _stereo(np.tanh(2.0*sig) * np.exp(-t*3.5) * 0.55)


def _acid_bass(sr, freq, dur=0.4):
    n = int(sr * dur); t = np.arange(n) / sr
    saw = np.zeros(n)
    for k in range(1, 10):
        saw += (1.0/k) * np.sin(2*np.pi*freq*k*t)
    saw /= 3.0
    # resonant sweep: simple resonant-ish emphasis via modulated mix
    cutoff_mod = 0.5 + 0.5*np.exp(-t*8.0)
    sig = np.tanh(3.0*saw) * cutoff_mod
    return _stereo(sig * np.exp(-t*5.0) * 0.5)


def _pluck_bass(sr, freq, dur=0.45):
    n = int(sr * dur); t = np.arange(n) / sr
    # Finger attack: upper partials that speak first, then the
    # fundamental takes over (the old one was a naked sub sine,
    # centroid 68 Hz at A1 — no string definition at all).
    sig = (np.sin(2*np.pi*freq*t) * np.exp(-t*9.0)
           + 0.5*np.sin(2*np.pi*2*freq*t) * np.exp(-t*16.0)
           + 0.2*np.sin(2*np.pi*3*freq*t) * np.exp(-t*25.0)
           + 0.26*np.sin(2*np.pi*4.3*freq*t) * np.exp(-t*38.0)
           + 0.17*np.sin(2*np.pi*6.7*freq*t) * np.exp(-t*52.0))
    return _cap_peak(_stereo(sig * 0.62))


def _sub_drop(sr, freq, dur=0.8):
    n = int(sr * dur); t = np.arange(n) / sr
    f = freq * 2.0 * np.exp(-t*6.0) + freq * 0.5
    phase = 2*np.pi*np.cumsum(f)/sr
    return _stereo(np.sin(phase) * np.exp(-t*4.0) * 0.7)


def _fm_bass(sr, freq, dur=0.5):
    n = int(sr * dur); t = np.arange(n) / sr
    mod = np.sin(2*np.pi*freq*2.0*t) * 3.0
    sig = np.sin(2*np.pi*freq*t + mod)
    return _stereo(np.tanh(1.8*sig) * np.exp(-t*6.0) * 0.5)


# ---------------------------------------------------------------------------
# New FX synth functions
# ---------------------------------------------------------------------------

def _reverse_cymbal(sr, rng, dur=1.5):
    n = int(sr * dur); t = np.arange(n) / sr
    noise = rng.standard_normal(n)
    hp = np.diff(noise, prepend=noise[0])
    env = (t/dur)**2.5  # swell into the hit
    hit = np.exp(-np.maximum(0, t-dur+0.05)*40.0) * (t > dur-0.1)
    return _cap_peak(_stereo((hp*env*0.5 + hp*hit*0.8) * 0.55))


def _sweep_up(sr, dur=1.0):
    n = int(sr * dur); t = np.arange(n) / sr
    f = 200.0 * (8000.0/200.0)**(t/dur)
    phase = 2*np.pi*np.cumsum(f)/sr
    return _stereo(np.sin(phase) * (t/dur) * 0.3)


def _sweep_down(sr, dur=1.0):
    n = int(sr * dur); t = np.arange(n) / sr
    f = 8000.0 * (200.0/8000.0)**(t/dur)
    phase = 2*np.pi*np.cumsum(f)/sr
    return _stereo(np.sin(phase) * (1-t/dur) * 0.3)


def _alarm(sr, dur=1.0):
    n = int(sr * dur); t = np.arange(n) / sr
    f = 660.0 + 220.0*np.sign(np.sin(2*np.pi*3*t))
    return _stereo(np.sin(2*np.pi*f*t) * 0.3)


def _laser(sr, dur=0.5):
    n = int(sr * dur); t = np.arange(n) / sr
    f = 3000.0 * np.exp(-t*8.0) + 200.0
    phase = 2*np.pi*np.cumsum(f)/sr
    return _stereo(np.sin(phase) * np.exp(-t*5.0) * 0.35)


def _chopped_vocal(sr, rng, dur=0.4):
    # formant-ish "yeah" chop: filtered saw bursts
    n = int(sr * dur); t = np.arange(n) / sr
    f0 = 140.0
    sig = np.zeros(n)
    for k in range(1, 8):
        sig += (1.0/k**1.5) * np.sin(2*np.pi*f0*k*t)
    # vowel envelope: two-syllable chop
    env = (np.exp(-((t-0.08)/0.06)**2) + 0.8*np.exp(-((t-0.25)/0.07)**2))
    return _stereo(np.tanh(2.0*sig) * env * 0.4)


def _tape_stop(sr, dur=0.8):
    # pitch dives to zero like stopping tape
    n = int(sr * dur); t = np.arange(n) / sr
    f = 440.0 * np.maximum(0.0, 1 - (t/dur)**1.5)
    phase = 2*np.pi*np.cumsum(f)/sr
    sig = np.sin(phase) + 0.3*np.sin(2*phase)
    return _stereo(sig * (1-t/dur) * 0.4)


def _shimmer(sr, rng, dur=2.0):
    n = int(sr * dur); t = np.arange(n) / sr
    noise = rng.standard_normal(n)
    hp = np.diff(noise, prepend=noise[0])
    env = np.sin(np.pi * t/dur)**2
    # sparkle: high sine partials
    sparkle = (np.sin(2*np.pi*5200*t) + 0.5*np.sin(2*np.pi*7800*t)) * 0.1
    return _stereo((hp*0.15 + sparkle) * env * 0.5)


# ---------------------------------------------------------------------------
# Drum loop generator — renders full grooves from kit drum functions
# ---------------------------------------------------------------------------

# 16-step patterns: K=kick S=snare H=closed hat O=open hat C=clap P=perc
_LOOP_PATTERNS = {
    "boom_bap": dict(
        kick=[1,0,0,0, 0,0,1,0, 0,0,1,0, 0,0,0,0],
        snare=[0,0,0,0, 1,0,0,0, 0,0,0,0, 1,0,0,0],
        chat=[1,0,1,0, 1,0,1,0, 1,0,1,0, 1,0,1,1],
        bpm=92),
    "trap": dict(
        kick=[1,0,0,0, 0,0,0,0, 0,0,1,0, 0,0,0,0],
        snare=[0,0,0,0, 0,0,0,0, 1,0,0,0, 0,0,0,0],
        chat=[1,1,1,1, 1,1,1,1, 1,1,1,1, 1,1,1,1],
        ohat=[0,0,0,0, 0,0,1,0, 0,0,0,0, 0,0,0,0],
        bpm=140),
    "drill": dict(
        kick=[1,0,0,1, 0,0,1,0, 0,0,1,0, 0,0,0,0],
        snare=[0,0,0,0, 0,0,0,0, 1,0,0,0, 0,0,0,1],
        chat=[1,0,1,1, 0,1,0,1, 1,0,1,0, 1,1,0,1],
        bpm=142),
    "rnb": dict(
        kick=[1,0,0,0, 0,0,1,0, 0,0,0,0, 1,0,0,0],
        snare=[0,0,0,0, 1,0,0,0, 0,0,0,0, 1,0,0,1],
        chat=[1,0,1,0, 1,0,1,0, 1,0,1,0, 1,0,1,0],
        clap=[0,0,0,0, 1,0,0,0, 0,0,0,0, 1,0,0,0],
        bpm=96),
    "lofi": dict(
        kick=[1,0,0,0, 0,0,0,1, 0,0,1,0, 0,0,0,0],
        snare=[0,0,0,0, 1,0,0,0, 0,0,0,0, 1,0,0,0],
        chat=[1,0,1,1, 0,1,0,1, 1,0,1,0, 1,0,1,0],
        bpm=84),
    "jersey": dict(
        kick=[1,0,0,0, 1,0,0,0, 1,0,0,0, 1,0,0,1],
        snare=[0,0,1,0, 0,0,1,0, 0,0,1,0, 0,0,1,0],
        chat=[1,1,0,1, 1,1,0,1, 1,1,0,1, 1,1,1,1],
        bpm=130),
    "rage": dict(
        kick=[1,0,0,0, 1,0,0,1, 0,0,1,0, 0,0,0,0],
        snare=[0,0,0,0, 1,0,0,0, 0,0,0,0, 1,0,1,0],
        chat=[1,0,1,0, 1,0,1,0, 1,0,1,0, 1,0,1,0],
        ohat=[0,0,0,0, 0,0,0,0, 0,0,1,0, 0,0,0,0],
        bpm=150),
    "afrobeats": dict(
        kick=[1,0,0,1, 0,0,1,0, 0,0,1,0, 0,1,0,0],
        snare=[0,0,0,0, 1,0,0,0, 0,0,1,0, 0,0,0,0],
        chat=[1,0,1,0, 1,0,1,0, 1,0,1,0, 1,0,1,0],
        perc=[0,0,1,0, 0,1,0,0, 1,0,0,1, 0,0,1,0],
        bpm=102),
    "dnb": dict(
        kick=[1,0,0,0, 0,0,0,0, 0,0,1,0, 0,0,0,0],
        snare=[0,0,0,0, 1,0,0,0, 0,0,0,0, 1,0,0,0],
        chat=[1,0,1,0, 1,0,1,0, 1,0,1,0, 1,0,1,0],
        bpm=174),
    "house": dict(
        kick=[1,0,0,0, 1,0,0,0, 1,0,0,0, 1,0,0,0],
        snare=[0,0,0,0, 1,0,0,0, 0,0,0,0, 1,0,0,0],
        chat=[0,0,1,0, 0,0,1,0, 0,0,1,0, 0,0,1,0],
        ohat=[0,0,0,0, 0,0,1,0, 0,0,0,0, 0,0,1,0],
        bpm=124),
}

_LOOP_KIT_MAP = {
    "boom_bap": "classic", "trap": "trap", "drill": "drill", "rnb": "sub",
    "lofi": "lofi", "jersey": "jersey", "rage": "hardstyle",
    "afrobeats": "soft808", "dnb": "punchy", "house": "punchy",
}


def render_drum_loop(sr, rng, loop_name, kit_sounds, bars=2):
    """Render a drum loop using pre-rendered kit one-shots.

    kit_sounds: dict with keys kick/snare/chat/ohat/clap/perc -> stereo arrays.
    """
    pat = _LOOP_PATTERNS[loop_name]
    bpm = pat["bpm"]
    step_dur = 60.0 / bpm / 4.0  # 16th notes
    total_steps = 16 * bars
    total_n = int(sr * step_dur * total_steps) + sr  # tail room
    out = np.zeros((total_n, 2), dtype=np.float32)

    def place(sound, step):
        if sound is None:
            return
        start = int(step * step_dur * sr)
        if start < 0:
            # humanization pushed before zero: trim the sound head
            trim = -start
            if trim >= len(sound):
                return
            sound = sound[trim:]
            start = 0
        end = min(total_n, start + len(sound))
        if end <= start:
            return
        out[start:end] += sound[:end - start] * 0.9

    for bar in range(bars):
        base = bar * 16
        for inst in ("kick", "snare", "chat", "ohat", "clap", "perc"):
            seq = pat.get(inst)
            snd = kit_sounds.get(inst)
            if not seq or snd is None:
                continue
            for i, hit in enumerate(seq):
                if hit:
                    # slight humanization on non-kick/snare
                    off = 0 if inst in ("kick", "snare") else rng.integers(-40, 41)
                    place(snd, base + i + off / sr / step_dur)
    # normalize
    peak = np.abs(out).max()
    if peak > 0:
        out *= 0.89 / peak
    return out


# ---------------------------------------------------------------------------
# Parametric expansion engine
# ---------------------------------------------------------------------------

def _jitter_params(base, spec, rng):
    """Perturb numeric params by relative amounts from spec {key: fraction}."""
    out = dict(base)
    for k, amt in spec.items():
        v = out.get(k)
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            out[k] = v * (1.0 + rng.uniform(-amt, amt))
    return out


def _expand_flat(base_dict, n_per_base, spec, prefix, seed_base=1000):
    """Expand {name: param_dict} -> {name: ..., name_xNN: ...}."""
    out = dict(base_dict)  # originals untouched
    for bi, (bname, bparams) in enumerate(sorted(base_dict.items())):
        rng = np.random.default_rng(seed_base + bi * 7919)
        for i in range(n_per_base):
            vrng = np.random.default_rng(seed_base + bi * 7919 + i * 131 + 7)
            out[f"{bname}_x{i+1:02d}"] = _jitter_params(bparams, spec, vrng)
    return out


def _expand_tuples(base_dict, n_per_base, spec, seed_base=2000):
    """Expand {name: (func, kwargs)} -> variations with jittered kwargs."""
    out = dict(base_dict)
    for bi, (bname, (fname, kw)) in enumerate(sorted(base_dict.items())):
        for i in range(n_per_base):
            vrng = np.random.default_rng(seed_base + bi * 7919 + i * 131 + 7)
            new_kw = _jitter_params(dict(kw), spec, vrng)
            out[f"{bname}_x{i+1:02d}"] = (fname, new_kw)
    return out


# Jitter specs per category — meaningful ranges for audible differences
KICK_SPEC = {"f0": 0.18, "sweep": 0.28, "sweep_decay": 0.25,
             "body_decay": 0.30, "click_decay": 0.30, "click_level": 0.35,
             "dur": 0.12, "level": 0.05}
SNARE_SPEC = {"noise_decay": 0.25, "noise_level": 0.20, "body_freq": 0.22,
              "body_decay": 0.25, "body_level": 0.20, "dur": 0.15}
HAT_SPEC = {"dur": 0.25, "decay": 0.30, "level": 0.12}
CLAP_SPEC = {"burst_decay": 0.30, "tail_decay": 0.30, "level": 0.10}
# clap bursts are tuples — jitter handled separately below
BASS808_SPEC = {"dur": 0.20, "drive": 0.30, "glide_time": 0.35,
                "harm2": 0.40, "harm3": 0.45, "decay": 0.30,
                "click": 0.50, "start_mult": 0.22}
PERC_SPEC = {"freq": 0.25, "dur": 0.20}
FX_SPEC = {"dur": 0.30}

# New percussion instruments: (func_name, base_kwargs)
_NEW_PERC = {
    "bongo_hi": ("bongo", dict(freq=262.0, dur=0.20)),
    "bongo_lo": ("bongo", dict(freq=196.0, dur=0.24)),
    "timbale_hi": ("timbale", dict(freq=392.0, dur=0.26)),
    "timbale_lo": ("timbale", dict(freq=294.0, dur=0.30)),
    "agogo_hi": ("agogo", dict(freq=880.0, dur=0.28)),
    "agogo_lo": ("agogo", dict(freq=659.0, dur=0.32)),
    "woodblock_hi": ("woodblock", dict(freq=1046.0, dur=0.10)),
    "woodblock_lo": ("woodblock", dict(freq=784.0, dur=0.14)),
    "triangle": ("triangle", dict(freq=1568.0, dur=0.7)),
    "cabasa": ("cabasa", dict(dur=0.18)),
    "vibraslap": ("vibraslap", dict(dur=0.5)),
    "guiro": ("guiro", dict(dur=0.3)),
    "clave": ("clave", dict(freq=2500.0, dur=0.09)),
    "tamborim": ("tamborim", dict(freq=494.0, dur=0.14)),
}

# New melodic instruments: (func_name, base_dur)
_NEW_MELODIC = {
    "rhodes": ("rhodes", 0.8),
    "organ": ("organ", 0.7),
    "strings": ("strings", 1.2),
    "guitar": ("guitar_pluck", 0.6),
    "guitar_dist": ("guitar_dist", 0.7),
    "musicbox": ("musicbox", 1.0),
    "steeldrum": ("steeldrum", 0.9),
    "sitar": ("sitar", 0.8),
    "epiano": ("epiano", 0.7),
    "wurlie": ("wurlie", 0.6),
    "lead_saw": ("lead_saw", 0.5),
    "lead_square": ("lead_square", 0.5),
}

# New FX: (func_name, base_kwargs_or_dur)
_NEW_FX_FUNCS = {
    "reverse_cymbal": "reverse_cymbal",
    "sweep_up": "sweep_up",
    "sweep_down": "sweep_down",
    "alarm": "alarm",
    "laser": "laser",
    "chopped_vocal": "chopped_vocal",
    "tape_stop": "tape_stop",
    "shimmer": "shimmer",
}

# New bass instruments (non-808): (func_name, base_dur)
_NEW_BASS = {
    "reese": ("reese_bass", 0.6),
    "acid": ("acid_bass", 0.4),
    "pluck_bass": ("pluck_bass", 0.45),
    "sub_drop": ("sub_drop", 0.8),
    "fm_bass": ("fm_bass", 0.5),
}

_NEW_PERC_FUNCS = {
    "bongo": _bongo, "timbale": _timbale, "agogo": _agogo,
    "woodblock": _woodblock, "triangle": _triangle, "cabasa": _cabasa,
    "vibraslap": _vibraslap, "guiro": _guiro, "clave": _clave,
    "tamborim": _tamborim,
}

_NEW_MELODIC_FUNCS = {
    "rhodes": _rhodes, "organ": _organ, "strings": _strings,
    "guitar_pluck": _guitar_pluck, "guitar_dist": _guitar_dist,
    "musicbox": _musicbox,
    "steeldrum": _steeldrum, "sitar": _sitar, "epiano": _epiano,
    "wurlie": _wurlie, "lead_saw": _lead_saw, "lead_square": _lead_square,
}

_NEW_BASS_FUNCS = {
    "reese_bass": _reese_bass, "acid_bass": _acid_bass,
    "pluck_bass": _pluck_bass, "sub_drop": _sub_drop, "fm_bass": _fm_bass,
}

_NEW_FX_RENDER = {
    "reverse_cymbal": _reverse_cymbal, "sweep_up": _sweep_up,
    "sweep_down": _sweep_down, "alarm": _alarm, "laser": _laser,
    "chopped_vocal": _chopped_vocal, "tape_stop": _tape_stop,
    "shimmer": _shimmer,
}


def build_expanded_library(lb):
    """Expand lightbeat's variant dicts in place. lb = lightbeat module.

    Returns dict of counts per category.
    """
    # --- drums: flat param dicts ---
    lb._KICK_VARIANTS.update(
        {k: v for k, v in _expand_flat(lb._KICK_VARIANTS, 12, KICK_SPEC, "kick").items()
         if k not in lb._KICK_VARIANTS})
    lb._SNARE_VARIANTS.update(
        {k: v for k, v in _expand_flat(lb._SNARE_VARIANTS, 12, SNARE_SPEC, "snare").items()
         if k not in lb._SNARE_VARIANTS})
    lb._HAT_VARIANTS.update(
        {k: v for k, v in _expand_flat(lb._HAT_VARIANTS, 18, HAT_SPEC, "chat").items()
         if k not in lb._HAT_VARIANTS})
    lb._OHAT_VARIANTS.update(
        {k: v for k, v in _expand_flat(lb._OHAT_VARIANTS, 24, HAT_SPEC, "ohat").items()
         if k not in lb._OHAT_VARIANTS})

    # --- claps: jitter numeric params, keep burst tuples ---
    lb._CLAP_VARIANTS.update(
        {k: v for k, v in _expand_flat(lb._CLAP_VARIANTS, 12, CLAP_SPEC, "clap").items()
         if k not in lb._CLAP_VARIANTS})

    # --- percussion: add new instruments, then expand all ---
    lb._PERC_VARIANTS.update(_NEW_PERC)
    lb._PERC_FUNCS.update(_NEW_PERC_FUNCS)
    lb._PERC_VARIANTS.update(
        {k: v for k, v in _expand_tuples(lb._PERC_VARIANTS, 7, PERC_SPEC).items()
         if k not in lb._PERC_VARIANTS})

    # --- 808s ---
    lb._808_VARIANTS.update(
        {k: v for k, v in _expand_flat(lb._808_VARIANTS, 18, BASS808_SPEC, "808").items()
         if k not in lb._808_VARIANTS})

    # --- melodic: add new instruments, expand durations ---
    lb._MELODIC_VARIANTS.update(_NEW_MELODIC)
    lb._MELODIC_FUNCS.update(_NEW_MELODIC_FUNCS)
    expanded_mel = {}
    for bname, (fname, dur) in sorted(lb._MELODIC_VARIANTS.items()):
        if "_x" in bname:
            continue
        for i in range(9):
            vrng = np.random.default_rng(3000 + _dhash(bname) % 100000 + i * 131)
            new_dur = dur * (1.0 + vrng.uniform(-0.25, 0.25))
            expanded_mel[f"{bname}_x{i+1:02d}"] = (fname, round(new_dur, 3))
    lb._MELODIC_VARIANTS.update(expanded_mel)

    # --- FX: add new types, expand durations ---
    for fx_name, func_name in _NEW_FX_FUNCS.items():
        lb._FX_VARIANTS[fx_name] = dict(kind=func_name, dur=1.0)
    lb._FX_FUNCS.update(_NEW_FX_RENDER)
    expanded_fx = {}
    for bname, p in sorted(lb._FX_VARIANTS.items()):
        if "_x" in bname:
            continue
        for i in range(8):
            vrng = np.random.default_rng(4000 + _dhash(bname) % 100000 + i * 131)
            new_dur = p["dur"] * (1.0 + vrng.uniform(-0.30, 0.30))
            expanded_fx[f"{bname}_x{i+1:02d}"] = dict(kind=p["kind"],
                                                     dur=round(new_dur, 3))
    lb._FX_VARIANTS.update(expanded_fx)

    # --- bass: brand-new category ---
    lb._BASS_VARIANTS = dict(_NEW_BASS)
    lb._BASS_FUNCS = dict(_NEW_BASS_FUNCS)
    expanded_bass = {}
    for bname, (fname, dur) in sorted(_NEW_BASS.items()):
        for i in range(19):
            vrng = np.random.default_rng(5000 + _dhash(bname) % 100000 + i * 131)
            new_dur = dur * (1.0 + vrng.uniform(-0.25, 0.25))
            expanded_bass[f"{bname}_x{i+1:02d}"] = (fname, round(new_dur, 3))
    lb._BASS_VARIANTS.update(expanded_bass)

    # --- loops: brand-new category (rendered on demand, not pre-expanded) ---
    lb._LOOP_VARIANTS = {}
    for loop_name in sorted(_LOOP_PATTERNS):
        lb._LOOP_VARIANTS[loop_name] = dict(pattern=loop_name, bars=2)
        # BPM-shifted + bar-count variations
        for i, bpm_shift in enumerate((-8, -4, 4, 8)):
            lb._LOOP_VARIANTS[f"{loop_name}_x{i+1:02d}"] = dict(
                pattern=loop_name, bars=2, bpm_shift=bpm_shift)
        for i, bars in enumerate((1, 4)):
            lb._LOOP_VARIANTS[f"{loop_name}_b{bars}"] = dict(
                pattern=loop_name, bars=bars)

    counts = {
        "kick": len(lb._KICK_VARIANTS),
        "snare": len(lb._SNARE_VARIANTS),
        "chat": len(lb._HAT_VARIANTS),
        "ohat": len(lb._OHAT_VARIANTS),
        "clap": len(lb._CLAP_VARIANTS),
        "perc": len(lb._PERC_VARIANTS),
        "808": len(lb._808_VARIANTS),
        "melodic": len(lb._MELODIC_VARIANTS),
        "fx": len(lb._FX_VARIANTS),
        "bass": len(lb._BASS_VARIANTS),
        "loops": len(lb._LOOP_VARIANTS),
    }
    return counts
