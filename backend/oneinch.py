"""1inch Swap API v6 client — quote + approve + swap execution (EVM)."""
import os
import time
import requests
from web3 import Web3

ONEINCH_KEY = os.environ.get("ONEINCH_KEY", "")
BASE = "https://api.1inch.dev/swap/v6.0"
NATIVE = Web3.to_checksum_address("0x" + "e" * 40)  # 1inch native sentinel

CHAIN_ID = {"ethereum": 1, "polygon": 137, "bsc": 56, "arbitrum": 42161}

ERC20_ABI = [
    {"constant": True, "inputs": [{"name": "_owner", "type": "address"}],
     "name": "balanceOf", "outputs": [{"name": "", "type": "uint256"}], "type": "function"},
]


def _headers():
    return {"Authorization": f"Bearer {ONEINCH_KEY}", "Accept": "application/json"}


def _get(chain_id, path, params=None):
    r = requests.get(f"{BASE}/{chain_id}/{path}", params=params or {}, headers=_headers(), timeout=25)
    if r.status_code >= 400:
        raise RuntimeError(f"1inch {path} {r.status_code}: {r.text[:200]}")
    return r.json()


def quote(chain, src, dst, amount_base):
    cid = CHAIN_ID[chain]
    return _get(cid, "quote", {"src": src, "dst": dst, "amount": str(amount_base), "includeGas": "true"})


def _send(w3, acct, payload, chain_id):
    tx = {
        "to": Web3.to_checksum_address(payload["to"]),
        "data": payload["data"],
        "value": int(payload.get("value", 0)),
        "nonce": w3.eth.get_transaction_count(acct.address, "pending"),
        "chainId": chain_id,
    }
    tx["gas"] = int(payload["gas"]) if payload.get("gas") else int(w3.eth.estimate_gas({**tx, "from": acct.address}))
    tx["gasPrice"] = int(payload.get("gasPrice") or w3.eth.gas_price)
    signed = acct.sign_transaction(tx)
    return w3.eth.send_raw_transaction(signed.rawTransaction).hex()


def execute_swap(w3, privkey, chain, src, dst, amount_base, slippage=1):
    """src/dst = token contract or NATIVE. Handles ERC-20 approval then swap. Returns tx hashes."""
    cid = CHAIN_ID[chain]
    acct = w3.eth.account.from_key(privkey)
    owner = acct.address
    result = {"approval": None, "swap": None}
    # approval for ERC-20 src
    if src != NATIVE:
        sp = _get(cid, "approve/spender")["address"]
        allow = int(_get(cid, "approve/allowance", {"tokenAddress": src, "walletAddress": owner})["allowance"])
        if allow < int(amount_base):
            appr = _get(cid, "approve/transaction", {"tokenAddress": src, "amount": str(amount_base)})
            h = _send(w3, acct, appr, cid)
            result["approval"] = h
            w3.eth.wait_for_transaction_receipt(h, timeout=180)
    swap = _get(cid, "swap", {"src": src, "dst": dst, "amount": str(amount_base),
                              "from": owner, "slippage": str(slippage), "disableEstimate": "false"})
    result["swap"] = _send(w3, acct, swap["tx"], cid)
    return result
