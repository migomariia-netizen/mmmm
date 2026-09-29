"""Admin router for FozPay platform-level settings.

Adds:
- Platform fee settings (superadmin only): deposit fee, withdrawal fee (cabinet & API)
- Network on/off toggles (superadmin only)
- 2FA (Google Authenticator) enrollment/verify for any user
"""
import io
import base64
import logging
from typing import Optional

import pyotp
import qrcode
from fastapi import APIRouter, HTTPException, Request, Body
from pydantic import BaseModel

from core import db, get_current_user
from catalog import NETWORKS, CURRENCIES

logger = logging.getLogger("fozpay.admin")

admin_router = APIRouter(prefix="/api/admin")
sec_router = APIRouter(prefix="/api/security")

# ---------------------------------------------------------------------------
# Helpers: platform settings
# ---------------------------------------------------------------------------
DEFAULT_PLATFORM = {
    "_id": "platform_settings",
    "deposit_fee": 0.5,               # legacy global fallback (in incoming currency units)
    # per-currency deposit fee (in the units of the incoming currency)
    "deposit_fee_by_iso": {
        "USDT": 0.5, "USDC": 0.5,
        "BTC": 0.00001, "ETH": 0.0002, "BNB": 0.001,
        "TRX": 1.0, "SOL": 0.005, "LTC": 0.005,
    },
    "withdrawal_fee_cabinet": 1.0,    # flat, added on top of user amount for direct-cabinet withdrawals
    "withdrawal_fee_api": 0.8,        # flat, for API-driven withdrawals (merchant integrations)
    # per-currency swap/exchange fee in PERCENT (applied on the source currency being swapped)
    "swap_fee_by_iso": {
        "USDT": 0.4, "USDC": 0.4, "BTC": 0.4, "ETH": 0.4,
        "BNB": 0.4, "TRX": 0.4, "SOL": 0.4, "LTC": 0.4,
    },
    # per-(currency:network) withdrawal fee override. key "ISO:network_id" ->
    # {"cabinet": x, "api": y}. Falls back to the global withdrawal_fee_* below.
    "withdrawal_fee_by_key": {},
    # pool broken down by iso -> network_id -> amount (so we know which chain the funds sit on)
    "pool_by_key": {},
    # per-chain treasury addresses (EVM taken from env TREASURY_EVM; here we store TRON/SOL/BTC/LTC + overrides)
    "treasury_addresses": {
        "ethereum": "", "bsc": "", "polygon": "", "arbitrum": "",  # EVM (default from env if empty)
        "tron": "", "solana": "", "bitcoin": "", "litecoin": "",
    },
}

DEFAULT_NETWORKS_DOC_ID = "network_settings"


async def get_platform_settings() -> dict:
    s = await db.system.find_one({"_id": "platform_settings"})
    if not s:
        await db.system.insert_one(dict(DEFAULT_PLATFORM))
        s = dict(DEFAULT_PLATFORM)
    # ensure all keys exist (schema evolution)
    for k, v in DEFAULT_PLATFORM.items():
        if k == "_id":
            continue
        if k not in s:
            s[k] = v
        elif isinstance(v, dict):
            for kk, vv in v.items():
                s.setdefault(k, {}).setdefault(kk, vv)
    # inject env EVM treasury as default if not overridden
    import os as _os
    env_evm = _os.environ.get("TREASURY_EVM", "").strip()
    if env_evm:
        for chain in ("ethereum", "bsc", "polygon", "arbitrum"):
            if not s["treasury_addresses"].get(chain):
                s["treasury_addresses"][chain] = env_evm
    return s


async def update_platform_settings(patch: dict) -> dict:
    await db.system.update_one({"_id": "platform_settings"},
                               {"$set": patch}, upsert=True)
    return await get_platform_settings()


