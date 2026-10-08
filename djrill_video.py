"""DJRILL video builder — music videos based on inputs.
Two modes:
  lyric       audio + timed lyric lines + audio-reactive visuals -> MP4.
              Kinetic-typography video. No performer is faked: when no
              performance footage is supplied, the video is visuals + words.
  performance artist footage + audio + lyrics -> edited music video.
              Cuts the artist's REAL performance to the track with lyric
              overlays. Requires the artist's own video file(s).
  selfie      artist photo(s) + audio + lyrics -> stylized music video.
              Ken Burns motion, cuts on lyric-section changes, lyric
              overlays. No synthetic performer — just the artist's photo.

Usage:
    python3 djrill_video.py lyric --demo --out demo_lyric_video.mp4
    python3 djrill_video.py lyric --audio song.mp3 --lyrics lyrics.json --out out.mp4
    python3 djrill_video.py performance --footage me1.mp4 me2.mp4 \\
        --audio song.mp3 --lyrics lyrics.json --out music_video.mp4
    python3 djrill_video.py selfie --photos me1.jpg me2.jpg \\
        --audio song.mp3 --lyrics lyrics.json --out music_video.mp4
Lyrics JSON: [{"start": s, "end": s, "section": "...", "line": "..."}, ...]
"""
import sys, os, argparse, json, subprocess, shlex
import numpy as np

SR = 44100
W, H, FPS = 1280, 720, 30
FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
FONT_REG = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"


def load_audio_mono(path):
    from scipy.io.wavfile import read as wav_read
    if path.lower().endswith(".wav"):
        sr, d = wav_read(path)
        return _to_mono(d, sr)
    # everything else (mp3/m4a/ogg/flac/...) via ffmpeg
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", path, "-ac", "1",
                          "-ar", str(SR), "-f", "f32le", "-"],
                         capture_output=True, check=True).stdout
    return np.frombuffer(raw, dtype=np.float32).astype(np.float64)


def _to_mono(d, sr):
    if d.dtype == np.int16:
        d = d.astype(np.float64) / 32768.0
    elif d.dtype == np.int32:
        d = d.astype(np.float64) / 2147483648.0
    else:
        d = d.astype(np.float64)
    if d.ndim > 1:
        d = d.mean(axis=1)
    if sr != SR:
        from scipy import signal
        d = signal.resample(d, int(len(d) * SR / sr))
    return d


def spectrum_frames(x, fps=FPS, n_bands=48):
    """Magnitude spectrogram resampled to video frame rate, log-scaled."""
    from scipy import signal as _sig
    f, t, Z = _sig.stft(x, fs=SR, nperseg=2048, noverlap=1536)
    mag = np.abs(Z)
    # mel-ish log banding
    edges = np.logspace(np.log10(40), np.log10(14000), n_bands + 1)
    bands = np.zeros((n_bands, mag.shape[1]))
    for i in range(n_bands):
        m = (f >= edges[i]) & (f < edges[i+1])
        if m.any():
            bands[i] = mag[m].mean(axis=0)
    bands = np.log1p(bands * 8)
    bands /= max(1e-9, bands.max())
    # resample time axis to fps
    n_out = int(len(x) / SR * fps)
    idx = (np.linspace(0, 1, n_out) * (bands.shape[1] - 1)).astype(int)
    return bands[:, idx].T  # (frames, bands)


