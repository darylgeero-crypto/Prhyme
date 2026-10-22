"""Prhyme billing — Flask wiring for billing_core.

Call billing.init_app(app, base_dir) once from app.py. This:
  * sets a persistent Flask secret key (sessions)
  * registers the billing blueprint (/pricing, /signup, /login, /account,
    /api/billing/*)
  * installs a before_request gate: POST /api/* endpoints require an
    active subscription (server-side — never trust the client).

Daryl: to accept real payments, paste your Stripe keys into
billing_core.py (STRIPE_SECRET_KEY etc.) and `pip install stripe`.
"""
import os
import secrets
import time

from flask import (Blueprint, jsonify, redirect, render_template, request,
                   session, url_for)

import billing_core as bc
import billing_payments as bp_pay
import billing_paypal as bp_pp

bp = Blueprint("billing", __name__)


# ------------------------------------------------------------------ helpers
def _base_url():
    # Prefer Host header; app is localhost-only for now.
    return request.host_url.rstrip("/")


def current_user():
    uid = session.get("uid")
    if not uid:
        return None
    try:
        return bc.get_user(int(uid))
    except (TypeError, ValueError):
        return None


def _do_login(uid):
    """Complete a login: set Flask session + register server-side session."""
    session["uid"] = uid
    session.permanent = True
    try:
        ip = request.headers.get("X-Forwarded-For", request.remote_addr or "")
        ua = request.headers.get("User-Agent", "")
        token = bc.register_session(uid, ip=ip, user_agent=ua)
        session["sess_token"] = token
    except Exception:
        pass


def _login_required():
    user = current_user()
    if not user:
        return None, redirect(url_for("billing.login",
                                      next=request.path))
    return user, None


# ------------------------------------------------------------------ gating
# POST /api/* endpoints that cost compute. Everything else stays open so
# browsing never breaks; the banner (see status endpoint) nudges upgrades.
#
# FREEMIUM: snippet/preview endpoints are OPEN (no account needed).
# Free users get short previews; paid users get full output.
_OPEN_API_PREFIXES = (
    "/api/billing/",
    "/api/job/",   # cancelling a running job must never be paywalled
    "/api/lite-mode",
    "/api/daw/projects",   # project save/list is cheap local storage
    "/api/beats/preview",   # freemium: 8-bar beat snippet, no login
    "/api/lyrics/preview",  # freemium: 8-line lyric snippet, no login
)
_OPEN_API_EXACT = set()


def _gate():
    """before_request: enforce subscription on gated endpoints."""
    if not bc.BILLING_ENFORCE:
        return None
    path = request.path
    if path.startswith("/static/"):
        return None
    # Only gate mutating API calls (the expensive stuff).
    if not (path.startswith("/api/") and request.method == "POST"):
        return None
    for prefix in _OPEN_API_PREFIXES:
        if path.startswith(prefix):
            return None
    if path in _OPEN_API_EXACT:
        return None
    user = current_user()
    active, label, detail = bc.subscription_state(user)
    if active:
        return None
    return jsonify({
        "ok": False,
        "error": "subscription_required",
        "message": detail,
        "plan_label": label,
        "upgrade_url": url_for("billing.pricing"),
    }), 402


# ------------------------------------------------------------------ pages
@bp.get("/pricing")
def pricing():
    return render_template(
        "pricing.html", active="pricing",
        monthly=bc.MONTHLY_PRICE,
        platinum=bc.PLATINUM_PRICE,
        lifetime=bc.lifetime_price_now(),
        lifetime_full=bc.LIFETIME_PRICE,
        trial_days=bc.TRIAL_DAYS,
        founding_spots=bc.FOUNDING_SPOTS,
        founding_left=bc.founding_spots_left(),
        stripe_key=bc.STRIPE_PUBLISHABLE_KEY
        if bc.stripe_configured() else "",
    )


