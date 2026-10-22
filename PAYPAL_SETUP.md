# Prhyme™ PayPal Billing — Setup Guide

Daryl-ordered 2026-10-16: PayPal replaces Stripe as the active provider
("at least for now"). Stripe code stays in place but dormant.

## What's built

| File | What it does |
|---|---|
| `deploy/billing_paypal.py` | PayPal REST client (stdlib-only, no new deps): $9/mo + $499/yr subscriptions, $4,999 lifetime one-time, pay-per-use credits (beat $2 / master $3 / video $2 / distribute $5 / stems $1), beat-store purchases at server-side prices |
| `deploy/test_billing_paypal.py` | 28 mocked unit tests — all passing |
| `deploy_paypal.py` | Idempotent phone-deploy patch script (run on the phone) |

**Prices (Daryl-confirmed 2026-10-14):** monthly $9 · platinum/yearly $499 ·
lifetime $4,999 · pay-per-use beat $2 / master $3 / video $2 / distribute $5 /
stems $1. Hardcoded in the module — change only on his word.

## How it works

- **Subscriptions:** `POST /api/billing/checkout` `{"plan": "monthly"|"platinum"}`
  → PayPal approval URL. User approves on PayPal's site →
  `BILLING.SUBSCRIPTION.ACTIVATED` webhook sets `plan` / `sub_status=active` /
  `current_period_end` in billing_core — the existing server-side gate keeps
  working unchanged. Cancelled/suspended/expired/failed webhooks update status
  the same way Stripe did.
- **One-time (lifetime, pay-per-use, beats):** Orders API. User approves →
  PayPal redirects to `/api/billing/paypal/return?token=ORDER_ID` → server
  captures and grants immediately (this path is what works on localhost, where
  webhooks can't reach). `PAYMENT.CAPTURE.COMPLETED` webhook is the fallback.
  Grants are **idempotent on the PayPal order id** — a double capture can never
  double-grant.
- **Credits:** land in the same `payg_credits` table the Stripe module used.
  Generation endpoints keep calling `consume_generation(uid, item)` — no changes.
- **Pricing page:** unchanged. Same routes, same JSON shapes — buttons keep working.

## Setup (do this when ready)

1. **Create the REST API app** (only you can do this): log in at
   https://developer.paypal.com/dashboard → My Apps & Credentials → Create App.
   Copy the **Client ID** and **Secret**. Don't paste them in chat — tell Muse
   when the app exists and he'll give you a secure handoff.
2. **Set env vars** (phone + Render `prhyme` service):
   `PAYPAL_CLIENT_ID`, `PAYPAL_CLIENT_SECRET`, `PAYPAL_MODE=sandbox` (while testing).
3. **Create the product + plans once** (sandbox first):
   ```python
   import billing_paypal as pp
   print(pp.create_product_and_plans())
   ```
   Paste the two plan ids into `PAYPAL_PLAN_MONTHLY` / `PAYPAL_PLAN_PLATINUM`.
4. **Phone deploy:** `cp billing_paypal.py /storage/emulated/0/djrill/mobile/`
   then `python3 deploy_paypal.py`, then `restart prhyme`.
5. **Webhook** (matters once the app has a public HTTPS URL — Render):
   developer.paypal.com → your app → Add Webhook →
   `https://<your-host>/api/billing/webhook`, subscribe to:
   `BILLING.SUBSCRIPTION.ACTIVATED`, `.CANCELLED`, `.SUSPENDED`, `.EXPIRED`,
   `.PAYMENT.FAILED`, `PAYMENT.SALE.COMPLETED`, `PAYMENT.CAPTURE.COMPLETED`.
   Copy the webhook ID into `PAYPAL_WEBHOOK_ID`.
   ⚠️ Webhooks don't reach localhost — on the phone, the return-URL capture
   path handles grants; webhooks take over on the public host.

## Going live (blocked until Daryl says go)

1. PayPal business account verified (his dashboard action).
2. Create a **live** REST API app → live Client ID + Secret.
3. `PAYPAL_MODE=live` + live creds in Render env vars; register the webhook on
   the live URL; paste the live webhook ID.
4. One $1 test charge on Daryl's explicit word, then refund it.

## Kill switch

`BILLING_ENFORCE = False` in `billing_core.py` disables all gating (dev mode).
To go back to Stripe later: revert the `deploy_paypal.py` patches in
`billing.py` (the markers make them easy to find) — no data migration needed,
credits and purchases are provider-agnostic.

## Frontend snippet (unchanged routes)

```js
async function subscribe(plan){           // "monthly" | "platinum" | "lifetime"
  const r = await fetch("/api/billing/checkout",{method:"POST",
    headers:{"Content-Type":"application/json"},body:JSON.stringify({plan})});
  const d = await r.json();
  if(d.ok) location.href = d.url; else alert(d.error);
}
async function buyPayg(item){ /* same shape as before */ }
async function buyBeat(beatId){ /* same shape as before */ }
```
