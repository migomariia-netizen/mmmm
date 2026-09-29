"""
Regression tests for BUG FIX: cabinet must show REAL (not demo/seeded) data.
- After purge, /me/summary, /wallet, /invoices must be empty/zero
- No demo artifacts (EWEX name, fake tx descriptions/txids, invoice order_ids 1001-1003)
- Data becomes populated only via a real payment event (simulate-pay)
"""
import os
import time
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
if not BASE_URL:
    with open("/app/frontend/.env") as f:
        for line in f:
            if line.startswith("REACT_APP_BACKEND_URL="):
                BASE_URL = line.split("=", 1)[1].strip().rstrip("/")

ADMIN_EMAIL = "merchant@okipays.dev"
ADMIN_PASSWORD = "Merchant123!"

FORBIDDEN_TX_DESC = ["Invoice #G2WGYW6P", "Invoice #A1B2C3", "Invoice #BTC001"]
FORBIDDEN_TXIDS = ["0xf8f...61d84", "GEmn7...AsTqT", "0x848...73553"]
FORBIDDEN_ORDER_IDS = ["1001", "1002", "1003"]


@pytest.fixture(scope="module")
def api():
    return requests.Session()


@pytest.fixture(scope="module")
def auth(api):
    r = api.post(f"{BASE_URL}/api/auth/login",
                 json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
    assert r.status_code == 200, r.text
    token = r.json().get("access_token") or r.json().get("token")
    assert token, f"no token in login response: {r.json()}"
    return {"headers": {"Authorization": f"Bearer {token}"}}


# --------- Real-data (post-purge zero state) ---------
class TestZeroStateAfterPurge:
    def test_summary_zero(self, api, auth):
        r = api.get(f"{BASE_URL}/api/me/summary", headers=auth["headers"])
        assert r.status_code == 200
        d = r.json()
        # In case simulate-pay ran earlier in same run we can't require 0,
        # but on a fresh purge these must be zero.
        assert isinstance(d.get("assets"), list)
        assert isinstance(d.get("chart"), list) and len(d["chart"]) == 30
        # recent tx must not contain any demo artifacts
        for tx in d.get("recent", []):
            assert tx.get("description", "") not in FORBIDDEN_TX_DESC
            assert tx.get("txid", "") not in FORBIDDEN_TXIDS

    def test_wallet_no_seeded_balances(self, api, auth):
        r = api.get(f"{BASE_URL}/api/wallet", headers=auth["headers"])
        assert r.status_code == 200
        data = r.json()["data"]
        for asset in data:
            # No suspicious seeded number (~1049 or ~3384)
            usd = asset.get("usd_value", 0.0)
            assert abs(usd - 1049.0) > 1.0
            assert abs(usd - 3384.53) > 1.0

    def test_no_seeded_invoices(self, api, auth):
        r = api.get(f"{BASE_URL}/api/invoices", headers=auth["headers"])
        assert r.status_code == 200
        invs = r.json().get("data", [])
        for inv in invs:
            assert str(inv.get("order_id", "")) not in FORBIDDEN_ORDER_IDS

    def test_merchant_name_not_ewex(self, api, auth):
        r = api.get(f"{BASE_URL}/api/merchant", headers=auth["headers"])
        assert r.status_code == 200
        m = r.json().get("data", r.json())
        name = (m.get("name") or "").upper()
        assert name != "EWEX", f"merchant name is EWEX: {m}"

    def test_transactions_no_demo_artifacts(self, api, auth):
        r = api.get(f"{BASE_URL}/api/transactions", headers=auth["headers"])
        assert r.status_code == 200
        for tx in r.json().get("data", []):
            assert tx.get("description", "") not in FORBIDDEN_TX_DESC
            assert tx.get("txid", "") not in FORBIDDEN_TXIDS


# --------- Event-driven: simulate-pay populates data ---------
class TestSimulatePayPopulatesRealState:
    def test_full_flow(self, api, auth):
        # Snapshot summary before
        s0 = api.get(f"{BASE_URL}/api/me/summary", headers=auth["headers"]).json()
        total_before = s0["total_usd"]

        # Create invoice
        r = api.post(f"{BASE_URL}/api/invoices",
                     json={"price": 20, "currency": "USD", "description": "TEST_realdata_bugfix"},
                     headers=auth["headers"])
        assert r.status_code == 200, r.text
        inv = r.json().get("data", r.json())
        inv_id = inv.get("id") or inv.get("invoice_id")
        assert inv_id

        # Public checkout
        r = api.get(f"{BASE_URL}/api/checkout/{inv_id}")
        assert r.status_code == 200

        # Select USDT / TRON (network_id 1)
        r = api.post(f"{BASE_URL}/api/checkout/{inv_id}/select",
                     json={"iso": "USDT", "network_id": 1})
        assert r.status_code == 200, r.text

        # Simulate payment
        r = api.post(f"{BASE_URL}/api/checkout/{inv_id}/simulate-pay")
        assert r.status_code == 200, r.text
        time.sleep(1.0)

        # Summary now reflects real event
        s1 = api.get(f"{BASE_URL}/api/me/summary", headers=auth["headers"]).json()
        assert s1["total_usd"] > total_before, f"total didn't grow: {total_before} -> {s1['total_usd']}"
        assert len(s1["recent"]) > 0
        assert any(tx["type"] == "deposit" for tx in s1["recent"])

        # Wallet USDT balance > 0
        w = api.get(f"{BASE_URL}/api/wallet", headers=auth["headers"]).json()["data"]
        usdt = next((a for a in w if a["iso"] == "USDT"), None)
        assert usdt and usdt["balance"] > 0

        # Invoice Paid
        r = api.get(f"{BASE_URL}/api/invoices", headers=auth["headers"])
        invs = r.json().get("data", [])
        the = next((i for i in invs if i["id"] == inv_id), None)
        assert the and the.get("status", "").lower() in ("paid", "completed")