def deposit_fee_for(settings: dict, iso: str) -> float:
    """Комісія платформи на вхід (депозит) для конкретної валюти.
    Якщо для валюти окремо не задано — використовує глобальне значення deposit_fee."""
    iso = (iso or "").upper()
    by = settings.get("deposit_fee_by_iso") or {}
    val = by.get(iso)
    if val is not None:
        try:
            return float(val)
        except (TypeError, ValueError):
            pass
    return float(settings.get("deposit_fee") or 0.0)


def swap_fee_percent_for(settings: dict, iso: str) -> float:
    """Комісія платформи при свопі (у відсотках) для конкретної валюти-джерела.
    Якщо не задано — 0.4% за замовчуванням."""
    iso = (iso or "").upper()
    by = settings.get("swap_fee_by_iso") or {}
    val = by.get(iso)
    if val is not None:
        try:
            return float(val)
        except (TypeError, ValueError):
            pass
    return 0.4


def withdrawal_fee_for(settings: dict, iso: str, network_id, src: str = "cabinet") -> float:
    """Комісія платформи на вивід для конкретної валюти+мережі та каналу (cabinet/api).
    Якщо для пари ISO:network окремо не задано — fallback на глобальну комісію."""
    iso = (iso or "").upper()
    by = settings.get("withdrawal_fee_by_key") or {}
    row = by.get(f"{iso}:{network_id}")
    if row and row.get(src) is not None:
        try:
            return float(row[src])
        except (TypeError, ValueError):
            pass
    glob = settings.get("withdrawal_fee_api") if src == "api" else settings.get("withdrawal_fee_cabinet")
    return float(glob or 0.0)


def withdrawal_matrix(settings: dict) -> list:
    """Full list of every currency+network withdrawal-fee cell with the effective
    values (custom override or global fallback). Drives the admin UI."""
    by = settings.get("withdrawal_fee_by_key") or {}
    glob_cab = float(settings.get("withdrawal_fee_cabinet") or 0.0)
    glob_api = float(settings.get("withdrawal_fee_api") or 0.0)
    out = []
    for iso, c in CURRENCIES.items():
        for nid in c["networks"]:
            key = f"{iso}:{nid}"
            row = by.get(key) or {}
            out.append({
                "key": key, "iso": iso, "network_id": nid,
                "network_name": NETWORKS.get(nid, {}).get("name", str(nid)),
                "network_iso": NETWORKS.get(nid, {}).get("iso", ""),
                "cabinet": float(row["cabinet"]) if row.get("cabinet") is not None else glob_cab,
                "api": float(row["api"]) if row.get("api") is not None else glob_api,
                "custom": bool(row),
            })
    return out


async def add_to_pool(iso: str, amount: float, network_id=None):
    if not amount:
        return
    key = f"{iso}:{network_id}" if network_id is not None else f"{iso}:_"
    await db.system.update_one(
        {"_id": "platform_settings"},
        {"$inc": {f"pool_by_key.{key}": float(amount)}},
        upsert=True,
    )


async def get_network_settings() -> dict:
    s = await db.system.find_one({"_id": DEFAULT_NETWORKS_DOC_ID})
    if not s:
        s = {"_id": DEFAULT_NETWORKS_DOC_ID,
             "enabled": {str(nid): True for nid in NETWORKS.keys()}}
        await db.system.insert_one(dict(s))
    # ensure all network ids present with default True
    changed = False
    for nid in NETWORKS.keys():
        if str(nid) not in s.get("enabled", {}):
            s.setdefault("enabled", {})[str(nid)] = True
            changed = True
    if changed:
        await db.system.update_one({"_id": DEFAULT_NETWORKS_DOC_ID},
                                   {"$set": {"enabled": s["enabled"]}}, upsert=True)
    return s


async def is_network_enabled(network_id) -> bool:
    if network_id is None:
        return True
    s = await get_network_settings()
    return bool(s.get("enabled", {}).get(str(network_id), True))


# ---------------------------------------------------------------------------
# 2FA helpers
# ---------------------------------------------------------------------------
def _generate_qr_data_url(otpauth_uri: str) -> str:
    img = qrcode.make(otpauth_uri)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


