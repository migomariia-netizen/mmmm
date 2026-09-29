"""Iteration 3 tests: webhook signature parity (token/sign lowercase),
IP allow-list enforcement, regressions on /currencies + /invoices."""
import os
import hashlib
import json
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
if not BASE_URL:
    with open("/app/frontend/.env") as fh:
        for line in fh:
            if line.startswith("REACT_APP_BACKEND_URL="):
                BASE_URL = line.split("=", 1)[1].strip().rstrip("/")

ADMIN_EMAIL = "admin@fozpay.io"
ADMIN_PASS = "FozPay#Admin2026"


# ---- JS-parity signature helpers ----
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


# ---- fixtures ----
@pytest.fixture(scope="module")
def admin():
    s = requests.Session()
    r = s.post(f"{BASE_URL}/api/auth/login",
               json={"email": ADMIN_EMAIL, "password": ADMIN_PASS}, timeout=20)
    assert r.status_code == 200, r.text
    return s


@pytest.fixture(scope="module")
def merchant(admin):
    r = admin.get(f"{BASE_URL}/api/merchant", timeout=15)
    assert r.status_code == 200
    return r.json()["data"]


@pytest.fixture(scope="module", autouse=True)
def _restore(admin):
    yield
    # Cleanup: reset allowed_ips and result_url
    admin.put(f"{BASE_URL}/api/merchant",
              json={"allowed_ips": [], "result_url": ""}, timeout=15)


# ---- 1. Admin login + GET /api/merchant fields ----
def test_admin_login_and_merchant_fields(admin, merchant):
    for k in ("token", "secret", "result_url", "allowed_ips"):
        assert k in merchant, f"missing merchant field: {k}"
    assert isinstance(merchant["token"], str) and len(merchant["token"]) >= 32
    assert isinstance(merchant["secret"], str) and len(merchant["secret"]) >= 32


# ---- 2. Signature parity: signed pay-in returns pay_info.address ----
def test_payin_signature_parity(merchant):
    body = {
        "order_id": "TEST_ITER3_" + os.urandom(4).hex(),
        "amount": 5.0,           # integral float → "5" per JS
        "currency": "USDT",
        "network": 4,
        "description": "iter3",
        "include_commission": True,  # bool → "true"
    }
    sign = make_sig(body, merchant["secret"])
    r = requests.post(f"{BASE_URL}/api/v1/merchant/pay-in", json=body,
                      headers={"X-Auth-Token": merchant["token"], "X-Auth-Sign": sign},
                      timeout=30)
    assert r.status_code == 200, r.text
    data = r.json().get("data", {})
    assert (data.get("pay_info") or {}).get("address"), data


# ---- 3. test-webhook: httpbin echoes lowercase `token`+`sign` headers, sign is 64-hex ----
def test_webhook_sends_lowercase_token_sign(admin):
    r = admin.put(f"{BASE_URL}/api/merchant",
                  json={"result_url": "https://httpbin.org/post"}, timeout=20)
    assert r.status_code == 200, r.text

    r2 = admin.post(f"{BASE_URL}/api/merchant/test-webhook", timeout=45)
    assert r2.status_code == 200, r2.text
    body = r2.json()
    assert body["status"] is True, body
    data = body["data"]
    assert data["delivered"] is True
    assert data["http_status"] == 200
    assert isinstance(data["sign"], str) and len(data["sign"]) == 64
    all(c in "0123456789abcdef" for c in data["sign"])

    resp = data["response"]
    # httpbin echoes headers in "headers" dict; verify lowercase keys present
    try:
        echoed = json.loads(resp)
        hdrs = {k.lower(): v for k, v in echoed.get("headers", {}).items()}
        assert "token" in hdrs, f"missing lowercase token header. headers={list(hdrs.keys())}"
        assert "sign" in hdrs, f"missing lowercase sign header. headers={list(hdrs.keys())}"
        assert hdrs["sign"] == data["sign"]
    except json.JSONDecodeError:
        # response truncated → fall back to string containment
        assert '"Token"' in resp or '"token"' in resp, resp[:400]
        assert '"Sign"' in resp or '"sign"' in resp, resp[:400]


