"""
Adaptive mastering for tracks with tempo/volume changes.
Analyzes audio to detect section boundaries, then adapts mastering
parameters per section. Wraps the existing master_chunked — does not
modify the working chain.
"""

def _analyze_track_sections_full(audio_path, sr=44100, window_s=5.0, min_section_s=15.0):
    """
    Analyze audio to find natural section boundaries based on:
    - RMS energy changes (volume shifts)
    - Spectral centroid changes (brightness/timbre shifts)
    - Onset density changes (tempo/rhythm shifts)
    
    Returns list of (start_sample, end_sample, characteristics_dict)
    """
    import numpy as np
    from scipy.io import wavfile
    
    # Load audio (convert to mono for analysis)
    try:
        import soundfile as sf
        data, file_sr = sf.read(audio_path, dtype='float32')
        if file_sr != sr:
            # Simple resample by linear interpolation
            ratio = sr / file_sr
            new_len = int(len(data) * ratio)
            if data.ndim > 1:
                data = np.mean(data, axis=1)
            old_idx = np.linspace(0, len(data)-1, len(data))
            new_idx = np.linspace(0, len(data)-1, new_len)
            data = np.interp(new_idx, old_idx, data).astype(np.float32)
        elif data.ndim > 1:
            data = np.mean(data, axis=1).astype(np.float32)
    except ImportError:
        sr_file, data = wavfile.read(audio_path)
        if data.dtype == np.int16:
            data = data.astype(np.float32) / 32768.0
        elif data.dtype == np.int32:
            data = data.astype(np.float32) / 2147483648.0
        if data.ndim > 1:
            data = np.mean(data, axis=1).astype(np.float32)
        if sr_file != sr:
            ratio = sr / sr_file
            new_len = int(len(data) * ratio)
            old_idx = np.linspace(0, len(data)-1, len(data))
            new_idx = np.linspace(0, len(data)-1, new_len)
            data = np.interp(new_idx, old_idx, data).astype(np.float32)
    
    window_n = int(window_s * sr)
    n_windows = len(data) // window_n
    
    if n_windows < 2:
        # Too short for analysis — single section
        return [(0, len(data), {'energy': 'medium', 'tempo': 'stable'})]
    
    # Compute features per window
    energies = []
    centroids = []
    onset_rates = []
    
    for i in range(n_windows):
        start = i * window_n
        end = start + window_n
        window = data[start:end]
        
        # RMS energy
        rms = np.sqrt(np.mean(window**2) + 1e-10)
        energies.append(20 * np.log10(rms + 1e-10))
        
        # Spectral centroid (brightness)
        spectrum = np.abs(np.fft.rfft(window * np.hanning(len(window))))
        freqs = np.fft.rfftfreq(len(window), 1.0/sr)
        if np.sum(spectrum) > 1e-10:
            centroid = np.sum(freqs * spectrum) / np.sum(spectrum)
        else:
            centroid = 0
        centroids.append(centroid)
        
        # Onset density (simple: count significant positive energy jumps)
        hop = window_n // 20
        prev_energy = 0
        onsets = 0
        for j in range(0, len(window)-hop, hop):
            frame = window[j:j+hop]
            e = np.mean(frame**2)
            if e > prev_energy * 1.5 and e > 1e-6:
                onsets += 1
            prev_energy = e
        onset_rates.append(onsets)
    
    return _sections_from_features(energies, centroids, onset_rates,
                                   window_n, len(data), min_section_s,
                                   window_s)


