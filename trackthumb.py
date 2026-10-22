# trackthumb.py — automatic track thumbnails from metadata (2026-10-22,
# Daryl's order: "Prhyme should automatically generate thumbnails for
# tracks based on meta data").
#
# For any audio file this returns a cached 288x288 JPEG cover:
#   1. embedded cover art (ID3 APIC / FLAC picture) if the file carries it,
#   2. otherwise a generated cover built from the track's metadata —
#      title/artist/genre/BPM from tags when present, genre guessed from
#      the name, a genre-coloured gradient, the track's REAL waveform
#      (decoded peaks), its duration, and a small Prhyme tag.
# Everything is best-effort: any failure returns None and the listing
# simply shows no image. Results are cached next to the outputs and
# regenerated only when the source file is newer.

import hashlib
import os
import re
import struct

SIZE = 288

GENRE_PALETTES = [
    (("trap",), ((26, 10, 46), (122, 44, 191))),
    (("drill",), ((8, 8, 12), (70, 90, 140))),
    (("boom", "east"), ((24, 18, 8), (140, 100, 30))),
    (("lofi", "lo-fi", "chill"), ((30, 24, 38), (96, 74, 110))),
    (("house", "edm", "dance", "techno"), ((6, 26, 34), (16, 120, 140))),
    (("dnb", "drum and bass", "jungle"), ((8, 30, 16), (24, 130, 70))),
    (("jazz",), ((28, 16, 34), (150, 90, 40))),
    (("blues",), ((10, 16, 34), (40, 80, 150))),
    (("rock", "metal", "punk"), ((30, 8, 8), (150, 40, 30))),
    (("soul", "r&b", "rnb", "funk"), ((34, 14, 24), (170, 80, 60))),
    (("gospel",), ((30, 26, 10), (170, 140, 50))),
    (("classical", "piano"), ((16, 16, 22), (90, 90, 120))),
    (("afro",), ((30, 18, 6), (180, 110, 30))),
    (("reggae", "dancehall"), ((10, 28, 12), (60, 140, 60))),
    (("country",), ((30, 22, 12), (150, 110, 60))),
    (("phonk",), ((20, 6, 26), (90, 40, 140))),
    (("west",), ((26, 14, 6), (170, 100, 40))),
    (("pop",), ((28, 10, 30), (170, 60, 130))),
]
DEFAULT_PALETTE = ((16, 10, 30), (105, 60, 190))  # Prhyme purple


def _palette_for(text):
    t = (text or "").lower()
    for keys, pal in GENRE_PALETTES:
        if any(k in t for k in keys):
            return pal
    return DEFAULT_PALETTE


# ---------------- embedded metadata (ID3v2 / FLAC) ----------------

def _synchsafe(b):
    return (b[0] << 21) | (b[1] << 14) | (b[2] << 7) | b[3]


def _decode_text(raw):
    if not raw:
        return ""
    enc = raw[0]
    body = raw[1:]
    try:
        if enc == 0:
            return body.decode("latin-1", "replace")
        if enc == 1:
            return body.decode("utf-16", "replace")
        if enc == 2:
            return body.decode("utf-16-be", "replace")
        return body.decode("utf-8", "replace")
    except Exception:
        return ""


def _read_id3(path):
    tags, art = {}, None
    try:
        with open(path, "rb") as f:
            head = f.read(10)
            if len(head) < 10 or head[:3] != b"ID3":
                return tags, art
            ver = head[3]
            size = _synchsafe(head[6:10])
            data = f.read(size)
        pos = 0
        while pos + 10 <= len(data):
            fid = data[pos:pos + 4]
            if fid.strip(b"\x00") == b"":
                break
            if ver == 4:
                fsize = _synchsafe(data[pos + 4:pos + 8])
            else:
                fsize = struct.unpack(">I", data[pos + 4:pos + 8])[0]
            frame = data[pos + 10:pos + 10 + fsize]
            pos += 10 + fsize
            if fid in (b"TIT2", b"TPE1", b"TCON", b"TBPM"):
                key = {b"TIT2": "title", b"TPE1": "artist",
                       b"TCON": "genre", b"TBPM": "bpm"}[fid]
                tags[key] = _decode_text(frame).split("\x00")[0].strip()
            elif fid == b"APIC" and frame:
                try:
                    enc = frame[0]
                    rest = frame[1:]
                    mime_end = rest.index(b"\x00")
                    rest = rest[mime_end + 2:]  # mime + picture-type byte
                    if enc in (1, 2):
                        d_end = rest.index(b"\x00\x00")
                        img = rest[d_end + 2:]
                    else:
                        d_end = rest.index(b"\x00")
                        img = rest[d_end + 1:]
                    if len(img) > 200:
                        art = img
                except Exception:
                    pass
    except Exception:
        pass
    return tags, art


