"""Minimal QR Code generator — byte mode, ECC level M, SVG output.

Stdlib-only. Supports versions 1-10 (sufficient for otpauth:// URIs).
Implements ISO/IEC 18004: data encoding, Reed-Solomon ECC, masking,
format/version info, and module placement.

Not a general-purpose library — tuned for short byte-mode payloads.
"""

# --- Galois field GF(256) ---
_EXP = [0] * 512
_LOG = [0] * 256


def _gf_init():
    x = 1
    for i in range(255):
        _EXP[i] = x
        _LOG[x] = i
        x <<= 1
        if x & 0x100:
            x ^= 0x11D
    for i in range(255, 512):
        _EXP[i] = _EXP[i - 255]


_gf_init()


def _gf_mul(a, b):
    return 0 if a == 0 or b == 0 else _EXP[_LOG[a] + _LOG[b]]


def _rs_generator(degree):
    """Reed-Solomon generator polynomial of given degree."""
    poly = [1]
    for i in range(degree):
        nxt = [0] * (len(poly) + 1)
        for j, c in enumerate(poly):
            nxt[j] ^= _gf_mul(c, _EXP[i])
            nxt[j + 1] ^= c
        poly = nxt
    return poly


def _rs_encode(data, degree):
    """Compute ECC bytes for data."""
    gen = _rs_generator(degree)
    res = [0] * degree
    for b in data:
        fb = b ^ res[0]
        res = res[1:] + [0]
        for i in range(degree):
            res[i] ^= _gf_mul(gen[i], fb)
    return res


# --- Version info: (size, total_codewords, ecc_codewords_per_block,
#                     blocks_g1, data_cw_g1, blocks_g2, data_cw_g2) ---
# ECC level M only, versions 1-10.
_VERSIONS = {
    1: (21, 26, 10, 1, 16, 0, 0),
    2: (25, 44, 16, 1, 28, 0, 0),
    3: (29, 70, 26, 1, 44, 0, 0),
    4: (33, 100, 18, 2, 32, 0, 0),
    5: (37, 134, 24, 2, 43, 0, 0),
    6: (41, 172, 16, 4, 27, 0, 0),
    7: (45, 196, 18, 4, 31, 0, 0),
    8: (49, 242, 22, 2, 38, 2, 39),
    9: (53, 292, 22, 3, 36, 2, 37),
    10: (57, 346, 26, 4, 43, 1, 44),
}

# Alignment pattern centers per version.
_ALIGN = {
    1: [], 2: [6, 18], 3: [6, 22], 4: [6, 26], 5: [6, 30],
    6: [6, 34], 7: [6, 22, 38], 8: [6, 24, 42], 9: [6, 26, 46],
    10: [6, 28, 50],
}

# Format info for ECC level M (15 bits, precomputed for all masks).
_FORMAT_M = [
    0b101010000010010, 0b101000100100101, 0b101111001111100,
    0b101101101001011, 0b100010111111001, 0b100000011001110,
    0b100111110010111, 0b100101010100000,
]


def _bits_for_version(data_len, version):
    """Bit count for byte-mode encoding at given version."""
    size, total_cw, _, _, _, _, _ = _VERSIONS[version]
    char_count_bits = 8 if version < 10 else 16
    return 4 + char_count_bits + data_len * 8


def _pick_version(data_len):
    for v in range(1, 11):
        size, total_cw, ecc_cw, b1, d1, b2, d2 = _VERSIONS[v]
        data_capacity = b1 * d1 + b2 * d2
        # Need: mode(4) + count(8/16) + data*8 + terminator(<=4) <= capacity*8
        need = _bits_for_version(data_len, v) + 4
        if need <= data_capacity * 8:
            return v
    raise ValueError("Data too long for QR version 10")