def _sections_from_features(energies, centroids, onset_rates,
                            window_n, total_len, min_section_s,
                            window_s):
    """Shared boundary + section logic for both analysis paths."""
    import numpy as np
    n_windows = len(energies)
    energies = np.array(energies)
    centroids = np.array(centroids)
    onset_rates = np.array(onset_rates)
    
    # Normalize features
    def norm(x):
        std = np.std(x)
        if std < 1e-10:
            return np.zeros_like(x)
        return (x - np.mean(x)) / std
    
    e_norm = norm(energies)
    c_norm = norm(centroids)
    o_norm = norm(onset_rates)
    
    # Detect change points: where combined feature distance is large
    change_scores = np.zeros(n_windows)
    for i in range(1, n_windows):
        # Distance between consecutive windows
        dist = np.sqrt((e_norm[i]-e_norm[i-1])**2 + 
                       (c_norm[i]-c_norm[i-1])**2 * 0.5 +
                       (o_norm[i]-o_norm[i-1])**2 * 0.5)
        change_scores[i] = dist
    
    # Find peaks in change scores (threshold: mean + 1.5*std)
    threshold = np.mean(change_scores) + 1.5 * np.std(change_scores)
    boundaries = [0]
    
    min_windows = int(min_section_s / window_s)
    last_boundary = 0
    
    for i in range(1, n_windows):
        if change_scores[i] > threshold and (i - last_boundary) >= min_windows:
            boundaries.append(i)
            last_boundary = i
    
    boundaries.append(n_windows)
    
    # Build sections with characteristics
    sections = []
    for idx in range(len(boundaries)-1):
        start_w = boundaries[idx]
        end_w = boundaries[idx+1]
        start_s = start_w * window_n
        end_s = min(end_w * window_n, total_len)
        
        # Characterize this section
        seg_e = np.mean(energies[start_w:end_w])
        seg_o = np.mean(onset_rates[start_w:end_w])
        
        # Energy level
        if seg_e > np.mean(energies) + np.std(energies):
            energy = 'high'
        elif seg_e < np.mean(energies) - np.std(energies):
            energy = 'low'
        else:
            energy = 'medium'
        
        # Tempo/activity
        if seg_o > np.mean(onset_rates) + np.std(onset_rates):
            tempo = 'fast'
        elif seg_o < np.mean(onset_rates) - np.std(onset_rates):
            tempo = 'slow'
        else:
            tempo = 'stable'
        
        sections.append((start_s, end_s, {
            'energy': energy,
            'tempo': tempo,
            'rms_db': float(seg_e),
            'onset_rate': float(seg_o),
        }))
    
    return sections




def analyze_track_sections(audio_path, sr=44100, window_s=5.0, min_section_s=15.0):
    """Section analysis, STREAMED (2026-10-22 optimization).

    The original implementation decoded the whole track into RAM
    (212 MB for a 20-min song) just to compute 5-second window
    features. This version reads one window at a time from disk and
    runs the identical feature/boundary math — same sections out,
    ~2 MB in RAM. Falls back to the full decode when the file's
    sample rate differs (the old path resamples) or streaming fails.
    """
    import numpy as np
    try:
        import soundfile as sf
        info = sf.info(audio_path)
        if int(info.samplerate) != int(sr) or int(info.frames) == 0:
            raise ValueError("stream fallback")
        total = int(info.frames)
        window_n = int(window_s * sr)
        n_windows = total // window_n
        if n_windows < 2:
            return [(0, total, {'energy': 'medium', 'tempo': 'stable'})]
        energies = []
        centroids = []
        onset_rates = []
        freqs = np.fft.rfftfreq(window_n, 1.0 / sr)
        hann = np.hanning(window_n)
        hop = window_n // 20
        with sf.SoundFile(audio_path) as f:
            for i in range(n_windows):
                block = f.read(window_n, dtype='float32', always_2d=True)
                if len(block) < window_n:
                    block = np.pad(block, ((0, window_n - len(block)), (0, 0)))
                window = block.mean(axis=1)
                rms = np.sqrt(np.mean(window ** 2) + 1e-10)
                energies.append(20 * np.log10(rms + 1e-10))
                spectrum = np.abs(np.fft.rfft(window * hann))
                if np.sum(spectrum) > 1e-10:
                    centroids.append(float(np.sum(freqs * spectrum) / np.sum(spectrum)))
                else:
                    centroids.append(0.0)
                prev_energy = 0
                onsets = 0
                for j in range(0, window_n - hop, hop):
                    frame = window[j:j + hop]
                    e = np.mean(frame ** 2)
                    if e > prev_energy * 1.5 and e > 1e-6:
                        onsets += 1
                    prev_energy = e
                onset_rates.append(onsets)
        return _sections_from_features(np.array(energies),
                                       np.array(centroids),
                                       np.array(onset_rates),
                                       window_n, total, min_section_s,
                                       window_s)
    except Exception:
        return _analyze_track_sections_full(audio_path, sr, window_s,
                                            min_section_s)