@bp.get("/signup")
def signup():
    if current_user():
        return redirect(url_for("billing.account"))
    return render_template("signup.html", active="pricing",
                           founding_left=bc.founding_spots_left())


@bp.get("/terms")
def terms():
    """Serve the Terms of Service (rendered from legal/TERMS_OF_SERVICE.md)."""
    import os as _os
    # 2026-10-21 overhaul: look in the app dir first (Render layout: legal/
    # ships inside the app root), then the parent (phone layout: djrill/legal).
    md = None
    for _base in (_os.path.dirname(__file__),
                  _os.path.dirname(_os.path.dirname(__file__))):
        try:
            with open(_os.path.join(_base, "legal", "TERMS_OF_SERVICE.md")) as f:
                md = f.read()
            break
        except OSError:
            continue
    if md is None:
        md = "# Terms of Service\n\nComing soon."
    return render_template("legal.html", active="pricing",
                           title="Terms of Service", content=md)


@bp.get("/privacy")
def privacy():
    """Serve the Privacy Policy."""
    import os as _os
    md = None
    for _base in (_os.path.dirname(__file__),
                  _os.path.dirname(_os.path.dirname(__file__))):
        try:
            with open(_os.path.join(_base, "legal", "PRIVACY_POLICY.md")) as f:
                md = f.read()
            break
        except OSError:
            continue
    if md is None:
        md = "# Privacy Policy\n\nComing soon."
    return render_template("legal.html", active="pricing",
                           title="Privacy Policy", content=md)


@bp.post("/signup")
def signup_post():
    data = request.get_json(force=True, silent=True) or request.form
    email = (data.get("email") or "").strip()
    password = data.get("password") or ""
    wants_json = request.is_json
    # Compliance: must accept ToS + Privacy Policy, and confirm 13+.
    _accepted = str(data.get("accept_terms") or "").lower() in (
        "on", "1", "true", "yes")
    _age_ok = str(data.get("age_confirm") or "").lower() in (
        "on", "1", "true", "yes")
    if not _accepted:
        msg = "You must accept the Terms of Service and Privacy Policy."
        if wants_json:
            return jsonify({"ok": False, "error": msg}), 400
        return render_template("signup.html", active="pricing", error=msg,
                               founding_left=bc.founding_spots_left()), 400
    if not _age_ok:
        msg = "You must confirm you are at least 13 years old."
        if wants_json:
            return jsonify({"ok": False, "error": msg}), 400
        return render_template("signup.html", active="pricing", error=msg,
                               founding_left=bc.founding_spots_left()), 400
    user, err = bc.create_user(email, password)
    if err:
        if wants_json:
            return jsonify({"ok": False, "error": err}), 400
        return render_template("signup.html", active="pricing", error=err,
                               founding_left=bc.founding_spots_left()), 400
    _do_login(user["id"])
    # Record ToS acceptance (compliance).
    import time as _t
    bc.update_user(user["id"], tos_accepted_at=_t.time(),
                   tos_version="2026-10-08")
    if wants_json:
        return jsonify({"ok": True,
                        "next": url_for("billing.account")})
    return redirect(url_for("billing.account"))


@bp.get("/login")
def login():
    if current_user():
        return redirect(url_for("billing.account"))
    return render_template("login.html", active="pricing")


@bp.post("/login")
def login_post():
    data = request.get_json(force=True, silent=True) or request.form
    user = bc.authenticate(data.get("email"), data.get("password"))
    wants_json = request.is_json
    if not user:
        msg = "Wrong email or password."
        if wants_json:
            return jsonify({"ok": False, "error": msg}), 401
        return render_template("login.html", active="pricing",
                               error=msg), 401
    # 2FA: if enabled, require TOTP before completing login.
    # Store pending UID in session (not yet authenticated).
    if user.get("totp_enabled"):
        session["pending_2fa_uid"] = user["id"]
        session.permanent = True
        if wants_json:
            return jsonify({"ok": True, "need_2fa": True,
                            "next": url_for("billing.verify_2fa")})
        return redirect(url_for("billing.verify_2fa"))
    _do_login(user["id"])
    nxt = request.args.get("next") or url_for("billing.account")
    if wants_json:
        return jsonify({"ok": True, "next": nxt})
    return redirect(nxt)


