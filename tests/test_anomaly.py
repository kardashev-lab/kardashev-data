"""Unit tests for anomaly detectors (no DB required)."""
from datetime import date, datetime, timedelta, timezone

from ingest.anomaly import (
    detect_curtailment_day,
    detect_iso_silent,
    detect_lmp_shocks,
    detect_load_steps,
    package_event,
)


def _series(start: datetime, values: list[float], step_min: int = 5):
    out = []
    t = start
    for v in values:
        out.append((t, v))
        t = t + timedelta(minutes=step_min)
    return out


def test_load_step_detects_sudden_drop():
    start = datetime(2026, 7, 22, 11, 0, tzinfo=timezone.utc)
    baseline = [100_000 + (i % 3) * 50 for i in range(20)]
    values = baseline + [100_050, 97_050]
    events = detect_load_steps(_series(start, values), iso="ERCOT", floor_mw=1500, z=3.0)
    assert len(events) >= 1
    e = events[0]
    assert e.kind == "load_step"
    assert e.iso == "ERCOT"
    assert e.magnitude >= 2900
    assert "drop" in e.summary


def test_load_step_ignores_gap_cliff():
    start = datetime(2026, 7, 22, 11, 0, tzinfo=timezone.utc)
    quiet = _series(start, [50_000 + i for i in range(15)], step_min=5)
    later = quiet[-1][0] + timedelta(hours=3)
    gapped = quiet + [(later, 40_000.0)]
    events = detect_load_steps(gapped, iso="CAISO", floor_mw=2000, z=2.0)
    assert events == []


def test_load_step_ignores_normal_ramp():
    start = datetime(2026, 8, 1, 12, 0, tzinfo=timezone.utc)
    values = [60_000 + i * 200 for i in range(24)]
    events = detect_load_steps(_series(start, values), iso="ERCOT", floor_mw=1500, z=3.0)
    assert events == []


def test_pjm_style_drop_at_floor_2000():
    start = datetime(2026, 7, 22, 11, 0, tzinfo=timezone.utc)
    baseline = [99_000 + (i % 3) * 30 for i in range(20)]
    values = baseline + [99_050, 96_500]  # -2550 MW
    events = detect_load_steps(_series(start, values), iso="PJM", floor_mw=2000, z=3.0)
    assert len(events) >= 1
    assert events[0].magnitude >= 2500


def test_lmp_abs_shock():
    ts = datetime(2026, 8, 2, 9, 10, tzinfo=timezone.utc)
    rows = [
        {"ts": ts, "node_id": "HB_NORTH", "node_name": "HB_NORTH", "lmp": 45.0},
        {"ts": ts, "node_id": "HB_WEST", "node_name": "HB_WEST", "lmp": 52.0},
        {"ts": ts, "node_id": "HB_HOUSTON", "node_name": "HB_HOUSTON", "lmp": 980.0},
    ]
    events = detect_lmp_shocks(rows, iso="ERCOT", abs_floor=500, spread_floor=200)
    kinds = {e.payload.get("mode") for e in events}
    assert "abs" in kinds
    assert any(e.magnitude >= 980 for e in events)


def test_lmp_spread_shock():
    ts = datetime(2026, 8, 2, 9, 10, tzinfo=timezone.utc)
    rows = [
        {"ts": ts, "node_id": "TH_NP15", "node_name": "NP15", "lmp": -80.0},
        {"ts": ts, "node_id": "TH_SP15", "node_name": "SP15", "lmp": 120.0},
        {"ts": ts, "node_id": "TH_ZP26", "node_name": "ZP26", "lmp": 40.0},
    ]
    events = detect_lmp_shocks(rows, iso="CAISO", abs_floor=500, spread_floor=150)
    assert any(e.payload.get("mode") == "spread" and e.magnitude >= 200 for e in events)


def test_lmp_filters_pathological_outlier():
    ts = datetime(2026, 8, 2, 9, 10, tzinfo=timezone.utc)
    rows = [
        {"ts": ts, "node_id": "A", "node_name": "HUB_A", "lmp": 40.0},
        {"ts": ts, "node_id": "B", "node_name": "HUB_B", "lmp": 42.0},
        {"ts": ts, "node_id": "BAD", "node_name": "HUB_BAD", "lmp": 50_000.0},
    ]
    events = detect_lmp_shocks(rows, iso="SPP", abs_floor=400, spread_floor=150)
    assert events == []


def test_curtailment_day_outlier():
    hist = [(date(2026, 6, 1) + timedelta(days=i), 3000.0 + (i % 7) * 200) for i in range(40)]
    spike = date(2026, 7, 11)
    hist.append((spike, 24_000.0))
    events = detect_curtailment_day(hist, iso="CAISO", target=spike)
    assert len(events) == 1
    assert events[0].magnitude == 24_000.0


def test_curtailment_day_normal_no_fire():
    hist = [(date(2026, 6, 1) + timedelta(days=i), 5000.0 + (i % 5) * 100) for i in range(40)]
    day = hist[-1][0]
    events = detect_curtailment_day(hist, iso="CAISO", target=day)
    assert events == []


def test_iso_silent_fires_when_stale():
    now = datetime(2026, 8, 3, 12, 0, tzinfo=timezone.utc)
    last = now - timedelta(minutes=45)
    events = detect_iso_silent(iso="PJM", kind="load", last_ts=last, now=now, max_age_min=20)
    assert len(events) == 1
    assert events[0].kind == "iso_silent"
    assert events[0].magnitude >= 45


def test_iso_silent_ok_when_fresh():
    now = datetime(2026, 8, 3, 12, 0, tzinfo=timezone.utc)
    last = now - timedelta(minutes=8)
    events = detect_iso_silent(iso="ERCOT", kind="load", last_ts=last, now=now, max_age_min=20)
    assert events == []


def test_package_event_has_emily_and_linkedin():
    start = datetime(2026, 7, 22, 11, 0, tzinfo=timezone.utc)
    baseline = [100_000 + (i % 3) * 50 for i in range(20)]
    values = baseline + [100_050, 97_050]
    events = detect_load_steps(_series(start, values), iso="PJM", floor_mw=1500, z=3.0)
    assert events
    drafts = package_event(events[0])
    assert "Hi Emily" in drafts["emily_email"]
    assert "grid-demand" in drafts["dashboard"]
    assert len(drafts["linkedin_teaser"]) > 20
