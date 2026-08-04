"""Database connection pool (asyncpg via SQLAlchemy async)."""
from __future__ import annotations

import os
from contextlib import asynccontextmanager
from typing import AsyncIterator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, create_async_engine

_engine: AsyncEngine | None = None


def _dsn() -> str:
    raw = os.environ["DATABASE_URL"]
    # SQLAlchemy async needs postgresql+asyncpg://
    return raw.replace("postgresql://", "postgresql+asyncpg://").replace(
        "postgres://", "postgresql+asyncpg://"
    )


def get_engine() -> AsyncEngine:
    global _engine
    if _engine is None:
        # Small pool: public tools are low-QPS; oversized pools inflate Postgres RAM.
        _engine = create_async_engine(
            _dsn(),
            pool_size=int(os.environ.get("DB_POOL_SIZE", "3")),
            max_overflow=int(os.environ.get("DB_POOL_OVERFLOW", "7")),
            pool_pre_ping=True,
            echo=False,
        )
    return _engine


@asynccontextmanager
async def conn() -> AsyncIterator[AsyncConnection]:
    async with get_engine().connect() as c:
        yield c


def _sanitize(row: dict) -> dict:
    """Replace float NaN/Inf with None so json.dumps doesn't choke."""
    return {
        k: (None if isinstance(v, float) and not (v == v) else v)
        for k, v in row.items()
    }


async def fetch(sql: str, **params):
    async with conn() as c:
        result = await c.execute(text(sql), params)
        return [_sanitize(dict(r)) for r in result.mappings().all()]


async def fetch_one(sql: str, **params):
    async with conn() as c:
        result = await c.execute(text(sql), params)
        row = result.mappings().first()
        return _sanitize(dict(row)) if row else None
