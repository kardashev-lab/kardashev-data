"""
PJM public API client (api.pjm.com) using the DataMiner2 UI subscription key.

The legacy dataminer2.pjm.com/feed/* CSV endpoints are dead (return SPA HTML).
The modern REST API accepts the public key shipped in
https://dataminer2.pjm.com/config/settings.json (also overridable via
PJM_API_KEY). Free — not the paid apiportal membership.

Used for:
  - Instantaneous RTO / zone load (5-min) → anomaly load-step detection
  - Unverified 5-min RT LMP for hubs + zones
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any

import requests

log = logging.getLogger(__name__)

_SETTINGS_URL = "https://dataminer2.pjm.com/config/settings.json"
_API_BASE = "https://api.pjm.com/api/v1"
_KEY_CACHE: str | None = None

# Major hubs + zones for RT LMP anomaly / dashboard coverage (not full bus set).
PJM_RT_PNODES: tuple[str, ...] = (
    # Hubs
    "51217", "51287", "51288", "4669664", "33092311", "33092313", "33092315",
    "34497125", "34497127", "34497151", "35010337", "116013751",
    # Zones + RTO
    "1", "51291", "8445784", "8394954", "51292", "33092371", "34508503",
    "51293", "51295", "51296", "51297", "51300", "51298", "51299", "51301",
    "7633629",
)


def subscription_key() -> str:
    """Resolve PJM API key: env override, else DataMiner2 public settings.json."""
    global _KEY_CACHE
    env = os.environ.get("PJM_API_KEY", "").strip()
    if env:
        return env
    if _KEY_CACHE:
        return _KEY_CACHE
    r = requests.get(
        _SETTINGS_URL,
        timeout=30,
        headers={"User-Agent": "kardashev-data/1.0", "Accept": "application/json"},
    )
    r.raise_for_status()
    key = r.json().get("subscriptionKey") or ""
    if not key:
        raise RuntimeError("PJM subscriptionKey missing from settings.json")
    _KEY_CACHE = key
    return key


def _get(path: str, params: dict[str, Any]) -> list[dict]:
    headers = {
        "Ocp-Apim-Subscription-Key": subscription_key(),
        "Accept": "application/json",
        "User-Agent": "kardashev-data/1.0",
    }
    r = requests.get(f"{_API_BASE}/{path}", params=params, headers=headers, timeout=60)
    r.raise_for_status()
    data = r.json()
    items = data.get("items") if isinstance(data, dict) else data
    return list(items or [])


def _parse_ts(value: str) -> datetime:
    # PJM returns "2026-08-03T09:15:00" without Z; treat as UTC when field is *_utc.
    ts = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts.astimezone(timezone.utc)


def get_inst_load(
    area: str = "PJM RTO",
    *,
    datetime_beginning_ept: str = "LastHour",
    row_count: int = 100,
) -> list[dict]:
    """
    5-min instantaneous load.

    datetime_beginning_ept: PJM relative window ("5MinutesAgo", "LastHour")
      or range "YYYY-MM-DD HH:MMtoYYYY-MM-DD HH:MM" in Eastern.

    Returns [{ts: datetime UTC, area, mw}].
    """
    items = _get(
        "inst_load",
        {
            "rowCount": row_count,
            "startRow": 1,
            "datetime_beginning_ept": datetime_beginning_ept,
            "area": area,
            "fields": "datetime_beginning_utc,area,instantaneous_load",
        },
    )
    out: list[dict] = []
    for row in items:
        try:
            mw = row.get("instantaneous_load")
            ts_raw = row.get("datetime_beginning_utc")
            if mw is None or not ts_raw:
                continue
            out.append({
                "ts": _parse_ts(str(ts_raw)),
                "area": row.get("area") or area,
                "mw": float(mw),
            })
        except Exception:
            continue
    out.sort(key=lambda r: r["ts"])
    return out


def get_lmp_rt_5min(
    pnode_ids: tuple[str, ...] | list[str] | None = None,
    *,
    datetime_beginning_ept: str = "LastHour",
    row_count: int = 2000,
) -> list[dict]:
    """
    Unverified 5-min RT LMP for selected pnodes (hubs + zones).

    Returns [{ts, node_id, node_name, node_type, lmp, congestion, loss}].
    """
    ids = list(pnode_ids) if pnode_ids is not None else list(PJM_RT_PNODES)
    # API accepts semicolon-separated pnode_id list.
    items = _get(
        "rt_unverified_fivemin_lmps",
        {
            "rowCount": row_count,
            "startRow": 1,
            "datetime_beginning_ept": datetime_beginning_ept,
            "pnode_id": ";".join(ids),
        },
    )
    out: list[dict] = []
    for row in items:
        try:
            lmp = row.get("total_lmp_rt")
            ts_raw = row.get("datetime_beginning_utc")
            if lmp is None or not ts_raw:
                continue
            out.append({
                "ts": _parse_ts(str(ts_raw)),
                "node_id": str(row.get("pnode_id", "")),
                "node_name": row.get("pnode_name"),
                "node_type": row.get("type"),
                "lmp": float(lmp),
                "congestion": float(row.get("congestion_price_rt") or 0),
                "loss": float(row.get("marginal_loss_price_rt") or 0),
                # Unverified feed often omits energy component.
                "energy": None,
            })
        except Exception:
            continue
    return out