async def check_user_2fa(user: dict, otp: Optional[str]) -> bool:
    """If user has 2FA enabled, validate the OTP. Returns True if OK / not enabled."""
    tf = (user or {}).get("two_fa") or {}
    if not tf.get("enabled"):
        return True
    if not otp:
        return False
    return pyotp.TOTP(tf.get("secret", "")).verify(str(otp).replace(" ", ""), valid_window=1)


# ---------------------------------------------------------------------------
# Authorization guard
# ---------------------------------------------------------------------------
async def _require_superadmin(request: Request) -> dict:
    user = await get_current_user(request)
    if user.get("role") != "admin":
        raise HTTPException(403, "Тільки для суперадміністратора FozPay")
    return user


# ---------------------------------------------------------------------------
# Platform fee endpoints
# ---------------------------------------------------------------------------
class PlatformFeesIn(BaseModel):
    deposit_fee: Optional[float] = None
    deposit_fee_by_iso: Optional[dict] = None
    swap_fee_by_iso: Optional[dict] = None
    withdrawal_fee_by_key: Optional[dict] = None
    withdrawal_fee_cabinet: Optional[float] = None
    withdrawal_fee_api: Optional[float] = None
    otp: Optional[str] = None


@admin_router.get("/platform-fees")
async def platform_fees_get(request: Request):
    user = await _require_superadmin(request)
    s = await get_platform_settings()
    s.pop("_id", None)
    s["withdrawal_fee_matrix"] = withdrawal_matrix(s)
    return {"status": True, "data": s}


@admin_router.put("/platform-fees")
async def platform_fees_put(request: Request, payload: PlatformFeesIn):
    user = await _require_superadmin(request)
    # 2FA gate for critical settings (if admin enabled it)
    if (user.get("two_fa") or {}).get("enabled"):
        if not await check_user_2fa(user, payload.otp):
            raise HTTPException(401, "Потрібен коректний код 2FA")
    patch = {}
    if payload.deposit_fee is not None:
        if payload.deposit_fee < 0:
            raise HTTPException(400, "Комісія не може бути від'ємною")
        patch["deposit_fee"] = float(payload.deposit_fee)
    if payload.deposit_fee_by_iso is not None:
        cur = await get_platform_settings()
        merged = dict(cur.get("deposit_fee_by_iso") or {})
        for iso, val in payload.deposit_fee_by_iso.items():
            iso = str(iso).upper()
            if iso not in CURRENCIES:
                raise HTTPException(400, f"Невідома валюта: {iso}")
            try:
                fval = float(val)
            except (TypeError, ValueError):
                raise HTTPException(400, f"Некоректна комісія для {iso}")
            if fval < 0:
                raise HTTPException(400, "Комісія не може бути від'ємною")
            merged[iso] = fval
        patch["deposit_fee_by_iso"] = merged
    if payload.swap_fee_by_iso is not None:
        cur = await get_platform_settings()
        merged = dict(cur.get("swap_fee_by_iso") or {})
        for iso, val in payload.swap_fee_by_iso.items():
            iso = str(iso).upper()
            if iso not in CURRENCIES:
                raise HTTPException(400, f"Невідома валюта: {iso}")
            try:
                fval = float(val)
            except (TypeError, ValueError):
                raise HTTPException(400, f"Некоректна комісія свопу для {iso}")
            if fval < 0 or fval > 100:
                raise HTTPException(400, "Комісія свопу має бути в межах 0–100%")
            merged[iso] = fval
        patch["swap_fee_by_iso"] = merged
    if payload.withdrawal_fee_cabinet is not None:
        if payload.withdrawal_fee_cabinet < 0:
            raise HTTPException(400, "Комісія не може бути від'ємною")
        patch["withdrawal_fee_cabinet"] = float(payload.withdrawal_fee_cabinet)
    if payload.withdrawal_fee_api is not None:
        if payload.withdrawal_fee_api < 0:
            raise HTTPException(400, "Комісія не може бути від'ємною")
        patch["withdrawal_fee_api"] = float(payload.withdrawal_fee_api)
    if payload.withdrawal_fee_by_key is not None:
        cur = await get_platform_settings()
        merged = dict(cur.get("withdrawal_fee_by_key") or {})
        for key, row in payload.withdrawal_fee_by_key.items():
            if not isinstance(row, dict):
                continue
            entry = dict(merged.get(key) or {})
            for chan in ("cabinet", "api"):
                if row.get(chan) is not None:
                    try:
                        fval = float(row[chan])
                    except (TypeError, ValueError):
                        raise HTTPException(400, f"Некоректна комісія для {key}")
                    if fval < 0:
                        raise HTTPException(400, "Комісія не може бути від'ємною")
                    entry[chan] = fval
            if entry:
                merged[key] = entry
        patch["withdrawal_fee_by_key"] = merged
    s = await update_platform_settings(patch)
    s.pop("_id", None)
    s["withdrawal_fee_matrix"] = withdrawal_matrix(s)
    return {"status": True, "data": s}


