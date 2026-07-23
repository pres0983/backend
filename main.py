"""
Main app entrypoint.
Run with: uvicorn main:app --host 0.0.0.0 --port 10000
"""

import asyncio
from datetime import datetime, timezone
from typing import Optional

from fastapi import FastAPI, Depends, HTTPException, Header
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy.orm import Session

from engine import config
from engine.db import init_db, get_db, User, ExchangeConnection, Trade
from engine.auth import hash_password, verify_password, create_access_token, decode_access_token
from engine.users_and_keys import encrypt_secret, decrypt_secret
from engine.exchange import make_exchange, fetch_ohlcv, to_ccxt_symbol, get_balance_usdt, place_market_order_with_sl_tp
from engine.strategy import SNRStrategy
from engine.bot_manager import bot_supervisor

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # tighten this to your Vercel URL once deployed
    allow_methods=["*"],
    allow_headers=["*"],
)

# in-memory scan state per connection_id — fine for now, promote to DB (daily_scans table) later
SCAN_STATE: dict[str, dict] = {}


# ---------- auth dependency ----------

def get_current_user(authorization: str = Header(None), db: Session = Depends(get_db)) -> User:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "Missing or invalid Authorization header")
    token = authorization.split(" ", 1)[1]
    payload = decode_access_token(token)
    if not payload:
        raise HTTPException(401, "Invalid or expired token")
    user = db.query(User).filter(User.id == payload["sub"]).first()
    if not user:
        raise HTTPException(401, "User not found")
    return user


def require_admin(user: User = Depends(get_current_user)) -> User:
    if user.role != "admin":
        raise HTTPException(403, "Admin only")
    return user


# ---------- schemas ----------

class SignupBody(BaseModel):
    email: str
    password: str


class LoginBody(BaseModel):
    email: str
    password: str


class ExchangeSettingsBody(BaseModel):
    api_key: str
    api_secret: str
    mode: str  # 'demo' or 'live'


# ---------- auth routes ----------

@app.post("/auth/signup")
def signup(body: SignupBody, db: Session = Depends(get_db)):
    if db.query(User).filter(User.email == body.email).first():
        raise HTTPException(400, "Email already registered")
    user = User(email=body.email, password_hash=hash_password(body.password))
    db.add(user)
    db.commit()
    db.refresh(user)
    token = create_access_token(str(user.id), user.role)
    return {"token": token, "email": user.email, "role": user.role}


@app.post("/auth/login")
def login(body: LoginBody, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == body.email).first()
    if not user or not verify_password(body.password, user.password_hash):
        raise HTTPException(401, "Invalid email or password")
    token = create_access_token(str(user.id), user.role)
    return {"token": token, "email": user.email, "role": user.role}


# ---------- settings routes (real, DB-backed) ----------

