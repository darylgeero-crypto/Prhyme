"""Prhyme(TM) local sync queue — offline-first change tracking.

Tracks local mutations (beats, lyrics, settings, soundkits, projects, notes,
billing snapshots) in a small SQLite database so a future cloud backend can
sync them opportunistically. Local storage is the source of truth; sync is
best-effort and never blocks the app.

Design rules:
  * Stdlib only (sqlite3, hashlib, json, uuid, threading, time, os).
  * Importing this module must NEVER break the app: it performs no I/O at
    import time and every public helper has a ``safe_`` variant that swallows
    all exceptions and returns a failure sentinel instead of raising.
  * Payloads stored in the queue are METADATA ONLY — never raw audio bytes.
    Large files (rendered beats, kit samples) are referenced by ``file_path``
    and hashed; the actual bytes upload happens at sync time via the cloud
    blob endpoint (see ~/workspace/djrill/SYNC_ARCHITECTURE.md).
  * One pending row per (item_type, item_id): repeat mutations coalesce into
    the latest state, so the queue stays small even if the cloud backend
    never appears.

Public API (as specified in SYNC_ARCHITECTURE.md):
    queue_change(item_type, item_id, action, payload=None, file_path=None)
    get_pending(limit=500)
    mark_synced(entry_id=None, item_id=None, item_type=None)
    get_last_sync() / set_last_sync(ts=None)

Plus helpers: safe_queue_change, get_device_id, queue_stats, prune_synced.
"""

import base64
import hashlib
import json
import os
import sqlite3
import threading
import time
import uuid

# ------------------------------------------------------------------ config

DB_FILENAME = "sync_queue.db"
DEVICE_ID_FILENAME = "device_id.txt"

ITEM_TYPES = ("beat", "lyric", "note", "setting", "soundkit",
              "billing", "project")
ACTIONS = ("create", "update", "delete")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS sync_queue (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    client_uuid  TEXT NOT NULL UNIQUE,   -- idempotency key for the cloud push
    enqueued_at  TEXT NOT NULL,           -- ISO-8601 UTC
    device_id    TEXT NOT NULL,
    item_type    TEXT NOT NULL,
    item_id      TEXT NOT NULL,
    action       TEXT NOT NULL,           -- create | update | delete
    content_hash TEXT NOT NULL,           -- sha256 over type+id+action+content
    payload      TEXT,                    -- JSON metadata (never raw audio)
    file_path    TEXT,                    -- local large file to upload at sync
    synced_at    TEXT,                    -- NULL = still pending
    attempts     INTEGER NOT NULL DEFAULT 0,
    last_error   TEXT
);
CREATE INDEX IF NOT EXISTS idx_queue_pending
    ON sync_queue (synced_at, enqueued_at);
CREATE INDEX IF NOT EXISTS idx_queue_item
    ON sync_queue (item_type, item_id);

CREATE TABLE IF NOT EXISTS sync_meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""

_lock = threading.Lock()


# ------------------------------------------------------------------ paths

def _module_dir():
    return os.path.dirname(os.path.abspath(__file__))


def _db_path(data_dir=None):
    d = data_dir or _module_dir()
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, DB_FILENAME)


def _connect(data_dir=None):
    """Short-lived connection; callers must not hold it across I/O."""
    cx = sqlite3.connect(_db_path(data_dir), timeout=10)
    cx.row_factory = sqlite3.Row
    with _lock:
        cx.executescript(_SCHEMA)
    return cx


# ------------------------------------------------------------------ misc

def _utcnow():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def get_device_id(data_dir=None):
    """Stable per-device UUID, generated once and persisted in a file.

    Survives sync_queue.db deletion on purpose: the cloud uses it to tell
    devices apart even after a local queue reset.
    """
    d = data_dir or _module_dir()
    os.makedirs(d, exist_ok=True)
    path = os.path.join(d, DEVICE_ID_FILENAME)
    try:
        with open(path, "r") as f:
            did = f.read().strip()
        if did:
            return did
    except OSError:
        pass
    did = "dev-" + uuid.uuid4().hex[:16]
    try:
        with open(path, "w") as f:
            f.write(did + "\n")
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
    except OSError:
        pass
    return did


