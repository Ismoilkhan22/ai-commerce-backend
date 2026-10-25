# ai-commerce-backend

AI Commerce OS — shop'lar uchun savdo tizimi backend'i (FastAPI modular monolith).

- Hujjatlar: [`docs/`](docs/README.md) — biznes, engineering (v2, bismuth standarti), qarorlar registri.
- Arxitektura: `app/shared` → `app/platform` → `app/domains` ([ADR-031](docs/engineering/ADR/ADR-031-layered-folder-structure.md)).
- Vazifalar: [docs/engineering/27-roadmap-and-tasks.md](docs/engineering/27-roadmap-and-tasks.md).

## Lokal ishga tushirish

Talablar: Python 3.12, [uv](https://docs.astral.sh/uv/), Docker.

```bash
cp .env.example .env
make install        # uv sync
make up             # PostgreSQL 16, Redis 7 (fayllar lokalda — var/storage)
make check          # ruff, mypy, import-linter, pytest — CI bilan bir xil
```

Batafsil: [docs/engineering/23-dev-setup-and-workflow.md](docs/engineering/23-dev-setup-and-workflow.md).
