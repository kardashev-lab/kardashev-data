"""Migrate schema, then run the ingest scheduler."""
from db.migrate import run as migrate
from ingest.scheduler import start

if __name__ == "__main__":
    migrate()
    start()
