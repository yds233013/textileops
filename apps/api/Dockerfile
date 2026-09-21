# TextileOps API and worker image.
#
#   docker build -t textileops-api apps/api
#   docker run -e DATABASE_URL=... -e JWT_SECRET=... textileops-api            # API
#   docker run -e ... textileops-api python -m textileops.workers.runner       # worker
#
# One image, two processes: the worker is the same code with a different
# command, so they can never drift apart in version.
FROM python:3.11-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Dependencies first, so a code change does not reinstall them.
COPY pyproject.toml ./
RUN mkdir -p textileops && touch textileops/__init__.py \
    && pip install --upgrade pip \
    && pip install . \
    && rm -rf textileops

COPY alembic.ini ./
COPY alembic ./alembic
COPY textileops ./textileops
COPY scripts/start-api.sh scripts/start-worker.sh ./scripts/
RUN pip install --no-deps . \
    && useradd --create-home --uid 10001 textileops \
    && mkdir -p /app/var/uploads \
    && chown -R textileops /app/var \
    && chmod +x scripts/*.sh

USER textileops

ENV ENVIRONMENT=production \
    LOG_JSON=true \
    DEBUG=false \
    UPLOAD_DIR=/app/var/uploads \
    PORT=8000

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
  CMD python -c "import os,urllib.request,sys; sys.exit(0 if urllib.request.urlopen(f'http://127.0.0.1:{os.environ.get(\"PORT\",\"8000\")}/api/v1/health', timeout=4).status==200 else 1)"

CMD ["./scripts/start-api.sh"]
