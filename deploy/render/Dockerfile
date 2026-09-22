# TextileOps as ONE container: the hosted demo on Render.
#
#   docker build -f deploy/render/Dockerfile -t textileops .
#
# Two processes, one boundary:
#
#   Next.js (web)   0.0.0.0:$PORT     the only listener the platform exposes
#   FastAPI (api)   127.0.0.1:8000    loopback only: unreachable from outside;
#                                     the worker runs as a thread beside it
#                                     (apps/api/textileops/serve.py)
#
# The browser still talks only to the web origin, which proxies /api/v1 to the
# API (apps/web/app/api/v1/[...path]/route.ts) — the same boundary as separate
# services, without paying for two more instances. apps/api/Dockerfile and
# apps/web/Dockerfile remain the images for running them separately
# (infra/docker-compose.prod.yml, or a larger deployment).

# --- web build ----------------------------------------------------------------
FROM node:22-slim AS web
WORKDIR /web
ENV NEXT_TELEMETRY_DISABLED=1
COPY apps/web/package.json apps/web/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY apps/web ./
# Same-origin API: nothing about the API's address goes into the bundle.
ENV NEXT_PUBLIC_API_BASE_URL=
RUN npm run build

# --- runtime ------------------------------------------------------------------
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Node runtime for the standalone Next.js server (same Debian base, so glibc matches).
COPY --from=web /usr/local/bin/node /usr/local/bin/node

WORKDIR /app/api
COPY apps/api/pyproject.toml ./
RUN mkdir -p textileops && touch textileops/__init__.py \
    && pip install --upgrade pip \
    && pip install . \
    && rm -rf textileops
COPY apps/api/alembic.ini ./
COPY apps/api/alembic ./alembic
COPY apps/api/textileops ./textileops
# Bytecode compiled at build time: on a tenth of a CPU, compiling the
# application on every cold start costs seconds a visitor would wait through.
RUN pip install --no-deps . && python -m compileall -q /app/api/textileops

WORKDIR /app/web
COPY --from=web /web/.next/standalone ./
COPY --from=web /web/.next/static ./.next/static

COPY deploy/render/start.sh /app/start.sh
RUN useradd --create-home --uid 10001 textileops \
    && mkdir -p /app/var/uploads \
    && chown -R textileops /app/var \
    && chmod +x /app/start.sh

USER textileops
WORKDIR /app

ENV ENVIRONMENT=production \
    LOG_JSON=true \
    DEBUG=false \
    NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    UPLOAD_DIR=/app/var/uploads \
    PORT=10000

EXPOSE 10000
# No Docker HEALTHCHECK: Render uses healthCheckPath (render.yaml), which goes
# through the proxy to the database. A HEALTHCHECK here only spawned a Python
# process every 30 s — on a free instance's tenth of a CPU they piled up faster
# than they finished and starved the application they were checking.

CMD ["/app/start.sh"]