# Public read-only view for merchants/users (they need to know cabinet fee at least)
@admin_router.get("/platform-fees/public")
async def platform_fees_public(request: Request):
    await get_current_user(request)
    s = await get_platform_settings()
    return {"status": True, "data": {
        "deposit_fee": s["deposit_fee"],
        "deposit_fee_by_iso": s.get("deposit_fee_by_iso", {}),
        "swap_fee_by_iso": s.get("swap_fee_by_iso", {}),
        "withdrawal_fee_cabinet": s["withdrawal_fee_cabinet"],
        "withdrawal_fee_api": s["withdrawal_fee_api"],
        "withdrawal_fee_by_key": s.get("withdrawal_fee_by_key", {}),
        "withdrawal_fee_matrix": withdrawal_matrix(s),
    }}


# ---------------------------------------------------------------------------
# Treasury addresses (per chain) and pool withdrawal
# ---------------------------------------------------------------------------
CHAIN_LABELS = {
    "ethereum": "Ethereum (ERC20)",
    "bsc": "BSC (BEP20)",
    "polygon": "Polygon",
    "arbitrum": "Arbitrum",
    "tron": "Tron (TRC20)",
    "solana": "Solana",
    "bitcoin": "Bitcoin",
    "litecoin": "Litecoin",
}


class TreasuryIn(BaseModel):
    addresses: dict  # {chain: address, ...}
    otp: Optional[str] = None


@admin_router.get("/treasury-addresses")
async def treasury_get(request: Request):
    user = await _require_superadmin(request)
    s = await get_platform_settings()
    return {"status": True, "data": {
        "addresses": s.get("treasury_addresses", {}),
        "labels": CHAIN_LABELS,
    }}


@admin_router.put("/treasury-addresses")
async def treasury_put(request: Request, payload: TreasuryIn):
    user = await _require_superadmin(request)
    if (user.get("two_fa") or {}).get("enabled"):
        if not await check_user_2fa(user, payload.otp):
            raise HTTPException(401, "Потрібен коректний код 2FA")
    # normalize & sanity check
    addr_patch = {}
    for chain, addr in (payload.addresses or {}).items():
        if chain not in CHAIN_LABELS:
            continue
        addr = (addr or "").strip()
        addr_patch[f"treasury_addresses.{chain}"] = addr
    if addr_patch:
        await db.system.update_one({"_id": "platform_settings"},
                                   {"$set": addr_patch}, upsert=True)
    s = await get_platform_settings()
    return {"status": True, "data": s.get("treasury_addresses", {})}


