"""Prhyme freemium — snippet previews + seed uniqueness.

Free tier (no account needed):
  * Beat generation: short previews only (8 bars, ~15-30s)
  * Lyrics: first 8 lines / first verse only

Paid tier (active subscription / lifetime / founding / trial):
  * Full songs, full lyrics, all heavy features

Seed uniqueness:
  * Every generation gets a unique seed — never repeats for the same
    user/session. Regenerating always produces a new variation.
"""

import hashlib
import secrets
import threading
import time

# In-memory seed tracking: {user_key: set(seeds_used)}
# user_key is "uid:<id>" for logged-in users, "sess:<session_id>" or
# "ip:<addr>" for anonymous. Bounded to prevent memory bloat.
_seen_seeds = {}
_seen_lock = threading.Lock()
_MAX_SEEDS_PER_USER = 500


def _prune(user_key):
    """Keep the seed set bounded (FIFO-ish via arbitrary discard)."""
    s = _seen_seeds.get(user_key)
    if s and len(s) > _MAX_SEEDS_PER_USER:
        # Drop oldest-ish: convert to list, keep the newest half.
        # Sets are unordered; this is approximate but effective.
        keep = list(s)[-_MAX_SEEDS_PER_USER // 2:]
        _seen_seeds[user_key] = set(keep)


def unique_seed(user_key, salt=""):
    """Return a cryptographically unique seed never before used by this user.

    Retries until a fresh seed is found (collision is ~impossible, but the
    loop guarantees the contract).
    """
    with _seen_lock:
        seen = _seen_seeds.setdefault(user_key, set())
        for _ in range(10):
            seed = int.from_bytes(secrets.token_bytes(4), "big")
            if salt:
                # Mix the salt in so different contexts can't collide.
                seed ^= int(hashlib.sha256(
                    f"{salt}:{seed}".encode()).hexdigest()[:8], 16)
                seed &= 0xFFFFFFFF
            if seed not in seen:
                seen.add(seed)
                _prune(user_key)
                return seed
        # Extremely unlikely fallback: timestamp-mixed seed.
        seed = (int(time.time() * 1000) ^ secrets.randbits(32)) & 0xFFFFFFFF
        seen.add(seed)
        _prune(user_key)
        return seed


def mark_seed_used(user_key, seed):
    """Record an externally-chosen seed as used (e.g. user-supplied)."""
    with _seen_lock:
        seen = _seen_seeds.setdefault(user_key, set())
        seen.add(int(seed))
        _prune(user_key)


def is_seed_used(user_key, seed):
    """Check whether this user already generated with this seed."""
    with _seen_lock:
        return int(seed) in _seen_seeds.get(user_key, set())


# ------------------------------------------------------------------ snippets
PREVIEW_BARS = 8          # beat preview length (~15-30s depending on BPM)
PREVIEW_LYRIC_LINES = 8   # lyric preview: first N lines


def snippet_beat_params(data):
    """Force preview constraints on beat params. Returns modified copy."""
    d = dict(data or {})
    d["bars"] = PREVIEW_BARS
    # Previews never get full-song durations.
    d.pop("length", None)
    d.pop("duration", None)
    return d


def snippet_lyrics(text):
    """Trim generated lyric text to the first PREVIEW_LYRIC_LINES non-empty lines,
    keeping the title line if present."""
    lines = text.split("\n")
    out = []
    for line in lines:
        out.append(line)
        # Count non-empty, non-header lines toward the limit.
        content = [l for l in out
                   if l.strip() and not l.strip().startswith("[")
                   and not l.strip().startswith("Title:")]
        if len(content) >= PREVIEW_LYRIC_LINES:
            break
    result = "\n".join(out).rstrip()
    if len(lines) > len(out):
        result += "\n\n… [Preview — upgrade for the full lyrics]"
    return result


def upgrade_payload():
    """Standard 'upgrade required' payload fragment for preview responses."""
    return {
        "is_preview": True,
        "upgrade_url": "/pricing",
        "upgrade_message": (
            "This is a free preview. Upgrade for full songs, "
            "full lyrics, and unlimited generations."
        ),
    }
