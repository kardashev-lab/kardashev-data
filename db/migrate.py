"""
Run schema migration. Safe to run multiple times (all statements are IF NOT EXISTS).

Usage:
    python -m db.migrate
    # or via entrypoint in Railway start command:
    python -m db.migrate && uvicorn api.main:app --host 0.0.0.0 --port $PORT
"""
import os
import sys
import time
from pathlib import Path

import psycopg2


def run(retries: int = 10, delay: float = 3.0):
    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        print("ERROR: DATABASE_URL not set", file=sys.stderr)
        sys.exit(1)

    schema = (Path(__file__).parent / "schema.sql").read_text()

    for attempt in range(1, retries + 1):
        try:
            conn = psycopg2.connect(dsn)
            try:
                with conn:
                    with conn.cursor() as cur:
                        cur.execute(schema)
                print("Migration complete")
                return
            finally:
                conn.close()
        except psycopg2.OperationalError as exc:
            if attempt == retries:
                print(f"Migration failed after {retries} attempts: {exc}", file=sys.stderr)
                sys.exit(1)
            print(f"DB not ready (attempt {attempt}/{retries}), retrying in {delay}s…")
            time.sleep(delay)


if __name__ == "__main__":
    run()
