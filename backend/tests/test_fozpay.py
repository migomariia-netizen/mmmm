"""FozPay backend tests (rebrand + admin-only user mgmt + hot wallet)."""
import os
import uuid
import hashlib
import pytest
import requests
from pathlib import Path


def _get_backend_url():
    url = os.environ.get("REACT_APP_BACKEND_URL")
    if not url:
        for line in Path("/app/frontend/.env").read_text().splitlines():
            if line.startswith("REACT_APP_BACKEND_URL="):
                url = line.split("=", 1)[1].strip()
    return url.rstrip("/")


BASE_URL = _get_backend_url()
ADMIN_EMAIL = "admin@fozpay.io"
ADMIN_PASSWORD = "FozPay#Admin2026"

MERCHANT_TOKEN = "c12a370e4be5f18af7aafec5ff55101327aa154ba9cc0da11a4b064e94430e2f"
MERCHANT_SECRET = "ec7127aa1e4a8da52b5fe48b84d156e5c4e04fdfaaac4b89abff949036154b21"


def _concat(obj):
    out = []
    def walk(o):
        if isinstance(o, dict):
            for k in sorted(o.keys()):
                walk(o[k])
        elif isinstance(o, (list, tuple)):
            for it in o:
                walk(it)
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


@pytest.fixture(scope="session")
def api():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