def adapt_mopts_for_section(base_mopts, characteristics):
    """
    Adapt mastering options based on section characteristics.
    Returns modified mopts dict.
    """
    mopts = dict(base_mopts)  # Copy

    energy = characteristics.get('energy', 'medium')
    tempo = characteristics.get('tempo', 'stable')

    # None-guard (2026-10-21): the master flow can carry target_lufs /
    # glue_drive / deess as explicit None (unset). dict.get's default does
    # NOT fire for a present-but-None key, and None arithmetic crashed the
    # adaptive stage (TypeError) after the polish had already succeeded.
    def _num(d, key, default):
        v = d.get(key)
        return default if v is None else v

    # Adapt target LUFS based on energy
    # High energy: slightly louder target (more limiting)
    # Low energy: preserve dynamics, slightly quieter
    base_lufs = _num(mopts, 'target_lufs', -14.0)
    if energy == 'high':
        mopts['target_lufs'] = base_lufs + 1.0  # Push louder
        mopts['glue_drive'] = _num(mopts, 'glue_drive', 1.5) * 1.2  # More glue
    elif energy == 'low':
        mopts['target_lufs'] = base_lufs - 1.5  # Preserve dynamics
        mopts['glue_drive'] = _num(mopts, 'glue_drive', 1.5) * 0.8  # Less saturation

    # Adapt for tempo
    # Fast sections: tighter timing, more transient preservation
    # Slow sections: allow more sustain, gentler attack
    if tempo == 'fast':
        mopts['deess'] = _num(mopts, 'deess', 0.0) + 0.1  # Tame harsh transients
    elif tempo == 'slow':
        mopts['multiband'] = True  # Polish sustained tones

    return mopts


# ------------------------------------------------------- vocal prominence
# Daryl's order (2026-10-22): adaptive mastering must DETECT spots where
# the background beat overpowers the vocal and fix them automatically.
# The old chain re-summed the separated stems at unity, so a vocal that
# was buried in the source stayed buried, and the old QA check only
# measured master-vs-original CHANGE, never the absolute balance.
# These helpers measure the absolute vocal-vs-beat margin per window
# from the stems the chain already has, and lift ONLY the vocal, ONLY
# where it is present but under the beat. The beat is never touched and
# gain is never taken away from the vocal.

def _band_db(x, sr, lo=300.0, hi=3400.0):
    """Energy of a mono window inside the vocal band [lo, hi] Hz, in dB."""
    import numpy as np
    n = len(x)
    if n == 0:
        return -120.0
    spec = np.abs(np.fft.rfft(x * np.hanning(n))) ** 2
    f = np.fft.rfftfreq(n, 1.0 / sr)
    e = np.sum(spec[(f >= lo) & (f <= hi)]) + 1e-12
    return float(10.0 * np.log10(e / n))


