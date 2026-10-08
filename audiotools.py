"""DJRILL audio tools — trimmer, normalizer, karaoke, ringtone, key detect.

Standalone utilities for the Tools page. All operate on float64 stereo @44.1k.
"""
import numpy as np
from scipy import signal

import djrill_master as M
import djrill_convert as C

SR = 44100


def trim_audio(path, start_s=0.0, end_s=None):
    """114. Trim heads/tails by time."""
    _, audio = M.load_audio(path)
    s0 = max(0, int(start_s * SR))
    s1 = int(end_s * SR) if end_s else len(audio)
    s1 = min(len(audio), max(s0 + 1, s1))
    return audio[s0:s1]


def remove_silence(path, thresh_db=-45, min_sil_s=0.5):
    """114b. Strip leading/trailing silence."""
    _, audio = M.load_audio(path)
    mono = np.abs(audio.mean(axis=1))
    thresh = 10 ** (thresh_db / 20.0)
    mask = mono > thresh
    if not np.any(mask):
        return audio
    # keep a little breathing room
    pad = int(0.1 * SR)
    s0 = max(0, int(np.argmax(mask)) - pad)
    s1 = min(len(audio), len(audio) - int(np.argmax(mask[::-1])) + pad)
    return audio[s0:s1]


def normalize_loudness(path, target_lufs=-14.0):
    """115. Loudness-normalize any file."""
    _, audio = M.load_audio(path)
    lufs = M.integrated_lufs(audio, SR)
    if np.isfinite(lufs):
        audio = audio * 10 ** ((target_lufs - lufs) / 20.0)
    tp = M.true_peak(audio, SR)
    ceiling = 10 ** (-1.0 / 20.0)
    if tp > ceiling and tp > 0:
        audio = audio * (ceiling / tp)
    return np.clip(audio, -1.0, 1.0)


def karaoke_cut(path, strength=0.8):
    """111. Center-cut 'vocal remover': attenuate panned-center content.

    Simple mid/side trick — reduces lead vocals, keeps stereo instruments.
    Not a stem separator; results vary by mix."""
    _, audio = M.load_audio(path)
    if audio.shape[1] < 2:
        return audio
    mid = (audio[:, 0] + audio[:, 1]) / 2
    side = (audio[:, 0] - audio[:, 1]) / 2
    mid_cut = mid * (1.0 - strength)
    l = mid_cut + side
    r = mid_cut - side
    out = np.column_stack([l, r])
    peak = np.max(np.abs(out))
    if peak > 0:
        out = out / peak * 0.9
    return out


def make_ringtone(path, start_s=0.0, dur_s=30.0):
    """110. 30-second ringtone cut with fades."""
    _, audio = M.load_audio(path)
    s0 = max(0, int(start_s * SR))
    n = int(dur_s * SR)
    seg = audio[s0:s0 + n]
    if len(seg) < SR:
        raise ValueError("Audio too short for a ringtone")
    fi = min(len(seg), int(0.5 * SR))
    fo = min(len(seg), int(2.0 * SR))
    seg[:fi] *= np.linspace(0, 1, fi)[:, None]
    seg[-fo:] *= np.linspace(1, 0, fo)[:, None]
    peak = np.max(np.abs(seg))
    if peak > 0:
        seg = seg / peak * 0.9
    return seg


def detect_key(path):
    """113. Rough key detection via chroma energy."""
    _, audio = M.load_audio(path)
    mono = audio.mean(axis=1)
    # use middle 60s max for speed
    if len(mono) > SR * 60:
        s = (len(mono) - SR * 60) // 2
        mono = mono[s:s + SR * 60]
    n_fft = 8192
    hop = 4096
    chroma = np.zeros(12)
    for s in range(0, len(mono) - n_fft, hop):
        fr = mono[s:s + n_fft] * np.hanning(n_fft)
        mag = np.abs(np.fft.rfft(fr))
        freqs = np.fft.rfftfreq(n_fft, 1 / SR)
        for i, f in enumerate(freqs):
            if f < 55 or f > 2000 or mag[i] < 1e-9:
                continue
            midi = 69 + 12 * np.log2(f / 440.0)
            pc = int(round(midi)) % 12
            chroma[pc] += mag[i]
    if chroma.sum() <= 0:
        return {"key": "?", "confidence": 0.0}
    # Krumhansl major/minor profiles, correlate all rotations
    major = np.array([6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88])
    minor = np.array([6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17])
    names = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
    best, best_name, best_mode = -2, "?", ""
    for mode, prof in (("major", major), ("minor", minor)):
        for r in range(12):
            corr = float(np.corrcoef(np.roll(chroma, -r), prof)[0, 1])
            if corr > best:
                best, best_name, best_mode = corr, names[r], mode
    return {"key": f"{best_name} {best_mode}",
            "confidence": round(max(0.0, min(1.0, (best + 1) / 2)), 2)}


def write_wav(path, audio):
    """Write float64 stereo -> 16-bit WAV."""
    from scipy.io.wavfile import write as wav_write
    pcm = (np.clip(audio, -1, 1) * 32767).astype(np.int16)
    wav_write(path, SR, pcm)
    return path


# 109. minimal MIDI writer (SMF type 0) for drum patterns
def write_midi_drums(path, steps16, bpm=90.0, root=36):
    """Write a 16-step drum pattern as a MIDI file.
    steps16: list of (step_index, midi_note, velocity)."""
    tpq = 480
    sec_per_tick = 60.0 / bpm / tpq
    step_ticks = tpq // 4
    events = []
    for step, note, vel in steps16:
        tick = int(step * step_ticks)
        events.append((tick, 0x90, note, int(vel)))
        events.append((tick + step_ticks // 2, 0x80, note, 0))
    events.sort()
    track = bytearray()
    track += b"\x00\xff\x51\x03" + int(60000000 / bpm).to_bytes(3, "big")
    last = 0
    for tick, status, d1, d2 in events:
        delta = tick - last
        last = tick
        # varlen
        var = bytearray()
        var.append(delta & 0x7F)
        delta >>= 7
        while delta:
            var.insert(0, (delta & 0x7F) | 0x80)
            delta >>= 7
        track += bytes(var) + bytes([status, d1, d2])
    track += b"\x00\xff\x2f\x00"
    with open(path, "wb") as f:
        f.write(b"MThd\x00\x00\x00\x06\x00\x00\x00\x01" + tpq.to_bytes(2, "big"))
        f.write(b"MTrk" + len(track).to_bytes(4, "big") + bytes(track))
    return path
