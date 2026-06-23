"""
BPA (Bonneville Power Administration) real-time balancing area data.

Sources (no auth required):
  Balance sheet  : https://transmission.bpa.gov/business/operations/Wind/baltwg.txt
    - Tab-delimited, updated every 5 minutes
    - Columns: Date/Time, Load, VER, Hydro, Fossil/Biomass, Nuclear
"""
from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd

from . import _http

_BALANCESHEET_URL = (
    "https://transmission.bpa.gov/business/operations/Wind/baltwg.txt"
)


def get_balancesheet() -> pd.DataFrame:
    """
    5-min BPA balancing area sheet.
    Returns DataFrame with columns: ts, load_mw, wind_mw, hydro_mw, thermal_mw,
    nuclear_mw.
    """
    r = _http.get(_BALANCESHEET_URL)
    r.raise_for_status()
    text = r.text

    rows = []
    for line in text.splitlines():
        parts = line.strip().split("\t")
        if len(parts) < 6:
            continue
        try:
            import pytz
            _PT = pytz.timezone("US/Pacific")
            ts_naive = datetime.strptime(parts[0].strip(), "%m/%d/%Y %H:%M")
            ts = _PT.localize(ts_naive, is_dst=False).astimezone(timezone.utc)
        except Exception:
            continue
        try:
            rows.append({
                "ts":          ts,
                "load_mw":     float(parts[1]) if parts[1].strip() else None,
                "wind_mw":     float(parts[2]) if parts[2].strip() else None,  # VER
                "hydro_mw":    float(parts[3]) if parts[3].strip() else None,
                "thermal_mw":  float(parts[4]) if parts[4].strip() else None,  # Fossil/Biomass
                "nuclear_mw":  float(parts[5]) if parts[5].strip() else None,
            })
        except (ValueError, IndexError):
            continue

    return pd.DataFrame(rows)