def vocal_prominence_map(voc, inst, sr, win_s=2.0):
    """Per-window vocal prominence from two stems (float arrays, (n, ch)).

    Prominence is judged INSIDE the vocal band (300-3400 Hz): broadband
    stem RMS is meaningless here because the beat is broadband while the
    vocal stem is band-limited by construction (a broadband comparison
    reads ~-9 dB even on a balanced mix — measured on Damicksup,
    2026-10-22). Returns (margins_db, present_mask, vocal_band_db).
    A window is vocal-present when its vocal-band energy is clearly
    above the separation noise floor.
    """
    import numpy as np
    n = min(len(voc), len(inst))
    w = max(1, int(win_s * sr))
    nwin = n // w
    margins = np.full(nwin, np.nan, dtype=np.float64)
    vdb = np.full(nwin, -120.0, dtype=np.float64)
    present = np.zeros(nwin, dtype=bool)
    for i in range(nwin):
        s, e = i * w, (i + 1) * w
        v = voc[s:e].astype(np.float64, copy=False)
        b = inst[s:e].astype(np.float64, copy=False)
        if v.ndim > 1:
            v = v.mean(axis=1)
        if b.ndim > 1:
            b = b.mean(axis=1)
        vv = _band_db(v, sr)
        bb = _band_db(b, sr)
        vdb[i] = vv
        margins[i] = vv - bb
        present[i] = vv > -58.0
    return margins, present, vdb


def prominence_gain_curve(voc, inst, sr, dip_db=4.0, headroom_db=1.0,
                          max_lift_db=6.0, win_s=2.0):
    """The per-window lift curve behind lift_buried_vocals, exposed so
    disk-streamed callers (the >4 min fast path) can apply the same
    gains segment by segment. Returns (need_s_db, report) where
    need_s_db is the SMOOTHED per-window lift in dB."""
    import numpy as np
    voc32 = voc.astype(np.float32, copy=False)
    margins, present, vdb = vocal_prominence_map(voc32, inst, sr, win_s)
    nwin = len(margins)
    report = {"windows": int(nwin), "present": int(present.sum()),
              "lifted": 0, "baseline_db": None,
              "worst_before_db": None, "worst_after_db": None}
    if nwin == 0 or not present.any():
        return np.zeros(max(nwin, 0)), report
    pres_margins = margins[present]
    baseline = float(np.median(pres_margins))
    report["baseline_db"] = baseline
    report["worst_before_db"] = float(np.min(pres_margins))
    target = baseline - headroom_db
    aud_floor = float(np.median(vdb[present])) - 45.0
    dipped = present & (vdb > aud_floor) & (margins < baseline - dip_db)
    need = np.where(dipped,
                    np.clip(target - np.nan_to_num(margins, nan=target),
                            0.0, max_lift_db),
                    0.0)
    report["lifted"] = int((need > 0.05).sum())
    if nwin >= 3:
        ker = np.array([0.25, 0.5, 0.25])
        padded = np.pad(need, (1, 1), mode="edge")
        need_s = np.convolve(padded, ker, mode="valid")
    else:
        need_s = need
    return need_s, report


