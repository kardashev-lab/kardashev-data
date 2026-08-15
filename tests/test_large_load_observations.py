"""HTTP: Large-Load Filing Observations keep restatements."""
from __future__ import annotations

from datetime import date

import api.routes.ercot_large_load as ll_route


def _obs(month, report, mw, url):
    return {
        "snapshot_month": date.fromisoformat(month) if isinstance(month, str) else month,
        "report_date": date.fromisoformat(report),
        "total_mw": mw,
        "colocated_mw": None,
        "standalone_mw": None,
        "by_status": None,
        "by_size_bucket": None,
        "by_type": None,
        "by_zone": None,
        "approved_to_energize_mw": None,
        "planning_studies_approved_mw": None,
        "trailing_12mo": None,
        "source_url": url,
        "extracted_at": None,
    }


MARCH = [
    _obs("2026-03-01", "2026-03-10", 238629, "https://ercot.com/decks/march-original"),
    _obs("2026-03-01", "2026-03-25", 410618, "https://ercot.com/decks/march-updated"),
    _obs("2026-03-01", "2026-04-15", 418998, "https://ercot.com/decks/april-restatement"),
]


def test_observations_keep_restated_month(client, monkeypatch):
    async def fake_fetch(sql, **params):
        return list(MARCH)

    monkeypatch.setattr(ll_route, "fetch", fake_fetch)
    res = client.get("/ercot/large-load/observations", params={"snapshot_month": "2026-03-01"})
    assert res.status_code == 200
    body = res.json()
    assert len(body) == 3
    totals = [row["total_mw"] for row in body]
    assert totals == [238629, 410618, 418998]


def test_as_of_march_known_in_april_uses_then_published_deck(client, monkeypatch):
    captured: dict = {}

    async def fake_fetch(sql, **params):
        captured["sql"] = " ".join(sql.split())
        captured["params"] = params
        on = params["on"]
        return [row for row in MARCH if row["report_date"] <= on][-1:]

    monkeypatch.setattr(ll_route, "fetch", fake_fetch)
    res = client.get(
        "/ercot/large-load/as-of",
        params={"month": "2026-03-01", "on": "2026-04-01"},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["total_mw"] == 410618
    assert "ercot_large_load_observations" in captured["sql"]
    assert "report_date <=" in captured["sql"]
