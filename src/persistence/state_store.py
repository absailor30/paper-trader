"""
Postgres-backed key/value store for portfolio state.

Render's free plan has no persistent disk, so anything written to
logs/*.json is wiped on every redeploy or restart. When DATABASE_URL is
set, portfolio state is persisted to Postgres instead (survives
redeploys); when it isn't set, callers fall back to local JSON files
(unchanged local/dev behavior).
"""
import json
import os
from typing import Optional

from loguru import logger

_TABLE_DDL = """
CREATE TABLE IF NOT EXISTS portfolio_state (
    key TEXT PRIMARY KEY,
    data JSONB NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
)
"""

_UPSERT_SQL = """
INSERT INTO portfolio_state (key, data, updated_at)
VALUES (%s, %s, now())
ON CONFLICT (key) DO UPDATE SET data = EXCLUDED.data, updated_at = now()
"""

_SELECT_SQL = "SELECT data FROM portfolio_state WHERE key = %s"


def is_db_configured() -> bool:
    return bool(os.getenv("DATABASE_URL"))


def _get_connection():
    import psycopg2

    dsn = os.environ["DATABASE_URL"]
    conn = psycopg2.connect(dsn, connect_timeout=5)
    with conn, conn.cursor() as cur:
        cur.execute(_TABLE_DDL)
    return conn


def save_state(key: str, state: dict) -> bool:
    """Upsert state under `key`. Returns True on success, False on failure."""
    try:
        conn = _get_connection()
        try:
            with conn, conn.cursor() as cur:
                cur.execute(_UPSERT_SQL, (key, json.dumps(state)))
            logger.info(f"Portfolio state saved to Postgres (key={key})")
            return True
        finally:
            conn.close()
    except Exception as e:
        logger.error(f"Failed to save state to Postgres (key={key}): {e}")
        return False


def load_state(key: str) -> Optional[dict]:
    """Load state for `key`. Returns None if missing or on failure."""
    try:
        conn = _get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(_SELECT_SQL, (key,))
                row = cur.fetchone()
            if row is None:
                logger.warning(f"No Postgres state found for key={key}")
                return None
            logger.info(f"Portfolio state loaded from Postgres (key={key})")
            return row[0]
        finally:
            conn.close()
    except Exception as e:
        logger.error(f"Failed to load state from Postgres (key={key}): {e}")
        return None
