"""Prhyme video EDITOR — real editing of existing videos (2026-10-21).

The /video generator renders new videos from audio; this module edits
videos Daryl already has, the way Resolve/Premiere/CapCut do at the core:

- edit_video(): trim, speed, brightness/contrast/saturation sliders,
  colour-grade presets, rotate/flip, resize, aspect pad, volume, audio
  fades, video fades, timed text overlays, mute, extract-audio — built
  as ONE ffmpeg filterchain pass (single decode, phone-friendly).
- concat_videos(): the timeline in list form — multiple clips with
  per-clip in/out points joined with hard cuts or dissolves (xfade +
  acrossfade), normalized to one canvas/fps like a real timeline.
- snapshot(): poster frame extraction.

Progress uses ffmpeg -progress polling; when the progress callback
raises (job cancel), the ffmpeg process is KILLED — unlike the older
runner in djrill_video, which orphaned it.
"""

import json
import os
import subprocess
import time

import djrill_video as V
import videofx

ASPECT_DIMS = videofx.ASPECTS
SPEEDS = (0.25, 0.5, 0.75, 1.0, 1.25, 1.5, 2.0, 3.0)


def probe(path):
    """Return dict(duration, width, height, fps, has_audio, has_video)."""
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-print_format", "json",
         "-show_format", "-show_streams", path],
        capture_output=True, text=True)
    info = json.loads(out.stdout or "{}")
    res = {"duration": 0.0, "width": 0, "height": 0, "fps": 30.0,
           "has_audio": False, "has_video": False}
    try:
        res["duration"] = float(info.get("format", {}).get("duration", 0))
    except (TypeError, ValueError):
        pass
    for s in info.get("streams", []):
        if s.get("codec_type") == "video" and not res["has_video"]:
            res["has_video"] = True
            res["width"] = int(s.get("width", 0))
            res["height"] = int(s.get("height", 0))
            fr = s.get("avg_frame_rate", "30/1")
            try:
                n, d = fr.split("/")
                res["fps"] = float(n) / max(1.0, float(d))
            except (ValueError, ZeroDivisionError):
                pass
        elif s.get("codec_type") == "audio":
            res["has_audio"] = True
    return res


def run_ffmpeg_progress(cmd, total_dur, progress_cb=None):
    """Run ffmpeg (cmd ends with the output path); report 0..1 progress.

    If progress_cb raises, the process is killed before propagating —
    a cancelled job must not leave an encoder running on the phone.
    """
    prog_path = os.path.join(
        os.environ.get("TMPDIR", "/tmp"), "vprog_%d.txt" % os.getpid())
    try:
        os.remove(prog_path)
    except OSError:
        pass
    full = cmd[:-1] + ["-progress", prog_path, "-nostats", cmd[-1]]
    proc = subprocess.Popen(full, stderr=subprocess.DEVNULL)
    try:
        while proc.poll() is None:
            frac = 0.0
            try:
                with open(prog_path) as f:
                    for line in f:
                        if line.startswith("out_time_ms="):
                            us = int(line.split("=")[1])
                            if us > 0 and total_dur > 0:
                                frac = min(0.99, (us / 1e6) / total_dur)
                            break
            except (OSError, ValueError):
                pass
            if progress_cb:
                progress_cb(frac)
            time.sleep(0.4)
    except BaseException:
        proc.kill()
        raise
    finally:
        try:
            os.remove(prog_path)
        except OSError:
            pass
    if proc.returncode != 0:
        raise subprocess.CalledProcessError(proc.returncode, full)
    if progress_cb:
        progress_cb(1.0)


def _esc_text(s):
    return (str(s)[:120].replace("\\", " ").replace(":", "\\:")
            .replace("'", "").replace("%", "\\%"))


def _atempo_chain(speed):
    parts = []
    s = float(speed)
    while s > 2.0:
        parts.append("atempo=2.0")
        s /= 2.0
    while s < 0.5:
        parts.append("atempo=0.5")
        s /= 0.5
    parts.append(f"atempo={s:.4f}")
    return ",".join(parts)


_POS = {
    "bottom": ("(w-text_w)/2", "h-text_h-48"),
    "top": ("(w-text_w)/2", "48"),
    "center": ("(w-text_w)/2", "(h-text_h)/2"),
}


