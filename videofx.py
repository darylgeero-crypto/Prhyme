"""DJRILL video FX — new templates, grades, overlays, and utilities.

Additive to djrill_video.py. Templates render PIL frames piped to FFmpeg
(same pattern as render_lyric_video). Grades/overlays use FFmpeg filters.
"""
import os
import subprocess

import numpy as np

import djrill_video as V

SR = 44100
FPS = 30

# 69. aspect ratio presets (W, H)
ASPECTS = {
    "16:9": (1280, 720),
    "9:16": (720, 1280),
    "1:1": (720, 720),
}

# 65. color grade presets -> FFmpeg eq filter args
GRADES = {
    "none": None,
    "warm": "eq=contrast=1.05:saturation=1.25:brightness=0.02",
    "cold": "eq=contrast=1.05:saturation=0.9:brightness=0.0,colorbalance=bs=0.15:bm=0.08",
    "bw": "hue=s=0,eq=contrast=1.1",
    "vintage": "eq=contrast=0.95:saturation=0.7:brightness=0.03,colorbalance=rs=0.1:gs=0.05",
    "neon": "eq=contrast=1.15:saturation=1.6",
}


def _fonts():
    from PIL import ImageFont
    return (ImageFont.truetype(V.FONT, 64),
            ImageFont.truetype(V.FONT, 54),
            ImageFont.truetype(V.FONT_REG, 30))


def _pipe_video(out_path, audio_path, n_frames, W, H, frame_fn,
                progress_cb=None, crf=20, preset="medium", vf=None,
                fast=False):
    """103. fast=True uses ultrafast preset for quick previews."""
    if fast:
        preset, crf = "ultrafast", 26
    cmd = ["ffmpeg", "-y", "-v", "error",
           "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}",
           "-r", str(FPS), "-i", "-",
           "-i", audio_path,
           "-map", "0:v", "-map", "1:a",
           "-c:v", "libx264", "-pix_fmt", "yuv420p",
           "-preset", preset, "-crf", str(crf)]
    if vf:
        cmd += ["-vf", vf]
    cmd += ["-c:a", "aac", "-b:a", "192k", "-shortest", out_path]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    for fi in range(n_frames):
        proc.stdin.write(frame_fn(fi).tobytes())
        if progress_cb and fi % 30 == 0:
            progress_cb(fi / n_frames)
    proc.stdin.close()
    proc.wait()
    if proc.returncode != 0:
        raise RuntimeError("FFmpeg video encode failed")