def _read_flac(path):
    tags, art = {}, None
    try:
        with open(path, "rb") as f:
            if f.read(4) != b"fLaC":
                return tags, art
            while True:
                hdr = f.read(4)
                if len(hdr) < 4:
                    break
                last = hdr[0] & 0x80
                btype = hdr[0] & 0x7F
                blen = struct.unpack(">I", b"\x00" + hdr[1:4])[0]
                block = f.read(blen)
                if btype == 4:  # vorbis comment
                    try:
                        p = 0
                        vlen = struct.unpack("<I", block[p:p + 4])[0]
                        p += 4 + vlen
                        count = struct.unpack("<I", block[p:p + 4])[0]
                        p += 4
                        for _ in range(count):
                            ln = struct.unpack("<I", block[p:p + 4])[0]
                            p += 4
                            entry = block[p:p + ln].decode("utf-8", "replace")
                            p += ln
                            if "=" in entry:
                                k, v = entry.split("=", 1)
                                tags[k.lower()] = v
                    except Exception:
                        pass
                elif btype == 6:  # picture
                    try:
                        p = 0
                        p += 4  # picture type
                        mlen = struct.unpack(">I", block[p:p + 4])[0]
                        p += 4 + mlen
                        dlen = struct.unpack(">I", block[p:p + 4])[0]
                        p += 4 + dlen
                        p += 16  # width/height/depth/colors
                        ilen = struct.unpack(">I", block[p:p + 4])[0]
                        p += 4
                        img = block[p:p + ilen]
                        if len(img) > 200:
                            art = img
                    except Exception:
                        pass
                if last:
                    break
    except Exception:
        pass
    return tags, art


def read_metadata(path):
    ext = os.path.splitext(path)[1].lower()
    if ext == ".flac":
        return _read_flac(path)
    if ext in (".mp3", ".m4a", ".aac", ".aiff", ".aif"):
        return _read_id3(path)
    return {}, None


# ---------------- audio facts (duration + real waveform peaks) ----------------

