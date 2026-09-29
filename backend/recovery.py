"""Live mainnet detection + sweep (wrong-network recovery) for EVM chains,
plus read-only detection for TRON and Bitcoin."""
import os
import requests
from web3 import Web3

from catalog import PRICES_USD

ALCHEMY_KEY = os.environ.get("ALCHEMY_KEY", "")
TRONGRID_KEY = os.environ.get("TRONGRID_KEY", "")
MEMPOOL_API = os.environ.get("MEMPOOL_API", "https://mempool.space/api")
TREASURY_EVM = os.environ.get("TREASURY_EVM", "")

# chain -> (alchemy subdomain, network_id, native symbol, chainId)
EVM = {
    "ethereum": ("eth-mainnet", 1, "ETH", 1),
    "polygon": ("polygon-mainnet", 6, "MATIC", 137),
    "bsc": ("bnb-mainnet", 4, "BNB", 56),
    "arbitrum": ("arb-mainnet", 7, "ETH", 42161),
}

# token contracts per chain: symbol -> (address, decimals)
TOKENS = {
    "ethereum": {
        "USDT": ("0xdAC17F958D2ee523a2206206994597C13D831ec7", 6),
        "USDC": ("0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48", 6),
    },
    "polygon": {
        "USDT": ("0xc2132D05D31c914a87C6611C10748AEb04B58e8F", 6),
        "USDC": ("0x3c499c542cEF5E3811e1192ce70d8cC03d5c3359", 6),
    },
    "bsc": {
        "USDT": ("0x55d398326f99059fF775485246999027B3197955", 18),
        "USDC": ("0x8AC76a51cc950d9822D68b83fE1Ad97B32Cd580d", 18),
    },
    "arbitrum": {
        "USDT": ("0xFd086bC7CD5C481DCC9C85ebE478A1C0b69FCbb9", 6),
        "USDC": ("0xaf88d065e77c8cC2239327C5EDb3A432268e5831", 6),
    },
}

NATIVE_USD = {"ETH": PRICES_USD["ETH"], "BNB": PRICES_USD["BNB"], "MATIC": 0.52}
TOKEN_USD = {"USDT": 1.0, "USDC": 1.0}

ERC20_ABI = [
    {"constant": True, "inputs": [{"name": "_owner", "type": "address"}],
     "name": "balanceOf", "outputs": [{"name": "balance", "type": "uint256"}], "type": "function"},
    {"constant": False, "inputs": [{"name": "_to", "type": "address"}, {"name": "_value", "type": "uint256"}],
     "name": "transfer", "outputs": [{"name": "", "type": "bool"}], "type": "function"},
]


def _rpc_url(chain: str) -> str:
    sub = EVM[chain][0]
    return f"https://{sub}.g.alchemy.com/v2/{ALCHEMY_KEY}"


def _w3(chain: str) -> Web3:
    return Web3(Web3.HTTPProvider(_rpc_url(chain), request_kwargs={"timeout": 20}))


# Per-chain minimum gas price (wei) — just enough for reliable inclusion, no more.
# BSC's protocol minimum is 0.1 gwei; forcing higher wastes the gas we send to
# deposit addresses. estimate_gas from an unfunded deposit address is impossible,
# so we fund a tight, realistic gas limit (below) instead of estimating.
_GAS_PRICE_FLOOR = {"bsc": 100_000_000}  # 0.1 gwei (BSC protocol minimum)
# Realistic gas a single ERC-20 transfer consumes per chain (with a small safety
# margin). Kept tight so the gas top-up sent to a deposit address is minimal.
_TOKEN_GAS_LIMIT_BY_CHAIN = {
    "bsc": 60_000, "polygon": 80_000, "ethereum": 90_000, "arbitrum": 1_500_000,
}
_GAS_FUND_BUFFER = 1.1  # 10% headroom on the funded gas amount


def _token_gas_limit(chain: str) -> int:
    return _TOKEN_GAS_LIMIT_BY_CHAIN.get(chain, 90_000)


def _gas_price(w3: Web3, chain: str) -> int:
    return max(int(w3.eth.gas_price), _GAS_PRICE_FLOOR.get(chain, 0))


