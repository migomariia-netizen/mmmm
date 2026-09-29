"""Tests focused on the NEW features:
- Real on-chain 1inch exchange (rejects non-EVM pairs; checks REAL hot-wallet balance).
- Wallet encryption at rest (system.wallet.mnemonic_enc present, no plaintext mnemonic).
- Hot wallet /api/admin/hot-wallet returns non-empty evm_address (HD index 0).
- Deposit addresses use HD index >= 1.
- Core cabinet endpoints respond without 500.
"""
import os
import re
import uuid
import pytest
import requests
from pathlib import Path
from pymongo import MongoClient


def _backend_url():
    url = os.environ.get("REACT_APP_BACKEND_URL")
    if not url:
        for line in Path("/app/frontend/.env").read_text().splitlines():
            if line.startswith("REACT_APP_BACKEND_URL="):
                url = line.split("=", 1)[1].strip()
    return url.rstrip("/")


BASE_URL = _backend_url()
ADMIN_EMAIL = "admin@fozpay.io"
ADMIN_PASSWORD = "FozPay#Admin2026"


def _load_backend_env():
    env = {}
    for line in Path("/app/backend/.env").read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        env[k.strip()] = v.strip().strip('"').strip("'")
    return env


BE_ENV = _load_backend_env()
MONGO_URL = BE_ENV.get("MONGO_URL", "mongodb://localhost:27017")
DB_NAME = BE_ENV.get("DB_NAME", "test_database")


@pytest.fixture(scope="session")
def mongo():
    return MongoClient(MONGO_URL)[DB_NAME]


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
    api.cookies.clear()
    return {"token": d["access_token"], "user": d["user"],
            "headers": {"Authorization": f"Bearer {d['access_token']}"}}


@pytest.fixture(autouse=True)
def _clear_cookies(api):
    api.cookies.clear()
    yield
    api.cookies.clear()


# ============ 1. Admin login ============
def test_admin_login_returns_admin_role(admin_auth):
    assert admin_auth["user"]["role"] == "admin"
    assert admin_auth["user"]["email"] == ADMIN_EMAIL
    assert admin_auth["token"]


# ============ 2. Public registration disabled ============
def test_register_disabled(api):
    r = api.post(f"{BASE_URL}/api/auth/register",
                 json={"email": f"x_{uuid.uuid4().hex[:6]}@ex.com",
                       "password": "Pass1234!", "name": "X"})
    assert r.status_code == 403, r.text


# ============ 3. Hot wallet has non-empty evm_address ============
def test_hot_wallet_populated(api, admin_auth):
    r = api.get(f"{BASE_URL}/api/admin/hot-wallet", headers=admin_auth["headers"])
    assert r.status_code == 200, r.text
    j = r.json()
    assert j.get("status") is True, j
    d = j.get("data", j)
    evm = d.get("evm_address", "")
    tron = d.get("tron_address", "")
    assert isinstance(evm, str) and re.match(r"^0x[0-9a-fA-F]{40}$", evm), f"bad evm: {evm!r}"
    assert isinstance(tron, str) and tron.startswith("T") and len(tron) >= 30, f"bad tron: {tron!r}"
    assert isinstance(d.get("balances"), list)
    assert "total_usd" in d


# ============ 4. Wallet encryption at rest ============
def test_wallet_encrypted_in_db(mongo):
    doc = mongo.system.find_one({"_id": "wallet"})
    assert doc is not None, "system.wallet doc missing"
    assert "mnemonic_enc" in doc and doc["mnemonic_enc"], "mnemonic_enc absent/empty"
    assert "mnemonic" not in doc, f"plaintext 'mnemonic' field still present: {list(doc.keys())}"
    # Ciphertext must not look like natural-language mnemonic
    enc = doc["mnemonic_enc"]
    # Fernet tokens start with 'gAAAAA'
    assert isinstance(enc, str) and enc.startswith("gAAAAA"), f"not a Fernet token: {enc[:20]}"


# ============ 5. Exchange - non-EVM pair rejected as unavailable on-chain ============
def test_exchange_non_evm_pair_rejected(api, admin_auth, mongo):
    uid = admin_auth["user"].get("user_id") or admin_auth["user"].get("id")
    assert uid, admin_auth["user"]
    # Seed BTC ledger balance so the ledger-balance check passes and we reach the on-chain branch
    mongo.wallets.update_one(
        {"user_id": uid, "iso": "BTC"},
        {"$set": {"balance": 1.0, "balance_available": 1.0}}, upsert=True)
    try:
        r = api.post(f"{BASE_URL}/api/wallet/exchange",
                     json={"from_iso": "BTC", "to_iso": "ETH", "amount": 0.01},
                     headers=admin_auth["headers"])
        assert r.status_code == 400, r.text
        body = r.text
        # Must indicate on-chain not supported for this pair — NOT a simulated success
        assert ("недоступний on-chain" in body) or ("не підтримується" in body.lower()) or ("on-chain" in body.lower()), body
        # And balances must NOT have changed (no simulated debit/credit)
        btc = mongo.wallets.find_one({"user_id": uid, "iso": "BTC"})
        eth = mongo.wallets.find_one({"user_id": uid, "iso": "ETH"})
        assert btc["balance_available"] == 1.0, f"BTC debited by simulated swap: {btc}"
        assert (eth is None) or (eth.get("balance_available", 0) == 0), f"ETH credited by sim: {eth}"
    finally:
        mongo.wallets.delete_one({"user_id": uid, "iso": "BTC"})
        mongo.wallets.delete_one({"user_id": uid, "iso": "ETH"})


