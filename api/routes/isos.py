from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(prefix="/isos", tags=["meta"])

_NON_ISO_BA_CATALOG = [
    {"iso": "TVA",  "name": "Tennessee Valley Authority",  "region": "Southeast",      "datasets": ["fuel_mix"], "refresh_intervals": {"fuel_mix": "hourly"}, "source": "EIA-930"},
    {"iso": "SOCO", "name": "Southern Company",            "region": "Southeast",      "datasets": ["fuel_mix"], "refresh_intervals": {"fuel_mix": "hourly"}, "source": "EIA-930"},
    {"iso": "FPL",  "name": "Florida Power & Light",       "region": "Florida",        "datasets": ["fuel_mix"], "refresh_intervals": {"fuel_mix": "hourly"}, "source": "EIA-930"},
    {"iso": "DUK",  "name": "Duke Energy",                 "region": "Carolinas",      "datasets": ["fuel_mix"], "refresh_intervals": {"fuel_mix": "hourly"}, "source": "EIA-930"},
    {"iso": "SRP",  "name": "Salt River Project",          "region": "Arizona",        "datasets": ["fuel_mix"], "refresh_intervals": {"fuel_mix": "hourly"}, "source": "EIA-930"},
    {"iso": "PSCO", "name": "Xcel Energy (Colorado)",      "region": "Colorado",       "datasets": ["fuel_mix"], "refresh_intervals": {"fuel_mix": "hourly"}, "source": "EIA-930"},
    {"iso": "PACE", "name": "PacifiCorp East",             "region": "Intermountain",  "datasets": ["fuel_mix"], "refresh_intervals": {"fuel_mix": "hourly"}, "source": "EIA-930"},
    {"iso": "BPAT", "name": "Bonneville Power Admin",      "region": "Pacific NW",     "datasets": ["fuel_mix"], "refresh_intervals": {"fuel_mix": "hourly"}, "source": "EIA-930"},
    {"iso": "NEVP", "name": "Nevada Power",                "region": "Nevada",         "datasets": ["fuel_mix"], "refresh_intervals": {"fuel_mix": "hourly"}, "source": "EIA-930"},
    {"iso": "WALC", "name": "Western Area Lower Colorado", "region": "Southwest",      "datasets": ["fuel_mix"], "refresh_intervals": {"fuel_mix": "hourly"}, "source": "EIA-930"},
    {"iso": "APS",  "name": "Arizona Public Service",      "region": "Arizona",        "datasets": ["fuel_mix"], "refresh_intervals": {"fuel_mix": "hourly"}, "source": "EIA-930"},
    {"iso": "IPCO", "name": "Idaho Power",                 "region": "Idaho",          "datasets": ["fuel_mix"], "refresh_intervals": {"fuel_mix": "hourly"}, "source": "EIA-930"},
    {"iso": "WACM", "name": "Western Area Colorado-Missouri", "region": "Colorado",   "datasets": ["fuel_mix"], "refresh_intervals": {"fuel_mix": "hourly"}, "source": "EIA-930"},
    {"iso": "TEPC", "name": "Tucson Electric Power",       "region": "Arizona",        "datasets": ["fuel_mix"], "refresh_intervals": {"fuel_mix": "hourly"}, "source": "EIA-930"},
    {"iso": "EPE",  "name": "El Paso Electric",            "region": "Texas/New Mexico", "datasets": ["fuel_mix"], "refresh_intervals": {"fuel_mix": "hourly"}, "source": "EIA-930"},
    {"iso": "PNM",  "name": "Public Service New Mexico",   "region": "New Mexico",     "datasets": ["fuel_mix"], "refresh_intervals": {"fuel_mix": "hourly"}, "source": "EIA-930"},
    {"iso": "BANC", "name": "Balancing Authority of Northern California", "region": "California", "datasets": ["fuel_mix"], "refresh_intervals": {"fuel_mix": "hourly"}, "source": "EIA-930"},
    {"iso": "IID",  "name": "Imperial Irrigation District", "region": "California",    "datasets": ["fuel_mix"], "refresh_intervals": {"fuel_mix": "hourly"}, "source": "EIA-930"},
    {"iso": "TIDC", "name": "Turlock Irrigation District", "region": "California",     "datasets": ["fuel_mix"], "refresh_intervals": {"fuel_mix": "hourly"}, "source": "EIA-930"},
    {"iso": "AVRN", "name": "Avangrid Renewables",         "region": "Pacific NW",     "datasets": ["fuel_mix"], "refresh_intervals": {"fuel_mix": "hourly"}, "source": "EIA-930"},
    {"iso": "SCL",  "name": "Seattle City Light",          "region": "Pacific NW",     "datasets": ["fuel_mix"], "refresh_intervals": {"fuel_mix": "hourly"}, "source": "EIA-930"},
    {"iso": "CHPD", "name": "Chelan PUD",                  "region": "Pacific NW",     "datasets": ["fuel_mix"], "refresh_intervals": {"fuel_mix": "hourly"}, "source": "EIA-930"},
    {"iso": "DOPD", "name": "Douglas PUD",                 "region": "Pacific NW",     "datasets": ["fuel_mix"], "refresh_intervals": {"fuel_mix": "hourly"}, "source": "EIA-930"},
    {"iso": "GWA",  "name": "NaturEner Power Watch",       "region": "Montana",        "datasets": ["fuel_mix"], "refresh_intervals": {"fuel_mix": "hourly"}, "source": "EIA-930"},
    {"iso": "NWMT", "name": "NorthWestern Energy (Montana)", "region": "Montana",      "datasets": ["fuel_mix"], "refresh_intervals": {"fuel_mix": "hourly"}, "source": "EIA-930"},
    {"iso": "WAUW", "name": "Western Area Upper Missouri", "region": "Northern Plains", "datasets": ["fuel_mix"], "refresh_intervals": {"fuel_mix": "hourly"}, "source": "EIA-930"},
    {"iso": "TPWR", "name": "City of Tacoma",              "region": "Pacific NW",     "datasets": ["fuel_mix"], "refresh_intervals": {"fuel_mix": "hourly"}, "source": "EIA-930"},
]

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
        "datasets": ["fuel_mix", "load"],
        "curtailment_source": "Not available — requires ERCOT MIS credentials (DUNS-gated)",
        "refresh_intervals": {"fuel_mix": "15min"},
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
async def list_isos(include_bas: bool = False):
    """
    List all supported ISOs with dataset coverage and data sources.

    Set include_bas=true to also include non-ISO balancing authorities (EIA-930).
    """
    if include_bas:
        return _ISO_CATALOG + _NON_ISO_BA_CATALOG
    return _ISO_CATALOG