def scan_evm_address(address: str) -> list:
    """Scan a single 0x address across ALL EVM chains for native + token balances."""
    addr = Web3.to_checksum_address(address)
    out = []
    for chain, (sub, nid, native, chainid) in EVM.items():
        w3 = _w3(chain)
        try:
            wei = w3.eth.get_balance(addr)
        except Exception:
            continue
        if wei > 0:
            amt = wei / 1e18
            out.append({"address": address, "chain": chain, "network_id": nid,
                        "symbol": native, "kind": "native", "contract": None,
                        "decimals": 18, "amount": amt,
                        "usd": round(amt * NATIVE_USD.get(native, 0.0), 2)})
        for sym, (caddr, dec) in TOKENS.get(chain, {}).items():
            try:
                c = w3.eth.contract(address=Web3.to_checksum_address(caddr), abi=ERC20_ABI)
                raw = c.functions.balanceOf(addr).call()
            except Exception:
                continue
            if raw > 0:
                amt = raw / (10 ** dec)
                out.append({"address": address, "chain": chain, "network_id": nid,
                            "symbol": sym, "kind": "token", "contract": caddr,
                            "decimals": dec, "amount": amt,
                            "usd": round(amt * TOKEN_USD.get(sym, 0.0), 2)})
    return out


def scan_tron_address(address: str) -> list:
    """Read-only TRX + USDT (TRC-20) balance via TronGrid."""
    out = []
    h = {"TRON-PRO-API-KEY": TRONGRID_KEY} if TRONGRID_KEY else {}
    try:
        r = requests.get(f"https://api.trongrid.io/v1/accounts/{address}", headers=h, timeout=15)
        data = (r.json().get("data") or [{}])[0]
        trx = data.get("balance", 0) / 1e6
        if trx > 0:
            out.append({"address": address, "chain": "tron", "network_id": 2, "symbol": "TRX",
                        "kind": "native", "contract": None, "decimals": 6, "amount": trx,
                        "usd": round(trx * PRICES_USD["TRX"], 2)})
        for t in data.get("trc20", []):
            for caddr, bal in t.items():
                if caddr == "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t":  # USDT-TRC20
                    amt = int(bal) / 1e6
                    if amt > 0:
                        out.append({"address": address, "chain": "tron", "network_id": 2, "symbol": "USDT",
                                    "kind": "token", "contract": caddr, "decimals": 6, "amount": amt,
                                    "usd": round(amt, 2)})
    except Exception:
        pass
    return out


def scan_btc_address(address: str) -> list:
    try:
        r = requests.get(f"{MEMPOOL_API}/address/{address}", timeout=15)
        d = r.json()
        cs = d.get("chain_stats", {})
        sats = cs.get("funded_txo_sum", 0) - cs.get("spent_txo_sum", 0)
        amt = sats / 1e8
        if amt > 0:
            return [{"address": address, "chain": "bitcoin", "network_id": 0, "symbol": "BTC",
                     "kind": "native", "contract": None, "decimals": 8, "amount": amt,
                     "usd": round(amt * PRICES_USD["BTC"], 2)}]
    except Exception:
        pass
    return []


