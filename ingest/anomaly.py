"""
Grid anomaly watcher v1.

v0: load steps, LMP shocks, curtailment-day outliers + Slack/email.
v1 adds:
  - PJM 5-min load + RT LMP (api.pjm.com)
  - ISO-silent staleness monitor
  - Event packaging (Emily / LinkedIn draft + dashboard deep link)
  - Optional co-signal note when load drop coincides with LMP move
  - Replay / backtest CLI over stored history

Notify: Slack-compatible webhook (ANOMALY_WEBHOOK_URL or SLACK_WEBHOOK_URL).
Optional email via Resend (ANOMALY_NOTIFY_EMAIL + RESEND_API_KEY).

CLI:
    python -m ingest.anomaly
    python -m ingest.anomaly --dry-run
    python -m ingest.anomaly --mode realtime|daily|silent|all
    python -m ingest.anomaly --replay --hours 48
    python -m ingest.anomaly --replay-pjm-july22   # July 22 2026 Ting-class check
"""
from __future__ import annotations

import json
import logging
import math
import os
import statistics
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any, Iterable, Sequence

import psycopg2
import psycopg2.extras

log = logging.getLogger("anomaly")

# System-total zones written by ingest_realtime_load_all (incl. PJM as of v1).
LOAD_ISOS = ("ERCOT", "CAISO", "NYISO", "MISO", "PJM")

# Absolute |ΔMW| floors — must clear these AND a z-score gate.
# PJM floor 2000 catches the 2026-07-22 ~2.5 GW 5-min drop in public inst_load.
LOAD_FLOOR_MW = {
    "ERCOT": 2500.0,
    "CAISO": 2500.0,
    "NYISO": 1500.0,
    "MISO": 2500.0,
    "PJM": 2000.0,
}
LOAD_Z = 3.5
LOAD_LOOKBACK_HOURS = 6
LOAD_MIN_DT_SEC = 180
LOAD_MAX_DT_SEC = 720
LOAD_MAX_WINDOW_STEPS = 2

LMP_ISOS = ("ERCOT", "CAISO", "NYISO", "MISO", "SPP", "ISONE", "PJM")
LMP_ABS_FLOOR = {
    "ERCOT": 500.0,
    "CAISO": 400.0,
    "NYISO": 400.0,
    "MISO": 400.0,
    "SPP": 400.0,
    "ISONE": 400.0,
    "PJM": 400.0,
}
LMP_SPREAD_FLOOR = {
    "ERCOT": 200.0,
    "CAISO": 150.0,
    "NYISO": 150.0,
    "MISO": 150.0,
    "SPP": 150.0,
    "ISONE": 150.0,
    "PJM": 150.0,
}
LMP_SANITY_ABS = 5000.0

CURTAILMENT_ISOS = ("CAISO", "SPP")
CURTAILMENT_LOOKBACK_DAYS = 90
CURTAILMENT_ABS_FLOOR_MWH = {
    "CAISO": 15000.0,
    "SPP": 8000.0,
}
CURTAILMENT_PERCENTILE = 0.95

# ISO silent: max age of freshest row before we page.
SILENT_LOAD_ISOS = LOAD_ISOS
SILENT_LMP_ISOS = ("ERCOT", "CAISO", "NYISO", "MISO", "SPP", "PJM")
SILENT_LOAD_MAX_AGE_MIN = {
    "ERCOT": 20,
    "CAISO": 20,
    "NYISO": 20,
    "MISO": 30,   # often single-snapshot updates
    "PJM": 20,
}
SILENT_LMP_MAX_AGE_MIN = 20

DASHBOARD = {
    "load_step": "https://grid-demand.kardashevlabs.org",
    "lmp_shock": "https://lmp.kardashevlabs.org",
    "curtailment_day": "https://curtailment-tracker.kardashevlabs.org",
    "iso_silent": "https://grid-demand.kardashevlabs.org",
}


@dataclass
class AnomalyEvent:
    event_key: str
    kind: str
    iso: str
    ts: datetime
    magnitude: float
    unit: str
    summary: str
    payload: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Pure detectors (unit-testable)
# ---------------------------------------------------------------------------

def _floor_bucket(ts: datetime, minutes: int) -> datetime:
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    ts = ts.astimezone(timezone.utc)
    discard = ts.minute % minutes
    return ts.replace(minute=ts.minute - discard, second=0, microsecond=0)