@bp.get("/verify-2fa")
def verify_2fa():
    """2FA verification page (after password login)."""
    if current_user():
        return redirect(url_for("billing.account"))
    if not session.get("pending_2fa_uid"):
        return redirect(url_for("billing.login"))
    return render_template("verify_2fa.html", active="pricing")


@bp.post("/verify-2fa")
def verify_2fa_post():
    uid = session.get("pending_2fa_uid")
    if not uid:
        return redirect(url_for("billing.login"))
    data = request.get_json(force=True, silent=True) or request.form
    code = (data.get("code") or "").strip()
    wants_json = request.is_json
    ok, msg, used_backup = bc.totp_verify_login(uid, code)
    if not ok:
        if wants_json:
            return jsonify({"ok": False, "error": msg}), 401
        return render_template("verify_2fa.html", active="pricing",
                               error=msg), 401
    # 2FA passed — complete login.
    session.pop("pending_2fa_uid", None)
    _do_login(uid)
    nxt = request.args.get("next") or url_for("billing.account")
    if wants_json:
        return jsonify({"ok": True, "next": nxt,
                        "used_backup": used_backup,
                        "message": msg})
    return redirect(nxt)


@bp.get("/logout")
def logout():
    session.pop("uid", None)
    return redirect(url_for("billing.pricing"))


def _storage_summary():
    """Library storage for the account page (Gemini suggestion, approved):
    sizes of outputs/uploads/samples beside billing.py + device free."""
    import os as _os
    import shutil as _sh
    root = _os.path.dirname(_os.path.abspath(__file__))
    parts = []
    total_b = 0
    total_n = 0
    for label, sub in (("Tracks & outputs", "outputs"),
                       ("Uploads", "uploads"), ("Samples", "samples")):
        d = _os.path.join(root, sub)
        b = n = 0
        if _os.path.isdir(d):
            for fn in _os.listdir(d):
                p = _os.path.join(d, fn)
                if _os.path.isfile(p):
                    b += _os.path.getsize(p)
                    n += 1
        parts.append({"label": label, "mb": round(b / 1048576, 1),
                      "count": n})
        total_b += b
        total_n += n
    total_mb = round(total_b / 1048576, 1)
    try:
        free_gb = round(_sh.disk_usage(root).free / 1073741824, 1)
    except Exception:
        free_gb = 0
    return {"parts": parts, "total_mb": total_mb, "count": total_n,
            "free_gb": free_gb,
            "pct": max(2, min(100, round(total_mb / 10.24)))}


@bp.get("/account")
def account():
    user, redir = _login_required()
    if redir:
        return redir
    active, label, detail = bc.subscription_state(user)
    return render_template(
        "account.html", active="account", user=user,
        active_sub=active, plan_label=label, detail=detail,
        trial_days_left=bc.trial_days_left(user),
        stripe_configured=bc.stripe_configured(),
        paid=request.args.get("paid") == "1",
        totp_enabled=bool(user.get("totp_enabled")),
        security_log=bc.get_security_log(user["id"], limit=10),
        storage=_storage_summary(),
    )


# ------------------------------------------------------- two-factor auth
@bp.get("/account/2fa/setup")
def totp_setup_page():
    """Start 2FA enrollment — shows QR code + backup codes."""
    user, redir = _login_required()
    if redir:
        return redir
    if user.get("totp_enabled"):
        return redirect(url_for("billing.account"))
    secret, uri, svg, codes = bc.totp_setup_start(user["id"])
    if not secret:
        return render_template("account.html", active="account",
                               user=user, error="Could not start 2FA setup."), 500
    return render_template("totp_setup.html", active="account",
                           qr_svg=svg, secret=secret,
                           backup_codes=codes)