def sweep_evm(privkey: str, chain: str, kind: str, contract: str, to_address: str = None,
              treasury_pk: str = None) -> dict:
    """Send full balance of an EVM asset to the treasury. Auto-funds gas from treasury
    for ERC-20 token sweeps when the deposit address has no native gas."""
    to_address = to_address or TREASURY_EVM
    if not to_address:
        return {"ok": False, "error": "Treasury address not configured"}
    _, nid, native, chainid = EVM[chain]
    w3 = _w3(chain)
    acct = w3.eth.account.from_key(privkey)
    frm = acct.address
    to_cs = Web3.to_checksum_address(to_address)
    gas_price = _gas_price(w3, chain)
    gas_funded = None
    try:
        if kind == "native":
            bal = w3.eth.get_balance(frm)
            fee = 21000 * gas_price
            value = bal - fee
            if value <= 0:
                return {"ok": False, "error": "Balance too low to cover gas"}
            nonce = w3.eth.get_transaction_count(frm)
            tx = {"to": to_cs, "value": value, "gas": 21000, "gasPrice": gas_price,
                  "nonce": nonce, "chainId": chainid}
        else:
            c = w3.eth.contract(address=Web3.to_checksum_address(contract), abi=ERC20_ABI)
            raw = c.functions.balanceOf(frm).call()
            if raw <= 0:
                return {"ok": False, "error": "No token balance"}
            # The deposit address has no native gas, so estimate_gas is impossible
            # here — use a tight, realistic limit and fund exactly that from treasury.
            gas_limit = _token_gas_limit(chain)
            needed = gas_limit * gas_price
            native_bal = w3.eth.get_balance(frm)
            if native_bal < needed:
                # GAS STATION: top up from treasury (hot wallet)
                if not treasury_pk:
                    return {"ok": False, "error": f"Not enough {native} for gas. Provide treasury gas funding."}
                topup = int((needed - native_bal) * _GAS_FUND_BUFFER)
                gas_funded = _fund_gas(w3, treasury_pk, frm, topup, gas_price, chainid, native)
                if not gas_funded.get("ok"):
                    return {"ok": False, "error": "Gas funding failed: " + gas_funded.get("error", "")}
                w3.eth.wait_for_transaction_receipt(gas_funded["tx_hash"], timeout=180)
            nonce = w3.eth.get_transaction_count(frm)
            tx = c.functions.transfer(to_cs, raw).build_transaction(
                {"from": frm, "nonce": nonce, "gasPrice": gas_price, "chainId": chainid, "gas": gas_limit})
        signed = acct.sign_transaction(tx)
        h = w3.eth.send_raw_transaction(signed.rawTransaction)
        return {"ok": True, "tx_hash": h.hex(), "from": frm, "to": to_cs, "chain": chain,
                "gas_funded": gas_funded.get("tx_hash") if gas_funded else None}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def _fund_gas(w3, treasury_pk, to_addr, amount_wei, gas_price, chainid, native):
    try:
        tacct = w3.eth.account.from_key(treasury_pk)
        tbal = w3.eth.get_balance(tacct.address)
        if tbal < amount_wei + 21000 * gas_price:
            return {"ok": False, "error": f"Treasury has insufficient {native} for gas top-up"}
        tx = {"to": Web3.to_checksum_address(to_addr), "value": int(amount_wei), "gas": 21000,
              "gasPrice": gas_price, "nonce": w3.eth.get_transaction_count(tacct.address), "chainId": chainid}
        signed = tacct.sign_transaction(tx)
        h = w3.eth.send_raw_transaction(signed.rawTransaction)
        return {"ok": True, "tx_hash": h.hex()}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def treasury_privkey(seed) -> str:
    """Derive the private key controlling TREASURY_EVM from the HD seed (search first indexes)."""
    from hd_wallet import derive_evm_privkey
    from eth_account import Account
    if not TREASURY_EVM:
        return None
    for i in range(0, 12):
        pk = derive_evm_privkey(seed, i)
        if Account.from_key(pk).address.lower() == TREASURY_EVM.lower():
            return pk
    return None


def check_evm_deposit(address: str, chain: str, symbol: str) -> float:
    """Return on-chain amount of `symbol` held by `address` on `chain` (0 if none/unsupported)."""
    if chain not in EVM:
        return 0.0
    w3 = _w3(chain)
    addr = Web3.to_checksum_address(address)
    native = EVM[chain][2]
    try:
        if symbol == native:
            return w3.eth.get_balance(addr) / 1e18
        tok = TOKENS.get(chain, {}).get(symbol)
        if tok:
            c = w3.eth.contract(address=Web3.to_checksum_address(tok[0]), abi=ERC20_ABI)
            return c.functions.balanceOf(addr).call() / (10 ** tok[1])
    except Exception:
        return 0.0
    return 0.0


def check_tron_deposit(address: str, symbol: str) -> float:
    for f in scan_tron_address(address):
        if f["symbol"] == symbol:
            return f["amount"]
    return 0.0


def check_btc_deposit(address: str) -> float:
    r = scan_btc_address(address)
    return r[0]["amount"] if r else 0.0


