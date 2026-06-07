"""
BPA (Bonneville Power Administration) real-time balancing area data.

Sources (no auth required):
  Balance sheet  : https://transmission.bpa.gov/business/operations/wind/balancesheet.txt
    - Tab-delimited, updated every 5 minutes
    - Columns: DateTime, Load, Wind, Hydro, Thermal, Nuclear, Net Interchange
  Wind/hydro gen : parsed from balancesheet.txt
"""
from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd

from . import _http

_BALANCESHEET_URL = (
    "https://transmission.bpa.gov/business/operations/wind/balancesheet.txt"
)


def get_balancesheet() -> pd.DataFrame:
    """
    5-min BPA balancing area sheet.
    Returns DataFrame with columns: ts, load_mw, wind_mw, hydro_mw, thermal_mw,
    nuclear_mw, net_interchange_mw.
    """
    r = _http.get(_BALANCESHEET_URL)
    r.raise_for_status()
    text = r.text

    rows = []
    for line in text.splitlines():
        parts = line.strip().split("\t")
        if len(parts) < 7:
            continue
        try:
            ts = datetime.strptime(parts[0].strip(), "%m/%d/%Y %H:%M")
            ts = ts.replace(tzinfo=timezone.utc)  # BPA timestamps are PST; treat as UTC for storage
        except ValueError:
            continue
        try:
            rows.append({
                "ts":               ts,
                "load_mw":          float(parts[1]) if parts[1].strip() else None,
                "wind_mw":          float(parts[2]) if parts[2].strip() else None,
                "hydro_mw":         float(parts[3]) if parts[3].strip() else None,
                "thermal_mw":       float(parts[4]) if parts[4].strip() else None,
                "nuclear_mw":       float(parts[5]) if parts[5].strip() else None,
                "net_interchange_mw": float(parts[6]) if parts[6].strip() else None,
            })
        except (ValueError, IndexError):
            continue

    return pd.DataFrame(rows)
