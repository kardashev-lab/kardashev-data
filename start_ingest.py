"""Migrate schema, run one-time cleanup, then run the ingest scheduler."""
import logging

from db.cleanup import run as cleanup
from db.migrate import run as migrate
from ingest.scheduler import start

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

if __name__ == "__main__":
    migrate()
    cleanup()
    start()
