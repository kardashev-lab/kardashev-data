"""Apply schema migration, then start uvicorn."""
import os

import uvicorn

from db.migrate import run as migrate

migrate()

port = int(os.environ.get("PORT", 8000))
print(f"Starting on 0.0.0.0:{port}", flush=True)
uvicorn.run("api.main:app", host="0.0.0.0", port=port, log_level="info")
