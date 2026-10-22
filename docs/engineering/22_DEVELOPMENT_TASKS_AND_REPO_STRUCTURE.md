# TECH-22 — Development implementation roadmap, repo skeleton, task breakdown

**Status:** executable work plan (baseline 2026-10-22: barcha DEC qarorlari kiritilgan), not finished code. **Execution:** founder + AI coding assistant. **Do not develop all Stage2/3 up front.** Specs anchored TECH-03–TECH-21.

## 1. Repos and source layout (DEC-004 / ADR-022, DEC-014)
```text
ai-commerce-backend/
  pyproject.toml                 # uv, ruff, mypy, pytest, import-linter
  docker-compose.yml             # lokal: PostgreSQL 16, Redis
  alembic/
  src/commerce_os/
    bootstrap/                   # app_factory, DI composition root, worker_factory, settings
    shared/
      kernel/                    # ids, money (ADR-025), clock, errors, events
      security/                  # ActorContext, policy service, tenant context (TECH-23)
      infra/                     # db + UoW (RLS set_config), outbox, jobs (PG leased), logging, tracing, storage
      contracts/                 # error envelope (K-07), pagination
    modules/                     # S0 da faqat identity, merchants, platform
      identity/{domain,application,infrastructure,presentation}/ + public.py
      merchants/  platform/                          # S0
      catalog/  pricing/  inventory/  storefronts/   # S1
      messaging/                                     # S2
      pc_builder/  merchant_ai/  sales/              # S3
      orders/                                        # S4
      engagement/  reporting/  fulfillment/          # S2–S5 (fulfillment — faqat support_cases, DEC-114)
      # payments/ — DEFERRED (DEC-100); integrations/, market_catalog/ — Stage 2; discovery/ — Stage 3
    workflows/                   # ADR-021: order_confirmation, order_completion, merchant_provisioning
    workers/                     # outbox_dispatcher, inbound_messages, ai_replies, reminders, audio_purge
    transport/                   # telegram_webhook, instagram_webhook, web_chat, websockets
    api/v1/                      # merchant/, storefront/, webhooks/, platform/, auth/ (ADR-024) + middlewares/
  tests/{unit,integration,contract,concurrency,security,ai_eval,e2e}/
  infra/{compose,proxy,backup,scripts}/        # monitoring — Grafana Cloud (DEC-012), self-hosted yo'q
  docs/{business,discovery,engineering,decisions}/

ai-commerce-frontend/
  pnpm-workspace.yaml
  apps/{merchant-dashboard,merchant-storefront}/
  packages/{ui,api-client,i18n,auth}/          # api-client — OpenAPI'dan generatsiya
  e2e/
```
Folders are created per slice, not up front. `shared/kernel` MUST NOT grow into business god module. Kontekstlararo sinxron yozuvlar faqat `workflows/` orqali (ADR-021); import boundary architecture test (import-linter) mandatory from S0.

## 2. S0 — foundation tasks
| ID | Task | Dependency | Acceptance |
|---|---|---|---|
| S0-00 | Meta (Instagram) app review arizasi va biznes verifikatsiyasi | — | ariza topshirilgan (DEC-116) |
| S0-01 | Python 3.12 + uv project, ruff, mypy, pytest, import-linter, CI | approved ADRs | reproducible setup and precommit |
| S0-02 | FastAPI bootstrap/config/DI, surface router'lari (ADR-024), K-07 error envelope + global exception handler'lar | S0-01 | health, readiness, barcha xatolar bitta formatda |
| S0-03 | Postgres async UoW, Alembic | S0-02 | rollback, pool tests |
| S0-04 | Identity (ADR-023 auth, refresh rotation), membership, rollar va permission katalogi (TECH-10), branch scope; **RLS spike** (DEC-002) | S0-03 | TC-ISO-01…10 |
| S0-05 | middleware zanjiri (TECH-12 §5a), JSON log sxemasi (§5b), OTel → Grafana Cloud, Sentry (DEC-012) | S0-02 | API→job trace correlation, log'da PII yo'q |
| S0-06 | PG jobs+outbox lease/worker/dedup | S0-03 | restart/crash replay test |
| S0-07 | frontend: pnpm workspace, ikki Next.js app, auth shell (ADR-023), generated client, i18n (uz/ru/en) | S0-02 OpenAPI | role-aware 401/403 UX |
| S0-08 | infra Docker, staging secrets, backup restore | S0-03 | smoke + restore rehearsal |

## 3. S1 — Merchant catalog/site
| ID | Task | Acceptance |
|---|---|---|
| S1-01 | Merchant/branch setup UI and policies | owner can create store and branch, validation |
| S1-02 | SKU/variant attributes, media upload, prices/version (UZS/USD + exchange rates, DEC-121) | atomic edits, uniqueness, audit |
| S1-02b | Reference hardware spec kutubxonasi: platform admin CRUD, SKU auto-link (MPN/model), merchant so'rovi (DEC-011, DEC-120) | bog'lanmagan SKU → REVIEW_REQUIRED |
| S1-03 | Branch stock ledger/receipt/adjustment, "tez sotuv" (DEC-123) | available = on_hand − reserved − allocated; concurrency tests |
| S1-04 | CSV/XLSX import validation as resumable job | dry-run, row errors, no memory blowup |
| S1-05 | Branded subdomain, catalog & product public pages, savatcha → buyurtma so'rovi (DEC-115) | no unpublished SKU, SEO, cache freshness |

