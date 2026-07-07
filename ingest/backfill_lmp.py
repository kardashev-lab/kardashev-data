"""
Historical LMP backfill for the forecasting dataset.

ERCOT: MIS yearly "Historical DAM/RTM Load Zone and Hub Prices" XLSX
       (reportTypeId 13060 = DAM hourly, 13061 = RTM 15-min), one file per
       year back to ~2010, hub + load-zone nodes only, no auth.
CAISO: OASIS PRC_LMP (DAM hourly) / PRC_INTVL_LMP (RTM 5-min) per pricing
       node, chunked date ranges, rate-limited.

Timestamps are interval-START in UTC (ERCOT source data is Central prevailing
time with a repeated-hour flag for DST fall-back).

Usage:
    python -m ingest.backfill_lmp ercot --start-year 2019 [--markets da,rt] [--replace]
    python -m ingest.backfill_lmp caiso --start 2024-01-01 [--end 2026-07-06] [--markets da,rt]

Upserts are idempotent; reruns and overlapping ranges are safe.
--replace deletes existing rows for that ISO+market first (use when existing
rows are known-bad, e.g. pre-timezone-fix ERCOT rows).
"""
from __future__ import annotations

import argparse
import logging
import time
from datetime import date, datetime, timedelta

import pandas as pd

log = logging.getLogger("backfill_lmp")

_OASIS_SLEEP_S = 5          # CAISO OASIS rate limit courtesy
_CAISO_DA_CHUNK_DAYS = 25   # OASIS PRC_LMP max ~31 days per query
_CAISO_RT_CHUNK_DAYS = 7    # PRC_INTVL_LMP: keep responses small
_UPSERT_BATCH = 50_000

_ERCOT_REPORT_IDS = {"da": 13060, "rt": 13061}  # DAMLZHBSPP / RTMLZHBSPP yearly


def _upsert(rows: list[dict]) -> int:
    from ingest.writer import upsert_lmp
    total = 0
    for i in range(0, len(rows), _UPSERT_BATCH):
        total += upsert_lmp(rows[i:i + _UPSERT_BATCH])
    return total


def _delete_iso_market(iso: str, market: str) -> int:
    from ingest.writer import cursor
    with cursor() as cur:
        cur.execute("DELETE FROM lmp WHERE iso = %s AND market = %s", (iso, market))
        return cur.rowcount


# ---------------------------------------------------------------------------
# ERCOT — yearly hub/LZ price files
# ---------------------------------------------------------------------------

def _ercot_sheet_to_rows(df: pd.DataFrame, market: str) -> list[dict]:
    """Convert one monthly sheet of a yearly ERCOT price XLSX to upsert rows."""
    from kardashev._ercot_lmp import HUB_NODES, _col

    df.columns = [str(c).strip() for c in df.columns]
    date_col = _col(df, ["Delivery Date", "DeliveryDate"])
    node_col = _col(df, ["Settlement Point", "Settlement Point Name", "SettlementPoint"])
    spp_col  = _col(df, ["Settlement Point Price", "SettlementPointPrice"])
    flag_col = _col(df, ["Repeated Hour Flag", "DSTFlag"])
    type_col = _col(df, ["Settlement Point Type"])
    if not all([date_col, node_col, spp_col]):
        log.warning("ERCOT sheet missing columns: %s", df.columns.tolist())
        return []

    df = df[df[node_col].astype(str).str.upper().isin(HUB_NODES)].copy()
    if df.empty:
        return []
    # RTM yearly files list load zones under multiple types (LZ, LZEW, LZ_DC);
    # keep only the plain settlement types to avoid duplicate (ts, node) keys.
    if type_col:
        df = df[~df[type_col].astype(str).str.upper().str.contains("EW|DC", regex=True)]

    base = pd.to_datetime(df[date_col], format="%m/%d/%Y")
    if market == "DA":
        # "Hour Ending" "01:00".."24:00" → hour start 0..23
        he_col = _col(df, ["Hour Ending", "HourEnding"])
        hours = df[he_col].astype(str).str.split(":").str[0].astype(int) - 1
        naive = base + pd.to_timedelta(hours, unit="h")
    else:
        # "Delivery Hour" 1..24, "Delivery Interval" 1..4 → 15-min interval start
        h_col = _col(df, ["Delivery Hour", "DeliveryHour"])
        i_col = _col(df, ["Delivery Interval", "DeliveryInterval"])
        minutes = (df[h_col].astype(int) - 1) * 60 + (df[i_col].astype(int) - 1) * 15
        naive = base + pd.to_timedelta(minutes, unit="m")

    # Central prevailing → UTC; repeated fall-back hour flagged "Y" is the
    # second (standard-time) occurrence → ambiguous=False
    ambiguous = (df[flag_col].astype(str).str.upper() != "Y") if flag_col else True
    ts = naive.dt.tz_localize("America/Chicago", ambiguous=ambiguous,
                              nonexistent="shift_forward").dt.tz_convert("UTC")

    nodes = df[node_col].astype(str).str.upper()
    prices = pd.to_numeric(df[spp_col], errors="coerce")

    out = pd.DataFrame({"ts": ts, "node_id": nodes, "lmp": prices}).dropna()
    out = out.drop_duplicates(subset=["ts", "node_id"], keep="first")
    return [
        {"ts": r.ts.to_pydatetime(), "iso": "ERCOT", "node_id": r.node_id,
         "node_name": r.node_id, "market": market, "lmp": float(r.lmp),
         "energy": None, "congestion": None, "loss": None}
        for r in out.itertuples()
    ]


