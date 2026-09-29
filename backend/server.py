import os
import asyncio
import logging
import random
import string
import time
from datetime import datetime, timezone, timedelta
from typing import Optional

import httpx
from fastapi import FastAPI, APIRouter, HTTPException, Request, Response, Body
from pydantic import BaseModel
from starlette.middleware.cors import CORSMiddleware

from core import (
    db, hash_password, verify_password, create_access_token, set_auth_cookie,
    set_session_cookie, clear_auth_cookies, get_current_user, exchange_emergent_session,
    make_signature, new_token, new_secret,
)
import catalog
from catalog import (
    CURRENCIES, NETWORKS, FIAT_CURRENCIES, FIAT_RATES_USD, PRICES_USD, PRICE_CHANGE,
    STATUS_MAP, STATUS_NAME_TO_ID, networks_for, commission_for,
)
from hd_wallet import generate_mnemonic, seed_from_mnemonic, derive_address
from wallet_crypto import encrypt_mnemonic, decrypt_mnemonic
from admin_router import (
    admin_router, sec_router,
    get_platform_settings, add_to_pool, is_network_enabled, check_user_2fa,
    deposit_fee_for, swap_fee_percent_for, withdrawal_fee_for,
)
import aml as aml_mod
import binance_prices
import uuid

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("fozpay")

app = FastAPI(title="FozPay API")
_seed = {"bytes": None}


# ============================ helpers ============================
def now_ts() -> int:
    return int(time.time())


def gen_id(n=8) -> str:
    return "".join(random.choices(string.ascii_uppercase + string.digits, k=n))


async def next_index(chain: str) -> int:
    doc = await db.counters.find_one_and_update(
        {"_id": chain}, {"$inc": {"seq": 1}}, upsert=True, return_document=True)
    return doc["seq"]


async def ensure_seed():
    if _seed["bytes"] is not None:
        return
    env_m = os.environ.get("WALLET_MNEMONIC", "").strip()
    if env_m:
        mnemonic = env_m
    else:
        sysdoc = await db.system.find_one({"_id": "wallet"})
        if sysdoc and sysdoc.get("mnemonic_enc"):
            # Основний шлях: зашифрований мнемонік у БД
            mnemonic = decrypt_mnemonic(sysdoc["mnemonic_enc"])
        elif sysdoc and sysdoc.get("mnemonic"):
            # Міграція legacy: був відкритий мнемонік → шифруємо й прибираємо plaintext
            mnemonic = sysdoc["mnemonic"]
            await db.system.update_one(
                {"_id": "wallet"},
                {"$set": {"mnemonic_enc": encrypt_mnemonic(mnemonic)},
                 "$unset": {"mnemonic": ""}})
            logger.warning("Migrated plaintext mnemonic in DB to encrypted (mnemonic_enc).")
        else:
            mnemonic = generate_mnemonic()
            await db.system.update_one(
                {"_id": "wallet"},
                {"$set": {"mnemonic_enc": encrypt_mnemonic(mnemonic)}}, upsert=True)
            logger.warning("Generated new HD wallet mnemonic (encrypted in DB).")
    _seed["bytes"] = seed_from_mnemonic(mnemonic)
    # Hot wallet = HD EVM address at index 0 (per-user deposit addresses start at
    # index 1, see next_index). Its private key is derivable from the encrypted
    # seed, so the platform can auto-fund gas and sweep deposits to it on every EVM
    # network without any hardcoded/plaintext treasury key. Respects an explicit
    # TREASURY_EVM override from the environment if one is provided.
    import recovery as _rec
    if not os.environ.get("TREASURY_EVM"):
        hot_evm = derive_address(_seed["bytes"], "ethereum", 0)["address"]
        _rec.TREASURY_EVM = hot_evm
        logger.info(f"Hot wallet EVM address (HD index 0): {hot_evm}")


async def allocate_address(user_id: str, iso: str, network_id: int, invoice_id=None) -> dict:
    await ensure_seed()
    net = NETWORKS.get(network_id)
    if not net:
        raise HTTPException(400, "Network not found")
    chain = net["chain"]
    if invoice_id is None:
        existing = await db.addresses.find_one(
            {"user_id": user_id, "iso": iso, "network_id": network_id, "invoice_id": None},
            {"_id": 0})
        if existing:
            return existing
    idx = await next_index("evm" if chain in ("ethereum", "bsc", "polygon", "arbitrum") else chain)
    d = derive_address(_seed["bytes"], chain, idx)
    doc = {"user_id": user_id, "iso": iso, "network_id": network_id, "chain": chain,
           "index": idx, "address": d["address"], "path": d["path"],
           "invoice_id": invoice_id, "time_create": now_ts()}
    await db.addresses.insert_one(dict(doc))
    doc.pop("_id", None)
    return doc


async def credit_balance(user_id: str, iso: str, amount: float, available: bool = True):
    inc = {"balance": amount}
    if available:
        inc["balance_available"] = amount
    await db.wallets.update_one(
        {"user_id": user_id, "iso": iso}, {"$inc": inc}, upsert=True)


async def get_balance(user_id: str, iso: str) -> dict:
    w = await db.wallets.find_one({"user_id": user_id, "iso": iso}, {"_id": 0})
    if not w:
        return {"iso": iso, "balance": 0.0, "balance_available": 0.0}
    return {"iso": iso, "balance": round(w.get("balance", 0.0), 8),
            "balance_available": round(w.get("balance_available", 0.0), 8)}


