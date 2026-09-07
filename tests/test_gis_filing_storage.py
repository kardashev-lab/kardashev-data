"""Real PostgreSQL coverage. Set GIS_TEST_DATABASE_URL to a disposable database."""
import hashlib
import os
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import psycopg2
import pytest

from ingest.writer import save_ercot_gis_filing


@pytest.fixture()
def gis_db(monkeypatch):
    dsn = os.environ.get("GIS_TEST_DATABASE_URL")
    if not dsn:
        pytest.skip("Set GIS_TEST_DATABASE_URL for isolated PostgreSQL tests")
    dsn = psycopg2.extensions.make_dsn(dsn, client_encoding="UTF8")
    namespace = "gis_test_" + uuid4().hex
    conn = psycopg2.connect(dsn)
    conn.autocommit = True
    with conn.cursor() as cur:
        cur.execute(f'CREATE SCHEMA "{namespace}"')
        cur.execute(f'SET search_path TO "{namespace}"')
    monkeypatch.setenv("DATABASE_URL", psycopg2.extensions.make_dsn(dsn, options=f"-c search_path={namespace}"))
    schema = (Path(__file__).parents[1] / "db/schema.sql").read_text()
    try:
        with conn.cursor() as cur:
            # Apply the pre-migration schema, seed legacy history, then migrate twice.
            before, rest = schema.split("-- Source-level GIS history.", 1)
            after = rest[rest.index("-- ---------------------------------------------------------------------------\n-- Precomputed timeline"):]
            cur.execute(before + after)
            cur.execute("INSERT INTO ercot_gis_snapshots (queue_id, snapshot_month, capacity_mw) VALUES ('legacy', '2026-06', 10)")
            cur.execute(schema)
            cur.execute(schema)
        yield conn, schema
    finally:
        with conn.cursor() as cur:
            cur.execute(f'DROP SCHEMA "{namespace}" CASCADE')
        conn.close()


def filing(doc="new", day=2, content=b"original", version="1", projects=(("A", 200),)):
    rows = [(qid, "2026-06", qid, None, "Travis", "North", None, "SOL", None, mw,
             None, None, None, None, None, None, None, None) for qid, mw in projects]
    return dict(source_document_id=doc, source_url=f"https://example.com/{doc}", source_name="GIS_Report_Jun2026",
                published_at=datetime(2026, 7, day, tzinfo=timezone.utc), snapshot_month="2026-06",
                content_sha256=hashlib.sha256(content).hexdigest(), raw_file=content, parser_version=version, rows=rows)


def test_history_corrections_replays_and_legacy_preservation(gis_db):
    conn, schema = gis_db
    assert save_ercot_gis_filing(**filing(projects=(("A", 200), ("B", 50)))) == 2
    assert save_ercot_gis_filing(**filing(content=b"correction", projects=(("A", 300),))) == 1
    assert save_ercot_gis_filing(**filing(content=b"correction", projects=(("A", 300),))) == 0
    # An earlier filing arriving later cannot supersede the corrected July 2 filing.
    assert save_ercot_gis_filing(**filing(doc="old", day=1, projects=(("A", 100),))) == 1
    # A corrected parser retains both extracts for the same source file.
    assert save_ercot_gis_filing(**filing(content=b"correction", version="2", projects=(("A", 310),))) == 1
    with conn.cursor() as cur:
        cur.execute("SELECT queue_id, capacity_mw FROM ercot_gis_snapshots")
        assert cur.fetchall() == [("A", 310)]
        cur.execute("SELECT capacity_mw FROM ercot_gis_observations WHERE queue_id = 'A' ORDER BY filing_id")
        assert [r[0] for r in cur.fetchall()] == [200, 300, 100, 310]
        cur.execute("SELECT raw_file FROM ercot_gis_filings ORDER BY filing_id")
        assert [bytes(r[0]) for r in cur.fetchall()] == [b"original", b"correction", b"original", b"correction"]
        cur.execute(schema)
        cur.execute("SELECT queue_id, capacity_mw FROM ercot_gis_legacy_snapshots")
        assert cur.fetchall() == [("legacy", 10)]


def test_invalid_extraction_rolls_back_entire_filing(gis_db):
    conn, _ = gis_db
    save_ercot_gis_filing(**filing())
    with pytest.raises(psycopg2.IntegrityError):
        save_ercot_gis_filing(**filing(doc="bad", projects=(("A", 200), ("A", 300))))
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM ercot_gis_filings")
        assert cur.fetchone()[0] == 1
        cur.execute("SELECT capacity_mw FROM ercot_gis_snapshots")
        assert cur.fetchone()[0] == 200
