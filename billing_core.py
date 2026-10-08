"""Prhyme billing core — users, trials, subscriptions, Stripe.

Stdlib-only (sqlite3 + hashlib) so it runs anywhere, no new dependencies.
Flask wiring lives in billing.py; this module holds all business logic and
is fully unit-testable without Flask.
"""
import hashlib
import hmac
import os
import secrets
import sqlite3
import time

# ------------------------------------------------------------------ config
# Daryl: flip to False to disable all billing enforcement (local dev).
BILLING_ENFORCE = True

# Pricing (USD) — from DJRILL_Ad_Campaigns.md. Adjust freely.
TRIAL_DAYS = 3
MONTHLY_PRICE = 9.00            # $9/mo subscription
PLATINUM_PRICE = 499.00         # $499/yr — Prhyme Platinum, all-access annual
LIFETIME_PRICE = 99.00          # $99 one-time, forever
PRELAUNCH_LIFETIME_PRICE = 49.00  # $49 for users 101-500 (50% off launch deal)
FOUNDING_SPOTS = 100            # first 100 signups: free lifetime
PRELAUNCH_SPOTS = 500           # users 101-500: $49 lifetime price

# --- Stripe (TEST MODE placeholders) -------------------------------------
# Daryl: replace these with your real keys from https://dashboard.stripe.com
# 1. Create a Stripe account, toggle "Test mode" ON while trying things out.
# 2. Developers -> API keys -> copy Publishable key + Secret key below.
# 3. Developers -> Webhooks -> add endpoint https://YOUR-DOMAIN/api/billing/webhook
#    -> copy the Signing secret below.
# 4. When ready for real money, toggle test mode OFF and swap in live keys.
STRIPE_PUBLISHABLE_KEY = os.environ.get("STRIPE_PUBLISHABLE_KEY", "pk_test_REPLACE_WITH_YOUR_STRIPE_PUBLISHABLE_KEY")
STRIPE_SECRET_KEY = os.environ.get("STRIPE_SECRET_KEY", "sk_test_REPLACE_WITH_YOUR_STRIPE_SECRET_KEY")
STRIPE_WEBHOOK_SECRET = os.environ.get("STRIPE_WEBHOOK_SECRET", "whsec_REPLACE_WITH_YOUR_STRIPE_WEBHOOK_SECRET")


def stripe_configured():
    """True only when Daryl has pasted real (non-placeholder) keys."""
    return (
        STRIPE_SECRET_KEY
        and "REPLACE_WITH" not in STRIPE_SECRET_KEY
        and STRIPE_PUBLISHABLE_KEY
        and "REPLACE_WITH" not in STRIPE_PUBLISHABLE_KEY
    )


# ------------------------------------------------------------------ db
_DB_PATH = None


def configure(db_path):
    global _DB_PATH
    _DB_PATH = db_path
    _init_db()


def _connect():
    con = sqlite3.connect(_DB_PATH)
    con.row_factory = sqlite3.Row
    return con