@bp.post("/api/billing/2fa/verify-setup")
def api_totp_verify_setup():
    """Verify TOTP code to complete 2FA enrollment."""
    user, redir = _login_required()
    if redir:
        return jsonify({"ok": False, "error": "Login required."}), 401
    data = request.get_json(force=True, silent=True) or {}
    ok, msg = bc.totp_setup_verify(user["id"], data.get("code", ""))
    return jsonify({"ok": ok,
                    "message": msg if ok else None,
                    "error": None if ok else msg})


@bp.post("/api/billing/2fa/disable")
def api_totp_disable():
    """Disable 2FA (requires password confirmation)."""
    user, redir = _login_required()
    if redir:
        return jsonify({"ok": False, "error": "Login required."}), 401
    data = request.get_json(force=True, silent=True) or {}
    ok, msg = bc.totp_disable(user["id"], data.get("password", ""))
    return jsonify({"ok": ok,
                    "message": msg if ok else None,
                    "error": None if ok else msg})


@bp.post("/api/billing/2fa/backup-codes")
def api_totp_backup_codes():
    """Regenerate backup codes (invalidates old ones)."""
    user, redir = _login_required()
    if redir:
        return jsonify({"ok": False, "error": "Login required."}), 401
    codes, err = bc.totp_regenerate_backup_codes(user["id"])
    if err:
        return jsonify({"ok": False, "error": err}), 400
    return jsonify({"ok": True, "backup_codes": codes})


# ------------------------------------------------------- 2FA account recovery
@bp.post("/api/billing/2fa/recovery-request")
def api_totp_recovery_request():
    """Start 48h recovery wait for lost 2FA device. Requires login."""
    user, redir = _login_required()
    if redir:
        return jsonify({"ok": False, "error": "Login required."}), 401
    ok, msg = bc.totp_recovery_request(user["id"])
    return jsonify({"ok": ok, "message": msg if ok else None,
                    "error": None if ok else msg})


@bp.post("/api/billing/2fa/recovery-complete")
def api_totp_recovery_complete():
    """Complete recovery after 48h wait."""
    user, redir = _login_required()
    if redir:
        return jsonify({"ok": False, "error": "Login required."}), 401
    ok, msg = bc.totp_recovery_complete(user["id"])
    return jsonify({"ok": ok, "message": msg if ok else None,
                    "error": None if ok else msg})


@bp.post("/api/billing/2fa/recovery-cancel")
def api_totp_recovery_cancel():
    user, redir = _login_required()
    if redir:
        return jsonify({"ok": False, "error": "Login required."}), 401
    ok, msg = bc.totp_recovery_cancel(user["id"])
    return jsonify({"ok": ok, "message": msg})


@bp.post("/api/billing/security-questions")
def api_security_questions():
    """Set security question answers."""
    user, redir = _login_required()
    if redir:
        return jsonify({"ok": False, "error": "Login required."}), 401
    data = request.get_json(force=True, silent=True) or {}
    ok, msg = bc.set_security_questions(
        user["id"], data.get("answer1", ""), data.get("answer2", ""))
    return jsonify({"ok": ok, "message": msg if ok else None,
                    "error": None if ok else msg})


@bp.get("/account/receipts")
def receipts():
    """Purchase history / receipts."""
    user, redir = _login_required()
    if redir:
        return redir
    return render_template("receipts.html", active="account",
                           purchases=bc.get_purchases(user["id"]))


@bp.get("/account/sessions")
def sessions_page():
    """View and revoke active sessions."""
    user, redir = _login_required()
    if redir:
        return redir
    current_token = session.get("sess_token", "")
    sessions = bc.get_sessions(user["id"])
    return render_template("sessions.html", active="account",
                           sessions=sessions, current_token=current_token)


