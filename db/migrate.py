"""
Run schema migration. Safe to run multiple times (all statements are IF NOT EXISTS).

Usage:
    python -m db.migrate
    # or via entrypoint in Railway start command:
    python -m db.migrate && uvicorn api.main:app --host 0.0.0.0 --port $PORT
"""
import os
import sys
from pathlib import Path

import psycopg2


def run():
    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        print("ERROR: DATABASE_URL not set", file=sys.stderr)
        sys.exit(1)

    schema = (Path(__file__).parent / "schema.sql").read_text()

    conn = psycopg2.connect(dsn)
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(schema)
        print("Migration complete")
    finally:
        conn.close()


if __name__ == "__main__":
    run()
