"""chunkpipe — Prhyme's single shared chunk/stitch pipeline (2026-10-20).

Daryl's unification directive: mastering (large sections + adaptive),
vocal separation, and sectional work all run on THIS code for splitting
audio into overlapping chunks and stitching it back — one implementation,
one set of tests, fully offline.

Semantics (proven by the 2026-10-20 marker test): chunks after the first
start `overlap` earlier so the crossfade blends the SAME audio moment in
both chunks — joins land sample-exact, no audio is eaten.
"""
import os
import subprocess

import numpy as np


def fade_ramps(xfade_n, channels=2):
    """Linear (1->0) / (0->1) crossfade ramps, shape (xfade_n, channels)."""
    fo = np.linspace(1, 0, xfade_n, dtype=np.float32)
    fi = np.linspace(0, 1, xfade_n, dtype=np.float32)
    if channels and channels > 1:
        fo = np.repeat(fo[:, None], channels, axis=1)
        fi = np.repeat(fi[:, None], channels, axis=1)
    return fo, fi


def xfade_blend(tail, head, xfade_n):
    """Blend the last xfade_n of A with the first xfade_n of B."""
    fo, fi = fade_ramps(xfade_n, tail.shape[1] if tail.ndim > 1 else 1)
    return tail[-xfade_n:] * fo + head[:xfade_n] * fi


def _as_float_stereo(p):
    if p.ndim == 1:
        p = p[:, None]
    if p.dtype == np.int16:
        p = p.astype(np.float32) / 32768.0
    elif p.dtype != np.float32:
        p = p.astype(np.float32)
    return p


def stitch_parts(parts, xfade_n):
    """Stitch a list of int16/float arrays with crossfades.

    Returns float32 in [-1, 1]; caller converts if it needs int16.
    """
    import gc
    parts = [_as_float_stereo(p) for p in parts]
    result = parts[0]
    for nxt in parts[1:]:
        if len(result) >= xfade_n and len(nxt) >= xfade_n:
            if result.shape[1] != nxt.shape[1]:
                if nxt.shape[1] == 1:
                    nxt = np.repeat(nxt, result.shape[1], axis=1)
                else:
                    result = np.repeat(result, nxt.shape[1], axis=1)
            x = xfade_blend(result, nxt, xfade_n)
            result = np.concatenate([result[:-xfade_n], x, nxt[xfade_n:]], axis=0)
        else:
            result = np.concatenate([result, nxt], axis=0)
        gc.collect()
    return result


def cut_sections(src_path, outdir, section_s, xfade_s, sr, prefix="sect_", spans_s=None):
    """Split src into section WAVs on disk via ffmpeg (zero RAM).

    Section i>0 starts xfade_s earlier and runs xfade_s longer so the
    stitch crossfade aligns the same audio moment in both sections.
    Returns the list of section file paths that exist and are non-trivial.
    """
    import math
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", src_path],
            capture_output=True, text=True, timeout=15)
        duration = float(r.stdout.strip())
    except Exception:
        try:
            duration = os.path.getsize(src_path) / 16000.0
        except Exception:
            duration = 0
    if spans_s:
        spans = [(max(0.0, a), min(duration, b)) for a, b in spans_s if b > a]
    else:
        n_fixed = int(math.ceil(duration / section_s)) if duration > 0 else 0
        spans = [(i * section_s, min(duration, (i + 1) * section_s))
                 for i in range(n_fixed)]
    files = []
    for i, (sec_start, sec_end) in enumerate(spans):
        start = sec_start - (xfade_s if i > 0 else 0)
        length = (sec_end - sec_start) + (xfade_s if i > 0 else 0)
        fp = os.path.join(outdir, f"{prefix}{i:03d}.wav")
        subprocess.run(
            ["ffmpeg", "-y", "-i", src_path,
             "-ss", str(start), "-t", str(length),
             "-c:a", "pcm_s16le", "-ar", str(sr), "-ac", "2", fp],
            capture_output=True, timeout=300)
        if os.path.exists(fp) and os.path.getsize(fp) > 1024:
            files.append(fp)
    return files, duration


def chunk_windows(total, chunk_n, overlap_n):
    """Yield (start, end) windows stepping by chunk_n - overlap_n."""
    step = chunk_n - overlap_n
    n = max(1, int(np.ceil((total - overlap_n) / step)))
    for ci in range(n):
        s = ci * step
        e = min(s + chunk_n, total)
        yield ci, s, e


def blend_into(buf, s, e, chunk_out, ov_n, fade):
    """Separator-style incremental blend of one processed chunk into buf.

    The overlap region is crossfaded against what is already in buf;
    the remainder is written directly. `fade` is linspace(0,1,ov_n)[:,None].
    """
    m = e - s
    chunk_out = chunk_out[:m]
    if s > 0:
        buf[s:s + ov_n] = buf[s:s + ov_n] * (1 - fade) + chunk_out[:ov_n] * fade
        buf[s + ov_n:e] = chunk_out[ov_n:]
    else:
        buf[s:e] = chunk_out


# ------------------------------------------------- RAM-versatile sizing
def mem_available_mb():
    """Free RAM (MB) from /proc/meminfo; None when unknown."""
    try:
        with open("/proc/meminfo") as f:
            for line in f:
                if line.startswith("MemAvailable:"):
                    return int(line.split()[1]) // 1024
    except OSError:
        pass
    return None


def ram_chunk_s(base_s, low_s, high_s):
    """Versatile RAM use (Daryl's rule): scale chunk length to free RAM.
    Plenty free -> bigger chunks (fewer passes, faster). Tight -> smaller
    chunks (never overload). One heavy job at a time keeps the total in
    check; this keeps each job's footprint proportional to headroom."""
    avail = mem_available_mb()
    if avail is None:
        return base_s
    if avail >= 1500:
        return high_s
    if avail >= 1000:
        return (base_s + high_s) / 2.0
    if avail >= 550:
        return base_s
    return low_s


def stitch_files(parts, out_path, xfade_n, sr, prog=None):
    """Stream-stitch section WAV files into one WAV with crossfades.

    The ONE stitcher (2026-10-21, Daryl's order): every mastering path
    joins its sections through here. Disk-to-disk — only one section
    plus a crossfade tail is ever in RAM, so long tracks cannot run
    out of memory while stitching. Parts after the first must start
    xfade_n samples early (the overlap built in by cut_sections and
    by the adaptive extractor). Returns out_path.
    """
    import gc

    import soundfile as sf

    fade_out, fade_in = fade_ramps(xfade_n)
    n = len(parts)
    with sf.SoundFile(out_path, mode="w", samplerate=sr, channels=2,
                      subtype="PCM_16") as out:
        prev_tail = None
        for idx, spath in enumerate(parts):
            if prog:
                prog(idx / max(1, n), "Stitching %d/%d…" % (idx + 1, n))
            cur, _ = sf.read(spath, dtype="float32", always_2d=True)
            if cur.shape[1] == 1:
                cur = np.repeat(cur, 2, axis=1)
            if prev_tail is not None and len(cur) >= xfade_n:
                out.write(prev_tail * fade_out + cur[:xfade_n] * fade_in)
                body = cur[xfade_n:]
            else:
                body = cur
            if idx == n - 1:
                out.write(body)
                prev_tail = None
            elif len(body) > xfade_n:
                out.write(body[:-xfade_n])
                prev_tail = body[-xfade_n:].copy()
            else:
                out.write(body)
                prev_tail = None
            del cur, body
            gc.collect()
    return out_path
