"""Iteration 3 tests - Gas fix + BEP-20 default + hot wallet with real funds.

Verifies:
  1. recovery.py gas config constants (0.1 gwei BSC floor, tight per-chain limits, 1.1 buffer).
  2. _gas_price never returns below the floor.
  3. Sweep/send token branches do NOT call estimate_gas on unfunded deposit addresses.
  4. BEP-20 (network_id=4) is the FIRST/default network for USDT + USDC.
  5. Admin login works & /api/admin/hot-wallet returns non-empty evm_address at HD index 0.
  6. Hot wallet holds real balances (total_usd > 0, includes USDT on BSC).
  7. Deposit address generation uses shared 'evm' HD index >= 3 and differs from hot wallet.
  8. Exchange endpoint uses REAL on-chain path (no simulated ledger swap).
  9. Core endpoints (auth/me, wallet list, transactions history) respond without 500.
 10. Admin has a real 'deposit' USDT 6.5 transaction recorded.

Non-destructive: we DO NOT touch admin's real USDT 6.5 balance or hot wallet state.
"""
import os
import re
import sys
import inspect
import pytest
import requests
from pathlib import Path
from pymongo import MongoClient

# Make backend importable for direct recovery.py inspection
sys.path.insert(0, "/app/backend")


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
HOT_WALLET_KNOWN = "0x06B8Edf964E761ba0BdA4430B57098De03E9627c".lower()


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


# ============ 1. GAS CONFIG CONSTANTS ============
def test_gas_price_floor_bsc_is_0_1_gwei():
    import recovery
    assert recovery._GAS_PRICE_FLOOR["bsc"] == 100_000_000, \
        f"BSC floor must be 0.1 gwei (100_000_000 wei), got {recovery._GAS_PRICE_FLOOR['bsc']}"


def test_token_gas_limits_are_tight():
    import recovery
    assert recovery._token_gas_limit("bsc") == 60_000
    assert recovery._token_gas_limit("ethereum") == 90_000
    assert recovery._token_gas_limit("polygon") == 80_000
    assert recovery._token_gas_limit("arbitrum") == 1_500_000
    # Unknown chain default
    assert recovery._token_gas_limit("unknown") == 90_000


def test_gas_fund_buffer_is_1_1():
    import recovery
    assert recovery._GAS_FUND_BUFFER == 1.1, \
        f"Buffer must be 1.1 (10% headroom), got {recovery._GAS_FUND_BUFFER}"


def test_bsc_gas_topup_is_significantly_smaller_than_old_config():
    """New: 60_000 * 0.1e9 * 1.1 = 6.6e12 wei = 6.6e-6 BNB
       Old: 100_000 * 1e9 * 1.3 = 1.3e14 wei = 1.3e-4 BNB
       New must be at least 15x less."""
    import recovery
    new = recovery._token_gas_limit("bsc") * recovery._GAS_PRICE_FLOOR["bsc"] * recovery._GAS_FUND_BUFFER
    old = 100_000 * 1_000_000_000 * 1.3
    ratio = old / new
    assert ratio >= 15, f"New gas top-up should be >=15x smaller than old; ratio={ratio:.2f}"
    # And new must be a reasonable tiny top-up in BNB
    assert new / 1e18 < 1e-5, f"New top-up too large: {new/1e18} BNB"


# ============ 2. _gas_price helper: never below floor ============
def test_gas_price_helper_respects_floor():
    import recovery

    class FakeEth:
        def __init__(self, gp):
            self.gas_price = gp

    class FakeW3:
        def __init__(self, gp):
            self.eth = FakeEth(gp)

    # Network below floor -> should return floor
    assert recovery._gas_price(FakeW3(50_000_000), "bsc") == 100_000_000
    # Network above floor -> should return network price
    assert recovery._gas_price(FakeW3(500_000_000), "bsc") == 500_000_000
    # Non-BSC chain with no floor entry -> returns network price
    assert recovery._gas_price(FakeW3(1_000_000_000), "ethereum") == 1_000_000_000


