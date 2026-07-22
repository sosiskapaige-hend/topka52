"""PostgreSQL (Neon) database layer using asyncpg."""
from __future__ import annotations

import asyncio
import logging
import os
from typing import Any

import asyncpg

logger = logging.getLogger(__name__)

_pool: asyncpg.Pool | None = None


async def get_pool() -> asyncpg.Pool:
    global _pool
    if _pool is None:
        raise RuntimeError("DB pool not initialized. Call init_pool() first.")
    return _pool


async def init_pool() -> asyncpg.Pool:
    global _pool
    dsn = os.environ["DATABASE_URL"]
    _pool = await asyncpg.create_pool(dsn, min_size=1, max_size=10, statement_cache_size=0)
    await _create_tables(_pool)
    logger.info("PostgreSQL pool initialized")
    return _pool


async def close_pool() -> None:
    global _pool
    if _pool:
        await _pool.close()
        _pool = None


async def _create_tables(pool: asyncpg.Pool) -> None:
    async with pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                telegram_id         BIGINT PRIMARY KEY,
                system_id           VARCHAR(10) NOT NULL UNIQUE,
                balance             DOUBLE PRECISION NOT NULL DEFAULT 0,
                total_deposited     DOUBLE PRECISION NOT NULL DEFAULT 0,
                operations_done     INTEGER NOT NULL DEFAULT 0,
                operations_limit    INTEGER NOT NULL DEFAULT 100,
                subscription_active BOOLEAN NOT NULL DEFAULT FALSE,
                subscription_expiry TEXT,
                referral_count      INTEGER NOT NULL DEFAULT 0,
                referral_bonus      DOUBLE PRECISION NOT NULL DEFAULT 0,
                referred_by         TEXT,
                active_bundles      JSONB NOT NULL DEFAULT '[]',
                history             JSONB NOT NULL DEFAULT '[]',
                is_admin            BOOLEAN NOT NULL DEFAULT FALSE,
                is_banned           BOOLEAN NOT NULL DEFAULT FALSE,
                last_support_time   DOUBLE PRECISION NOT NULL DEFAULT 0,
                pending_referrer    TEXT,
                referral_qualified  BOOLEAN NOT NULL DEFAULT FALSE
            );

            CREATE TABLE IF NOT EXISTS tickets (
                ticket_id   VARCHAR(10) PRIMARY KEY,
                user_id     BIGINT NOT NULL,
                username    TEXT NOT NULL,
                message     TEXT NOT NULL,
                status      VARCHAR(10) NOT NULL DEFAULT 'open'
            );

            CREATE TABLE IF NOT EXISTS payments (
                invoice_id       TEXT PRIMARY KEY,
                user_id          BIGINT NOT NULL,
                amount_requested DOUBLE PRECISION NOT NULL,
                unique_amount    DOUBLE PRECISION NOT NULL,
                currency         VARCHAR(10) NOT NULL DEFAULT 'USDT',
                status           VARCHAR(20) NOT NULL DEFAULT 'pending',
                payment_url      TEXT,
                created_at       DOUBLE PRECISION NOT NULL,
                paid_at          DOUBLE PRECISION,
                metadata         JSONB,
                external_meta    JSONB,
                processed        BOOLEAN NOT NULL DEFAULT FALSE
            );

            CREATE TABLE IF NOT EXISTS withdrawals (
                withdraw_id      VARCHAR(10) PRIMARY KEY,
                user_id          BIGINT NOT NULL,
                username         TEXT NOT NULL,
                amount           DOUBLE PRECISION NOT NULL,
                amount_requested DOUBLE PRECISION NOT NULL DEFAULT 0,
                address          TEXT NOT NULL,
                status           VARCHAR(10) NOT NULL DEFAULT 'pending',
                reject_reason    TEXT
            );

            ALTER TABLE withdrawals ADD COLUMN IF NOT EXISTS amount_requested DOUBLE PRECISION NOT NULL DEFAULT 0;
        """)