def beat_envelope(x, fps=FPS):
    from scipy import signal as _sig
    win, hop = 1024, 512
    nfr = max(1, (len(x) - win) // hop)
    env = np.zeros(nfr); prev = None
    for i in range(nfr):
        fr = x[i*hop:i*hop+win] * np.hanning(win)
        mg = np.abs(np.fft.rfft(fr))
        if prev is not None:
            env[i] = np.sum(np.maximum(0, mg - prev))
        prev = mg
    env /= max(1e-9, env.max())
    n_out = int(len(x) / SR * fps)
    return np.interp(np.linspace(0, 1, n_out), np.linspace(0, 1, nfr), env)


def drawtext_escape(s):
    """Red-team mandated: neutralize drawtext metachars in lyric text.
    Escapes backslash first, then quotes/colons; strips % before { (which
    would trigger drawtext expansion); removes newlines and control chars
    so text= can never break out of its filter."""
    import re
    s = str(s)
    s = s.replace("\\", "\\\\")
    s = s.replace("'", "\\'")
    s = s.replace(":", "\\:")
    s = re.sub(r"%(?=\{)", "", s)
    s = "".join(c for c in s if c == " " or (ord(c) >= 32 and ord(c) != 127))
    return s.strip()


def render_lyric_video(audio_path, events, out_path, title="DJRILL",
                       progress_cb=None):
    from PIL import Image, ImageDraw, ImageFont
    print("[VIDEO] loading audio...")
    x = load_audio_mono(audio_path)
    dur = len(x) / SR
    n_frames = int(dur * FPS)
    print(f"[VIDEO] {dur:.1f}s -> {n_frames} frames; computing visuals...")
    spec = spectrum_frames(x)
    beat = beat_envelope(x)
    f_title = ImageFont.truetype(FONT, 64)
    f_line = ImageFont.truetype(FONT, 54)
    f_small = ImageFont.truetype(FONT_REG, 30)

    cmd = ["ffmpeg", "-y", "-v", "error",
           "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}",
           "-r", str(FPS), "-i", "-",
           "-i", audio_path,
           "-map", "0:v", "-map", "1:a",
           "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "medium", "-crf", "20",
           "-c:a", "aac", "-b:a", "192k", "-shortest", out_path]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    ev_idx = 0
    for fi in range(n_frames):
        t = fi / FPS
        while ev_idx + 1 < len(events) and events[ev_idx + 1]["start"] <= t:
            ev_idx += 1
        ev = events[ev_idx] if events and events[ev_idx]["start"] <= t <= events[ev_idx]["end"] else None
        pulse = float(beat[fi]) if fi < len(beat) else 0.0
        img = Image.new("RGB", (W, H), (8, 10, 18))
        dr = ImageDraw.Draw(img)
        # pulsing ring
        cx, cy = W // 2, 300
        r = int(120 + pulse * 60)
        dr.ellipse([cx-r, cy-r, cx+r, cy+r], outline=(0, 200, 200), width=6)
        dr.ellipse([cx-r+18, cy-r+18, cx+r-18, cy+r-18], outline=(120, 50, 180), width=3)
        # spectrum bars along the bottom
        n_b = spec.shape[1]
        bw = W / n_b
        for i in range(n_b):
            v = float(spec[fi, i]) if fi < spec.shape[0] else 0.0
            bh = int(v * 220)
            x0 = int(i * bw)
            dr.rectangle([x0, H-bh, x0+int(bw*0.7), H], fill=(0, int(120+120*v), 200))
        # lyric line
        if ev:
            line = ev["line"]
            tb = dr.textbbox((0, 0), line, font=f_line)
            dr.text(((W-(tb[2]-tb[0]))/2, 480), line, font=f_line, fill=(255, 255, 255))
            sec = ev.get("section", "")
            dr.text((40, 30), sec, font=f_small, fill=(0, 220, 220))
        dr.text((40, H-60), title, font=f_small, fill=(150, 150, 170))
        dr.text((W-460, H-60), "AI draft lyrics - artist decides", font=f_small, fill=(110, 110, 130))
        proc.stdin.write(img.tobytes())
        if fi % 600 == 0:
            print(f"[VIDEO] frame {fi}/{n_frames}", flush=True)
        if progress_cb and fi % 30 == 0:
            progress_cb(fi / n_frames)
    proc.stdin.close()
    proc.wait()
    print(f"[VIDEO] wrote {out_path}")


def _probe_duration(path):
    return float(subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1", path],
        capture_output=True, text=True).stdout.split("=")[1])