@bp.post("/api/billing/sessions/revoke")
def api_revoke_session():
    user, redir = _login_required()
    if redir:
        return jsonify({"ok": False, "error": "Login required."}), 401
    data = request.get_json(force=True, silent=True) or {}
    token = (data.get("token") or "").strip()
    if not token or token == session.get("sess_token"):
        return jsonify({"ok": False,
                        "error": "Cannot revoke your current session."}), 400
    bc.revoke_session(user["id"], token)
    return jsonify({"ok": True})


@bp.post("/api/billing/sessions/revoke-all")
def api_revoke_all_sessions():
    user, redir = _login_required()
    if redir:
        return jsonify({"ok": False, "error": "Login required."}), 401
    bc.revoke_all_sessions(user["id"],
                           except_token=session.get("sess_token"))
    return jsonify({"ok": True})


# ------------------------------------------------------------------ API
@bp.get("/api/billing/status")
def api_status():
    return jsonify(bc.public_status(current_user()))


@bp.post("/api/billing/checkout")
def api_checkout():
    user, redir = _login_required()
    if redir:
        return jsonify({"ok": False, "error": "Login required."}), 401
    active, label, _ = bc.subscription_state(user)
    if active and label in ("lifetime", "monthly", "platinum"):
        return jsonify({"ok": False,
                        "error": "You already have active access."}), 400
    data = request.get_json(force=True, silent=True) or {}
    plan = data.get("plan")
    # PayPal is the active provider (Daryl 2026-10-16).
    if plan == "lifetime":
        url, err = bp_pp.create_lifetime_order(user, _base_url())
    else:
        url, err = bp_pp.create_subscription(user, plan, _base_url())
    if err:
        return jsonify({"ok": False, "error": err}), 400
    return jsonify({"ok": True, "url": url})


@bp.post("/api/billing/webhook")
def api_webhook():
    payload = request.get_data()
    # PayPal webhook dispatch (verified via PayPal's API).
    if request.headers.get("Paypal-Transmission-Id"):
        handled, ok, msg = bp_pp.try_webhook(request.headers, payload)
        if handled:
            return jsonify({"ok": ok, "message": msg}), 200 if ok else 400
    sig = request.headers.get("Stripe-Signature", "")
    # Pay-per-use / beat-store events are handled by billing_payments first;
    # subscription + lifetime events fall through to billing_core.
    handled, ok, msg = bp_pay.try_webhook(payload, sig)
    if handled:
        return jsonify({"ok": ok, "message": msg}), 200 if ok else 400
    ok, msg = bc.handle_webhook(payload, sig)
    return jsonify({"ok": ok, "message": msg}), 200 if ok else 400


@bp.get("/api/billing/paypal/return")
def api_paypal_return():
    """PayPal redirects here after approval (?token=ORDER_ID or ?kind=sub).

    Captures one-time orders server-side (webhooks can't reach localhost).
    Subscriptions are activated by the webhook on the public host.
    """
    order_id = request.args.get("token", "")
    if order_id:
        ok, msg = bp_pp.capture_order(order_id)
        if not ok:
            return jsonify({"ok": False, "error": msg}), 400
    return redirect("/account?paid=1")


@bp.get("/api/billing/paypal/cancel")
def api_paypal_cancel():
    return redirect("/pricing?canceled=1")


@bp.post("/api/billing/payg")
def api_payg():
    """Buy one pay-per-use credit (beat/master/video/distribute/stems)."""
    user, redir = _login_required()
    if redir:
        return jsonify({"ok": False, "error": "Login required."}), 401
    data = request.get_json(force=True, silent=True) or {}
    url, err = bp_pp.create_payg_order(user, data.get("item"), _base_url())
    if err:
        return jsonify({"ok": False, "error": err}), 400
    return jsonify({"ok": True, "url": url,
                    "prices": bp_pp.PAY_PER_USE})


