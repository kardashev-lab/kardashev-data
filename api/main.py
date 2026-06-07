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
    # Run migration in background thread — uvicorn binds immediately so health check passes
    import asyncio, threading
    def _migrate():
        try:
            from db.migrate import run
            run()
        except Exception as exc:
            import logging
            logging.getLogger("migrate").error("Migration error: %s", exc)
    threading.Thread(target=_migrate, daemon=True).start()
    yield
    from api.db import get_engine
    await get_engine().dispose()


app = FastAPI(
    title="Kardashev Data Platform",
    description="Bloomberg Terminal for Energy — unified US grid data API",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=os.environ.get("CORS_ORIGINS", "*").split(","),
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