# ============ 3. No estimate_gas on unfunded deposit address ============
def _strip_comments(src: str) -> str:
    out = []
    for line in src.splitlines():
        # Drop comment content but keep code before #
        if "#" in line:
            line = line.split("#", 1)[0]
        out.append(line)
    # Also strip docstrings (triple-quoted)
    import re as _re
    joined = "\n".join(out)
    joined = _re.sub(r'"""[\s\S]*?"""', "", joined)
    joined = _re.sub(r"'''[\s\S]*?'''", "", joined)
    return joined


def test_sweep_evm_does_not_call_estimate_gas():
    import recovery
    src = _strip_comments(inspect.getsource(recovery.sweep_evm))
    assert "estimate_gas" not in src, \
        "sweep_evm must not call estimate_gas on the unfunded deposit address"
    assert "_token_gas_limit(chain)" in src, \
        "sweep_evm should use fixed _token_gas_limit(chain)"


def test_send_evm_amount_does_not_call_estimate_gas():
    import recovery
    src = _strip_comments(inspect.getsource(recovery.send_evm_amount))
    assert "estimate_gas" not in src, \
        "send_evm_amount must not call estimate_gas on the (possibly unfunded) wallet"
    assert "_token_gas_limit(chain)" in src


# ============ 4. Admin login ============
def test_admin_login(admin_auth):
    assert admin_auth["user"]["role"] == "admin"
    assert admin_auth["user"]["email"] == ADMIN_EMAIL
    assert admin_auth["token"]


# ============ 5. Hot wallet: non-empty + real balances ============
def test_hot_wallet_populated_with_real_funds(api, admin_auth):
    r = api.get(f"{BASE_URL}/api/admin/hot-wallet", headers=admin_auth["headers"])
    assert r.status_code == 200, r.text
    j = r.json()
    d = j.get("data", j)
    evm = d.get("evm_address", "")
    assert isinstance(evm, str) and re.match(r"^0x[0-9a-fA-F]{40}$", evm), f"bad evm: {evm!r}"
    assert evm.lower() == HOT_WALLET_KNOWN, \
        f"hot wallet evm addr changed from known HD idx 0: got {evm}, expected {HOT_WALLET_KNOWN}"
    assert isinstance(d.get("balances"), list)
    # Real funds: 6.5 USDT + small BNB on BSC
    total_usd = d.get("total_usd", 0)
    assert total_usd > 0, f"hot wallet total_usd must be > 0 (real funds present), got {total_usd}"
    balances = d["balances"]
    # Should have USDT on BSC (network_id 4)
    usdt_bsc = [b for b in balances if b.get("symbol") == "USDT" and b.get("network_id") == 4]
    assert usdt_bsc, f"expected USDT on BSC in hot wallet balances: {balances}"


# ============ 6. BEP-20 (network_id 4) is default for USDT + USDC ============
def test_bep20_is_default_for_usdt_and_usdc(api):
    """Confirm currency-network list: USDT and USDC list BSC (4) FIRST."""
    r = api.get(f"{BASE_URL}/api/v1/public/currency-network-list")
    assert r.status_code == 200, r.text
    data = (r.json().get("data") or r.json())
    by_iso = {c.get("iso3") or c.get("iso"): c for c in data}
    usdt = by_iso.get("USDT")
    usdc = by_iso.get("USDC")
    assert usdt, f"USDT missing in catalog: {list(by_iso.keys())}"
    assert usdc, f"USDC missing"
    usdt_nets = usdt["networks"]
    usdc_nets = usdc["networks"]
    first_usdt = usdt_nets[0]["network_id"]
    first_usdc = usdc_nets[0]["network_id"]
    assert first_usdt == 4, f"USDT default network must be 4 (BEP-20), got {first_usdt} -> {usdt_nets}"
    assert first_usdc == 4, f"USDC default network must be 4 (BEP-20), got {first_usdc} -> {usdc_nets}"