@bp.post("/api/billing/buy-beat")
def api_buy_beat():
    """Buy a beat listing at its server-side price."""
    user, redir = _login_required()
    if redir:
        return jsonify({"ok": False, "error": "Login required."}), 401
    data = request.get_json(force=True, silent=True) or {}
    url, err = bp_pp.create_beat_order(user, data.get("beat_id"), _base_url())
    if err:
        return jsonify({"ok": False, "error": err}), 400
    return jsonify({"ok": True, "url": url})


@bp.get("/api/billing/payg/balance")
def api_payg_balance():
    """Pay-per-use credit balances + prices for the logged-in user."""
    user, redir = _login_required()
    if redir:
        return jsonify({"ok": False, "error": "Login required."}), 401
    return jsonify({"ok": True,
                    "balance": bp_pp.payg_balance(user["id"]),
                    "prices": bp_pp.PAY_PER_USE})


@bp.post("/api/billing/cancel")
def api_cancel():
    user, redir = _login_required()
    if redir:
        return jsonify({"ok": False, "error": "Login required."}), 401
    bp_pp.cancel_subscription(user)
    return jsonify({"ok": True})


@bp.post("/api/billing/forgot")
def api_forgot():
    data = request.get_json(force=True, silent=True) or {}
    token = bc.issue_reset_token(data.get("email"))
    # NOTE: no email infra on the phone yet. In production, send the link
    # via SMTP here. For now the token is printed to the server log so
    # Daryl can complete a reset locally during testing.
    if token:
        print(f"[billing] password reset link: {_base_url()}/reset/{token}",
              flush=True)
    return jsonify({"ok": True,
                    "message": "If that email is registered, a reset link "
                               "was generated."})


@bp.get("/reset/<token>")
def reset_page(token):
    user = bc.consume_reset_token(token)
    if not user:
        return render_template("reset.html", active="pricing",
                               error="That reset link is invalid or expired.",
                               token=None)
    return render_template("reset.html", active="pricing", token=token)


@bp.post("/reset/<token>")
def reset_post(token):
    user = bc.consume_reset_token(token)
    data = request.get_json(force=True, silent=True) or request.form
    wants_json = request.is_json
    if not user:
        msg = "That reset link is invalid or expired."
        if wants_json:
            return jsonify({"ok": False, "error": msg}), 400
        return render_template("reset.html", active="pricing", error=msg,
                               token=None), 400
    pw = data.get("password") or ""
    if len(pw) < 8:
        msg = "Password must be at least 8 characters."
        if wants_json:
            return jsonify({"ok": False, "error": msg}), 400
        return render_template("reset.html", active="pricing", error=msg,
                               token=token), 400
    bc.set_password(user["id"], pw)
    _do_login(user["id"])
    if wants_json:
        return jsonify({"ok": True, "next": url_for("billing.account")})
    return redirect(url_for("billing.account"))


# ------------------------------------------------------------------ init
def _ensure_secret_key(app, base_dir):
    """Persistent secret key so sessions survive restarts."""
    key_file = os.path.join(base_dir, ".flask_secret")
    key = None
    if os.path.isfile(key_file):
        try:
            with open(key_file, "r") as f:
                key = f.read().strip()
        except OSError:
            key = None
    if not key:
        key = secrets.token_hex(32)
        try:
            with open(key_file, "w") as f:
                f.write(key)
            os.chmod(key_file, 0o600)
        except OSError:
            pass
    app.secret_key = key


def init_app(app, base_dir):
    bc.configure(os.path.join(base_dir, "billing.db"))
    _ensure_secret_key(app, base_dir)
    app.register_blueprint(bp)
    app.before_request(_gate)

    @app.context_processor
    def _inject_billing():
        user = current_user()
        st = bc.public_status(user)
        return {"billing": st}
