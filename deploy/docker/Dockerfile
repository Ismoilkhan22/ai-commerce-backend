# syntax=docker/dockerfile:1.7
# Backend image (22 §2): bitta image, buyruqlar — api | outbox-worker | task-worker | scheduler | migrate.
#   docker build -f deploy/docker/Dockerfile -t cos-backend:$(git rev-parse --short HEAD) .

ARG PYTHON_VERSION=3.12

# ---------- 1. builder: uv bilan virtualenv (faqat runtime bog'liqliklar; loyiha o'zi o'rnatilmaydi —
#            kod /app'da, PYTHONPATH orqali; alembic migratsiyalari fayl sifatida kerak) ----------
FROM ghcr.io/astral-sh/uv:0.9-python${PYTHON_VERSION}-bookworm-slim AS builder
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=0 \
    UV_PROJECT_ENVIRONMENT=/app/.venv
WORKDIR /app
# Avval faqat bog'liqliklar — kod o'zgarsa bu qatlam keshdan olinadi
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --locked --no-dev --no-install-project

# ---------- 2. runtime: slim, non-root, uv yo'q ----------
FROM python:${PYTHON_VERSION}-slim-bookworm AS runtime
ARG APP_VERSION=dev
ENV PATH=/app/.venv/bin:$PATH \
    PYTHONPATH=/app \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    APP_VERSION=${APP_VERSION}
RUN groupadd --system --gid 10001 app \
    && useradd --system --uid 10001 --gid app --home-dir /app --shell /usr/sbin/nologin app
WORKDIR /app
COPY --from=builder --chown=root:root /app/.venv /app/.venv
# alembic.ini + migratsiyalar fayl sifatida kerak (script_location = app/db/migrations/<schema>)
COPY --chown=root:root alembic.ini ./
COPY --chown=root:root app ./app
COPY --chown=root:root --chmod=755 deploy/docker/entrypoint.sh /usr/local/bin/cos
# Lokal fayl ombori (STORAGE_BACKEND=local) uchun yagona yoziladigan joy — volume ulanadi
RUN mkdir -p /app/var/storage && chown app:app /app/var /app/var/storage
USER app
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=3s --start-period=20s --retries=3 \
    CMD ["python", "-c", "import os,urllib.request,sys; sys.exit(0) if os.environ.get('SERVICE_NAME','api')!='api' else urllib.request.urlopen('http://127.0.0.1:8000/health/live', timeout=2)"]
ENTRYPOINT ["cos"]
CMD ["api"]
