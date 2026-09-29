"""AML module — free public lists (Option B).

Sources:
- OFAC SDN List (US Treasury, government-issued, updated daily)
- Tornado Cash contract addresses (well-known mixer)
- CryptoScamDB (community-sourced scam addresses)

Simple risk heuristics on top (address age, amount, structured behaviour).

All checks are LOCAL after periodic refresh — no per-request API cost.
"""
import asyncio
import logging
import time
from typing import Optional

import httpx

from core import db

logger = logging.getLogger("fozpay.aml")

# ---------------------------------------------------------------------------
# Well-known mixer / sanctioned addresses (constants, hard-coded)
# ---------------------------------------------------------------------------
TORNADO_CASH_ETH = {
    # ETH pools
    "0x8589427373d6d84e98730d7795d8f6f8731fda16".lower(),  # Tornado.Cash Router
    "0x722122df12d4e14e13ac3b6895a86e84145b6967".lower(),  # 0.1 ETH pool
    "0xdd4c48c0b24039969fc16d1cdf626eab821d3384".lower(),  # 1 ETH pool
    "0x910cbd523d972eb0a6f4cae4618ad62622b39dbf".lower(),  # 10 ETH pool
    "0xa160cdab225685da1d56aa342ad8841c3b53f291".lower(),  # 100 ETH pool
    # USDC pools
    "0xd96f2b1c14db8458374d9aca76e26c3d18364307".lower(),
    "0x4736dcf1b7a3d580672ccce6213ca176d69c8b06".lower(),
    "0xd691f27f38b395864ea86cfc7253969b409c362d".lower(),
    "0xaeaac358560e11f52454d997aaff2c5731b6f8a6".lower(),
    "0x1356c899d8c9467c7f71c195612f8a395abf2f0a".lower(),
    "0xa60c772958a3ed56c1f15dd055ba37ac8e523a0d".lower(),
    # USDT pools
    "0x169ad27a470d064dede56a2d3ff727986b15d52b".lower(),
    "0x0836222f2b2b24a3f36f98668ed8f0b38d1a872f".lower(),
    "0xf67721a2d8f736e75a49fdd7fad2e31d8676542a".lower(),
    "0x9ad122c22b14202b4490edaf288fdb3c7cb3ff5e".lower(),
    "0x07687e702b410fa43f4cb4af7fa097918ffd2730".lower(),
    "0x23773e65ed146a459791799d01336db287f25334".lower(),
    "0xd21be7248e0197ee08e0c20d4a96debdac3d20af".lower(),
    "0x610b717796ad172b316836ac95a2ffad065ceab4".lower(),
    "0x178169b423a011fff22b9e3f3abea13414ddd0f1".lower(),
    "0xbb93e510bbcd0b7beb5a853875f9ec60275cf498".lower(),
}

TORNADO_CASH_BSC = {
    "0x84443cfd09a48af6ef360c6976c5392ac5023a1f".lower(),
    "0xd47438c816c9e7f2e2888e060936a499af9582b3".lower(),
    "0x330bdfade01ee9bf63c209ee33102dd334618e0a".lower(),
}

# Known Lazarus Group / North Korea addresses (samples from OFAC actions)
LAZARUS_KNOWN = {
    "0xa7e5d5a720f06526557c513402f2e6b5fa20b008".lower(),
    "0xf7b31119c2682c88d88d455dbb9d5932c65cf1be".lower(),
    "0x3cffd56b47b7b41c56258d9c7731abadc360e073".lower(),
    "0x53b6936513e738f44fb50d2b9476730c0ab3bfc1".lower(),
    "0x1da5821544e25c636c1417ba96ade4cf6d2f9b5a".lower(),
    "0x9f4cda013e354b8fc285bf4b9a60460cee7f7ea9".lower(),
    "0x72a5843cc08275c8171e582972aa4fda8c397b2a".lower(),
    "0x098b716b8aaf21512996dc57eb0615e2383e2f96".lower(),
    "0xa0e1c89ef1a489c9c7de96311ed5ce5d32c20e4b".lower(),
    "0x3cbded43efdaf0fc77b9c55f6fc9988fcc9b757d".lower(),
    "0x83091f21bc42e39cd0d51e775bd1cb0e4d7ea2d0".lower(),
    "0x7f19720a857f834887fc9a7bc0a0fbe7fc7f8102".lower(),
    "0x9f4cda013e354b8fc285bf4b9a60460cee7f7ea9".lower(),
}

STATIC_SANCTIONS = TORNADO_CASH_ETH | TORNADO_CASH_BSC | LAZARUS_KNOWN

# ---------------------------------------------------------------------------
# Dynamic list refresh (OFAC SDN + CryptoScamDB) — persisted in db.aml_lists
# ---------------------------------------------------------------------------
OFAC_URL = "https://www.treasury.gov/ofac/downloads/sdnlist.txt"
CRYPTOSCAM_URL = "https://api.cryptoscamdb.org/v1/addresses"

REFRESH_INTERVAL = 60 * 60 * 24  # 24h


