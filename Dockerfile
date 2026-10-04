FROM python:3.12-slim

# Prevent Python from writing .pyc files and enable unbuffered output
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Install dependencies first (layer caching)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY app/ app/
COPY translations/ translations/
COPY manage.py .

# Create instance directory for SQLite DB
RUN useradd -m -u 1000 appuser \
    && mkdir -p /app/instance /app/logs \
    && chown -R appuser:appuser /app/instance /app/logs
USER appuser

EXPOSE 8400

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8400/health')" || exit 1

CMD ["python", "-m", "waitress", "--listen", "0.0.0.0:8400", "--threads", "4", "--call", "app:create_app"]
