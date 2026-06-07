FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy everything first (no split — editable install needs source present)
COPY . .

# Regular (non-editable) install — correct for production containers
RUN pip install --no-cache-dir ".[api,ingest]"

ENV PYTHONUNBUFFERED=1

# Default: API service (migration runs inside FastAPI lifespan).
# Override start command for ingest service in Railway dashboard:
#   ingest: python -m db.migrate && python -m ingest.scheduler
CMD ["sh", "-c", "uvicorn api.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
