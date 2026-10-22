"""Prhyme payments via PayPal (subscriptions + one-time).

Daryl-ordered 2026-10-16: "change everything to PayPal instead at least for
now". This module replaces Stripe as the active provider; the Stripe code
(billing_core.py / billing_payments.py) stays in place but dormant.

Stdlib-only (urllib) — no new dependencies, phone-safe.

What it does:
  * Subscriptions: $9/month ("monthly") and $499/year ("platinum") via the
    PayPal Subscriptions API. User approves on PayPal's site; the
    BILLING.SUBSCRIPTION.ACTIVATED webhook activates the tier in
    billing_core (same fields Stripe used: plan / sub_status / current_period_end),
    so the existing server-side gate keeps working unchanged.
  * One-time Orders API: $4,999 lifetime, pay-per-use credits
    (beat $2, master $3, video $2, distribute $5, stems $1) and beat-store
    purchases at server-side prices. Capture happens on the return URL AND
    via the PAYMENT.CAPTURE.COMPLETED webhook; grants are idempotent on the
    PayPal order id, so a double capture can never double-grant.
  * Pay-per-use credits land in the same `payg_credits` table the Stripe
    module used, so generation endpoints keep calling
    consume_generation(uid, item) with no changes.

SANDBOX until Daryl completes the go-live checklist in PAYPAL_SETUP.md.
No live money moves here: amounts come from the tables below, never the client.
"""
import base64
import json
import time
import urllib.parse
import urllib.request
from datetime import datetime

import billing_core as bc

# ------------------------------------------------------------------ config
# Self-load ~/.paypal_env when the launcher didn't export it (2026-10-21):
# checkout must work no matter how the server was started (Termux `restart`,
# watchdog, manual). Existing environment always wins; the file only fills
# gaps. Values are never logged.
def _load_paypal_env_file():
    import os
    path = os.path.expanduser("~/.paypal_env")
    try:
        with open(path, "r") as f:
            for line in f:
                line = line.strip()
                if line.startswith("export "):
                    line = line[len("export "):].lstrip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                k = k.strip()
                v = v.strip().strip('"').strip("'")
                if k and k not in os.environ:
                    os.environ[k] = v
    except OSError:
        pass


_load_paypal_env_file()

# Daryl: create a REST API app at https://developer.paypal.com/dashboard
# (log in with your PayPal account -> Dashboard -> Create App), then paste
# the Client ID + Secret below. Keep MODE="sandbox" while testing.
PAYPAL_CLIENT_ID = __import__("os").environ.get(
    "PAYPAL_CLIENT_ID", "REPLACE_WITH_YOUR_PAYPAL_CLIENT_ID")
PAYPAL_CLIENT_SECRET = __import__("os").environ.get(
    "PAYPAL_CLIENT_SECRET", "REPLACE_WITH_YOUR_PAYPAL_CLIENT_SECRET")
PAYPAL_MODE = __import__("os").environ.get("PAYPAL_MODE", "sandbox").lower()
PAYPAL_WEBHOOK_ID = __import__("os").environ.get("PAYPAL_WEBHOOK_ID", "")
PAYPAL_PLAN_MONTHLY = __import__("os").environ.get("PAYPAL_PLAN_MONTHLY", "")
PAYPAL_PLAN_PLATINUM = __import__("os").environ.get("PAYPAL_PLAN_PLATINUM", "")

# Pricing (USD) — Daryl-confirmed 2026-10-14. Do not change without his word.
PRICE_MONTHLY = 9.00
PRICE_PLATINUM = 499.00
PRICE_LIFETIME = 4999.00
PAY_PER_USE = {
    "beat": 2.00,
    "master": 3.00,
    "video": 2.00,
    "distribute": 5.00,
    "stems": 1.00,
}

SUCCESS_PATH = "/account?paid=1"
CANCEL_PATH = "/pricing?canceled=1"
RETURN_PATH = "/api/billing/paypal/return"


