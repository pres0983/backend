"""
Database models and session setup, using SQLAlchemy + Postgres.
Set DATABASE_URL env var, e.g. from Render Postgres or Supabase.
"""

import os
import uuid
from datetime import datetime, timezone

from sqlalchemy import create_engine, Column, String, Boolean, DateTime, Numeric, ForeignKey, Date
from sqlalchemy.orm import declarative_base, sessionmaker, relationship

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./local_dev.db")  # sqlite fallback for local testing only

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False} if "sqlite" in DATABASE_URL else {})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def now_utc():
    return datetime.now(timezone.utc)


def new_id():
    return str(uuid.uuid4())


class User(Base):
    __tablename__ = "users"
    id = Column(String, primary_key=True, default=new_id)
    email = Column(String, unique=True, nullable=False)
    password_hash = Column(String, nullable=False)
    role = Column(String, default="user")  # 'user' or 'admin'
    created_at = Column(DateTime, default=now_utc)

    connections = relationship("ExchangeConnection", back_populates="user")
    trades = relationship("Trade", back_populates="user")


class ExchangeConnection(Base):
    __tablename__ = "exchange_connections"
    id = Column(String, primary_key=True, default=new_id)
    user_id = Column(String, ForeignKey("users.id"))
    exchange = Column(String, default="bybit")
    api_key_encrypted = Column(String)
    api_secret_encrypted = Column(String)
    mode = Column(String, default="demo")  # 'demo' or 'live'
    is_active = Column(Boolean, default=False)
    created_at = Column(DateTime, default=now_utc)

    user = relationship("User", back_populates="connections")


class Trade(Base):
    __tablename__ = "trades"
    id = Column(String, primary_key=True, default=new_id)
    user_id = Column(String, ForeignKey("users.id"))
    pair = Column(String)
    side = Column(String)
    entry_price = Column(Numeric)
    sl = Column(Numeric)
    tp = Column(Numeric)
    result = Column(String, default="open")  # 'open', 'win', 'loss', 'scratch'
    pnl = Column(Numeric, nullable=True)
    opened_at = Column(DateTime, default=now_utc)
    closed_at = Column(DateTime, nullable=True)

    user = relationship("User", back_populates="trades")


class DailyScan(Base):
    __tablename__ = "daily_scans"
    id = Column(String, primary_key=True, default=new_id)
    scan_date = Column(Date)
    pair = Column(String)
    atr_pct = Column(Numeric)
    volume_24h = Column(Numeric)
    rank_score = Column(Numeric)
    selected = Column(Boolean, default=False)


def init_db():
    Base.metadata.create_all(bind=engine)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
