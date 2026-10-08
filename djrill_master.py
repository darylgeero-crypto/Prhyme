"""DJRILL mastering pipeline — EDIT a human recording, never generate one.

Takes the artist's recorded performance (any WAV/MP3 vocal or song stem) and:
  1. Renders a DJRILL beat locked to its tempo (strict grid, no drift)
  2. Applies gentle mix polish to the recording (EQ, light compression)
  3. Mixes voice-forward over the beat
  4. Masters to -14 LUFS integrated / -1.0 dBTP with dither

The vocal is NEVER synthesized, replaced, re-voiced, or re-timed beyond
placement. What goes in is the human's performance; what comes out is an
edited, mixed, mastered track.

Usage:
    python3 djrill_master.py VOCAL.wav --genre Drill --bpm 92 \\
        --title "Cypress Killa (DJRILL Master)" --seed 5
"""
import sys
import os
import argparse
import importlib.util
import numpy as np
from scipy.io.wavfile import read as wav_read, write as wav_write
from scipy import signal

SR = 44100

# ---------------------------------------------------------------- engine
def load_engine():
    sys.path.insert(0, "/tmp/stubs")  # headless pygame stub (import-time only)
    here = os.path.dirname(os.path.abspath(__file__))
    spec = importlib.util.spec_from_file_location(
        "djrill_v68", os.path.join(here, "app", "djrill_mixer_v68.py"))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def load_audio(path):
    ext = os.path.splitext(path)[1].lower()
    if ext != ".wav":
        # V68.1: accept any filetype as a recording via the universal converter
        from djrill_convert import decode_any
        return SR, decode_any(path, SR, 2)
    sr, d = wav_read(path)
    if d.dtype == np.int16:
        d = d.astype(np.float64) / 32768.0
    elif d.dtype == np.int32:
        d = d.astype(np.float64) / 2147483648.0
    else:
        d = d.astype(np.float64)
    if d.ndim == 1:
        d = np.column_stack([d, d])
    if sr != SR:
        n = int(d.shape[0] * SR / sr)
        d = signal.resample(d, n)
    return SR, d


