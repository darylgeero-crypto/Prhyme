"""Unit tests for billing_paypal.py — PayPal REST calls are mocked.

Run:  python3 test_billing_paypal.py
"""
import json
import os
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import billing_core as bc
import billing_paypal as pp


def _user(email="t@t.com", pw="x" * 12):
    u, err = bc.create_user(email, pw)
    assert err is None, err
    return u


class PayPalTest(unittest.TestCase):
    def setUp(self):
        self.db = tempfile.NamedTemporaryFile(suffix=".db", delete=False).name
        bc.configure(self.db)
        # Real (non-placeholder) creds so paypal_configured() passes.
        self._orig = (pp.PAYPAL_CLIENT_ID, pp.PAYPAL_CLIENT_SECRET,
                      pp.PAYPAL_MODE, pp.PAYPAL_WEBHOOK_ID,
                      pp.PAYPAL_PLAN_MONTHLY, pp.PAYPAL_PLAN_PLATINUM)
        pp.PAYPAL_CLIENT_ID = "test-client-id"
        pp.PAYPAL_CLIENT_SECRET = "test-secret"
        pp.PAYPAL_MODE = "sandbox"
        pp.PAYPAL_WEBHOOK_ID = "WH-TEST"
        pp.PAYPAL_PLAN_MONTHLY = "P-MONTHLY"
        pp.PAYPAL_PLAN_PLATINUM = "P-PLATINUM"
        pp._token_cache["token"] = None
        self.calls = []

        def fake_api(method, path, body=None, idem_key=None):
            self.calls.append((method, path, body, idem_key))
            return self.fake_response(method, path, body)

        self.fake_response = lambda m, p, b: {}
        patcher = patch.object(pp, "_api", side_effect=fake_api)
        patcher.start()
        self.addCleanup(patcher.stop)

    def tearDown(self):
        (pp.PAYPAL_CLIENT_ID, pp.PAYPAL_CLIENT_SECRET, pp.PAYPAL_MODE,
         pp.PAYPAL_WEBHOOK_ID, pp.PAYPAL_PLAN_MONTHLY,
         pp.PAYPAL_PLAN_PLATINUM) = self._orig
        try:
            os.unlink(self.db)
        except OSError:
            pass

    # -- config ---------------------------------------------------------
    def test_not_configured_with_placeholders(self):
        pp.PAYPAL_CLIENT_ID = "REPLACE_WITH_YOUR_PAYPAL_CLIENT_ID"
        self.assertFalse(pp.paypal_configured())

    def test_configured_with_real_creds(self):
        self.assertTrue(pp.paypal_configured())

    # -- subscriptions --------------------------------------------------
    def test_create_subscription_unknown_plan(self):
        u = _user()
        url, err = pp.create_subscription(bc.get_user(u["id"]), "weekly",
                                          "https://x.test")
        self.assertIsNone(url)
        self.assertIn("Unknown plan", err)

    def test_create_subscription_missing_plan_id(self):
        pp.PAYPAL_PLAN_MONTHLY = ""
        u = _user()
        url, err = pp.create_subscription(bc.get_user(u["id"]), "monthly",
                                          "https://x.test")
        self.assertIsNone(url)
        self.assertIn("plan id", err)

    def test_create_subscription_monthly_payload(self):
        u = _user()
        captured = {}

        def resp(m, p, b):
            captured.update(b or {})
            return {"id": "I-SUB1",
                    "links": [{"rel": "approve",
                               "href": "https://paypal/approve/I-SUB1"}]}
        self.fake_response = resp
        url, err = pp.create_subscription(bc.get_user(u["id"]), "monthly",
                                          "https://x.test")
        self.assertIsNone(err)
        self.assertEqual(url, "https://paypal/approve/I-SUB1")
        self.assertEqual(captured["plan_id"], "P-MONTHLY")
        self.assertEqual(captured["custom_id"],
                         f"prhyme:sub:monthly:{u['id']}")
        self.assertIn("paypal/return", captured["application_context"]["return_url"])

    # -- one-time orders ------------------------------------------------
    def _order_resp(self, order_id="ORD-1"):
        def resp(m, p, b):
            return {"id": order_id,
                    "links": [{"rel": "approve",
                               "href": "https://paypal/approve/" + order_id}]}
        return resp

    def test_payg_unknown_item(self):
        u = _user()
        url, err = pp.create_payg_order(bc.get_user(u["id"]), "dance",
                                        "https://x.test")
        self.assertIsNone(url)
        self.assertIn("Unknown item", err)

    def test_payg_beat_amount_and_custom_id(self):
        u = _user()
        seen = {}

        def resp(m, p, b):
            seen.update(b or {})
            return self._order_resp()(m, p, b)
        self.fake_response = resp
        url, err = pp.create_payg_order(bc.get_user(u["id"]), "beat",
                                        "https://x.test")
        self.assertIsNone(err)
        pu = seen["purchase_units"][0]
        self.assertEqual(pu["amount"]["value"], "2.00")
        self.assertEqual(pu["custom_id"], f"prhyme:order:payg:{u['id']}:beat")

    def test_payg_master_amount(self):
        u = _user()
        seen = {}

        def resp(m, p, b):
            seen.update(b or {})
            return self._order_resp()(m, p, b)
        self.fake_response = resp
        pp.create_payg_order(bc.get_user(u["id"]), "master", "https://x.test")
        self.assertEqual(seen["purchase_units"][0]["amount"]["value"], "3.00")

    def test_lifetime_order_amount(self):
        u = _user()
        seen = {}

        def resp(m, p, b):
            seen.update(b or {})
            return self._order_resp()(m, p, b)
        self.fake_response = resp
        url, err = pp.create_lifetime_order(bc.get_user(u["id"]), "https://x.test")
        self.assertIsNone(err)
        pu = seen["purchase_units"][0]
        self.assertEqual(pu["amount"]["value"], "4999.00")
        self.assertTrue(pu["custom_id"].startswith("prhyme:order:lifetime:"))

    def test_beat_order_no_lookup(self):
        u = _user()
        url, err = pp.create_beat_order(bc.get_user(u["id"]), "b1",
                                        "https://x.test")
        self.assertIsNone(url)
        self.assertIn("Beat not found", err)

    def test_beat_order_blocks_own_beat(self):
        u = _user()
        pp.register_beat_lookup(
            lambda bid: {"id": bid, "title": "T", "price": 25.0,
                         "license": "lease", "seller_uid": u["id"]})
        self.addCleanup(lambda: pp.register_beat_lookup(None))
        url, err = pp.create_beat_order(bc.get_user(u["id"]), "b1",
                                        "https://x.test")
        self.assertIn("own beat", err)

    def test_beat_order_uses_server_price(self):
        u = _user()
        seen = {}
        pp.register_beat_lookup(
            lambda bid: {"id": bid, "title": "Boom", "price": 49.99,
                         "license": "exclusive", "seller_uid": 999})
        self.addCleanup(lambda: pp.register_beat_lookup(None))

        def resp(m, p, b):
            seen.update(b or {})
            return self._order_resp()(m, p, b)
        self.fake_response = resp
        url, err = pp.create_beat_order(bc.get_user(u["id"]), "b9",
                                        "https://x.test")
        self.assertIsNone(err)
        self.assertEqual(seen["purchase_units"][0]["amount"]["value"], "49.99")

    def test_beat_order_blocks_duplicate(self):
        u = _user()
        pp.register_beat_lookup(
            lambda bid: {"id": bid, "title": "T", "price": 10.0,
                         "license": "lease", "seller_uid": 999})
        self.addCleanup(lambda: pp.register_beat_lookup(None))
        pp.record_beat_purchase(u["id"], "b2", "T", "lease", 10.0, "usd", "X")
        url, err = pp.create_beat_order(bc.get_user(u["id"]), "b2",
                                        "https://x.test")
        self.assertIn("already own", err)

    # -- capture + idempotent grants ------------------------------------
    def _capture_flow(self, custom_id, order_id="ORD-9", amount="3.00"):
        calls = {"n": 0}

        def resp(m, p, b):
            if m == "GET":
                # First GET: approved; later GETs: completed.
                calls["n"] += 1
                if calls["n"] == 1:
                    return {"id": order_id, "status": "APPROVED",
                            "purchase_units": [
                                {"custom_id": custom_id,
                                 "amount": {"value": amount}}]}
                return {"id": order_id, "status": "COMPLETED",
                        "purchase_units": [
                            {"custom_id": custom_id,
                             "amount": {"value": amount},
                             "payments": {"captures": [{"id": "CAP-1"}]}}]}
            return {"id": order_id, "status": "COMPLETED",
                    "purchase_units": [
                        {"custom_id": custom_id,
                         "amount": {"value": amount},
                         "payments": {"captures": [{"id": "CAP-1"}]}}]}
        self.fake_response = resp

    def test_capture_grants_payg_once(self):
        u = _user()
        self._capture_flow(f"prhyme:order:payg:{u['id']}:master")
        ok, msg = pp.capture_order("ORD-9")
        self.assertTrue(ok)
        self.assertIn("master", msg)
        self.assertEqual(pp.payg_balance(u["id"]).get("master"), 1)
        # Second capture must not double-grant.
        ok2, msg2 = pp.capture_order("ORD-9")
        self.assertTrue(ok2)
        self.assertIn("already processed", msg2)
        self.assertEqual(pp.payg_balance(u["id"]).get("master"), 1)

    def test_capture_grants_lifetime(self):
        u = _user()
        self._capture_flow(f"prhyme:order:lifetime:{u['id']}:x",
                           amount="4999.00")
        ok, msg = pp.capture_order("ORD-9")
        self.assertTrue(ok)
        user = bc.get_user(u["id"])
        self.assertEqual(user["plan"], "lifetime")
        self.assertEqual(user["sub_status"], "lifetime")

    def test_capture_grants_beat(self):
        u = _user()
        pp.register_beat_lookup(
            lambda bid: {"id": bid, "title": "Boom", "price": 30.0,
                         "license": "lease", "seller_uid": 999})
        self.addCleanup(lambda: pp.register_beat_lookup(None))
        self._capture_flow(f"prhyme:order:beat:{u['id']}:b7", amount="30.00")
        ok, msg = pp.capture_order("ORD-9")
        self.assertTrue(ok)
        self.assertIsNotNone(pp.beat_owned(u["id"], "b7"))

    # -- subscription activation via webhook -----------------------------
    def _webhook(self, etype, resource):
        payload = json.dumps({"event_type": etype,
                              "resource": resource}).encode()
        with patch.object(pp, "verify_webhook", return_value=True):
            return pp.try_webhook({"Paypal-Transmission-Id": "t"}, payload)

    def test_webhook_activated_monthly(self):
        u = _user()
        handled, ok, msg = self._webhook(
            "BILLING.SUBSCRIPTION.ACTIVATED",
            {"id": "I-SUB1", "custom_id": f"prhyme:sub:monthly:{u['id']}",
             "billing_info": {"next_billing_time": "2026-11-16T10:00:00Z"}})
        self.assertTrue(handled and ok)
        user = bc.get_user(u["id"])
        self.assertEqual(user["plan"], "monthly")
        self.assertEqual(user["sub_status"], "active")
        # next_billing_time parsed (Nov 16 2026).
        self.assertGreater(user["current_period_end"], time.time() + 20 * 86400)

    def test_webhook_activated_platinum_fallback_period(self):
        u = _user()
        handled, ok, msg = self._webhook(
            "BILLING.SUBSCRIPTION.ACTIVATED",
            {"id": "I-SUB2", "custom_id": f"prhyme:sub:platinum:{u['id']}"})
        self.assertTrue(handled and ok)
        user = bc.get_user(u["id"])
        self.assertEqual(user["plan"], "platinum")
        self.assertGreater(user["current_period_end"],
                           time.time() + 360 * 86400)

    def test_webhook_activated_bad_custom_id(self):
        handled, ok, msg = self._webhook(
            "BILLING.SUBSCRIPTION.ACTIVATED",
            {"id": "I-X", "custom_id": "garbage"})
        self.assertTrue(handled)
        self.assertFalse(ok)

    def test_webhook_cancelled(self):
        u = _user()
        bc.update_user(u["id"], plan="monthly", sub_status="active",
                       current_period_end=time.time() + 9999)
        handled, ok, msg = self._webhook(
            "BILLING.SUBSCRIPTION.CANCELLED",
            {"id": "I-SUB1", "custom_id": f"prhyme:sub:monthly:{u['id']}"})
        self.assertTrue(handled and ok)
        self.assertEqual(bc.get_user(u["id"])["sub_status"], "canceled")

    def test_webhook_payment_failed(self):
        u = _user()
        handled, ok, msg = self._webhook(
            "BILLING.SUBSCRIPTION.PAYMENT.FAILED",
            {"id": "I-SUB1", "custom_id": f"prhyme:sub:monthly:{u['id']}"})
        self.assertTrue(handled and ok)
        self.assertEqual(bc.get_user(u["id"])["sub_status"], "past_due")

    def test_webhook_sale_completed_renews(self):
        u = _user()
        bc.update_user(u["id"], plan="monthly", sub_status="active",
                       current_period_end=time.time() + 100)
        # Seed the subscription mapping as ACTIVATED would.
        self._webhook("BILLING.SUBSCRIPTION.ACTIVATED",
                      {"id": "I-SUB1",
                       "custom_id": f"prhyme:sub:monthly:{u['id']}"})
        before = bc.get_user(u["id"])["current_period_end"]
        handled, ok, msg = self._webhook(
            "PAYMENT.SALE.COMPLETED",
            {"id": "SALE-1", "billing_agreement_id": "I-SUB1",
             "amount": {"total": "9.00"}})
        self.assertTrue(handled and ok)
        self.assertGreater(bc.get_user(u["id"])["current_period_end"], before)
        self.assertTrue(any(p["plan"] == "monthly"
                            for p in bc.get_purchases(u["id"])))

    def test_webhook_capture_completed_fallback_grant(self):
        u = _user()
        handled, ok, msg = self._webhook(
            "PAYMENT.CAPTURE.COMPLETED",
            {"id": "CAP-9",
             "custom_id": f"prhyme:order:payg:{u['id']}:video",
             "amount": {"value": "2.00"},
             "supplementary_data": {"related_ids": {"order_id": "ORD-7"}}})
        self.assertTrue(handled and ok)
        self.assertEqual(pp.payg_balance(u["id"]).get("video"), 1)
        # Idempotent: second delivery grants nothing more.
        handled, ok, msg = self._webhook(
            "PAYMENT.CAPTURE.COMPLETED",
            {"id": "CAP-9",
             "custom_id": f"prhyme:order:payg:{u['id']}:video",
             "amount": {"value": "2.00"},
             "supplementary_data": {"related_ids": {"order_id": "ORD-7"}}})
        self.assertEqual(pp.payg_balance(u["id"]).get("video"), 1)

    def test_webhook_unknown_event_falls_through(self):
        handled, ok, msg = self._webhook("SOME.NEW.EVENT", {})
        self.assertFalse(handled)
        self.assertTrue(ok)

    def test_webhook_rejected_when_unverified(self):
        payload = json.dumps({"event_type": "BILLING.SUBSCRIPTION.ACTIVATED",
                              "resource": {}}).encode()
        with patch.object(pp, "verify_webhook", return_value=False):
            handled, ok, msg = pp.try_webhook({}, payload)
        self.assertFalse(handled)
        self.assertFalse(ok)

    # -- cancel ----------------------------------------------------------
    def test_cancel_marks_locally_even_if_api_fails(self):
        u = _user()
        bc.update_user(u["id"], plan="monthly", sub_status="active",
                       current_period_end=time.time() + 9999)
        pp._ensure_tables()
        con = bc._connect()
        con.execute("INSERT OR REPLACE INTO paypal_subscriptions"
                    " (uid, subscription_id, plan, status, updated_at)"
                    " VALUES (?,?,?,?,?)",
                    (u["id"], "I-GONE", "monthly", "active", time.time()))
        con.commit()
        con.close()

        def boom(m, p, b):
            raise pp.PayPalError("gone")
        self.fake_response = boom
        self.assertTrue(pp.cancel_subscription(bc.get_user(u["id"])))
        self.assertEqual(bc.get_user(u["id"])["sub_status"], "canceled")

    # -- consume_generation ----------------------------------------------
    def test_consume_generation_payment_required(self):
        u = _user()
        ok, via = pp.consume_generation(u["id"], "master")
        self.assertEqual((ok, via), (False, "payment_required"))

    def test_consume_generation_spends_credit(self):
        u = _user()
        pp.grant_payg_credit(u["id"], "stems")
        ok, via = pp.consume_generation(u["id"], "stems")
        self.assertEqual((ok, via), (True, "pay_per_use"))
        self.assertEqual(pp.payg_balance(u["id"]).get("stems"), 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
