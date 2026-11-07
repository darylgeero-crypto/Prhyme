"""DJRILL universal media conversion — audio, video, and images.

Decodes audio (MP3, WAV, OGG/Opus, M4A/AAC, FLAC, WMA, AIFF), video
(MP4, MOV, MKV, WebM, AVI, M4V) and images (JPG, PNG, WebP, GIF, BMP, TIFF)
via ffmpeg/Pillow; encodes to audio, video, or image outputs.
Used by the sample loader (any filetype as a sample), the mastering
pipeline (any filetype as a recording), the chat console, and the
/convert page (any media file to any media file).
Documents (PDF/Word) and archives are NOT covered: they need LibreOffice
or office tooling that is not installed on the phone or the cloud host,
so they are rejected with a plain message instead of a broken promise.
"""
import subprocess
import os
import json
from shutil import which

import numpy as np

FFMPEG = which("ffmpeg")
FFPROBE = which("ffprobe")
FFMPEG_OK = FFMPEG is not None

AUDIO_IN = {".wav", ".mp3", ".ogg", ".oga", ".opus", ".m4a", ".aac",
            ".flac", ".wma", ".aiff", ".aif"}
VIDEO_IN = {".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v"}
IMAGE_IN = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp",
            ".tiff", ".tif"}
SUPPORTED_IN = AUDIO_IN | VIDEO_IN | IMAGE_IN

AUDIO_OUT = {".wav", ".mp3", ".ogg", ".flac", ".m4a", ".opus"}
VIDEO_OUT = {".mp4", ".webm", ".mov", ".mkv"}
IMAGE_OUT = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
SUPPORTED_OUT = AUDIO_OUT | VIDEO_OUT | IMAGE_OUT


def _kind(ext):
    ext = (ext or "").lower()
    if ext in AUDIO_OUT:
        return "audio"
    if ext in VIDEO_OUT:
        return "video"
    if ext in IMAGE_OUT:
        return "image"
    return None


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


def probe_streams(path):
    """Return {has_audio, has_video} for a media file via ffprobe."""
    if not FFPROBE:
        return {"has_audio": False, "has_video": False}
    try:
        out = subprocess.run(
            [FFPROBE, "-v", "error", "-show_entries", "stream=codec_type",
             "-of", "json", path],
            capture_output=True, check=True, text=True).stdout
        types = {s.get("codec_type") for s in json.loads(out).get("streams", [])}
        return {"has_audio": "audio" in types, "has_video": "video" in types}
    except Exception:
        return {"has_audio": False, "has_video": False}


def probe(path):
    """Return {duration, codec, sample_rate, channels, width, height}.

    Video stream first when one exists (a file with video IS a video file,
    so its codec/dimensions describe it), then audio, then Pillow for
    still images. Missing values stay 0/None instead of raising.
    """
    info = {"codec": None, "sample_rate": 0, "channels": 0,
            "duration": 0.0, "width": 0, "height": 0}
    if FFPROBE:
        try:
            out = subprocess.run(
                [FFPROBE, "-v", "error",
                 "-show_entries",
                 "stream=codec_type,codec_name,sample_rate,channels,width,height:format=duration",
                 "-of", "json", path],
                capture_output=True, check=True, text=True).stdout
            j = json.loads(out)
            streams = j.get("streams") or []
            audio = next((s for s in streams if s.get("codec_type") == "audio"), None)
            video = next((s for s in streams if s.get("codec_type") == "video"), None)
            pick = video or audio
            if pick:
                info["codec"] = pick.get("codec_name")
                info["sample_rate"] = int(pick.get("sample_rate", 0) or 0)
                info["channels"] = int(pick.get("channels", 0) or 0)
                info["width"] = int(pick.get("width", 0) or 0)
                info["height"] = int(pick.get("height", 0) or 0)
            info["duration"] = float((j.get("format") or {}).get("duration", 0) or 0)
            if info["codec"]:
                return info
        except Exception:
            pass
    try:
        from PIL import Image as _Image
        with _Image.open(path) as im:
            info["codec"] = (im.format or "image").lower()
            info["width"], info["height"] = im.size
    except Exception:
        pass
    return info


