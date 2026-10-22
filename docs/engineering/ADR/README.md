# Architecture Decision Records (ADR)

> Har muhim arxitektura qarori uchun bitta fayl. Format: Michael Nygard (bismuth v2 bilan bir xil). Founder qarorlarining biznes tomoni — [../../decisions/DECISION_REGISTER.md](../../decisions/DECISION_REGISTER.md).

## Qoidalar

- Fayl nomi: `ADR-XXX-kebab-sarlavha.md`, raqamlar ketma-ket.
- **Qabul qilingan ADR tahrirlanmaydi.** Qaror o'zgarsa — yangi ADR yoziladi, eskisining holati `Superseded by ADR-YYY` ga o'zgartiriladi (faqat holat qatori va qisqa izoh).
- Kichik aniqlik (masalan, nom almashishi — DEC-124 `merchant` → `shop`) holat qatorida izoh sifatida yoziladi.
- Har ADR'da: kontekst, qaror, variantlar, oqibatlar, tekshiruv, qayta ko'rish sharti.

## Holatlar

- **Proposed** — muhokamada
- **Accepted** — qabul qilingan, amalda
- **Deprecated** — endi tavsiya qilinmaydi
- **Superseded by ADR-XXX** — yangi ADR almashtirdi

## Yangi ADR yozish

```bash
cp docs/engineering/ADR/_template.md docs/engineering/ADR/ADR-036-sarlavha.md
```
So'ng: shu jadvalga qator qo'shiladi, registrda tegishli DEC yangilanadi, PR'da `arch-change` belgisi.

## Ro'yxat

