from __future__ import annotations
import contextlib
import os
import logging
from urllib.parse import urlparse, unquote

import asyncpg
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

DATABASE_URL: str = os.getenv("DATABASE_URL", "")

_pool: asyncpg.Pool | None = None

CREATE_ITEMS = """
CREATE TABLE IF NOT EXISTS items (
    item_id         TEXT PRIMARY KEY,
    household_id    TEXT NOT NULL DEFAULT '__default__',
    name            TEXT NOT NULL,
    category        TEXT NOT NULL,
    quantity        INTEGER NOT NULL DEFAULT 1,
    entry_time      TEXT NOT NULL,
    shelf_life      INTEGER NOT NULL,
    location        TEXT NOT NULL DEFAULT '',
    estimated_cost  DOUBLE PRECISION NOT NULL DEFAULT 0.0,
    storage_temp    DOUBLE PRECISION NOT NULL DEFAULT 4.0,
    humidity        DOUBLE PRECISION NOT NULL DEFAULT 50.0,
    p_spoil         DOUBLE PRECISION,
    rsl             DOUBLE PRECISION,
    fapf_score      DOUBLE PRECISION,
    paif_action     TEXT,
    confidence_tier TEXT NOT NULL DEFAULT 'LOW',
    updated_at      TEXT NOT NULL
)
"""

CREATE_ALERTS = """
CREATE TABLE IF NOT EXISTS alerts (
    alert_id     TEXT PRIMARY KEY,
    household_id TEXT NOT NULL DEFAULT '__default__',
    item_id      TEXT NOT NULL,
    item_name    TEXT NOT NULL,
    alert_type   TEXT NOT NULL,
    p_spoil      DOUBLE PRECISION,
    rsl          DOUBLE PRECISION,
    message      TEXT NOT NULL,
    created_at   TEXT NOT NULL,
    dismissed    INTEGER NOT NULL DEFAULT 0
)
"""

MIGRATE_ALERTS_DISMISSED = """
ALTER TABLE alerts ADD COLUMN dismissed INTEGER NOT NULL DEFAULT 0
"""

CREATE_FEEDBACK = """
CREATE TABLE IF NOT EXISTS feedback (
    feedback_id         TEXT PRIMARY KEY,
    household_id        TEXT NOT NULL DEFAULT '__default__',
    item_id             TEXT NOT NULL,
    category            TEXT NOT NULL,
    shelf_life_declared INTEGER NOT NULL,
    shelf_life_actual   DOUBLE PRECISION NOT NULL,
    correction          DOUBLE PRECISION NOT NULL,
    created_at          TEXT NOT NULL
)
"""

CREATE_GROCERY = """
CREATE TABLE IF NOT EXISTS grocery_items (
    grocery_id   TEXT PRIMARY KEY,
    household_id TEXT NOT NULL DEFAULT '__default__',
    name         TEXT NOT NULL,
    category     TEXT NOT NULL DEFAULT 'vegetable',
    quantity     INTEGER NOT NULL DEFAULT 1,
    checked      INTEGER NOT NULL DEFAULT 0,
    source       TEXT NOT NULL DEFAULT 'manual',
    created_at   TEXT NOT NULL
)
"""

CREATE_CONSUMPTION_HISTORY = """
CREATE TABLE IF NOT EXISTS consumption_history (
    id                  TEXT PRIMARY KEY,
    household_id        TEXT NOT NULL DEFAULT '__default__',
    item_id             TEXT NOT NULL,
    item_name           TEXT NOT NULL,
    category            TEXT NOT NULL,
    quantity_consumed   INTEGER NOT NULL DEFAULT 1,
    reason              TEXT NOT NULL DEFAULT 'consumed',
    p_spoil_at_removal  DOUBLE PRECISION,
    consumed_at         TEXT NOT NULL
)
"""

MIGRATE_ADD_HOUSEHOLD_ID = [
    "ALTER TABLE items ADD COLUMN household_id TEXT NOT NULL DEFAULT '__default__'",
    "ALTER TABLE alerts ADD COLUMN household_id TEXT NOT NULL DEFAULT '__default__'",
    "ALTER TABLE feedback ADD COLUMN household_id TEXT NOT NULL DEFAULT '__default__'",
    "ALTER TABLE grocery_items ADD COLUMN household_id TEXT NOT NULL DEFAULT '__default__'",
    "ALTER TABLE consumption_history ADD COLUMN household_id TEXT NOT NULL DEFAULT '__default__'",
]

HOUSEHOLD_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_items_household ON items (household_id)",
    "CREATE INDEX IF NOT EXISTS idx_alerts_household ON alerts (household_id)",
    "CREATE INDEX IF NOT EXISTS idx_feedback_household ON feedback (household_id)",
    "CREATE INDEX IF NOT EXISTS idx_grocery_household ON grocery_items (household_id)",
    "CREATE INDEX IF NOT EXISTS idx_consumption_household ON consumption_history (household_id)",
]


async def init_db() -> None:
    global _pool
    if not DATABASE_URL:
        raise RuntimeError(
            "DATABASE_URL is not set in .env — "
            "get it from Supabase: Settings > Database > Connection string (Transaction pooler)"
        )
    parsed = urlparse(DATABASE_URL)
    _pool = await asyncpg.create_pool(
        host=parsed.hostname,
        port=parsed.port or 6543,
        user=unquote(parsed.username or ""),
        password=unquote(parsed.password or ""),
        database=(parsed.path or "/postgres").lstrip("/"),
        min_size=2, max_size=10, ssl="require", statement_cache_size=0,
    )
    logger.info("PostgreSQL pool created")
    async with _pool.acquire() as conn:
        await conn.execute(CREATE_ITEMS)
        await conn.execute(CREATE_ALERTS)
        try:
            await conn.execute(MIGRATE_ALERTS_DISMISSED)
        except Exception:
            pass  # column already exists
        await conn.execute(CREATE_FEEDBACK)
        await conn.execute(CREATE_GROCERY)
        await conn.execute(CREATE_CONSUMPTION_HISTORY)
        # Migrate: add household_id to existing tables
        for stmt in MIGRATE_ADD_HOUSEHOLD_ID:
            try:
                await conn.execute(stmt)
            except Exception:
                pass  # column already exists
        for stmt in HOUSEHOLD_INDEXES:
            await conn.execute(stmt)


async def close_db() -> None:
    global _pool
    if _pool:
        await _pool.close()
        _pool = None


@contextlib.asynccontextmanager
async def get_db():
    async with _pool.acquire() as conn:
        yield conn


async def db_dependency():
    async with _pool.acquire() as conn:
        yield conn
