#!/bin/sh
# Bitta image — bir nechta jarayon (22 §2). Makefile maqsadlari bilan bir xil buyruqlar.
#   cos api | outbox-worker | task-worker | scheduler | migrate | bootstrap | <boshqa buyruq>
set -eu

SCHEMAS="platform audit catalog commerce messaging sales_ai storefront support reporting"

cmd="${1:-api}"
[ "$#" -gt 0 ] && shift

case "$cmd" in
  api)
    # Kirish logi ilovaning o'zida (query qiymatlarisiz, 09 §4.2); X-Forwarded-For'ni ilova o'qiydi
    # (TRUSTED_PROXIES, app/shared/client_ip.py) — shuning uchun --no-proxy-headers
    export SERVICE_NAME="${SERVICE_NAME:-api}"
    exec uvicorn app.main:app \
      --host 0.0.0.0 --port "${PORT:-8000}" \
      --workers "${WEB_CONCURRENCY:-2}" \
      --no-access-log --no-proxy-headers \
      --timeout-graceful-shutdown 20 "$@"
    ;;
  outbox-worker)
    export SERVICE_NAME="${SERVICE_NAME:-outbox-worker}"
    exec python -m app.workers.outbox_worker "$@"
    ;;
  task-worker)
    export SERVICE_NAME="${SERVICE_NAME:-task-worker}"
    exec arq app.workers.task_worker.WorkerSettings "$@"
    ;;
  scheduler)
    export SERVICE_NAME="${SERVICE_NAME:-scheduler}"
    exec python -m app.workers.scheduler "$@"
    ;;
  bootstrap)
    # Rollar + schemalar + huquqlar (idempotent). DATABASE_ADMIN_URL faqat shu yerda kerak
    exec python -m app.db.bootstrap
    ;;
  migrate)
    # Bir martalik: bootstrap (idempotent) → har schema o'z Alembic env'i bilan (ADR-035, 22 §6.4)
    export SERVICE_NAME="${SERVICE_NAME:-migrate}"
    if [ -n "${DATABASE_ADMIN_URL:-}" ]; then
      python -m app.db.bootstrap
    fi
    for s in $SCHEMAS; do
      echo "migrate: $s"
      alembic -n "$s" upgrade head
    done
    ;;
  *)
    exec "$cmd" "$@"
    ;;
esac
