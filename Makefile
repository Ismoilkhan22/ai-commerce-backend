# 23-dev-setup-and-workflow §3–4
SCHEMAS := platform audit catalog commerce messaging sales_ai storefront support reporting
COMPOSE := docker compose -f deploy/docker-compose.yml

.PHONY: install up down lint format typecheck imports test check migrate

install:
	uv sync

up:
	$(COMPOSE) up -d postgres redis minio

down:
	$(COMPOSE) down

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

# S0-03 da Alembic env'lari qo'shilgach ishlaydi
migrate:
	@for s in $(SCHEMAS); do \
		if [ -d app/db/migrations/$$s ]; then uv run alembic -n $$s upgrade head; fi; \
	done
