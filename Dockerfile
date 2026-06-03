FROM python:3.12-slim

WORKDIR /app

# System deps (including photo processing)
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    libpq5 \
    libsm6 \
    libxext6 \
    libxrender-dev \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md requirements.lock /app/
RUN pip install --no-cache-dir -r requirements.lock && pip install --no-cache-dir --no-deps .

COPY . /app

# Create non-root user and ensure data directory is writable
RUN useradd --system --no-create-home appuser \
    && mkdir -p /data \
    && chown appuser:appuser /data

ENV PYTHONUNBUFFERED=1
ENV SEED_DB_PATH=/data/seed.db
ENV PYTHONPATH=/app

EXPOSE 8000

# Switch to non-root user
USER appuser

# Health check — actually probe the /health endpoint
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')" || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