# Show pool broken down per iso+network
@admin_router.get("/pool")
async def pool_get(request: Request):
    user = await _require_superadmin(request)
    s = await get_platform_settings()
    pool = s.get("pool_by_key", {}) or {}
    treasury = s.get("treasury_addresses", {}) or {}
    items = []
    for key, amount in pool.items():
        try:
            iso, nid_str = key.split(":", 1)
            nid = int(nid_str) if nid_str != "_" else None
        except Exception:
            continue
        net = NETWORKS.get(nid, {}) if nid is not None else {}
        chain = net.get("chain")
        tres_addr = treasury.get(chain, "") if chain else ""
        items.append({
            "key": key,
            "iso": iso,
            "network_id": nid,
            "network_name": net.get("name") or "—",
            "chain": chain or "—",
            "amount": float(amount or 0),
            "treasury_address": tres_addr,
            "withdrawable": bool(tres_addr) and float(amount or 0) > 0,
        })
    items.sort(key=lambda x: (x["chain"], x["iso"]))
    return {"status": True, "data": items}


class PoolWithdrawIn(BaseModel):
    key: str  # "USDT:2"
    otp: Optional[str] = None


@admin_router.post("/pool/withdraw")
async def pool_withdraw(request: Request, payload: PoolWithdrawIn):
    user = await _require_superadmin(request)
    if (user.get("two_fa") or {}).get("enabled"):
        if not await check_user_2fa(user, payload.otp):
            raise HTTPException(401, "Потрібен коректний код 2FA")
    s = await get_platform_settings()
    pool = s.get("pool_by_key", {}) or {}
    amount = float(pool.get(payload.key, 0) or 0)
    if amount <= 0:
        raise HTTPException(400, "Немає коштів у пулі за цим ключем")
    try:
        iso, nid_str = payload.key.split(":", 1)
        nid = int(nid_str) if nid_str != "_" else None
    except Exception:
        raise HTTPException(400, "Невірний ключ пулу")
    net = NETWORKS.get(nid, {}) if nid is not None else {}
    chain = net.get("chain")
    treasury = (s.get("treasury_addresses") or {}).get(chain, "")
    if not treasury:
        raise HTTPException(400, f"Не задано treasury-адресу для мережі {chain or '?'}. Спочатку налаштуйте у розділі Платформа → Гаманці.")
    # Reset the pool entry (accounting) and record a pending platform_withdrawal transaction.
    # Actual on-chain send is performed by the platform operator using the hot-wallet private key
    # (or via the sweep worker in a future iteration).
    await db.system.update_one(
        {"_id": "platform_settings"},
        {"$unset": {f"pool_by_key.{payload.key}": ""}},
    )
    tx = {
        "tx_id": __import__("uuid").uuid4().hex[:12],
        "user_id": "platform",
        "type": "platform_fee_withdraw",
        "iso": iso,
        "network_id": nid,
        "amount": round(amount, 8),
        "fee": 0,
        "fee_iso": iso,
        "gross_amount": round(amount, 8),
        "usd_value": 0,
        "status": "Pending",
        "address": treasury,
        "txid": None,
        "description": f"Platform fee → treasury ({chain})",
        "order_id": None,
        "invoice_id": None,
        "created_ts": int(__import__("time").time()),
        "created_at": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat(),
        "source": "platform",
    }
    await db.transactions.insert_one(dict(tx))
    tx.pop("_id", None)
    logger.info(f"Platform pool withdraw queued: {amount} {iso} @{chain} → {treasury}")
    return {"status": True, "data": {"transaction": tx, "amount": amount, "iso": iso,
                                     "chain": chain, "treasury": treasury,
                                     "note": "Заявку створено. Фізичний on-chain переказ виконується оператором вручну або воркером свипу."}}


# List platform fee transactions (superadmin view)
@admin_router.get("/pool/history")
async def pool_history(request: Request):
    user = await _require_superadmin(request)
    txs = await db.transactions.find(
        {"user_id": "platform"}, {"_id": 0}
    ).sort("created_ts", -1).to_list(200)
    return {"status": True, "data": txs}


# ---------------------------------------------------------------------------
# Network toggle endpoints
# ---------------------------------------------------------------------------
class NetworkToggleIn(BaseModel):
    network_id: int
    enabled: bool
    otp: Optional[str] = None