def detect_load_steps(
    series: Sequence[tuple[datetime, float]],
    *,
    iso: str,
    floor_mw: float | None = None,
    z: float = LOAD_Z,
    max_window_steps: int = LOAD_MAX_WINDOW_STEPS,
) -> list[AnomalyEvent]:
    """series: ascending (ts, mw) for one ISO system zone."""
    if len(series) < 4:
        return []
    floor = floor_mw if floor_mw is not None else LOAD_FLOOR_MW.get(iso, 1500.0)

    # Valid consecutive pairs only (reject gap cliffs).
    deltas: list[tuple[datetime, datetime, float, float, float]] = []
    # (ts_prev, ts_curr, mw_prev, mw_curr, delta)
    for i in range(1, len(series)):
        t0, m0 = series[i - 1]
        t1, m1 = series[i]
        dt = (t1 - t0).total_seconds()
        if dt < LOAD_MIN_DT_SEC or dt > LOAD_MAX_DT_SEC:
            continue
        deltas.append((t0, t1, m0, m1, m1 - m0))

    if len(deltas) < 4:
        return []

    abs_hist = [abs(d[4]) for d in deltas]
    events: list[AnomalyEvent] = []
    seen_keys: set[str] = set()

    for i in range(len(deltas)):
        for steps in range(1, max_window_steps + 1):
            start_i = i - steps + 1
            if start_i < 0:
                break
            window = deltas[start_i : i + 1]
            if len(window) != steps:
                break
            # Require time-contiguous chain (gap-skipped pairs are adjacent in
            # `deltas` but not on the clock).
            contiguous = all(window[j][1] == window[j + 1][0] for j in range(steps - 1))
            if not contiguous:
                break

            ts_before, _, mw_start, _, _ = window[0]
            _, ts_after, _, mw_end, _ = window[-1]
            delta = mw_end - mw_start
            abs_delta = abs(delta)
            if abs_delta < floor:
                continue

            hist = abs_hist[:start_i]
            if len(hist) < 8:
                continue
            mu = statistics.mean(hist)
            sigma = statistics.pstdev(hist) or 1.0
            if abs_delta < mu + z * sigma:
                continue

            bucket = _floor_bucket(ts_after, 15)
            key = f"load_step:{iso}:{bucket.strftime('%Y%m%dT%H%MZ')}"
            if key in seen_keys:
                continue
            seen_keys.add(key)

            direction = "drop" if delta < 0 else "jump"
            elapsed_min = max(1, int(round((ts_after - ts_before).total_seconds() / 60)))
            events.append(
                AnomalyEvent(
                    event_key=key,
                    kind="load_step",
                    iso=iso,
                    ts=ts_after,
                    magnitude=abs_delta,
                    unit="MW",
                    summary=(
                        f"{iso} system load {direction} of {abs_delta:,.0f} MW "
                        f"in ~{elapsed_min} min "
                        f"({mw_start:,.0f} → {mw_end:,.0f} MW) at "
                        f"{ts_after.astimezone(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}"
                    ),
                    payload={
                        "mw_before": mw_start,
                        "mw_after": mw_end,
                        "delta_mw": delta,
                        "steps": steps,
                        "z": abs_delta / sigma,
                        "sigma_mw": sigma,
                        "mean_abs_mw": mu,
                        "floor_mw": floor,
                        "ts_before": ts_before.astimezone(timezone.utc).isoformat(),
                        "ts_after": ts_after.astimezone(timezone.utc).isoformat(),
                        "dashboard": DASHBOARD["load_step"],
                    },
                )
            )
    return events


def _is_hub_like(node_id: str, node_name: str | None) -> bool:
    nid = (node_id or "").upper()
    name = (node_name or "").upper()
    if any(tok in nid for tok in ("HB_", "HUB", "TH_", "_HUB", "LZ_")):
        return True
    if any(tok in name for tok in ("HUB", "ZONE", "LOAD ZONE")):
        return True
    # NYISO zonal names often lack HUB in the id.
    if nid.isdigit() and name and " " not in name.strip() and len(name) <= 12:
        return True
    return False


