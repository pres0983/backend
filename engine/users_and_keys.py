"""
User + exchange-connection model, with encrypted API key storage.
Each user owns their own Bybit API key — the platform never holds funds,
only stores encrypted credentials to place orders on the user's behalf,
on their own account.
"""

from cryptography.fernet import Fernet
import os

# Generate ONE key for your whole app and store it in an env var (never in code).
# Generate it once with: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
ENCRYPTION_KEY = os.getenv("API_KEY_ENCRYPTION_KEY", "").encode()
_fernet = Fernet(ENCRYPTION_KEY)


def encrypt_secret(plain_text: str) -> str:
    return _fernet.encrypt(plain_text.encode()).decode()


def decrypt_secret(token: str) -> str:
    return _fernet.decrypt(token.encode()).decode()


# --- Example schema (Postgres) ---
"""
users
  id            uuid primary key
  email         text unique
  password_hash text
  role          text default 'user'   -- 'user' or 'admin'
  created_at    timestamptz

exchange_connections
  id                 uuid primary key
  user_id            uuid references users(id)
  exchange           text default 'bybit'
  api_key_encrypted  text     -- store encrypted, never plaintext
  api_secret_encrypted text
  mode               text default 'demo'   -- 'demo' or 'live'
  is_active          boolean default false  -- bot on/off toggle
  created_at         timestamptz

trades
  id            uuid primary key
  user_id       uuid references users(id)
  pair          text
  side          text        -- 'buy' or 'sell'
  entry_price   numeric
  sl            numeric
  tp            numeric
  result        text        -- 'open', 'win', 'loss', 'scratch'
  pnl           numeric
  opened_at     timestamptz
  closed_at     timestamptz

daily_scans
  id            uuid primary key
  scan_date     date
  pair          text
  atr_pct       numeric
  volume_24h    numeric
  rank_score    numeric
  selected      boolean
"""
