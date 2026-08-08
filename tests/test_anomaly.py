"""Unit tests for anomaly detectors (no DB required)."""
from datetime import date, datetime, timedelta, timezone

from ingest.anomaly import (
    AnomalyEvent,
    detect_curtailment_day,
    detect_iso_silent,
    detect_lmp_shocks,
    detect_load_steps,
    format_email_body,
    format_message,
    package_event,
    slack_payload,
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
    # Confirming sample after trough (stays down).
    values = baseline + [100_050, 97_050, 97_100]
    events = detect_load_steps(_series(start, values), iso="ERCOT", floor_mw=1500, z=3.0)
    assert len(events) >= 1
    e = events[0]
    assert e.kind == "load_step"
    assert e.iso == "ERCOT"
    assert e.magnitude >= 2900
    assert "drop" in e.summary


def test_load_step_ignores_interim_glitch_that_rebounds():
    """MISO/PJM-style bad :00 stamp that snaps back next interval."""
    start = datetime(2026, 8, 8, 12, 0, tzinfo=timezone.utc)
    baseline = [98_000 + (i % 3) * 40 for i in range(20)]
    values = baseline + [98_893, 74_366, 99_419]  # -24 GW then full rebound
    assert detect_load_steps(_series(start, values), iso="MISO") == []


def test_load_step_defers_without_confirming_sample():
    start = datetime(2026, 7, 22, 11, 0, tzinfo=timezone.utc)
    baseline = [100_000 + (i % 3) * 50 for i in range(20)]
    values = baseline + [100_050, 97_050]  # drop at end of series — wait for next point
    assert detect_load_steps(_series(start, values), iso="ERCOT", floor_mw=1500, z=3.0) == []


def test_load_step_pjm_one_second_correction_is_glitch():
    start = datetime(2026, 8, 8, 13, 0, tzinfo=timezone.utc)
    series = _series(start, [106_000 + (i % 3) * 20 for i in range(20)], step_min=5)
    t_bad = series[-1][0] + timedelta(minutes=5)
    t_fix = t_bad + timedelta(seconds=1)
    series = series + [(t_bad, 94_082.0), (t_fix, 107_548.0)]
    assert detect_load_steps(series, iso="PJM") == []


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
    values = baseline + [99_050, 96_500, 96_480]  # -2550 MW, stays down
    events = detect_load_steps(_series(start, values), iso="PJM", floor_mw=2000, z=3.0)
    assert len(events) >= 1
    assert events[0].magnitude >= 2500


def test_lmp_abs_shock():
    ts = datetime(2026, 8, 2, 9, 10, tzinfo=timezone.utc)
    rows = [
        {"ts": ts, "node_id": "HB_NORTH", "node_name": "HB_NORTH", "lmp": 45.0},
        {"ts": ts, "node_id": "HB_WEST", "node_name": "HB_WEST", "lmp": 52.0},
        {"ts": ts, "node_id": "HB_HOUSTON", "node_name": "HB_HOUSTON", "lmp": 2500.0},
    ]
    events = detect_lmp_shocks(rows, iso="ERCOT", abs_floor=2000, spread_floor=800)
    kinds = {e.payload.get("mode") for e in events}
    assert "abs" in kinds
    assert any(e.magnitude >= 2500 for e in events)


def test_lmp_spread_shock():
    ts = datetime(2026, 8, 2, 9, 10, tzinfo=timezone.utc)
    rows = [
        {"ts": ts, "node_id": "TH_NP15", "node_name": "NP15", "lmp": -200.0},
        {"ts": ts, "node_id": "TH_SP15", "node_name": "SP15", "lmp": 1600.0},
        {"ts": ts, "node_id": "TH_ZP26", "node_name": "ZP26", "lmp": 40.0},
    ]
    events = detect_lmp_shocks(rows, iso="CAISO", abs_floor=2000, spread_floor=1500)
    assert any(e.payload.get("mode") == "spread" and e.magnitude >= 1500 for e in events)


def test_default_lmp_ignores_moderate_nyiso_spread():
    ts = datetime(2026, 8, 8, 21, 45, tzinfo=timezone.utc)
    rows = [
        {"ts": ts, "node_id": "WEST", "node_name": "WEST", "lmp": 30.0},
        {"ts": ts, "node_id": "N.Y.C.", "node_name": "N.Y.C.", "lmp": 660.0},
        {"ts": ts, "node_id": "LONGIL", "node_name": "LONGIL", "lmp": 200.0},
    ]
    assert detect_lmp_shocks(rows, iso="NYISO") == []


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
    hist.append((spike, 55_000.0))  # clears 45 GWh floor + p99
    events = detect_curtailment_day(hist, iso="CAISO", target=spike)
    assert len(events) == 1
    assert events[0].magnitude == 55_000.0


def test_curtailment_day_high_but_not_record_no_fire():
    """Summer-busy CAISO day (~24 GWh) is not breaking news under p99/45 GWh bar."""
    hist = [(date(2026, 6, 1) + timedelta(days=i), 3000.0 + (i % 7) * 200) for i in range(40)]
    spike = date(2026, 7, 11)
    hist.append((spike, 24_000.0))
    events = detect_curtailment_day(hist, iso="CAISO", target=spike)
    assert events == []


def test_default_lmp_ignores_routine_congestion():
    ts = datetime(2026, 8, 2, 9, 10, tzinfo=timezone.utc)
    rows = [
        {"ts": ts, "node_id": "HB_NORTH", "node_name": "HB_NORTH", "lmp": 45.0},
        {"ts": ts, "node_id": "HB_WEST", "node_name": "HB_WEST", "lmp": 120.0},
        {"ts": ts, "node_id": "HB_HOUSTON", "node_name": "HB_HOUSTON", "lmp": 780.0},
    ]
    # Defaults are scarcity-class; ~$780 / ~$735 spread is not news.
    assert detect_lmp_shocks(rows, iso="ERCOT") == []


def test_default_pjm_ting_class_drop_fires():
    start = datetime(2026, 7, 22, 11, 0, tzinfo=timezone.utc)
    baseline = [99_000 + (i % 3) * 30 for i in range(20)]
    values = baseline + [99_050, 96_500, 96_450]  # -2550 MW, confirmed
    events = detect_load_steps(_series(start, values), iso="PJM")
    assert len(events) >= 1
    assert events[0].magnitude >= 2500


def test_curtailment_day_normal_no_fire():
    hist = [(date(2026, 6, 1) + timedelta(days=i), 5000.0 + (i % 5) * 100) for i in range(40)]
    day = hist[-1][0]
    events = detect_curtailment_day(hist, iso="CAISO", target=day)
    assert events == []


def test_default_load_ignores_sub_floor_drop():
    start = datetime(2026, 7, 22, 11, 0, tzinfo=timezone.utc)
    baseline = [99_000 + (i % 3) * 30 for i in range(20)]
    values = baseline + [99_050, 97_050]  # -2000 MW — under PJM 2500 floor
    assert detect_load_steps(_series(start, values), iso="PJM") == []


def test_default_load_ignores_jump_even_if_large():
    start = datetime(2026, 7, 22, 11, 0, tzinfo=timezone.utc)
    baseline = [90_000 + (i % 3) * 30 for i in range(20)]
    values = baseline + [90_050, 94_050]  # +4000 MW jump
    assert detect_load_steps(_series(start, values), iso="ERCOT") == []


def test_should_page_skips_iso_silent_by_default():
    from ingest.anomaly import _should_page

    silent = AnomalyEvent(
        event_key="iso_silent:load:PJM:x",
        kind="iso_silent",
        iso="PJM",
        ts=datetime(2026, 8, 3, 12, 0, tzinfo=timezone.utc),
        magnitude=90.0,
        unit="min",
        summary="PJM load silent",
    )
    news = AnomalyEvent(
        event_key="load_step:PJM:x",
        kind="load_step",
        iso="PJM",
        ts=datetime(2026, 8, 3, 12, 0, tzinfo=timezone.utc),
        magnitude=3000.0,
        unit="MW",
        summary="drop",
    )
    assert _should_page(silent) is False
    assert _should_page(news) is True


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
    values = baseline + [100_050, 97_050, 97_000]
    events = detect_load_steps(_series(start, values), iso="PJM", floor_mw=1500, z=3.0)
    assert events
    drafts = package_event(events[0])
    assert "Hi Emily" in drafts["emily_email"]
    assert "grid-demand" in drafts["dashboard"]
    assert len(drafts["linkedin_teaser"]) > 20


def test_slack_message_is_readable_not_draft_dump():
    event = AnomalyEvent(
        event_key="load_step:PJM:20260722T1200Z",
        kind="load_step",
        iso="PJM",
        ts=datetime(2026, 7, 22, 12, 0, tzinfo=timezone.utc),
        magnitude=2500.0,
        unit="MW",
        summary=(
            "PJM system load drop of 2,500 MW in ~5 min "
            "(95,000 → 92,500 MW) at 2026-07-22 12:00 UTC"
        ),
        payload={
            "delta_mw": -2500.0,
            "dashboard": "https://grid-demand.kardashevlabs.org",
            "cosignal": ["RT LMP spread ~180 $/MWh in the same window"],
        },
    )
    slack = format_message(event)
    assert "PJM load drop: 2,500 MW" in slack
    assert "2026-07-22 12:00 UTC" in slack
    assert "grid-demand" in slack
    assert "Hi Emily" not in slack
    assert "LinkedIn" not in slack
    assert "Subject:" not in slack
    assert "KL anomaly" not in slack

    payload = slack_payload(event)
    assert "blocks" in payload
    assert payload["text"] == slack
    # Minimal: headline + optional button — no draft sections.
    assert len(payload["blocks"]) <= 3

    email = format_email_body(event)
    assert "Hi Emily" in email
    assert "LinkedIn" in email


def test_iso_silent_email_has_no_emily_drafts():
    event = AnomalyEvent(
        event_key="iso_silent:lmp:MISO:x",
        kind="iso_silent",
        iso="MISO",
        ts=datetime(2026, 8, 8, 11, 0, tzinfo=timezone.utc),
        magnitude=120.0,
        unit="min",
        summary="MISO lmp feed has no rows in the lookback window",
        payload={"feed": "lmp", "dashboard": "https://grid-demand.kardashevlabs.org"},
    )
    body = format_email_body(event)
    assert "Hi Emily" not in body
    assert "LinkedIn" not in body
    assert "MISO" in body
