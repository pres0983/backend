"""
Bybit exchange connection wrapper.
Handles both demo (testnet) and live modes per-user, based on their settings.
"""

import ccxt
from typing import Optional


def make_exchange(api_key: str, api_secret: str, demo: bool = True) -> ccxt.bybit:
    """
    Create a ccxt Bybit exchange instance for a specific user.
    demo=True uses Bybit's testnet — always start here before going live.
    """
    exchange = ccxt.bybit({
        "apiKey": api_key,
        "secret": api_secret,
        "enableRateLimit": True,
        "options": {"defaultType": "swap"},  # USDT perpetual futures
    })
    if demo:
        exchange.set_sandbox_mode(True)
    return exchange


def fetch_ohlcv(exchange: ccxt.bybit, symbol: str, timeframe: str = "1h", limit: int = 300):
    """
    Returns a list of [timestamp, open, high, low, close, volume].
    `symbol` should be ccxt unified format, e.g. 'BTC/USDT:USDT'.
    """
    return exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)


def to_ccxt_symbol(bybit_symbol: str) -> str:
    """Converts 'BTCUSDT' -> 'BTC/USDT:USDT' (ccxt unified perpetual format)."""
    base = bybit_symbol.replace("USDT", "")
    return f"{base}/USDT:USDT"


def get_balance_usdt(exchange: ccxt.bybit) -> float:
    bal = exchange.fetch_balance()
    return float(bal.get("USDT", {}).get("free", 0.0))


def place_market_order_with_sl_tp(
    exchange: ccxt.bybit,
    symbol: str,
    side: str,          # 'buy' or 'sell'
    amount: float,       # contract quantity
    sl_price: float,
    tp_price: float,
) -> dict:
    """
    Opens a market position and attaches SL/TP as real exchange-side orders,
    so the stop exists on Bybit's engine even if this bot process is asleep.
    """
    order = exchange.create_order(
        symbol=symbol,
        type="market",
        side=side,
        amount=amount,
        params={
            "stopLoss": str(sl_price),
            "takeProfit": str(tp_price),
        },
    )
    return order


def move_stop_to_breakeven(exchange: ccxt.bybit, symbol: str, entry_price: float) -> dict:
    """Updates the position's SL to entry price (breakeven)."""
    return exchange.set_trading_stop(symbol, params={"stopLoss": str(entry_price)})


def close_partial_position(exchange: ccxt.bybit, symbol: str, side_to_close: str, amount: float) -> dict:
    """side_to_close = opposite of the original entry side, to reduce/close."""
    return exchange.create_order(
        symbol=symbol,
        type="market",
        side=side_to_close,
        amount=amount,
        params={"reduceOnly": True},
    )