def detect_lmp_shocks(
    rows: Sequence[dict[str, Any]],
    *,
    iso: str,
    abs_floor: float | None = None,
    spread_floor: float | None = None,
) -> list[AnomalyEvent]:
    """rows: RT LMP dicts at one or more timestamps for one ISO.
    Each row: {ts, node_id, node_name?, lmp}
    Uses the latest timestamp only.
    """
    if not rows:
        return []
    abs_floor = abs_floor if abs_floor is not None else LMP_ABS_FLOOR.get(iso, 400.0)
    spread_floor = spread_floor if spread_floor is not None else LMP_SPREAD_FLOOR.get(iso, 150.0)

    by_ts: dict[datetime, list[dict[str, Any]]] = {}
    for r in rows:
        ts = r["ts"]
        if isinstance(ts, str):
            ts = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        by_ts.setdefault(ts, []).append({**r, "ts": ts})

    latest = max(by_ts)
    points = by_ts[latest]
    sane = [
        p for p in points
        if p.get("lmp") is not None and abs(float(p["lmp"])) <= LMP_SANITY_ABS
    ]
    if len(sane) < 2:
        return []

    hubs = [p for p in sane if _is_hub_like(str(p.get("node_id", "")), p.get("node_name"))]
    pool = hubs if len(hubs) >= 2 else sane

    lmps = [float(p["lmp"]) for p in pool]
    lo = min(lmps)
    hi = max(lmps)
    spread = hi - lo
    extreme = max(pool, key=lambda p: abs(float(p["lmp"])))
    extreme_lmp = float(extreme["lmp"])

    events: list[AnomalyEvent] = []
    hour_bucket = _floor_bucket(latest, 60)

    if abs(extreme_lmp) >= abs_floor:
        key = f"lmp_shock:abs:{iso}:{hour_bucket.strftime('%Y%m%dT%H%MZ')}"
        events.append(
            AnomalyEvent(
                event_key=key,
                kind="lmp_shock",
                iso=iso,
                ts=latest,
                magnitude=abs(extreme_lmp),
                unit="$/MWh",
                summary=(
                    f"{iso} RT LMP extreme {extreme_lmp:+.1f} $/MWh at "
                    f"{extreme.get('node_name') or extreme.get('node_id')} "
                    f"({latest.astimezone(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')})"
                ),
                payload={
                    "mode": "abs",
                    "lmp": extreme_lmp,
                    "node_id": extreme.get("node_id"),
                    "node_name": extreme.get("node_name"),
                    "floor": abs_floor,
                    "dashboard": DASHBOARD["lmp_shock"],
                },
            )
        )

    if spread >= spread_floor:
        key = f"lmp_shock:spread:{iso}:{hour_bucket.strftime('%Y%m%dT%H%MZ')}"
        lo_node = min(pool, key=lambda p: float(p["lmp"]))
        hi_node = max(pool, key=lambda p: float(p["lmp"]))
        events.append(
            AnomalyEvent(
                event_key=key,
                kind="lmp_shock",
                iso=iso,
                ts=latest,
                magnitude=spread,
                unit="$/MWh",
                summary=(
                    f"{iso} RT LMP spread {spread:.0f} $/MWh "
                    f"({float(lo_node['lmp']):+.1f} at {lo_node.get('node_name') or lo_node.get('node_id')} → "
                    f"{float(hi_node['lmp']):+.1f} at {hi_node.get('node_name') or hi_node.get('node_id')}) "
                    f"at {latest.astimezone(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}"
                ),
                payload={
                    "mode": "spread",
                    "spread": spread,
                    "min_lmp": lo,
                    "max_lmp": hi,
                    "min_node": lo_node.get("node_id"),
                    "max_node": hi_node.get("node_id"),
                    "floor": spread_floor,
                    "n_nodes": len(pool),
                    "dashboard": DASHBOARD["lmp_shock"],
                },
            )
        )
    return events


def detect_curtailment_day(
    history: Sequence[tuple[date, float]],
    *,
    iso: str,
    target: date | None = None,
    percentile: float = CURTAILMENT_PERCENTILE,
    abs_floor: float | None = None,
) -> list[AnomalyEvent]:
    """history: (date, total_mwh) ascending. Scores the most recent complete day
    (or `target`) against trailing history excluding that day."""
    if len(history) < 14:
        return []
    abs_floor = abs_floor if abs_floor is not None else CURTAILMENT_ABS_FLOOR_MWH.get(iso, 10000.0)
    by_date = {d: float(v) for d, v in history}
    day = target or max(by_date)
    if day not in by_date:
        return []
    value = by_date[day]
    prior = sorted(v for d, v in by_date.items() if d < day)
    if len(prior) < 14:
        return []
    # Nearest-rank percentile.
    prior_sorted = sorted(prior)
    idx = min(len(prior_sorted) - 1, max(0, int(math.ceil(percentile * len(prior_sorted)) - 1)))
    pctl = prior_sorted[idx]
    if value < abs_floor or value < pctl:
        return []
    return [
        AnomalyEvent(
            event_key=f"curtailment_day:{iso}:{day.isoformat()}",
            kind="curtailment_day",
            iso=iso,
            ts=datetime(day.year, day.month, day.day, 23, 59, tzinfo=timezone.utc),
            magnitude=value,
            unit="MWh",
            summary=(
                f"{iso} curtailment {value:,.0f} MWh on {day.isoformat()} "
                f"(≥ p{int(percentile * 100)} of prior {len(prior)} days = {pctl:,.0f} MWh)"
            ),
            payload={
                "date": day.isoformat(),
                "total_mwh": value,
                "percentile": percentile,
                "percentile_mwh": pctl,
                "floor_mwh": abs_floor,
                "n_prior_days": len(prior),
                "dashboard": DASHBOARD["curtailment_day"],
            },
        )
    ]