def _run_ffmpeg_progress(cmd, total_dur, progress_cb=None):
    """Run an ffmpeg command list; report 0..1 progress via -progress polling.

    cmd must end with the output path. total_dur is the expected output
    duration in seconds (for the progress fraction)."""
    import time
    prog_path = "/tmp/djrill_vprog_%d.txt" % os.getpid()
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
            time.sleep(0.5)
    finally:
        try:
            os.remove(prog_path)
        except OSError:
            pass
    if proc.returncode != 0:
        raise subprocess.CalledProcessError(proc.returncode, full)
    if progress_cb:
        progress_cb(1.0)


def render_performance_video(footage, audio_path, events, out_path, title="DJRILL",
                             progress_cb=None):
    """Cut the artist's real footage to the track. No synthetic performer."""
    # chain: scale/crop footage, gentle zoom, lyric overlays, grade
    draw = []
    for e in events:
        txt = drawtext_escape(e["line"])
        draw.append(
            f"drawtext=fontfile={FONT}:text='{txt}':fontsize=44:fontcolor=white:"
            f"x=(w-text_w)/2:y=h-160:enable='between(t\\,{e['start']:.2f}\\,{e['end']:.2f})':"
            f"box=1:boxcolor=black@0.55:boxborderw=12")
    vf = ("scale=1280:720:force_original_aspect_ratio=increase,crop=1280:720,"
          "eq=contrast=1.08:saturation=1.15,")
    vf += ",".join(draw) + ",format=yuv420p"
    # loop the artist's footage so it always covers the full track;
    # -shortest trims the result to the audio length
    fin = ["-stream_loop", "-1", "-i", footage[0]]
    for f in footage[1:]:
        fin += ["-i", f]
    fin += ["-i", audio_path]
    dur = _probe_duration(audio_path)
    cmd = (["ffmpeg", "-y", "-v", "error"] + fin +
           ["-filter_complex",
            f"[0:v]{vf}[v]",
            "-map", "[v]", f"-map", f"{len(footage)}:a",
            "-c:v", "libx264", "-preset", "medium", "-crf", "20",
            "-c:a", "aac", "-b:a", "192k",
            "-t", f"{dur:.2f}", out_path])
    print("[VIDEO] cutting performance footage...")
    _run_ffmpeg_progress(cmd, dur, progress_cb)
    print(f"[VIDEO] wrote {out_path}")


