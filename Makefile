# 23-dev-setup-and-workflow §3–4
SCHEMAS := platform audit catalog commerce messaging sales_ai storefront support reporting
COMPOSE := docker compose -f deploy/docker-compose.yml

.PHONY: install up down bootstrap run lint format typecheck imports test check migrate seed

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