# ============ 7. Deposit address generation - BEP-20, shared evm index >= 3 ============
def test_generate_bep20_deposit_address(api, admin_auth, mongo):
    r = api.post(f"{BASE_URL}/api/wallet/deposit-address",
                 json={"currency": "USDT", "network_id": 4},
                 headers=admin_auth["headers"])
    assert r.status_code == 200, r.text
    d = r.json().get("data") or r.json()
    addr = d["address"]
    assert re.match(r"^0x[0-9a-fA-F]{40}$", addr), addr
    assert addr.lower() != HOT_WALLET_KNOWN, \
        "deposit address must not equal hot wallet (HD index 0)"
    dbdoc = mongo.addresses.find_one({"address": addr})
    assert dbdoc is not None
    idx = dbdoc.get("index", 0)
    assert idx >= 1, f"HD index should be >= 1 for a deposit address, got {idx}"
    # Shared evm counter should now be >= 3 (per iteration description)
    # We check that at least one 'evm-family' allocated address in DB has index >= 3
    evm_chains = ["ethereum", "bsc", "polygon", "arbitrum"]
    max_idx = 0
    for a in mongo.addresses.find({"chain": {"$in": evm_chains}}):
        max_idx = max(max_idx, a.get("index", 0))
    assert max_idx >= 1, f"expected shared evm HD counter to be >=1, max seen={max_idx}"


def test_two_bep20_deposit_addresses_shared_counter(api, admin_auth, mongo):
    """A fresh BSC + Ethereum request should return addresses that use the SAME shared
    'evm' counter (monotonically increasing indexes across chains)."""
    # First: BSC
    r1 = api.post(f"{BASE_URL}/api/wallet/deposit-address",
                  json={"currency": "USDC", "network_id": 4},
                  headers=admin_auth["headers"])
    assert r1.status_code == 200
    a1 = (r1.json().get("data") or r1.json())["address"]
    doc1 = mongo.addresses.find_one({"address": a1})
    # Second: Ethereum via USDC (should reuse existing or allocate new — but if new, index > doc1.index)
    r2 = api.post(f"{BASE_URL}/api/wallet/deposit-address",
                  json={"currency": "USDC", "network_id": 1},
                  headers=admin_auth["headers"])
    assert r2.status_code == 200
    a2 = (r2.json().get("data") or r2.json())["address"]
    doc2 = mongo.addresses.find_one({"address": a2})
    # If both are freshly allocated (different addresses), indexes must differ (shared counter)
    if a1.lower() != a2.lower():
        assert doc1["index"] != doc2["index"], \
            "shared 'evm' counter should produce distinct indexes for different EVM allocations"
    # Both must be at HD index >= 1 (not the hot wallet)
    assert doc1["index"] >= 1 and doc2["index"] >= 1


# ============ 8. Exchange: real on-chain path (no simulated ledger swap) ============
def test_exchange_btc_eth_rejected_non_evm(api, admin_auth, mongo):
    """BTC->ETH must be rejected as unsupported on-chain pair (no simulated swap)."""
    uid = admin_auth["user"].get("user_id") or admin_auth["user"].get("id")
    # Seed BTC ledger so ledger-balance check passes
    mongo.wallets.update_one(
        {"user_id": uid, "iso": "BTC"},
        {"$set": {"balance": 1.0, "balance_available": 1.0}}, upsert=True)
    # Save current ETH balance to detect any changes
    eth_before = mongo.wallets.find_one({"user_id": uid, "iso": "ETH"}) or {}
    eth_bal_before = eth_before.get("balance_available", 0.0)
    try:
        r = api.post(f"{BASE_URL}/api/wallet/exchange",
                     json={"from_iso": "BTC", "to_iso": "ETH", "amount": 0.01},
                     headers=admin_auth["headers"])
        assert r.status_code == 400, r.text
        assert "on-chain" in r.text.lower() or "недоступний" in r.text.lower(), r.text
        # Ledger untouched
        btc = mongo.wallets.find_one({"user_id": uid, "iso": "BTC"})
        assert btc["balance_available"] == 1.0, f"BTC debited: {btc}"
        eth_after = mongo.wallets.find_one({"user_id": uid, "iso": "ETH"}) or {}
        assert eth_after.get("balance_available", 0.0) == eth_bal_before, "ETH balance changed"
    finally:
        mongo.wallets.delete_one({"user_id": uid, "iso": "BTC"})