@pytest.fixture(scope="session")
def admin_auth(api):
    api.cookies.clear()
    r = api.post(f"{BASE_URL}/api/auth/login",
                 json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
    assert r.status_code == 200, r.text
    d = r.json()
    # clear cookies so shared session doesn't send them (we use Bearer explicitly)
    api.cookies.clear()
    return {"token": d["access_token"], "user": d["user"],
            "headers": {"Authorization": f"Bearer {d['access_token']}"}}


@pytest.fixture(autouse=True)
def _clear_cookies(api):
    """Ensure no leaked cookies between tests so Bearer tokens are used."""
    api.cookies.clear()
    yield
    api.cookies.clear()


# ============ Registration disabled ============
class TestRegistrationDisabled:
    def test_register_disabled_returns_403(self, api):
        r = api.post(f"{BASE_URL}/api/auth/register",
                     json={"email": f"x_{uuid.uuid4().hex[:6]}@ex.com",
                           "password": "Pass1234!", "name": "X"})
        assert r.status_code == 403, r.text
        # Ukrainian message expected
        body = r.text
        assert any(ord(c) > 127 for c in body), f"Expected Ukrainian text, got: {body}"


# ============ Admin login & role ============
class TestAdminLogin:
    def test_login_ok(self, admin_auth):
        assert admin_auth["user"]["role"] == "admin"
        assert admin_auth["user"]["email"] == ADMIN_EMAIL
        assert admin_auth["token"]


# ============ Admin user management ============
class TestAdminUsers:
    def test_list_users_requires_admin(self, api):
        r = api.get(f"{BASE_URL}/api/admin/users")
        assert r.status_code in (401, 403)

    def test_list_users_admin(self, api, admin_auth):
        r = api.get(f"{BASE_URL}/api/admin/users", headers=admin_auth["headers"])
        assert r.status_code == 200, r.text
        j = r.json()
        users = j.get("data", j) if isinstance(j, dict) else j
        assert isinstance(users, list)
        emails = [u.get("email") for u in users]
        assert ADMIN_EMAIL in emails

    def test_create_user_then_duplicate(self, api, admin_auth):
        email = f"test_{uuid.uuid4().hex[:8]}@fozpay.test"
        payload = {"email": email, "password": "InitPass1!", "name": "Test User"}
        r = api.post(f"{BASE_URL}/api/admin/users", json=payload,
                     headers=admin_auth["headers"])
        assert r.status_code == 200, r.text
        j = r.json()
        user = j.get("data", j)
        assert user.get("email") == email
        assert user.get("role") == "user"
        user_id = user.get("user_id") or user.get("id") or user.get("_id")
        assert user_id
        pytest.shared_user = {"id": user_id, "email": email, "password": "InitPass1!"}

        # Duplicate
        r2 = api.post(f"{BASE_URL}/api/admin/users", json=payload,
                      headers=admin_auth["headers"])
        assert r2.status_code == 400, r2.text

    def test_non_admin_cannot_list_users(self):
        # login as newly created user with fresh session (avoid cookie leaking)
        u = getattr(pytest, "shared_user", None)
        assert u, "user fixture missing"
        r = requests.post(f"{BASE_URL}/api/auth/login",
                          json={"email": u["email"], "password": u["password"]})
        assert r.status_code == 200, r.text
        tok = r.json()["access_token"]
        r2 = requests.get(f"{BASE_URL}/api/admin/users",
                          headers={"Authorization": f"Bearer {tok}"})
        assert r2.status_code == 403, r2.text
        pytest.shared_user["token"] = tok

    def test_change_password(self, api, admin_auth):
        u = pytest.shared_user
        new_pw = "NewPass2!@"
        # clear any cookies from previous logins so admin bearer is used
        api.cookies.clear()
        r = api.put(f"{BASE_URL}/api/admin/users/password",
                    json={"user_id": u["id"], "password": new_pw},
                    headers=admin_auth["headers"])
        assert r.status_code == 200, r.text
        # login with new
        r2 = requests.post(f"{BASE_URL}/api/auth/login",
                           json={"email": u["email"], "password": new_pw})
        assert r2.status_code == 200, r2.text
        # login with old fails
        r3 = requests.post(f"{BASE_URL}/api/auth/login",
                           json={"email": u["email"], "password": u["password"]})
        assert r3.status_code == 401
        pytest.shared_user["password"] = new_pw

    def test_admin_cannot_delete_self(self, api, admin_auth):
        api.cookies.clear()
        admin_id = admin_auth["user"].get("user_id") or admin_auth["user"].get("id")
        assert admin_id, f"admin user has no id field: {admin_auth['user']}"
        r = api.delete(f"{BASE_URL}/api/admin/users/{admin_id}",
                       headers=admin_auth["headers"])
        assert r.status_code == 400, r.text

    def test_delete_user(self, api, admin_auth):
        u = pytest.shared_user
        api.cookies.clear()
        r = api.delete(f"{BASE_URL}/api/admin/users/{u['id']}",
                       headers=admin_auth["headers"])
        assert r.status_code == 200, r.text
        # cannot login
        r2 = requests.post(f"{BASE_URL}/api/auth/login",
                           json={"email": u["email"], "password": u["password"]})
        assert r2.status_code == 401


# ============ Hot wallet ============
class TestHotWallet:
    def test_get_requires_admin(self, api, admin_auth):
        email = f"hw_{uuid.uuid4().hex[:6]}@fozpay.test"
        h = admin_auth["headers"]
        cr = api.post(f"{BASE_URL}/api/admin/users",
                      json={"email": email, "password": "UserPass1!", "name": "hw"},
                      headers=h)
        assert cr.status_code == 200, cr.text
        u = (cr.json().get("data") or cr.json())
        uid = u.get("user_id") or u.get("id")
        login = requests.post(f"{BASE_URL}/api/auth/login",
                              json={"email": email, "password": "UserPass1!"}).json()
        utok = login["access_token"]
        r = requests.get(f"{BASE_URL}/api/admin/hot-wallet",
                         headers={"Authorization": f"Bearer {utok}"})
        assert r.status_code == 403, r.text
        api.delete(f"{BASE_URL}/api/admin/users/{uid}", headers=h)

    def test_get_hot_wallet_admin(self, api, admin_auth):
        r = api.get(f"{BASE_URL}/api/admin/hot-wallet", headers=admin_auth["headers"])
        assert r.status_code == 200, r.text
        j = r.json()
        d = j.get("data", j)
        assert "evm_address" in d
        assert "tron_address" in d
        assert d["evm_address"].startswith("0x")
        assert d["tron_address"].startswith("T")
        assert "balances" in d and isinstance(d["balances"], list)
        assert "total_usd" in d

    def test_withdraw_insufficient(self, api, admin_auth):
        r = api.post(f"{BASE_URL}/api/admin/hot-wallet/withdraw",
                     json={"chain": "ethereum", "iso": "USDT",
                           "to_address": "0x1111111111111111111111111111111111111111",
                           "amount": 1},
                     headers=admin_auth["headers"])
        assert r.status_code == 400, r.text
        assert "Недостатньо" in r.text or "insufficient" in r.text.lower()

    def test_withdraw_non_evm_rejected(self, api, admin_auth):
        r = api.post(f"{BASE_URL}/api/admin/hot-wallet/withdraw",
                     json={"chain": "tron", "iso": "USDT",
                           "to_address": "TXYZxxxxxxxxxxxxxxxxxxxxxxxxxxx",
                           "amount": 1},
                     headers=admin_auth["headers"])
        assert r.status_code == 400, r.text


# ============ Wallet endpoints ============
class TestWallet:
    def test_deposit_address_evm(self, api, admin_auth):
        r = api.post(f"{BASE_URL}/api/wallet/deposit-address",
                     json={"currency": "USDT", "network_id": 1},
                     headers=admin_auth["headers"])
        assert r.status_code == 200, r.text
        addr = (r.json().get("data") or r.json())["address"]
        assert addr.startswith("0x") and len(addr) == 42

    def test_deposit_address_tron(self, api, admin_auth):
        r = api.post(f"{BASE_URL}/api/wallet/deposit-address",
                     json={"currency": "USDT", "network_id": 2},
                     headers=admin_auth["headers"])
        assert r.status_code == 200, r.text
        addr = (r.json().get("data") or r.json())["address"]
        assert addr.startswith("T")

    def test_exchange_insufficient(self, api, admin_auth):
        h = admin_auth["headers"]
        email = f"swap_{uuid.uuid4().hex[:6]}@fozpay.test"
        cr = api.post(f"{BASE_URL}/api/admin/users",
                      json={"email": email, "password": "SwapPass1!", "name": "s"},
                      headers=h)
        u = (cr.json().get("data") or cr.json())
        uid = u.get("user_id") or u.get("id")
        login = requests.post(f"{BASE_URL}/api/auth/login",
                              json={"email": email, "password": "SwapPass1!"}).json()
        utok = login["access_token"]
        r = requests.post(f"{BASE_URL}/api/wallet/exchange",
                          json={"from_iso": "USDT", "to_iso": "BTC", "amount": 5},
                          headers={"Authorization": f"Bearer {utok}"})
        assert r.status_code == 400, r.text
        r2 = requests.post(f"{BASE_URL}/api/wallet/withdraw",
                           json={"currency": "USDT", "network_id": 1, "amount": 5,
                                 "address": "0x1111111111111111111111111111111111111111"},
                           headers={"Authorization": f"Bearer {utok}"})
        assert r2.status_code == 400, r2.text
        api.delete(f"{BASE_URL}/api/admin/users/{uid}", headers=h)


# ============ Prices ============
class TestPrices:
    def test_prices(self, api):
        r = api.get(f"{BASE_URL}/api/prices")
        assert r.status_code == 200
        j = r.json()
        data = j.get("data", j)
        assert isinstance(data, list) and len(data) > 0
        by_iso = {c["iso"]: c for c in data}
        assert "USDT" in by_iso and abs(by_iso["USDT"]["price"] - 1) < 0.05
        assert "BTC" in by_iso and by_iso["BTC"]["price"] > 0


# ============ Merchant private API ============
class TestMerchantPrivate:
    def test_public_currency_list(self, api):
        r = api.get(f"{BASE_URL}/api/v1/public/currency-list")
        assert r.status_code == 200
        j = r.json()
        data = j.get("data", j)
        assert isinstance(data, list) and len(data) > 0

    def test_private_coins(self, api):
        r = api.post(f"{BASE_URL}/api/v1/private/coins",
                     headers={"X-Auth-Token": MERCHANT_TOKEN})
        # may be GET or POST — try both
        if r.status_code == 405:
            r = api.get(f"{BASE_URL}/api/v1/private/coins",
                        headers={"X-Auth-Token": MERCHANT_TOKEN})
        assert r.status_code == 200, r.text
        j = r.json()
        assert j.get("status") is True
        assert "data" in j
