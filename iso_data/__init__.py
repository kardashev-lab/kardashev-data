"""
iso_data — direct raw-data clients for US grid operators.

No gridstatus dependency. No rate limits beyond the ISOs' own.

ISOs covered:
  caiso   — California ISO       (curtailment HTML scrape + OASIS API)
  ercot   — ERCOT Texas          (dashboard JSON, ~15-min latency)
  isone   — ISO New England      (transform CSV, WebSocket real-time)
  miso    — Midcontinent ISO     (public API + market reports; no curtailment)
  nyiso   — New York ISO         (public MIS CSV endpoints)
  pjm     — PJM Interconnection  (Dataminer2 API; free API key required)
  spp     — Southwest Power Pool (VER curtailment CSV + gen mix)

Shared HTTP layer: _http (retry, rate-limit headers, zip helpers)

Quick-start:
    from iso_data import caiso, spp, ercot
    from datetime import date

    totals = caiso.get_curtailment_daily_totals(date(2025, 6, 1))
    # {'solar_mwh': 2341.5, 'wind_mwh': 83.2, 'total_mwh': 2424.7}

    df = spp.get_ver_curtailments_raw(date(2025, 6, 1))

    # PJM requires a free API key first:
    from iso_data import pjm
    pjm.set_api_key("YOUR_KEY_HERE")
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
