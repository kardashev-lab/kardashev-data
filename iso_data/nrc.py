"""
NRC (Nuclear Regulatory Commission) daily power reactor status.

Source: https://www.nrc.gov/reading-rm/doc-collections/event-status/reactor-status/powerreactorstatusforlast365days.txt

Tab-delimited. Columns: ReportDt, Unit, Power
  ReportDt: M/D/YYYY (e.g. "6/15/2024")
  Unit:     reactor name (e.g. "Calvert Cliffs 1")
  Power:    integer % capacity (0-100; blank if shutdown)

~100 US reactors, updated each weekday.
"""
from __future__ import annotations

from datetime import date
from typing import Iterator

import pandas as pd

from . import _http

_URL = (
    "https://www.nrc.gov/reading-rm/doc-collections/event-status/"
    "reactor-status/powerreactorstatusforlast365days.txt"
)


def get_reactor_status() -> list[dict]:
    """
    Fetch the rolling 365-day reactor status file.

    Returns list of dicts:
        date (date), unit (str), power_pct (float)
    """
    df = _http.get_csv(_URL, sep="\t", encoding="latin-1")
    df.columns = [c.strip() for c in df.columns]

    # Normalise column names — NRC occasionally changes casing
    col_map: dict[str, str] = {}
    for c in df.columns:
        key = c.strip().lower().replace(" ", "").replace("_", "")
        if key in ("reportdt", "reportdate", "date"):
            col_map[c] = "ReportDt"
        elif key in ("unit", "unitname"):
            col_map[c] = "Unit"
        elif key in ("power", "powerpct", "power%"):
            col_map[c] = "Power"
    df.rename(columns=col_map, inplace=True)

    required = {"ReportDt", "Unit", "Power"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"NRC reactor status file missing columns: {missing}. "
                         f"Got: {list(df.columns)}")

    rows: list[dict] = []
    for _, row in df.iterrows():
        raw_date = str(row["ReportDt"]).strip()
        try:
            report_date = _parse_date(raw_date)
        except ValueError:
            continue

        unit = str(row["Unit"]).strip()
        if not unit or unit.lower() == "nan":
            continue

        raw_power = str(row["Power"]).strip()
        try:
            power_pct = float(raw_power)
        except (ValueError, TypeError):
            # Blank or non-numeric means offline / unknown
            power_pct = 0.0

        rows.append({
            "date":      report_date,
            "unit":      unit,
            "power_pct": power_pct,
        })

    return rows


def _parse_date(raw: str) -> date:
    """Parse NRC date formats: M/D/YYYY, MM/DD/YYYY, YYYY-MM-DD."""
    import re
    raw = raw.strip()
    if re.match(r"\d{1,2}/\d{1,2}/\d{4}", raw):
        parts = raw.split("/")
        return date(int(parts[2]), int(parts[0]), int(parts[1]))
    if re.match(r"\d{4}-\d{2}-\d{2}", raw):
        parts = raw.split("-")
        return date(int(parts[0]), int(parts[1]), int(parts[2]))
    raise ValueError(f"Unrecognised NRC date: {raw}")
