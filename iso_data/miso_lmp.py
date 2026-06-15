"""
MISO LMP client — real-time and day-ahead prices.

No authentication required.

RT LMP:  https://api.misoenergy.org/MISO/LMP/current  (JSON)
DA LMP:  https://docs.misoenergy.org/marketreports/{YYYYMMDD}_da_exante_lmp.csv

Key hubs returned:
  MISO.HUB   — system-wide aggregate hub
  Indiana Hub, Illinois Hub, Michigan Hub, Minnesota Hub, Arkansas Hub
"""
from __future__ import annotations

import io
from datetime import date, datetime, timezone
from typing import Any

import pandas as pd

from . import _http

_RT_URL = "https://api.misoenergy.org/MISO/LMP/current"
_DA_URL_TEMPLATE = "https://docs.misoenergy.org/marketreports/{date}_da_exante_lmp.csv"

# Hub node IDs in the MISO system — exact strings as returned by the API
_HUB_KEYWORDS = {
    "MISO.HUB",
    "INDIANA.HUB",
    "ILLINOIS.HUB",
    "MICHIGAN.HUB",
    "MINNESOTA.HUB",
    "ARKANSAS.HUB",
}


def get_rt_lmp() -> list[dict]:
    """
    Fetch current real-time LMP from MISO public API.

    Returns list of dicts compatible with upsert_lmp():
        ts, iso, node_id, node_name, market, lmp, energy, congestion, loss
    """
    resp = _http.get(_RT_URL, headers={"Accept": "application/json"})
    data = resp.json()

    # Shape: {"LMPData": {"LMPNode": [{"name": ..., "value": ...}, ...]}, "RefId": ...}
    # or sometimes the top-level is just a list
    items: list[dict] = []
    if isinstance(data, list):
        items = data
    elif isinstance(data, dict):
        lmp_data = data.get("LMPData", data)
        nodes = lmp_data.get("LMPNode", lmp_data.get("LmpNode", []))
        if isinstance(nodes, dict):
            nodes = [nodes]
        items = nodes if isinstance(nodes, list) else []

    # MISO RT endpoint returns a current-hour timestamp in the response
    raw_ts = None
    if isinstance(data, dict):
        raw_ts = data.get("RefId") or data.get("Timestamp") or data.get("timestamp")
    ts = _parse_ts(raw_ts) or datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)

    rows: list[dict] = []
    for item in items:
        name = str(item.get("name") or item.get("Name") or "")
        if not name:
            continue
        # Filter to hub nodes only (case-insensitive)
        name_upper = name.upper().replace(" ", ".").replace("-", ".")
        if not any(hub in name_upper for hub in _HUB_KEYWORDS):
            # Also accept if name exactly matches common hub patterns
            if "HUB" not in name_upper:
                continue

        lmp_val = _float(item.get("value") or item.get("Value") or item.get("LmpTotal"))
        rows.append({
            "ts":         ts,
            "iso":        "MISO",
            "node_id":    name_upper,
            "node_name":  name,
            "market":     "RT",
            "lmp":        lmp_val,
            "energy":     None,
            "congestion": None,
            "loss":       None,
        })

    return rows


def get_da_lmp(target: date) -> list[dict]:
    """
    Fetch day-ahead ex-ante LMP CSV for a given date.

    CSV columns (typical): Node, Type, Value, HourEnding columns (HE1..HE24)
    Returns list of dicts compatible with upsert_lmp().
    """
    date_str = target.strftime("%Y%m%d")
    url = _DA_URL_TEMPLATE.format(date=date_str)

    try:
        df = _http.get_csv(url)
    except Exception:
        import logging
        logging.getLogger(__name__).warning("MISO DA LMP: no CSV for %s", date_str)
        return []

    # Normalise column names
    df.columns = [str(c).strip() for c in df.columns]

    # Find node column (usually "Node" or "PNODE")
    node_col = next((c for c in df.columns if c.upper() in ("NODE", "PNODE", "NAME")), None)
    if node_col is None:
        return []

    # Find type column to filter for LMP rows
    type_col = next((c for c in df.columns if c.upper() in ("TYPE", "LMPTYPE", "VALUE TYPE")), None)

    # Hour-ending columns: HE1..HE24
    he_cols = [c for c in df.columns if c.upper().startswith("HE") and c[2:].isdigit()]
    if not he_cols:
        return []

    # Filter to LMP rows
    if type_col:
        df = df[df[type_col].str.strip().str.upper() == "LMP"]

    # Filter to hub nodes
    df = df[df[node_col].str.upper().str.contains("HUB", na=False)]

    rows: list[dict] = []
    for _, row in df.iterrows():
        node_id   = str(row[node_col]).strip().upper()
        node_name = str(row[node_col]).strip()

        for he_col in he_cols:
            hour = int(he_col.upper().replace("HE", "")) - 1  # HE1 = hour 0
            ts = datetime(target.year, target.month, target.day, hour,
                          tzinfo=timezone.utc)
            try:
                lmp = float(row[he_col])
            except (TypeError, ValueError):
                continue
            rows.append({
                "ts":         ts,
                "iso":        "MISO",
                "node_id":    node_id,
                "node_name":  node_name,
                "market":     "DA",
                "lmp":        lmp,
                "energy":     None,
                "congestion": None,
                "loss":       None,
            })

    return rows


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _float(v: Any) -> float | None:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _parse_ts(raw: Any) -> datetime | None:
    if not raw:
        return None
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y%m%d%H%M"):
        try:
            return datetime.strptime(str(raw)[:19], fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None
