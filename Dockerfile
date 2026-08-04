FROM python:3.12-slim

WORKDIR /app

# API image: no LibreOffice (that is ingest-only for monthly ERCOT LLWG PPTX).
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY . .

RUN pip install --no-cache-dir ".[api,ingest]"

ENV PYTHONUNBUFFERED=1

# Default: API service (run.py migrates, then serves uvicorn).
# Override start command for ingest in Railway, or use Dockerfile.ingest.
CMD ["python", "/app/run.py"]