def render_waveform_video(audio_path, events, out_path, title="DJRILL",
                          bg="rings", aspect="16:9", progress_cb=None,
                          fast=False):
    """61. Waveform visualizer: scrolling waveform + lyrics.
    72. bg: rings | bars | wave (audio-reactive background choice)."""
    from PIL import Image, ImageDraw
    W, H = ASPECTS.get(aspect, ASPECTS["16:9"])
    x = V.load_audio_mono(audio_path)
    dur = len(x) / SR
    n_frames = int(dur * FPS)
    spec = V.spectrum_frames(x)
    beat = V.beat_envelope(x)
    f_title, f_line, f_small = _fonts()

    # precompute waveform overview
    n_ov = 1200
    idx = np.linspace(0, len(x), n_ov + 1).astype(int)
    ov = np.array([np.max(np.abs(x[idx[i]:idx[i + 1]])) if idx[i+1] > idx[i] else 0
                   for i in range(n_ov)])
    ev_idx = 0

    def frame(fi):
        nonlocal ev_idx
        t = fi / FPS
        while ev_idx + 1 < len(events) and events[ev_idx + 1]["start"] <= t:
            ev_idx += 1
        ev = (events[ev_idx] if events and
              events[ev_idx]["start"] <= t <= events[ev_idx]["end"] else None)
        pulse = float(beat[fi]) if fi < len(beat) else 0.0
        img = Image.new("RGB", (W, H), (8, 10, 18))
        dr = ImageDraw.Draw(img)
        cx, cy = W // 2, H // 2 - 40
        if bg == "rings":
            r = int(120 + pulse * 60)
            dr.ellipse([cx-r, cy-r, cx+r, cy+r], outline=(0, 200, 200), width=6)
            dr.ellipse([cx-r+18, cy-r+18, cx+r-18, cy+r-18],
                       outline=(120, 50, 180), width=3)
        elif bg == "bars":
            n_b = spec.shape[1]
            bw = W / n_b
            for i in range(n_b):
                v = float(spec[fi, i]) if fi < spec.shape[0] else 0.0
                bh = int(v * 260)
                x0 = int(i * bw)
                dr.rectangle([x0, H-bh, x0+int(bw*0.7), H],
                             fill=(0, int(120+120*v), 200))
        else:  # wave: scrolling waveform overview
            pos = int(t / dur * n_ov)
            for i in range(W):
                oi = max(0, min(n_ov - 1, pos - W // 2 + i))
                h = int(ov[oi] * 160 * (1 + pulse * 0.5))
                dr.line([i, cy-h, i, cy+h], fill=(0, 200, 220))
            dr.line([W//2, cy-200, W//2, cy+200], fill=(255, 45, 120), width=2)
        if ev:
            line = ev["line"]
            tb = dr.textbbox((0, 0), line, font=f_line)
            dr.text(((W-(tb[2]-tb[0]))/2, H-160), line, font=f_line,
                    fill=(255, 255, 255))
        dr.text((40, 30), title, font=f_small, fill=(150, 150, 170))
        return img

    _pipe_video(out_path, audio_path, n_frames, W, H, frame, progress_cb,
                fast=fast)


def render_collage_video(photos, audio_path, events, out_path, title="DJRILL",
                         aspect="16:9", progress_cb=None):
    """62. Photo collage grid: 2x2 tiles crossfading between photo sets."""
    from PIL import Image, ImageDraw
    W, H = ASPECTS.get(aspect, ASPECTS["16:9"])
    x = V.load_audio_mono(audio_path)
    dur = len(x) / SR
    n_frames = int(dur * FPS)
    beat = V.beat_envelope(x)
    f_title, f_line, f_small = _fonts()

    from PIL import Image as I
    imgs = []
    for p in photos[:8]:
        try:
            im = I.open(p).convert("RGB")
            imgs.append(im)
        except Exception:
            continue
    if not imgs:
        raise ValueError("No readable photos")
    # 74. auto-enhance: mild contrast/saturation lift
    from PIL import ImageEnhance
    imgs = [ImageEnhance.Color(ImageEnhance.Contrast(im).enhance(1.15)).enhance(1.12)
            for im in imgs]

    tw, th = W // 2, H // 2
    tiles = []
    for im in imgs:
        r = max(tw / im.width, th / im.height)
        im2 = im.resize((int(im.width*r)+1, int(im.height*r+1)), I.LANCZOS)
        l, t_ = (im2.width-tw)//2, (im2.height-th)//2
        tiles.append(im2.crop((l, t_, l+tw, t_+th)))
    # 64. transitions: crossfade tile sets every 4s
    set_dur = 4 * FPS
    n_sets = max(1, (n_frames // set_dur) + 1)

    def frame(fi):
        s0 = (fi // set_dur) % max(1, (len(tiles) + 3) // 4)
        s1 = (s0 + 1) % max(1, (len(tiles) + 3) // 4)
        local = fi % set_dur
        alpha = min(1.0, local / (0.5 * FPS)) if local < set_dur - 0.5*FPS else 1.0
        # fade out at end of set
        if local > set_dur - 0.5 * FPS:
            alpha = max(0.0, (set_dur - local) / (0.5 * FPS))
        img = Image.new("RGB", (W, H), (5, 5, 10))
        for q in range(4):
            i0 = (s0 * 4 + q) % len(tiles)
            i1 = (s1 * 4 + q) % len(tiles)
            a = tiles[i0].copy()
            if alpha < 1.0:
                a = Image.blend(a, tiles[i1], 1.0 - alpha)
            img.paste(a, ((q % 2) * tw, (q // 2) * th))
        dr = ImageDraw.Draw(img)
        pulse = float(beat[fi]) if fi < len(beat) else 0.0
        # vignette pulse border
        b = int(4 + pulse * 6)
        dr.rectangle([0, 0, W-1, H-1], outline=(0, 220, 220), width=b)
        dr.text((40, 30), title, font=f_small, fill=(255, 255, 255))
        return img

    _pipe_video(out_path, audio_path, n_frames, W, H, frame, progress_cb)


def render_minimal_video(audio_path, events, out_path, title="DJRILL",
                         aspect="16:9", progress_cb=None):
    """63. Minimal typographic: huge kinetic type on black."""
    from PIL import Image, ImageDraw
    W, H = ASPECTS.get(aspect, ASPECTS["16:9"])
    x = V.load_audio_mono(audio_path)
    dur = len(x) / SR
    n_frames = int(dur * FPS)
    beat = V.beat_envelope(x)
    from PIL import ImageFont
    f_big = ImageFont.truetype(V.FONT, 96)
    f_small = ImageFont.truetype(V.FONT_REG, 30)
    ev_idx = 0

    def frame(fi):
        nonlocal ev_idx
        t = fi / FPS
        while ev_idx + 1 < len(events) and events[ev_idx + 1]["start"] <= t:
            ev_idx += 1
        ev = (events[ev_idx] if events and
              events[ev_idx]["start"] <= t <= events[ev_idx]["end"] else None)
        pulse = float(beat[fi]) if fi < len(beat) else 0.0
        img = Image.new("RGB", (W, H), (0, 0, 0))
        dr = ImageDraw.Draw(img)
        # kinetic: line scales with the beat
        if ev:
            line = ev["line"]
            size = 64 + int(pulse * 28)
            try:
                f = ImageFont.truetype(V.FONT, size)
            except Exception:
                f = f_big
            tb = dr.textbbox((0, 0), line, font=f)
            tw = tb[2] - tb[0]
            # word-by-word reveal
            words = line.split()
            frac = min(1.0, (t - ev["start"]) / max(0.5, ev["end"] - ev["start"]))
            shown = " ".join(words[:max(1, int(len(words) * frac))])
            tb2 = dr.textbbox((0, 0), shown, font=f)
            dr.text(((W-(tb2[2]-tb2[0]))/2, H/2-60), shown, font=f,
                    fill=(255, 255, 255))
            sec = ev.get("section", "")
            dr.text((40, 40), sec, font=f_small, fill=(0, 220, 220))
        else:
            tb = dr.textbbox((0, 0), title, font=f_big)
            dr.text(((W-(tb[2]-tb[0]))/2, H/2-60), title, font=f_big,
                    fill=(120, 120, 140))
        # 67. progress bar overlay
        pw = int(W * 0.8)
        px0 = (W - pw) // 2
        dr.rectangle([px0, H-50, px0+pw, H-44], fill=(40, 40, 50))
        dr.rectangle([px0, H-50, px0+int(pw*t/dur), H-44], fill=(0, 220, 220))
        return img

    _pipe_video(out_path, audio_path, n_frames, W, H, frame, progress_cb)


def apply_grade(in_path, out_path, grade="warm"):
    """65. Apply a color grade preset via FFmpeg."""
    vf = GRADES.get(grade)
    if not vf:
        # no-op copy
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", in_path,
                        "-c", "copy", out_path], check=True)
        return out_path
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", in_path,
                    "-vf", vf, "-c:a", "copy", out_path], check=True)
    return out_path


def add_watermark(in_path, out_path, text="DJRILL"):
    """68. Logo/watermark overlay (bottom-right)."""
    esc = text.replace(":", "\\:").replace("'", "")
    vf = (f"drawtext=fontfile={V.FONT_REG}:text='{esc}':fontsize=28:"
          f"fontcolor=white@0.7:x=w-text_w-30:y=h-text_h-30")
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", in_path,
                    "-vf", vf, "-c:a", "copy", out_path], check=True)
    return out_path


def add_progress_bar(in_path, out_path):
    """67. Burn a progress bar into an existing video."""
    vf = ("drawbox=x=0:y=ih-8:w=iw*t/DURATION:h=8:color=cyan@0.9:t=fill")
    # DURATION via ffprobe
    dur = V._probe_duration(in_path)
    vf = vf.replace("DURATION", f"{dur:.2f}")
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", in_path,
                    "-vf", vf, "-c:a", "copy", out_path], check=True)
    return out_path


def _title_card(text, dur_s, W, H, out_path):
    """70/71. Render a static title/outro card."""
    from PIL import Image, ImageDraw, ImageFont
    img = Image.new("RGB", (W, H), (8, 10, 18))
    dr = ImageDraw.Draw(img)
    try:
        f = ImageFont.truetype(V.FONT, 72)
    except Exception:
        f = ImageFont.load_default()
    tb = dr.textbbox((0, 0), text, font=f)
    dr.text(((W-(tb[2]-tb[0]))/2, H/2-40), text, font=f, fill=(255, 255, 255))
    img.save(out_path)


def prepend_title_card(video_path, out_path, text, card_s=2.0):
    """70. Intro title card prepended to the video."""
    dur = V._probe_duration(video_path)
    # probe dimensions
    info = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height", "-of", "csv=p=0",
         video_path], capture_output=True, text=True).stdout.strip()
    W, H = (int(v) for v in info.split(",")[:2])
    card_png = out_path + ".card.png"
    _title_card(text, card_s, W, H, card_png)
    card_mp4 = out_path + ".card.mp4"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-loop", "1",
                    "-t", str(card_s), "-i", card_png,
                    "-f", "lavfi", "-t", str(card_s), "-i", "anullsrc=r=44100:cl=stereo",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p",
                    "-c:a", "aac", "-shortest", card_mp4], check=True)
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", card_mp4,
                    "-i", video_path, "-filter_complex",
                    "[0:v][0:a][1:v][1:a]concat=n=2:v=1:a=1",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p",
                    "-c:a", "aac", out_path], check=True)
    for p in (card_png, card_mp4):
        try:
            os.remove(p)
        except OSError:
            pass
    return out_path


