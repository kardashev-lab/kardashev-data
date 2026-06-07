"""API entry point — reads PORT from env and starts uvicorn."""
import os
import uvicorn

port = int(os.environ.get("PORT", 8000))
print(f"Starting on 0.0.0.0:{port}", flush=True)
uvicorn.run("api.main:app", host="0.0.0.0", port=port, log_level="info")