def _init_db():
    con = _connect()
    try:
        con.execute(
            """CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                created_at REAL NOT NULL,
                trial_ends_at REAL NOT NULL,
                is_founding INTEGER NOT NULL DEFAULT 0,
                founding_number INTEGER,
                is_owner INTEGER NOT NULL DEFAULT 0,
                plan TEXT NOT NULL DEFAULT 'trial',
                sub_status TEXT NOT NULL DEFAULT 'trial',
                stripe_customer_id TEXT,
                stripe_subscription_id TEXT,
                current_period_end REAL,
                reset_token_hash TEXT,
                reset_expires_at REAL,
                totp_secret TEXT,
                totp_enabled INTEGER NOT NULL DEFAULT 0,
                totp_backup_codes TEXT,
                totp_failed_attempts INTEGER NOT NULL DEFAULT 0,
                totp_locked_until REAL,
                totp_recovery_requested_at REAL,
                totp_recovery_expires_at REAL,
                sec_q1_hash TEXT,
                sec_q2_hash TEXT,
                tos_accepted_at REAL,
                tos_version TEXT
            )"""
        )
        con.execute(
            "CREATE INDEX IF NOT EXISTS idx_users_email ON users(email)")
        # Purchases ledger (receipts/invoices).
        con.execute(
            """CREATE TABLE IF NOT EXISTS purchases (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                uid INTEGER NOT NULL,
                plan TEXT NOT NULL,
                amount REAL NOT NULL,
                currency TEXT NOT NULL DEFAULT 'usd',
                stripe_session_id TEXT,
                stripe_invoice_id TEXT,
                status TEXT NOT NULL DEFAULT 'completed',
                created_at REAL NOT NULL)""")
        con.execute("CREATE INDEX IF NOT EXISTS idx_purch_uid "
                    "ON purchases(uid)")
        # Active sessions (for view/revoke).
        con.execute(
            """CREATE TABLE IF NOT EXISTS sessions (
                token TEXT PRIMARY KEY,
                uid INTEGER NOT NULL,
                ip TEXT,
                user_agent TEXT,
                created_at REAL NOT NULL,
                last_seen REAL NOT NULL)""")
        con.execute("CREATE INDEX IF NOT EXISTS idx_sess_uid "
                    "ON sessions(uid)")
        # Privacy-respecting analytics (aggregated counts only, no PII).
        con.execute(
            """CREATE TABLE IF NOT EXISTS analytics (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event TEXT NOT NULL,
                plan_label TEXT,
                created_at REAL NOT NULL)""")
        con.execute("CREATE INDEX IF NOT EXISTS idx_ana_event "
                    "ON analytics(event, created_at)")
        # Migration: add 2FA columns to existing databases.
        _cols = [r[1] for r in con.execute("PRAGMA table_info(users)")]
        for _col, _typ in [
            ("totp_secret", "TEXT"),
            ("totp_enabled", "INTEGER NOT NULL DEFAULT 0"),
            ("totp_backup_codes", "TEXT"),
            ("totp_failed_attempts", "INTEGER NOT NULL DEFAULT 0"),
            ("totp_locked_until", "REAL"),
            ("totp_recovery_requested_at", "REAL"),
            ("totp_recovery_expires_at", "REAL"),
            ("sec_q1_hash", "TEXT"),
            ("sec_q2_hash", "TEXT"),
            ("tos_accepted_at", "REAL"),
            ("tos_version", "TEXT"),
        ]:
            if _col not in _cols:
                con.execute(f"ALTER TABLE users ADD COLUMN {_col} {_typ}")
        con.commit()
    finally:
        con.close()


def _row_to_dict(row):
    return dict(row) if row else None


# ------------------------------------------------------- password hashing
# PBKDF2-SHA256, 260k iterations — stdlib only, no new dependencies.
_HASH_ALGO = "pbkdf2_sha256"
_HASH_ITERS = 260000


def hash_password(password):
    salt = secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"),
                             salt.encode("utf-8"), _HASH_ITERS)
    return f"{_HASH_ALGO}${_HASH_ITERS}${salt}${dk.hex()}"


def verify_password(password, stored):
    try:
        algo, iters, salt, hexhash = stored.split("$")
        if algo != _HASH_ALGO:
            return False
        dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"),
                                 salt.encode("utf-8"), int(iters))
        return hmac.compare_digest(dk.hex(), hexhash)
    except (ValueError, AttributeError):
        return False


# ------------------------------------------------------------- user ops
def _norm_email(email):
    return (email or "").strip().lower()


def get_user_by_email(email):
    con = _connect()
    try:
        row = con.execute("SELECT * FROM users WHERE email = ?",
                          (_norm_email(email),)).fetchone()
        return _row_to_dict(row)
    finally:
        con.close()


def get_user(uid):
    con = _connect()
    try:
        row = con.execute("SELECT * FROM users WHERE id = ?",
                          (uid,)).fetchone()
        return _row_to_dict(row)
    finally:
        con.close()


def user_count():
    con = _connect()
    try:
        return con.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    finally:
        con.close()


def founding_count():
    con = _connect()
    try:
        return con.execute(
            "SELECT COUNT(*) FROM users WHERE is_founding = 1").fetchone()[0]
    finally:
        con.close()


def founding_spots_left():
    return max(0, FOUNDING_SPOTS - founding_count())