def _peaks_and_duration(path, buckets=56):
    """Best-effort: (peaks list 0..1, duration seconds) or (None, None)."""
    try:
        import soundfile as sf
        info = sf.info(path)
        dur = float(info.frames) / float(info.samplerate or 44100)
        peaks = [0.0] * buckets
        per = max(1, int(info.frames) // buckets)
        with sf.SoundFile(path) as f:
            done = 0
            idx = 0
            while idx < buckets:
                block = f.read(per, dtype="float32", always_2d=True)
                if block is None or len(block) == 0:
                    break
                import numpy as np
                peaks[idx] = float(np.max(np.abs(block)))
                idx += 1
                done += len(block)
        mx = max(peaks) or 1.0
        return [p / mx for p in peaks], dur
    except Exception:
        pass
    try:
        import miniaudio
        src = miniaudio.SampleRateConverter  # noqa - presence probe
        decoded = miniaudio.decode_file(path)
        import numpy as np
        import array as _arr
        samples = _arr.array("h")
        samples.frombytes(decoded.samples)
        a = np.asarray(samples, dtype=np.float32) / 32768.0
        if decoded.nchannels > 1:
            a = a.reshape(-1, decoded.nchannels).mean(axis=1)
        dur = len(a) / float(decoded.sample_rate or 44100)
        per = max(1, len(a) // buckets)
        peaks = []
        for i in range(buckets):
            seg = a[i * per:(i + 1) * per]
            peaks.append(float(np.max(np.abs(seg))) if len(seg) else 0.0)
        mx = max(peaks) or 1.0
        return [p / mx for p in peaks], dur
    except Exception:
        return None, None


# ---------------- cover rendering ----------------

def _font(size, bold=True):
    from PIL import ImageFont
    names = (["DejaVuSans-Bold.ttf"] if bold else ["DejaVuSans.ttf"])
    roots = ["/usr/share/fonts", "/data/data/com.termux/files/usr/share/fonts",
             "/system/fonts"]
    for root in roots:
        if os.path.isdir(root):
            for dirpath, _dirs, files in os.walk(root):
                for n in names:
                    if n in files:
                        try:
                            return ImageFont.truetype(os.path.join(dirpath, n), size)
                        except Exception:
                            pass
    try:
        return ImageFont.load_default(size=size)
    except Exception:
        return ImageFont.load_default()


def _title_from_filename(path):
    name = os.path.splitext(os.path.basename(path))[0]
    name = re.sub(r"^(outputs?|master|beat|final|track)[_\-\s]+", "", name,
                  flags=re.I)
    name = name.replace("_", " ").replace("-", " ").strip()
    name = re.sub(r"\s+", " ", name)
    return name.title() if name else "Untitled"


def _guess_genre(text):
    t = (text or "").lower()
    for keys, _pal in GENRE_PALETTES:
        for k in keys:
            if k in t:
                return k.replace("boom", "boom bap").title()
    return ""


def _fmt_dur(sec):
    if not sec:
        return ""
    sec = int(round(sec))
    return "%d:%02d" % (sec // 60, sec % 60)


def make_thumb(path):
    """Return JPEG bytes for the track's cover, or None."""
    try:
        from PIL import Image, ImageDraw
        import io
    except Exception:
        return None
    try:
        tags, art = read_metadata(path)
        title = (tags.get("title") or "").strip() or _title_from_filename(path)
        artist = (tags.get("artist") or "").strip()
        genre = (tags.get("genre") or "").strip() or _guess_genre(
            os.path.basename(path) + " " + title)
        bpm = (tags.get("bpm") or "").strip()
        peaks, dur = _peaks_and_duration(path)

        img = None
        if art:
            try:
                src = Image.open(io.BytesIO(art)).convert("RGB")
                w, h = src.size
                side = min(w, h)
                src = src.crop(((w - side) // 2, (h - side) // 2,
                                (w + side) // 2, (h + side) // 2))
                img = src.resize((SIZE, SIZE))
            except Exception:
                img = None
        if img is None:
            top, bot = _palette_for(genre + " " + os.path.basename(path))
            img = Image.new("RGB", (SIZE, SIZE), top)
            px = img.load()
            for y in range(SIZE):
                f = y / float(SIZE - 1)
                c = tuple(int(top[i] + (bot[i] - top[i]) * f) for i in range(3))
                for x in range(SIZE):
                    px[x, y] = c
            d = ImageDraw.Draw(img, "RGBA")
            # waveform band (real peaks when we could decode them)
            mid = SIZE // 2
            if peaks:
                vals = peaks
            else:
                import math
                vals = [0.35 + 0.3 * abs(math.sin(i * 0.7))
                        for i in range(56)]
            bw = SIZE / float(len(vals))
            for i, v in enumerate(vals):
                hgt = max(3, int(v * SIZE * 0.26))
                x0 = int(i * bw + 1)
                d.rectangle([x0, mid - hgt, x0 + max(1, int(bw - 2)),
                             mid + hgt], fill=(255, 255, 255, 110))
            d.rectangle([0, SIZE - 64, SIZE, SIZE], fill=(0, 0, 0, 90))
        else:
            d = ImageDraw.Draw(img, "RGBA")
            d.rectangle([0, SIZE - 64, SIZE, SIZE], fill=(0, 0, 0, 110))

        # title (wrapped, max 2 lines) + metadata line
        d = ImageDraw.Draw(img, "RGBA")
        f_title = _font(26)
        words, lines, cur = title.split(), [], ""
        for w_ in words:
            trial = (cur + " " + w_).strip()
            if d.textlength(trial, font=f_title) <= SIZE - 24 or not cur:
                cur = trial
            else:
                lines.append(cur)
                cur = w_
            if len(lines) == 2:
                break
        if cur and len(lines) < 2:
            lines.append(cur)
        y = SIZE - 58
        for ln in reversed(lines):
            d.text((12, y - 30), ln, font=f_title, fill=(255, 255, 255, 255))
            y -= 30
        bits = [b for b in (artist, genre.title() if genre else "",
                            (bpm + " BPM") if bpm else "", _fmt_dur(dur)) if b]
        if bits:
            d.text((12, SIZE - 24), " • ".join(bits), font=_font(15, bold=False),
                   fill=(230, 220, 255, 230))
        _tag = "♪ Prhyme"
        _tf = _font(13, bold=False)
        try:
            _tw = d.textlength(_tag, font=_tf)
        except Exception:
            _tw = 60
        d.text((SIZE - 10 - _tw, 8), _tag, font=_tf,
               fill=(255, 255, 255, 160))
        out = io.BytesIO()
        img.save(out, "JPEG", quality=82)
        return out.getvalue()
    except Exception:
        return None


# ---------------- cache ----------------

def get_or_make_thumb(path, cache_dir):
    """Cached thumbnail file path for an audio file, or None."""
    try:
        if not path or not os.path.isfile(path):
            return None
        os.makedirs(cache_dir, exist_ok=True)
        key = hashlib.sha1(os.path.realpath(path).encode("utf-8")).hexdigest()[:16]
        out = os.path.join(cache_dir, key + ".jpg")
        try:
            if (os.path.isfile(out)
                    and os.path.getmtime(out) >= os.path.getmtime(path)):
                return out
        except OSError:
            pass
        data = make_thumb(path)
        if not data:
            return None
        tmp = out + ".tmp"
        with open(tmp, "wb") as f:
            f.write(data)
        os.replace(tmp, out)
        return out
    except Exception:
        return None
