"""
Main app entrypoint.
Run with: uvicorn main:app --host 0.0.0.0 --port 10000
"""

import asyncio
import time
from datetime import datetime, timezone
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from engine import config
from engine.exchange import make_exchange, fetch_ohlcv, to_ccxt_symbol, get_balance_usdt, place_market_order_with_sl_tp
from engine.strategy import SNRStrategy

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # tighten this to your Vercel URL once deployed
    allow_methods=["*"],
    allow_headers=["*"],
)

# in-memory state for now — swap for real DB reads once auth/DB is wired in
STATE = {
    "last_scan_date": None,
    "active_pairs": [],
    "last_ping": None,
}


@app.get("/ping")
def ping():
    """Hit by cron-job.org / UptimeRobot every 1 min to keep Render's free tier awake."""
    STATE["last_ping"] = datetime.now(timezone.utc).isoformat()
    return {"status": "awake", "time": STATE["last_ping"]}


@app.get("/status")
def status():
    return STATE


def rank_pairs_for_today(user_exchange) -> list:
    """Scores each candidate pair by ATR%% and 24h volume, returns top N symbols."""
    scored = []
    for symbol in config.CANDIDATE_PAIRS:
        ccxt_symbol = to_ccxt_symbol(symbol)
        try:
            candles = fetch_ohlcv(user_exchange, ccxt_symbol, config.TIMEFRAME, limit=100)
            if len(candles) < 20:
                continue
            closes = [c[4] for c in candles]
            highs = [c[2] for c in candles]
            lows = [c[3] for c in candles]
            vols = [c[5] for c in candles]

            trs = [highs[i] - lows[i] for i in range(len(candles))]
            atr_val = sum(trs[-14:]) / 14
            price = closes[-1]
            atr_pct = (atr_val / price) * 100 if price else 0
            vol_24h = sum(vols[-24:]) if config.TIMEFRAME == "1h" else sum(vols[-1:])

            score = atr_pct * 1.0 + (vol_24h / 1_000_000) * 0.1
            scored.append((symbol, score, atr_pct, vol_24h))
        except Exception as e:
            print(f"[scan] skipped {symbol}: {e}")
            continue

    scored.sort(key=lambda x: x[1], reverse=True)
    top = [s[0] for s in scored[: config.DAILY_TOP_N]]
    return top


async def daily_scan_job(user_exchange):
    """Runs once per day around midnight — picks today's top pairs to watch."""
    while True:
        now = datetime.now(timezone.utc)
        if now.hour == 0 and STATE["last_scan_date"] != now.date():
            print("[scan] running nightly pair scan...")
            top_pairs = rank_pairs_for_today(user_exchange)
            STATE["active_pairs"] = top_pairs
            STATE["last_scan_date"] = now.date()
            print(f"[scan] today's pairs: {top_pairs}")
        await asyncio.sleep(60)


async def trading_loop(user_exchange, risk_per_trade_pct: float):
    """
    Checks each active pair for a fresh signal every loop, places a trade if found.
    NOTE: this is a starting scaffold — one strategy instance per pair needs to
    persist across restarts in production (store level/trade state in the DB,
    not just in memory) so a redeploy doesn't lose track of an open trade.
    """
    strategies = {symbol: SNRStrategy(
        swing_lookback=config.SWING_LOOKBACK,
        atr_len=config.ATR_LEN,
        atr_sl_mult=config.ATR_SL_MULT,
        risk_reward=config.RISK_REWARD,
        touch_tolerance_atr_mult=config.TOUCH_TOLERANCE_ATR_MULT,
    ) for symbol in config.CANDIDATE_PAIRS}

    while True:
        for symbol in STATE["active_pairs"]:
            try:
                ccxt_symbol = to_ccxt_symbol(symbol)
                candles = fetch_ohlcv(user_exchange, ccxt_symbol, config.TIMEFRAME, limit=300)
                strat = strategies[symbol]
                signal = strat.latest_signal_from_live_candles(candles)

                if signal is not None:
                    balance = get_balance_usdt(user_exchange)
                    risk_amount = balance * (risk_per_trade_pct / 100.0)
                    qty = risk_amount / signal.risk if signal.risk > 0 else 0
                    if qty > 0:
                        print(f"[trade] {symbol} {signal.side} entry={signal.entry} sl={signal.sl} tp={signal.tp}")
                        place_market_order_with_sl_tp(
                            user_exchange, ccxt_symbol, signal.side, qty, signal.sl, signal.tp
                        )
            except Exception as e:
                print(f"[trade] error on {symbol}: {e}")

        await asyncio.sleep(60 * 60)  # matches 1h timeframe — check once per candle


@app.on_event("startup")
async def startup_event():
    """
    Placeholder single-user startup for testing. Once auth/multi-user DB is in,
    this becomes: loop over all users with is_active=True, spawn a pair of
    tasks (scan + trade loop) per user, using their own decrypted API keys.
    """
    if config.BYBIT_API_KEY:
        exchange = make_exchange(config.BYBIT_API_KEY, config.BYBIT_API_SECRET, demo=config.BYBIT_TESTNET)
        asyncio.create_task(daily_scan_job(exchange))
        asyncio.create_task(trading_loop(exchange, config.RISK_PER_TRADE_PCT))
    else:
        print("[startup] no API key set yet — engine idle, /ping still works for keep-alive testing.")