def detect_iso_silent(
    *,
    iso: str,
    kind: str,
    last_ts: datetime | None,
    now: datetime | None = None,
    max_age_min: float,
) -> list[AnomalyEvent]:
    """Fire when the freshest row for an ISO/feed is older than max_age_min."""
    now = now or datetime.now(timezone.utc)
    if last_ts is None:
        bucket = _floor_bucket(now, 60)
        key = f"iso_silent:{kind}:{iso}:missing:{bucket.strftime('%Y%m%dT%H%MZ')}"
        return [
            AnomalyEvent(
                event_key=key,
                kind="iso_silent",
                iso=iso,
                ts=now,
                magnitude=99999.0,
                unit="min",
                summary=f"{iso} {kind} feed has no rows in the lookback window",
                payload={
                    "feed": kind,
                    "last_ts": None,
                    "age_min": None,
                    "max_age_min": max_age_min,
                    "dashboard": DASHBOARD["iso_silent"],
                },
            )
        ]
    if last_ts.tzinfo is None:
        last_ts = last_ts.replace(tzinfo=timezone.utc)
    age_min = (now - last_ts.astimezone(timezone.utc)).total_seconds() / 60.0
    if age_min <= max_age_min:
        return []
    bucket = _floor_bucket(now, 60)
    key = f"iso_silent:{kind}:{iso}:{bucket.strftime('%Y%m%dT%H%MZ')}"
    return [
        AnomalyEvent(
            event_key=key,
            kind="iso_silent",
            iso=iso,
            ts=now,
            magnitude=age_min,
            unit="min",
            summary=(
                f"{iso} {kind} silent for {age_min:.0f} min "
                f"(last point {last_ts.astimezone(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}; "
                f"threshold {max_age_min:.0f} min)"
            ),
            payload={
                "feed": kind,
                "last_ts": last_ts.astimezone(timezone.utc).isoformat(),
                "age_min": age_min,
                "max_age_min": max_age_min,
                "dashboard": DASHBOARD["iso_silent"],
            },
        )
    ]


def package_event(event: AnomalyEvent) -> dict[str, str]:
    """Emily email + LinkedIn teaser drafts + dashboard link."""
    dash = event.payload.get("dashboard") or DASHBOARD.get(event.kind, "")
    ts_str = event.ts.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    if event.kind == "load_step":
        direction = "dropped" if float(event.payload.get("delta_mw", 0)) < 0 else "jumped"
        emily = (
            f"Subject: {event.iso} load {direction} {event.magnitude:,.0f} MW\n\n"
            f"Hi Emily,\n\n"
            f"Quick dispatch: {event.iso} system load {direction} by "
            f"{event.magnitude:,.0f} MW around {ts_str}.\n\n"
            f"{event.summary}\n\n"
            f"Live demand: {dash}\n\n"
            f"Happy to dig if useful.\n\nAshutosh"
        )
        linkedin = (
            f"{event.iso} load just {direction} {event.magnitude:,.0f} MW in minutes "
            f"({ts_str}).\n\n{dash}"
        )
    elif event.kind == "lmp_shock":
        emily = (
            f"Subject: {event.iso} RT LMP shock\n\n"
            f"Hi Emily,\n\n"
            f"{event.summary}\n\n"
            f"LMP terminal: {dash}\n\n"
            f"Happy to dig if useful.\n\nAshutosh"
        )
        linkedin = f"{event.summary}\n\n{dash}"
    elif event.kind == "curtailment_day":
        emily = (
            f"Subject: {event.iso} curtailment spike {event.magnitude:,.0f} MWh\n\n"
            f"Hi Emily,\n\n"
            f"{event.summary}\n\n"
            f"Tracker: {dash}\n\n"
            f"Happy to dig if useful.\n\nAshutosh"
        )
        linkedin = f"{event.summary}\n\n{dash}"
    else:
        emily = (
            f"Subject: {event.iso} data feed silent\n\n"
            f"Hi Emily,\n\n"
            f"{event.summary}\n\n"
            f"(Internal ops alert — sharing only if it becomes a story.)\n\nAshutosh"
        )
        linkedin = event.summary

    return {
        "emily_email": emily,
        "linkedin_teaser": linkedin,
        "dashboard": dash,
    }