# ============ 6. Exchange - supported EVM pair but hot wallet empty → real balance error ============
def test_exchange_evm_pair_hot_wallet_empty(api, admin_auth, mongo):
    uid = admin_auth["user"].get("user_id") or admin_auth["user"].get("id")
    # Seed USDT ledger so we reach the on-chain step
    mongo.wallets.update_one(
        {"user_id": uid, "iso": "USDT"},
        {"$set": {"balance": 100.0, "balance_available": 100.0}}, upsert=True)
    try:
        r = api.post(f"{BASE_URL}/api/wallet/exchange",
                     json={"from_iso": "USDT", "to_iso": "ETH", "amount": 10.0},
                     headers=admin_auth["headers"], timeout=60)
        assert r.status_code == 400, r.text
        # Real balance check message from _swap_exact
        body = r.text
        assert ("Недостатньо USDT на гарячому гаманці" in body) \
               or ("Недостатньо" in body and ("гарячому" in body or "газу" in body)), body
        # Ledger must NOT be debited, ETH must NOT be credited
        usdt = mongo.wallets.find_one({"user_id": uid, "iso": "USDT"})
        eth = mongo.wallets.find_one({"user_id": uid, "iso": "ETH"})
        assert usdt["balance_available"] == 100.0, f"USDT debited on failure: {usdt}"
        assert (eth is None) or (eth.get("balance_available", 0) == 0), f"ETH credited: {eth}"
    finally:
        mongo.wallets.delete_one({"user_id": uid, "iso": "USDT"})
        mongo.wallets.delete_one({"user_id": uid, "iso": "ETH"})


# ============ 7. Exchange - zero ledger balance rejected with ledger message ============
def test_exchange_zero_balance_rejected(api, admin_auth, mongo):
    uid = admin_auth["user"].get("user_id") or admin_auth["user"].get("id")
    # Ensure no balance
    mongo.wallets.delete_one({"user_id": uid, "iso": "USDT"})
    r = api.post(f"{BASE_URL}/api/wallet/exchange",
                 json={"from_iso": "USDT", "to_iso": "ETH", "amount": 1.0},
                 headers=admin_auth["headers"])
    assert r.status_code == 400, r.text
    assert "Недостатньо коштів на балансі" in r.text, r.text


# ============ 8. Deposit address is unique + HD index >= 1 ============
def test_deposit_address_hd_index_ge_1(api, admin_auth, mongo):
    r = api.post(f"{BASE_URL}/api/wallet/deposit-address",
                 json={"currency": "USDT", "network_id": 1},
                 headers=admin_auth["headers"])
    assert r.status_code == 200, r.text
    d = r.json()
    addr_obj = d.get("data", d)
    addr = addr_obj["address"]
    assert re.match(r"^0x[0-9a-fA-F]{40}$", addr), addr
    # Confirm hot wallet address is at index 0 and this deposit is index >= 1
    hw = api.get(f"{BASE_URL}/api/admin/hot-wallet", headers=admin_auth["headers"]).json()
    hot_evm = (hw.get("data") or hw)["evm_address"]
    assert addr.lower() != hot_evm.lower(), "deposit address must not equal hot wallet (index 0)"
    # Cross-check DB: index recorded is >= 1
    dbdoc = mongo.addresses.find_one({"address": addr})
    assert dbdoc is not None
    assert dbdoc.get("index", 0) >= 1, f"HD index should be >=1, got {dbdoc.get('index')}"


def test_deposit_address_tron(api, admin_auth):
    r = api.post(f"{BASE_URL}/api/wallet/deposit-address",
                 json={"currency": "USDT", "network_id": 2},
                 headers=admin_auth["headers"])
    assert r.status_code == 200, r.text
    addr = (r.json().get("data") or r.json())["address"]
    assert addr.startswith("T") and len(addr) >= 30


# ============ 9. Core cabinet endpoints healthy (no 500) ============
def test_auth_me(api, admin_auth):
    r = api.get(f"{BASE_URL}/api/auth/me", headers=admin_auth["headers"])
    assert r.status_code == 200, r.text
    assert r.json()["email"] == ADMIN_EMAIL


def test_wallet_list(api, admin_auth):
    r = api.get(f"{BASE_URL}/api/wallet", headers=admin_auth["headers"])
    assert r.status_code == 200, r.text
    data = (r.json().get("data") or r.json())
    assert isinstance(data, list) and len(data) > 0


def test_public_currency_network_list(api):
    r = api.get(f"{BASE_URL}/api/v1/public/currency-network-list")
    assert r.status_code == 200, r.text
    data = (r.json().get("data") or r.json())
    assert isinstance(data, list) and len(data) > 0
    assert all("networks" in c for c in data)