## 4. S2 — channels + conversation
| ID | Task | Acceptance |
|---|---|---|
| S2-01 | Web widget inbound events and conversation model | durable inbox, mapped visitor |
| S2-02 | Telegram bot adapter, official webhook auth | signature/secret, duplicate retry test |
| S2-03 | Conversation inbox, status, assign/handoff | speaker CAS, WS reconnect |
| S2-04 | Outbound message intent, provider delivery tracking | retry/ambiguous send visible |
| S2-05 | Instagram (Meta) adapter — Stage 1 kanali (DEC-116); production ruxsat kelguncha feature flag | Meta sandbox test, ruxsat kelgach yoqiladi |

## 5. S3 — AI + PC + quote
| ID | Task | Acceptance |
|---|---|---|
| S3-00 | LLM bake-off: 200 uz/ru/en dialog, 2–3 model (DEC-009) | tanlangan model + baholash hisoboti |
| S3-01 | AI model provider abstraction (`LLMPort`), PII redaction (DEC-016), budgets and tool broker | forbidden mutation impossible |
| S3-02 | Catalog hybrid retrieval+merchant knowledge policies | exact SKU/price grounded |
| S3-03 | Deterministic PC rules with evidence and REVIEW | wrong socket blocked, unknown escalated |
| S3-04 | Lead capture, quote versions (faqat PC), Manager/Owner tasdig'i (`ALWAYS`/`RISK_ONLY`), 24 soat muddat; AI `orders.create_draft` | immutable sent snapshot, expiry, TC-028 |
| S3-05 | 3-language agent evaluation and shadow tests | eval+cost pass/AI kill switch |

## 6. S4 — order (to'lovsiz, DEC-100)
| ID | Task | Acceptance |
|---|---|---|
| S4-01 | Order FSM-08 + `workflows/order_confirmation`: confirm (assigned Sales/Manager) + atomic multi-SKU reserve | two final-unit confirms no oversell (TC-002, TC-027) |
| S4-02 | Processing/complete: allocated → consumed, `on_hand` kamayadi; cancel (Manager/Owner) | TC-029, TC-030 |
| S4-03 | Order notes (chat/telefon kelishuvi), `fulfillment_method` + manzil, ixtiyoriy "to'landi" belgisi | audit, tekshirilmagan deb ko'rsatiladi |
| S4-04 | Reminder job'lari: 24 soat tasdiqlanmagan, 72 soat rezerv review (DEC-104) | vazifa yaratiladi, holat o'zgarmaydi |
| S4-05 | Xaridorga status xabarlari (Telegram/Instagram/web) | one per transition |
| — | Payment proof / gateway, shipment/courier | `DEFERRED` (DEC-100, DEC-113) |

## 7. S5 — reports/voice/billing/reliability
| ID | Task | Acceptance |
|---|---|---|
| S5-01 | Metric registry (completed orders, tekshirilmagan paid-mark, leads by channel) va dashboard; matnli hisobot-chat (DEC-112) | raqamlar DB bilan mos, data_as_of |
| S5-02 | Kafolat murojaatlari (DEC-114) | warranty snapshot, qaytgan mahsulot karantinda |
| S5-03b | Voice beta: STT/TTS bake-off (DEC-010), 2 bosqichli endpoint, audio o'chirish (DEC-117) | golden set o'tgach feature flag |
| S5-03 | Pilot usage metering/quotas/plan switch | AI cost bounded by merchant |
| S5-04 | alerts, runbooks, backup restore and load tests | SLO measurement and recovery proof |
| S5-05 | paid pilot readiness review | founder signoff all critical TC |

## 8. Stage 2 follow-up (N1…)
Self-service merchant provisioning; POS/ERP connectors and source precedence; canonical product schema; match review tool; public-offer opt-in/withdraw; async index and billing/support scale. Gate by merchant adoption. **Avoid integrating all ERP systems before one authorized partner.**

## 9. Stage 3 follow-up (G1…)
Public buyer search app/SEO; geosearch, canonical comparison, AI advisor public tools, referral attribution, trust quality, organic vs sponsored differentiation. Gate by public coverage, freshness and ability to maintain truthful comparisons.

## 10. AI-assisted development handoff contract
One task per PR: include source M-ID/BL-ID, SPEC doc, exact API DTOs, affected entity/port, error conditions, concurrency/idempotency, tests, telemetry, rollback. Claude can implement, ChatGPT reviews architecture, founder runs tests/approves; do not accept code merely because generated. Required PR template:
```text
Ticket / stage:
Business rule IDs / test IDs:
Interface and schema changes:
DB migration and tenant guard:
Transactions, locks, async/outbox:
AI tool boundary/provider error:
UI: loading/empty/error/conflict:
Observability and privacy:
Unit/integration/e2e evidence:
Rollback and risk:
```

## 11. Release sequencing principle
Vertical increments produce usable paths, not detached abstract modules: `merchant→catalog→storefront→message→AI/quote→order→payment→delivery→report`. Feature flags disable unready integrations. S0–S5 labels are development slices **within Stage1**, not separate commercial stages.