def paypal_configured():
    """True only when Daryl has pasted real (non-placeholder) credentials."""
    return (
        PAYPAL_CLIENT_ID and "REPLACE_WITH" not in PAYPAL_CLIENT_ID
        and PAYPAL_CLIENT_SECRET and "REPLACE_WITH" not in PAYPAL_CLIENT_SECRET
    )


# ------------------------------------------------------------------ REST client
class PayPalError(Exception):
    pass


_token_cache = {"token": None, "expires_at": 0.0}


def _base():
    return ("https://api-m.sandbox.paypal.com"
            if PAYPAL_MODE != "live" else "https://api-m.paypal.com")


def _access_token():
    """OAuth2 client-credentials token, cached until near expiry."""
    if (_token_cache["token"]
            and time.time() < _token_cache["expires_at"] - 60):
        return _token_cache["token"]
    creds = base64.b64encode(
        f"{PAYPAL_CLIENT_ID}:{PAYPAL_CLIENT_SECRET}".encode()).decode()
    req = urllib.request.Request(
        _base() + "/v1/oauth2/token",
        data=urllib.parse.urlencode(
            {"grant_type": "client_credentials"}).encode(),
        headers={"Authorization": f"Basic {creds}",
                 "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            body = json.loads(r.read().decode())
    except Exception as e:
        raise PayPalError(f"PayPal auth failed: {e}")
    tok = body.get("access_token")
    if not tok:
        raise PayPalError("PayPal auth returned no access token.")
    _token_cache["token"] = tok
    _token_cache["expires_at"] = time.time() + int(
        body.get("expires_in", 32400))
    return tok


def _api(method, path, body=None, idem_key=None):
    """Call the PayPal REST API. Returns parsed JSON. Raises PayPalError."""
    if not paypal_configured():
        raise PayPalError("PayPal is not configured — create a REST API app "
                          "at developer.paypal.com and set PAYPAL_CLIENT_ID / "
                          "PAYPAL_CLIENT_SECRET.")
    data = json.dumps(body).encode() if body is not None else None
    headers = {"Authorization": f"Bearer {_access_token()}",
               "Accept": "application/json"}
    if data is not None:
        headers["Content-Type"] = "application/json"
    if idem_key:
        headers["PayPal-Request-Id"] = idem_key
    req = urllib.request.Request(_base() + path, data=data,
                                 headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=25) as r:
            raw = r.read().decode()
            return json.loads(raw) if raw.strip() else {}
    except urllib.error.HTTPError as e:
        detail = e.read().decode(errors="replace")[:500]
        raise PayPalError(f"PayPal {method} {path} -> HTTP {e.code}: {detail}")
    except Exception as e:
        raise PayPalError(f"PayPal {method} {path} failed: {e}")


def _link(obj, rel):
    for l in obj.get("links", []) or []:
        if l.get("rel") == rel:
            return l.get("href")
    return None


# ------------------------------------------------------------------ tables
def _ensure_tables():
    con = bc._connect()
    try:
        # Shared with the Stripe module: credits granted by either provider
        # spend from the same balance.
        con.execute(
            "CREATE TABLE IF NOT EXISTS payg_credits ("
            " uid INTEGER NOT NULL, item TEXT NOT NULL, credits INTEGER NOT NULL DEFAULT 0,"
            " updated_at REAL NOT NULL, PRIMARY KEY (uid, item))")
        con.execute(
            "CREATE TABLE IF NOT EXISTS beat_purchases ("
            " id INTEGER PRIMARY KEY AUTOINCREMENT, uid INTEGER NOT NULL,"
            " beat_id TEXT NOT NULL, title TEXT NOT NULL DEFAULT '',"
            " license TEXT NOT NULL DEFAULT 'lease', amount REAL NOT NULL DEFAULT 0,"
            " currency TEXT NOT NULL DEFAULT 'usd', stripe_session_id TEXT NOT NULL DEFAULT '',"
            " created_at REAL NOT NULL)")
        con.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_beat_purchases_uid_beat"
            " ON beat_purchases (uid, beat_id)")
        # PayPal-specific: subscription refs + order idempotency.
        con.execute(
            "CREATE TABLE IF NOT EXISTS paypal_subscriptions ("
            " uid INTEGER PRIMARY KEY, subscription_id TEXT NOT NULL,"
            " plan TEXT NOT NULL DEFAULT '', status TEXT NOT NULL DEFAULT '',"
            " updated_at REAL NOT NULL)")
        con.execute(
            "CREATE TABLE IF NOT EXISTS paypal_orders ("
            " order_id TEXT PRIMARY KEY, uid INTEGER NOT NULL,"
            " purpose TEXT NOT NULL DEFAULT '', ref TEXT NOT NULL DEFAULT '',"
            " status TEXT NOT NULL DEFAULT '', granted INTEGER NOT NULL DEFAULT 0,"
            " created_at REAL NOT NULL, updated_at REAL NOT NULL)")
        con.commit()
    finally:
        con.close()


# ------------------------------------------------------------------ one-time setup
def create_product_and_plans():
    """Create the Prhyme product + monthly/platinum plans (run ONCE).

    Returns {"product_id": ..., "monthly_plan_id": ..., "platinum_plan_id": ...}.
    Paste the two plan ids into PAYPAL_PLAN_MONTHLY / PAYPAL_PLAN_PLATINUM.
    """
    prod = _api("POST", "/v1/catalogs/products", {
        "name": "Prhyme",
        "description": "Prhyme music creation platform — subscriptions and credits.",
        "type": "SERVICE",
        "category": "SOFTWARE",
    })
    product_id = prod.get("id")

    def _plan(name, desc, unit, value):
        p = _api("POST", "/v1/billing/plans", {
            "product_id": product_id,
            "name": name,
            "description": desc,
            "billing_cycles": [{
                "frequency": {"interval_unit": unit, "interval_count": 1},
                "tenure_type": "REGULAR",
                "sequence": 1,
                "total_cycles": 0,  # until cancelled
                "pricing_scheme": {
                    "fixed_price": {"value": f"{value:.2f}",
                                    "currency_code": "USD"}}
            }],
            "payment_preferences": {
                "auto_bill_outstanding": True,
                "payment_failure_threshold": 3,
            },
        })
        return p.get("id")

    return {
        "product_id": product_id,
        "monthly_plan_id": _plan("Prhyme Monthly",
                                 "Full Prhyme access, billed monthly.",
                                 "MONTH", PRICE_MONTHLY),
        "platinum_plan_id": _plan("Prhyme Platinum — Annual",
                                  "Everything Prhyme offers for a full year.",
                                  "YEAR", PRICE_PLATINUM),
    }


# ------------------------------------------------------------------ subscriptions
def _plan_id(plan):
    return {"monthly": PAYPAL_PLAN_MONTHLY,
            "platinum": PAYPAL_PLAN_PLATINUM}.get(plan, "")


def create_subscription(user, plan, base_url):
    """Create a PayPal subscription. Returns (approval_url, error)."""
    _ensure_tables()
    if plan not in ("monthly", "platinum"):
        return None, "Unknown plan."
    plan_id = _plan_id(plan)
    if not plan_id:
        return None, (f"PayPal {plan} plan id is not set — run "
                      "create_product_and_plans() once and paste the plan id "
                      "into PAYPAL_PLAN_MONTHLY / PAYPAL_PLAN_PLATINUM.")
    try:
        sub = _api("POST", "/v1/billing/subscriptions", {
            "plan_id": plan_id,
            "custom_id": f"prhyme:sub:{plan}:{user['id']}",
            "application_context": {
                "brand_name": "Prhyme",
                "user_action": "SUBSCRIBE_NOW",
                "return_url": base_url.rstrip("/") + RETURN_PATH + "?kind=sub",
                "cancel_url": base_url.rstrip("/") + CANCEL_PATH,
            },
        }, idem_key=f"prhyme-sub-{plan}-{user['id']}-{int(time.time() // 3600)}")
    except PayPalError as e:
        return None, str(e)
    url = _link(sub, "approve")
    if not url:
        return None, "PayPal did not return an approval link."
    return url, None


def cancel_subscription(user):
    """Cancel the PayPal subscription (if any) and mark canceled locally."""
    _ensure_tables()
    con = bc._connect()
    try:
        row = con.execute(
            "SELECT subscription_id FROM paypal_subscriptions WHERE uid = ?",
            (user["id"],)).fetchone()
    finally:
        con.close()
    sub_id = row["subscription_id"] if row else None
    if sub_id:
        try:
            _api("POST", f"/v1/billing/subscriptions/{sub_id}/cancel",
                 {"reason": "Canceled from Prhyme account page."})
        except PayPalError:
            pass  # still mark locally; PayPal dashboard is source of truth
    bc.update_user(user["id"], sub_status="canceled")
    return True


# ------------------------------------------------------------------ one-time orders
def _order(user, amount, description, custom_id, base_url, idem_key):
    try:
        order = _api("POST", "/v2/checkout/orders", {
            "intent": "CAPTURE",
            "purchase_units": [{
                "amount": {"currency_code": "USD",
                           "value": f"{amount:.2f}"},
                "description": description,
                "custom_id": custom_id,
            }],
            "application_context": {
                "brand_name": "Prhyme",
                "user_action": "PAY_NOW",
                "return_url": base_url.rstrip("/") + RETURN_PATH,
                "cancel_url": base_url.rstrip("/") + CANCEL_PATH,
            },
        }, idem_key=idem_key)
    except PayPalError as e:
        return None, str(e)
    url = _link(order, "approve")
    if not url:
        return None, "PayPal did not return an approval link."
    return url, None


def create_lifetime_order(user, base_url):
    """One-time $4,999 lifetime purchase. Returns (approval_url, error)."""
    _ensure_tables()
    return _order(user, PRICE_LIFETIME, "Prhyme Lifetime — all-access, forever",
                  f"prhyme:order:lifetime:{user['id']}:x", base_url,
                  f"prhyme-lifetime-{user['id']}-{int(time.time() // 3600)}")


def create_payg_order(user, item, base_url):
    """One pay-per-use credit. Returns (approval_url, error)."""
    _ensure_tables()
    if item not in PAY_PER_USE:
        return None, f"Unknown item: {item}."
    amount = PAY_PER_USE[item]
    return _order(user, amount, f"Prhyme — 1 x {item} (pay per use)",
                  f"prhyme:order:payg:{user['id']}:{item}", base_url,
                  f"prhyme-payg-{item}-{user['id']}-{int(time.time())}")


# ------------------------------------------------------------------ beat store
_beat_lookup = None


def register_beat_lookup(fn):
    """Register server-side beat-listing lookup: fn(beat_id) -> dict|None.

    The dict must have: id, title, price (float USD), license ('lease'|'exclusive').
    app.py wires this to the store backend. Prices NEVER come from the client.
    """
    global _beat_lookup
    _beat_lookup = fn


def get_beat_listing(beat_id):
    if _beat_lookup is None:
        return None
    try:
        return _beat_lookup(beat_id)
    except Exception:
        return None


def create_beat_order(user, beat_id, base_url):
    """One-time beat purchase at the listing's server-side price."""
    _ensure_tables()
    beat = get_beat_listing(beat_id)
    if not beat:
        return None, "Beat not found."
    try:
        price = float(beat.get("price") or 0)
    except (TypeError, ValueError):
        price = 0
    if price <= 0:
        return None, "This listing has no buyable price."
    if str(beat.get("seller_uid") or "") == str(user["id"]):
        return None, "You can't buy your own beat."
    if beat_owned(user["id"], beat_id):
        return None, "You already own this beat."
    license_label = str(beat.get("license") or "lease")
    return _order(user, price,
                  f"Prhyme Beat — {beat.get('title', beat_id)} ({license_label} license)",
                  f"prhyme:order:beat:{user['id']}:{beat_id}", base_url,
                  f"prhyme-beat-{beat_id}-{user['id']}-{int(time.time())}")


# ------------------------------------------------------------------ credits (shared tables)
def grant_payg_credit(uid, item, n=1):
    _ensure_tables()
    con = bc._connect()
    try:
        con.execute(
            "INSERT INTO payg_credits (uid, item, credits, updated_at)"
            " VALUES (?,?,?,?)"
            " ON CONFLICT(uid, item) DO UPDATE SET"
            " credits = credits + excluded.credits, updated_at = excluded.updated_at",
            (uid, item, n, time.time()))
        con.commit()
    finally:
        con.close()


def payg_balance(uid):
    _ensure_tables()
    con = bc._connect()
    try:
        rows = con.execute(
            "SELECT item, credits FROM payg_credits WHERE uid = ?", (uid,)).fetchall()
        return {r["item"]: r["credits"] for r in rows}
    finally:
        con.close()


def spend_payg_credit(uid, item):
    _ensure_tables()
    con = bc._connect()
    try:
        cur = con.execute(
            "UPDATE payg_credits SET credits = credits - 1, updated_at = ?"
            " WHERE uid = ? AND item = ? AND credits > 0",
            (time.time(), uid, item))
        con.commit()
        return cur.rowcount > 0
    finally:
        con.close()


def consume_generation(uid, item):
    """Spend allowance first (if billing_core tracks it), else a pay-per-use credit.

    Returns (ok: bool, via: str) where via is 'allowance' | 'pay_per_use' | 'payment_required'.
    Generation endpoints call this before doing expensive work.
    """
    check = getattr(bc, "check_allowance", None)
    if callable(check):
        try:
            res = check(uid, item)
            allowed = res[0] if isinstance(res, (tuple, list)) else bool(res)
            if allowed:
                log = getattr(bc, "log_usage", None)
                if callable(log):
                    try:
                        log(uid, item)
                    except Exception:
                        pass
                return True, "allowance"
        except Exception:
            pass
    if spend_payg_credit(uid, item):
        return True, "pay_per_use"
    return False, "payment_required"


def beat_owned(uid, beat_id):
    _ensure_tables()
    con = bc._connect()
    try:
        row = con.execute(
            "SELECT * FROM beat_purchases WHERE uid = ? AND beat_id = ?",
            (uid, str(beat_id))).fetchone()
        return dict(row) if row else None
    finally:
        con.close()


def record_beat_purchase(uid, beat_id, title, license, amount, currency,
                         provider_ref):
    _ensure_tables()
    con = bc._connect()
    try:
        con.execute(
            "INSERT OR IGNORE INTO beat_purchases"
            " (uid, beat_id, title, license, amount, currency,"
            " stripe_session_id, created_at)"
            " VALUES (?,?,?,?,?,?,?,?)",
            (uid, str(beat_id), title, license, amount, currency,
             provider_ref, time.time()))
        con.commit()
    finally:
        con.close()


# ------------------------------------------------------------------ capture + grants
def _parse_custom_id(custom_id):
    """custom_id forms: prhyme:sub:{plan}:{uid} | prhyme:order:{purpose}:{uid}:{ref}"""
    parts = (custom_id or "").split(":")
    if len(parts) >= 4 and parts[0] == "prhyme" and parts[1] == "sub":
        try:
            return {"kind": "sub", "plan": parts[2], "uid": int(parts[3])}
        except (TypeError, ValueError):
            return None
    if len(parts) >= 5 and parts[0] == "prhyme" and parts[1] == "order":
        try:
            return {"kind": "order", "purpose": parts[2],
                    "uid": int(parts[3]), "ref": ":".join(parts[4:])}
        except (TypeError, ValueError):
            return None
    return None


def _mark_order(order_id, uid, purpose, ref, status, granted):
    _ensure_tables()
    con = bc._connect()
    try:
        con.execute(
            "INSERT INTO paypal_orders"
            " (order_id, uid, purpose, ref, status, granted, created_at, updated_at)"
            " VALUES (?,?,?,?,?,?,?,?)"
            " ON CONFLICT(order_id) DO UPDATE SET"
            " status = excluded.status, granted = excluded.granted,"
            " updated_at = excluded.updated_at",
            (order_id, uid, purpose, ref, status, granted,
             time.time(), time.time()))
        con.commit()
    finally:
        con.close()


def _order_already_granted(order_id):
    _ensure_tables()
    con = bc._connect()
    try:
        row = con.execute(
            "SELECT granted FROM paypal_orders WHERE order_id = ?",
            (order_id,)).fetchone()
        return bool(row and row["granted"])
    finally:
        con.close()


def _grant_from_order(order):
    """Grant whatever a captured order paid for. Idempotent on order id.

    Returns (granted: bool, message: str). granted=False means it was already
    granted before (safe to call twice).
    """
    units = order.get("purchase_units") or []
    pu = units[0] if units else {}
    custom_id = pu.get("custom_id") or ""
    parsed = _parse_custom_id(custom_id)
    order_id = order.get("id", "")
    if not parsed or parsed["kind"] != "order":
        return False, f"Order {order_id}: no Prhyme custom_id."
    uid, purpose, ref = parsed["uid"], parsed["purpose"], parsed["ref"]
    if _order_already_granted(order_id):
        return False, f"Order {order_id}: already granted."
    amount = 0.0
    try:
        amount = float((pu.get("amount") or {}).get("value") or 0)
    except (TypeError, ValueError):
        pass
    captures = ((pu.get("payments") or {}).get("captures")) or []
    provider_ref = captures[0].get("id") if captures else order_id

    if purpose == "lifetime":
        bc.update_user(uid, plan="lifetime", sub_status="lifetime")
        bc.record_purchase(uid, "lifetime", amount or PRICE_LIFETIME,
                           "usd", provider_ref)
        msg = "Lifetime activated."
    elif purpose == "payg":
        if ref not in PAY_PER_USE:
            return False, f"Order {order_id}: unknown pay-per-use item {ref}."
        grant_payg_credit(uid, ref)
        bc.record_purchase(uid, f"payg_{ref}", amount or PAY_PER_USE[ref],
                           "usd", provider_ref)
        msg = f"Granted 1 x {ref} credit."
    elif purpose == "beat":
        beat = get_beat_listing(ref) or {}
        record_beat_purchase(uid, ref, beat.get("title", ref),
                             str(beat.get("license") or "lease"),
                             amount, "usd", provider_ref)
        bc.record_purchase(uid, "beat_purchase", amount, "usd", provider_ref)
        msg = f"Recorded beat purchase {ref}."
    else:
        return False, f"Order {order_id}: unknown purpose {purpose}."
    _mark_order(order_id, uid, purpose, ref, "granted", 1)
    return True, msg


def capture_order(order_id):
    """Capture an approved order and grant it. Called from the return URL.

    Returns (ok: bool, message: str). Safe to call repeatedly.
    """
    try:
        order = _api("GET", f"/v2/checkout/orders/{order_id}")
    except PayPalError as e:
        return False, str(e)
    status = (order.get("status") or "").upper()
    if status == "COMPLETED":
        granted, msg = _grant_from_order(order)
        return True, msg if granted else "Payment already processed."
    if status != "APPROVED":
        return False, f"Order is {status}, not approved."
    try:
        captured = _api("POST", f"/v2/checkout/orders/{order_id}/capture", {},
                        idem_key=f"prhyme-capture-{order_id}")
    except PayPalError as e:
        return False, str(e)
    if (captured.get("status") or "").upper() != "COMPLETED":
        return False, "Capture did not complete."
    granted, msg = _grant_from_order(captured)
    return True, msg if granted else "Payment already processed."


# ------------------------------------------------------------------ webhooks
def verify_webhook(headers, raw_body):
    """Verify a PayPal webhook signature via PayPal's API. Returns bool."""
    if not PAYPAL_WEBHOOK_ID:
        return False
    try:
        event = json.loads(raw_body.decode()
                           if isinstance(raw_body, bytes) else raw_body)
    except Exception:
        return False
    h = {k.lower(): v for k, v in (headers or {}).items()}
    try:
        res = _api("POST", "/v1/notifications/verify-webhook-signature", {
            "auth_algo": h.get("paypal-auth-algo", ""),
            "cert_url": h.get("paypal-cert-url", ""),
            "transmission_id": h.get("paypal-transmission-id", ""),
            "transmission_sig": h.get("paypal-transmission-sig", ""),
            "transmission_time": h.get("paypal-transmission-time", ""),
            "webhook_id": PAYPAL_WEBHOOK_ID,
            "webhook_event": event,
        })
    except PayPalError:
        return False
    return (res.get("verification_status") or "").upper() == "SUCCESS"


def _parse_iso(ts):
    try:
        return datetime.fromisoformat(
            ts.replace("Z", "+00:00")).timestamp()
    except Exception:
        return 0.0


def _activate_subscription(uid, plan, paypal_sub_id, next_billing_time):
    _ensure_tables()
    if plan == "monthly":
        period = _parse_iso(next_billing_time) or (time.time() + 30 * 86400)
        price = PRICE_MONTHLY
    elif plan == "platinum":
        period = _parse_iso(next_billing_time) or (time.time() + 365 * 86400)
        price = PRICE_PLATINUM
    else:
        return False, f"Unknown plan in custom_id: {plan}."
    bc.update_user(uid, plan=plan, sub_status="active",
                   current_period_end=period)
    con = bc._connect()
    try:
        con.execute(
            "INSERT INTO paypal_subscriptions"
            " (uid, subscription_id, plan, status, updated_at)"
            " VALUES (?,?,?,?,?)"
            " ON CONFLICT(uid) DO UPDATE SET subscription_id = excluded.subscription_id,"
            " plan = excluded.plan, status = excluded.status,"
            " updated_at = excluded.updated_at",
            (uid, paypal_sub_id, plan, "active", time.time()))
        con.commit()
    finally:
        con.close()
    bc.record_purchase(uid, plan, price, "usd", paypal_sub_id)
    return True, f"Activated {plan}."


def _sub_status_event(uid, paypal_sub_id, status):
    _ensure_tables()
    con = bc._connect()
    try:
        con.execute(
            "INSERT INTO paypal_subscriptions"
            " (uid, subscription_id, plan, status, updated_at)"
            " VALUES (?,?,?,?,?)"
            " ON CONFLICT(uid) DO UPDATE SET status = excluded.status,"
            " updated_at = excluded.updated_at",
            (uid, paypal_sub_id, "", status, time.time()))
        con.commit()
    finally:
        con.close()
    bc.update_user(uid, sub_status=status)


def _uid_for_subscription(paypal_sub_id):
    _ensure_tables()
    con = bc._connect()
    try:
        row = con.execute(
            "SELECT uid, plan FROM paypal_subscriptions WHERE subscription_id = ?",
            (paypal_sub_id,)).fetchone()
        return (row["uid"], row["plan"]) if row else (0, "")
    finally:
        con.close()


def try_webhook(headers, payload):
    """Handle PayPal webhook events.

    Returns (handled: bool, ok: bool, message: str). Unhandled events return
    (False, ...) so the caller can fall through to other providers.
    """
    if not verify_webhook(headers, payload):
        return False, False, "PayPal webhook verification failed."
    try:
        event = json.loads(payload.decode()
                           if isinstance(payload, bytes) else payload)
    except Exception:
        return False, False, "Bad webhook JSON."
    etype = event.get("event_type", "")
    res = event.get("resource") or {}

    if etype == "BILLING.SUBSCRIPTION.ACTIVATED":
        parsed = _parse_custom_id(res.get("custom_id") or "")
        if not parsed or parsed["kind"] != "sub":
            return True, False, "Subscription has no Prhyme custom_id."
        ok, msg = _activate_subscription(
            parsed["uid"], parsed["plan"], res.get("id", ""),
            (res.get("billing_info") or {}).get("next_billing_time", ""))
        return True, ok, msg

    if etype in ("BILLING.SUBSCRIPTION.CANCELLED",
                 "BILLING.SUBSCRIPTION.SUSPENDED",
                 "BILLING.SUBSCRIPTION.EXPIRED"):
        parsed = _parse_custom_id(res.get("custom_id") or "")
        uid = parsed["uid"] if parsed else 0
        if not uid:
            uid, _ = _uid_for_subscription(res.get("id", ""))
        if not uid:
            return True, False, "Subscription event has no Prhyme user."
        mapped = {"BILLING.SUBSCRIPTION.CANCELLED": "canceled",
                  "BILLING.SUBSCRIPTION.SUSPENDED": "suspended",
                  "BILLING.SUBSCRIPTION.EXPIRED": "expired"}[etype]
        _sub_status_event(uid, res.get("id", ""), mapped)
        return True, True, f"Subscription {mapped}."

    if etype == "BILLING.SUBSCRIPTION.PAYMENT.FAILED":
        parsed = _parse_custom_id(res.get("custom_id") or "")
        uid = parsed["uid"] if parsed else 0
        if not uid:
            uid, _ = _uid_for_subscription(res.get("id", ""))
        if uid:
            bc.update_user(uid, sub_status="past_due")
            return True, True, "Marked past_due."
        return True, False, "Payment-failed event has no Prhyme user."

    if etype == "PAYMENT.SALE.COMPLETED":
        # Recurring payment collected: extend the period, log the receipt.
        uid, plan = _uid_for_subscription(
            res.get("billing_agreement_id", ""))
        if not uid:
            return True, False, "Sale event has no Prhyme user."
        amount = 0.0
        try:
            amount = float((res.get("amount") or {}).get("total") or 0)
        except (TypeError, ValueError):
            pass
        period = (time.time() + 365 * 86400 if plan == "platinum"
                  else time.time() + 30 * 86400)
        bc.update_user(uid, sub_status="active", current_period_end=period)
        bc.record_purchase(uid, plan or "subscription", amount, "usd",
                           res.get("id", ""))
        return True, True, "Renewal recorded."

    if etype == "PAYMENT.CAPTURE.COMPLETED":
        # Fallback grant for one-time orders (in case the return-URL
        # capture was missed). Idempotent on the order id.
        custom_id = res.get("custom_id") or ""
        order_id = ((res.get("supplementary_data") or {})
                    .get("related_ids") or {}).get("order_id", "")
        if not custom_id and order_id:
            try:
                order = _api("GET", f"/v2/checkout/orders/{order_id}")
                units = order.get("purchase_units") or []
                custom_id = (units[0] if units else {}).get("custom_id", "")
            except PayPalError:
                custom_id = ""
        parsed = _parse_custom_id(custom_id)
        if not parsed or parsed["kind"] != "order":
            return True, True, "Capture is not a Prhyme order."
        if _order_already_granted(order_id or res.get("id", "")):
            return True, True, "Capture already granted."
        grant_order = {"id": order_id or res.get("id", ""),
                       "purchase_units": [{
                           "custom_id": custom_id,
                           "amount": {"value": str(
                               (res.get("amount") or {}).get("value") or 0)},
                           "payments": {"captures": [
                               {"id": res.get("id", "")}]}}]}
        granted, msg = _grant_from_order(grant_order)
        return True, True, msg if granted else "Capture already processed."

    return False, True, f"Unhandled PayPal event {etype}."
