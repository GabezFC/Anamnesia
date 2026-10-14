# Anamnésia: local-first image. Built and verified with `docker build` + `anamnesia version` + GET /health.
# ANA-221: pinned by digest (multi-arch image index of python:3.14-slim, read from the Docker Hub registry
# API on 2026-10-12 via HEAD /v2/library/python/manifests/3.14-slim). The digest freezes the base layer;
# it does NOT receive security patches by itself: refresh it on purpose (docs/guides/QUICKSTART.md).
FROM python:3.14-slim@sha256:a2b82f3c48559aa0a8446d9af49826b6e2b2016f4cd2afabfe6013ec53729170

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    # Everything the app WRITES (.env with the local token, benchmark.db, logs) lives in the /data volume.
    ANAMNESIA_HOME=/data \
    # Inside the container the app must bind 0.0.0.0 so the published port reaches it.
    # The HOST side stays loopback-only: see docker-compose.yml (127.0.0.1:8000:8000).
    MG_HOST=0.0.0.0

WORKDIR /app
COPY . /app
RUN pip install . && rm -rf /app/* \
    && useradd --create-home --uid 10001 anamnesia \
    && mkdir /data && chown anamnesia:anamnesia /data

USER anamnesia
VOLUME ["/data"]
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=4).status == 200 else 1)"

CMD ["anamnesia", "start"]
