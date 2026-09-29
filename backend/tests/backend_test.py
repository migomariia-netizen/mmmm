"""Backend E2E tests for OKIPAYS clone.
Covers: auth, wallet, invoices, checkout, contacts, merchant, public+private OKIPAYS API.
"""
import os
import hashlib
import time
import uuid

import pytest
import requests

BASE_URL = os.environ["REACT_APP_BACKEND_URL"].rstrip("/") if os.environ.get("REACT_APP_BACKEND_URL") else None
if not BASE_URL:
    # fall back to frontend .env
    from pathlib import Path
    for line in Path("/app/frontend/.env").read_text().splitlines():
        if line.startswith("REACT_APP_BACKEND_URL="):
            BASE_URL = line.split("=", 1)[1].strip().rstrip("/")

ADMIN_EMAIL = "merchant@okipays.dev"
ADMIN_PASSWORD = "Merchant123!"


# -------------------- helpers --------------------
def _concat(obj):
    out = []
    def walk(o):
        if isinstance(o, dict):
            for k in sorted(o.keys()):
                walk(o[k])
        elif isinstance(o, (list, tuple)):
            for item in o:
                walk(item)
        elif isinstance(o, bool):
            out.append("1" if o else "0")
        elif o is None:
            out.append("")
        else:
            out.append(str(o))
    walk(obj)
    return "".join(out)


def sign(body, secret):
    return hashlib.sha256((_concat(body) + secret).encode()).hexdigest()


# -------------------- fixtures --------------------
@pytest.fixture(scope="session")
def api():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