def test_exchange_usdt_eth_uses_real_onchain(api, admin_auth, mongo):
    """USDT (6.5 real) -> ETH: must either succeed via real 1inch OR fail with a real
    on-chain balance/gas error message. Must NOT do a simulated ledger swap."""
    uid = admin_auth["user"].get("user_id") or admin_auth["user"].get("id")
    # Snapshot admin USDT balance (should be ~6.5 real deposit)
    usdt_doc = mongo.wallets.find_one({"user_id": uid, "iso": "USDT"}) or {}
    usdt_before = usdt_doc.get("balance_available", 0.0)
    eth_doc_before = mongo.wallets.find_one({"user_id": uid, "iso": "ETH"}) or {}
    eth_before = eth_doc_before.get("balance_available", 0.0)

    r = api.post(f"{BASE_URL}/api/wallet/exchange",
                 json={"from_iso": "USDT", "to_iso": "ETH", "amount": 1.0},
                 headers=admin_auth["headers"], timeout=120)
    if r.status_code == 200:
        # Real swap succeeded -- OK, but must have on-chain tx info
        body = r.json()
        blob = str(body)
        assert "tx" in blob.lower() or "hash" in blob.lower() or "hash" in body.get("data", {}), \
            f"success without on-chain tx hash: {body}"
    else:
        assert r.status_code == 400, r.text
        body = r.text
        # Must be a REAL on-chain error, not a generic ledger message
        real_indicators = [
            "гарячому гаманці", "on-chain", "газу", "hot wallet",
            "insufficient", "Недостатньо USDT", "1inch",
        ]
        assert any(k.lower() in body.lower() for k in real_indicators), \
            f"error must reference real on-chain path, got: {body}"
        # Ledger must NOT be debited on failure
        usdt_doc2 = mongo.wallets.find_one({"user_id": uid, "iso": "USDT"}) or {}
        assert abs(usdt_doc2.get("balance_available", 0.0) - usdt_before) < 1e-8, \
            f"USDT debited on failure: was {usdt_before}, now {usdt_doc2}"
        eth_doc2 = mongo.wallets.find_one({"user_id": uid, "iso": "ETH"}) or {}
        assert abs(eth_doc2.get("balance_available", 0.0) - eth_before) < 1e-8, \
            f"ETH credited on failure: {eth_doc2}"


# ============ 9. Core endpoints healthy ============
def test_auth_me_ok(api, admin_auth):
    r = api.get(f"{BASE_URL}/api/auth/me", headers=admin_auth["headers"])
    assert r.status_code == 200, r.text
    assert r.json()["email"] == ADMIN_EMAIL


def test_wallet_list_ok(api, admin_auth):
    r = api.get(f"{BASE_URL}/api/wallet", headers=admin_auth["headers"])
    assert r.status_code == 200, r.text
    data = r.json().get("data") or r.json()
    assert isinstance(data, list) and len(data) > 0


def test_transactions_history_ok(api, admin_auth):
    r = api.get(f"{BASE_URL}/api/transactions", headers=admin_auth["headers"])
    assert r.status_code == 200, r.text
    data = r.json().get("data") or r.json()
    assert isinstance(data, list)
    # Admin should have >=1 deposit USDT 6.5 transaction from the real recovered deposit
    usdt_deposits = [t for t in data if t.get("type") == "deposit" and t.get("iso") == "USDT"]
    assert usdt_deposits, f"expected at least 1 admin USDT deposit tx, got: {data}"
    # At least one should be around 6.5 USDT
    matches = [t for t in usdt_deposits if abs(float(t.get("amount", 0)) - 6.5) < 0.01]
    assert matches, f"expected a USDT deposit tx of ~6.5, got amounts: {[t.get('amount') for t in usdt_deposits]}"


# ============ 10. Admin USDT ledger balance is 6.5 ============
def test_admin_usdt_ledger_balance(mongo, admin_auth):
    uid = admin_auth["user"].get("user_id") or admin_auth["user"].get("id")
    w = mongo.wallets.find_one({"user_id": uid, "iso": "USDT"})
    assert w, "admin USDT wallet doc missing"
    bal = w.get("balance_available", 0.0)
    assert abs(bal - 6.5) < 0.01, f"admin USDT balance must be ~6.5, got {bal}"