def render_selfie_video(photos, audio_path, events, out_path, title="DJRILL",
                        progress_cb=None, kb_direction="auto"):
    """Selfie music video: the artist's own photos, slow Ken Burns motion,
    cuts on lyric-section changes with crossfades, lyric overlays, grade.
    No synthetic performer — the photo IS the artist.

    kb_direction: auto | in | out | left | right | up | down — #73.

    Duration math: each photo is fed as ONE still frame; zoompan emits
    exactly N frames for it (N = segment seconds * FPS), so every segment
    is exactly its intended length. The xfade chain consumes 0.5s per
    transition, so the final segment is lengthened by 0.5*(n-1) to make the
    finished video exactly the audio length."""
    dur = _probe_duration(audio_path)
    # segment boundaries from lyric sections (intro/outro cover the edges)
    bounds = [0.0]
    if events:
        secs, cur = [], None
        for e in events:
            s = e.get("section") or ""
            if s != cur:
                if cur is not None:
                    secs.append((cur, s0, e["end"]))
                cur, s0 = s, e["start"]
        if cur is not None:
            secs.append((cur, s0, events[-1]["end"]))
        for _, a, b in secs:
            if a - bounds[-1] > 1.0:
                bounds.append(a)
        bounds.append(dur)
    else:
        n = len(photos)
        bounds = [i * dur / n for i in range(n)] + [dur]
    segs = [(bounds[i], bounds[i + 1]) for i in range(len(bounds) - 1)]
    # drop slivers, keep photo cycling
    segs = [(a, b) for a, b in segs if b - a > 0.6] or [(0.0, dur)]
    # compensate the 0.5s each xfade consumes: extend the final segment so
    # the finished video lands exactly on the audio duration
    if len(segs) > 1:
        comp = 0.5 * (len(segs) - 1)
        segs[-1] = (segs[-1][0], segs[-1][1] + comp)

    fin, fc = [], []
    labels = []
    for i, (a, b) in enumerate(segs):
        d = b - a
        nframes = max(2, int(round(d * FPS)))
        # ONE still frame per photo: zoompan then emits exactly nframes
        # (feeding a looped stream would multiply: nframes per input frame)
        fin += ["-i", photos[i % len(photos)]]
        # #73 Ken Burns direction control (auto = original alternate in/out)
        if kb_direction == "auto":
            d = "in" if i % 2 == 0 else "out"
        else:
            d = kb_direction if kb_direction in (
                "in", "out", "left", "right", "up", "down") else "in"
        if d == "in":
            z, xp, yp = f"1+0.14*on/{nframes}", "iw/2-(iw/zoom/2)", "ih/2-(ih/zoom/2)"
        elif d == "out":
            z, xp, yp = f"1.14-0.14*on/{nframes}", "iw/2-(iw/zoom/2)", "ih/2-(ih/zoom/2)"
        elif d == "left":
            z, xp, yp = "1.14", f"(iw-iw/zoom)*on/{nframes}", "ih/2-(ih/zoom/2)"
        elif d == "right":
            z, xp, yp = "1.14", f"(iw-iw/zoom)*(1-on/{nframes})", "ih/2-(ih/zoom/2)"
        elif d == "up":
            z, xp, yp = "1.14", "iw/2-(iw/zoom/2)", f"(ih-ih/zoom)*on/{nframes}"
        else:  # down
            z, xp, yp = "1.14", "iw/2-(iw/zoom/2)", f"(ih-ih/zoom)*(1-on/{nframes})"
        fc.append(
            f"[{i}:v]scale=2560:1440:force_original_aspect_ratio=increase,"
            f"crop=2560:1440,zoompan=z='{z}':d={nframes}:"
            f"x='{xp}':y='{yp}':s={W}x{H},"
            f"fps={FPS},setpts=PTS-STARTPTS[v{i}]")
        labels.append(f"[v{i}]")
    fin += ["-i", audio_path]
    # crossfade chain: offset_k = (cumulative seconds before shot k) - 0.5*k
    cur_v = labels[0]
    for i in range(1, len(labels)):
        off = (segs[i - 1][1] - segs[0][0]) - 0.5 * i
        fc.append(f"{cur_v}{labels[i]}xfade=transition=fade:duration=0.5:"
                  f"offset={off:.2f}[x{i}]")
        cur_v = f"[x{i}]"
    # lyric overlays + grade
    draw = []
    for e in events or []:
        txt = drawtext_escape(e["line"])
        draw.append(
            f"drawtext=fontfile={FONT}:text='{txt}':fontsize=46:fontcolor=white:"
            f"x=(w-text_w)/2:y=h-150:enable='between(t\\,{e['start']:.2f}\\,{e['end']:.2f})':"
            f"box=1:boxcolor=black@0.55:boxborderw=12")
    vf = (cur_v + "eq=contrast=1.06:saturation=1.18,vignette=PI/5,"
          + ",".join(draw) + ",format=yuv420p[v]")
    fc.append(vf)
    aidx = len(segs)
    cmd = (["ffmpeg", "-y", "-v", "error"] + fin +
           ["-filter_complex", ";".join(fc),
            "-map", "[v]", "-map", f"{aidx}:a",
            "-c:v", "libx264", "-preset", "medium", "-crf", "20",
            "-c:a", "aac", "-b:a", "192k", "-shortest", out_path])
    print(f"[VIDEO] selfie video: {len(segs)} shots, target {dur:.1f}s...")
    _run_ffmpeg_progress(cmd, dur, progress_cb)
    print(f"[VIDEO] wrote {out_path}")


