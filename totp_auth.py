"""Prhyme two-factor authentication — TOTP + backup codes.

Stdlib-only (hmac, hashlib, base64, struct, time, secrets). No new
dependencies so it runs on the phone's Termux Python as-is.

TOTP follows RFC 6238 (SHA-1, 30s period, 6 digits) — compatible with
Google Authenticator, Authy, 1Password, etc.
"""

import base64
import hashlib
import hmac
import secrets
import struct
import time

# ------------------------------------------------------------------ TOTP
_PERIOD = 30
_DIGITS = 6


def generate_secret():
    """New random TOTP secret (base32, 160 bits)."""
    return base64.b32encode(secrets.token_bytes(20)).decode("ascii")


def _hotp(secret_b32, counter):
    """RFC 4226 HOTP."""
    key = base64.b32decode(secret_b32, casefold=True)
    msg = struct.pack(">Q", counter)
    mac = hmac.new(key, msg, hashlib.sha1).digest()
    offset = mac[-1] & 0x0F
    code = struct.unpack(">I", mac[offset:offset + 4])[0] & 0x7FFFFFFF
    return code % (10 ** _DIGITS)


def totp_now(secret_b32):
    """Current TOTP code (for testing)."""
    return _hotp(secret_b32, int(time.time()) // _PERIOD)


def verify_totp(secret_b32, code, window=1):
    """Verify a TOTP code. `window` allows ±N periods for clock skew.

    Uses hmac.compare_digest for constant-time comparison.
    """
    try:
        code = str(code).strip()
        if not code.isdigit():
            return False
    except (AttributeError, TypeError):
        return False
    counter = int(time.time()) // _PERIOD
    for delta in range(-window, window + 1):
        expected = f"{_hotp(secret_b32, counter + delta):06d}"
        if hmac.compare_digest(code.zfill(6), expected):
            return True
    return False


def provisioning_uri(secret_b32, email, issuer="Prhyme"):
    """otpauth:// URI for QR code / manual entry."""
    from urllib.parse import quote
    label = quote(f"{issuer}:{email}")
    params = (f"secret={secret_b32}&issuer={quote(issuer)}"
              f"&algorithm=SHA1&digits=6&period=30")
    return f"otpauth://totp/{label}?{params}"


# ------------------------------------------------------------ backup codes
_N_BACKUP_CODES = 10


def generate_backup_codes():
    """Generate N single-use backup codes. Returns (codes, hashes).

    Codes are shown to the user once; only hashes are stored.
    Format: XXXX-XXXX (8 chars from unambiguous alphabet).
    """
    alphabet = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"  # no 0/O, 1/I/L
    codes, hashes = [], []
    for _ in range(_N_BACKUP_CODES):
        code = "-".join(
            "".join(secrets.choice(alphabet) for _ in range(4))
            for _ in range(2))
        codes.append(code)
        # Hash like passwords (PBKDF2, fewer iterations — codes are high-entropy).
        salt = secrets.token_hex(8)
        dk = hashlib.pbkdf2_hmac("sha256", code.encode(),
                                 salt.encode(), 100000)
        hashes.append(f"pbkdf2_sha256$100000${salt}${dk.hex()}")
    return codes, hashes


def verify_backup_code(code, stored_hashes):
    """Check a backup code against stored hashes.

    Returns (valid: bool, remaining_hashes: list). Consumed codes are
    removed from the list (single-use).
    """
    code = (code or "").strip().upper()
    for i, stored in enumerate(stored_hashes):
        try:
            algo, iters, salt, hexhash = stored.split("$")
            dk = hashlib.pbkdf2_hmac("sha256", code.encode(),
                                     salt.encode(), int(iters))
            if hmac.compare_digest(dk.hex(), hexhash):
                remaining = stored_hashes[:i] + stored_hashes[i + 1:]
                return True, remaining
        except (ValueError, AttributeError):
            continue
    return False, stored_hashes
