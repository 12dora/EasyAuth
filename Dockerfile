# syntax=docker/dockerfile:1

# EasyAuth container image.
# Multi-stage: build the React frontend once on the native build platform (its output
# is architecture-independent static assets), then assemble a per-target Python runtime.
# Built for linux/amd64 (Linux x86-64) and linux/arm64 (Apple Silicon / ARM).

########################  Stage 1 — frontend build  ########################
FROM --platform=$BUILDPLATFORM node:22-bookworm-slim@sha256:53ada149d435c38b14476cb57e4a7da73c15595aba79bd6971b547ceb6d018bf AS frontend
WORKDIR /app
ENV CI=1
RUN corepack enable && corepack prepare pnpm@11.2.2 --activate

# Workspace manifests first so `pnpm install` layer is cached independently of source.
COPY pnpm-workspace.yaml pnpm-lock.yaml ./
COPY frontend/package.json ./frontend/package.json
RUN pnpm install --frozen-lockfile

# Frontend source + production build.
# Vite emits into ../src/easyauth/static/easyauth/frontend (see frontend/vite.config.ts).
COPY frontend/ ./frontend/
RUN pnpm --filter @easyauth/frontend build

########################  Stage 2 — python runtime  ########################
FROM python:3.12-slim-bookworm@sha256:8a7e7cc04fd3e2bd787f7f24e22d5d119aa590d429b50c95dfe12b3abe52f48b AS runtime
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    DJANGO_SETTINGS_MODULE=easyauth.config.settings.base \
    PYTHONPATH=/app/src \
    PATH="/app/.venv/bin:$PATH" \
    UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1
WORKDIR /app

# uv (fast, lockfile-faithful installs).
COPY --from=ghcr.io/astral-sh/uv:0.8.22@sha256:9874eb7afe5ca16c363fe80b294fe700e460df29a55532bbfea234a0f12eddb1 /uv /usr/local/bin/uv

# Minimal runtime OS deps. psycopg[binary] ships its own libpq; curl powers the healthcheck.
RUN apt-get update \
 && apt-get install -y --no-install-recommends curl iptables util-linux \
 && rm -rf /var/lib/apt/lists/*

# Runtime Python deps (locked, no dev extras). Cached independently of the app source.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project \
 && uv cache clean

# Application source (imported via PYTHONPATH=/app/src).
COPY src/ ./src/
COPY manage.py ./
COPY deploy/webhook-worker-entrypoint.sh ./deploy/webhook-worker-entrypoint.sh

# Built frontend assets (Vite manifest + hashed bundles + brand assets).
COPY --from=frontend /app/src/easyauth/static/easyauth/frontend/ ./src/easyauth/static/easyauth/frontend/

# Run as a non-root user.
RUN useradd --system --uid 10001 easyauth \
 && chmod 0755 /app/deploy/webhook-worker-entrypoint.sh \
 && chown -R easyauth:easyauth /app
USER easyauth

EXPOSE 8001

# Requires the app to be configured (DATABASE_URL etc.); the process fails fast otherwise.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD curl -fsS http://localhost:8001/health/ || exit 1

CMD ["gunicorn", "easyauth.config.wsgi:application", \
     "--bind", "0.0.0.0:8001", "--workers", "4", "--timeout", "60"]