def lift_buried_vocals(voc, inst, sr, dip_db=4.0, headroom_db=1.0,
                       max_lift_db=6.0, win_s=2.0):
    """Lift the vocal stem in the spots where the beat overpowers it.

    The track's own baseline (median in-band margin over vocal-present
    windows) defines 'normal' for this song. Windows dipping more than
    dip_db below baseline are lifted toward (baseline - headroom_db),
    capped at max_lift_db. Per-window gains are smoothed (3-window
    moving average, then linear ramps) so the lift breathes instead of
    stepping. Windows at/above the dip threshold — and windows with no
    real vocal — are left exactly as they are. The beat is never
    touched and gain is never taken away from the vocal.

    Returns (corrected_vocal_float32, report_dict).
    """
    import numpy as np
    voc32 = voc.astype(np.float32, copy=False)
    need_s, report = prominence_gain_curve(voc32, inst, sr, dip_db,
                                           headroom_db, max_lift_db,
                                           win_s)
    if report["lifted"] == 0:
        report["worst_after_db"] = report["worst_before_db"]
        return voc32, report
    w = max(1, int(win_s * sr))
    nwin = len(need_s)
    n = min(len(voc32), nwin * w)
    centers = (np.arange(nwin) * w + w // 2).astype(np.float64)
    xs = np.arange(n, dtype=np.float64)
    gain_db = np.interp(xs, centers, need_s)
    gain = np.power(10.0, gain_db / 20.0).astype(np.float32)
    out = voc32[:n] * gain[:, None]
    if len(voc32) > n:
        out = np.concatenate([out, voc32[n:]], axis=0)
    m2, p2, _ = vocal_prominence_map(out, inst, sr, win_s)
    if p2.any():
        report["worst_after_db"] = float(np.min(m2[p2]))
    report["max_lift_db"] = float(np.max(need_s))
    return out.astype(np.float32, copy=False), report




def stem_balance_map(voc, inst, sr, win_s=2.0):
    """Per-window balance map from two stems: like
    vocal_prominence_map but also returns the instrumental's in-band
    levels, which two-way balancing needs (a window can only be
    balanced when BOTH stems carry real energy there). Returns
    (margins_db, present_mask, vocal_band_db, inst_band_db)."""
    import numpy as np
    n = min(len(voc), len(inst))
    w = max(1, int(win_s * sr))
    nwin = n // w
    margins = np.full(nwin, np.nan, dtype=np.float64)
    vdb = np.full(nwin, -120.0, dtype=np.float64)
    bdb = np.full(nwin, -120.0, dtype=np.float64)
    present = np.zeros(nwin, dtype=bool)
    for i in range(nwin):
        s, e = i * w, (i + 1) * w
        v = voc[s:e].astype(np.float64, copy=False)
        b = inst[s:e].astype(np.float64, copy=False)
        if v.ndim > 1:
            v = v.mean(axis=1)
        if b.ndim > 1:
            b = b.mean(axis=1)
        vv = _band_db(v, sr)
        bb = _band_db(b, sr)
        vdb[i] = vv
        bdb[i] = bb
        margins[i] = vv - bb
        present[i] = vv > -58.0
    return margins, present, vdb, bdb


def _smooth3(x):
    import numpy as np
    if len(x) >= 3:
        ker = np.array([0.25, 0.5, 0.25])
        return np.convolve(np.pad(x, (1, 1), mode="edge"), ker,
                           mode="valid")
    return x


def balance_gain_curves(voc, inst, sr, dip_db=4.0, headroom_db=1.0,
                        max_move_db=6.0, win_s=2.0):
    """Two-way balance curves (Daryl's spec, 2026-10-22): per window,
    the vocal and the beat move TOWARD EACH OTHER and meet between
    their gain difference — the quieter side rises by half the gap,
    the louder side drops by half. A window whose margin sits more
    than dip_db BELOW the track baseline is buried (vocal up, beat
    down); more than dip_db ABOVE baseline is vocal-hot (vocal down,
    beat up). Targets leave headroom_db of margin so balanced windows
    land just off the baseline instead of slamming onto it. Only
    windows where both stems carry real energy move — an a cappella
    break or a beat-only intro is never 'balanced' into mush. Each
    side's move is capped at max_move_db. Returns (voc_curve_db,
    inst_curve_db, report) with smoothed per-window gains in dB."""
    import numpy as np
    margins, present, vdb, bdb = stem_balance_map(voc, inst, sr, win_s)
    nwin = len(margins)
    report = {"windows": int(nwin), "present": int(present.sum()),
              "moved": 0, "baseline_db": None,
              "worst_before_db": None, "worst_dev_db": None}
    zero = np.zeros(max(nwin, 0))
    if nwin == 0 or not present.any():
        return zero, zero.copy(), report
    pres = margins[present]
    baseline = float(np.median(pres))
    report["baseline_db"] = baseline
    report["worst_before_db"] = float(np.min(pres))
    report["worst_dev_db"] = float(np.max(np.abs(pres - baseline)))
    target_hi = baseline - headroom_db
    target_lo = baseline + headroom_db
    aud_floor_v = float(np.median(vdb[present])) - 45.0
    bfloor = float(np.median(bdb[present])) - 45.0
    both = present & (vdb > aud_floor_v) & (bdb > bfloor)
    dev = np.nan_to_num(margins, nan=baseline) - baseline
    need = np.zeros(nwin)
    buried = both & (dev < -dip_db)
    hot = both & (dev > dip_db)
    need[buried] = target_hi - margins[buried]
    need[hot] = target_lo - margins[hot]
    half = np.clip(need / 2.0, -max_move_db, max_move_db)
    voc_curve = np.where(need != 0, half, 0.0)
    inst_curve = np.where(need != 0, -half, 0.0)
    report["moved"] = int((np.abs(half) > 0.05).sum())
    return _smooth3(voc_curve), _smooth3(inst_curve), report


def _apply_curve_db(x, curve_db, sr, win_s=2.0):
    """Apply a smoothed per-window dB curve to an in-RAM stem
    (per-sample linear interpolation between window centers, the
    same ramp shape lift_buried_vocals uses)."""
    import numpy as np
    if len(curve_db) == 0 or not np.any(np.abs(curve_db) > 0.001):
        return x
    w = max(1, int(win_s * sr))
    nwin = len(curve_db)
    n = min(len(x), nwin * w)
    centers = (np.arange(nwin) * w + w // 2).astype(np.float64)
    xs = np.arange(n, dtype=np.float64)
    gain = np.power(10.0, np.interp(xs, centers, curve_db)
                    / 20.0).astype(np.float32)
    out = x[:n] * gain[:, None]
    if len(x) > n:
        out = np.concatenate([out, x[n:]], axis=0)
    return out.astype(np.float32, copy=False)


def balance_stems(voc, inst, sr, passes=3, tol_db=0.75, dip_db=4.0,
                  headroom_db=1.0, max_move_db=6.0, win_s=2.0):
    """Meet-in-the-middle balancing over up to `passes` measurement
    passes (Daryl, 2026-10-22: 'can even make 2 or 3 passes over same
    sections if needed to get them correctly balanced'). Each pass
    re-measures the corrected stems and moves only what is still out
    of line; it stops early when the worst deviation from the track
    baseline is within tol_db. Gain is only ever redistributed
    between the two stems — words are never cut and neither stem is
    silenced. Returns (voc, inst, report)."""
    import numpy as np
    v = voc.astype(np.float32, copy=False)
    b = inst.astype(np.float32, copy=False)
    report = {"passes": 0, "moved": 0, "baseline_db": None,
              "worst_before_db": None, "worst_after_db": None}
    for p in range(max(1, int(passes))):
        vc, ic, rep = balance_gain_curves(v, b, sr, dip_db, headroom_db,
                                          max_move_db, win_s)
        if p == 0:
            report["baseline_db"] = rep["baseline_db"]
            report["worst_before_db"] = rep["worst_before_db"]
        if rep["moved"] == 0:
            break
        if p > 0 and rep["worst_dev_db"] is not None \
                and rep["worst_dev_db"] <= tol_db:
            break
        v = _apply_curve_db(v, vc, sr, win_s)
        b = _apply_curve_db(b, ic, sr, win_s)
        report["passes"] = p + 1
        report["moved"] += rep["moved"]
    margins, present, vdb, bdb = stem_balance_map(v, b, sr, win_s)
    if present.any() and report["baseline_db"] is not None:
        # 'Worst' is judged only over windows balancing may touch
        # (both stems carrying real energy) — an a cappella break has
        # a huge margin by nature and is not a balance failure.
        aud_floor_v = float(np.median(vdb[present])) - 45.0
        bfloor = float(np.median(bdb[present])) - 45.0
        elig = present & (vdb > aud_floor_v) & (bdb > bfloor)
        pool = margins[elig] if elig.any() else margins[present]
        report["worst_after_db"] = float(
            np.max(np.abs(pool - report["baseline_db"])))
    else:
        report["worst_after_db"] = report["worst_before_db"]
    return v, b, report
