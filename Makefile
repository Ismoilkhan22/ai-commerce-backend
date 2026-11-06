# 23-dev-setup-and-workflow §3–4
SCHEMAS := platform audit catalog commerce messaging sales_ai storefront support reporting network
COMPOSE := docker compose -f deploy/docker-compose.yml

.PHONY: install up down bootstrap run worker outbox-worker task-worker scheduler lint format typecheck imports test check migrate seed reporting-backfill

install:
	uv sync

up:
	$(COMPOSE) up -d postgres redis

down:
	$(COMPOSE) down

# Lokal API. Kirish logi ilovaning o'zida (query qiymatlarisiz); X-Forwarded-For'ni uvicorn emas, ilova o'qiydi
# (TRUSTED_PROXIES, app/shared/client_ip.py) — shuning uchun --no-proxy-headers
run:
	uv run uvicorn app.main:app --port 8000 --reload --no-access-log --no-proxy-headers

# Fon ishlari (06 §2, 5a): lokalda uchalasi bitta jarayonda — outbox_worker + task_worker (arq) + scheduler.
# Production'da alohida: outbox-worker, task-worker, scheduler (22 §5)
worker:
	uv run python -m app.workers.dev

outbox-worker:
	uv run python -m app.workers.outbox_worker

task-worker:
	uv run arq app.workers.task_worker.WorkerSettings

scheduler:
	uv run python -m app.workers.scheduler

# Rollar (app_migrator, app_runtime) + schemalar + huquqlar (07 §10)
bootstrap:
	uv run python -m app.db.bootstrap

lint:
	uv run ruff check .
	uv run ruff format --check .

format:
	uv run ruff check --fix .
	uv run ruff format .

typecheck:
	uv run mypy

imports:
	uv run lint-imports

test:
	uv run pytest

# CI bilan bir xil tekshiruvlar
check: lint typecheck imports test

# Har schema o'z env'i bilan, platform → audit → qolganlari (ADR-035)
migrate:
	@for s in $(SCHEMAS); do uv run alembic -n $$s upgrade head; done

# Lokal demo ma'lumotlari: platforma jamoasi va turli holatdagi 8 ta shop (qayta ishga tushirish xavfsiz)
seed:
	uv run python -m app.db.seed.dev_seed

# Hisobot proyeksiyalarini mavjud ma'lumotdan qayta qurish (7c, bir martalik; worker to'xtatilgan bo'lsin)
reporting-backfill:
	uv run python -m app.workers.reporting_backfill
