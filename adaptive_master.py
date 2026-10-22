"""
Adaptive mastering for tracks with tempo/volume changes.
Analyzes audio to detect section boundaries, then adapts mastering
parameters per section. Wraps the existing master_chunked — does not
modify the working chain.
"""

def analyze_track_sections(audio_path, sr=44100, window_s=5.0, min_section_s=15.0):
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
        end_s = min(end_w * window_n, len(data))
        
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
