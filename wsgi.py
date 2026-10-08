"""Production WSGI entry point for Prhyme on Render/cloud hosting.

- Binds via gunicorn (see Procfile); host/port come from $PORT.
- Stripe keys and secrets come from environment variables, never hardcoded.
- The local/phone version (python3 app.py) is untouched.
"""
import os

# Stripe keys from environment (fall back to billing_core placeholders = test mode disabled gracefully)
if os.environ.get("STRIPE_PUBLISHABLE_KEY"):
    os.environ["PRHYME_STRIPE_PUB"] = os.environ["STRIPE_PUBLISHABLE_KEY"]
if os.environ.get("STRIPE_SECRET_KEY"):
    os.environ["PRHYME_STRIPE_SEC"] = os.environ["STRIPE_SECRET_KEY"]
if os.environ.get("STRIPE_WEBHOOK_SECRET"):
    os.environ["PRHYME_STRIPE_WHSEC"] = os.environ["STRIPE_WEBHOOK_SECRET"]

from app import app  # noqa: E402

# Ensure a secret key exists in production (billing.py generates one if missing,
# but an explicit env var is better for session persistence across restarts)
if not app.secret_key:
    app.secret_key = os.environ.get("FLASK_SECRET_KEY", os.urandom(32).hex())

application = app
