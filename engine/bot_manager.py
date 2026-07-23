"""
Runs one scan+trade loop per user who has an active exchange connection.
Polls the DB every 30s for users whose is_active flag changed, and
starts/stops their asyncio tasks accordingly.
"""

import asyncio
from sqlalchemy.orm import Session

from engine.db import SessionLocal, ExchangeConnection
from engine.users_and_keys import decrypt_secret
from engine.exchange import make_exchange
from engine import config

RUNNING_TASKS: dict[str, asyncio.Task] = {}  # connection_id -> task


async def run_user_bot(connection_id: str, api_key: str, api_secret: str, demo: bool):
    """One user's scan+trade loop. Mirrors the single-user version, per-user now."""
    from main import daily_scan_job, trading_loop  # local import avoids circular import

    exchange = make_exchange(api_key, api_secret, demo=demo)
    scan_task = asyncio.create_task(daily_scan_job(exchange, connection_id))
    trade_task = asyncio.create_task(trading_loop(exchange, config.RISK_PER_TRADE_PCT, connection_id))
    await asyncio.gather(scan_task, trade_task)


async def bot_supervisor():
    """
    Background loop: checks the DB for which connections should be active,
    starts a task for newly-activated ones, cancels tasks for deactivated ones.
    """
    while True:
        db: Session = SessionLocal()
        try:
            active_connections = db.query(ExchangeConnection).filter(ExchangeConnection.is_active == True).all()
            active_ids = {str(c.id) for c in active_connections}

            # stop any running task whose connection is no longer active
            for conn_id in list(RUNNING_TASKS.keys()):
                if conn_id not in active_ids:
                    RUNNING_TASKS[conn_id].cancel()
                    del RUNNING_TASKS[conn_id]
                    print(f"[supervisor] stopped bot for connection {conn_id}")

            # start any active connection that isn't running yet
            for conn in active_connections:
                conn_id = str(conn.id)
                if conn_id not in RUNNING_TASKS:
                    api_key = decrypt_secret(conn.api_key_encrypted)
                    api_secret = decrypt_secret(conn.api_secret_encrypted)
                    demo = conn.mode == "demo"
                    task = asyncio.create_task(run_user_bot(conn_id, api_key, api_secret, demo))
                    RUNNING_TASKS[conn_id] = task
                    print(f"[supervisor] started bot for connection {conn_id} (mode={conn.mode})")
        except Exception as e:
            print(f"[supervisor] error: {e}")
        finally:
            db.close()

        await asyncio.sleep(30)
