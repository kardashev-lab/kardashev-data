FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc libpq-dev libreoffice-impress \
    && rm -rf /var/lib/apt/lists/*

# Copy everything before install (editable install needs source present)
COPY . .

# Regular non-editable install for production containers
RUN pip install --no-cache-dir ".[api,ingest]"

ENV PYTHONUNBUFFERED=1

# Default: API service (run.py migrates, then serves uvicorn).
# Override start command for ingest service in Railway dashboard:
#   ingest: python /app/start_ingest.py
CMD ["python", "/app/run.py"]
