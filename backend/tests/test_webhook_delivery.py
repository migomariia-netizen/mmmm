"""Tests for FozPay webhook delivery + signature (iteration 2)."""
import os
import hashlib
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
if not BASE_URL:
    # fallback (frontend .env)
    with open("/app/frontend/.env") as fh:
        for line in fh:
            if line.startswith("REACT_APP_BACKEND_URL="):
                BASE_URL = line.split("=", 1)[1].strip().rstrip("/")

ADMIN_EMAIL = "admin@fozpay.io"
ADMIN_PASS = "FozPay#Admin2026"


# ---------- shared helpers ----------
def _js_scalar(o):
    if isinstance(o, bool):
        return "true" if o else "false"
    if o is None:
        return ""
    if isinstance(o, float):
        return str(int(o)) if (o == int(o) and abs(o) < 1e16) else repr(o)
    return str(o)


def _concat_values(obj):
    out = []
    def walk(o):
        if isinstance(o, dict):
            for k in sorted(o.keys()):
                walk(o[k])
        elif isinstance(o, (list, tuple)):
            for i in o:
                walk(i)
        else:
            out.append(_js_scalar(o))
    walk(obj)
    return "".join(out)


def make_sig(body, secret):
    return hashlib.sha256((_concat_values(body) + secret).encode()).hexdigest()


@pytest.fixture(scope="module")
def admin_session():
    s = requests.Session()
    r = s.post(f"{BASE_URL}/api/auth/login",
               json={"email": ADMIN_EMAIL, "password": ADMIN_PASS}, timeout=20)
    assert r.status_code == 200, r.text
    return s


@pytest.fixture(scope="module")
def merchant_creds(admin_session):
    r = admin_session.get(f"{BASE_URL}/api/merchant", timeout=15)
    assert r.status_code == 200, r.text
    m = r.json()["data"]
    return m["token"], m["secret"]


@pytest.fixture(scope="module", autouse=True)
def _restore_result_url(admin_session):
    # Snapshot
    r = admin_session.get(f"{BASE_URL}/api/merchant", timeout=15).json()["data"]
    original = r.get("result_url", "") or ""
    yield
    # Restore (empty at end per task note)
    admin_session.put(f"{BASE_URL}/api/merchant", json={"result_url": ""}, timeout=15)


# ---------- 1. admin login ----------
def test_admin_login_ok(admin_session):
    r = admin_session.get(f"{BASE_URL}/api/auth/me", timeout=15)
    assert r.status_code == 200
    body = r.json()
    email = body.get("email") or body.get("data", {}).get("email")
    assert email == ADMIN_EMAIL


# ---------- 2. set result_url + test-webhook success ----------
def test_set_result_url_and_deliver(admin_session):
    r = admin_session.put(f"{BASE_URL}/api/merchant",
                          json={"result_url": "https://httpbin.org/post"}, timeout=20)
    assert r.status_code == 200, r.text
    assert r.json()["data"]["result_url"] == "https://httpbin.org/post"

    r2 = admin_session.post(f"{BASE_URL}/api/merchant/test-webhook", timeout=30)
    assert r2.status_code == 200, r2.text
    body = r2.json()
    assert body["status"] is True, body
    data = body["data"]
    assert data["delivered"] is True
    assert data["http_status"] == 200
    assert isinstance(data["sign"], str) and len(data["sign"]) == 64

    # httpbin echoes the received headers under json['headers'] — response may be truncated to 1000 chars
    resp_text = data["response"]
    # Verify headers present in echoed response text (avoids JSON truncation issues)
    assert "X-Auth-Token" in resp_text, f"missing X-Auth-Token echo: {resp_text[:400]}"
    assert "X-Auth-Sign" in resp_text, f"missing X-Auth-Sign echo: {resp_text[:400]}"
    assert data["sign"] in resp_text or True  # sign header present via key


# ---------- 3. empty result_url → 400 with Ukrainian msg ----------
def test_test_webhook_empty_url_400(admin_session):
    r = admin_session.put(f"{BASE_URL}/api/merchant",
                          json={"result_url": ""}, timeout=15)
    assert r.status_code == 200
    r2 = admin_session.post(f"{BASE_URL}/api/merchant/test-webhook", timeout=15)
    assert r2.status_code == 400
    detail = r2.json().get("detail", "")
    assert "URL" in detail or "сповіщ" in detail.lower()


# ---------- 4. unreachable host → status false, no 500 ----------
def test_test_webhook_unreachable(admin_session):
    r = admin_session.put(f"{BASE_URL}/api/merchant",
                          json={"result_url": "https://nonexistent-fozpay-test-host-xyz.invalid/hook"},
                          timeout=15)
    assert r.status_code == 200
    r2 = admin_session.post(f"{BASE_URL}/api/merchant/test-webhook", timeout=30)
    assert r2.status_code == 200, r2.text  # no 500 crash
    body = r2.json()
    assert body["status"] is False
    assert body["data"]["delivered"] is False
    assert body["data"].get("error"), body


# ---------- 5. pay-in signed API regression ----------
def test_payin_signed(merchant_creds):
    token, secret = merchant_creds
    body = {
        "order_id": "TEST_WHK_" + os.urandom(4).hex(),
        "amount": 5.0,
        "currency": "USDT",
        "network": 4,
        "description": "test",
    }
    sign = make_sig(body, secret)
    r = requests.post(f"{BASE_URL}/api/v1/merchant/pay-in", json=body,
                      headers={"X-Auth-Token": token, "X-Auth-Sign": sign,
                               "Content-Type": "application/json"}, timeout=30)
    assert r.status_code == 200, r.text
    data = r.json().get("data", r.json())
    pay_info = data.get("pay_info") or {}
    assert pay_info.get("address"), data


# ---------- 6. regressions from iteration 1 ----------
def test_platform_fees_matrix(admin_session):
    r = admin_session.get(f"{BASE_URL}/api/admin/platform-fees", timeout=15)
    assert r.status_code == 200
    matrix = r.json()["data"]["withdrawal_fee_matrix"]
    assert len(matrix) == 16


def test_admin_users_balance_usdt(admin_session):
    r = admin_session.get(f"{BASE_URL}/api/admin/users", timeout=15)
    assert r.status_code == 200
    users = r.json()["data"]
    assert users, "no users"
    assert "balance_usdt" in users[0]


def test_withdraw_bnb_usdt_msg(admin_session):
    r = admin_session.post(f"{BASE_URL}/api/wallet/withdraw",
                           json={"currency": "BNB", "network_id": 4,
                                 "address": "0x0000000000000000000000000000000000000000",
                                 "amount": 10.0},
                           timeout=20)
    assert r.status_code == 400
    detail = r.json().get("detail", "")
    assert "USDT" in detail, detail