# ---------------------------------------------------------------- detect
def onset_envelope(x, sr, win=1024, hop=512):
    nfr = max(1, (len(x) - win) // hop)
    env = np.zeros(nfr)
    prev = None
    for i in range(nfr):
        fr = x[i*hop:i*hop+win] * np.hanning(win)
        mag = np.abs(np.fft.rfft(fr))
        if prev is not None:
            env[i] = np.sum(np.maximum(0, mag - prev))
        prev = mag
    mx = env.max()
    return env / mx if mx > 0 else env, sr / hop


def detect_bpm(x, sr):
    env, fps = onset_envelope(x, sr)
    if env.max() <= 0:
        return None
    c = env - np.median(env)
    ac = np.correlate(c, c, mode="full")[len(c)-1:]
    lo, hi = int(fps*60/180), int(fps*60/50)
    if hi <= lo or np.max(ac[lo:hi]) < 1e-9:
        return None
    peak = lo + int(np.argmax(ac[lo:hi]))
    return float(60 * fps / peak)


def first_onset_sec(x, sr, thresh=0.3):
    env, fps = onset_envelope(x, sr)
    for i, v in enumerate(env):
        if v > thresh:
            return float(i / fps)
    return 0.0


# ---------------------------------------------------------------- polish
def highpass(x, sr, fc=70):
    sos = signal.butter(2, fc, btype="highpass", fs=sr, output="sos")
    return signal.sosfilt(sos, x, axis=0)


def gentle_compress(x, sr, thr_db=-18.0, ratio=2.0, attack_ms=10.0, release_ms=120.0):
    """Linked feedforward peak compressor. Gentle by design."""
    det = np.max(np.abs(x), axis=1)
    a_att = np.exp(-1.0 / (attack_ms * sr / 1000.0))
    a_rel = np.exp(-1.0 / (release_ms * sr / 1000.0))
    env = np.zeros_like(det)
    e = 0.0
    for i, v in enumerate(det):
        a = a_att if v > e else a_rel
        e = a * e + (1 - a) * v
        env[i] = e
    env_db = 20 * np.log10(np.maximum(env, 1e-9))
    over = np.maximum(0.0, env_db - thr_db)
    gain_db = -(over * (1.0 - 1.0 / ratio))
    gain = 10 ** (gain_db / 20.0)
    return x * gain[:, None]


def polish_vocal(v):
    v = highpass(v, SR, 70)
    v = gentle_compress(v, SR)
    peak = np.max(np.abs(v))
    if peak > 0:
        v = v / peak * 0.7
    return v


# ---------------------------------------------------------------- reference match
MATCH_BANDS = [(20, 150), (150, 400), (400, 1200), (1200, 4000), (4000, 10000), (10000, 20000)]
BAND_CENTERS = [85, 275, 800, 2600, 7000, 15000]

# ---------------------------------------------------------------- V8 reference profile
# Measured from Before_Its_Too_Late_OGREMIX_V8_MASTER.mp3 (Daryl's approved
# sound reference). Spectral balance in spectral_bands() format, plus the
# integrated loudness the V8 master sits at. The V8 sound: louder, tighter
# low-mids, stronger sub, more 1-6 kHz presence, gentle bus glue.
V8_PROFILE = {
    "bands": {(20, 150): -5.47, (150, 400): -7.69, (400, 1200): -4.79,
              (1200, 4000): -8.37, (4000, 10000): -13.04, (10000, 20000): -17.31},
    "target_lufs": -16.9,
    "glue_drive": 1.06,   # a touch hotter than the default 1.03 for V8's glue
}


def spectral_bands(x, sr):
    X = np.abs(np.fft.rfft(x * np.hanning(len(x))))
    freqs = np.fft.rfftfreq(len(x), 1 / sr)
    tot = np.sum(X ** 2)
    out = {}
    for lo, hi in MATCH_BANDS:
        m = (freqs >= lo) & (freqs < hi)
        out[(lo, hi)] = 10 * np.log10(np.sum(X[m] ** 2) / tot)
    return out


def design_match_eq(mix_bands, ref_bands, sr, max_corr_db=7.0):
    """FIR EQ that bends the mix's spectral balance toward the reference."""
    deltas = []
    for (lo, hi), c in zip(MATCH_BANDS, BAND_CENTERS):
        d = ref_bands[(lo, hi)] - mix_bands[(lo, hi)]
        deltas.append(float(np.clip(d, -max_corr_db, max_corr_db)))
    # anchor the ends to the nearest band (firwin2 needs 0..fs/2)
    # narrow the bass shelf: extra midpoint so the 85 Hz boost decays
    # fast instead of bleeding a broad hump into 150-400 Hz
    mid_f, mid_g = 150.0, deltas[0] * 0.25 + deltas[1] * 0.75
    freq_pts = [0, BAND_CENTERS[0], mid_f] + BAND_CENTERS[1:] + [sr / 2]
    gain_db = [deltas[0], deltas[0], mid_g] + deltas[1:] + [deltas[-1]]
    taps = signal.firwin2(255, freq_pts, 10 ** (np.array(gain_db) / 20.0), fs=sr)
    return taps, deltas


def apply_fir(x, taps):
    return np.column_stack([signal.fftconvolve(x[:, ch], taps, mode="same")
                            for ch in range(x.shape[1])])


# ---------------------------------------------------------------- master
# ITU-R BS.1770 K-weighting coefficients
_PRE_B = [1.53512485958697, -2.69169618940638, 1.19839281085285]
_PRE_A = [1.0, -1.69065929318241, 0.73248077421585]
_RLB_B = [1.0, -2.0, 1.0]
_RLB_A = [1.0, -1.99004745483398, 0.99007225036621]


def integrated_lufs(x, sr):
    y = signal.lfilter(_PRE_B, _PRE_A, x, axis=0)
    y = signal.lfilter(_RLB_B, _RLB_A, y, axis=0)
    blk, hop = int(sr * 0.4), int(sr * 0.1)
    ms = []
    for s in range(0, y.shape[0] - blk, hop):
        b = y[s:s+blk]
        ms.append(np.mean(b ** 2))
    ms = np.array(ms)
    if ms.size == 0:
        return float("-inf")
    lufs = -0.691 + 10 * np.log10(np.maximum(ms, 1e-12))
    gated = lufs[lufs > -70]
    if gated.size == 0:
        return float("-inf")
    # relative gate: 10 LU below the mean loudness of absolute-gated blocks
    mean_loud = -0.691 + 10 * np.log10(np.mean(10 ** (gated / 10)))
    g2 = gated[gated > mean_loud - 10]
    if g2.size == 0:
        return float("-inf")
    return float(-0.691 + 10 * np.log10(np.mean(10 ** (g2 / 10))))


def true_peak(x, sr, oversample=4):
    up = signal.resample_poly(x, oversample, 1, axis=0)
    return float(np.max(np.abs(up)))


# ---------------------------------------------------------------- QA gates
def envelope(x, sr, win_ms=50.0):
    w = max(1, int(sr * win_ms / 1000.0))
    mono = x.mean(axis=1) if x.ndim > 1 else x
    n = (len(mono) // w) * w
    return np.sqrt(np.mean(mono[:n].reshape(-1, w) ** 2, axis=1) + 1e-12)


def verify_vocal_integrity(vocal_polished, mix, s0, min_corr=0.85):
    """Lyric-integrity gate: the vocal's energy envelope must survive into the
    mix at the place it was laid. Returns (ok, correlation). A deleted or
    snipped vocal craters the correlation; beat bleed alone cannot."""
    n = vocal_polished.shape[0]
    region = mix[s0:s0 + n]
    if region.shape[0] < n:
        return False, 0.0
    ev = envelope(vocal_polished, SR)
    em = envelope(region, SR)
    k = min(len(ev), len(em))
    ev, em = ev[:k], em[:k]
    ev = ev - ev.mean(); em = em - em.mean()
    denom = np.sqrt(np.sum(ev ** 2) * np.sum(em ** 2)) + 1e-12
    corr = float(np.sum(ev * em) / denom)
    return corr >= min_corr, corr


def verify_no_clipping(pcm, sr, ceiling_db=-1.0):
    """True-peak gate on the finished master. Returns (ok, tp_db)."""
    tp = true_peak(pcm.astype(np.float64) / 32768.0, sr)
    tp_db = 20 * np.log10(tp + 1e-12)
    return tp_db <= ceiling_db + 0.05, tp_db


def master_track(mix, target_lufs=-14.0, ceiling_db=-1.0, glue_drive=1.03):
    # whisper of bus glue (kept dynamic like the reference masters)
    mix = np.tanh(mix * glue_drive) / np.tanh(glue_drive)
    # loudness normalize
    lufs = integrated_lufs(mix, SR)
    if np.isfinite(lufs):
        mix = mix * 10 ** ((target_lufs - lufs) / 20.0)
    # true-peak limit
    tp = true_peak(mix, SR)
    ceiling = 10 ** (ceiling_db / 20.0)
    if tp > ceiling and tp > 0:
        mix = mix * (ceiling / tp)
    mix = np.clip(mix, -1.0, 1.0)
    # TPDF dither to 16-bit
    dith = (np.random.rand(*mix.shape) - np.random.rand(*mix.shape)) * (0.5 / 32768.0)
    out = np.clip(mix + dith, -1.0, 1.0)
    return (out * 32767).astype(np.int16), integrated_lufs(mix, SR), true_peak(mix, SR)


# ---------------------------------------------------------------- beat
def new_beat_seed():
    """Strong unique seed so no two generated beats ever repeat."""
    import secrets
    return int.from_bytes(secrets.token_bytes(4), "big")


def render_beat(m, genre, bpm, n_bars, seed=None):
    if seed is None:
        seed = new_beat_seed()
    print(f"[DJRILL] beat seed: {seed} (genre={genre}, bpm={bpm}, bars={n_bars}) — "
          f"reuse this seed to regenerate the identical beat")
    g = m.Generator(seed=seed, genre=genre, hook_name="Hook A")
    g.tempo = float(bpm)
    g.current_global_tempo = float(bpm)
    g.last_bar_tempo = float(bpm)
    # keep the beat dynamic: no per-bar limiting here, one gentle limit at the end
    g._bypass_master = True
    # V69: arrangement variant from the seed — same genre, different song shape
    song = m.SongStructure(num_verses=3, num_hooks=4, variant=int(seed) % 3)
    chunks = []
    for bar in range(n_bars):
        sname, _, bis = song.get_section_info(bar)
        g.synthesize_bar_audio(sname, bis)
        chunks.append(g.current_bar_audio_buffer)
    g._bypass_master = False
    beat = np.concatenate(chunks, axis=0)
    peak = np.max(np.abs(beat))
    if peak > 0:
        beat = beat / peak * 0.9
    # sub reinforcement: the synth 808/kick is light vs commercial refs;
    # lift 20-120 Hz with a tight shelf so the adaptive match EQ that
    # follows doesn't have to hit its correction cap
    sub_taps = signal.firwin2(255, [0, 60, 120, 200, SR / 2],
                              [2.51, 2.51, 1.78, 1.0, 1.0], fs=SR)  # +8/+5/0 dB
    beat = np.column_stack([signal.fftconvolve(beat[:, ch], sub_taps, mode="same")
                            for ch in range(beat.shape[1])])
    peak = np.max(np.abs(beat))
    if peak > 0:
        beat = beat / peak * 0.9
    return beat


# ---------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser(description="DJRILL mastering pipeline (edits, never generates, a performance)")
    ap.add_argument("vocal", help="recording to master (WAV/MP3)")
    ap.add_argument("--genre", default="HipHop")
    ap.add_argument("--bpm", type=float, default=None)
    ap.add_argument("--title", default="DJRILL Master")
    ap.add_argument("--seed", type=int, default=None,
                    help="beat seed for reproducibility; omit for a fresh unique beat every run")
    ap.add_argument("--intro-bars", type=int, default=1)
    ap.add_argument("--reference", default=None,
                    help="reference master to match (spectral balance + loudness)")
    ap.add_argument("--v8", dest="v8", action="store_true", default=True,
                    help="master to Daryl's V8 reference profile (default on)")
    ap.add_argument("--no-v8", dest="v8", action="store_false",
                    help="disable the V8 reference profile")
    ap.add_argument("--vocal-boost-db", type=float, default=2.5,
                    help="extra vocal level vs the beat (vocals-forward)")
    ap.add_argument("--outdir", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "masters"))
    args = ap.parse_args()

    print(f"[MASTER] loading recording: {args.vocal}")
    _, vocal = load_audio(args.vocal)
    v_dur = vocal.shape[0] / SR
    print(f"[MASTER] recording: {v_dur:.1f}s")

    bpm = args.bpm or detect_bpm(vocal.mean(axis=1), SR) or 90.0
    print(f"[MASTER] tempo: {bpm:.2f} BPM")
    bar_dur = 60.0 / bpm * 4
    intro = args.intro_bars * bar_dur
    total = intro + v_dur + 2 * bar_dur
    n_bars = int(np.ceil(total / bar_dur))
    print(f"[MASTER] rendering {n_bars} bars of {args.genre} beat (seed {args.seed})...")

    m = load_engine()
    m.BASE_DIR = "/tmp/djrill_nomedia/"
    m.SAMPLE_BASE_DIR = "/tmp/djrill_nomedia/Ai_music_samples"
    beat = render_beat(m, args.genre, bpm, n_bars, args.seed)

    print("[MASTER] polishing vocal (HP + gentle compression)...")
    vp = polish_vocal(vocal)

    print("[MASTER] mixing (voice-forward)...")
    need = int(intro + vocal.shape[0] + 1 * SR)
    mix = np.zeros((max(need, beat.shape[0]), 2))
    mix[:beat.shape[0]] += beat * 0.5
    s0 = int(intro * SR)
    mix[s0:s0+vp.shape[0]] += vp * 10 ** (args.vocal_boost_db / 20.0)
    # trim trailing silence past content
    end = min(mix.shape[0], s0 + vp.shape[0] + int(2 * SR))
    mix = mix[:end]
    # fades
    fi = int(0.5 * SR)
    mix[:fi] *= np.linspace(0, 1, fi)[:, None]
    fo = int(3 * SR)
    mix[-fo:] *= np.linspace(1, 0, fo)[:, None]

    target_lufs = -14.0
    glue_drive = 1.03
    if args.reference:
        print(f"[MASTER] matching reference: {args.reference}")
        _, ref_audio = load_audio(args.reference)
        ref_bands = spectral_bands(ref_audio.mean(axis=1), SR)
        ref_lufs = integrated_lufs(ref_audio, SR)
        mix_bands = spectral_bands(mix.mean(axis=1), SR)
        taps, deltas = design_match_eq(mix_bands, ref_bands, SR)
        print("[MASTER] corrective EQ (dB): " +
              " ".join(f"{c}:{d:+.1f}" for c, d in zip(BAND_CENTERS, deltas)))
        mix = apply_fir(mix, taps)
        if np.isfinite(ref_lufs):
            target_lufs = float(ref_lufs)
            print(f"[MASTER] target loudness from reference: {target_lufs:.1f} LUFS")
    elif args.v8:
        print("[MASTER] V8 reference profile (Daryl's approved sound)")
        mix_bands = spectral_bands(mix.mean(axis=1), SR)
        taps, deltas = design_match_eq(mix_bands, V8_PROFILE["bands"], SR)
        print("[MASTER] V8 corrective EQ (dB): " +
              " ".join(f"{c}:{d:+.1f}" for c, d in zip(BAND_CENTERS, deltas)))
        mix = apply_fir(mix, taps)
        target_lufs = V8_PROFILE["target_lufs"]
        glue_drive = V8_PROFILE["glue_drive"]
        print(f"[MASTER] V8 target loudness: {target_lufs:.1f} LUFS")

    # lyric-integrity gate: vocal envelope must survive into the mix
    ok_vox, vox_corr = verify_vocal_integrity(vp, mix, s0)
    print(f"[QA] vocal integrity: corr={vox_corr:.3f} {'PASS' if ok_vox else 'FAIL — vocal damaged!'}")
    if not ok_vox:
        print("[QA] ABORTING: lyric integrity check failed, refusing to master a damaged vocal")
        return 1

    print(f"[MASTER] mastering to {target_lufs:.1f} LUFS / -1.0 dBTP...")
    pcm16, lufs, tp = master_track(mix, target_lufs=target_lufs, glue_drive=glue_drive)

    # clip gate on the PCM master
    ok_tp, tp_db = verify_no_clipping(pcm16, SR)
    print(f"[QA] true peak: {tp_db:.2f} dBTP {'PASS' if ok_tp else 'FAIL — clipping!'}")
    if not ok_tp:
        print("[QA] ABORTING: master clips, refusing to deliver")
        return 1

    os.makedirs(args.outdir, exist_ok=True)
    safe = "".join(c if c.isalnum() or c in " _-" else "_" for c in args.title).strip()
    wav_path = os.path.join(args.outdir, safe + ".wav")
    mp3_path = os.path.join(args.outdir, safe + ".mp3")
    wav_write(wav_path, SR, pcm16)
    import shlex
    os.system(f"ffmpeg -y -v error -i {shlex.quote(wav_path)} -codec:a libmp3lame -b:a 192k {shlex.quote(mp3_path)}")
    # clip gate on the encoded MP3 (encoding can add ~0.5 dB)
    _, mp3_audio = load_audio(mp3_path)
    ok_mp3, mp3_tp = verify_no_clipping((mp3_audio * 32767).astype(np.int16), SR)
    print(f"[QA] MP3 true peak: {mp3_tp:.2f} dBTP {'PASS' if ok_mp3 else 'FAIL — encoded MP3 clips!'}")
    print(f"[MASTER] wrote {mp3_path}")
    print(f"[MASTER] report: {lufs:.1f} LUFS integrated, {20*np.log10(tp):.2f} dBTP, {end/SR:.1f}s")


if __name__ == "__main__":
    main()