def backfill_ercot(start_year: int, markets: list[str], replace: bool) -> None:
    import io
    import zipfile

    from kardashev import _ercot_lmp as ercot

    for market in markets:
        mkt = market.upper()
        if replace:
            n = _delete_iso_market("ERCOT", mkt)
            log.info("ERCOT %s: deleted %d existing rows (--replace)", mkt, n)

        docs = ercot.list_mis_docs(_ERCOT_REPORT_IDS[market])
        for doc in docs:
            name = str(doc.get("FriendlyName", ""))
            try:
                year = int(name.rsplit("_", 1)[-1])
            except ValueError:
                continue
            if year < start_year:
                continue

            log.info("ERCOT %s %d: downloading %s", mkt, year, name)
            content = ercot.download_mis_doc(doc["DocID"])
            with zipfile.ZipFile(io.BytesIO(content)) as zf:
                xlsx = [n for n in zf.namelist() if n.endswith(".xlsx")]
                if not xlsx:
                    log.warning("ERCOT %s %d: no xlsx in zip", mkt, year)
                    continue
                xl = pd.ExcelFile(io.BytesIO(zf.read(xlsx[0])))

            year_rows = 0
            for sheet in xl.sheet_names:
                rows = _ercot_sheet_to_rows(xl.parse(sheet), mkt)
                year_rows += _upsert(rows)
            log.info("ERCOT %s %d: %d rows", mkt, year, year_rows)


# ---------------------------------------------------------------------------
# CAISO — OASIS per-node chunked queries
# ---------------------------------------------------------------------------

def _chunks(start: date, end: date, days: int):
    cur = start
    while cur <= end:
        yield cur, min(cur + timedelta(days=days - 1), end)
        cur += timedelta(days=days)


def backfill_caiso(start: date, end: date, markets: list[str]) -> None:
    from kardashev import _caiso as caiso

    from ingest.jobs import _CAISO_PRICE_AREAS, _caiso_oasis_to_lmp_rows

    plans = []
    if "da" in markets:
        plans.append(("DA", caiso.get_lmp_dam, _CAISO_DA_CHUNK_DAYS))
    if "rt" in markets:
        plans.append(("RT", caiso.get_lmp_rtm, _CAISO_RT_CHUNK_DAYS))

    for mkt, fetch, chunk_days in plans:
        for node_id, node_name in _CAISO_PRICE_AREAS:
            node_rows = 0
            for s, e in _chunks(start, end, chunk_days):
                try:
                    df = fetch(node_id, s, e)
                    rows = _caiso_oasis_to_lmp_rows(df, node_id, node_name, mkt)
                    node_rows += _upsert(rows)
                except Exception as exc:
                    log.warning("CAISO %s %s %s→%s failed: %s", mkt, node_name, s, e, exc)
                time.sleep(_OASIS_SLEEP_S)
            log.info("CAISO %s %s: %d rows (%s → %s)", mkt, node_name, node_rows, start, end)


# ---------------------------------------------------------------------------

def main() -> None:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s %(message)s")
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("iso", choices=["ercot", "caiso"])
    ap.add_argument("--markets", default="da,rt",
                    help="comma-separated: da,rt (default both)")
    ap.add_argument("--start-year", type=int, default=2019,
                    help="ERCOT: earliest yearly file to load")
    ap.add_argument("--start", type=lambda s: datetime.strptime(s, "%Y-%m-%d").date(),
                    help="CAISO: range start (YYYY-MM-DD)")
    ap.add_argument("--end", type=lambda s: datetime.strptime(s, "%Y-%m-%d").date(),
                    default=date.today() - timedelta(days=1),
                    help="CAISO: range end (default yesterday)")
    ap.add_argument("--replace", action="store_true",
                    help="delete existing rows for this ISO+market before loading")
    args = ap.parse_args()

    markets = [m.strip().lower() for m in args.markets.split(",") if m.strip()]
    if args.iso == "ercot":
        backfill_ercot(args.start_year, markets, args.replace)
    else:
        if not args.start:
            ap.error("caiso requires --start")
        backfill_caiso(args.start, args.end, markets)


if __name__ == "__main__":
    main()
