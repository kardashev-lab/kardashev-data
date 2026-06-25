"""
Direct data clients for US ISO/RTOs. No gridstatus dependency.

Modules:
  caiso     - California ISO (curtailment HTML scrape + OASIS API)
  ercot     - ERCOT Texas (dashboard JSON, ~15-min latency)
  isone     - ISO New England (EIA-930 + transform CSV)
  miso      - Midcontinent ISO (public API + market reports)
  nyiso     - New York ISO (public MIS CSV endpoints)
  pjm       - PJM Interconnection (Dataminer2 API, free key required)
  spp       - Southwest Power Pool (VER curtailment CSV + gen mix)

Shared HTTP utils in _http (retry, zip helpers).

Usage:
    from iso_data import caiso, spp, ercot
    from datetime import date

    totals = caiso.get_curtailment_daily_totals(date(2025, 6, 1))
    df = spp.get_ver_curtailments_raw(date(2025, 6, 1))

    # PJM needs a free key from dataminer2.pjm.com:
    from iso_data import pjm
    pjm.set_api_key("your-key")
    df = pjm.get_fuel_mix(date(2025, 6, 1))
"""

from . import (
    _http,
    caiso,
    eia,
    eia_930,
    eia_commodities,
    ercot,
    ercot_lmp,
    epa,
    isone,
    isone_api,
    miso,
    miso_lmp,
    nrc,
    nrel,
    nyiso,
    pjm,
    rggi,
    spp,
    usbr,
)

__all__ = [
    "caiso", "eia", "eia_930", "eia_commodities", "ercot", "ercot_lmp", "epa",
    "isone", "isone_api", "miso", "miso_lmp", "nrc", "nrel", "nyiso", "pjm",
    "rggi", "spp", "usbr", "_http",
]