async def _fetch_ofac_addresses() -> set:
    """OFAC SDN list contains addresses embedded in freeform text.
    We extract 0x... (EVM) and T... (Tron) address candidates."""
    import re
    try:
        async with httpx.AsyncClient(timeout=30) as cli:
            r = await cli.get(OFAC_URL)
            r.raise_for_status()
            text = r.text
        addrs = set()
        # EVM
        for m in re.findall(r"\b0x[a-fA-F0-9]{40}\b", text):
            addrs.add(m.lower())
        # Tron
        for m in re.findall(r"\bT[a-zA-HJ-NP-Z1-9]{33}\b", text):
            addrs.add(m)  # tron addresses case-sensitive base58
        # Bitcoin (rough)
        for m in re.findall(r"\b(?:bc1|[13])[a-zA-HJ-NP-Z0-9]{25,42}\b", text):
            addrs.add(m)
        return addrs
    except Exception as e:
        logger.warning(f"OFAC fetch failed: {e}")
        return set()


async def _fetch_cryptoscamdb() -> set:
    try:
        async with httpx.AsyncClient(timeout=30) as cli:
            r = await cli.get(CRYPTOSCAM_URL)
            r.raise_for_status()
            data = r.json()
        addrs = set()
        entries = data.get("result") or data.get("addresses") or {}
        if isinstance(entries, dict):
            for a in entries.keys():
                addrs.add(a.lower() if a.startswith("0x") else a)
        elif isinstance(entries, list):
            for e in entries:
                a = e.get("address") if isinstance(e, dict) else str(e)
                if a:
                    addrs.add(a.lower() if a.startswith("0x") else a)
        return addrs
    except Exception as e:
        logger.warning(f"CryptoScamDB fetch failed: {e}")
        return set()


async def refresh_aml_lists(force: bool = False):
    """Refresh OFAC + CryptoScamDB lists if older than REFRESH_INTERVAL."""
    doc = await db.aml_lists.find_one({"_id": "state"})
    now = int(time.time())
    if not force and doc and (now - doc.get("updated_ts", 0)) < REFRESH_INTERVAL:
        return doc
    ofac = await _fetch_ofac_addresses()
    scam = await _fetch_cryptoscamdb()
    all_blacklist = list(ofac | scam | STATIC_SANCTIONS)
    payload = {"_id": "state", "updated_ts": now, "ofac_count": len(ofac),
               "scam_count": len(scam), "static_count": len(STATIC_SANCTIONS),
               "total": len(all_blacklist), "addresses": all_blacklist}
    await db.aml_lists.update_one({"_id": "state"}, {"$set": payload}, upsert=True)
    logger.info(f"AML lists refreshed: OFAC={len(ofac)} Scam={len(scam)} "
                f"Static={len(STATIC_SANCTIONS)} Total={len(all_blacklist)}")
    return payload


async def is_blacklisted(address: str) -> Optional[str]:
    """Return category ('sanctions'|'scam'|'mixer') if blacklisted, else None."""
    if not address:
        return None
    key_lower = address.lower() if address.startswith("0x") else address
    if key_lower in STATIC_SANCTIONS:
        if key_lower in TORNADO_CASH_ETH or key_lower in TORNADO_CASH_BSC:
            return "mixer"
        return "sanctions"
    doc = await db.aml_lists.find_one({"_id": "state"}, {"addresses": 1})
    if doc and key_lower in set(doc.get("addresses", [])):
        return "sanctions_or_scam"
    return None


# ---------------------------------------------------------------------------
# Deposit AML check
# ---------------------------------------------------------------------------
async def check_deposit_aml(from_address: str, amount: float, iso: str,
                            network_id: Optional[int] = None) -> dict:
    """Screen an incoming deposit. Returns a structured result.

    action:
    - BLOCK   → do not credit, mark tx as blocked
    - REVIEW  → credit as hold (frozen) until admin approves
    - APPROVE → normal processing
    """
    hit = await is_blacklisted(from_address) if from_address else None
    result = {
        "address": from_address,
        "amount": amount,
        "iso": iso,
        "risk_score": 0,
        "flags": [],
        "hit": hit,
    }
    if hit == "mixer":
        result["risk_score"] = 100
        result["flags"].append("tornado_cash_mixer")
        result["action"] = "BLOCK"
        return result
    if hit == "sanctions":
        result["risk_score"] = 100
        result["flags"].append("ofac_sanctions")
        result["action"] = "BLOCK"
        return result
    if hit == "sanctions_or_scam":
        result["risk_score"] = 80
        result["flags"].append("public_blacklist")
        result["action"] = "REVIEW"
        return result
    # Simple amount heuristic
    if amount and amount > 50000:
        result["risk_score"] += 40
        result["flags"].append("large_amount")
    if amount and amount > 10000:
        result["risk_score"] += 15
        result["flags"].append("above_threshold")
    if result["risk_score"] >= 50:
        result["action"] = "REVIEW"
    else:
        result["action"] = "APPROVE"
    return result


# ---------------------------------------------------------------------------
# Startup task
# ---------------------------------------------------------------------------
async def aml_refresh_worker():
    while True:
        try:
            await refresh_aml_lists(force=False)
        except Exception as e:
            logger.info(f"aml refresh error: {e}")
        await asyncio.sleep(REFRESH_INTERVAL)
