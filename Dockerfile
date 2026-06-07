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

# Default: API service. Override in Railway dashboard per service:
#   api:    python -m db.migrate && uvicorn api.main:app --host 0.0.0.0 --port $PORT
#   ingest: python -m db.migrate && python -m ingest.scheduler
CMD ["sh", "-c", "python -m db.migrate && uvicorn api.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