| # | Sarlavha | Holat |
|---|---|---|
| ADR-001 | [FastAPI va modular monolith](ADR-001-fastapi-modular-monolith.md) | Accepted (ichki qatlamlar → ADR-031) |
| ADR-002 | [Umumiy PostgreSQL, har qatorda `shop_id`](ADR-002-shared-postgresql-shop-scoped.md) | Accepted (ADR-035 bilan to'ldirildi) |
| ADR-003 | [Shop doirasini cheklash: middleware + UoW, RLS](ADR-003-tenant-scoping-and-rls.md) | Accepted (RLS — S0 spike) |
| ADR-004 | [SQLAlchemy 2 async + Alembic](ADR-004-sqlalchemy-async-alembic.md) | Accepted |
| ADR-005 | [PostgreSQL outbox + PG leased jobs](ADR-005-pg-outbox-and-leased-jobs.md) | Superseded by ADR-033 |
| ADR-006 | [Redis — haqiqat manbai emas](ADR-006-redis-cache-not-source-of-truth.md) | Accepted (ADR-033 bilan o'zgartirildi) |
| ADR-007 | [Pul va noaniq AI amallari uchun odam tasdig'i](ADR-007-human-approval-for-money-and-ai-actions.md) | Accepted |
| ADR-008 | [REST `/api/v1`, OpenAPI klient, WS faqat inbox](ADR-008-rest-api-v1-openapi-ws-inbox.md) | Accepted |
| ADR-009 | [Ikki repo: backend (infra ichida) va frontend](ADR-009-two-repos-infra-in-backend.md) | Accepted |
| ADR-010 | [Dashboard va sayt — alohida Next.js ilovalari](ADR-010-dashboard-and-storefront-separate-nextjs-apps.md) | Accepted |
| ADR-011 | [Hosted LLM; narx/qoldiq/PC — aniq qoidalar](ADR-011-hosted-llm-tools-deterministic-rules.md) | Accepted |
| ADR-012 | [Metrika registri; ovoz faqat o'qish](ADR-012-metric-registry-read-only-voice.md) | Accepted |
| ADR-013 | [Stage 1 qidiruvi — PostgreSQL FTS va trigram](ADR-013-postgres-fts-trigram-search.md) | Accepted |
| ADR-014 | [S3-compatible storage, signed URL](ADR-014-s3-object-storage-signed-urls.md) | Accepted |
| ADR-015 | [Rasmiy kanal adapterlari, webhook imzosi](ADR-015-official-channel-adapters-webhook-signatures.md) | Accepted |
| ADR-016 | [To'lov shop hisobiga](ADR-016-payments-to-shop-account.md) | Accepted, Stage 1 da DEFERRED (DEC-100) |
| ADR-017 | [OpenTelemetry, request ID, strukturali loglar](ADR-017-opentelemetry-tracing-structured-logs.md) | Accepted (vositalar — ADR-029) |
| ADR-018 | [Ommaviy taklif — rozilik bilan proyeksiya](ADR-018-public-offer-opt-in-projection.md) | Accepted |
| ADR-019 | [Tasdiqlashda narx va qoldiq lock ostida](ADR-019-checkout-rechecks-price-and-stock-under-lock.md) | Accepted |
| ADR-020 | [Pilot uchun VM'da Docker Compose](ADR-020-docker-compose-on-vm-for-pilot.md) | Accepted |
| ADR-021 | [Kontekstlararo `workflows/` bitta UoW'da](ADR-021-cross-context-workflows-single-uow.md) | Superseded by ADR-032 |
| ADR-022 | [Repo skeleti `src/commerce_os/modules/...`](ADR-022-src-commerce-os-modules-layout.md) | Superseded by ADR-031 |
| ADR-023 | [Dashboard auth: JWT xotirada + refresh cookie](ADR-023-dashboard-auth-jwt-memory-refresh-cookie.md) | Accepted |
| ADR-024 | [API surface prefikslari](ADR-024-api-surface-prefixes.md) | Accepted (`merchant` → `shop`) |
| ADR-025 | [Pul: minor units, ISO 4217](ADR-025-money-minor-units-iso4217.md) | Accepted |
| ADR-026 | [Shared-first, dedicated-ready](ADR-026-shared-first-dedicated-ready.md) | Accepted |
| ADR-027 | [`LLMPort` + bake-off, redaction](ADR-027-llm-port-bake-off-redaction.md) | Accepted |
| ADR-028 | [PC texnik ma'lumotlar kutubxonasi](ADR-028-pc-reference-spec-library.md) | Accepted |
| ADR-029 | [Observability: Grafana Cloud + Sentry](ADR-029-observability-grafana-cloud-sentry.md) | Accepted |
| ADR-030 | [Production PII O'zbekistonda](ADR-030-uz-hosting-data-residency.md) | Accepted (huquqshunos sharti) |
| ADR-031 | [Uch qatlamli papka tuzilmasi (bismuth v2)](ADR-031-layered-folder-structure.md) | Accepted |
| ADR-032 | [`commerce` domeni, event + Query Port](ADR-032-commerce-domain-and-event-communication.md) | Accepted |
| ADR-033 | [Outbox + arq + APScheduler](ADR-033-outbox-arq-scheduler.md) | Accepted |
| ADR-034 | [Slim USE — holat o'tishlari](ADR-034-slim-use-transition-log.md) | Accepted |
| ADR-035 | [Har domen — alohida schema](ADR-035-schema-per-domain.md) | Accepted |

## Ochiq texnik savollar

Bular spike yoki o'lchov bilan hal qilinadi, taxmin qilinmaydi.

| ID | Savol | Holat | Kerakli dalil | Xavfsiz yo'l (hal bo'lguncha) |
|---|---|---|---|---|
| A-01 | RLS async session va pool bilan ishlaydimi | S0 spike (DEC-002) | SQLAlchemy async + pool integratsiya testi | App-layer filtr; shop konteksti yo'q so'rov rad etiladi |
| A-02 | Navbat sig'imi yetadimi | Outbox + arq tanlandi (DEC-003 D); benchmark S0/S5 da | Pilot yuklamasining 10 barobari bilan sintetik test | AI'ni pasaytirish, buyurtmalarni saqlash |
| A-03 | To'lov provayderi | DEFERRED (DEC-100) | Imzolangan shartnoma + sandbox | To'lov tizimdan tashqarida |
| A-04 | Shaxsiy ma'lumotni lokal qayta ishlash | UZ hosting (DEC-013), huquqshunos xulosasi kutilmoqda | UZ qonuni va tashqi LLM'ga yuboriladigan matn bo'yicha xulosa | Haqiqiy PII tasdiqdan oldin yo'q |
| A-05 | O'zbekcha STT sifati va narxi | Avval matn; ovoz beta bake-off'dan keyin (DEC-010, DEC-112) | Golden voice set, kechikish o'lchovi | Matnni ko'rsatib tasdiqlash + matnli muqobil |
| A-06 | Sayt subdomenlari | S1 da platforma subdomeni, custom domain keyin | DNS/TLS avtomatlashtirish va suiiste'moldan himoya | Faqat platforma subdomeni |
| A-07 | Saqlash muddatlari va backup RPO | Audio transkripsiyadan keyin o'chiriladi (DEC-117); qolgani huquqshunos bilan | Biznes/huquqiy talablar + tiklash sinovi | Kam PII, backup'lar cheklangan |