@admin_router.get("/networks")
async def networks_get(request: Request):
    user = await _require_superadmin(request)
    s = await get_network_settings()
    items = []
    for nid, meta in NETWORKS.items():
        items.append({
            "network_id": nid,
            "name": meta.get("name"),
            "chain": meta.get("chain"),
            "iso": meta.get("iso"),
            "enabled": bool(s["enabled"].get(str(nid), True)),
        })
    return {"status": True, "data": items}


@admin_router.put("/networks")
async def networks_put(request: Request, payload: NetworkToggleIn):
    user = await _require_superadmin(request)
    if (user.get("two_fa") or {}).get("enabled"):
        if not await check_user_2fa(user, payload.otp):
            raise HTTPException(401, "Потрібен коректний код 2FA")
    if payload.network_id not in NETWORKS:
        raise HTTPException(400, "Невідома мережа")
    await db.system.update_one(
        {"_id": DEFAULT_NETWORKS_DOC_ID},
        {"$set": {f"enabled.{payload.network_id}": bool(payload.enabled)}},
        upsert=True,
    )
    s = await get_network_settings()
    return {"status": True, "data": {"network_id": payload.network_id,
                                     "enabled": bool(s["enabled"].get(str(payload.network_id), True))}}


# Public: all users need to know which networks are active for UI selection
@admin_router.get("/networks/public")
async def networks_public(request: Request):
    await get_current_user(request)
    s = await get_network_settings()
    return {"status": True, "data": {str(nid): bool(s["enabled"].get(str(nid), True))
                                     for nid in NETWORKS.keys()}}


# ---------------------------------------------------------------------------
# 2FA endpoints (any authenticated user)
# ---------------------------------------------------------------------------
class OtpIn(BaseModel):
    otp: str


@sec_router.get("/2fa/status")
async def twofa_status(request: Request):
    user = await get_current_user(request)
    tf = user.get("two_fa") or {}
    return {"status": True, "data": {"enabled": bool(tf.get("enabled"))}}


@sec_router.post("/2fa/setup")
async def twofa_setup(request: Request):
    """Generate a new pending secret + QR code. Not yet enabled."""
    user = await get_current_user(request)
    secret = pyotp.random_base32()
    label = user.get("email", user["user_id"])
    otpauth = pyotp.totp.TOTP(secret).provisioning_uri(name=label, issuer_name="FozPay")
    qr = _generate_qr_data_url(otpauth)
    await db.users.update_one(
        {"user_id": user["user_id"]},
        {"$set": {"two_fa.pending_secret": secret}}
    )
    return {"status": True, "data": {"secret": secret, "otpauth_uri": otpauth,
                                     "qr_data_url": qr}}


@sec_router.post("/2fa/enable")
async def twofa_enable(request: Request, payload: OtpIn):
    user = await get_current_user(request)
    pending = ((user.get("two_fa") or {}).get("pending_secret")) or ""
    if not pending:
        raise HTTPException(400, "Спочатку виконайте setup")
    ok = pyotp.TOTP(pending).verify(str(payload.otp).replace(" ", ""), valid_window=1)
    if not ok:
        raise HTTPException(400, "Невірний код")
    await db.users.update_one(
        {"user_id": user["user_id"]},
        {"$set": {"two_fa.enabled": True, "two_fa.secret": pending},
         "$unset": {"two_fa.pending_secret": ""}}
    )
    return {"status": True, "message": "2FA увімкнено"}


@sec_router.post("/2fa/disable")
async def twofa_disable(request: Request, payload: OtpIn):
    user = await get_current_user(request)
    tf = user.get("two_fa") or {}
    if not tf.get("enabled"):
        return {"status": True, "message": "2FA не активна"}
    ok = pyotp.TOTP(tf.get("secret", "")).verify(str(payload.otp).replace(" ", ""), valid_window=1)
    if not ok:
        raise HTTPException(400, "Невірний код")
    await db.users.update_one(
        {"user_id": user["user_id"]},
        {"$set": {"two_fa.enabled": False},
         "$unset": {"two_fa.secret": "", "two_fa.pending_secret": ""}}
    )
    return {"status": True, "message": "2FA вимкнено"}