def edit_video(in_path, out_path, opts, progress_cb=None):
    """Apply the edit described by opts in one ffmpeg pass.

    opts (all optional): start, end, speed, brightness (-1..1),
    contrast (0.5..2), saturation (0..3), grade (videofx.GRADES name),
    rotate (0|90|180|270), flip ("h"|"v"|""), height (720|1080|0),
    aspect ("16:9"|"9:16"|"1:1"|""), volume_db, afade_in, afade_out,
    fade_in, fade_out, texts [{text,start,end,pos,size}], mute,
    extract ("mp3"|"").
    Returns the probed output info dict.
    """
    opts = opts or {}
    info = probe(in_path)
    dur = info["duration"]
    if dur <= 0:
        raise ValueError("Could not read the video duration")
    start = max(0.0, float(opts.get("start") or 0))
    end = float(opts.get("end") or 0)
    end = end if (end > start) else dur
    end = min(end, dur)
    seg = end - start
    speed = float(opts.get("speed") or 1.0)
    if speed not in SPEEDS:
        speed = min(SPEEDS, key=lambda s: abs(s - speed))
    out_dur = seg / speed if speed else seg
    extract = (opts.get("extract") or "") == "mp3"

    vf = []
    if int(opts.get("rotate") or 0) == 90:
        vf.append("transpose=1")
    elif int(opts.get("rotate") or 0) == 270:
        vf.append("transpose=2")
    elif int(opts.get("rotate") or 0) == 180:
        vf.append("hflip,vflip")
    if opts.get("flip") == "h":
        vf.append("hflip")
    elif opts.get("flip") == "v":
        vf.append("vflip")
    height = int(opts.get("height") or 0)
    if height in (480, 720, 1080):
        vf.append(f"scale=-2:{height}")
    aspect = opts.get("aspect") or ""
    if aspect in ASPECT_DIMS:
        W, H = ASPECT_DIMS[aspect]
        vf.append(f"scale={W}:{H}:force_original_aspect_ratio=decrease")
        vf.append(f"pad={W}:{H}:(ow-iw)/2:(oh-ih)/2:black")
    b = float(opts.get("brightness") or 0)
    c = float(opts.get("contrast") if opts.get("contrast") is not None else 1)
    s_ = float(opts.get("saturation") if opts.get("saturation") is not None else 1)
    if b or c != 1 or s_ != 1:
        vf.append(f"eq=brightness={b:.3f}:contrast={c:.3f}:saturation={s_:.3f}")
    grade = videofx.GRADES.get(opts.get("grade") or "none")
    if grade:
        vf.append(grade)
    if speed != 1.0:
        vf.append(f"setpts=PTS/{speed:.4f}")
    fi = float(opts.get("fade_in") or 0)
    fo = float(opts.get("fade_out") or 0)
    if fi > 0:
        vf.append(f"fade=t=in:st=0:d={fi:.2f}")
    if fo > 0:
        vf.append(f"fade=t=out:st={max(0.0, out_dur - fo):.2f}:d={fo:.2f}")
    for t in (opts.get("texts") or [])[:4]:
        if not t.get("text"):
            continue
        x, y = _POS.get(t.get("pos") or "bottom", _POS["bottom"])
        size = int(t.get("size") or 44)
        ts = float(t.get("start") or 0)
        te = float(t.get("end") or 0) or out_dur
        vf.append(
            f"drawtext=fontfile={V.FONT_REG}:text='{_esc_text(t['text'])}'"
            f":fontsize={size}:fontcolor=white:borderw=2:bordercolor=black"
            f":x={x}:y={y}:enable='between(t,{ts:.2f},{te:.2f})'")

    af = []
    mute = bool(opts.get("mute")) or not info["has_audio"]
    if not mute and not extract:
        af.append("asetpts=N/SR/TB")
        if speed != 1.0:
            af.append(_atempo_chain(speed))
        vdb = float(opts.get("volume_db") or 0)
        if vdb:
            af.append(f"volume={vdb:.1f}dB")
        ai = float(opts.get("afade_in") or 0)
        ao = float(opts.get("afade_out") or 0)
        if ai > 0:
            af.append(f"afade=t=in:st=0:d={ai:.2f}")
        if ao > 0:
            af.append(f"afade=t=out:st={max(0.0, out_dur - ao):.2f}:d={ao:.2f}")
    elif not mute and extract:
        if speed != 1.0:
            af.append(_atempo_chain(speed))
        vdb = float(opts.get("volume_db") or 0)
        if vdb:
            af.append(f"volume={vdb:.1f}dB")

    # -ss/-t are INPUT options on purpose: an output-side -t counts
    # post-filter timestamps, so a speed change would let extra input
    # through (found in VM testing: 4s at 2x came out 2.57s, not 2.0s).
    cmd = ["ffmpeg", "-y", "-v", "error", "-ss", f"{start:.3f}",
           "-t", f"{seg:.3f}", "-i", in_path]
    if extract:
        if af:
            cmd += ["-af", ",".join(af)]
        cmd += ["-vn", "-c:a", "libmp3lame", "-b:a", "192k", out_path]
    else:
        if vf:
            cmd += ["-vf", ",".join(vf)]
        if mute:
            cmd += ["-an"]
        elif af:
            cmd += ["-af", ",".join(af)]
        cmd += ["-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset",
                "medium", "-crf", "20", "-c:a", "aac", "-b:a", "192k",
                "-movflags", "+faststart", out_path]
    run_ffmpeg_progress(cmd, out_dur, progress_cb)
    return probe(out_path)


