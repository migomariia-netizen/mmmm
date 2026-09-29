"""Tests for FozPay new features:
- Deposit amount fix (amount_to_pay == amount)
- Per-currency+network withdrawal fee matrix
- Auto-convert from USDT branch
- explorer_url on transactions
- Admin users list with balance_usdt
"""
import os
import time
import uuid
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
if not BASE_URL:
    from pathlib import Path
    for line in Path("/app/frontend/.env").read_text().splitlines():
        if line.startswith("REACT_APP_BACKEND_URL="):
            BASE_URL = line.split("=", 1)[1].strip().rstrip("/")
ADMIN_EMAIL = "admin@fozpay.io"
ADMIN_PASSWORD = "FozPay#Admin2026"


@pytest.fixture(scope="session")
def api():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


@pytest.fixture(scope="session")
def admin_token(api):
    r = api.post(f"{BASE_URL}/api/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
    assert r.status_code == 200, r.text
    return r.json()["access_token"] if "access_token" in r.json() else r.json().get("token")


@pytest.fixture(scope="session")
def admin_api(api, admin_token):
    api.headers.update({"Authorization": f"Bearer {admin_token}"})
    return api


# ------- Admin login -------
class TestAdminLogin:
    def test_login_success(self, api):
        r = api.post(f"{BASE_URL}/api/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
        assert r.status_code == 200, r.text
        j = r.json()
        assert "access_token" in j or "token" in j

    def test_me(self, admin_api):
        r = admin_api.get(f"{BASE_URL}/api/auth/me")
        assert r.status_code == 200
        assert r.json().get("email") == ADMIN_EMAIL


# ------- Platform fees matrix -------
class TestPlatformFees:
    def test_get_matrix(self, admin_api):
        r = admin_api.get(f"{BASE_URL}/api/admin/platform-fees")
        assert r.status_code == 200, r.text
        j = r.json().get("data", r.json())
        assert "withdrawal_fee_matrix" in j, j
        matrix = j["withdrawal_fee_matrix"]
        assert isinstance(matrix, list)
        assert len(matrix) == 16, f"Expected 16 rows, got {len(matrix)}: {matrix}"
        for row in matrix:
            assert "cabinet" in row and "api" in row
            assert "iso" in row or "currency" in row or "key" in row

    def test_put_matrix_persists(self, admin_api):
        payload = {"withdrawal_fee_by_key": {"BNB:4": {"cabinet": 0.02, "api": 0.03}}}
        r = admin_api.put(f"{BASE_URL}/api/admin/platform-fees", json=payload)
        assert r.status_code == 200, r.text
        r2 = admin_api.get(f"{BASE_URL}/api/admin/platform-fees")
        j = r2.json().get("data", r2.json())
        by_key = j.get("withdrawal_fee_by_key") or {}
        assert "BNB:4" in by_key, by_key
        assert float(by_key["BNB:4"]["cabinet"]) == 0.02
        assert float(by_key["BNB:4"]["api"]) == 0.03
        matrix = j["withdrawal_fee_matrix"]
        bnb4 = [row for row in matrix if (row.get("key") == "BNB:4" or (row.get("iso") == "BNB" and str(row.get("network_id")) == "4"))]
        assert bnb4, f"BNB:4 row not found in matrix"
        assert float(bnb4[0]["cabinet"]) == 0.02
        assert float(bnb4[0]["api"]) == 0.03


# ------- Deposit amount fix -------
class TestDepositAmount:
    def test_amount_to_pay_equals_amount(self, admin_api):
        order_id = f"TEST_{uuid.uuid4().hex[:12]}"
        r = admin_api.post(f"{BASE_URL}/api/invoices", json={
            "order_id": order_id, "price": 3, "payment_currency_iso": "USDT"
        })
        assert r.status_code in (200, 201), r.text
        inv = r.json().get("data", r.json())
        inv_id = inv.get("id") or inv.get("invoice_id") or inv.get("_id")
        assert inv_id, inv
        r2 = admin_api.post(f"{BASE_URL}/api/checkout/{inv_id}/select", json={
            "iso": "USDT", "network_id": 4
        })
        assert r2.status_code == 200, r2.text
        j = r2.json().get("data", r2.json())
        assert float(j.get("amount_to_pay")) == 3.0, j
        # amount is 3, platform fee separate
        if "platform_fee" in j:
            assert float(j["platform_fee"]) >= 0


# ------- Auto-convert withdraw branch -------
class TestWithdrawAutoConvert:
    def test_auto_convert_hint_for_evm(self, admin_api):
        r = admin_api.post(f"{BASE_URL}/api/wallet/withdraw", json={
            "currency": "BNB", "network_id": 4, "amount": 0.01,
            "address": "0x0000000000000000000000000000000000000001", "source": "cabinet"
        })
        assert r.status_code == 400, r.text
        detail = (r.json().get("detail") or "").lower()
        # Ukrainian message with 'авто-конвертації потрібно' and USDT
        assert "usdt" in detail or "конверт" in detail, f"Missing auto-convert hint: {r.json()}"

    def test_no_convert_for_btc(self, admin_api):
        r = admin_api.post(f"{BASE_URL}/api/wallet/withdraw", json={
            "currency": "BTC", "network_id": 0, "amount": 0.001,
            "address": "bc1qxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx0", "source": "cabinet"
        })
        assert r.status_code == 400, r.text
        detail = (r.json().get("detail") or "")
        assert "конверт" not in detail.lower(), f"Should not offer conversion for BTC: {detail}"
        assert "недостатньо" in detail.lower() or "коштів" in detail.lower(), detail


# ------- Admin users with balance_usdt -------
class TestAdminUsers:
    def test_users_list_has_balance_usdt(self, admin_api):
        r = admin_api.get(f"{BASE_URL}/api/admin/users")
        assert r.status_code == 200, r.text
        users = r.json().get("data", r.json())
        assert isinstance(users, list) and len(users) >= 1
        for u in users:
            assert "balance_usdt" in u, u
            assert isinstance(u["balance_usdt"], (int, float))
            assert "balances" in u
            if u["balances"]:
                for b in u["balances"]:
                    assert "iso" in b and "balance" in b


# ------- Transactions explorer_url -------
class TestExplorerUrl:
    def test_wallet_transactions_have_explorer_url_key(self, admin_api):
        r = admin_api.get(f"{BASE_URL}/api/wallet")
        assert r.status_code == 200, r.text
        j = r.json()
        txs = j.get("transactions") or j.get("txs") or []
        # try alternate endpoint
        if not txs:
            r2 = admin_api.get(f"{BASE_URL}/api/wallet/transactions")
            if r2.status_code == 200:
                txs = r2.json()
        # Trigger creating a withdraw tx by intentionally failing (should not add tx though).
        # Instead check schema on any existing txs
        for tx in txs:
            assert "explorer_url" in tx, f"tx missing explorer_url: {tx}"


# ------- Regression -------
class TestRegression:
    def test_wallet(self, admin_api):
        r = admin_api.get(f"{BASE_URL}/api/wallet")
        assert r.status_code == 200, r.text

    def test_currencies(self, admin_api):
        r = admin_api.get(f"{BASE_URL}/api/currencies")
        assert r.status_code == 200, r.text
        data = r.json().get("data", r.json())
        assert isinstance(data, list)

    def test_invoices_list(self, admin_api):
        r = admin_api.get(f"{BASE_URL}/api/invoices")
        assert r.status_code == 200, r.text

    def test_create_invoice(self, admin_api):
        order_id = f"TEST_{uuid.uuid4().hex[:12]}"
        r = admin_api.post(f"{BASE_URL}/api/invoices", json={
            "order_id": order_id, "price": 5, "payment_currency_iso": "USDT"
        })
        assert r.status_code in (200, 201), r.text

    def test_register_disabled(self, api):
        r = api.post(f"{BASE_URL}/api/auth/register", json={
            "email": "x@x.com", "password": "xxxxxxxx"
        })
        assert r.status_code == 403, r.text
