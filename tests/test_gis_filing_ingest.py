"""Exercise real XLSX extraction with simulated source revisions."""
import hashlib
import io

import pandas as pd
import pytest

from ingest import ercot_gis, writer


def workbook(mw=200):
    stream = io.BytesIO()
    pd.DataFrame([{"INR": "A", "Capacity (MW)": mw}]).to_excel(stream, sheet_name="Project Details", index=False)
    return stream.getvalue()


def test_revision_in_existing_month_is_not_skipped(monkeypatch):
    doc = {"DocID": "second", "FriendlyName": "GIS_Report_Jun2026", "PublishDate": "2026-07-02T12:00:00-05:00"}
    monkeypatch.setattr(ercot_gis, "list_gis_docs", lambda: [doc])
    # Original bug: all later documents were skipped when the month existed.
    monkeypatch.setattr(ercot_gis, "_existing_snapshot_months", lambda: {"2026-06"}, raising=False)
    known = set()
    monkeypatch.setattr(writer, "existing_ercot_gis_filings", lambda: known)
    content = [workbook()]
    monkeypatch.setattr(ercot_gis, "download_document", lambda _: content[0])
    monkeypatch.setattr(ercot_gis.time, "sleep", lambda _: None)
    saved = []

    def save(**filing):
        saved.append(filing)
        known.add((filing["source_document_id"], filing["published_at"], filing["content_sha256"], filing["parser_version"]))
        return len(filing["rows"])

    monkeypatch.setattr(writer, "save_ercot_gis_filing", save)
    assert ercot_gis.ingest_ercot_gis() == 1
    assert saved[0]["rows"][0][9] == 200
    assert saved[0]["source_document_id"] == "second"
    assert saved[0]["raw_file"] == content[0]
    assert ercot_gis.ingest_ercot_gis() == 0
    # Same ID/date, changed source bytes must survive as another observation.
    content[0] = workbook(300)
    assert ercot_gis.ingest_ercot_gis() == 1
    assert len(saved) == 2
    assert saved[1]["rows"][0][9] == 300
    assert saved[1]["content_sha256"] == hashlib.sha256(content[0]).hexdigest()
    # Parser fixes preserve the earlier extraction too.
    monkeypatch.setattr(ercot_gis, "PARSER_VERSION", "2")
    assert ercot_gis.ingest_ercot_gis() == 1


def test_dry_run_needs_no_database(monkeypatch):
    monkeypatch.setattr(ercot_gis, "list_gis_docs", lambda: [{
        "DocID": "1", "FriendlyName": "GIS_Report_Jun2026", "PublishDate": "2026-07-01T12:00:00"
    }])
    monkeypatch.setattr(ercot_gis, "download_document", lambda _: workbook())
    monkeypatch.setattr(ercot_gis.time, "sleep", lambda _: None)
    monkeypatch.setattr(writer, "existing_ercot_gis_filings", lambda: pytest.fail("Database accessed"))
    monkeypatch.setattr(writer, "save_ercot_gis_filing", lambda **_: pytest.fail("Database written"))
    assert ercot_gis.ingest_ercot_gis(dry_run=True) == 1


def test_naive_publication_date_uses_texas_timezone():
    result = ercot_gis.publication_time({"PublishDate": "2026-07-02T12:00:00"})
    assert result.isoformat() == "2026-07-02T12:00:00-05:00"