def _is_image(path):
    return os.path.splitext(path)[1].lower() in IMAGE_IN


def _convert_audio(src, dst, ext, sr, bitrate):
    cmd = [FFMPEG, "-y", "-v", "error", "-i", src, "-vn"]
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
    elif ext == ".opus":
        cmd += ["-ac", "2", "-codec:a", "libopus", "-b:a", bitrate]
    cmd.append(dst)
    subprocess.run(cmd, check=True)
    return dst


def _convert_video(src, dst, ext, bitrate):
    streams = probe_streams(src)
    if _is_image(src):
        # Still image -> 3-second clip.
        cmd = [FFMPEG, "-y", "-v", "error", "-loop", "1", "-t", "3", "-i", src]
    elif streams["has_video"]:
        cmd = [FFMPEG, "-y", "-v", "error", "-i", src]
    else:
        raise ValueError("no video in this file — it has audio only, "
                         "so it can convert to audio, not video")
    if ext == ".mp4":
        cmd += ["-c:v", "libx264", "-pix_fmt", "yuv420p",
                "-c:a", "aac", "-b:a", bitrate, "-movflags", "+faststart"]
    elif ext == ".webm":
        cmd += ["-c:v", "libvpx-vp9", "-b:v", "0", "-crf", "30",
                "-c:a", "libopus"]
    elif ext == ".mov":
        cmd += ["-c:v", "libx264", "-pix_fmt", "yuv420p",
                "-c:a", "aac", "-b:a", bitrate]
    elif ext == ".mkv":
        cmd += ["-c:v", "libx264", "-pix_fmt", "yuv420p",
                "-c:a", "aac", "-b:a", bitrate]
    if _is_image(src):
        cmd += ["-shortest"]
    cmd.append(dst)
    subprocess.run(cmd, check=True)
    return dst


def _convert_image(src, dst, ext):
    if _is_image(src):
        from PIL import Image as _Image
        with _Image.open(src) as im:
            if im.mode in ("RGBA", "LA", "P") and ext in (".jpg", ".jpeg"):
                im = im.convert("RGB")
            elif im.mode == "P":
                im = im.convert("RGBA")
            im.save(dst)
        return dst
    streams = probe_streams(src)
    if not streams["has_video"]:
        raise ValueError("no picture in this file — it has audio only, "
                         "so it can convert to audio, not images")
    if ext == ".gif":
        # Animated GIF: first 5 seconds, 480px wide, 10 fps (bounded size).
        filt = ("fps=10,scale=480:-1:flags=lanczos,"
                "split[s0][s1];[s0]palettegen=max_colors=256[p];[s1][p]paletteuse")
        cmd = [FFMPEG, "-y", "-v", "error", "-t", "5", "-i", src,
               "-vf", filt, dst]
    else:
        cmd = [FFMPEG, "-y", "-v", "error", "-ss", "0", "-i", src,
               "-frames:v", "1", dst]
    subprocess.run(cmd, check=True)
    return dst


def convert_file(src, dst, sr=None, bitrate="192k"):
    """Convert any media file to an audio, video, or image output."""
    if not FFMPEG_OK and _kind(os.path.splitext(dst)[1]) != "image":
        raise RuntimeError("ffmpeg not available for file conversion")
    ext = os.path.splitext(dst)[1].lower()
    kind = _kind(ext)
    if kind is None:
        raise ValueError(f"unsupported output type {ext} (want one of {sorted(SUPPORTED_OUT)})")
    if kind == "audio":
        return _convert_audio(src, dst, ext, sr, bitrate)
    if kind == "video":
        return _convert_video(src, dst, ext, bitrate)
    return _convert_image(src, dst, ext)


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="DJRILL media file converter")
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
