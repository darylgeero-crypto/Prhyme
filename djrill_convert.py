"""DJRILL universal audio conversion — accept any filetype, convert to any.

Decodes MP3, WAV, OGG/Opus, M4A/AAC, FLAC, WMA, AIFF (and video files'
audio tracks) via ffmpeg; encodes to WAV, MP3, OGG, FLAC, M4A.
Used by the sample loader (any filetype as a sample), the mastering
pipeline (any filetype as a recording), and the chat console.
"""
import subprocess
import os
import json
from shutil import which

import numpy as np

FFMPEG = which("ffmpeg")
FFPROBE = which("ffprobe")
FFMPEG_OK = FFMPEG is not None

SUPPORTED_IN = {".wav", ".mp3", ".ogg", ".oga", ".opus", ".m4a", ".aac",
                ".flac", ".wma", ".aiff", ".aif", ".mp4", ".mov", ".mkv"}
SUPPORTED_OUT = {".wav", ".mp3", ".ogg", ".flac", ".m4a"}


def decode_any(path, sr=44100, channels=2):
    """Decode any supported audio file -> float64 (frames, channels) @ sr."""
    if FFMPEG_OK:
        raw = subprocess.run(
            [FFMPEG, "-v", "error", "-i", path, "-ac", str(channels),
             "-ar", str(sr), "-f", "f32le", "-"],
            capture_output=True, check=True).stdout
        d = np.frombuffer(raw, dtype=np.float32).reshape(-1, channels).astype(np.float64)
        if d.size == 0:
            raise RuntimeError(f"could not decode audio from {path}")
        return d
    # Fallback: miniaudio (pure Python wheel, no system ffmpeg needed)
    try:
        import miniaudio
        info = miniaudio.decode_file(path, output_format=miniaudio.SampleFormat.FLOAT32)
        d = np.frombuffer(info.samples, dtype=np.float32)
        in_ch = info.nchannels
        d = d.reshape(-1, in_ch)
        # Resample if needed (simple linear)
        if info.sample_rate != sr:
            n_out = int(d.shape[0] * sr / info.sample_rate)
            idx = np.linspace(0, d.shape[0] - 1, n_out)
            d = np.stack([np.interp(idx, np.arange(d.shape[0]), d[:, c]) for c in range(in_ch)], axis=1)
        # Channel convert
        if in_ch == 1 and channels == 2:
            d = np.column_stack([d[:, 0], d[:, 0]])
        elif in_ch == 2 and channels == 1:
            d = d.mean(axis=1, keepdims=True)
        elif in_ch != channels:
            d = d[:, :channels] if in_ch > channels else np.column_stack([d] * channels)[:, :channels]
        d = d.astype(np.float64)
        if d.size == 0:
            raise RuntimeError(f"could not decode audio from {path}")
        return d
    except ImportError:
        pass
    raise RuntimeError("ffmpeg not available for file conversion")


def probe(path):
    """Return {duration, codec, sample_rate, channels} via ffprobe."""
    if not FFPROBE:
        raise RuntimeError("ffprobe not available")
    out = subprocess.run(
        [FFPROBE, "-v", "error", "-select_streams", "a:0",
         "-show_entries", "stream=codec_name,sample_rate,channels:format=duration",
         "-of", "json", path],
        capture_output=True, check=True, text=True).stdout
    j = json.loads(out)
    s = (j.get("streams") or [{}])[0]
    return {
        "codec": s.get("codec_name"),
        "sample_rate": int(s.get("sample_rate", 0)),
        "channels": int(s.get("channels", 0)),
        "duration": float((j.get("format") or {}).get("duration", 0) or 0),
    }


def convert_file(src, dst, sr=None, bitrate="192k"):
    """Convert any audio file to WAV/MP3/OGG/FLAC/M4A."""
    if not FFMPEG_OK:
        raise RuntimeError("ffmpeg not available for file conversion")
    ext = os.path.splitext(dst)[1].lower()
    if ext not in SUPPORTED_OUT:
        raise ValueError(f"unsupported output type {ext} (want one of {sorted(SUPPORTED_OUT)})")
    cmd = [FFMPEG, "-y", "-v", "error", "-i", src]
    if sr:
        cmd += ["-ar", str(sr)]
    if ext == ".wav":
        cmd += ["-ac", "2", "-c:a", "pcm_s16le"]
    elif ext == ".mp3":
        cmd += ["-ac", "2", "-codec:a", "libmp3lame", "-b:a", bitrate]
    elif ext == ".ogg":
        cmd += ["-ac", "2", "-codec:a", "libvorbis", "-b:a", bitrate]
    elif ext == ".flac":
        cmd += ["-ac", "2", "-codec:a", "flac"]
    elif ext == ".m4a":
        cmd += ["-ac", "2", "-codec:a", "aac", "-b:a", bitrate]
    cmd.append(dst)
    subprocess.run(cmd, check=True)
    return dst


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="DJRILL audio file converter")
    ap.add_argument("src")
    ap.add_argument("dst")
    ap.add_argument("--sr", type=int, default=None)
    ap.add_argument("--bitrate", default="192k")
    ap.add_argument("--info", action="store_true", help="print file info instead of converting")
    a = ap.parse_args()
    if a.info:
        print(json.dumps(probe(a.src), indent=1))
    else:
        convert_file(a.src, a.dst, sr=a.sr, bitrate=a.bitrate)
        print(f"converted -> {a.dst}")