def _canonical_payload(payload):
    """Return a JSON-canonical string for hashing/storage.

    bytes -> base64 envelope; dict/list/str/num/bool/None -> sorted JSON.
    """
    if payload is None:
        return ""
    if isinstance(payload, bytes):
        payload = {"__bytes_b64__": base64.b64encode(payload).decode("ascii")}
    try:
        return json.dumps(payload, sort_keys=True, separators=(",", ":"),
                          ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        return json.dumps(str(payload), ensure_ascii=False)


def _hash_content(item_type, item_id, action, payload_canon, file_path=None):
    h = hashlib.sha256()
    h.update(item_type.encode("utf-8"))
    h.update(b"\x00" + item_id.encode("utf-8"))
    h.update(b"\x00" + action.encode("utf-8"))
    h.update(b"\x00" + payload_canon.encode("utf-8"))
    if file_path and os.path.isfile(file_path):
        try:
            with open(file_path, "rb") as f:
                for chunk in iter(lambda: f.read(1024 * 1024), b""):
                    h.update(chunk)
        except OSError:
            h.update(b"\x00<unreadable>")
    return h.hexdigest()


# ------------------------------------------------------------------ API

def queue_change(item_type, item_id, action, payload=None, file_path=None,
                 data_dir=None):
    """Record a local mutation for future sync. Returns the queue entry id.

    Coalesces: if a pending entry already exists for (item_type, item_id) it
    is updated in place to the newest state (last-write-wins locally), so a
    device that stays offline for weeks does not accumulate junk.

    Raises ValueError on bad item_type/action; sqlite errors propagate — use
    safe_queue_change() from app code paths that must never fail.
    """
    if item_type not in ITEM_TYPES:
        raise ValueError("unknown item_type: %r" % (item_type,))
    if action not in ACTIONS:
        raise ValueError("unknown action: %r" % (action,))
    item_id = str(item_id)
    canon = _canonical_payload(payload)
    if action == "delete":
        canon = ""          # deletes carry no content; tombstone only
        file_path = None
    content_hash = _hash_content(item_type, item_id, action, canon, file_path)
    now = _utcnow()
    device_id = get_device_id(data_dir)

    cx = _connect(data_dir)
    try:
        with _lock:
            row = cx.execute(
                "SELECT id, client_uuid FROM sync_queue "
                "WHERE item_type = ? AND item_id = ? AND synced_at IS NULL",
                (item_type, item_id)).fetchone()
            if row:
                cx.execute(
                    "UPDATE sync_queue SET enqueued_at = ?, action = ?, "
                    "content_hash = ?, payload = ?, file_path = ?, "
                    "attempts = 0, last_error = NULL WHERE id = ?",
                    (now, action, content_hash, canon or None, file_path,
                     row["id"]))
                entry_id = row["id"]
            else:
                cur = cx.execute(
                    "INSERT INTO sync_queue (client_uuid, enqueued_at, "
                    "device_id, item_type, item_id, action, content_hash, "
                    "payload, file_path) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (uuid.uuid4().hex, now, device_id, item_type, item_id,
                     action, content_hash, canon or None, file_path))
                entry_id = cur.lastrowid
            cx.commit()
    finally:
        cx.close()
    return entry_id


def safe_queue_change(item_type, item_id, action, payload=None, file_path=None,
                      data_dir=None):
    """Never-raising wrapper for use inside app request handlers.

    Returns the queue entry id, or None if anything went wrong. Sync
    tracking must never break audio generation or the UI.
    """
    try:
        return queue_change(item_type, item_id, action, payload=payload,
                            file_path=file_path, data_dir=data_dir)
    except Exception:
        return None


def get_pending(limit=500, data_dir=None):
    """Pending (unsynced) entries, oldest first. Each is a plain dict."""
    cx = _connect(data_dir)
    try:
        with _lock:
            rows = cx.execute(
                "SELECT * FROM sync_queue WHERE synced_at IS NULL "
                "ORDER BY enqueued_at ASC LIMIT ?",
                (int(limit),)).fetchall()
    finally:
        cx.close()
    out = []
    for r in rows:
        d = dict(r)
        try:
            d["payload"] = json.loads(d["payload"]) if d["payload"] else None
        except (TypeError, ValueError):
            pass
        out.append(d)
    return out


def mark_synced(entry_id=None, item_id=None, item_type=None, data_dir=None):
    """Mark pending entries as synced. Returns number of rows marked.

    Prefer entry_id (exact). item_id (+ optional item_type) marks every
    pending entry for that item — what the cloud push worker uses after a
    successful POST /sync/push batch.
    """
    if entry_id is None and item_id is None:
        raise ValueError("mark_synced needs entry_id or item_id")
    now = _utcnow()
    cx = _connect(data_dir)
    try:
        with _lock:
            if entry_id is not None:
                cur = cx.execute(
                    "UPDATE sync_queue SET synced_at = ? "
                    "WHERE id = ? AND synced_at IS NULL",
                    (now, entry_id))
            elif item_type is not None:
                cur = cx.execute(
                    "UPDATE sync_queue SET synced_at = ? "
                    "WHERE item_type = ? AND item_id = ? AND synced_at IS NULL",
                    (now, item_type, str(item_id)))
            else:
                cur = cx.execute(
                    "UPDATE sync_queue SET synced_at = ? "
                    "WHERE item_id = ? AND synced_at IS NULL",
                    (now, str(item_id)))
            cx.commit()
            n = cur.rowcount
    finally:
        cx.close()
    return n