def last_incoming_tx(address: str, chain: str, symbol: str):
    """Best-effort: fetch the most recent INCOMING tx hash for address+asset so we can
    show a clickable explorer link on deposits. Returns hash string or None."""
    try:
        if chain in EVM:
            native = EVM[chain][2]
            params = {"toAddress": Web3.to_checksum_address(address), "order": "desc",
                      "maxCount": "0x5", "excludeZeroValue": True, "withMetadata": False}
            if symbol == native:
                params["category"] = ["external"]
            else:
                tok = TOKENS.get(chain, {}).get(symbol)
                params["category"] = ["erc20"]
                if tok:
                    params["contractAddresses"] = [Web3.to_checksum_address(tok[0])]
            r = requests.post(_rpc_url(chain),
                              json={"jsonrpc": "2.0", "id": 1,
                                    "method": "alchemy_getAssetTransfers", "params": [params]},
                              timeout=20)
            transfers = (r.json().get("result") or {}).get("transfers") or []
            if transfers:
                return transfers[0].get("hash")
        elif chain == "tron":
            h = {"TRON-PRO-API-KEY": TRONGRID_KEY} if TRONGRID_KEY else {}
            if symbol == "TRX":
                r = requests.get(f"https://api.trongrid.io/v1/accounts/{address}/transactions",
                                 params={"only_to": "true", "limit": 1}, headers=h, timeout=15)
                data = r.json().get("data") or []
                if data:
                    return data[0].get("txID")
            else:
                r = requests.get(f"https://api.trongrid.io/v1/accounts/{address}/transactions/trc20",
                                 params={"only_to": "true", "limit": 1}, headers=h, timeout=15)
                data = r.json().get("data") or []
                if data:
                    return data[0].get("transaction_id")
        elif chain == "bitcoin":
            r = requests.get(f"{MEMPOOL_API}/address/{address}/txs", timeout=15)
            data = r.json() or []
            if data:
                return data[0].get("txid")
    except Exception:
        pass
    return None


def send_evm_amount(privkey: str, chain: str, iso: str, to_address: str, amount: float,
                    treasury_pk: str = None) -> dict:
    """Send a SPECIFIC `amount` of `iso` (native or ERC-20) from the wallet controlled
    by `privkey` to `to_address` on an EVM chain. Used for real withdrawals & hot-wallet payouts.
    Auto-tops-up gas from treasury for token transfers when needed."""
    if chain not in EVM:
        return {"ok": False, "error": f"{chain} не є EVM-мережею"}
    _, nid, native, chainid = EVM[chain]
    w3 = _w3(chain)
    acct = w3.eth.account.from_key(privkey)
    frm = acct.address
    to_cs = Web3.to_checksum_address(to_address)
    gas_price = _gas_price(w3, chain)
    try:
        if iso == native:
            value = int(round(amount * 1e18))
            bal = w3.eth.get_balance(frm)
            fee = 21000 * gas_price
            if bal < value + fee:
                return {"ok": False, "error": f"Недостатньо {native} на гарячому гаманці (баланс {bal/1e18:.6f})"}
            nonce = w3.eth.get_transaction_count(frm)
            tx = {"to": to_cs, "value": value, "gas": 21000, "gasPrice": gas_price,
                  "nonce": nonce, "chainId": chainid}
        else:
            tok = TOKENS.get(chain, {}).get(iso)
            if not tok:
                return {"ok": False, "error": f"{iso} не підтримується у мережі {chain}"}
            caddr, dec = tok
            c = w3.eth.contract(address=Web3.to_checksum_address(caddr), abi=ERC20_ABI)
            raw = int(round(amount * (10 ** dec)))
            have = c.functions.balanceOf(frm).call()
            if have < raw:
                return {"ok": False, "error": f"Недостатньо {iso} на гарячому гаманці (баланс {have/(10**dec):.6f})"}
            gas_limit = _token_gas_limit(chain)
            needed = gas_limit * gas_price
            if w3.eth.get_balance(frm) < needed and treasury_pk and treasury_pk != privkey:
                gf = _fund_gas(w3, treasury_pk, frm, int((needed) * _GAS_FUND_BUFFER), gas_price, chainid, native)
                if gf.get("ok"):
                    w3.eth.wait_for_transaction_receipt(gf["tx_hash"], timeout=180)
            if w3.eth.get_balance(frm) < needed:
                return {"ok": False, "error": f"Недостатньо {native} для газу на гарячому гаманці"}
            nonce = w3.eth.get_transaction_count(frm)
            tx = c.functions.transfer(to_cs, raw).build_transaction(
                {"from": frm, "nonce": nonce, "gasPrice": gas_price, "chainId": chainid, "gas": gas_limit})
        signed = acct.sign_transaction(tx)
        h = w3.eth.send_raw_transaction(signed.rawTransaction)
        return {"ok": True, "tx_hash": h.hex(), "from": frm, "to": to_cs, "chain": chain}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def hot_wallet_balances(evm_address: str, tron_address: str = None) -> list:
    """Read on-chain balances the platform hot wallet actually holds (EVM chains + TRON)."""
    out = []
    if evm_address:
        try:
            out.extend(scan_evm_address(evm_address))
        except Exception:
            pass
    if tron_address:
        try:
            out.extend(scan_tron_address(tron_address))
        except Exception:
            pass
    return out
