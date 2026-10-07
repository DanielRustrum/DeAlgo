FROM python:3.12-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PAMPHLETS_DATA_DIR=/data \
    PAMPHLETS_PORT=8080

WORKDIR /app

# Dependencies first so code edits do not invalidate the wheel layer.
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY pyproject.toml README.md LICENSE ./
COPY pamphlets ./pamphlets
RUN pip install --no-cache-dir --no-deps .

# The database lives on a volume; the app itself owns nothing else on disk.
RUN useradd --create-home --uid 10001 pamphlets \
    && mkdir -p /data \
    && chown -R pamphlets:pamphlets /data /app
USER pamphlets
VOLUME ["/data"]
EXPOSE 8080

# Reads the port from the environment, so changing PAMPHLETS_PORT does not leave
# the container permanently unhealthy.
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import os,sys,urllib.request; port=os.getenv('PAMPHLETS_PORT','8080'); sys.exit(0 if urllib.request.urlopen(f'http://127.0.0.1:{port}/healthz', timeout=4).status == 200 else 1)"

ENTRYPOINT ["pamphlets"]
CMD ["serve"]
