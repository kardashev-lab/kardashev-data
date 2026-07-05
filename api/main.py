"""FastAPI entrypoint for the Kardashev data platform."""
from __future__ import annotations

import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from api.rate_limit import RateLimitMiddleware, requests_per_minute
from api.routes import (
    ancillary,
    bpa,
    carbon,
    carbon_markets,
    commodities,
    constraints,
    curtailment,
    eia_static,
    emissions,
    ercot_large_load,
    fuel_mix,
    generation,
    hydro,
    interchange,
    isos,
    lmp,
    load,
    nat_gas,
    nuclear,
    outages,
    queue,
    solar,
    weather,
)


# Schema migration is handled at process start (run.py / db.migrate), not here.
@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    try:
        from api.db import get_engine
        await get_engine().dispose()
    except Exception:
        pass


app = FastAPI(
    title="Kardashev Data Platform",
    description=(
        "Open API for US energy grid intelligence. "
        "Real-time fuel mix, carbon intensity, LMP, curtailment, load, "
        "generation, nat gas, hydro, nuclear, emissions, and more, "
        "across all 7 major US ISOs. No key required.\n\n"
        "Source: [github.com/kardashev-lab/kardashev-data](https://github.com/kardashev-lab/kardashev-data)"
    ),
    version="0.1.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
)

app.add_middleware(RateLimitMiddleware, requests_per_minute=requests_per_minute())

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
app.include_router(carbon.router)
app.include_router(curtailment.router)
app.include_router(lmp.router)
app.include_router(load.router)
app.include_router(generation.router)
app.include_router(nat_gas.router)
app.include_router(bpa.router)
app.include_router(weather.router)
app.include_router(constraints.router)
app.include_router(eia_static.router)
app.include_router(interchange.router)
app.include_router(queue.router)
app.include_router(isos.router)
# New datasets
app.include_router(nuclear.router)
app.include_router(emissions.router)
app.include_router(carbon_markets.router)
app.include_router(hydro.router)
app.include_router(commodities.router)
app.include_router(solar.router)
app.include_router(outages.router)
app.include_router(ancillary.router)
app.include_router(ercot_large_load.router)


@app.get("/")
async def root():
    return {
        "name": "Kardashev Data Platform",
        "docs": "https://data.kardashevlabs.org/docs",
        "source": "https://github.com/kardashev-lab/kardashev-data",
        "endpoints": [
            "/fuel-mix",
            "/carbon/latest",
            "/lmp",
            "/lmp/map",
            "/curtailment",
            "/load",
            "/generation",
            "/interchange",
            "/nat-gas/prices",
            "/nuclear/status",
            "/emissions",
            "/hydro",
            "/commodities",
            "/queue",
            "/weather",
        ],
    }


@app.get("/health")
async def health():
    from api.db import fetch_one

    try:
        await fetch_one("SELECT 1")
    except Exception:
        return JSONResponse(status_code=503, content={"status": "degraded", "db": "unreachable"})
    return {"status": "ok", "db": "ok"}
