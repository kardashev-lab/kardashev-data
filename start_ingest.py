"""Single entrypoint for the ingest service — migrate then schedule."""
from db.migrate import run as migrate
from ingest.scheduler import start

if __name__ == "__main__":
    migrate()
    start()
