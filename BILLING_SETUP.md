# Prhyme™ Monetization — Setup Guide

## What's built

- **User accounts**: signup / login / logout, password reset (token flow)
- **3-day free trial**: full access, no card required
- **Founding 100**: first 100 signups get free lifetime access + in-app 🏆 badge
- **Paid plans**: $9/mo subscription or lifetime one-time ($99, or $49 pre-launch for users 101–500)
- **30-day money-back**: stated on pricing page (refunds via Stripe dashboard)
- **Server-side enforcement**: every `POST /api/*` requires an active subscription (HTTP 402 + redirect to /pricing). Pages stay viewable with an upgrade banner.
- **First signup** automatically becomes owner + founding member #1 (lifetime) — that's you, Daryl.

## Files

| File | What it does |
|---|---|
| `billing_core.py` | All billing logic: SQLite users, PBKDF2 password hashing, trial/subscription rules, Stripe API calls |
| `billing.py` | Flask blueprint: `/pricing`, `/signup`, `/login`, `/account`, `/reset/<token>`, `/api/billing/*` |
| `templates/pricing.html`, `signup.html`, `login.html`, `account.html`, `reset.html` | Pages |
| `app.py` | Hooks in `billing.init_app(app, BASE)` — secret key, blueprint, request gate |

## To accept real payments (do this when ready)

1. **Install Stripe on the server**: `pip install stripe`
2. **Create a Stripe account** at https://dashboard.stripe.com (toggle **Test mode** ON first)
3. **Get API keys**: Developers → API keys → copy the Publishable key + Secret key
4. **Paste them** into `billing_core.py`:
   - `STRIPE_PUBLISHABLE_KEY = "pk_test_..."`
   - `STRIPE_SECRET_KEY = "sk_test_..."`
5. **Webhook** (for subscription renewals/cancels to register automatically):
   - Developers → Webhooks → Add endpoint: `https://YOUR-DOMAIN/api/billing/webhook`
   - Copy the Signing secret → `STRIPE_WEBHOOK_SECRET = "whsec_..."`
   - ⚠️ Webhooks need a public HTTPS URL — they don't work on localhost. They matter once the app is on cloud hosting.
6. **Go live**: in Stripe, toggle test mode OFF, swap in the `pk_live_...` / `sk_live_...` keys.

No Stripe Price objects needed — the code builds prices inline ($9/mo, $49/$99 lifetime).

## What still needs work before commercial launch

1. **Cloud hosting** — the app currently runs on your phone's localhost. For paying customers you need a real server (VPS like Hetzner/DigitalOcean ~$6/mo, or similar) running the Flask app behind HTTPS.
2. **Domain + HTTPS** — required for Stripe webhooks and customer trust.
3. **Email delivery** — password-reset links currently print to the server log. Wire SMTP (e.g. Resend, Postmark, or Gmail SMTP) in `billing.py::api_forgot`.
4. **Terms of Service + Privacy Policy** pages (legal requirement for payments).
5. **Refunds** — handled manually in the Stripe dashboard (30-day guarantee).
6. **APK distribution** — the current APK points at localhost. A commercial build needs to point at your cloud server URL.
7. **Backups** — `billing.db` holds all users; back it up regularly once live.

## Kill switch

Set `BILLING_ENFORCE = False` in `billing_core.py` to disable all gating (open access, e.g. for local dev).
