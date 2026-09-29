"""Живі курси криптовалют з публічного API Binance.

Оновлює словники catalog.PRICES_USD та catalog.PRICE_CHANGE НА МІСЦІ (in-place),
щоб усі модулі, які вже імпортували ці словники за іменем, бачили свіжі значення.

Використовує публічний endpoint Binance /api/v3/ticker/24hr (ключі не потрібні).
Основний хост — api.binance.com, резервний — data-api.binance.vision
(інколи основний хост може бути недоступний за IP/регіоном).
"""
import logging
import httpx

import catalog

logger = logging.getLogger("binance_prices")

# ISO валюти -> символ пари на Binance (до USDT)
SYMBOL_MAP = {
    "BTC": "BTCUSDT",
    "ETH": "ETHUSDT",
    "BNB": "BNBUSDT",
    "TRX": "TRXUSDT",
    "SOL": "SOLUSDT",
    "LTC": "LTCUSDT",
    "USDC": "USDCUSDT",
}
# Стейбли фіксуємо в 1.0 (не залежать від тікера)
STABLE = {"USDT": 1.0}

HOSTS = [
    "https://api.binance.com",
    "https://data-api.binance.vision",
]


async def fetch_prices() -> bool:
    """Отримати тікери й оновити catalog.PRICES_USD / catalog.PRICE_CHANGE.

    Повертає True якщо оновлення вдалося.
    """
    symbols = list(SYMBOL_MAP.values())
    # Формат query: symbols=["BTCUSDT","ETHUSDT",...]
    symbols_param = "[" + ",".join(f'"{s}"' for s in symbols) + "]"

    last_err = None
    for host in HOSTS:
        url = f"{host}/api/v3/ticker/24hr"
        try:
            async with httpx.AsyncClient(timeout=15) as c:
                r = await c.get(url, params={"symbols": symbols_param})
                if r.status_code != 200:
                    last_err = f"{host} -> HTTP {r.status_code}"
                    continue
                data = r.json()
        except Exception as e:  # мережева/парсинг помилка -> пробуємо наступний хост
            last_err = f"{host} -> {e}"
            continue

        by_symbol = {item["symbol"]: item for item in data}
        updated = 0
        for iso, sym in SYMBOL_MAP.items():
            item = by_symbol.get(sym)
            if not item:
                continue
            try:
                price = float(item["lastPrice"])
                change = float(item["priceChangePercent"])
            except (KeyError, ValueError, TypeError):
                continue
            if price > 0:
                catalog.PRICES_USD[iso] = round(price, 6)
                catalog.PRICE_CHANGE[iso] = round(change, 2)
                updated += 1

        # стейбли завжди 1.0
        for iso, val in STABLE.items():
            catalog.PRICES_USD[iso] = val
            catalog.PRICE_CHANGE.setdefault(iso, 0.0)

        if updated:
            logger.info(f"Binance prices updated ({updated} pairs) via {host}")
            return True
        last_err = f"{host} -> no pairs parsed"

    logger.warning(f"Binance price fetch failed, keeping previous values. Last error: {last_err}")
    return False


async def price_worker():
    """Фоновий цикл: оновлює ціни при старті та кожні 30 секунд."""
    import asyncio
    await fetch_prices()
    while True:
        await asyncio.sleep(30)
        try:
            await fetch_prices()
        except Exception as e:
            logger.info(f"price_worker error: {e}")