def append_outro_card(video_path, out_path, text="Thanks for watching"):
    """71. Outro end card appended."""
    return prepend_title_card(video_path, out_path, text)


def convert_aspect(in_path, out_path, aspect="9:16"):
    """69. Convert to 16:9 / 9:16 / 1:1 (pad with blur)."""
    W, H = ASPECTS.get(aspect, ASPECTS["16:9"])
    vf = (f"split[a][b];[a]scale={W}:{H}:force_original_aspect_ratio=increase,"
          f"crop={W}:{H},gblur=sigma=40[bg];"
          f"[b]scale={W}:{H}:force_original_aspect_ratio=decrease[fg];"
          f"[bg][fg]overlay=(W-w)/2:(H-h)/2,scale={W}:{H}")
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", in_path,
                    "-vf", vf, "-c:a", "copy", out_path], check=True)
    return out_path


def make_thumbnail(video_path, out_path, at_s=None):
    """75. Extract a thumbnail JPG."""
    dur = V._probe_duration(video_path)
    t = at_s if at_s is not None else dur * 0.25
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", str(t),
                    "-i", video_path, "-frames:v", "1", "-q:v", "3",
                    out_path], check=True)
    return out_path


def burn_subtitles(video_path, srt_path, out_path):
    """66. Burn an SRT subtitle file into the video."""
    vf = f"subtitles={srt_path.replace(':', chr(92)+':')}"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", video_path,
                    "-vf", vf, "-c:a", "copy", out_path], check=True)
    return out_path


def events_to_srt(events, srt_path):
    """66. Convert lyric events to SRT for subtitle burn-in."""
    def ts(s):
        h, m = int(s // 3600), int(s % 3600 // 60)
        sec = s % 60
        return f"{h:02d}:{m:02d}:{sec:06.3f}".replace(".", ",")
    with open(srt_path, "w") as f:
        for i, e in enumerate(events, 1):
            f.write(f"{i}\n{ts(e['start'])} --> {ts(e['end'])}\n"
                    f"{e.get('line','')}\n\n")
    return srt_path
