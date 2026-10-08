# DJRILL Mobile — Security Measures

**Last audited:** 2026-10-04
**Scope:** Flask app running locally on device via Termux (`127.0.0.1:5000`)

## Threat Model

DJRILL runs as a **local-only app** on the user's own phone. There is no remote
server, no user accounts, no payment processing. The realistic threats are:

1. Malicious file uploads (disguised executables, path traversal)
2. Resource exhaustion (accidental or via crafted requests)
3. Information disclosure (file paths, tracebacks)
4. Local tampering (someone modifying the app on the device)

**Out of scope:** Remote attackers (app is localhost-only), DRM/copy protection
(see "Honest Limitations" below).

## Measures in Place

### 1. Network Isolation
- App binds to `127.0.0.1` only — not reachable from the local network or internet
- No `0.0.0.0` binding, no port forwarding

### 2. Path Traversal Protection
| Route | Protection |
|---|---|
| `/download/<path:fname>` | `secure_filename` + rejects `/` and `\` + `isfile` check |
| `/sample/<path:fname>` | `secure_filename` equality check |
| `/clip/<path:fname>` | `daw.clip_path()` raises `ValueError` on traversal → 404 |
| `/api/kits/<name>/...` | `sanitize_name()` strips all non-alphanumeric chars |
| `/api/daw/projects/<name>` | `daw.sanitize_name()` |
| `/api/daw/notes/<name>` | `daw.sanitize_name()` |
| Chunk uploads | `commonpath` containment check |

All file operations verify the resolved path stays inside the intended directory.

### 3. Upload Validation
- **Extension whitelist** (`save_upload`): only audio formats accepted
- **Content probing**: FFmpeg probes the actual file content, rejects non-audio
- **WAV-only** for soundkit samples, with size (2MB) and duration (5s) caps
- **Filename sanitization**: `secure_filename` + UUID prefix (no collisions, no overwrites)
- **Disk-space guard**: refuses uploads if <500MB free
- **200MB** global request size limit (`MAX_CONTENT_LENGTH`)

### 4. Input Validation
- All numeric inputs (BPM, bars, EQ values, FX params) are type-checked and clamped server-side
- JSON payloads parsed with `silent=True` (malformed → empty dict, not crash)
- String inputs length-bounded (kit names ≤40 chars, notes ≤5000 chars, etc.)

### 5. Rate Limiting
- **General**: 120 requests/minute per IP
- **Heavy operations** (beat gen, mastering, mix, video, export, convert): 10 per 5 minutes per IP
- Returns clean `429` JSON, never hangs

### 6. Error Handling
- Every `/api/*` error returns `{"ok": false, "error": "..."}` — never a traceback
- Flask debug mode is **off**
- 500 errors are logged server-side, generic message to client
- No file paths, stack traces, or internals leak to the browser

### 7. Resource Guards
- **Memory guards** before heavy ops: reads `/proc/meminfo`, estimates working set, refuses gracefully instead of OOM-killing
- **Lite mode** (default ON): caps bars, skips heavy FX chains, reduces mix segments
- **Concurrency guard**: limits simultaneous heavy jobs
- **Timeouts** on long operations

### 8. Anti-Tamper (Startup Integrity Check)
- On startup, SHA-256 hashes of critical modules (`app.py`, `lightbeat.py`, `soundkits.py`, `vocalfix.py`, `trackfx.py`, `mixgen.py`, `daw.py`) are compared against the last known-good baseline
- If any module changed, a warning is printed to the console and log
- Baseline stored in `.integrity.json` (first run establishes it)

### 9. No Dangerous Patterns
- ✅ No `eval()`, `exec()`, or `pickle` deserialization of user input
- ✅ No `os.system()` / `subprocess` with user-controlled arguments
- ✅ No SQL (no database to inject)
- ✅ FFmpeg calls use argument lists, never shell strings

## Test Results (2026-10-04)

| Test | Result |
|---|---|
| Path traversal (`../../../etc/passwd`) on downloads | ✅ Blocked |
| Path traversal on kit names | ✅ Neutralized |
| Windows-style traversal (`..\\..\\`) | ✅ Blocked |
| Kit path containment | ✅ All paths inside `soundkits/` |
| Malicious filenames | ✅ Sanitized |
| `app.py` syntax after hardening | ✅ Valid |

## Honest Limitations

**What this does NOT prevent:**

1. **Local code modification**: Anyone with file access to the phone can edit the
   Python source. This is inherent to running interpreted code locally — no
   obfuscation or license check in Python can fully prevent this. If Daryl adds
   paid features later, enforcement must happen on a **remote server**, not in
   the local app.

2. **"Free use" via copying**: The app has no license key system because there's
   nothing to enforce against — it's a local tool, not a SaaS product. Anyone
   with the files can run it. This is by design for a personal studio app.

3. **Physical device access**: If someone has the unlocked phone, they have the
   app. Device-level security (lock screen, encryption) is the user's responsibility.

4. **Dependency vulnerabilities**: The app uses Flask, NumPy, SciPy. Keep them
   updated via `pip` in Termux. No automated vulnerability scanning is configured.

## Recommendations

- [ ] If paid tiers are added: implement license validation against a remote server
- [ ] Periodically run `pip list --outdated` in Termux and update Flask/NumPy
- [ ] The nightly red-team audit (`djrill-nightly-redteam` cron) covers the vault/secrets — keep it running
- [ ] Don't expose port 5000 beyond localhost (no `ssh -R`, no ngrok) unless you understand the risk