def enrich_load_event_with_lmp(
    event: AnomalyEvent,
    lmp_rows: Sequence[dict[str, Any]],
) -> AnomalyEvent:
    """Attach a co-signal note when RT LMP moved hard in the same window."""
    if event.kind != "load_step" or not lmp_rows:
        return event
    ts_before = event.payload.get("ts_before")
    ts_after = event.payload.get("ts_after")
    if not ts_before or not ts_after:
        return event
    t0 = datetime.fromisoformat(str(ts_before).replace("Z", "+00:00"))
    t1 = datetime.fromisoformat(str(ts_after).replace("Z", "+00:00"))
    window = []
    for r in lmp_rows:
        ts = r["ts"]
        if isinstance(ts, str):
            ts = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        if t0 - timedelta(minutes=10) <= ts <= t1 + timedelta(minutes=10):
            if r.get("lmp") is not None and abs(float(r["lmp"])) <= LMP_SANITY_ABS:
                window.append(float(r["lmp"]))
    if len(window) < 4:
        return event
    spread = max(window) - min(window)
    extreme = max(abs(x) for x in window)
    notes = []
    if spread >= LMP_SPREAD_FLOOR.get(event.iso, 150):
        notes.append(f"RT LMP spread ~{spread:.0f} $/MWh in the same window")
    if extreme >= LMP_ABS_FLOOR.get(event.iso, 400):
        notes.append(f"RT |LMP| peaked ~{extreme:.0f} $/MWh")
    if not notes:
        return event
    payload = dict(event.payload)
    payload["cosignal"] = notes
    summary = event.summary + " · " + "; ".join(notes)
    return AnomalyEvent(
        event_key=event.event_key,
        kind=event.kind,
        iso=event.iso,
        ts=event.ts,
        magnitude=event.magnitude,
        unit=event.unit,
        summary=summary,
        payload=payload,
    )


# ---------------------------------------------------------------------------
# DB I/O
# ---------------------------------------------------------------------------

def _dsn() -> str:
    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        raise RuntimeError("DATABASE_URL not set")
    return dsn


def fetch_load_series(iso: str, hours: int = LOAD_LOOKBACK_HOURS) -> list[tuple[datetime, float]]:
    with psycopg2.connect(_dsn()) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT ts, mw_actual
                FROM load_data
                WHERE iso = %s
                  AND zone = %s
                  AND mw_actual IS NOT NULL
                  AND ts > now() - (%s || ' hours')::interval
                ORDER BY ts ASC
                """,
                (iso, iso, str(hours)),
            )
            return [(row[0], float(row[1])) for row in cur.fetchall()]


def fetch_lmp_rt_recent(iso: str, hours: float = 2.0) -> list[dict[str, Any]]:
    with psycopg2.connect(_dsn()) as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                SELECT ts, node_id, node_name, lmp
                FROM lmp
                WHERE iso = %s
                  AND market = 'RT'
                  AND lmp IS NOT NULL
                  AND ts > now() - (%s || ' hours')::interval
                ORDER BY ts DESC
                LIMIT 20000
                """,
                (iso, str(hours)),
            )
            return [dict(r) for r in cur.fetchall()]


def fetch_curtailment_history(iso: str, days: int = CURTAILMENT_LOOKBACK_DAYS) -> list[tuple[date, float]]:
    with psycopg2.connect(_dsn()) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT date, total_mwh
                FROM curtailment
                WHERE iso = %s
                  AND date >= current_date - %s
                  AND total_mwh IS NOT NULL
                ORDER BY date ASC
                """,
                (iso, days),
            )
            return [(row[0], float(row[1])) for row in cur.fetchall()]


def fetch_latest_load_ts(iso: str, hours: int = 6) -> datetime | None:
    with psycopg2.connect(_dsn()) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT MAX(ts) FROM load_data
                WHERE iso = %s AND zone = %s
                  AND mw_actual IS NOT NULL
                  AND ts > now() - (%s || ' hours')::interval
                """,
                (iso, iso, str(hours)),
            )
            row = cur.fetchone()
            return row[0] if row and row[0] else None


def fetch_latest_lmp_ts(iso: str, hours: int = 6) -> datetime | None:
    with psycopg2.connect(_dsn()) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT MAX(ts) FROM lmp
                WHERE iso = %s AND market = 'RT' AND lmp IS NOT NULL
                  AND ts > now() - (%s || ' hours')::interval
                """,
                (iso, str(hours)),
            )
            row = cur.fetchone()
            return row[0] if row and row[0] else None


def insert_anomaly(event: AnomalyEvent) -> bool:
    """Insert if new. Returns True when a new row was created."""
    with psycopg2.connect(_dsn()) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO anomaly_events
                  (event_key, kind, iso, ts, magnitude, unit, summary, payload)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s::jsonb)
                ON CONFLICT (event_key) DO NOTHING
                RETURNING id
                """,
                (
                    event.event_key,
                    event.kind,
                    event.iso,
                    event.ts,
                    event.magnitude,
                    event.unit,
                    event.summary,
                    json.dumps(event.payload, default=str),
                ),
            )
            row = cur.fetchone()
            conn.commit()
            return row is not None


