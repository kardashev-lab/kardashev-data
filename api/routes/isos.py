from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(prefix="/isos", tags=["meta"])

_ISO_CATALOG = [
    {
        "iso": "CAISO",
        "name": "California ISO",
        "region": "California",
        "datasets": ["fuel_mix", "lmp_rt", "lmp_da", "load", "curtailment", "curtailment_hourly"],
        "curtailment_source": "HTML scrape — caiso.com daily renewable report",
        "refresh_intervals": {"fuel_mix": "5min", "lmp": "5min", "curtailment": "daily"},
    },
    {
        "iso": "SPP",
        "name": "Southwest Power Pool",
        "region": "Central US",
        "datasets": ["fuel_mix", "load", "curtailment"],
        "curtailment_source": "portal.spp.org VER curtailment CSV",
        "refresh_intervals": {"fuel_mix": "5min", "curtailment": "5min"},
    },
    {
        "iso": "ERCOT",
        "name": "Electric Reliability Council of Texas",
        "region": "Texas",
        "datasets": ["fuel_mix", "load", "curtailment_estimate"],
        "curtailment_source": "Estimated: max(0, potential - actual) — dashboard JSON",
        "refresh_intervals": {"fuel_mix": "15min", "curtailment": "15min"},
    },
    {
        "iso": "MISO",
        "name": "Midcontinent ISO",
        "region": "Midwest + South",
        "datasets": ["fuel_mix", "load", "binding_constraints"],
        "curtailment_source": "Not available without dms.miso.energy credentials",
        "refresh_intervals": {"fuel_mix": "5min"},
    },
    {
        "iso": "NYISO",
        "name": "New York ISO",
        "region": "New York",
        "datasets": ["fuel_mix", "lmp_rt", "lmp_da", "load", "btm_solar"],
        "curtailment_source": "Not publicly available",
        "refresh_intervals": {"fuel_mix": "5min", "lmp": "5min"},
    },
    {
        "iso": "ISONE",
        "name": "ISO New England",
        "region": "New England",
        "datasets": ["fuel_mix", "lmp_rt", "lmp_da", "load"],
        "curtailment_source": "Not publicly available",
        "refresh_intervals": {"fuel_mix": "5min"},
    },
    {
        "iso": "PJM",
        "name": "PJM Interconnection",
        "region": "Mid-Atlantic + Midwest",
        "datasets": ["fuel_mix", "lmp_rt", "lmp_da", "load", "wind_gen", "solar_gen"],
        "curtailment_source": "Not publicly available (no dedicated endpoint)",
        "refresh_intervals": {"fuel_mix": "1hr", "lmp": "5min"},
        "auth_required": "Free API key — dataminer2.pjm.com",
    },
]


@router.get("")
async def list_isos():
    """List all supported ISOs with dataset coverage and data sources."""
    return _ISO_CATALOG