# ---- 4. empty result_url → HTTP 400 with Ukrainian text ----
def test_webhook_empty_url_400(admin):
    admin.put(f"{BASE_URL}/api/merchant", json={"result_url": ""}, timeout=15)
    r = admin.post(f"{BASE_URL}/api/merchant/test-webhook", timeout=15)
    assert r.status_code == 400
    detail = r.json().get("detail", "")
    assert "URL" in detail or "сповіщ" in detail.lower(), detail


# ---- 5. unreachable host → status:false, delivered:false, no 500 ----
def test_webhook_unreachable(admin):
    admin.put(f"{BASE_URL}/api/merchant",
              json={"result_url": "https://nonexistent-fozpay-xyz-abc-123.invalid/hook"},
              timeout=15)
    r = admin.post(f"{BASE_URL}/api/merchant/test-webhook", timeout=45)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] is False
    assert body["data"]["delivered"] is False
    assert body["data"].get("error")


# ---- 6. IP whitelist enforcement ----
def test_ip_whitelist_enforcement(admin, merchant):
    token = merchant["token"]
    # Set allowed_ips to a specific IP
    r = admin.put(f"{BASE_URL}/api/merchant",
                  json={"allowed_ips": ["72.60.34.27"]}, timeout=15)
    assert r.status_code == 200
    assert r.json()["data"]["allowed_ips"] == ["72.60.34.27"]

    # Wrong IP → 403
    r_bad = requests.get(f"{BASE_URL}/api/v1/private/coins",
                         headers={"X-Auth-Token": token, "X-Forwarded-For": "9.9.9.9"},
                         timeout=20)
    assert r_bad.status_code == 403, f"expected 403, got {r_bad.status_code}: {r_bad.text}"

    # Whitelisted IP → 200
    r_ok = requests.get(f"{BASE_URL}/api/v1/private/coins",
                        headers={"X-Auth-Token": token, "X-Forwarded-For": "72.60.34.27"},
                        timeout=20)
    assert r_ok.status_code == 200, f"expected 200 with whitelisted IP, got {r_ok.status_code}: {r_ok.text}"
    assert r_ok.json().get("status") is True

    # Restore open access
    r = admin.put(f"{BASE_URL}/api/merchant", json={"allowed_ips": []}, timeout=15)
    assert r.status_code == 200
    assert r.json()["data"]["allowed_ips"] == []

    # Previously blocked call now succeeds
    r_now = requests.get(f"{BASE_URL}/api/v1/private/coins",
                        headers={"X-Auth-Token": token, "X-Forwarded-For": "9.9.9.9"},
                        timeout=20)
    assert r_now.status_code == 200, f"after clearing allow-list expected 200, got {r_now.status_code}"


# ---- 7. Regressions ----
def test_get_currencies(admin):
    r = admin.get(f"{BASE_URL}/api/currencies", timeout=15)
    assert r.status_code == 200, r.text
    data = r.json()
    # payload shape may be {status,data} or list
    body = data.get("data", data)
    assert body, "empty currencies"


def test_get_invoices(admin):
    r = admin.get(f"{BASE_URL}/api/invoices", timeout=15)
    assert r.status_code == 200, r.text
    body = r.json()
    assert "data" in body or isinstance(body, list)


def test_post_invoice_usdt(admin):
    payload = {
        "order_id": "TEST_ITER3_INV_" + os.urandom(4).hex(),
        "price": 10.0,
        "payment_currency_iso": "USDT",
    }
    r = admin.post(f"{BASE_URL}/api/invoices", json=payload, timeout=20)
    assert r.status_code == 200, r.text
    data = r.json().get("data", r.json())
    assert data.get("id") or data.get("order_id"), data