def create_user(email, password):
    """Create a user. First-ever user becomes owner + founding #1 (lifetime).
    Next 99 signups become founding members (free lifetime). Everyone else
    starts a 3-day trial."""
    email = _norm_email(email)
    if not email or "@" not in email:
        return None, "Enter a valid email address."
    if not password or len(password) < 8:
        return None, "Password must be at least 8 characters."
    if get_user_by_email(email):
        return None, "That email is already registered. Try logging in."

    now = time.time()
    total = user_count()
    n_founding = founding_count()

    is_owner = 1 if total == 0 else 0
    is_founding = 0
    founding_number = None
    plan, sub_status = "trial", "trial"
    if is_owner or n_founding < FOUNDING_SPOTS:
        is_founding = 1
        founding_number = n_founding + 1
        plan, sub_status = "lifetime", "lifetime"

    con = _connect()
    try:
        cur = con.execute(
            """INSERT INTO users
               (email, password_hash, created_at, trial_ends_at,
                is_founding, founding_number, is_owner, plan, sub_status)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (email, hash_password(password), now,
             now + TRIAL_DAYS * 86400,
             is_founding, founding_number, is_owner, plan, sub_status))
        con.commit()
        uid = cur.lastrowid
    finally:
        con.close()
    track_event("signup", "founding" if is_founding else "trial")
    return get_user(uid), None


def authenticate(email, password):
    user = get_user_by_email(email)
    if not user:
        return None
    if not verify_password(password, user["password_hash"]):
        return None
    return user


def set_password(uid, new_password):
    con = _connect()
    try:
        con.execute(
            "UPDATE users SET password_hash = ?, reset_token_hash = NULL,"
            " reset_expires_at = NULL WHERE id = ?",
            (hash_password(new_password), uid))
        con.commit()
    finally:
        con.close()


def update_user(uid, **fields):
    allowed = {"plan", "sub_status", "stripe_customer_id",
               "stripe_subscription_id", "current_period_end",
               "reset_token_hash", "reset_expires_at",
               "totp_secret", "totp_enabled", "totp_backup_codes",
               "totp_failed_attempts", "totp_locked_until",
               "totp_recovery_requested_at", "totp_recovery_expires_at",
               "sec_q1_hash", "sec_q2_hash",
               "tos_accepted_at", "tos_version"}
    sets = {k: v for k, v in fields.items() if k in allowed}
    if not sets:
        return
    con = _connect()
    try:
        cols = ", ".join(f"{k} = ?" for k in sets)
        con.execute(f"UPDATE users SET {cols} WHERE id = ?",
                    (*sets.values(), uid))
        con.commit()
    finally:
        con.close()


# ------------------------------------------------------- access control
def subscription_state(user):
    """Return (active: bool, label: str, detail: str).

    Server-side only — never trust the client for this. Called on every
    gated request.
    """
    if not BILLING_ENFORCE:
        return True, "open", "Billing enforcement is off (dev mode)."
    if not user:
        return False, "logged_out", "Log in to use Prhyme."
    if user["is_founding"] or user["sub_status"] == "lifetime":
        return True, "lifetime", "Lifetime access."
    now = time.time()
    if user["sub_status"] == "trial":
        if now < (user["trial_ends_at"] or 0):
            days = max(1, int((user["trial_ends_at"] - now) / 86400) + 1)
            return True, "trial", f"{days} day(s) left in your free trial."
        return False, "trial_expired", "Your 3-day free trial has ended."
    if user["plan"] == "monthly" and user["sub_status"] == "active":
        end = user["current_period_end"] or 0
        if now < end:
            return True, "monthly", "Subscription active."
        return False, "expired", "Your subscription period has ended."
    if user["plan"] == "platinum" and user["sub_status"] == "active":
        end = user["current_period_end"] or 0
        if now < end:
            days = max(1, int((end - now) / 86400))
            return True, "platinum", f"Platinum all-access — {days} day(s) left."
        return False, "expired", "Your Platinum year has ended."
    if user["sub_status"] == "past_due":
        return False, "past_due", "Your last payment failed."
    if user["sub_status"] in ("canceled", "expired"):
        return False, user["sub_status"], "Your subscription is not active."
    return False, "inactive", "No active subscription."


def trial_days_left(user):
    if not user or user["sub_status"] != "trial":
        return 0
    left = (user["trial_ends_at"] or 0) - time.time()
    return max(0, int(left / 86400) + (1 if left > 0 else 0))


def lifetime_price_now():
    """$49 pre-launch price for users 101-500, $99 after."""
    if user_count() < PRELAUNCH_SPOTS:
        return PRELAUNCH_LIFETIME_PRICE
    return LIFETIME_PRICE


def public_status(user):
    """Safe-for-frontend status dict (no secrets)."""
    if not user:
        return {"logged_in": False}
    active, label, detail = subscription_state(user)
    return {
        "logged_in": True,
        "email": user["email"],
        "active": active,
        "plan_label": label,
        "detail": detail,
        "is_founding": bool(user["is_founding"]),
        "founding_number": user["founding_number"],
        "is_owner": bool(user["is_owner"]),
        "trial_days_left": trial_days_left(user),
        "founding_spots_left": founding_spots_left(),
    }


# ------------------------------------------------------- password reset
def issue_reset_token(email):
    user = get_user_by_email(email)
    # Always "succeed" publicly to avoid leaking which emails exist.
    if not user:
        return None
    token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    update_user(user["id"], reset_token_hash=token_hash,
                reset_expires_at=time.time() + 3600)
    return token


def consume_reset_token(token):
    token_hash = hashlib.sha256((token or "").encode()).hexdigest()
    con = _connect()
    try:
        row = con.execute(
            "SELECT * FROM users WHERE reset_token_hash = ?",
            (token_hash,)).fetchone()
        user = _row_to_dict(row)
    finally:
        con.close()
    if not user:
        return None
    if time.time() > (user["reset_expires_at"] or 0):
        return None
    return user


# ------------------------------------------------------- two-factor auth
# TOTP (RFC 6238) + single-use backup codes. All stdlib — see totp_auth.py.
# Rate limiting: 5 failed attempts → 15-min lockout. All attempts logged.

_TOTP_MAX_ATTEMPTS = 5
_TOTP_LOCKOUT_SECS = 900  # 15 minutes


def totp_setup_start(uid):
    """Begin 2FA enrollment: generate secret + backup codes.

    Returns (secret, provisioning_uri, qr_svg, backup_codes) or (None, ...) on error.
    The secret is NOT yet enabled — user must verify a code first.
    """
    import totp_auth as _ta
    import qr_svg as _qr
    user = get_user(uid)
    if not user:
        return None, None, None, None
    secret = _ta.generate_secret()
    codes, hashes = _ta.generate_backup_codes()
    # Store secret as pending (not enabled until verified).
    update_user(uid, totp_secret=secret,
                totp_backup_codes=json_dumps(hashes),
                totp_enabled=0, totp_failed_attempts=0,
                totp_locked_until=None)
    uri = _ta.provisioning_uri(secret, user["email"])
    svg = _qr.qr_svg(uri)
    return secret, uri, svg, codes


def totp_setup_verify(uid, code):
    """Verify a TOTP code during enrollment. Enables 2FA on success."""
    import totp_auth as _ta
    user = get_user(uid)
    if not user or not user.get("totp_secret"):
        return False, "No 2FA setup in progress."
    if _ta.verify_totp(user["totp_secret"], code):
        update_user(uid, totp_enabled=1, totp_failed_attempts=0,
                    totp_locked_until=None)
        return True, "Two-factor authentication enabled."
    return False, "Invalid code — try again."


def totp_disable(uid, password):
    """Disable 2FA. Requires password confirmation."""
    user = get_user(uid)
    if not user:
        return False, "User not found."
    if not verify_password(password, user["password_hash"]):
        return False, "Incorrect password."
    update_user(uid, totp_secret=None, totp_enabled=0,
                totp_backup_codes=None, totp_failed_attempts=0,
                totp_locked_until=None,
                totp_recovery_requested_at=None,
                totp_recovery_expires_at=None)
    return True, "Two-factor authentication disabled."


def totp_verify_login(uid, code):
    """Verify TOTP or backup code during login.

    Returns (ok: bool, message: str, used_backup: bool).
    Enforces rate limiting with progressive lockout.
    """
    import totp_auth as _ta
    user = get_user(uid)
    if not user or not user.get("totp_enabled"):
        return False, "2FA is not enabled for this account.", False
    now = time.time()
    # Check lockout.
    if (user.get("totp_locked_until") or 0) > now:
        remaining = int(user["totp_locked_until"] - now)
        _log_security(uid, "totp_locked_attempt",
                      f"Attempt during lockout ({remaining}s left)")
        return False, f"Too many failed attempts. Try again in {remaining}s.", False
    # Try TOTP first.
    if user.get("totp_secret") and _ta.verify_totp(user["totp_secret"], code):
        update_user(uid, totp_failed_attempts=0, totp_locked_until=None)
        _log_security(uid, "totp_success", "TOTP login verified")
        return True, "Verified.", False
    # Try backup codes.
    try:
        hashes = json_loads(user.get("totp_backup_codes") or "[]")
    except Exception:
        hashes = []
    valid, remaining = _ta.verify_backup_code(code, hashes)
    if valid:
        update_user(uid, totp_backup_codes=json_dumps(remaining),
                    totp_failed_attempts=0, totp_locked_until=None)
        _log_security(uid, "totp_backup_used",
                      f"Backup code used, {len(remaining)} remaining")
        return True, (f"Verified with backup code. "
                      f"{len(remaining)} codes remaining."), True
    # Failed attempt.
    attempts = (user.get("totp_failed_attempts") or 0) + 1
    if attempts >= _TOTP_MAX_ATTEMPTS:
        update_user(uid, totp_failed_attempts=attempts,
                    totp_locked_until=now + _TOTP_LOCKOUT_SECS)
        _log_security(uid, "totp_locked",
                      f"{attempts} failed attempts — locked 15 min")
        return False, ("Too many failed attempts. "
                       "Account locked for 15 minutes."), False
    update_user(uid, totp_failed_attempts=attempts)
    _log_security(uid, "totp_failed", f"Failed attempt {attempts}")
    return False, f"Invalid code. {attempts} of {_TOTP_MAX_ATTEMPTS} attempts.", False


def totp_regenerate_backup_codes(uid):
    """Generate fresh backup codes (invalidates old ones)."""
    import totp_auth as _ta
    user = get_user(uid)
    if not user or not user.get("totp_enabled"):
        return None, "2FA is not enabled."
    codes, hashes = _ta.generate_backup_codes()
    update_user(uid, totp_backup_codes=json_dumps(hashes))
    _log_security(uid, "totp_backup_regenerated", "New backup codes issued")
    return codes, None


def json_dumps(obj):
    import json as _j
    return _j.dumps(obj)


def json_loads(s):
    import json as _j
    return _j.loads(s) if s else []


# ------------------------------------------------------- security logging
def _log_security(uid, event, detail=""):
    """Append to security audit log. Rate-limited writes."""
    try:
        con = _connect()
        con.execute(
            """CREATE TABLE IF NOT EXISTS security_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                uid INTEGER, event TEXT NOT NULL,
                detail TEXT, ip TEXT, created_at REAL NOT NULL)""")
        con.execute(
            "INSERT INTO security_log (uid, event, detail, created_at)"
            " VALUES (?, ?, ?, ?)",
            (uid, event, detail[:500], time.time()))
        con.commit()
    except Exception:
        pass
    finally:
        try:
            con.close()
        except Exception:
            pass


def get_security_log(uid, limit=50):
    """Recent security events for a user (for account page)."""
    try:
        con = _connect()
        rows = con.execute(
            "SELECT event, detail, created_at FROM security_log"
            " WHERE uid = ? ORDER BY id DESC LIMIT ?",
            (uid, limit)).fetchall()
        return [dict(r) for r in rows]
    except Exception:
        return []
    finally:
        try:
            con.close()
        except Exception:
            pass


# ------------------------------------------------------- account recovery
# Lost 2FA device: email-verified request starts a 48-hour waiting period
# (anti-social-engineering). After the wait, user can disable 2FA via a
# recovery token sent to their email. Security questions are an optional
# additional backup.

_RECOVERY_WAIT_SECS = 48 * 3600  # 48 hours


def totp_recovery_request(uid):
    """Start the 48h recovery wait for a lost 2FA device.

    Returns (ok, message). Logs the request. In production, an email
    would be sent here (logged for now).
    """
    user = get_user(uid)
    if not user or not user.get("totp_enabled"):
        return False, "2FA is not enabled."
    now = time.time()
    # If a request is already pending and not expired, report the wait.
    exp = user.get("totp_recovery_expires_at") or 0
    if exp > now:
        hrs = int((exp - now) / 3600)
        return False, (f"Recovery already requested. "
                       f"{hrs} hour(s) remaining in the waiting period.")
    update_user(uid,
                totp_recovery_requested_at=now,
                totp_recovery_expires_at=now + _RECOVERY_WAIT_SECS)
    _log_security(uid, "totp_recovery_requested",
                  "48h recovery wait started for lost 2FA device")
    # TODO: send email notification when SMTP is wired.
    print(f"[SECURITY] 2FA recovery requested for uid={uid} "
          f"({user['email']}) — eligible after 48h", flush=True)
    return True, ("Recovery requested. For your protection, there is a "
                  "48-hour waiting period before 2FA can be disabled. "
                  "You will be notified by email.")


def totp_recovery_complete(uid):
    """Complete recovery after the 48h wait — disables 2FA."""
    user = get_user(uid)
    if not user or not user.get("totp_enabled"):
        return False, "2FA is not enabled."
    now = time.time()
    exp = user.get("totp_recovery_expires_at") or 0
    req = user.get("totp_recovery_requested_at") or 0
    if not req:
        return False, "No recovery request found."
    if now < exp:
        hrs = int((exp - now) / 3600) + 1
        return False, (f"Waiting period not complete. "
                       f"{hrs} hour(s) remaining.")
    # Wait complete — disable 2FA.
    update_user(uid, totp_secret=None, totp_enabled=0,
                totp_backup_codes=None, totp_failed_attempts=0,
                totp_locked_until=None,
                totp_recovery_requested_at=None,
                totp_recovery_expires_at=None)
    _log_security(uid, "totp_recovery_completed",
                  "2FA disabled after 48h recovery wait")
    return True, ("2FA has been disabled. Please set it up again "
                  "on your new device.")


def totp_recovery_cancel(uid):
    """Cancel a pending recovery request (e.g. found the device)."""
    update_user(uid, totp_recovery_requested_at=None,
                totp_recovery_expires_at=None)
    _log_security(uid, "totp_recovery_cancelled", "User cancelled recovery")
    return True, "Recovery request cancelled."


# ------------------------------------------------------- security questions
_SEC_Q_MIN_LEN = 4


def _hash_answer(answer):
    salt = secrets.token_hex(8)
    dk = hashlib.pbkdf2_hmac("sha256", answer.strip().lower().encode(),
                             salt.encode(), 100000)
    return f"pbkdf2_sha256$100000${salt}${dk.hex()}"


def set_security_questions(uid, q1_answer, q2_answer):
    """Set two security question answers (hashed)."""
    if len((q1_answer or "").strip()) < _SEC_Q_MIN_LEN or \
       len((q2_answer or "").strip()) < _SEC_Q_MIN_LEN:
        return False, "Answers must be at least 4 characters."
    update_user(uid,
                sec_q1_hash=_hash_answer(q1_answer),
                sec_q2_hash=_hash_answer(q2_answer))
    _log_security(uid, "sec_questions_set", "Security questions updated")
    return True, "Security questions saved."


def verify_security_questions(uid, q1_answer, q2_answer):
    """Verify both security question answers."""
    user = get_user(uid)
    if not user or not user.get("sec_q1_hash"):
        return False
    for ans, stored in [(q1_answer, user["sec_q1_hash"]),
                        (q2_answer, user["sec_q2_hash"])]:
        try:
            algo, iters, salt, hexhash = stored.split("$")
            dk = hashlib.pbkdf2_hmac(
                "sha256", ans.strip().lower().encode(),
                salt.encode(), int(iters))
            if not hmac.compare_digest(dk.hex(), hexhash):
                return False
        except (ValueError, AttributeError):
            return False
    _log_security(uid, "sec_questions_verified",
                  "Security questions answered correctly")
    return True


def has_security_questions(uid):
    user = get_user(uid)
    return bool(user and user.get("sec_q1_hash"))


# ------------------------------------------------------- Stripe helpers
def _stripe():
    try:
        import stripe as _s
    except ImportError:
        return None
    if not stripe_configured():
        return None
    _s.api_key = STRIPE_SECRET_KEY
    return _s


def create_checkout_session(user, plan, base_url):
    """Create a Stripe Checkout Session. Returns (url, error)."""
    s = _stripe()
    if s is None:
        return None, ("Stripe is not configured yet — Daryl needs to paste "
                      "his API keys into billing_core.py (STRIPE_SECRET_KEY).")
    if plan == "monthly":
        price_data = {"currency": "usd", "unit_amount": int(MONTHLY_PRICE * 100),
                      "recurring": {"interval": "month"},
                      "product_data": {"name": "Prhyme Monthly"}}
        mode = "subscription"
    elif plan == "platinum":
        price_data = {"currency": "usd", "unit_amount": int(PLATINUM_PRICE * 100),
                      "recurring": {"interval": "year"},
                      "product_data": {
                          "name": "Prhyme Platinum — All-Access Annual",
                          "description": (
                              "Everything Prhyme offers for a full year: "
                              "full songs, full lyrics, all 1683+ sounds, "
                              "all 17 genres, priority generation, and every "
                              "new feature the moment it ships.")}}
        mode = "subscription"
    elif plan == "lifetime":
        amount = lifetime_price_now()
        price_data = {"currency": "usd", "unit_amount": int(amount * 100),
                      "product_data": {"name": "Prhyme Lifetime"}}
        mode = "payment"
    else:
        return None, "Unknown plan."

    # Reuse or create the Stripe customer.
    customer_id = user.get("stripe_customer_id")
    if not customer_id:
        customer = s.Customer.create(email=user["email"],
                                     metadata={"prhyme_user_id": user["id"]})
        customer_id = customer.id
        update_user(user["id"], stripe_customer_id=customer_id)

    sess = s.checkout.Session.create(
        customer=customer_id,
        mode=mode,
        line_items=[{"price_data": price_data, "quantity": 1}],
        metadata={"prhyme_user_id": user["id"], "prhyme_plan": plan},
        success_url=base_url.rstrip("/") + "/account?paid=1",
        cancel_url=base_url.rstrip("/") + "/pricing?canceled=1",
    )
    return sess.url, None


def handle_webhook(payload, sig_header):
    """Process a Stripe webhook. Returns (ok: bool, message: str)."""
    s = _stripe()
    if s is None:
        return False, "Stripe not configured."
    try:
        event = s.Webhook.construct_event(payload, sig_header,
                                          STRIPE_WEBHOOK_SECRET)
    except Exception as e:  # bad signature etc.
        return False, f"Webhook verification failed: {e}"

    etype = event.get("type", "")
    obj = event.get("data", {}).get("object", {}) or {}

    def _uid():
        md = obj.get("metadata") or {}
        try:
            return int(md.get("prhyme_user_id") or 0)
        except (TypeError, ValueError):
            return 0

    if etype == "checkout.session.completed":
        uid, plan = _uid(), (obj.get("metadata") or {}).get("prhyme_plan")
        _amount = (obj.get("amount_total") or 0) / 100.0
        _currency = (obj.get("currency") or "usd").lower()
        _sess_id = obj.get("id", "")
        if uid and plan == "monthly":
            sub_id = obj.get("subscription")
            update_user(uid, plan="monthly", sub_status="active",
                        stripe_subscription_id=sub_id,
                        current_period_end=time.time() + 30 * 86400)
            record_purchase(uid, plan, _amount or MONTHLY_PRICE,
                            _currency, _sess_id)
        elif uid and plan == "platinum":
            sub_id = obj.get("subscription")
            update_user(uid, plan="platinum", sub_status="active",
                        stripe_subscription_id=sub_id,
                        current_period_end=time.time() + 365 * 86400)
            record_purchase(uid, plan, _amount or PLATINUM_PRICE,
                            _currency, _sess_id)
        elif uid and plan == "lifetime":
            update_user(uid, plan="lifetime", sub_status="lifetime")
            record_purchase(uid, plan, _amount or lifetime_price_now(),
                            _currency, _sess_id)
    elif etype == "customer.subscription.updated":
        uid = _uid()
        status = obj.get("status")  # active|past_due|canceled|unpaid...
        cpe = (obj.get("current_period_end")
               or int(time.time() + 30 * 86400))
        if uid and status:
            mapped = {"active": "active", "trialing": "active",
                      "past_due": "past_due"}.get(status, "expired")
            update_user(uid, sub_status=mapped, current_period_end=float(cpe))
    elif etype == "customer.subscription.deleted":
        uid = _uid()
        if uid:
            update_user(uid, sub_status="canceled")
    elif etype == "invoice.payment_failed":
        uid = _uid()
        if uid:
            update_user(uid, sub_status="past_due")
    return True, f"Handled {etype}."


def cancel_subscription(user):
    """Cancel at Stripe (if configured) and mark canceled locally."""
    s = _stripe()
    sub_id = user.get("stripe_subscription_id")
    if s is not None and sub_id:
        try:
            s.Subscription.delete(sub_id)
        except Exception:
            pass  # still mark locally; Stripe dashboard is source of truth
    update_user(user["id"], sub_status="canceled")
    return True


# ------------------------------------------------------- purchase receipts
def record_purchase(uid, plan, amount, currency="usd", stripe_session_id="",
                    stripe_invoice_id=""):
    """Log a completed purchase for receipts/invoices."""
    con = _connect()
    try:
        cur = con.execute(
            "INSERT INTO purchases (uid, plan, amount, currency,"
            " stripe_session_id, stripe_invoice_id, created_at)"
            " VALUES (?,?,?,?,?,?,?)",
            (uid, plan, amount, currency, stripe_session_id,
             stripe_invoice_id, time.time()))
        con.commit()
        track_event("purchase", plan)
        return cur.lastrowid
    finally:
        con.close()


def get_purchases(uid, limit=50):
    """Purchase history for receipts page."""
    con = _connect()
    try:
        rows = con.execute(
            "SELECT * FROM purchases WHERE uid = ?"
            " ORDER BY id DESC LIMIT ?", (uid, limit)).fetchall()
        return [dict(r) for r in rows]
    finally:
        con.close()


# ------------------------------------------------------- session management
def register_session(uid, ip="", user_agent=""):
    """Track a login session. Returns session token."""
    token = secrets.token_hex(32)
    con = _connect()
    try:
        now = time.time()
        con.execute(
            "INSERT INTO sessions (token, uid, ip, user_agent,"
            " created_at, last_seen) VALUES (?,?,?,?,?,?)",
            (token, uid, ip[:60], user_agent[:200], now, now))
        con.commit()
    finally:
        con.close()
    return token


def touch_session(token):
    """Update last-seen for a session."""
    try:
        con = _connect()
        con.execute("UPDATE sessions SET last_seen = ? WHERE token = ?",
                    (time.time(), token))
        con.commit()
    except Exception:
        pass
    finally:
        try:
            con.close()
        except Exception:
            pass


def get_sessions(uid):
    """Active sessions for a user (last 30 days)."""
    con = _connect()
    try:
        rows = con.execute(
            "SELECT token, ip, user_agent, created_at, last_seen"
            " FROM sessions WHERE uid = ? AND last_seen > ?"
            " ORDER BY last_seen DESC",
            (uid, time.time() - 30 * 86400)).fetchall()
        return [dict(r) for r in rows]
    finally:
        con.close()


def revoke_session(uid, token):
    """Revoke one session (not the current one — handled by caller)."""
    con = _connect()
    try:
        con.execute("DELETE FROM sessions WHERE uid = ? AND token = ?",
                    (uid, token))
        con.commit()
        _log_security(uid, "session_revoked", f"Token {token[:8]}… revoked")
    finally:
        con.close()


def revoke_all_sessions(uid, except_token=None):
    """Revoke all sessions except the current one."""
    con = _connect()
    try:
        if except_token:
            con.execute("DELETE FROM sessions WHERE uid = ? AND token != ?",
                        (uid, except_token))
        else:
            con.execute("DELETE FROM sessions WHERE uid = ?", (uid,))
        con.commit()
        _log_security(uid, "sessions_revoked_all",
                      "All other sessions revoked")
    finally:
        con.close()


# ------------------------------------------------------- analytics (privacy-respecting)
# Aggregated event counts only — no PII, no per-user tracking.
# Daryl uses this to see conversion funnels (signup → trial → paid).
def track_event(event, plan_label=None):
    """Log an analytics event. Fire-and-forget, never blocks."""
    try:
        con = _connect()
        con.execute(
            "INSERT INTO analytics (event, plan_label, created_at)"
            " VALUES (?,?,?)",
            (event[:60], (plan_label or "")[:30], time.time()))
        con.commit()
    except Exception:
        pass
    finally:
        try:
            con.close()
        except Exception:
            pass


def analytics_summary(days=30):
    """Event counts for the last N days, for Daryl's dashboard."""
    con = _connect()
    try:
        since = time.time() - days * 86400
        rows = con.execute(
            "SELECT event, plan_label, COUNT(*) c FROM analytics"
            " WHERE created_at > ? GROUP BY event, plan_label"
            " ORDER BY c DESC",
            (since,)).fetchall()
        return [dict(r) for r in rows]
    except Exception:
        return []
    finally:
        con.close()
