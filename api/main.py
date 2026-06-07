"""
Kardashev Data Platform — FastAPI entrypoint.

Run locally:
    uvicorn api.main:app --reload --port 8000

Endpoints:
    GET  /fuel-mix          5-min fuel mix by ISO
    GET  /curtailment       Daily renewable curtailment
    GET  /curtailment/hourly Hourly curtailment breakdown (CAISO)
    GET  /curtailment/summary Cross-ISO 30-day summary
    GET  /lmp               LMP prices (RT + DA)
    GET  /load              Actual + forecast demand
    GET  /interconnection-queue Active queue with filters
    GET  /isos              ISO catalog with dataset coverage
    GET  /health            Uptime check
"""
from __future__ import annotations

import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.routes import curtailment, fuel_mix, isos, lmp, load, queue


@asynccontextmanager
async def lifespan(app: FastAPI):
    import threading, logging
    def _migrate():
        try:
            import psycopg2, time, os
            from pathlib import Path
            dsn = os.environ.get("DATABASE_URL", "")
            if not dsn:
                return
            # /app/db/schema.sql always exists after COPY . . in Docker
            schema_path = Path("/app/db/schema.sql")
            if not schema_path.exists():
                schema_path = Path(__file__).parent.parent / "db" / "schema.sql"
            schema = schema_path.read_text()
            for attempt in range(10):
                try:
                    conn = psycopg2.connect(dsn)
                    with conn:
                        with conn.cursor() as cur:
                            cur.execute(schema)
                    conn.close()
                    logging.getLogger("migrate").info("Migration complete")
                    return
                except psycopg2.OperationalError:
                    time.sleep(3)
        except Exception as exc:
            logging.getLogger("migrate").error("Migration error: %s", exc)
    threading.Thread(target=_migrate, daemon=True).start()
    yield
    try:
        from api.db import get_engine
        await get_engine().dispose()
    except Exception:
        pass


app = FastAPI(
    title="Kardashev Data Platform",
    description="Bloomberg Terminal for Energy — unified US grid data API",
    version="0.1.0",
    lifespan=lifespan,
)

_extra_origins = [
    o.strip()
    for o in os.environ.get("CORS_ORIGINS", "").split(",")
    if o.strip()
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_extra_origins,
    allow_origin_regex=r"https://([a-z0-9-]+\.)*kardashevlabs\.org",
    allow_methods=["GET"],
    allow_headers=["*"],
)

app.include_router(fuel_mix.router)
app.include_router(curtailment.router)
app.include_router(lmp.router)
app.include_router(load.router)
app.include_router(queue.router)
app.include_router(isos.router)


@app.get("/health")
async def health():
    return {"status": "ok"}