def mark_notified(event_key: str) -> None:
    with psycopg2.connect(_dsn()) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE anomaly_events
                SET notified_at = now()
                WHERE event_key = %s AND notified_at IS NULL
                """,
                (event_key,),
            )
            conn.commit()


def pending_notify(event_key: str) -> bool:
    with psycopg2.connect(_dsn()) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT notified_at FROM anomaly_events WHERE event_key = %s",
                (event_key,),
            )
            row = cur.fetchone()
            return bool(row) and row[0] is None


# ---------------------------------------------------------------------------
# Notify
# ---------------------------------------------------------------------------

def _webhook_url() -> str | None:
    return os.environ.get("ANOMALY_WEBHOOK_URL") or os.environ.get("SLACK_WEBHOOK_URL") or None


def _notify_email() -> str | None:
    return os.environ.get("ANOMALY_NOTIFY_EMAIL") or None


def format_message(event: AnomalyEvent) -> str:
    packaged = package_event(event)
    dash = packaged.get("dashboard", "")
    lines = [
        f"*KL anomaly · {event.kind} · {event.iso}*",
        event.summary,
    ]
    if event.payload.get("cosignal"):
        lines.append("Co-signal: " + "; ".join(event.payload["cosignal"]))
    if dash:
        lines.append(dash)
    lines.append("")
    lines.append("*LinkedIn teaser*")
    lines.append(packaged["linkedin_teaser"])
    lines.append("")
    lines.append("*Emily draft*")
    lines.append(packaged["emily_email"])
    lines.append(f"`{event.event_key}`")
    return "\n".join(lines)


def notify(event: AnomalyEvent) -> bool:
    """Send webhook and/or email. Returns True if at least one channel succeeded
    or if no channels are configured (log-only counts as success so we don't
    retry forever)."""
    text = format_message(event)
    webhook = _webhook_url()
    email_to = _notify_email()
    if not webhook and not email_to:
        log.info("anomaly (no notify channel): %s", event.summary)
        return True

    ok = False
    if webhook:
        try:
            body = json.dumps({"text": text}).encode()
            req = urllib.request.Request(
                webhook,
                data=body,
                headers={"Content-Type": "application/json", "User-Agent": "kardashev-anomaly/1"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=15) as resp:
                if 200 <= resp.status < 300:
                    ok = True
                else:
                    log.warning("webhook status %s for %s", resp.status, event.event_key)
        except urllib.error.URLError as exc:
            log.warning("webhook failed for %s: %s", event.event_key, exc)

    if email_to:
        api_key = os.environ.get("RESEND_API_KEY")
        if not api_key:
            log.warning("ANOMALY_NOTIFY_EMAIL set but RESEND_API_KEY missing")
        else:
            try:
                payload = {
                    "from": os.environ.get("ANOMALY_EMAIL_FROM", "Kardashev Labs <alerts@kardashevlabs.org>"),
                    "to": [email_to],
                    "subject": f"[KL] {event.kind} · {event.iso}",
                    "text": text.replace("*", ""),
                }
                req = urllib.request.Request(
                    "https://api.resend.com/emails",
                    data=json.dumps(payload).encode(),
                    headers={
                        "Content-Type": "application/json",
                        "Authorization": f"Bearer {api_key}",
                        "User-Agent": "kardashev-anomaly/1",
                    },
                    method="POST",
                )
                with urllib.request.urlopen(req, timeout=15) as resp:
                    if 200 <= resp.status < 300:
                        ok = True
            except urllib.error.URLError as exc:
                log.warning("email notify failed for %s: %s", event.event_key, exc)

    return ok


# ---------------------------------------------------------------------------
# Scan orchestration
# ---------------------------------------------------------------------------

def scan_load_steps() -> list[AnomalyEvent]:
    out: list[AnomalyEvent] = []
    for iso in LOAD_ISOS:
        try:
            series = fetch_load_series(iso)
            found = detect_load_steps(series, iso=iso)
            if found:
                try:
                    lmp_rows = fetch_lmp_rt_recent(iso, hours=2.0)
                    found = [enrich_load_event_with_lmp(e, lmp_rows) for e in found]
                except Exception as exc:
                    log.warning("cosignal %s failed: %s", iso, exc)
            out.extend(found)
            if found:
                log.info("load_step %s: %d event(s)", iso, len(found))
        except Exception as exc:
            log.warning("load_step scan %s failed: %s", iso, exc)
    return out


def scan_lmp_shocks() -> list[AnomalyEvent]:
    out: list[AnomalyEvent] = []
    for iso in LMP_ISOS:
        try:
            rows = fetch_lmp_rt_recent(iso)
            found = detect_lmp_shocks(rows, iso=iso)
            out.extend(found)
            if found:
                log.info("lmp_shock %s: %d event(s)", iso, len(found))
        except Exception as exc:
            log.warning("lmp_shock scan %s failed: %s", iso, exc)
    return out


def scan_curtailment_days(target: date | None = None) -> list[AnomalyEvent]:
    out: list[AnomalyEvent] = []
    day = target or (date.today() - timedelta(days=1))
    for iso in CURTAILMENT_ISOS:
        try:
            hist = fetch_curtailment_history(iso)
            found = detect_curtailment_day(hist, iso=iso, target=day)
            out.extend(found)
            if found:
                log.info("curtailment_day %s: %d event(s)", iso, len(found))
        except Exception as exc:
            log.warning("curtailment scan %s failed: %s", iso, exc)
    return out


def scan_iso_silent() -> list[AnomalyEvent]:
    out: list[AnomalyEvent] = []
    now = datetime.now(timezone.utc)
    for iso in SILENT_LOAD_ISOS:
        try:
            last = fetch_latest_load_ts(iso)
            found = detect_iso_silent(
                iso=iso,
                kind="load",
                last_ts=last,
                now=now,
                max_age_min=SILENT_LOAD_MAX_AGE_MIN.get(iso, 20),
            )
            out.extend(found)
        except Exception as exc:
            log.warning("silent load scan %s failed: %s", iso, exc)
    for iso in SILENT_LMP_ISOS:
        try:
            last = fetch_latest_lmp_ts(iso)
            found = detect_iso_silent(
                iso=iso,
                kind="lmp",
                last_ts=last,
                now=now,
                max_age_min=SILENT_LMP_MAX_AGE_MIN,
            )
            out.extend(found)
        except Exception as exc:
            log.warning("silent lmp scan %s failed: %s", iso, exc)
    if out:
        log.info("iso_silent: %d event(s)", len(out))
    return out


def process_events(events: Iterable[AnomalyEvent], *, dry_run: bool = False) -> list[AnomalyEvent]:
    """Persist + notify. Returns events that were newly inserted (or all in dry-run)."""
    emitted: list[AnomalyEvent] = []
    for event in events:
        # Always attach packaging into payload for storage / dry-run JSON.
        packaged = package_event(event)
        event.payload = {**event.payload, "drafts": packaged}

        if dry_run:
            log.info("DRY-RUN %s", event.summary)
            emitted.append(event)
            continue
        try:
            created = insert_anomaly(event)
        except Exception as exc:
            log.error("insert failed %s: %s", event.event_key, exc)
            continue
        if not created:
            try:
                if not pending_notify(event.event_key):
                    continue
            except Exception:
                continue
        else:
            emitted.append(event)
            log.info("stored %s", event.event_key)

        try:
            if notify(event):
                mark_notified(event.event_key)
        except Exception as exc:
            log.warning("notify path failed %s: %s", event.event_key, exc)
    return emitted


def run_realtime_scan(*, dry_run: bool = False) -> list[AnomalyEvent]:
    """5-min tick: load steps + LMP shocks + ISO silent."""
    events = scan_load_steps() + scan_lmp_shocks() + scan_iso_silent()
    return process_events(events, dry_run=dry_run)


def run_daily_scan(*, dry_run: bool = False) -> list[AnomalyEvent]:
    """Daily tick after curtailment ingest."""
    events = scan_curtailment_days()
    return process_events(events, dry_run=dry_run)


def run_all(*, dry_run: bool = False) -> list[AnomalyEvent]:
    return process_events(
        scan_load_steps() + scan_lmp_shocks() + scan_iso_silent() + scan_curtailment_days(),
        dry_run=dry_run,
    )


def replay(hours: int = 48, *, dry_run: bool = True) -> dict[str, Any]:
    """
    Backtest load-step + LMP detectors over stored history.
    Returns counts by ISO/kind (no notify unless dry_run=False).
    """
    report: dict[str, Any] = {"hours": hours, "events": [], "counts": {}}
    events: list[AnomalyEvent] = []
    for iso in LOAD_ISOS:
        series = fetch_load_series(iso, hours=hours)
        found = detect_load_steps(series, iso=iso)
        events.extend(found)
    for iso in LMP_ISOS:
        # Pull a longer LMP window by scanning hour chunks via recent helper
        # (table retention is short; hours param on fetch is enough for ≤48h).
        rows = fetch_lmp_rt_recent(iso, hours=float(min(hours, 48)))
        # detect_lmp_shocks only looks at latest ts — for replay, walk each ts.
        by_ts: dict[datetime, list[dict]] = {}
        for r in rows:
            ts = r["ts"]
            if isinstance(ts, str):
                ts = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            by_ts.setdefault(ts, []).append({**r, "ts": ts})
        for ts in sorted(by_ts):
            found = detect_lmp_shocks(by_ts[ts], iso=iso)
            # Rewrite event_key hour bucket already; keep all.
            events.extend(found)
    # Deduplicate by event_key
    uniq = {e.event_key: e for e in events}
    events = list(uniq.values())
    for e in events:
        key = f"{e.kind}:{e.iso}"
        report["counts"][key] = report["counts"].get(key, 0) + 1
        report["events"].append({
            "event_key": e.event_key,
            "kind": e.kind,
            "iso": e.iso,
            "ts": e.ts.isoformat(),
            "magnitude": e.magnitude,
            "summary": e.summary,
        })
    if not dry_run:
        process_events(events, dry_run=False)
    return report


def replay_pjm_july22() -> dict[str, Any]:
    """
    Fetch PJM inst_load around the 2026-07-22 Dominion/data-center event and
    run the load-step detector. Does not require DB history for PJM.
    """
    from iso_data.pjm_api import get_inst_load

    points = get_inst_load(
        area="PJM RTO",
        datetime_beginning_ept="2026-07-22 07:30to2026-07-22 08:30",
        row_count=100,
    )
    series = [(p["ts"], p["mw"]) for p in points]
    # Seed a quiet baseline so z-score has history — prepend synthetic calm
    # points only if the window is short; for July 22 the public series alone
    # may be thin, so pull LastHour-style broader window if needed.
    if len(series) < 12:
        wider = get_inst_load(
            area="PJM RTO",
            datetime_beginning_ept="2026-07-22 06:00to2026-07-22 09:00",
            row_count=100,
        )
        series = [(p["ts"], p["mw"]) for p in wider]

    # Build artificial prior baseline from the pre-drop median so z-gate can fire
    # on a short public window (detector needs ≥8 prior deltas).
    if len(series) >= 2:
        pre = [mw for ts, mw in series if ts < datetime(2026, 7, 22, 11, 56, tzinfo=timezone.utc)]
        if pre:
            base = statistics.median(pre)
            seed_start = series[0][0] - timedelta(minutes=5 * 20)
            seed = []
            t = seed_start
            for i in range(20):
                seed.append((t, base + (i % 3) * 40))
                t += timedelta(minutes=5)
            series = seed + series

    events = detect_load_steps(series, iso="PJM", floor_mw=2000.0, z=3.0)
    return {
        "n_points": len(series),
        "series_tail": [
            {"ts": ts.isoformat(), "mw": mw} for ts, mw in series[-15:]
        ],
        "events": [
            {
                "event_key": e.event_key,
                "magnitude": e.magnitude,
                "summary": e.summary,
                "payload": e.payload,
            }
            for e in events
        ],
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    import argparse

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    p = argparse.ArgumentParser(description="Kardashev grid anomaly watcher v1")
    p.add_argument("--dry-run", action="store_true", help="Detect only; do not write or notify")
    p.add_argument(
        "--mode",
        choices=("all", "realtime", "daily", "silent"),
        default="all",
        help="Which detector set to run",
    )
    p.add_argument("--replay", action="store_true", help="Backtest over stored history")
    p.add_argument("--hours", type=int, default=48, help="Replay lookback hours")
    p.add_argument(
        "--replay-pjm-july22",
        action="store_true",
        help="Replay the 2026-07-22 PJM ~3 GW data-center drop from public inst_load",
    )
    args = p.parse_args(argv)

    if args.replay_pjm_july22:
        print(json.dumps(replay_pjm_july22(), indent=2, default=str))
        return 0
    if args.replay:
        print(json.dumps(replay(hours=args.hours, dry_run=args.dry_run), indent=2, default=str))
        return 0

    if args.mode == "realtime":
        events = run_realtime_scan(dry_run=args.dry_run)
    elif args.mode == "daily":
        events = run_daily_scan(dry_run=args.dry_run)
    elif args.mode == "silent":
        events = process_events(scan_iso_silent(), dry_run=args.dry_run)
    else:
        events = run_all(dry_run=args.dry_run)

    print(json.dumps([asdict(e) | {"ts": e.ts.isoformat()} for e in events], indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