def capture_selfie(out_path):
    """Take a selfie with the phone's front camera (Termux:API on-device)."""
    import shutil
    if not shutil.which("termux-camera-photo"):
        raise RuntimeError("termux-camera-photo not available — take a selfie "
                           "with the camera app and pass --photos <file>")
    subprocess.run(["termux-camera-photo", "-c", "1", out_path], check=True)
    return out_path


def demo(out_path):
    """Demo lyric video: fresh 48-bar beat + AI draft lyrics (seed-matched)."""
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import djrill_lyrics as L
    sys.path.insert(0, "/tmp/stubs")
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "djrill_v68", os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                   "app", "djrill_mixer_v68.py"))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    m.BASE_DIR = "/tmp/djrill_nomedia/"
    m.SAMPLE_BASE_DIR = "/tmp/djrill_nomedia/Ai_music_samples"
    seed, bpm, genre = 7, 90, "HipHop"
    print("[VIDEO] rendering demo beat (48 bars)...")
    g = m.Generator(seed=seed, genre=genre, hook_name="Hook A")
    g.tempo = float(bpm); g.current_global_tempo = float(bpm)
    song = m.SongStructure(num_verses=3, num_hooks=4)
    chunks = []
    for bar in range(48):
        sname, _, bis = song.get_section_info(bar)
        g.synthesize_bar_audio(sname, bis)
        chunks.append(g.current_bar_audio_buffer)
    beat = np.concatenate(chunks, axis=0)
    tmp_wav = "/tmp/djrill_demo_beat.wav"
    from scipy.io.wavfile import write as wav_write
    wav_write(tmp_wav, SR, (np.clip(beat, -1, 1) * 32767).astype(np.int16))
    print("[VIDEO] generating draft lyrics...")
    song_l = L.generate_song_lyrics(seed, genre)
    tl = L.lyric_timeline(song_l, bpm)[:24]  # verse1 (16) + hook (8) = 48 bars
    events = [{"start": s, "end": e, "section": sec, "line": ln}
              for s, e, sec, ln in tl]
    with open("/tmp/djrill_demo_lyrics.json", "w") as f:
        json.dump(events, f, indent=1)
    render_lyric_video(tmp_wav, events, out_path, title=f"DJRILL {genre} (demo)")


def main():
    ap = argparse.ArgumentParser(description="DJRILL video builder")
    sub = ap.add_subparsers(dest="mode", required=True)
    a = sub.add_parser("lyric")
    a.add_argument("--audio"); a.add_argument("--lyrics"); a.add_argument("--out", required=True)
    a.add_argument("--title", default="DJRILL"); a.add_argument("--demo", action="store_true")
    b = sub.add_parser("performance")
    b.add_argument("--footage", nargs="+", required=True)
    b.add_argument("--audio", required=True); b.add_argument("--lyrics", required=True)
    b.add_argument("--out", required=True); b.add_argument("--title", default="DJRILL")
    c = sub.add_parser("selfie")
    c.add_argument("--photos", nargs="*", default=[])
    c.add_argument("--take", action="store_true",
                   help="capture a selfie with the front camera (Termux:API)")
    c.add_argument("--audio", required=True); c.add_argument("--lyrics", required=True)
    c.add_argument("--out", required=True); c.add_argument("--title", default="DJRILL")
    args = ap.parse_args()
    if args.mode == "lyric":
        if args.demo:
            demo(args.out)
        else:
            events = json.load(open(args.lyrics))
            render_lyric_video(args.audio, events, args.out, title=args.title)
    elif args.mode == "performance":
        events = json.load(open(args.lyrics))
        render_performance_video(args.footage, args.audio, events, args.out, title=args.title)
    elif args.mode == "selfie":
        photos = list(args.photos)
        if args.take:
            photos.insert(0, capture_selfie("/tmp/djrill_selfie.jpg"))
        if not photos:
            raise SystemExit("selfie mode needs --photos <file...> and/or --take")
        events = json.load(open(args.lyrics))
        render_selfie_video(photos, args.audio, events, args.out, title=args.title)


if __name__ == "__main__":
    main()
