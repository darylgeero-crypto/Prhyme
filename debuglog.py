"""Persistent debug log (2026-10-21, Daryl's order).

Survives server restarts — the nohup logs get truncated on every boot,
which hid crashes. One log per app: logs/debug.log beside the app file.
Entries older than 36 hours are pruned automatically.
"""
import os
import threading
import time

_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")
_FILE = os.path.join(_DIR, "debug.log")
_LOCK = threading.Lock()
_KEEP_S = 36 * 3600
_WRITES = [0]


def log(msg):
    try:
        line = time.strftime("%Y-%m-%d %H:%M:%S") + " " + str(msg) + "\n"
        with _LOCK:
            os.makedirs(_DIR, exist_ok=True)
            with open(_FILE, "a", encoding="utf-8") as f:
                f.write(line)
            _WRITES[0] += 1
            if _WRITES[0] % 200 == 0:
                prune()
    except Exception:
        pass


def prune():
    try:
        if not os.path.exists(_FILE):
            return
        cutoff = time.time() - _KEEP_S
        kept = []
        with open(_FILE, encoding="utf-8", errors="replace") as f:
            for ln in f:
                try:
                    ts = time.mktime(time.strptime(ln[:19],
                                                   "%Y-%m-%d %H:%M:%S"))
                    if ts >= cutoff:
                        kept.append(ln)
                except Exception:
                    kept.append(ln)
        with open(_FILE, "w", encoding="utf-8") as f:
            f.writelines(kept[-8000:])
    except Exception:
        pass


def _thread_hook(args):
    try:
        log("THREAD-DIED %s: %s: %s" % (
            args.thread.name, args.exc_type.__name__, args.exc_value))
    except Exception:
        pass


def install(name="app"):
    threading.excepthook = _thread_hook
    prune()
    log("BOOT %s starting (pid %s)" % (name, os.getpid()))
    return True
