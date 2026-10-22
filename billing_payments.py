"""Prhyme pay-per-use + beat-store purchases (Stripe).

Companion to billing_core.py / billing.py. Kept as a separate module so it
merges cleanly with the phone's newer billing code (allowance tracking).

What it does:
  * Pay-per-use credits: beat $2, master $3, video $2, distribute $5, stems $1.
    A user buys one credit via Stripe Checkout; the credit is granted by the
    webhook and spent by generation endpoints via consume_generation().
  * Beat-store purchases: one-time Checkout for a listing's server-side price.
    Ownership is recorded; the buyer can download the full files.

TEST MODE ONLY until Daryl completes Stripe verification + live-key swap.
No live money moves here: amounts come from the tables below, never the client.
"""
import time

import billing_core as bc

# Daryl-confirmed 2026-10-14 (USD)
PAY_PER_USE = {
    "beat": 2.00,
    "master": 3.00,
    "video": 2.00,
    "distribute": 5.00,
    "stems": 1.00,
}

SUCCESS_PATH = "/account?paid=1"
CANCEL_PATH = "/pricing?canceled=1"


def _ensure_tables():
    con = bc._connect()
    try:
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
        con.commit()
    finally:
        con.close()


# ------------------------------------------------------------- Stripe glue
def _stripe_or_error():
    s = bc._stripe()
    if s is None:
        return None, ("Stripe is not configured — paste API keys into "
                      "billing_core.py (STRIPE_SECRET_KEY) and `pip install stripe`.")
    return s, None


def _get_or_create_customer(s, user):
    customer_id = user.get("stripe_customer_id")
    if not customer_id:
        customer = s.Customer.create(email=user["email"],
                                     metadata={"prhyme_user_id": user["id"]})
        customer_id = customer.id
        bc.update_user(user["id"], stripe_customer_id=customer_id)
    return customer_id


def create_payg_session(user, item, base_url):
    """Checkout for one pay-per-use credit. Returns (url, error)."""
    _ensure_tables()
    if item not in PAY_PER_USE:
        return None, f"Unknown item: {item}."
    s, err = _stripe_or_error()
    if err:
        return None, err
    amount = PAY_PER_USE[item]
    customer_id = _get_or_create_customer(s, user)
    sess = s.checkout.Session.create(
        customer=customer_id,
        mode="payment",
        line_items=[{"price_data": {
            "currency": "usd",
            "unit_amount": int(round(amount * 100)),
            "product_data": {
                "name": f"Prhyme — 1 × {item} (pay per use)",
                "description": "Single %s generation, no subscription needed." % item,
            }}, "quantity": 1}],
        metadata={"prhyme_user_id": user["id"], "prhyme_payg": item},
        success_url=base_url.rstrip("/") + SUCCESS_PATH,
        cancel_url=base_url.rstrip("/") + CANCEL_PATH,
    )
    return sess.url, None


# ------------------------------------------------------------- beat store
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


def create_beat_session(user, beat_id, base_url):
    """Checkout for a beat listing at its server-side price. Returns (url, error)."""
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
    s, err = _stripe_or_error()
    if err:
        return None, err
    license_label = str(beat.get("license") or "lease")
    customer_id = _get_or_create_customer(s, user)
    sess = s.checkout.Session.create(
        customer=customer_id,
        mode="payment",
        line_items=[{"price_data": {
            "currency": "usd",
            "unit_amount": int(round(price * 100)),
            "product_data": {
                "name": "Prhyme Beat — %s" % beat.get("title", beat_id),
                "description": "%s license" % license_label,
            }}, "quantity": 1}],
        metadata={"prhyme_user_id": user["id"],
                  "prhyme_beat_id": str(beat_id),
                  "prhyme_license": license_label},
        success_url=base_url.rstrip("/") + SUCCESS_PATH,
        cancel_url=base_url.rstrip("/") + CANCEL_PATH,
    )
    return sess.url, None


# ------------------------------------------------------------- credits
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
    """Spend one credit. Returns True if one was available."""
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
                         stripe_session_id):
    _ensure_tables()
    con = bc._connect()
    try:
        con.execute(
            "INSERT OR IGNORE INTO beat_purchases"
            " (uid, beat_id, title, license, amount, currency,"
            " stripe_session_id, created_at)"
            " VALUES (?,?,?,?,?,?,?,?)",
            (uid, str(beat_id), title, license, amount, currency,
             stripe_session_id, time.time()))
        con.commit()
    finally:
        con.close()


# ------------------------------------------------------------- webhook
def try_webhook(payload, sig_header):
    """Handle pay-per-use / beat-store Stripe events.

    Returns (handled: bool, ok: bool, message: str). Unhandled events return
    (False, ...) so the caller can fall through to billing_core.handle_webhook.
    """
    s, err = _stripe_or_error()
    if err:
        return False, False, "Stripe not configured."
    try:
        event = s.Webhook.construct_event(payload, sig_header,
                                          bc.STRIPE_WEBHOOK_SECRET)
    except Exception as e:
        return False, False, f"Webhook verification failed: {e}"
    if event.get("type") != "checkout.session.completed":
        return False, True, "Not a completion event."
    obj = event.get("data", {}).get("object", {}) or {}
    md = obj.get("metadata") or {}
    uid = 0
    try:
        uid = int(md.get("prhyme_user_id") or 0)
    except (TypeError, ValueError):
        uid = 0
    if not uid:
        return False, True, "No prhyme user in metadata."
    amount = (obj.get("amount_total") or 0) / 100.0
    currency = (obj.get("currency") or "usd").lower()
    sess_id = obj.get("id", "")

    if md.get("prhyme_payg"):
        item = md["prhyme_payg"]
        if item not in PAY_PER_USE:
            return True, False, f"Unknown pay-per-use item: {item}."
        grant_payg_credit(uid, item)
        bc.record_purchase(uid, f"payg_{item}", amount or PAY_PER_USE[item],
                           currency, sess_id)
        return True, True, f"Granted 1 × {item} credit."

    if md.get("prhyme_beat_id"):
        beat_id = md["prhyme_beat_id"]
        license = md.get("prhyme_license", "lease")
        beat = get_beat_listing(beat_id) or {}
        record_beat_purchase(uid, beat_id, beat.get("title", beat_id),
                             license, amount, currency, sess_id)
        bc.record_purchase(uid, "beat_purchase", amount, currency, sess_id)
        return True, True, f"Recorded beat purchase {beat_id}."
    return False, True, "No payment metadata matched."