def snapshot(in_path, out_path, at_s=None):
    """Extract one poster frame as JPG (default: 25% through)."""
    info = probe(in_path)
    t = float(at_s) if at_s is not None else info["duration"] * 0.25
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", f"{t:.2f}",
                    "-i", in_path, "-frames:v", "1", "-q:v", "3",
                    out_path], check=True)
    return out_path


def concat_videos(clips, out_path, opts, progress_cb=None):
    """Join clips [{path, in, out}] into one video (the timeline).

    opts: transition ("cut"|"fade"), fade_s (dissolve length, default
    0.5), aspect (canvas, default "16:9"), height cap via aspect dims.
    Audio: clips without audio get silence so the join never breaks.
    Returns probed output info.
    """
    opts = opts or {}
    if not (2 <= len(clips) <= 6):
        raise ValueError("Join 2–6 clips")
    W, H = ASPECT_DIMS.get(opts.get("aspect") or "16:9", (1280, 720))
    trans = opts.get("transition") or "cut"
    fade = float(opts.get("fade_s") or 0.5)
    fade = min(1.5, max(0.2, fade)) if trans == "fade" else 0.0

    cmd = ["ffmpeg", "-y", "-v", "error"]
    segs = []
    for c in clips:
        info = probe(c["path"])
        st = max(0.0, float(c.get("in") or 0))
        en = float(c.get("out") or 0)
        en = en if en > st else info["duration"]
        en = min(en, info["duration"])
        if en - st < 0.3:
            raise ValueError("Each clip needs at least 0.3s selected")
        segs.append((st, en - st, info["has_audio"]))
        cmd += ["-ss", f"{st:.3f}", "-t", f"{en - st:.3f}", "-i", c["path"]]

    fc = []
    for i, (st, d, has_a) in enumerate(segs):
        fc.append(f"[{i}:v]scale={W}:{H}:force_original_aspect_ratio="
                  f"decrease,pad={W}:{H}:(ow-iw)/2:(oh-ih)/2,fps=30,"
                  f"setsar=1,setpts=PTS-STARTPTS[v{i}]")
        if has_a:
            fc.append(f"[{i}:a]aresample=44100,asetpts=N/SR/TB[a{i}]")
        else:
            fc.append(f"anullsrc=channel_layout=stereo:sample_rate=44100,"
                      f"atrim=0:{d:.3f},asetpts=N/SR/TB[a{i}]")
    total = sum(d for _, d, _ in segs)
    if fade:
        total -= fade * (len(segs) - 1)
        vprev, aprev, off = "v0", "a0", segs[0][1] - fade
        for i in range(1, len(segs)):
            vl, al = (f"vx{i}", f"ax{i}") if i < len(segs) - 1 else ("vout", "aout")
            fc.append(f"[{vprev}][v{i}]xfade=transition=fade:duration="
                      f"{fade:.2f}:offset={off:.3f}[{vl}]")
            fc.append(f"[{aprev}][a{i}]acrossfade=d={fade:.2f}[{al}]")
            vprev, aprev = vl, al
            if i < len(segs) - 1:
                off += segs[i][1] - fade
        vmap, amap = "vout", "aout"
    else:
        ins = "".join(f"[v{i}][a{i}]" for i in range(len(segs)))
        fc.append(f"{ins}concat=n={len(segs)}:v=1:a=1[vout][aout]")
        vmap, amap = "vout", "aout"
    cmd += ["-filter_complex", ";".join(fc), "-map", f"[{vmap}]",
            "-map", f"[{amap}]", "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-preset", "medium", "-crf", "20", "-c:a", "aac", "-b:a",
            "192k", "-movflags", "+faststart", out_path]
    run_ffmpeg_progress(cmd, total, progress_cb)
    return probe(out_path)