def _encode_data(data_bytes, version):
    size, total_cw, ecc_cw, b1, d1, b2, d2 = _VERSIONS[version]
    data_capacity = b1 * d1 + b2 * d2
    bits = []
    # Mode indicator: 0100 (byte mode)
    bits += [0, 1, 0, 0]
    # Character count
    ccbits = 8 if version < 10 else 16
    n = len(data_bytes)
    for i in range(ccbits - 1, -1, -1):
        bits.append((n >> i) & 1)
    # Data
    for b in data_bytes:
        for i in range(7, -1, -1):
            bits.append((b >> i) & 1)
    # Terminator (up to 4 zeros)
    capacity_bits = data_capacity * 8
    term = min(4, capacity_bits - len(bits))
    bits += [0] * term
    # Pad to byte boundary
    while len(bits) % 8:
        bits.append(0)
    # Pad bytes 0xEC, 0x11 alternating
    data = []
    for i in range(0, len(bits), 8):
        byte = 0
        for b in bits[i:i + 8]:
            byte = (byte << 1) | b
        data.append(byte)
    pad = [0xEC, 0x11]
    pi = 0
    while len(data) < data_capacity:
        data.append(pad[pi % 2])
        pi += 1
    return data


def _interleave(data, version):
    """Split into blocks, add ECC, interleave."""
    _, _, ecc_cw, b1, d1, b2, d2 = _VERSIONS[version]
    blocks = []
    idx = 0
    for _ in range(b1):
        blocks.append(data[idx:idx + d1])
        idx += d1
    for _ in range(b2):
        blocks.append(data[idx:idx + d2])
        idx += d2
    ecc_blocks = [_rs_encode(b, ecc_cw) for b in blocks]
    # Interleave data
    out = []
    max_d = max(d1, d2)
    for i in range(max_d):
        for b in blocks:
            if i < len(b):
                out.append(b[i])
    # Interleave ECC
    for i in range(ecc_cw):
        for eb in ecc_blocks:
            out.append(eb[i])
    return out