@pytest.fixture(scope="session")
def auth(api):
    r = api.post(f"{BASE_URL}/api/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
    assert r.status_code == 200, r.text
    data = r.json()
    token = data["access_token"]
    return {"token": token, "user": data["user"], "headers": {"Authorization": f"Bearer {token}"}}


@pytest.fixture(scope="session")
def merchant_creds(api, auth):
    r = api.get(f"{BASE_URL}/api/merchant", headers=auth["headers"])
    assert r.status_code == 200
    m = r.json()["data"]
    return {"token": m["token"], "secret": m["secret"]}


# ============ AUTH ============
class TestAuth:
    def test_login_success(self, api):
        r = api.post(f"{BASE_URL}/api/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
        assert r.status_code == 200
        j = r.json()
        assert "access_token" in j and j["user"]["email"] == ADMIN_EMAIL

    def test_login_invalid(self, api):
        r = api.post(f"{BASE_URL}/api/auth/login", json={"email": ADMIN_EMAIL, "password": "wrong"})
        assert r.status_code == 401

    def test_me_with_bearer(self, api, auth):
        r = api.get(f"{BASE_URL}/api/auth/me", headers=auth["headers"])
        assert r.status_code == 200
        assert r.json()["email"] == ADMIN_EMAIL

    def test_me_unauth(self):
        r = requests.get(f"{BASE_URL}/api/auth/me")
        assert r.status_code == 401

    def test_register_new_user(self, api):
        email = f"test_{uuid.uuid4().hex[:8]}@example.com"
        r = api.post(f"{BASE_URL}/api/auth/register",
                     json={"email": email, "password": "Pass1234!", "name": "T"})
        assert r.status_code == 200, r.text
        j = r.json()
        assert j["user"]["email"] == email and "access_token" in j
        # verify /me with token
        r2 = api.get(f"{BASE_URL}/api/auth/me",
                     headers={"Authorization": f"Bearer {j['access_token']}"})
        assert r2.status_code == 200

    def test_logout(self, api):
        r = api.post(f"{BASE_URL}/api/auth/logout")
        assert r.status_code == 200


# ============ PRICES + SUMMARY ============
class TestDashboard:
    def test_prices(self, api):
        r = api.get(f"{BASE_URL}/api/prices")
        assert r.status_code == 200
        d = r.json()["data"]
        assert len(d) == 8
        for c in d:
            assert "price" in c and "change" in c and "iso" in c

    def test_summary(self, api, auth):
        r = api.get(f"{BASE_URL}/api/me/summary", headers=auth["headers"])
        assert r.status_code == 200
        j = r.json()
        assert "total_usd" in j and "available_usd" in j
        assert len(j["assets"]) == 8
        assert len(j["chart"]) == 31
        assert isinstance(j["recent"], list)


# ============ WALLET ============
class TestWallet:
    def test_wallet_list(self, api, auth):
        r = api.get(f"{BASE_URL}/api/wallet", headers=auth["headers"])
        assert r.status_code == 200
        data = r.json()["data"]
        assert len(data) == 8
        for a in data:
            assert "networks" in a and len(a["networks"]) >= 1

    def test_deposit_address_tron_usdt(self, api, auth):
        r = api.post(f"{BASE_URL}/api/wallet/deposit-address",
                     json={"currency": "USDT", "network_id": 2}, headers=auth["headers"])
        assert r.status_code == 200, r.text
        addr = r.json()["data"]["address"]
        assert addr.startswith("T"), f"TRON address expected: {addr}"

    def test_deposit_address_btc(self, api, auth):
        r = api.post(f"{BASE_URL}/api/wallet/deposit-address",
                     json={"currency": "BTC", "network_id": 0}, headers=auth["headers"])
        assert r.status_code == 200, r.text
        addr = r.json()["data"]["address"]
        assert addr.startswith("bc1") or addr.startswith("1") or addr.startswith("3"), addr

    def test_deposit_address_eth(self, api, auth):
        r = api.post(f"{BASE_URL}/api/wallet/deposit-address",
                     json={"currency": "ETH", "network_id": 1}, headers=auth["headers"])
        assert r.status_code == 200, r.text
        assert r.json()["data"]["address"].startswith("0x")

    def test_withdraw_insufficient(self, api, auth):
        r = api.post(f"{BASE_URL}/api/wallet/withdraw",
                     json={"currency": "BTC", "network_id": 0, "amount": 999999, "address": "bc1qxxxx"},
                     headers=auth["headers"])
        assert r.status_code == 400

    def test_withdraw_ok(self, api, auth):
        # USDT should have seeded 1049
        r = api.post(f"{BASE_URL}/api/wallet/withdraw",
                     json={"currency": "USDT", "network_id": 2, "amount": 1.0, "address": "TXYZxxxxxxxxxxxxxxxxxxxxxxxxxxx"},
                     headers=auth["headers"])
        assert r.status_code == 200, r.text
        assert r.json()["data"]["status"] == "Pending"

    def test_exchange(self, api, auth):
        # get balance first
        bal = api.get(f"{BASE_URL}/api/wallet", headers=auth["headers"]).json()["data"]
        usdt = next(a for a in bal if a["iso"] == "USDT")
        if usdt["balance_available"] < 5:
            pytest.skip("insufficient USDT balance for exchange test")
        r = api.post(f"{BASE_URL}/api/wallet/exchange",
                     json={"from_iso": "USDT", "to_iso": "TRX", "amount": 5.0},
                     headers=auth["headers"])
        assert r.status_code == 200, r.text
        d = r.json()["data"]
        assert d["received"] > 0 and d["fee_usd"] > 0


# ============ INVOICES + CHECKOUT ============
class TestInvoiceCheckout:
    inv_id = None

    def test_create_invoice(self, api, auth):
        r = api.post(f"{BASE_URL}/api/invoices",
                     json={"order_id": f"TEST_{uuid.uuid4().hex[:6]}", "price": 12.5,
                           "payment_currency_iso": "USD", "description": "test"},
                     headers=auth["headers"])
        assert r.status_code == 200, r.text
        d = r.json()["data"]
        assert d["id"] and "/checkout/" in d["link"]
        TestInvoiceCheckout.inv_id = d["id"]

    def test_list_invoices(self, api, auth):
        r = api.get(f"{BASE_URL}/api/invoices", headers=auth["headers"])
        assert r.status_code == 200
        assert isinstance(r.json()["data"], list)

    def test_checkout_get_public(self, api):
        assert TestInvoiceCheckout.inv_id
        r = api.get(f"{BASE_URL}/api/checkout/{TestInvoiceCheckout.inv_id}")
        assert r.status_code == 200
        d = r.json()["data"]
        assert d["id"] == TestInvoiceCheckout.inv_id
        assert "merchant" in d and "currency_meta" in d and "network_meta" in d

    def test_checkout_select_and_pay(self, api):
        assert TestInvoiceCheckout.inv_id
        r = api.post(f"{BASE_URL}/api/checkout/{TestInvoiceCheckout.inv_id}/select",
                     json={"iso": "USDT", "network_id": 2})
        assert r.status_code == 200, r.text
        pay_info = r.json()["data"]
        assert pay_info["address"].startswith("T")
        assert pay_info["amount"] > 0 and pay_info["amount_to_pay"] > 0

        r2 = api.post(f"{BASE_URL}/api/checkout/{TestInvoiceCheckout.inv_id}/simulate-pay")
        assert r2.status_code == 200, r2.text
        assert r2.json()["data"]["status"] == "Paid"

    def test_cancel_invoice(self, api, auth):
        r = api.post(f"{BASE_URL}/api/invoices",
                     json={"order_id": f"TEST_C_{uuid.uuid4().hex[:6]}", "price": 1.0},
                     headers=auth["headers"])
        iid = r.json()["data"]["id"]
        r2 = api.post(f"{BASE_URL}/api/invoices/{iid}/cancel", headers=auth["headers"])
        assert r2.status_code == 200


# ============ CONTACTS ============
class TestContacts:
    def test_contacts_crud(self, api, auth):
        # create
        r = api.post(f"{BASE_URL}/api/contacts",
                     json={"name": "TEST_c", "address": "0xdeadbeef", "network_id": 1, "currency": "ETH"},
                     headers=auth["headers"])
        assert r.status_code == 200
        cid = r.json()["data"]["contact_id"]
        # list
        r2 = api.get(f"{BASE_URL}/api/contacts", headers=auth["headers"])
        assert any(c["contact_id"] == cid for c in r2.json()["data"])
        # delete
        r3 = api.delete(f"{BASE_URL}/api/contacts/{cid}", headers=auth["headers"])
        assert r3.status_code == 200


# ============ MERCHANT SETTINGS ============
class TestMerchant:
    def test_merchant_get(self, api, auth):
        r = api.get(f"{BASE_URL}/api/merchant", headers=auth["headers"])
        assert r.status_code == 200
        d = r.json()["data"]
        assert d["token"] and d["secret"]

    def test_merchant_update(self, api, auth):
        r = api.put(f"{BASE_URL}/api/merchant",
                    json={"name": "TEST_M", "brand_color": "#123456", "description": "d"},
                    headers=auth["headers"])
        assert r.status_code == 200
        d = r.json()["data"]
        assert d["name"] == "TEST_M" and d["brand_color"] == "#123456"

    def test_merchant_regenerate(self, api, auth):
        old = api.get(f"{BASE_URL}/api/merchant", headers=auth["headers"]).json()["data"]
        r = api.post(f"{BASE_URL}/api/merchant/regenerate", headers=auth["headers"])
        assert r.status_code == 200
        new = r.json()["data"]
        assert new["token"] != old["token"] and new["secret"] != old["secret"]


# ============ PUBLIC OKIPAYS API ============
class TestPublicApi:
    def test_currency_list(self, api):
        r = api.get(f"{BASE_URL}/api/v1/public/currency-list")
        assert r.status_code == 200
        assert isinstance(r.json()["data"], list)

    def test_currency_network_list(self, api):
        r = api.get(f"{BASE_URL}/api/v1/public/currency-network-list")
        assert r.status_code == 200
        data = r.json()["data"]
        assert len(data) == 8
        assert all("networks" in c for c in data)


# ============ PRIVATE OKIPAYS API (signature) ============
class TestPrivateApi:
    def test_coins_no_token(self, api):
        r = api.get(f"{BASE_URL}/api/v1/private/coins")
        assert r.status_code == 401

    def test_coins_invalid_token(self, api):
        r = api.get(f"{BASE_URL}/api/v1/private/coins",
                    headers={"X-Auth-Token": "bad"})
        assert r.status_code == 401

    def test_coins_ok(self, api, merchant_creds):
        r = api.get(f"{BASE_URL}/api/v1/private/coins",
                    headers={"X-Auth-Token": merchant_creds["token"]})
        assert r.status_code == 200
        data = r.json()["data"]
        assert "USDT" in data and "networks" in data["USDT"]

    def test_get_address_bad_signature(self, api, merchant_creds):
        body = {"currency": "USDT", "network": "TRC 20"}
        r = api.post(f"{BASE_URL}/api/v1/private/get-address", json=body,
                     headers={"X-Auth-Token": merchant_creds["token"],
                              "X-Auth-Sign": "deadbeef"})
        assert r.status_code == 400
        assert "Signature" in r.text

    def test_get_address_ok(self, api, merchant_creds):
        body = {"currency": "USDT", "network": "TRC 20"}
        s = sign(body, merchant_creds["secret"])
        r = api.post(f"{BASE_URL}/api/v1/private/get-address", json=body,
                     headers={"X-Auth-Token": merchant_creds["token"], "X-Auth-Sign": s})
        assert r.status_code == 200, r.text
        assert r.json()["data"]["address"].startswith("T")

    def test_order_create_and_get(self, api, merchant_creds):
        body = {"order_id": f"TEST_O_{uuid.uuid4().hex[:6]}", "price": 5,
                "payment_currency_iso": "USD", "description": "d"}
        s = sign(body, merchant_creds["secret"])
        r = api.post(f"{BASE_URL}/api/v1/order/create", json=body,
                     headers={"X-Auth-Token": merchant_creds["token"], "X-Auth-Sign": s})
        assert r.status_code == 200, r.text
        d = r.json()["data"]
        assert d["id"] and "/checkout/" in d["link"]

        gbody = {"order_id": body["order_id"]}
        gs = sign(gbody, merchant_creds["secret"])
        r2 = api.post(f"{BASE_URL}/api/v1/order/get", json=gbody,
                      headers={"X-Auth-Token": merchant_creds["token"], "X-Auth-Sign": gs})
        assert r2.status_code == 200
        assert r2.json()["data"]["order_id"] == body["order_id"]

    def test_pay_in(self, api, merchant_creds):
        body = {"currency": "USDT", "network": "TRC 20", "amount": 10,
                "order_id": f"TEST_P_{uuid.uuid4().hex[:6]}"}
        s = sign(body, merchant_creds["secret"])
        r = api.post(f"{BASE_URL}/api/v1/merchant/pay-in", json=body,
                     headers={"X-Auth-Token": merchant_creds["token"], "X-Auth-Sign": s})
        assert r.status_code == 200, r.text
        d = r.json()["data"]
        assert d["pay_info"]["address"].startswith("T")

    def test_balance(self, api, merchant_creds):
        body = {"currency": "USDT"}
        s = sign(body, merchant_creds["secret"])
        r = api.post(f"{BASE_URL}/api/v1/merchant/balance", json=body,
                     headers={"X-Auth-Token": merchant_creds["token"], "X-Auth-Sign": s})
        assert r.status_code == 200, r.text
        d = r.json()["data"]
        assert d["currency"]["iso3"] == "USDT" and "balance" in d
