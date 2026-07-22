"""
Central config for the trading engine.
Fill in your Bybit API key/secret via environment variables — never hardcode them.
"""

import os

BYBIT_API_KEY = os.getenv("BYBIT_API_KEY", "c6bNNaq25LQwA1ywd4")
BYBIT_API_SECRET = os.getenv("BYBIT_API_SECRET", "HgZqyYuzLh5GNqOpj56ADu1iBTfIi2A7imq9")
BYBIT_TESTNET = os.getenv("BYBIT_TESTNET", "true").lower() == "true"  # start on testnet!

TIMEFRAME = "1h"

CANDIDATE_PAIRS = [
    "BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT",
    "DOGEUSDT", "AVAXUSDT", "LINKUSDT", "ADAUSDT", "DOTUSDT",
    "UNIUSDT", "NEARUSDT", "AAVEUSDT", "APTUSDT", "ARBUSDT",
    "OPUSDT", "INJUSDT", "SUIUSDT", "TIAUSDT", "LDOUSDT",
    "STXUSDT", "RUNEUSDT", "HBARUSDT", "KAVAUSDT", "GMXUSDT",
    "DYDXUSDT", "CRVUSDT", "SNXUSDT", "GALAUSDT", "SANDUSDT",
    "MANAUSDT", "APEUSDT", "CHZUSDT", "GRTUSDT", "1000PEPEUSDT",
    "WIFUSDT", "JUPUSDT", "RENDERUSDT", "FETUSDT", "ARKMUSDT",
    "STORJUSDT", "CFXUSDT", "1000LUNCUSDT", "ZILUSDT", "QNTUSDT",
    "MASKUSDT", "WLDUSDT", "PYTHUSDT", "ENAUSDT", "ONDOUSDT",
]

DAILY_TOP_N = 20          # how many pairs to actively watch after the nightly scan
RISK_PER_TRADE_PCT = 1.0  # % of account balance risked per trade
RISK_REWARD = 3.0         # TP distance = SL distance * this
BREAKEVEN_AT_R = 1.0      # move SL to entry once price reaches this many R in profit
PARTIAL_CLOSE_AT_BE = 0.4 # fraction of position closed when breakeven triggers (0 = disable)

# Strategy params (mirrors the upgraded indicator)
SWING_LOOKBACK = 3
ATR_LEN = 14
ATR_SL_MULT = 0.3
TOUCH_TOLERANCE_ATR_MULT = 0.3
MIN_LEVEL_ATR_MULT = 0.5
TREND_EMA_LEN = 50
MIN_BODY_ATR_MULT = 0.25
