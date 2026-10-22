# AI Commerce OS & Network — Engineering Design Pack v1.0

**Date:** 2026-10-21, yangilangan 2026-10-22 · **Product:** three-stage commerce platform · **Status:** `ENGINEERING BASELINE` — founder qarorlari kiritilgan (`../decisions/DECISION_REGISTER.md`); **NOT** implemented / not deployed / not legally certified.

## Product stages
1. Merchant Sales OS (PC/electronics first, own storefront, stock, official chat/AI, orders, payment review, Voice Copilot).
2. Merchant Network (self-serve, POS/ERP, canonical catalog, authorized public offers).
3. Global AI Shopping (price/geo/warranty/availability comparison across opted-in stores, fair buyer AI).
Agro/B2B, custody and marketing studio are **outside current 3-stage scope** pending new business approval.

## Documents (read in order)
- `03_DDD_DOMAIN_ARCHITECTURE.md` — **previous** 19 C01–C19 contexts, 39 business module mappings, 6 diagrams.
- `04_SYSTEM_ARCHITECTURE_C4.md` — **previous** overall C4-like design and 14 diagrams.
- `05_ARCHITECTURE_DECISIONS_ADR.md` — TECH-05 — Architecture Decision Records (ADR)
- `06_DATABASE_ERD_AND_SCHEMA.md` — TECH-06 — Database ERD, schema and lifecycle
- `07_DOMAIN_TRANSACTIONS_CONCURRENCY.md` — TECH-07 — Domain transactions, concurrency, invariants
- `08_API_CONTRACTS.md` — TECH-08 — REST / WebSocket API contract design
- `09_EVENTS_OUTBOX_AND_JOBS.md` — TECH-09 — Event contracts, transactional outbox, durable jobs
- `10_SECURITY_AND_RBAC.md` — TECH-10 — Security, tenancy, RBAC, audit and privacy
- `11_ASYNC_RUNTIME_ARCHITECTURE.md` — TECH-11 — FastAPI async runtime, worker capacity and backpressure
- `12_OBSERVABILITY_AND_TRACING.md` — TECH-12 — Observability, tracing, SLOs and incident diagnostics
- `13_INTEGRATION_ARCHITECTURE.md` — TECH-13 — Channel, payment, POS/ERP and map integration architecture
- `14_GLOBAL_CATALOG_SEARCH_ARCHITECTURE.md` — TECH-14 — Network global catalog, offer publication and shopper search
- `15_AI_AGENTS_ARCHITECTURE.md` — TECH-15 — AI agent architecture and tool authorization
- `16_VOICE_AI_ARCHITECTURE.md` — TECH-16 — Business Voice Copilot in Uzbek, Russian and English
- `17_DATASET_MODEL_TRAINING_EVALUATION.md` — TECH-17 — Dataset governance, model strategy and evaluation
- `18_FRONTEND_ARCHITECTURE_AND_UI.md` — TECH-18 — Frontend architecture, page contracts and UX states
- `19_INFRASTRUCTURE_AND_DEPLOYMENT.md` — TECH-19 — Infrastructure, environments, CI/CD, backup and recovery
- `20_TESTING_AND_RELEASE_PLAN.md` — TECH-20 — Verification strategy, acceptance, stage gates
- `21_FINAL_ARCHITECTURE_REVIEW.md` — TECH-21 — Final architecture cross-review, discrepancies and founder sign-off
- `22_DEVELOPMENT_TASKS_AND_REPO_STRUCTURE.md` — TECH-22 — Development implementation roadmap, repo skeleton, task breakdown
- `23_TENANT_ISOLATION_AND_DEPLOYMENT_MODES.md` — TECH-23 — Tenant isolation, merchant AI agent izolyatsiyasi, shared/dedicated deployment (PROPOSED, `DEC-001/002`)
- Ochiq qarorlar: `../decisions/DECISION_REGISTER.md`

- `../business/` — canonical 13 business specifications M01–M39 / BL-001–BL-111 / FSM / UI / UAT.

## Important decisions and gaps
- Stage 1 architecture **baseline (2026-10-22)**: FastAPI modular monolith (`src/commerce_os/`, ADR-022), PostgreSQL core with atomic order+stock UoW (ADR-021) and transactional outbox; PG leased jobs (ADR-005); Redis cache/rate limit only; frontend separate repo with 2 Next.js apps (ADR-010); infra in backend repo; shared-first tenant model + RLS spike (ADR-026, TECH-23); auth — ADR-023; API surfaces — ADR-024; money — ADR-025; LLM — ADR-027; PC spec library — ADR-028; observability — ADR-029; hosting — ADR-030.
- **Stage 1 savdo oqimi (DEC-100):** buyurtma bor, to'lov va yetkazish tizimdan tashqarida; AI faqat `DRAFT` buyurtma yaratadi, operator/sotuvchi tasdiqlaydi. To'lov (M14) va yetkazish (M15) — `DEFERRED`.
- Stage 2/3 are designed at **extension/boundary** level, not fully executable schema/API or UI. Do not misrepresent them as ready to deploy.
- Biznes parametrlari baseline sifatida hal qilingan (registr). Ochiq: huquqshunos xulosasi (data residency, retention), Meta ruxsati, unit economics (pilotda o'lchanadi).
- Texnik spike'lar: RLS under async session/pool (S0), PG jobs load benchmark, LLM bake-off (S3), STT bake-off (voice beta), aniq RPO/RTO.
- Exact executable OpenAPI spec, Alembic migrations, complete component-level mockups, code, provider sandbox tests and real performance evidence are **next implementation deliverables**. Design documents do not equal tested production code.

## Approval workflow / practical reading
1. Read `05` ADR and `21` review; founder approves/revises choices.
2. Align `06` ERD with each Stage 1 business flow; freeze initial schema migrations.
3. Freeze `08` API DTOs per vertical slice, then generate typed frontend client; do not hand-maintain two incompatible schemas.
4. Before external/financial live workflows, pass `07` concurrency, `10` security, `09` outbox, `20` tests and integration sandbox.
5. Run `22` S0→S5 vertical slices; keep feature flags; audit before each production enable.

## Document consistency principles
`merchant_id` never trusted from client; price/stock/payment never LLM truth; human/AI speaking authority via version; public offer opt-in and immediate revoke; no silent double charge; no exact-once external side-effects promises; no real data before privacy/provider review.
