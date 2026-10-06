# syntax=docker/dockerfile:1

FROM ghcr.io/astral-sh/uv:0.11.18 AS uv

FROM debian:bookworm-slim AS web-build
ARG FLUTTER_VERSION=3.47.3
ARG FLUTTER_REVISION=e8113bf45620cbeb8aff64947ee4c93e16adb4cf
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl git unzip xz-utils libglu1-mesa \
    && rm -rf /var/lib/apt/lists/*
RUN git clone --depth 1 --branch "${FLUTTER_VERSION}" https://github.com/flutter/flutter.git /opt/flutter \
    && test "$(git -C /opt/flutter rev-parse HEAD)" = "${FLUTTER_REVISION}"
ENV PATH="/opt/flutter/bin:${PATH}" \
    TAR_OPTIONS=--no-same-owner
RUN flutter config --no-analytics && flutter precache --web
WORKDIR /src
COPY frontend/.flutter-version frontend/pubspec.yaml frontend/pubspec.lock ./
RUN test "$(cat .flutter-version)" = "${FLUTTER_VERSION}" \
    && flutter pub get --enforce-lockfile
COPY frontend/lib/ ./lib/
COPY frontend/web/ ./web/
# Same-origin API URLs; ship renderer assets and disable offline app caching.
RUN flutter build web --release --no-pub --no-web-resources-cdn --pwa-strategy=none

FROM python:3.12.13-slim-bookworm AS python-base

FROM python-base AS backend-build
COPY --from=uv /uv /usr/local/bin/uv
ENV UV_PYTHON_DOWNLOADS=never UV_LINK_MODE=copy UV_COMPILE_BYTECODE=1
WORKDIR /app
COPY backend/pyproject.toml backend/uv.lock backend/.python-version ./
RUN uv sync --locked --no-dev --no-install-project

FROM python-base AS runtime
ENV PATH="/app/.venv/bin:${PATH}" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    TRIPS_DB=/data/trips.sqlite3 \
    WEB_DIR=/app/web \
    TZ=Asia/Almaty
WORKDIR /app
RUN groupadd --gid 10001 app \
    && useradd --uid 10001 --gid app --no-create-home --shell /usr/sbin/nologin app \
    && mkdir /data \
    && chown app:app /data
COPY --from=backend-build /app/.venv /app/.venv
COPY backend/app/ ./app/
COPY backend/data/trips.json backend/data/demo_trips.json ./examples/
COPY --from=web-build /src/build/web/ ./web/
USER 10001:10001
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=3s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import os, urllib.request; urllib.request.urlopen(f'http://127.0.0.1:{os.environ.get(\"PORT\", \"8000\")}/health', timeout=2).close()"]
# Hosts such as Render set PORT. SEED_FILE optionally imports trips on every start;
# the import is idempotent, and a failed seed must not block the server.
CMD ["sh", "-c", "if [ -n \"$SEED_FILE\" ]; then python -m app.import_trips \"$SEED_FILE\" || true; fi; exec uvicorn app.main:app --host 0.0.0.0 --port \"${PORT:-8000}\""]