async def add_transaction(user_id: str, ttype: str, iso: str, network_id, amount,
                          status="Done", address=None, txid=None, description="",
                          order_id=None, invoice_id=None, usd=None,
                          fee=0.0, fee_iso=None, gross_amount=None, source="cabinet"):
    tx = {
        "tx_id": uuid.uuid4().hex[:12], "user_id": user_id, "type": ttype, "iso": iso,
        "network_id": network_id, "amount": round(float(amount), 8),
        "gross_amount": round(float(gross_amount if gross_amount is not None else amount), 8),
        "fee": round(float(fee or 0.0), 8),
        "fee_iso": fee_iso or iso,
        "source": source,
        "usd_value": usd if usd is not None else catalog.usd_value(iso, amount),
        "status": status, "address": address, "txid": txid,
        "explorer_url": catalog.explorer_tx_url(network_id, txid), "description": description,
        "order_id": order_id, "invoice_id": invoice_id, "created_ts": now_ts(),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    await db.transactions.insert_one(dict(tx))
    tx.pop("_id", None)
    return tx


async def get_merchant(user_id: str) -> dict:
    m = await db.merchants.find_one({"user_id": user_id}, {"_id": 0})
    if not m:
        m = {
            "merchant_id": int(now_ts()), "user_id": user_id, "name": "My Merchant",
            "home_url": "", "result_url": "", "token": new_token(), "secret": new_secret(),
            "brand_color": "#2563EB", "logo_url": "", "description": "", "is_default": True,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        await db.merchants.insert_one(dict(m))
        m.pop("_id", None)
    return m


def resolve_fee(merchant: dict, iso: str, direction: str) -> dict:
    """Merchant-configured earning fee for 'in' (deposits/invoices) or 'out' (withdrawals)."""
    fees = (merchant or {}).get("fees") or {}
    row = fees.get(iso) or fees.get("default") or {}
    if direction == "in":
        return {"percent": float(row.get("in_percent") or 0), "fixed": float(row.get("in_fixed") or 0)}
    return {"percent": float(row.get("out_percent") or 0), "fixed": float(row.get("out_fixed") or 0)}


def invoice_public(inv: dict) -> dict:
    return {k: inv.get(k) for k in [
        "id", "order_id", "status", "status_id", "price", "payment_currency_iso",
        "include_commission", "description", "link", "currencies", "redirect_url",
        "time_create", "time_expired", "pay_info", "amount_paid", "usd_value"]}


async def send_webhook(merchant: dict, inv: dict, cur_iso=None, amount=0.0):
    url = merchant.get("result_url")
    if not url:
        logger.info(f"webhook skip inv={inv.get('id')}: merchant has NO result_url configured")
        return
    rate = PRICES_USD.get(cur_iso, 0.0) if cur_iso else 0.0
    payload = {
        "id": inv["id"], "order_id": inv["order_id"], "currency": cur_iso or "",
        "payment_currency": inv["payment_currency_iso"], "status": inv["status"],
        "amount": amount, "amount_send": amount, "price": inv["price"],
        "price_send": round(amount * rate, 2), "rate": rate,
        "total_sum_price": round(amount * rate, 2), "commission": 0,
        "address": (inv.get("pay_info") or {}).get("address", ""),
        "network_type": (inv.get("pay_info") or {}).get("network", ""),
        "time_create": inv["time_create"], "time_update": now_ts(),
        "time_done": now_ts() if inv["status"] in ("Paid", "Completed", "Overpayment") else None,
        "time_expired": inv.get("time_expired"), "time_send": now_ts(),
        "time_receive": None, "include_commission": inv.get("include_commission", 0),
    }
    # Sign the webhook exactly like the merchant API signs requests, so ewex-style
    # receivers that verify X-Auth-Sign / X-Auth-Token accept the callback.
    try:
        sign = make_signature(payload, merchant.get("secret", ""))
    except Exception:
        sign = ""
    headers = {
        "Content-Type": "application/json",
        "X-Auth-Token": merchant.get("token", ""),
        "X-Auth-Sign": sign,
        "User-Agent": "FozPay-Webhook/1.0",
    }
    last_err = None
    for attempt in range(1, 4):
        try:
            async with httpx.AsyncClient(timeout=15, follow_redirects=True) as c:
                r = await c.post(url, json=payload, headers=headers)
            logger.info(f"webhook sent inv={inv.get('id')} url={url} attempt={attempt} "
                        f"status={r.status_code} resp={r.text[:200]}")
            await db.invoices.update_one({"id": inv.get("id")}, {"$set": {
                "webhook_status": r.status_code, "webhook_sent_ts": now_ts(),
                "webhook_response": r.text[:500], "webhook_url": url}})
            if 200 <= r.status_code < 300:
                return
            last_err = f"HTTP {r.status_code}: {r.text[:120]}"
        except Exception as e:
            last_err = str(e)
            logger.info(f"webhook attempt {attempt} failed inv={inv.get('id')} url={url}: {e}")
        await asyncio.sleep(2 * attempt)
    await db.invoices.update_one({"id": inv.get("id")}, {"$set": {
        "webhook_status": "failed", "webhook_error": str(last_err),
        "webhook_sent_ts": now_ts(), "webhook_url": url}})
    logger.warning(f"webhook FAILED after 3 attempts inv={inv.get('id')} url={url}: {last_err}")


# ============================ auth router ============================
auth_router = APIRouter(prefix="/api/auth")


class RegisterIn(BaseModel):
    email: str
    password: str
    name: str = ""


class LoginIn(BaseModel):
    email: str
    password: str
    otp: Optional[str] = None


@auth_router.post("/register")
async def register(payload: RegisterIn, response: Response):
    # Публічна реєстрація вимкнена. Нових користувачів створює лише адміністратор
    # у своєму кабінеті (розділ Налаштування → Користувачі).
    raise HTTPException(403, "Реєстрація вимкнена. Зверніться до адміністратора FozPay для створення акаунта.")


@auth_router.post("/login")
async def login(payload: LoginIn, response: Response):
    email = payload.email.lower().strip()
    user = await db.users.find_one({"email": email})
    if not user or not user.get("password_hash") or not verify_password(payload.password, user["password_hash"]):
        raise HTTPException(401, "Невірний email або пароль")
    tf = user.get("two_fa") or {}
    if tf.get("enabled"):
        if not payload.otp:
            raise HTTPException(401, {"error": "2FA_REQUIRED", "message": "Потрібен код Google Authenticator"})
        import pyotp
        if not pyotp.TOTP(tf.get("secret", "")).verify(str(payload.otp).replace(" ", ""), valid_window=1):
            raise HTTPException(401, {"error": "2FA_INVALID", "message": "Невірний код 2FA"})
    token = create_access_token(user["user_id"], email)
    set_auth_cookie(response, token)
    user.pop("password_hash", None)
    user.pop("_id", None)
    return {"user": user, "access_token": token}


class SessionIn(BaseModel):
    session_id: str


@auth_router.post("/google/session")
async def google_session(payload: SessionIn, response: Response):
    data = await exchange_emergent_session(payload.session_id)
    email = data["email"].lower().strip()
    user = await db.users.find_one({"email": email}, {"_id": 0})
    if not user:
        user_id = f"user_{uuid.uuid4().hex[:12]}"
        user = {"user_id": user_id, "email": email, "name": data.get("name", ""),
                "picture": data.get("picture", ""), "auth_provider": "google",
                "created_at": datetime.now(timezone.utc).isoformat()}
        await db.users.insert_one(dict(user))
        await get_merchant(user_id)
    else:
        user_id = user["user_id"]
    stoken = data["session_token"]
    await db.user_sessions.update_one(
        {"session_token": stoken},
        {"$set": {"user_id": user_id, "session_token": stoken,
                  "expires_at": (datetime.now(timezone.utc) + timedelta(days=7)).isoformat(),
                  "created_at": datetime.now(timezone.utc).isoformat()}}, upsert=True)
    set_session_cookie(response, stoken)
    user.pop("password_hash", None)
    return {"user": user}


@auth_router.get("/me")
async def me(request: Request):
    return await get_current_user(request)


@auth_router.post("/logout")
async def logout(response: Response):
    clear_auth_cookies(response)
    return {"status": "ok"}


# ============================ cabinet router ============================
cab = APIRouter(prefix="/api")


@cab.get("/prices")
async def prices():
    return {"status": True, "data": [
        {"iso": iso, "name": CURRENCIES[iso]["name"], "color": CURRENCIES[iso]["color"],
         "price": PRICES_USD[iso], "change": PRICE_CHANGE.get(iso, 0.0)}
        for iso in CURRENCIES]}


@cab.get("/me/summary")
async def summary(request: Request):
    user = await get_current_user(request)
    uid = user["user_id"]
    wallets = await db.wallets.find({"user_id": uid}, {"_id": 0}).to_list(100)
    assets, total, available = [], 0.0, 0.0
    for iso in CURRENCIES:
        w = next((x for x in wallets if x["iso"] == iso), None)
        bal = w.get("balance", 0.0) if w else 0.0
        avail = w.get("balance_available", 0.0) if w else 0.0
        usd = catalog.usd_value(iso, bal)
        total += usd
        available += catalog.usd_value(iso, avail)
        assets.append({"iso": iso, "name": CURRENCIES[iso]["name"], "color": CURRENCIES[iso]["color"],
                       "balance": round(bal, 8), "balance_available": round(avail, 8),
                       "price": PRICES_USD[iso], "usd_value": usd})
    txs = await db.transactions.find({"user_id": uid}, {"_id": 0}).sort("created_ts", -1).to_list(10)
    # 30-day balance chart derived from REAL deposit/withdraw history
    all_tx = await db.transactions.find(
        {"user_id": uid, "type": {"$in": ["deposit", "withdraw"]}}, {"_id": 0}
    ).sort("created_ts", 1).to_list(2000)
    now = datetime.now(timezone.utc)
    day_delta = {}
    for tx in all_tx:
        d = datetime.fromtimestamp(tx.get("created_ts", 0), tz=timezone.utc).date()
        sign = -1 if tx["type"] == "withdraw" else 1
        day_delta[d] = day_delta.get(d, 0.0) + sign * float(tx.get("usd_value", 0.0))
    start_date = (now - timedelta(days=29)).date()
    running = sum(v for d, v in day_delta.items() if d < start_date)
    chart = []
    for i in range(29, -1, -1):
        d = (now - timedelta(days=i)).date()
        running += day_delta.get(d, 0.0)
        chart.append({"t": d.strftime("%d.%m"), "value": round(max(running, 0.0), 2)})
    return {"status": True, "total_usd": round(total, 2), "available_usd": round(available, 2),
            "assets": assets, "recent": txs, "chart": chart}


@cab.get("/transactions")
async def transactions(request: Request):
    user = await get_current_user(request)
    txs = await db.transactions.find({"user_id": user["user_id"]}, {"_id": 0}).sort("created_ts", -1).to_list(200)
    return {"status": True, "data": txs}


@cab.get("/wallet")
async def wallet(request: Request):
    user = await get_current_user(request)
    uid = user["user_id"]
    out = []
    for iso, cur in CURRENCIES.items():
        b = await get_balance(uid, iso)
        out.append({"iso": iso, "name": cur["name"], "color": cur["color"],
                    "price": PRICES_USD[iso], "balance": b["balance"],
                    "balance_available": b["balance_available"],
                    "usd_value": catalog.usd_value(iso, b["balance"]),
                    "networks": networks_for(iso)})
    return {"status": True, "data": out}


class DepositAddrIn(BaseModel):
    currency: str
    network_id: int


@cab.post("/wallet/deposit-address")
async def deposit_address(request: Request, payload: DepositAddrIn):
    user = await get_current_user(request)
    iso = payload.currency.upper()
    if iso not in CURRENCIES or payload.network_id not in CURRENCIES[iso]["networks"]:
        raise HTTPException(400, "Currency/network not available")
    if not await is_network_enabled(payload.network_id):
        net_name = NETWORKS.get(payload.network_id, {}).get("name", str(payload.network_id))
        raise HTTPException(400, f"Мережа {net_name} тимчасово вимкнена суперадміністратором")
    addr = await allocate_address(user["user_id"], iso, payload.network_id)
    net = NETWORKS[payload.network_id]
    plat = await get_platform_settings()
    return {"status": True, "data": {"address": addr["address"], "currency": iso,
            "network_id": payload.network_id, "network": net["name"], "network_iso": net["iso"],
            "platform_deposit_fee": deposit_fee_for(plat, iso)}}


class WithdrawIn(BaseModel):
    currency: str
    network_id: int
    amount: float
    address: str
    otp: Optional[str] = None
    source: Optional[str] = "cabinet"   # "cabinet" or "api"


@cab.post("/wallet/withdraw")
async def withdraw(request: Request, payload: WithdrawIn):
    user = await get_current_user(request)
    uid = user["user_id"]
    iso = payload.currency.upper()
    if iso not in CURRENCIES:
        raise HTTPException(400, "Currency not available")
    if not await is_network_enabled(payload.network_id):
        net_name = NETWORKS.get(payload.network_id, {}).get("name", str(payload.network_id))
        raise HTTPException(400, f"Мережа {net_name} тимчасово вимкнена суперадміністратором")
    # 2FA gate for withdrawal
    if not await check_user_2fa(user, payload.otp):
        raise HTTPException(401, {"error": "2FA_REQUIRED",
                                  "message": "Потрібен код Google Authenticator для підтвердження виведення"})
    bal = await get_balance(uid, iso)
    merchant = await get_merchant(uid)
    ofee = resolve_fee(merchant, iso, "out")
    merchant_fee = payload.amount * ofee["percent"] / 100 + ofee["fixed"]
    # Platform-level withdrawal fee (per currency+network, falls back to global)
    plat = await get_platform_settings()
    src = "api" if (payload.source or "").lower() == "api" else "cabinet"
    platform_fee = float(withdrawal_fee_for(plat, iso, payload.network_id, src))
    total_fee = round(merchant_fee + platform_fee, 8)
    total = round(payload.amount + total_fee, 8)
    if payload.amount <= 0:
        raise HTTPException(400, "Invalid amount")

    convert_from = None
    convert_amount = 0.0
    if total <= bal["balance_available"]:
        # Enough of the requested currency — normal path.
        await credit_balance(uid, iso, -total)
        await add_to_pool(iso, platform_fee, network_id=payload.network_id)
    else:
        # AUTO-CONVERT FROM USDT: the user asked to withdraw a currency they don't
        # hold enough of (e.g. BNB), but has USDT. We debit the USDT equivalent and
        # the payout worker performs a REAL on-chain 1inch swap (USDT→iso) on the
        # hot wallet, then sends the requested currency to the address.
        chain = NETWORKS.get(payload.network_id, {}).get("chain")
        if iso == "USDT" or chain not in ("ethereum", "bsc", "polygon", "arbitrum"):
            raise HTTPException(400, "Недостатньо коштів на балансі (з урахуванням комісії)")
        price_iso = PRICES_USD.get(iso, 0.0)
        price_usdt = PRICES_USD.get("USDT", 1.0) or 1.0
        if price_iso <= 0:
            raise HTTPException(400, "Недостатньо коштів і немає курсу для конвертації")
        # USDT to source `amount` of iso (+2% buffer for swap slippage/gas) + fee in USDT
        usdt_for_amount = round(payload.amount * price_iso / price_usdt * 1.02, 8)
        usdt_fee = round(platform_fee * price_iso / price_usdt, 8)
        usdt_needed = round(usdt_for_amount + usdt_fee, 8)
        usdt_bal = await get_balance(uid, "USDT")
        if usdt_needed > usdt_bal["balance_available"]:
            raise HTTPException(400,
                f"Недостатньо {iso}. Для авто-конвертації потрібно ~{usdt_needed} USDT, "
                f"доступно {usdt_bal['balance_available']} USDT")
        await credit_balance(uid, "USDT", -usdt_needed)
        await add_to_pool("USDT", usdt_fee, network_id=payload.network_id)
        convert_from = "USDT"
        convert_amount = usdt_for_amount

    tx = await add_transaction(uid, "withdraw", iso, payload.network_id, payload.amount,
                               status="Pending", address=payload.address,
                               description=(f"Withdraw {iso} — авто-конвертація з {convert_amount} USDT"
                                            if convert_from else f"Withdraw {iso} (комісія {total_fee} {iso})"),
                               fee=total_fee, fee_iso=iso,
                               gross_amount=total, source=src)
    if convert_from:
        await db.transactions.update_one({"tx_id": tx["tx_id"]},
            {"$set": {"convert_from": "USDT", "convert_amount": convert_amount,
                      "convert_chain": NETWORKS.get(payload.network_id, {}).get("chain")}})
    return {"status": True, "data": tx, "commission": total_fee,
            "platform_fee": platform_fee, "merchant_fee": round(merchant_fee, 8),
            "converted_from_usdt": convert_amount if convert_from else 0,
            "total_debited": round(total, 8)}


class ExchangeIn(BaseModel):
    from_iso: str
    to_iso: str
    amount: float


@cab.post("/wallet/exchange")
async def exchange(request: Request, payload: ExchangeIn):
    user = await get_current_user(request)
    uid = user["user_id"]
    fi, ti = payload.from_iso.upper(), payload.to_iso.upper()
    if fi not in CURRENCIES or ti not in CURRENCIES or fi == ti:
        raise HTTPException(400, "Invalid pair")
    bal = await get_balance(uid, fi)
    if payload.amount <= 0 or payload.amount > bal["balance_available"]:
        raise HTTPException(400, "Недостатньо коштів на балансі")
    # REAL on-chain swap via the hot wallet (1inch). Supported only for EVM pairs
    # that live on the same network (e.g. ETH/USDT/USDC on Ethereum, BNB/USDT on BSC).
    chain = _common_evm_chain(fi, ti)
    if not chain:
        raise HTTPException(
            400,
            f"Реальний обмін {fi} → {ti} недоступний on-chain. Підтримуються лише "
            "EVM-пари на одній мережі (ETH/USDT/USDC на Ethereum, BNB/USDT/USDC на "
            "BSC, USDT↔USDC на Polygon/Arbitrum тощо).")
    await ensure_seed()
    hot_pk = derive_evm_privkey(_seed["bytes"], 0)
    result = await asyncio.to_thread(_swap_exact, chain, fi, ti, payload.amount, hot_pk)
    if not result.get("ok"):
        raise HTTPException(400, result.get("error", "Обмін не виконано"))
    received_gross = float(result["received"])
    if received_gross <= 0:
        raise HTTPException(400, "Обмін повернув 0 — перевірте ліквідність/суму")
    plat = await get_platform_settings()
    swap_pct = swap_fee_percent_for(plat, fi)  # % комісія платформи (задає адмін)
    fee_ti = round(received_gross * (swap_pct / 100.0), 8)
    received = round(received_gross - fee_ti, 8)
    # Ledger: debit source, credit real received amount of target.
    await credit_balance(uid, fi, -payload.amount)
    await credit_balance(uid, ti, received)
    if fee_ti > 0:
        await add_to_pool(ti, fee_ti)
    await add_transaction(uid, "exchange", fi, None, payload.amount, status="Done",
                          txid=result.get("tx"),
                          description=f"Exchange {fi} → {ti} on {chain} (real swap, fee {swap_pct}%)",
                          usd=round(payload.amount * PRICES_USD.get(fi, 0.0), 2))
    tx = await add_transaction(uid, "exchange", ti, None, received, status="Done",
                               txid=result.get("tx"),
                               description=f"Received {ti} from {fi} (on-chain swap)")
    return {"status": True, "data": {"received": received, "gross_received": round(received_gross, 8),
            "rate": round(received / payload.amount, 8) if payload.amount else 0,
            "fee_ti": fee_ti, "fee_percent": swap_pct, "chain": chain,
            "txid": result.get("tx"), "tx": tx}}


# ---------- invoices (cabinet) ----------
class InvoiceIn(BaseModel):
    order_id: str = ""
    payment_currency_iso: str = "USD"
    price: float = 0
    include_commission: int = 1
    description: str = ""
    currencies: list = []
    time_expired: int = 0
    redirect_url: str = ""


async def _create_invoice(user, merchant, data: dict) -> dict:
    inv_id = gen_id()
    # Currency the merchant expects payment IN (crypto ticker like USDT/BTC/ETH).
    pci = (data.get("payment_currency_iso") or "USDT").upper()
    if pci not in CURRENCIES:
        raise HTTPException(400, f"payment_currency_iso must be one of: {', '.join(CURRENCIES.keys())}")
    # Build accepted (iso, network) pairs — filter out networks disabled by superadmin
    curs = data.get("currencies") or []
    net_settings = await db.system.find_one({"_id": "network_settings"}) or {"enabled": {}}
    enabled_map = net_settings.get("enabled", {})
    if not curs:
        curs = []
        for iso, c in CURRENCIES.items():
            for nid in c["networks"]:
                if enabled_map.get(str(nid), True):
                    curs.append({"iso": iso, "network": nid})
    else:
        # Validate + filter by admin-enabled networks
        filtered = []
        for row in curs:
            iso = row.get("iso", "").upper()
            nid = int(row.get("network"))
            if iso in CURRENCIES and nid in CURRENCIES[iso]["networks"] and enabled_map.get(str(nid), True):
                filtered.append({"iso": iso, "network": nid})
        curs = filtered
    if not curs:
        raise HTTPException(400, "Немає доступних мереж — усі вимкнено суперадміністратором")
    order_id = data.get("order_id") or gen_id(6)
    frontend = os.environ.get("FRONTEND_URL", "")
    inv = {
        "id": inv_id, "user_id": user["user_id"], "merchant_id": merchant["merchant_id"],
        "order_id": str(order_id), "payment_currency_iso": pci,
        "price": float(data.get("price", 0)), "include_commission": int(data.get("include_commission", 1)),
        "description": data.get("description", ""), "status_id": 0, "status": "Created",
        "currencies": curs, "link": f"{frontend}/checkout/{inv_id}",
        "redirect_url": data.get("redirect_url", ""),
        "time_create": now_ts(),
        "time_expired": int(data.get("time_expired")) if data.get("time_expired") else now_ts() + 3600,
        "pay_info": None, "amount_paid": 0.0, "usd_value": 0.0,
    }
    await db.invoices.insert_one(dict(inv))
    inv.pop("_id", None)
    return inv


@cab.get("/invoices")
async def list_invoices(request: Request):
    user = await get_current_user(request)
    invs = await db.invoices.find({"user_id": user["user_id"]}, {"_id": 0}).sort("time_create", -1).to_list(200)
    return {"status": True, "data": [invoice_public(i) for i in invs]}


@cab.post("/invoices")
async def create_invoice_cab(request: Request, payload: InvoiceIn):
    user = await get_current_user(request)
    merchant = await get_merchant(user["user_id"])
    inv = await _create_invoice(user, merchant, payload.model_dump())
    return {"status": True, "data": invoice_public(inv)}


@cab.post("/invoices/{inv_id}/cancel")
async def cancel_invoice(request: Request, inv_id: str):
    user = await get_current_user(request)
    inv = await db.invoices.find_one({"id": inv_id, "user_id": user["user_id"]})
    if not inv:
        raise HTTPException(404, "Not found")
    await db.invoices.update_one({"id": inv_id}, {"$set": {"status": "Cancelled", "status_id": 3}})
    return {"status": True}


# ---------- contacts ----------
class ContactIn(BaseModel):
    name: str
    address: str
    network_id: int
    currency: str = ""


@cab.get("/contacts")
async def list_contacts(request: Request):
    user = await get_current_user(request)
    cs = await db.contacts.find({"user_id": user["user_id"]}, {"_id": 0}).sort("created_at", -1).to_list(200)
    return {"status": True, "data": cs}


@cab.post("/contacts")
async def add_contact(request: Request, payload: ContactIn):
    user = await get_current_user(request)
    c = {"contact_id": uuid.uuid4().hex[:10], "user_id": user["user_id"], "name": payload.name,
         "address": payload.address, "network_id": payload.network_id, "currency": payload.currency.upper(),
         "network": NETWORKS.get(payload.network_id, {}).get("name", ""),
         "created_at": datetime.now(timezone.utc).isoformat()}
    await db.contacts.insert_one(dict(c))
    c.pop("_id", None)
    return {"status": True, "data": c}


@cab.delete("/contacts/{cid}")
async def del_contact(request: Request, cid: str):
    user = await get_current_user(request)
    await db.contacts.delete_one({"contact_id": cid, "user_id": user["user_id"]})
    return {"status": True}


# ---------- merchant settings ----------
class MerchantIn(BaseModel):
    name: str = None
    home_url: str = None
    result_url: str = None
    brand_color: str = None
    logo_url: str = None
    description: str = None
    auto_swap: bool = None
    auto_swap_to: str = None
    fees: dict = None


@cab.get("/merchant")
async def merchant_get(request: Request):
    user = await get_current_user(request)
    return {"status": True, "data": await get_merchant(user["user_id"])}


@cab.put("/merchant")
async def merchant_update(request: Request, payload: MerchantIn):
    user = await get_current_user(request)
    await get_merchant(user["user_id"])
    upd = {k: v for k, v in payload.model_dump().items() if v is not None}
    if upd:
        await db.merchants.update_one({"user_id": user["user_id"]}, {"$set": upd})
    return {"status": True, "data": await get_merchant(user["user_id"])}


@cab.post("/merchant/regenerate")
async def merchant_regen(request: Request):
    user = await get_current_user(request)
    await get_merchant(user["user_id"])
    await db.merchants.update_one({"user_id": user["user_id"]},
                                  {"$set": {"token": new_token(), "secret": new_secret()}})
    return {"status": True, "data": await get_merchant(user["user_id"])}


@cab.post("/merchant/test-webhook")
async def merchant_test_webhook(request: Request):
    """Send a signed sample webhook to the merchant result_url so integrators (ewex, etc.)
    can verify delivery + signature immediately. Returns the HTTP status and response body."""
    user = await get_current_user(request)
    merchant = await get_merchant(user["user_id"])
    url = merchant.get("result_url")
    if not url:
        raise HTTPException(400, "Спочатку вкажіть URL для сповіщень (result_url) у налаштуваннях мерчанта")
    payload = {
        "id": "test_" + gen_id(6), "order_id": "TEST-ORDER", "currency": "USDT",
        "payment_currency": "USDT", "status": "Paid", "amount": 3.0, "amount_send": 3.0,
        "price": 3.0, "price_send": 3.0, "rate": PRICES_USD.get("USDT", 1.0),
        "total_sum_price": 3.0, "commission": 0, "address": "TEST", "network_type": "BEP-20",
        "time_create": now_ts(), "time_update": now_ts(), "time_done": now_ts(),
        "time_expired": None, "time_send": now_ts(), "time_receive": None,
        "include_commission": 0, "test": True,
    }
    sign = make_signature(payload, merchant.get("secret", ""))
    headers = {"Content-Type": "application/json", "X-Auth-Token": merchant.get("token", ""),
               "X-Auth-Sign": sign, "User-Agent": "FozPay-Webhook/1.0"}
    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as c:
            r = await c.post(url, json=payload, headers=headers)
        return {"status": True, "data": {"url": url, "http_status": r.status_code,
                "response": r.text[:1000], "sign": sign,
                "delivered": 200 <= r.status_code < 300}}
    except Exception as e:
        return {"status": False, "data": {"url": url, "error": str(e), "delivered": False}}


# ---------- public checkout ----------
@cab.get("/checkout/{inv_id}")
async def checkout_get(inv_id: str):
    inv = await db.invoices.find_one({"id": inv_id}, {"_id": 0})
    if not inv:
        raise HTTPException(404, "Invoice not found")
    merchant = await db.merchants.find_one({"merchant_id": inv["merchant_id"]}, {"_id": 0})
    return {"status": True, "data": {
        **invoice_public(inv),
        "merchant": {"name": merchant.get("name", ""), "brand_color": merchant.get("brand_color", "#2563EB"),
                     "logo_url": merchant.get("logo_url", "")} if merchant else {},
        "currency_meta": {iso: {"name": CURRENCIES[iso]["name"], "color": CURRENCIES[iso]["color"]} for iso in CURRENCIES},
        "network_meta": {str(k): v for k, v in NETWORKS.items()},
    }}


class CheckoutSelectIn(BaseModel):
    iso: str
    network_id: int


@cab.post("/checkout/{inv_id}/select")
async def checkout_select(inv_id: str, payload: CheckoutSelectIn):
    inv = await db.invoices.find_one({"id": inv_id}, {"_id": 0})
    if not inv:
        raise HTTPException(404, "Invoice not found")
    if inv["status"] in ("Paid", "Completed", "Cancelled", "Expired"):
        raise HTTPException(400, "Invoice not payable")
    iso = payload.iso.upper()
    if iso not in CURRENCIES or payload.network_id not in CURRENCIES[iso]["networks"]:
        raise HTTPException(400, "Currency/network not available")
    if not await is_network_enabled(payload.network_id):
        net_name = NETWORKS.get(payload.network_id, {}).get("name", str(payload.network_id))
        raise HTTPException(400, f"Мережа {net_name} тимчасово вимкнена")
    addr = await allocate_address(inv["user_id"], iso, payload.network_id, invoice_id=inv_id)
    # Convert invoice price (denominated in a crypto ISO) to the chosen payment ISO via USD parity.
    pay_iso = (inv.get("payment_currency_iso") or "USDT").upper()
    if pay_iso not in PRICES_USD:
        raise HTTPException(400, f"Invoice currency {pay_iso} not supported")
    usd = float(inv["price"]) * PRICES_USD[pay_iso]
    amount = usd / PRICES_USD[iso] if PRICES_USD[iso] else 0.0
    merchant = await db.merchants.find_one({"merchant_id": inv["merchant_id"]}, {"_id": 0})
    infee = resolve_fee(merchant, iso, "in")
    merchant_fee = amount * infee["percent"] / 100 + infee["fixed"]
    # Include platform deposit fee in the amount the payer must send so recipient credit stays whole
    plat = await get_platform_settings()
    platform_fee = deposit_fee_for(plat, iso)
    amount_to_pay = amount
    net = NETWORKS[payload.network_id]
    pay_info = {"amount": round(amount, 8), "merchant_fee": round(merchant_fee, 8),
                "platform_fee": round(platform_fee, 8),
                "commission": round(merchant_fee + platform_fee, 8),
                "amount_to_pay": round(amount_to_pay, 8), "address": addr["address"],
                "currency": iso, "network": net["name"], "network_id": payload.network_id,
                "network_iso": net["iso"], "rate": PRICES_USD[iso]}
    await db.invoices.update_one({"id": inv_id}, {"$set": {"pay_info": pay_info, "status": "In Process", "status_id": 6}})
    return {"status": True, "data": pay_info}


@cab.post("/checkout/{inv_id}/simulate-pay", deprecated=True)
async def checkout_simulate_removed(inv_id: str):
    """Симуляція оплат ВИМКНЕНА — всі платежі приймаються тільки з реального блокчейну."""
    raise HTTPException(410, "Симуляція оплат вимкнена. Надішліть реальні кошти на адресу checkout — deposit worker підтвердить транзакцію on-chain (Alchemy/TronGrid).")


@cab.get("/currencies")
async def crypto_currency_list(request: Request):
    """List of CRYPTO currencies available for invoices/deposits (fiat removed)."""
    await get_current_user(request)
    net_settings = await db.system.find_one({"_id": "network_settings"}) or {"enabled": {}}
    enabled_map = net_settings.get("enabled", {})
    out = []
    for iso, c in CURRENCIES.items():
        nets = []
        for nid in c["networks"]:
            if enabled_map.get(str(nid), True):
                nm = NETWORKS[nid]
                nets.append({"network_id": nid, "network_iso": nm["iso"], "name": nm["name"], "chain": nm["chain"]})
        if nets:
            out.append({"iso": iso, "name": c["name"], "color": c["color"], "networks": nets,
                        "price_usd": PRICES_USD.get(iso, 0)})
    return {"status": True, "data": out}


# ============================ public fozpay API ============================
pub = APIRouter(prefix="/api/v1/public")


@pub.get("/currency-list")
async def currency_list():
    """Public list of CRYPTO ISOs supported for invoices (fiat is deprecated)."""
    return {"status": True, "data": [
        {"id": CURRENCIES[iso]["id"], "name": CURRENCIES[iso]["name"], "iso3": iso}
        for iso in CURRENCIES]}


@pub.get("/currency-network-list")
async def currency_network_list():
    return {"status": True, "data": [
        {"name": CURRENCIES[iso]["name"], "iso3": iso, "icon": "",
         "networks": networks_for(iso)} for iso in CURRENCIES]}


# ============================ private fozpay API (signature) ============================
priv = APIRouter(prefix="/api/v1")


async def auth_merchant(request: Request):
    token = request.headers.get("X-Auth-Token")
    if not token:
        raise HTTPException(401, "Your request was made with invalid credentials.NONE headers")
    merchant = await db.merchants.find_one({"token": token}, {"_id": 0})
    if not merchant:
        raise HTTPException(401, "Your request was made with invalid credentials.NONE headers")
    body = {}
    if request.method == "POST":
        try:
            body = await request.json()
        except Exception:
            body = {}
        sign = request.headers.get("X-Auth-Sign", "")
        expected = make_signature(body, merchant["secret"])
        if sign != expected:
            raise HTTPException(400, "Signature is invalid")
    user = await db.users.find_one({"user_id": merchant["user_id"]}, {"_id": 0})
    return merchant, user, body


def coins_payload(merchant=None):
    data = {}
    for iso, c in CURRENCIES.items():
        infee = resolve_fee(merchant, iso, "in")
        outfee = resolve_fee(merchant, iso, "out")
        nets = {}
        for nid in c["networks"]:
            net = NETWORKS[nid]
            comm = commission_for(iso, nid)
            nets[net["name"]] = {
                "name": net["name"], "network_id": nid, "network_iso": net["iso"],
                "in": 1, "out": 1,
                "withdraw": {"commission": {"fixed": comm["withdraw"]["fixed"] + outfee["fixed"],
                                            "percent": comm["withdraw"]["percent"] + outfee["percent"],
                                            "min_fee": comm["withdraw"]["min_fee"]},
                             "min": comm["withdraw"]["min"]},
                "refill": {"commission": {"fixed": infee["fixed"],
                                          "percent": infee["percent"],
                                          "min_fee": comm["refill"]["min_fee"]},
                           "min": comm["refill"]["min"]},
            }
        data[iso] = {"id": c["id"], "name": c["name"], "iso3": iso, "networks": nets}
    return data


@priv.get("/private/coins")
async def private_coins(request: Request):
    merchant, _, _ = await auth_merchant(request)
    return {"status": True, "data": coins_payload(merchant), "token": merchant["token"]}


@priv.post("/private/get-address")
async def private_get_address(request: Request):
    merchant, user, body = await auth_merchant(request)
    iso = str(body.get("currency", "")).upper()
    net_in = body.get("network")
    nid = _resolve_network(iso, net_in)
    if iso not in CURRENCIES or nid is None:
        return {"status": False, "error": "Currency not found", "token": merchant["token"]}
    addr = await allocate_address(user["user_id"], iso, nid)
    return {"status": True, "message": "", "data": {
        "address": addr["address"], "time_create": addr["time_create"],
        "network": NETWORKS[nid]["name"], "currency": {"iso": iso, "name": CURRENCIES[iso]["name"]}},
        "token": merchant["token"]}


def _resolve_network(iso, net_in):
    if iso not in CURRENCIES:
        return None
    allowed = CURRENCIES[iso]["networks"]
    if isinstance(net_in, int):
        return net_in if net_in in allowed else None
    if isinstance(net_in, str):
        for nid in allowed:
            if NETWORKS[nid]["name"].lower() == net_in.lower() or NETWORKS[nid]["iso"].lower() == net_in.lower():
                return nid
    if len(allowed) == 1:
        return allowed[0]
    return None


@priv.post("/order/create")
async def order_create(request: Request):
    merchant, user, body = await auth_merchant(request)
    if not body.get("order_id"):
        raise HTTPException(400, "order_id required")
    curs = []
    for c in body.get("currencies", []) or []:
        curs.append({"iso": str(c.get("iso", "")).upper(), "network": c.get("network")})
    pci = str(body.get("payment_currency_iso") or "USDT").upper()
    data = {"order_id": body.get("order_id"), "payment_currency_iso": pci,
            "price": body.get("price", 0), "include_commission": body.get("include_commission", 1),
            "description": body.get("description", ""), "currencies": curs,
            "time_expired": body.get("time_expired", 0), "redirect_url": body.get("redirect_url", "")}
    inv = await _create_invoice(user, merchant, data)
    return {"status": True, "message": "Success send request to create order.",
            "data": invoice_public(inv), "token": merchant["token"]}


@priv.post("/order/get")
async def order_get(request: Request):
    merchant, user, body = await auth_merchant(request)
    q = {"user_id": user["user_id"]}
    if body.get("order_id"):
        q["order_id"] = str(body["order_id"])
    inv = await db.invoices.find_one(q, {"_id": 0}, sort=[("time_create", -1)])
    if not inv:
        raise HTTPException(400, "Order not found")
    return {"status": True, "message": "Success get order data.",
            "data": invoice_public(inv), "token": merchant["token"]}


@priv.post("/merchant/balance")
async def merchant_balance(request: Request):
    merchant, user, body = await auth_merchant(request)
    iso = str(body.get("currency", "")).upper()
    if iso not in CURRENCIES:
        raise HTTPException(400, "Currency not available")
    b = await get_balance(user["user_id"], iso)
    return {"status": True, "message": "", "data": {
        "balance": str(b["balance"]), "balance_available": str(b["balance_available"]),
        "currency": {"iso3": iso, "name": CURRENCIES[iso]["name"]}}, "token": merchant["token"]}


@priv.post("/merchant/pay-in")
async def merchant_pay_in(request: Request):
    """Create Pay-in v2 — returns pay_info with deposit address immediately."""
    merchant, user, body = await auth_merchant(request)
    iso = str(body.get("currency", "")).upper()
    nid = _resolve_network(iso, body.get("network"))
    if iso not in CURRENCIES or nid is None:
        raise HTTPException(400, "Currency not available")
    if not await is_network_enabled(nid):
        net_name = NETWORKS.get(nid, {}).get("name", str(nid))
        raise HTTPException(400, f"Мережа {net_name} тимчасово вимкнена суперадміністратором")
    amount = float(body.get("amount", 0))
    data = {"order_id": body.get("order_id") or gen_id(6), "payment_currency_iso": iso,
            "price": amount, "include_commission": body.get("include_commission", 0),
            "description": body.get("description", ""),
            "currencies": [{"iso": iso, "network": nid}],
            "redirect_url": body.get("redirect_url", "")}
    inv = await _create_invoice(user, merchant, data)
    addr = await allocate_address(user["user_id"], iso, nid, invoice_id=inv["id"])
    infee = resolve_fee(merchant, iso, "in")
    merchant_fee = amount * infee["percent"] / 100 + infee["fixed"]
    # Include platform fee so the recipient credit stays whole after platform deducts it
    plat = await get_platform_settings()
    platform_fee = deposit_fee_for(plat, iso)
    amount_to_pay = amount
    net = NETWORKS[nid]
    pay_info = {"commission": round(merchant_fee + platform_fee, 8),
                "merchant_fee": round(merchant_fee, 8),
                "platform_fee": round(platform_fee, 8),
                "amount_to_pay": round(amount_to_pay, 8),
                "amount": round(amount, 8), "address": addr["address"],
                "currency": iso, "network": net["name"], "network_id": nid, "rate": PRICES_USD[iso]}
    await db.invoices.update_one({"id": inv["id"]}, {"$set": {"pay_info": pay_info, "status": "In Process", "status_id": 6}})
    inv = await db.invoices.find_one({"id": inv["id"]}, {"_id": 0})
    return {"status": True, "message": "Success send request to create order.",
            "data": invoice_public(inv), "token": merchant["token"]}


# ============================ recovery (wrong-network) ============================
import recovery as rec_mod
from hd_wallet import derive_evm_privkey

rec = APIRouter(prefix="/api/recovery")


@rec.get("/scan")
async def recovery_scan(request: Request, address: str = None):
    user = await get_current_user(request)
    q = {"user_id": user["user_id"]}
    docs = await db.addresses.find(q, {"_id": 0}).to_list(500)
    evm_addrs, tron_addrs, btc_addrs = {}, set(), set()
    for d in docs:
        ch = d["chain"]
        if address and d["address"] != address:
            continue
        if ch in rec_mod.EVM or ch in ("ethereum", "polygon", "bsc", "arbitrum"):
            evm_addrs.setdefault(d["address"], d["index"])
        elif ch == "tron":
            tron_addrs.add(d["address"])
        elif ch == "bitcoin":
            btc_addrs.add(d["address"])
    findings = []
    for a, idx in list(evm_addrs.items())[:30]:
        res = await asyncio.to_thread(rec_mod.scan_evm_address, a)
        for r in res:
            r["index"] = idx
        findings.extend(res)
    for a in list(tron_addrs)[:20]:
        findings.extend(await asyncio.to_thread(rec_mod.scan_tron_address, a))
    for a in list(btc_addrs)[:20]:
        findings.extend(await asyncio.to_thread(rec_mod.scan_btc_address, a))
    return {"status": True, "treasury": rec_mod.TREASURY_EVM,
            "scanned": {"evm": len(evm_addrs), "tron": len(tron_addrs), "btc": len(btc_addrs)},
            "findings": findings}


class SweepIn(BaseModel):
    address: str
    chain: str
    kind: str
    contract: str = None
    to_address: str = None


@rec.post("/sweep")
async def recovery_sweep(request: Request, payload: SweepIn):
    user = await get_current_user(request)
    if payload.chain not in rec_mod.EVM:
        raise HTTPException(400, "Sweep підтримується лише для EVM-мереж (ETH/BSC/Polygon/Arbitrum)")
    doc = await db.addresses.find_one({"user_id": user["user_id"], "address": payload.address}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "Адресу не знайдено")
    await ensure_seed()
    pk = derive_evm_privkey(_seed["bytes"], doc["index"])
    from eth_account import Account
    if Account.from_key(pk).address.lower() != payload.address.lower():
        raise HTTPException(400, "Приватний ключ не відповідає адресі (стара seed-фраза). Згенеруйте нову адресу.")
    tpk = rec_mod.treasury_privkey(_seed["bytes"])
    result = await asyncio.to_thread(
        rec_mod.sweep_evm, pk, payload.chain, payload.kind, payload.contract, payload.to_address, tpk)
    if not result.get("ok"):
        raise HTTPException(400, result.get("error", "Sweep failed"))
    await add_transaction(user["user_id"], "recovery", payload.kind == "native" and rec_mod.EVM[payload.chain][2] or "TOKEN",
                          rec_mod.EVM[payload.chain][1], 0, status="Done",
                          address=result["to"], txid=result["tx_hash"],
                          description=f"Recovery sweep {payload.chain} → treasury")
    return {"status": True, "data": result}


class SwapReq(BaseModel):
    address: str
    chain: str
    src_iso: str
    dst_iso: str


@rec.post("/swap")
async def recovery_swap(request: Request, payload: SwapReq):
    user = await get_current_user(request)
    if payload.chain not in rec_mod.EVM:
        raise HTTPException(400, "Swap підтримується лише для EVM-мереж")
    doc = await db.addresses.find_one({"user_id": user["user_id"], "address": payload.address}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "Адресу не знайдено")
    await ensure_seed()
    pk = derive_evm_privkey(_seed["bytes"], doc["index"])
    tpk = rec_mod.treasury_privkey(_seed["bytes"])
    res = await asyncio.to_thread(_do_swap, pk, payload.chain, payload.src_iso.upper(), payload.dst_iso.upper(), tpk)
    if isinstance(res, dict) and res.get("ok") is False:
        raise HTTPException(400, res.get("error", "Swap failed"))
    return {"status": True, "data": res}
# ============================ hot wallet (admin) ============================
hotw = APIRouter(prefix="/api/admin")


async def _require_admin(request: Request) -> dict:
    user = await get_current_user(request)
    if user.get("role") != "admin":
        raise HTTPException(403, "Тільки для адміністратора FozPay")
    return user


async def _hot_wallet_addresses():
    await ensure_seed()
    evm = rec_mod.TREASURY_EVM or os.environ.get("TREASURY_EVM", "")
    tron = derive_address(_seed["bytes"], "tron", 0)["address"]
    return evm, tron


@hotw.get("/hot-wallet")
async def hot_wallet_get(request: Request):
    await _require_admin(request)
    evm, tron = await _hot_wallet_addresses()
    bals = await asyncio.to_thread(rec_mod.hot_wallet_balances, evm, tron)
    total_usd = round(sum(float(b.get("usd", 0) or 0) for b in bals), 2)
    return {"status": True, "data": {"evm_address": evm, "tron_address": tron,
                                     "balances": bals, "total_usd": total_usd}}


class HotWithdrawIn(BaseModel):
    chain: str
    iso: str
    to_address: str
    amount: float
    otp: Optional[str] = None


@hotw.post("/hot-wallet/withdraw")
async def hot_wallet_withdraw(request: Request, payload: HotWithdrawIn):
    user = await _require_admin(request)
    if (user.get("two_fa") or {}).get("enabled"):
        if not await check_user_2fa(user, payload.otp):
            raise HTTPException(401, "Потрібен коректний код 2FA")
    if payload.amount <= 0:
        raise HTTPException(400, "Некоректна сума")
    if payload.chain not in rec_mod.EVM:
        raise HTTPException(400, "Реальний вивід з гарячого гаманця підтримується для EVM-мереж (ETH/BSC/Polygon/Arbitrum). Для TRON/BTC — вручну оператором.")
    await ensure_seed()
    tpk = rec_mod.treasury_privkey(_seed["bytes"])
    if not tpk:
        raise HTTPException(400, "Не вдалося отримати приватний ключ гарячого гаманця (перевірте TREASURY_EVM/мнемонік)")
    res = await asyncio.to_thread(
        rec_mod.send_evm_amount, tpk, payload.chain, payload.iso.upper(),
        payload.to_address, payload.amount, tpk)
    if not res.get("ok"):
        raise HTTPException(400, res.get("error", "Не вдалося надіслати"))
    nid = rec_mod.EVM[payload.chain][1]
    await add_transaction("platform", "hot_withdraw", payload.iso.upper(), nid, payload.amount,
                          status="Done", address=payload.to_address, txid=res["tx_hash"],
                          description=f"Hot wallet payout {payload.chain}", source="platform")
    return {"status": True, "data": res}


# ============================ admin: user management ============================
class AdminUserCreateIn(BaseModel):
    email: str
    password: str
    name: str = ""


class AdminUserPasswordIn(BaseModel):
    user_id: str
    password: str


@hotw.get("/users")
async def admin_users_list(request: Request):
    await _require_admin(request)
    users = await db.users.find({}, {"_id": 0, "password_hash": 0}).sort("created_at", -1).to_list(500)
    for u in users:
        wallets = await db.wallets.find({"user_id": u["user_id"]}, {"_id": 0}).to_list(100)
        balances = []
        total_usdt = 0.0
        for w in wallets:
            iso = w.get("iso")
            bal = float(w.get("balance", 0.0) or 0.0)
            if bal == 0:
                continue
            usd = round(bal * PRICES_USD.get(iso, 0.0), 2)
            total_usdt += usd
            balances.append({"iso": iso, "balance": round(bal, 8), "usd": usd})
        balances.sort(key=lambda x: -x["usd"])
        u["balances"] = balances
        u["balance_usdt"] = round(total_usdt, 2)
    return {"status": True, "data": users}


@hotw.post("/users")
async def admin_users_create(request: Request, payload: AdminUserCreateIn):
    await _require_admin(request)
    email = payload.email.lower().strip()
    if not email or not payload.password:
        raise HTTPException(400, "Email та пароль обов'язкові")
    if await db.users.find_one({"email": email}):
        raise HTTPException(400, "Користувач з таким email вже існує")
    user_id = f"user_{uuid.uuid4().hex[:12]}"
    user = {"user_id": user_id, "email": email, "name": payload.name or email.split("@")[0],
            "password_hash": hash_password(payload.password), "auth_provider": "password",
            "role": "user", "picture": "", "created_at": datetime.now(timezone.utc).isoformat()}
    await db.users.insert_one(dict(user))
    await get_merchant(user_id)
    user.pop("password_hash", None)
    return {"status": True, "data": user}


@hotw.put("/users/password")
async def admin_users_password(request: Request, payload: AdminUserPasswordIn):
    await _require_admin(request)
    if not payload.password or len(payload.password) < 4:
        raise HTTPException(400, "Пароль занадто короткий")
    r = await db.users.update_one({"user_id": payload.user_id},
                                  {"$set": {"password_hash": hash_password(payload.password),
                                            "auth_provider": "password"}})
    if r.matched_count == 0:
        raise HTTPException(404, "Користувача не знайдено")
    return {"status": True, "message": "Пароль оновлено"}


@hotw.delete("/users/{uid}")
async def admin_users_delete(request: Request, uid: str):
    admin = await _require_admin(request)
    if uid == admin["user_id"]:
        raise HTTPException(400, "Не можна видалити власний акаунт")
    await db.users.delete_one({"user_id": uid})
    await db.merchants.delete_many({"user_id": uid})
    await db.wallets.delete_many({"user_id": uid})
    return {"status": True, "message": "Користувача видалено"}


async def sweep_to_hot_wallet(chain, iso, address):
    """Move a received deposit from the per-user address to the platform hot wallet.
    EVM: real on-chain sweep (auto-funds gas from hot wallet). Non-EVM: operator handles."""
    try:
        if chain not in rec_mod.EVM:
            return
        doc = await db.addresses.find_one({"address": address}, {"_id": 0})
        if not doc:
            return
        await ensure_seed()
        pk = derive_evm_privkey(_seed["bytes"], doc["index"])
        # Don't sweep the hot wallet into itself
        from eth_account import Account as _Acct
        if _Acct.from_key(pk).address.lower() == (rec_mod.TREASURY_EVM or "").lower():
            return
        tpk = rec_mod.treasury_privkey(_seed["bytes"])
        native = rec_mod.EVM[chain][2]
        kind = "native" if iso == native else "token"
        contract = None if kind == "native" else (rec_mod.TOKENS.get(chain, {}).get(iso) or [None])[0]
        if kind == "token" and not contract:
            return
        res = await asyncio.to_thread(
            rec_mod.sweep_evm, pk, chain, kind, contract, rec_mod.TREASURY_EVM, tpk)
        logger.info(f"sweep_to_hot_wallet {iso} {chain} {address}: {res}")
    except Exception as e:
        logger.info(f"sweep_to_hot_wallet failed: {e}")


def _evm_chains_for_iso(iso):
    """EVM chains where this ISO is either the native coin or a known token."""
    chains = []
    for ch, (sub, nid, native, cid) in rec_mod.EVM.items():
        if iso == native or iso in rec_mod.TOKENS.get(ch, {}):
            chains.append(ch)
    return chains


async def _credit_direct_deposit(a, iso, chain, nid, onchain):
    """Credit the delta of a detected on-chain deposit (per address+iso+chain) and sweep."""
    address = a["address"]
    seen = await db.addr_credits.find_one({"address": address, "iso": iso, "chain": chain})
    last = float(seen.get("balance", 0.0)) if seen else 0.0
    if onchain > last + 1e-9:
        delta = round(onchain - last, 8)
        plat = await get_platform_settings()
        plat_fee = deposit_fee_for(plat, iso)
        net_amount = max(0.0, round(delta - plat_fee, 8))
        fee_applied = round(delta - net_amount, 8)
        await credit_balance(a["user_id"], iso, net_amount)
        if fee_applied > 0:
            await add_to_pool(iso, fee_applied, network_id=nid)
        net_name = NETWORKS.get(nid, {}).get("name", chain)
        real_hash = await asyncio.to_thread(rec_mod.last_incoming_tx, address, chain, iso)
        txrec = await add_transaction(
            a["user_id"], "deposit", iso, nid, net_amount, status="Done",
            address=address, txid=real_hash or "onchain",
            description=f"Deposit {iso} · {net_name} (gross {delta} {iso}, fee {fee_applied} {iso})",
            fee=fee_applied, fee_iso=iso, gross_amount=delta, source="cabinet")
        await db.addr_credits.update_one(
            {"address": address, "iso": iso, "chain": chain},
            {"$set": {"balance": onchain, "updated_ts": now_ts()}}, upsert=True)
        logger.info(f"direct deposit credited: {net_amount} {iso} on {chain} @ {address}")
        asyncio.create_task(sweep_to_hot_wallet(chain, iso, address))
        # Notify merchant callback (result_url) for direct/API deposits too.
        merchant = await db.merchants.find_one({"user_id": a["user_id"]}, {"_id": 0})
        if merchant and merchant.get("result_url"):
            synth = {
                "id": txrec.get("tx_id"), "order_id": a.get("order_id", "") or "",
                "status": "Paid", "payment_currency_iso": iso, "price": net_amount,
                "pay_info": {"address": address, "network": net_name},
                "time_create": now_ts(), "time_expired": None, "include_commission": 0,
            }
            asyncio.create_task(send_webhook(merchant, synth, iso, delta))
    elif onchain < last:
        await db.addr_credits.update_one(
            {"address": address, "iso": iso, "chain": chain},
            {"$set": {"balance": onchain, "updated_ts": now_ts()}}, upsert=True)


async def direct_deposit_worker():
    """LIVE detection for CABINET deposits made straight to a wallet address (no invoice).
    Credits balance + writes history, then sweeps funds to the hot wallet.
    EVM addresses are identical across ETH/BSC/Polygon/Arbitrum, so we detect the deposit
    on ALL EVM chains (a user who chose ERC-20 but paid on BEP-20 is still credited)."""
    await asyncio.sleep(12)
    while True:
        try:
            addrs = await db.addresses.find(
                {"invoice_id": None}, {"_id": 0}).sort("time_create", -1).to_list(300)
            for a in addrs:
                chain = a.get("chain")
                iso = a.get("iso")
                address = a.get("address")
                if not (chain and iso and address):
                    continue
                if chain in rec_mod.EVM:
                    # Scan the SAME 0x address across EVERY EVM network for ALL
                    # supported assets (native + tokens). A deposit is detected and
                    # swept no matter which EVM chain / currency the sender used.
                    try:
                        findings = await asyncio.to_thread(rec_mod.scan_evm_address, address)
                    except Exception:
                        findings = []
                    for f in findings:
                        sym = f.get("symbol")
                        if sym not in CURRENCIES:
                            continue
                        await _credit_direct_deposit(
                            a, sym, f["chain"], f["network_id"], float(f.get("amount") or 0))
                elif chain == "tron":
                    onchain = await asyncio.to_thread(rec_mod.check_tron_deposit, address, iso)
                    await _credit_direct_deposit(a, iso, "tron", 2, float(onchain or 0))
                elif chain == "bitcoin":
                    onchain = await asyncio.to_thread(rec_mod.check_btc_deposit, address)
                    await _credit_direct_deposit(a, iso, "bitcoin", 0, float(onchain or 0))
        except Exception as e:
            logger.info(f"direct_deposit_worker error: {e}")
        await asyncio.sleep(25)





async def withdrawal_worker():
    """Execute REAL on-chain payouts for Pending withdrawals from the hot wallet (EVM).
    Non-EVM withdrawals stay Pending for the operator."""
    await asyncio.sleep(15)
    while True:
        try:
            pend = await db.transactions.find(
                {"type": "withdraw", "status": "Pending"}, {"_id": 0}).to_list(100)
            for tx in pend:
                nid = tx.get("network_id")
                chain = NETWORKS.get(nid, {}).get("chain")
                if chain not in rec_mod.EVM:
                    continue
                if int(tx.get("wd_attempts", 0)) >= 5:
                    continue
                await ensure_seed()
                tpk = rec_mod.treasury_privkey(_seed["bytes"])
                if not tpk:
                    continue
                # Auto-convert leg: swap USDT→iso on the hot wallet first (real 1inch)
                if tx.get("convert_from") == "USDT" and not tx.get("converted"):
                    conv = await asyncio.to_thread(
                        _swap_exact, chain, "USDT", tx["iso"], float(tx.get("convert_amount") or 0), tpk)
                    if not conv.get("ok"):
                        await db.transactions.update_one(
                            {"tx_id": tx["tx_id"]},
                            {"$inc": {"wd_attempts": 1},
                             "$set": {"wd_error": "convert: " + conv.get("error", "")}})
                        continue
                    await db.transactions.update_one(
                        {"tx_id": tx["tx_id"]},
                        {"$set": {"converted": True, "convert_txid": conv.get("tx")}})
                res = await asyncio.to_thread(
                    rec_mod.send_evm_amount, tpk, chain, tx["iso"], tx["address"], tx["amount"], tpk)
                if res.get("ok"):
                    await db.transactions.update_one(
                        {"tx_id": tx["tx_id"]},
                        {"$set": {"status": "Done", "txid": res["tx_hash"],
                                  "explorer_url": catalog.explorer_tx_url(nid, res["tx_hash"])}})
                    logger.info(f"withdrawal paid {tx['tx_id']}: {res['tx_hash']}")
                else:
                    await db.transactions.update_one(
                        {"tx_id": tx["tx_id"]},
                        {"$inc": {"wd_attempts": 1},
                         "$set": {"wd_error": res.get("error", "")}})
                    logger.info(f"withdrawal {tx['tx_id']} not sent: {res.get('error')}")
        except Exception as e:
            logger.info(f"withdrawal_worker error: {e}")
        await asyncio.sleep(30)


async def deposit_worker():
    """LIVE detection: poll pending invoices and credit merchant when funds arrive on-chain."""
    await asyncio.sleep(8)
    while True:
        try:
            ts = now_ts()
            cur = db.invoices.find({"status": {"$in": ["In Process", "Partially"]},
                                    "pay_info": {"$ne": None},
                                    "time_expired": {"$gt": ts}}, {"_id": 0})
            async for inv in cur:
                pi = inv["pay_info"]
                chain = NETWORKS.get(pi["network_id"], {}).get("chain")
                sym = pi["currency"]
                addr = pi["address"]
                expected = float(pi.get("amount_to_pay", pi["amount"]))
                if chain in rec_mod.EVM:
                    got = await asyncio.to_thread(rec_mod.check_evm_deposit, addr, chain, sym)
                elif chain == "tron":
                    got = await asyncio.to_thread(rec_mod.check_tron_deposit, addr, sym)
                elif chain == "bitcoin":
                    got = await asyncio.to_thread(rec_mod.check_btc_deposit, addr)
                else:
                    continue
                if got <= 0:
                    continue
                if got >= expected * 0.995:
                    status = "Overpayment" if got > expected * 1.02 else "Paid"
                    sid = 10 if status == "Overpayment" else 8
                    await _confirm_payment(inv, sym, pi["network_id"], got, addr, status, sid)
                elif got > 0:
                    await db.invoices.update_one({"id": inv["id"]},
                        {"$set": {"status": "Partially", "status_id": 1, "amount_paid": got}})
        except Exception as e:
            logger.info(f"deposit_worker error: {e}")
        await asyncio.sleep(20)


async def _confirm_payment(inv, iso, nid, amount, address, status, sid, from_address=None):
    already = await db.invoices.find_one({"id": inv["id"]}, {"status": 1})
    if already and already.get("status") in ("Paid", "Completed", "Overpayment"):
        return
    # AML screening on the sender (if we can detect it, best-effort)
    aml_result = await aml_mod.check_deposit_aml(from_address or "", amount, iso, nid)
    if aml_result.get("action") == "BLOCK":
        logger.warning(f"AML BLOCK deposit inv={inv['id']} from={from_address}: {aml_result}")
        await db.invoices.update_one({"id": inv["id"]}, {"$set": {
            "status": "Blocked", "status_id": 8, "aml": aml_result,
            "amount_paid": amount}})
        # Record a blocked transaction so admin sees it
        await add_transaction(inv["user_id"], "deposit_blocked", iso, nid, 0,
                              status="Blocked", address=address, txid="onchain",
                              description=f"BLOCKED by AML ({', '.join(aml_result.get('flags', []))})",
                              invoice_id=inv["id"], order_id=inv["order_id"],
                              fee=0, fee_iso=iso, gross_amount=float(amount),
                              source="cabinet")
        return
    review_hold = aml_result.get("action") == "REVIEW"
    # Deduct platform deposit fee (e.g. 0.5 USDT flat) from the incoming amount.
    plat = await get_platform_settings()
    plat_fee = deposit_fee_for(plat, iso)
    net_amount = max(0.0, round(float(amount) - plat_fee, 8))
    fee_applied = round(float(amount) - net_amount, 8)
    if not review_hold:
        await credit_balance(inv["user_id"], iso, net_amount)
    if fee_applied > 0:
        await add_to_pool(iso, fee_applied, network_id=nid)
    if not review_hold:
        asyncio.create_task(sweep_to_hot_wallet(nid and NETWORKS.get(nid, {}).get("chain"), iso, address))
    tx_status = "Review" if review_hold else "Done"
    real_hash = await asyncio.to_thread(
        rec_mod.last_incoming_tx, address, NETWORKS.get(nid, {}).get("chain"), iso)
    await add_transaction(inv["user_id"], "deposit", iso, nid, net_amount, status=tx_status,
                          address=address, txid=real_hash or "onchain",
                          description=f"Deposit Invoice #{inv['id']} (gross {amount} {iso}, fee {fee_applied} {iso})"
                                      + (" — ON HOLD by AML" if review_hold else ""),
                          invoice_id=inv["id"], order_id=inv["order_id"],
                          fee=fee_applied, fee_iso=iso, gross_amount=float(amount),
                          source="cabinet")
    await db.invoices.update_one({"id": inv["id"]}, {"$set": {
        "status": ("Hold" if review_hold else status),
        "status_id": (9 if review_hold else sid),
        "amount_paid": amount, "aml": aml_result,
        "usd_value": round(amount * PRICES_USD.get(iso, 0.0), 2)}})
    inv["status"] = "Hold" if review_hold else status
    merchant = await db.merchants.find_one({"merchant_id": inv["merchant_id"]}, {"_id": 0})
    if merchant and not review_hold:
        await send_webhook(merchant, inv, iso, amount)
        if merchant.get("auto_swap"):
            asyncio.create_task(_auto_swap(inv, merchant, iso, address))


async def _auto_swap(inv, merchant, iso, address):
    """Best-effort 1inch swap of a received EVM deposit into the target currency."""
    try:
        pi = inv["pay_info"]
        chain = NETWORKS.get(pi["network_id"], {}).get("chain")
        if chain not in rec_mod.EVM:
            return
        target = (merchant.get("auto_swap_to") or "USDT").upper()
        if iso == target:
            return
        doc = await db.addresses.find_one({"address": address}, {"_id": 0})
        if not doc:
            return
        await ensure_seed()
        pk = derive_evm_privkey(_seed["bytes"], doc["index"])
        tpk = rec_mod.treasury_privkey(_seed["bytes"])
        res = await asyncio.to_thread(_do_swap, pk, chain, iso, target, tpk)
        logger.info(f"auto_swap invoice {inv['id']}: {res}")
    except Exception as e:
        logger.info(f"auto_swap failed: {e}")


def _do_swap(privkey, chain, src_iso, dst_iso, treasury_pk):
    """Resolve tokens, ensure gas, execute 1inch swap on the deposit address."""
    import oneinch as oi
    from web3 import Web3
    native = rec_mod.EVM[chain][2]
    chainid = rec_mod.EVM[chain][3]
    w3 = rec_mod._w3(chain)
    acct = w3.eth.account.from_key(privkey)
    frm = acct.address
    # resolve src amount + address
    if src_iso == native:
        src = oi.NATIVE
        amount = w3.eth.get_balance(frm)
        gas_reserve = 250000 * w3.eth.gas_price
        amount = amount - gas_reserve
    else:
        tok = rec_mod.TOKENS.get(chain, {}).get(src_iso)
        if not tok:
            return {"ok": False, "error": "src token not on chain"}
        src = Web3.to_checksum_address(tok[0])
        c = w3.eth.contract(address=src, abi=rec_mod.ERC20_ABI)
        amount = c.functions.balanceOf(frm).call()
        # ensure gas for approve+swap
        need = 350000 * w3.eth.gas_price
        if w3.eth.get_balance(frm) < need and treasury_pk:
            gf = rec_mod._fund_gas(w3, treasury_pk, frm, int(need * 1.3), w3.eth.gas_price, chainid, native)
            if gf.get("ok"):
                w3.eth.wait_for_transaction_receipt(gf["tx_hash"], timeout=180)
    if amount <= 0:
        return {"ok": False, "error": "nothing to swap"}
    dtok = rec_mod.TOKENS.get(chain, {}).get(dst_iso)
    dst = oi.NATIVE if dst_iso == native else (Web3.to_checksum_address(dtok[0]) if dtok else None)
    if not dst:
        return {"ok": False, "error": "dst token not on chain"}
    return oi.execute_swap(w3, privkey, chain, src, dst, amount)


def _iso_evm_repr(chain, iso):
    """Return ('native'|'token', contract_or_None, decimals) for iso on an EVM chain, else None."""
    native = rec_mod.EVM[chain][2]
    if iso == native:
        return ("native", None, 18)
    tok = rec_mod.TOKENS.get(chain, {}).get(iso)
    if tok:
        return ("token", tok[0], tok[1])
    return None


def _common_evm_chain(fi, ti):
    """First EVM chain where BOTH currencies are swappable on-chain (native or token)."""
    for ch in rec_mod.EVM:
        if _iso_evm_repr(ch, fi) and _iso_evm_repr(ch, ti):
            return ch
    return None


def _hot_iso_balance(w3, addr, chain, iso):
    """Human-unit balance of `iso` (native or ERC-20) held by `addr` on `chain`."""
    rep = _iso_evm_repr(chain, iso)
    if not rep:
        return 0.0
    kind, contract, dec = rep
    if kind == "native":
        return w3.eth.get_balance(addr) / 1e18
    from web3 import Web3
    c = w3.eth.contract(address=Web3.to_checksum_address(contract), abi=rec_mod.ERC20_ABI)
    return c.functions.balanceOf(addr).call() / (10 ** dec)


def _swap_exact(chain, src_iso, dst_iso, amount_human, hot_pk):
    """Execute a REAL 1inch swap of a SPECIFIC amount from the hot wallet and
    return the actual received amount of dst_iso (measured on-chain)."""
    import oneinch as oi
    from web3 import Web3
    native = rec_mod.EVM[chain][2]
    w3 = rec_mod._w3(chain)
    acct = w3.eth.account.from_key(hot_pk)
    frm = acct.address
    gas_price = w3.eth.gas_price
    src_rep = _iso_evm_repr(chain, src_iso)
    dst_rep = _iso_evm_repr(chain, dst_iso)
    if not src_rep or not dst_rep:
        return {"ok": False, "error": "Пара не підтримується для on-chain обміну"}
    # resolve src token address + base amount, verify hot-wallet holds it + gas
    if src_rep[0] == "native":
        src = oi.NATIVE
        base = int(round(amount_human * 1e18))
        if w3.eth.get_balance(frm) < base + 300000 * gas_price:
            return {"ok": False, "error": f"Недостатньо {native} на гарячому гаманці для обміну"}
    else:
        src = Web3.to_checksum_address(src_rep[1])
        base = int(round(amount_human * (10 ** src_rep[2])))
        c = w3.eth.contract(address=src, abi=rec_mod.ERC20_ABI)
        if c.functions.balanceOf(frm).call() < base:
            return {"ok": False, "error": f"Недостатньо {src_iso} на гарячому гаманці для обміну"}
        if w3.eth.get_balance(frm) < 350000 * gas_price:
            return {"ok": False, "error": f"Недостатньо {native} для газу на гарячому гаманці"}
    if base <= 0:
        return {"ok": False, "error": "Некоректна сума обміну"}
    dst = oi.NATIVE if dst_rep[0] == "native" else Web3.to_checksum_address(dst_rep[1])
    before = _hot_iso_balance(w3, frm, chain, dst_iso)
    try:
        res = oi.execute_swap(w3, hot_pk, chain, src, dst, base)
        w3.eth.wait_for_transaction_receipt(res["swap"], timeout=150)
    except Exception as e:
        return {"ok": False, "error": f"Помилка on-chain обміну: {str(e)[:180]}"}
    after = _hot_iso_balance(w3, frm, chain, dst_iso)
    received = max(0.0, after - before)
    return {"ok": True, "received": received, "tx": res.get("swap"), "chain": chain}


async def expire_worker():
    while True:
        try:
            ts = now_ts()
            cur = db.invoices.find({"status": {"$in": ["Created", "In Process"]},
                                    "time_expired": {"$lt": ts}}, {"_id": 0})
            async for inv in cur:
                await db.invoices.update_one({"id": inv["id"]}, {"$set": {"status": "Expired", "status_id": 7}})
                merchant = await db.merchants.find_one({"merchant_id": inv["merchant_id"]}, {"_id": 0})
                if merchant:
                    inv["status"] = "Expired"
                    await send_webhook(merchant, inv)
        except Exception as e:
            logger.info(f"worker error: {e}")
        await asyncio.sleep(30)


async def seed_demo():
    admin_email = os.environ["ADMIN_EMAIL"].lower()
    admin_pw = os.environ["ADMIN_PASSWORD"]
    existing = await db.users.find_one({"email": admin_email})
    if existing:
        if existing.get("password_hash") and not verify_password(admin_pw, existing["password_hash"]):
            await db.users.update_one({"email": admin_email}, {"$set": {"password_hash": hash_password(admin_pw)}})
        uid = existing["user_id"]
    else:
        uid = f"user_{uuid.uuid4().hex[:12]}"
        await db.users.insert_one({"user_id": uid, "email": admin_email, "name": "Merchant",
                                   "password_hash": hash_password(admin_pw), "auth_provider": "password",
                                   "picture": "", "role": "admin",
                                   "created_at": datetime.now(timezone.utc).isoformat()})
    await get_merchant(uid)
    # ONE-TIME purge of any previously seeded/test financial data so the cabinet
    # reflects REAL on-chain state (zero until real payments arrive).
    flag = await db.system.find_one({"_id": "purged_v3"})
    if not flag:
        await db.wallets.delete_many({"user_id": uid})
        await db.transactions.delete_many({"user_id": uid})
        await db.invoices.delete_many({"user_id": uid})
        await db.system.update_one({"_id": "purged_v3"}, {"$set": {"done": True}}, upsert=True)
        logger.info(f"Purged demo/test financial data for {admin_email} — cabinet now shows real data")
    return uid


@app.on_event("startup")
async def startup():
    await db.users.create_index("email", unique=True)
    await db.users.create_index("user_id")
    await db.merchants.create_index("token")
    await db.merchants.create_index("user_id")
    await db.addresses.create_index([("chain", 1), ("index", 1)], unique=True)
    await db.invoices.create_index("id", unique=True)
    await db.transactions.create_index([("user_id", 1), ("created_ts", -1)])
    await db.user_sessions.create_index("session_token")
    await ensure_seed()
    uid = await seed_demo()
    merchant = await db.merchants.find_one({"user_id": uid}, {"_id": 0})
    try:
        from pathlib import Path as _P
        _P("/app/memory/test_credentials.md").write_text(
            "# Test Credentials\n\n"
            f"## Admin cabinet (email/password)\n- Email: {os.environ['ADMIN_EMAIL']}\n"
            f"- Password: {os.environ['ADMIN_PASSWORD']}\n- Role: admin\n\n"
            "Note: Публічної реєстрації немає. Адмін створює користувачів у "
            "Налаштування → Користувачі та може змінювати їхні паролі.\n\n"
            "## Merchant API keys (for private /api/v1 endpoints)\n"
            f"- X-Auth-Token: {merchant['token']}\n- Secret: {merchant['secret']}\n\n"
            "## Auth endpoints\n- POST /api/auth/login\n"
            "- POST /api/auth/google/session\n- GET /api/auth/me\n- POST /api/auth/logout\n")
    except Exception as e:
        logger.info(f"cred write failed: {e}")
    asyncio.create_task(expire_worker())
    asyncio.create_task(deposit_worker())
    asyncio.create_task(direct_deposit_worker())
    asyncio.create_task(withdrawal_worker())
    asyncio.create_task(aml_mod.aml_refresh_worker())
    asyncio.create_task(binance_prices.price_worker())


@app.on_event("shutdown")
async def shutdown():
    from core import client as _c
    _c.close()


@app.get("/api/")
async def root():
    return {"message": "FozPay clone API", "status": True}


for r in (auth_router, cab, pub, priv, rec, admin_router, sec_router, hotw):
    app.include_router(r)

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=[os.environ.get("FRONTEND_URL", "*")] if os.environ.get("FRONTEND_URL") else ["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)