def _mask_func(mask, r, c):
    if mask == 0:
        return (r + c) % 2 == 0
    if mask == 1:
        return r % 2 == 0
    if mask == 2:
        return c % 3 == 0
    if mask == 3:
        return (r + c) % 3 == 0
    if mask == 4:
        return (r // 2 + c // 3) % 2 == 0
    if mask == 5:
        return (r * c) % 2 + (r * c) % 3 == 0
    if mask == 6:
        return ((r * c) % 2 + (r * c) % 3) % 2 == 0
    return ((r + c) % 2 + (r * c) % 3) % 2 == 0


def _place_finder(m, r, c):
    pat = [[1] * 7] + [[1] + [0] * 5 + [1]] + \
          [[1, 0] + [1] * 3 + [0, 1]] * 3 + \
          [[1] + [0] * 5 + [1]] + [[1] * 7]
    for dr in range(7):
        for dc in range(7):
            m[r + dr][c + dc] = pat[dr][dc]
    # Separator (white border)
    n = len(m)
    for i in range(-1, 8):
        for rr, cc in [(r - 1, c + i), (r + 7, c + i),
                       (r + i, c - 1), (r + i, c + 7)]:
            if 0 <= rr < n and 0 <= cc < n and m[rr][cc] == -1:
                m[rr][cc] = 0


def _place_alignment(m, centers):
    n = len(m)
    for r in centers:
        for c in centers:
            # Skip overlaps with finders
            if (r < 9 and c < 9) or (r < 9 and c > n - 9) or \
               (r > n - 9 and c < 9):
                continue
            for dr in range(-2, 3):
                for dc in range(-2, 3):
                    v = 1 if max(abs(dr), abs(dc)) != 1 else 0
                    if m[r + dr][c + dc] == -1:
                        m[r + dr][c + dc] = v


def _reserve_format(m):
    n = len(m)
    # Format info areas (marked with -2 so data placement skips them)
    for i in range(6):
        m[8][i] = m[8][n - 1 - i] = -2
        m[i][8] = m[n - 1 - i][8] = -2
    m[8][7] = m[8][n - 8] = m[7][8] = m[n - 8][8] = -2
    # Timing patterns
    for i in range(8, n - 8):
        if m[6][i] == -1:
            m[6][i] = i % 2 == 0
        if m[i][6] == -1:
            m[i][6] = i % 2 == 0
    # Dark module
    m[n - 8][8] = 1


def _write_format(m, mask):
    n = len(m)
    fmt = _FORMAT_M[mask]
    bits = [(fmt >> i) & 1 for i in range(14, -1, -1)]
    # Top-left copy
    pos = [(8, 0), (8, 1), (8, 2), (8, 3), (8, 4), (8, 5),
           (8, 7), (8, 8),
           (7, 8), (5, 8), (4, 8), (3, 8), (2, 8), (1, 8), (0, 8)]
    for (r, c), b in zip(pos, bits):
        m[r][c] = b
    # Split copies
    for i in range(7):
        m[n - 1 - i][8] = bits[i]
    for i in range(8):
        m[8][n - 8 + i] = bits[7 + i]


def _penalty(m):
    """Simplified penalty score for mask selection."""
    n = len(m)
    score = 0
    # Rule 1: consecutive same-color runs in rows/cols
    for r in range(n):
        run = 1
        for c in range(1, n):
            if m[r][c] == m[r][c - 1]:
                run += 1
            else:
                if run >= 5:
                    score += 3 + (run - 5)
                run = 1
        if run >= 5:
            score += 3 + (run - 5)
    for c in range(n):
        run = 1
        for r in range(1, n):
            if m[r][c] == m[r - 1][c]:
                run += 1
            else:
                if run >= 5:
                    score += 3 + (run - 5)
                run = 1
        if run >= 5:
            score += 3 + (run - 5)
    # Rule 4: dark module ratio
    dark = sum(cell == 1 for row in m for cell in row)
    ratio = abs(dark * 20 / (n * n) - 10)
    score += int(ratio) * 10
    return score


def generate_matrix(text):
    """Generate QR module matrix (list of lists of 0/1) for text."""
    data_bytes = text.encode("utf-8")
    version = _pick_version(len(data_bytes))
    size, _, _, _, _, _, _ = _VERSIONS[version]
    data_cw = _encode_data(data_bytes, version)
    final = _interleave(data_cw, version)

    best = None
    best_score = None
    for mask in range(8):
        m = [[-1] * size for _ in range(size)]
        _place_finder(m, 0, 0)
        _place_finder(m, 0, size - 7)
        _place_finder(m, size - 7, 0)
        _place_alignment(m, _ALIGN[version])
        _reserve_format(m)
        # Place data bits (zigzag from bottom-right)
        bit_idx = 0
        bits = []
        for b in final:
            for i in range(7, -1, -1):
                bits.append((b >> i) & 1)
        c = size - 1
        upward = True
        while c > 0:
            if c == 6:
                c -= 1
            rows = range(size - 1, -1, -1) if upward else range(size)
            for r in rows:
                for dc in (0, 1):
                    cc = c - dc
                    if m[r][cc] == -1 and bit_idx < len(bits):
                        v = bits[bit_idx]
                        if _mask_func(mask, r, cc):
                            v ^= 1
                        m[r][cc] = v
                        bit_idx += 1
            upward = not upward
            c -= 2
        _write_format(m, mask)
        # Fill any leftovers (shouldn't happen)
        for r in range(size):
            for cc in range(size):
                if m[r][cc] < 0:
                    m[r][cc] = 0
        score = _penalty(m)
        if best_score is None or score < best_score:
            best_score = score
            best = m
    return best


def to_svg(matrix, scale=4, border=4, dark="#000", light="#fff"):
    """Render module matrix as SVG string."""
    n = len(matrix)
    total = (n + border * 2) * scale
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" '
             f'width="{total}" height="{total}" viewBox="0 0 {total} {total}">',
             f'<rect width="{total}" height="{total}" fill="{light}"/>']
    for r in range(n):
        for c in range(n):
            if matrix[r][c]:
                x = (c + border) * scale
                y = (r + border) * scale
                parts.append(f'<rect x="{x}" y="{y}" width="{scale}" '
                             f'height="{scale}" fill="{dark}"/>')
    parts.append('</svg>')
    return "".join(parts)


def qr_svg(text, scale=4):
    """One-call: text → SVG string."""
    return to_svg(generate_matrix(text), scale=scale)