def record_attempt(entry_id, error, data_dir=None):
    """Log a failed sync attempt (used by the future sync worker)."""
    cx = _connect(data_dir)
    try:
        with _lock:
            cx.execute(
                "UPDATE sync_queue SET attempts = attempts + 1, "
                "last_error = ? WHERE id = ?",
                (str(error)[:500], entry_id))
            cx.commit()
    finally:
        cx.close()


def get_last_sync(data_dir=None):
    """ISO-8601 UTC timestamp of the last successful sync, or None."""
    cx = _connect(data_dir)
    try:
        with _lock:
            row = cx.execute(
                "SELECT value FROM sync_meta WHERE key = 'last_sync'"
            ).fetchone()
    finally:
        cx.close()
    return row["value"] if row else None


def set_last_sync(ts=None, data_dir=None):
    """Record a successful sync (ts defaults to now, UTC)."""
    ts = ts or _utcnow()
    cx = _connect(data_dir)
    try:
        with _lock:
            cx.execute(
                "INSERT INTO sync_meta (key, value) VALUES ('last_sync', ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (ts,))
            cx.commit()
    finally:
        cx.close()
    return ts


def queue_stats(data_dir=None):
    """Small health snapshot: pending/synced counts, oldest pending, last sync."""
    cx = _connect(data_dir)
    try:
        with _lock:
            pending = cx.execute(
                "SELECT COUNT(*) c FROM sync_queue WHERE synced_at IS NULL"
            ).fetchone()["c"]
            synced = cx.execute(
                "SELECT COUNT(*) c FROM sync_queue WHERE synced_at IS NOT NULL"
            ).fetchone()["c"]
            oldest = cx.execute(
                "SELECT MIN(enqueued_at) m FROM sync_queue "
                "WHERE synced_at IS NULL").fetchone()["m"]
            by_type = cx.execute(
                "SELECT item_type, COUNT(*) c FROM sync_queue "
                "WHERE synced_at IS NULL GROUP BY item_type").fetchall()
    finally:
        cx.close()
    return {
        "pending": pending,
        "synced": synced,
        "oldest_pending": oldest,
        "pending_by_type": {r["item_type"]: r["c"] for r in by_type},
        "last_sync": get_last_sync(data_dir),
        "device_id": get_device_id(data_dir),
    }


def prune_synced(keep_days=30, data_dir=None):
    """Delete synced entries older than keep_days. Returns rows removed.

    Pending entries are NEVER pruned — only the future sync worker (or an
    explicit user action) may clear those via mark_synced().
    """
    cutoff = time.strftime("%Y-%m-%dT%H:%M:%SZ",
                           time.gmtime(time.time() - keep_days * 86400))
    cx = _connect(data_dir)
    try:
        with _lock:
            cur = cx.execute(
                "DELETE FROM sync_queue WHERE synced_at IS NOT NULL "
                "AND synced_at < ?", (cutoff,))
            cx.commit()
            n = cur.rowcount
    finally:
        cx.close()
    return n


# ------------------------------------------------------------------ self-test

if __name__ == "__main__":
    import tempfile
    tmp = tempfile.mkdtemp(prefix="syncq_")
    print("self-test in", tmp)
    q1 = queue_change("setting", "lite_mode", "update",
                      {"lite": True}, data_dir=tmp)
    q2 = queue_change("setting", "lite_mode", "update",
                      {"lite": False}, data_dir=tmp)   # coalesces into q1
    assert q1 == q2, (q1, q2)
    q3 = queue_change("beat", "mybeat_001", "create",
                      {"title": "My Beat", "genre": "Drill", "bpm": 140,
                       "bars": 32, "seed": 42, "format": "mp3"},
                      file_path="/nonexistent/x.mp3", data_dir=tmp)
    assert q3 != q1
    q4 = queue_change("note", "myproject", "delete", data_dir=tmp)
    pend = get_pending(data_dir=tmp)
    assert len(pend) == 3, pend
    assert pend[0]["payload"] == {"lite": False}          # latest wins
    assert len(pend[1]["content_hash"]) == 64
    assert pend[2]["action"] == "delete" and pend[2]["payload"] is None
    assert mark_synced(entry_id=q1, data_dir=tmp) == 1
    assert mark_synced(item_id="mybeat_001", item_type="beat",
                       data_dir=tmp) == 1
    assert len(get_pending(data_dir=tmp)) == 1
    set_last_sync(data_dir=tmp)
    st = queue_stats(data_dir=tmp)
    assert st["pending"] == 1 and st["synced"] == 2 and st["last_sync"]
    assert st["device_id"].startswith("dev-")
    assert get_device_id(data_dir=tmp) == st["device_id"]  # stable
    assert prune_synced(keep_days=30, data_dir=tmp) == 0   # recent: kept
    assert safe_queue_change("bogus", "x", "update", data_dir=tmp) is None
    print("all self-tests passed")
