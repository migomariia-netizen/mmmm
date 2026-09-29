"""Currency, network catalog, prices and commission config for FozPay clone."""

# network_id -> metadata. chain = HD derivation chain key.
NETWORKS = {
    0: {"iso": "Main", "name": "Bitcoin", "chain": "bitcoin"},
    1: {"iso": "ETH", "name": "ERC 20", "chain": "ethereum"},
    2: {"iso": "TRX", "name": "TRC 20", "chain": "tron"},
    4: {"iso": "BSC", "name": "BEP 20", "chain": "bsc"},
    5: {"iso": "SOL", "name": "Solana", "chain": "solana"},
    6: {"iso": "MATIC", "name": "Polygon", "chain": "polygon"},
    7: {"iso": "ARB", "name": "Arbitrum", "chain": "arbitrum"},
    8: {"iso": "LTC", "name": "Litecoin", "chain": "litecoin"},
}

# payment (fiat) currencies for invoices
FIAT_CURRENCIES = [
    {"id": 4, "name": "Dollar", "iso3": "USD"},
    {"id": 5, "name": "Euro", "iso3": "EUR"},
    {"id": 6, "name": "Hryvnia", "iso3": "UAH"},
]

FIAT_RATES_USD = {"USD": 1.0, "EUR": 1.08, "UAH": 0.024}

# crypto currencies with allowed networks and icons
CURRENCIES = {
    "USDT": {
        "id": 1, "name": "Tether", "iso3": "USDT", "color": "#26A17B",
        "networks": [4, 2, 1, 6, 7],
    },
    "USDC": {
        "id": 2, "name": "USD Coin", "iso3": "USDC", "color": "#2775CA",
        "networks": [4, 1, 6, 7],
    },
    "BTC": {
        "id": 3, "name": "Bitcoin", "iso3": "BTC", "color": "#F7931A",
        "networks": [0],
    },
    "ETH": {
        "id": 4, "name": "Ethereum", "iso3": "ETH", "color": "#627EEA",
        "networks": [1, 7],
    },
    "BNB": {
        "id": 5, "name": "BNB", "iso3": "BNB", "color": "#F3BA2F",
        "networks": [4],
    },
    "TRX": {
        "id": 6, "name": "Tron", "iso3": "TRX", "color": "#FF0013",
        "networks": [2],
    },
    "SOL": {
        "id": 7, "name": "Solana", "iso3": "SOL", "color": "#14F195",
        "networks": [5],
    },
    "LTC": {
        "id": 8, "name": "Litecoin", "iso3": "LTC", "color": "#345D9D",
        "networks": [8],
    },
}

# indicative USD prices (demo). Live monitoring replaces these when keys are set.
PRICES_USD = {
    "USDT": 1.0, "USDC": 1.0, "BTC": 84526.0, "ETH": 3210.0,
    "BNB": 690.0, "TRX": 0.34, "SOL": 115.84, "LTC": 73.21,
}

# 24h change % (demo)
PRICE_CHANGE = {
    "BTC": 2.8, "ETH": 1.6, "BNB": 0.9, "TRX": 1.1,
    "SOL": 3.4, "LTC": -0.5, "USDT": 0.0, "USDC": 0.0,
}

# commission config per (currency, network). fixed + percent, min_fee
def commission_for(iso, network_id):
    net = NETWORKS.get(network_id, {})
    chain = net.get("chain")
    if chain == "bitcoin":
        return {"withdraw": {"fixed": 0.0002, "percent": 0.0, "min_fee": 0.0002, "min": 0.0005},
                "refill": {"fixed": 0.0, "percent": 0.0, "min_fee": 0.0, "min": 0.0001}}
    if chain == "tron":
        return {"withdraw": {"fixed": 1.0, "percent": 0.0, "min_fee": 1.0, "min": 5},
                "refill": {"fixed": 0.0, "percent": 0.0, "min_fee": 0.0, "min": 1}}
    if chain == "litecoin":
        return {"withdraw": {"fixed": 0.001, "percent": 0.0, "min_fee": 0.001, "min": 0.01},
                "refill": {"fixed": 0.0, "percent": 0.0, "min_fee": 0.0, "min": 0.001}}
    if chain == "solana":
        return {"withdraw": {"fixed": 0.01, "percent": 0.0, "min_fee": 0.01, "min": 0.05},
                "refill": {"fixed": 0.0, "percent": 0.0, "min_fee": 0.0, "min": 0.01}}
    # EVM
    return {"withdraw": {"fixed": 0.5, "percent": 0.2, "min_fee": 0.5, "min": 5},
            "refill": {"fixed": 0.0, "percent": 0.0, "min_fee": 0.0, "min": 1}}


def networks_for(iso):
    cur = CURRENCIES.get(iso)
    if not cur:
        return []
    return [{"network_id": nid, "network_iso": NETWORKS[nid]["iso"], "name": NETWORKS[nid]["name"]}
            for nid in cur["networks"]]


def usd_value(iso, amount):
    return round(float(amount) * PRICES_USD.get(iso, 0.0), 2)


STATUS_MAP = {
    0: "Created", 1: "Partially", 2: "Completed", 3: "Cancelled",
    6: "In Process", 7: "Expired", 8: "Paid", 9: "Deleted", 10: "Overpayment",
}
STATUS_NAME_TO_ID = {v: k for k, v in STATUS_MAP.items()}

# block explorer tx URL templates per network_id (see NETWORKS above)
EXPLORER_TX = {
    0: "https://mempool.space/tx/{h}",
    1: "https://etherscan.io/tx/{h}",
    2: "https://tronscan.org/#/transaction/{h}",
    4: "https://bscscan.com/tx/{h}",
    5: "https://solscan.io/tx/{h}",
    6: "https://polygonscan.com/tx/{h}",
    7: "https://arbiscan.io/tx/{h}",
    8: "https://blockchair.com/litecoin/transaction/{h}",
}


def explorer_tx_url(network_id, txid):
    """Return a clickable block-explorer URL for a real on-chain tx hash, else None."""
    if not txid or txid == "onchain":
        return None
    h = str(txid)
    if network_id in (1, 4, 6, 7) and not h.startswith("0x"):
        h = "0x" + h
    tmpl = EXPLORER_TX.get(network_id)
    return tmpl.format(h=h) if tmpl else None