@app.post("/settings/exchange")
def save_exchange_settings(body: ExchangeSettingsBody, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if body.mode not in ("demo", "live"):
        raise HTTPException(400, "mode must be 'demo' or 'live'")

    conn = db.query(ExchangeConnection).filter(ExchangeConnection.user_id == user.id).first()
    if conn is None:
        conn = ExchangeConnection(user_id=user.id)
        db.add(conn)

    conn.api_key_encrypted = encrypt_secret(body.api_key)
    conn.api_secret_encrypted = encrypt_secret(body.api_secret)
    conn.mode = body.mode
    db.commit()
    return {"ok": True, "mode": conn.mode}


@app.post("/settings/bot-toggle")
def toggle_bot(active: bool, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    conn = db.query(ExchangeConnection).filter(ExchangeConnection.user_id == user.id).first()
    if conn is None:
        raise HTTPException(400, "Connect your exchange API key first")
    conn.is_active = active
    db.commit()
    # bot_supervisor() picks this up within 30s and starts/stops the task
    return {"ok": True, "active": conn.is_active}


@app.get("/settings/status")
def my_status(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    conn = db.query(ExchangeConnection).filter(ExchangeConnection.user_id == user.id).first()
    scan = SCAN_STATE.get(str(conn.id)) if conn else None
    return {
        "connected": conn is not None,
        "mode": conn.mode if conn else None,
        "active": conn.is_active if conn else False,
        "active_pairs": scan.get("active_pairs", []) if scan else [],
        "last_scan_date": str(scan.get("last_scan_date")) if scan else None,
    }


@app.get("/trades")
def my_trades(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    trades = db.query(Trade).filter(Trade.user_id == user.id).order_by(Trade.opened_at.desc()).limit(200).all()
    return [
        {
            "pair": t.pair, "side": t.side, "entry_price": float(t.entry_price) if t.entry_price else None,
            "sl": float(t.sl) if t.sl else None, "tp": float(t.tp) if t.tp else None,
            "result": t.result, "pnl": float(t.pnl) if t.pnl else None,
            "opened_at": t.opened_at.isoformat() if t.opened_at else None,
        }
        for t in trades
    ]


# ---------- admin routes ----------

@app.get("/admin/users")
def admin_list_users(admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    users = db.query(User).all()
    result = []
    for u in users:
        conn = db.query(ExchangeConnection).filter(ExchangeConnection.user_id == u.id).first()
        trade_count = db.query(Trade).filter(Trade.user_id == u.id).count()
        result.append({
            "id": str(u.id), "email": u.email, "mode": conn.mode if conn else None,
            "active": conn.is_active if conn else False, "trades": trade_count,
        })
    return result


@app.post("/admin/users/{user_id}/force-stop")
def admin_force_stop(user_id: str, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    conn = db.query(ExchangeConnection).filter(ExchangeConnection.user_id == user_id).first()
    if conn:
        conn.is_active = False
        db.commit()
    return {"ok": True}


# ---------- keep-alive ----------

@app.get("/ping")
def ping():
    """Hit by cron-job.org / UptimeRobot every 1 min to keep Render's free tier awake."""
    return {"status": "awake", "time": datetime.now(timezone.utc).isoformat()}


# ---------- trading engine (per-connection, called by bot_manager) ----------

def rank_pairs_for_today(user_exchange) -> list:
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
            scored.append((symbol, score))
        except Exception as e:
            print(f"[scan] skipped {symbol}: {e}")
            continue
    scored.sort(key=lambda x: x[1], reverse=True)
    return [s[0] for s in scored[: config.DAILY_TOP_N]]


async def daily_scan_job(user_exchange, connection_id: str = "default"):
    while True:
        now = datetime.now(timezone.utc)
        state = SCAN_STATE.setdefault(connection_id, {"last_scan_date": None, "active_pairs": []})
        if now.hour == 0 and state["last_scan_date"] != now.date():
            print(f"[scan:{connection_id}] running nightly pair scan...")
            state["active_pairs"] = rank_pairs_for_today(user_exchange)
            state["last_scan_date"] = now.date()
            print(f"[scan:{connection_id}] today's pairs: {state['active_pairs']}")
        await asyncio.sleep(60)


async def trading_loop(user_exchange, risk_per_trade_pct: float, connection_id: str = "default"):
    strategies = {symbol: SNRStrategy(
        swing_lookback=config.SWING_LOOKBACK,
        atr_len=config.ATR_LEN,
        atr_sl_mult=config.ATR_SL_MULT,
        risk_reward=config.RISK_REWARD,
        touch_tolerance_atr_mult=config.TOUCH_TOLERANCE_ATR_MULT,
    ) for symbol in config.CANDIDATE_PAIRS}

    while True:
        state = SCAN_STATE.get(connection_id, {"active_pairs": []})
        for symbol in state.get("active_pairs", []):
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
                        print(f"[trade:{connection_id}] {symbol} {signal.side} entry={signal.entry} sl={signal.sl} tp={signal.tp}")
                        place_market_order_with_sl_tp(user_exchange, ccxt_symbol, signal.side, qty, signal.sl, signal.tp)
            except Exception as e:
                print(f"[trade:{connection_id}] error on {symbol}: {e}")
        await asyncio.sleep(60 * 60)


@app.on_event("startup")
async def startup_event():
    init_db()
    asyncio.create_task(bot_supervisor())
    print("[startup] DB initialized, bot supervisor running — waiting for users to activate bots.")
