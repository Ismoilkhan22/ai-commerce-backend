# TECH-05 — Architecture Decision Records (ADR)

**Status:** `APPROVED (baseline, 2026-10-22)` — founder qarorlari `../decisions/DECISION_REGISTER.md` da; pilot yoki spike natijasiga qarab o'zgartirilishi mumkin. · **Scope:** 3 stages; only Stage 1 implementation commitments. **Sources:** TECH-03, TECH-04, M01–M39, BL-001–BL-111. **Owner:** Founder.

**ADR raqamlash:** bu fayl yagona manba. TECH-03 §16 dagi eski ro'yxat bu jadval bilan almashtirildi. ADR-001…020 — dastlabki takliflar (endi baseline), ADR-021…030 — 2026-10-22 founder qarorlaridan qo'shildi.

## Decision process
An ADR records **context / options / decision / consequences / verification / revisit trigger**. `PROPOSED` is not approved; changing one later updates impacted docs and migration plan. Every ADR below is a candidate baseline, NOT demonstrated performance.

| ID | Decision | Alternatives rejected for MVP | Why | Measurable revisit trigger |
|---|---|---|---|---|
| ADR-001 | FastAPI + modular monolith, domain/application/adapters | Microservices, full Django rewrite | One founder; local ACID orchestration | independent scaling/release bottleneck |
| ADR-002 | Shared PostgreSQL, merchant-scoped schema; no DB per tenant | separate tenant DB now | simpler transactions/migrations | isolation contract needs or compliance |
| ADR-003 | Tenant scoping middleware+UoW; RLS for sensitive private tables after integration spike | solely trusting `merchant_id` in body | defense-in-depth, async pooled connection hazards considered | isolated tests fail / complexity measured |
| ADR-004 | SQLAlchemy 2 async + Alembic | sync request DB access | bounded non-blocking I/O, explicit transactions | driver performance issues |
| ADR-005 | PostgreSQL transactional outbox + PG leased job queue for first launch | Kafka, RabbitMQ+Celery at day one | no extra broker; strong durable commit semantics | job throughput/DB contention SLO breached |
| ADR-006 | Redis only for cache, token bucket, ephemeral state; not authoritative | Redis-only stock/queue | fail closed for rate limits; PG source of truth | sustained load needs broker |
| ADR-007 | Owner+merchant explicit approver for finance and ambiguous AI actions | AI autonomous order/payment actions | financial and reputation safety | mature approved multi-step workflow |
| ADR-008 | HTTPS REST versioned `/api/v1`, typed OpenAPI client; WS only inbox | GraphQL first | testable contracts, simple caching | many complex cross-client read patterns |
| ADR-009 | One backend repo (`infra/` inside), one frontend repo (Next.js workspace) | 3+ repo split | low coordination cost | separate infra ownership |
| ADR-010 | Merchant store and dashboard same frontend workspace, independent Next.js apps | single large Next.js deployment | independent domains SEO vs private auth | duplicate shared UI overhead |
| ADR-011 | Hosted LLM routed via provider adapter, RAG/tools, deterministic price/stock/PC rules | Train foundation LLM | time to market, safety | eval proves specific fine-tune ROI |
| ADR-012 | SQL-based approved metric registry; voice STT→intent→metric→TTS read-only | LLM free SQL | fact consistency, RBAC | measured voice eval passes mutation gate |
| ADR-013 | PG FTS/trgm structured search Stage 1; postpone dedicated search infra | Elasticsearch now | small catalog; precision on SKU | p95/catalog size threshold experimentally hit |
| ADR-014 | S3-compatible object storage for media; signed read URLs | DB blobs | limits database growth | sensitive-content retention requirements |
| ADR-015 | OAuth/provider adapters + webhook signature validation; channel capability registry | unofficial browser bots | provider terms / reliability | approved provider changes |
| ADR-016 | External payments to merchant account, verified callback / authorized finance approval — **Stage 1: `DEFERRED` (DEC-100)** | platform custody | reduces regulated money flow | marketplace split payments required |
| ADR-017 | OpenTelemetry W3C `traceparent`, request ID, structured logs, Prometheus+Grafana, error collector | uncorrelated print logs | incidents and async lineage | tracing storage costs exceed budget |
| ADR-018 | Stage 2 public offer is merchant opt-in projection, separate from private SKU | expose merchant DB to public search | privacy, revocation | never weaken boundary |
| ADR-019 | Storefront checkout rechecks authoritative price/availability under lock | rely on search cache | avoid stale quote and oversell | never relax invariant |
| ADR-020 | Docker Compose on sized VM/managed PostgreSQL as candidate pilot; prod isolated secrets/backups | Kubernetes on day one | operational simplicity | HA/scale goals demand orchestration |
| ADR-021 | Kontekstlararo sinxron yozuvlar faqat `workflows/` dagi nomlangan use case orqali, bitta UoW ichida (masalan order confirm + inventory reserve) | context A ning context B jadvaliga to'g'ridan-to'g'ri yozishi; event zanjiri | atomik invariant, aniq egalik | workflow soni nazoratsiz o'ssa |
| ADR-022 | Repo skeleti `src/commerce_os/` + `modules/<context>/{domain,application,infrastructure,presentation}` (DEC-004) | `app/contexts` (TECH-22 eski varianti) | src-layout, `workflows/` uchun joy | — |
| ADR-023 | Dashboard auth: access JWT xotirada (10–15 daq) + rotating refresh token `httpOnly Secure SameSite=Strict` cookie; WS — qisqa ticket (DEC-008) | cookie-session + BFF CSRF; localStorage | XSS'dan himoya, stateless API | dashboard va API turli site'da bo'lishi kerak bo'lsa |
| ADR-024 | API surface prefikslari: `/api/v1/merchant`, `/storefront/{slug}`, `/webhooks`, `/platform`, `/public` (DEC-006) | tekis `/api/v1/*` | har surface o'z auth/rate-limit middleware'i | — |
| ADR-025 | Pul: `amount_minor bigint` + ISO 4217 exponent (`currencies` jadvali), UZS = 2; USD narx + kurs snapshot (DEC-007, DEC-121) | butun so'm; float | standart, kurs hisobida aniqlik | — |
| ADR-026 | Shared-first, dedicated-ready deployment; app-layer tenant scoping + composite FK; RLS spike S0 da, o'tsa sezgir jadvallarga (DEC-001, DEC-002; batafsil TECH-23) | DB-per-tenant; darhol to'liq RLS | xarajat va soddalik, ikki qavat himoya | spike yiqilsa yoki Enterprise talab |
| ADR-027 | LLM: provayderdan mustaqil `LLMPort` + 1 haftalik bake-off (default nomzod Claude Sonnet); PII redaction + zero-retention/no-training sharti (DEC-009, DEC-016) | darhol multi-provider; self-hosted | dalilga asoslangan tanlov, huquqiy xavf kam | bake-off natijasi, narx |
| ADR-028 | PC compatibility ma'lumoti — platforma `reference_hardware_specs` kutubxonasi, SKU bog'lanadi; bog'lanmasa `REVIEW_REQUIRED` (DEC-011, DEC-120) | merchant kiritadi; to'liq global katalog | ishonchli spec, merchantga ish yo'q | kutubxonani yuritish xarajati |
| ADR-029 | Observability: OpenTelemetry + JSON loglar → Grafana Cloud; xatolar → Sentry; PII telemetriyaga yozilmaydi (DEC-012) | self-hosted Grafana stack | bitta odam uchun boshqarish yo'q | narx yoki residency talabi |
| ADR-030 | Hosting: production PII DB va storage O'zbekistonda, huquqshunos xulosasidan keyin real PII (DEC-013) | xorijiy cloud; gibrid | lokalizatsiya talabi | huquqiy xulosa |

## Formal option comparisons and implementation consequences

### ADR-001 Modular monolith / DDD
- **Context:** M01–M39 map to C01–C19; business modules are not deployable services. C01–C16 mostly Stage 1, C17–C18 Stage 2, C19 Stage 3.
- **Decision:** One application package; routing and workers call public `application` APIs, domain has no FastAPI/ORM imports. Domain events are returned by aggregates; same-UoW cross-context flow coordinated in an application orchestrator rather than chained eventual handlers.
- **Consequences:** Imports enforced by architecture tests, versions of public ports; no internal HTTP and no cross-context repository access. A context may share DB process but not mutate another context's table except through explicit synchronous UoW orchestration in `workflows/` (ADR-021).
- **Test:** `import-linter`/dependency tests forbid cycles, integration tests verify ports.

### ADR-002 / ADR-003 shared DB and tenant security
- **Context:** Pooled async sessions may accidentally reuse tenant context. Merchant has branches, restricted staff, anonymous signed shopper sessions.
- **Decision:** Every tenant-owned row has `merchant_id NOT NULL`; every query scoping is bound to server-authorized membership; owner merchant `id` comes from authenticated principal, never request payload. Proof-of-concept RLS by `SET LOCAL app.merchant_id` per transaction; test connections/reset across tenants. Until RLS is implemented and verified, deny all administrative cross-tenant generic endpoints.
- **Consequences:** Unique constraints include tenant scope, all job payloads refer tenant but workers fetch current membership from DB, read/public projections live in dedicated schemas/views with allowlist. No implicit superadmin bypass.
- **Test:** Merchant A/B matrix × each endpoint/worker/tool; connection-reuse regression; transaction rollback cleanup.

### ADR-005 PG jobs vs external broker
- **Decision:** PG `outbox_messages` and `jobs` tables polled via `FOR UPDATE SKIP LOCKED`; worker-specific queue, heartbeat/lease, attempts, visibility deadlines, dead state, operator replay, retention. Dispatcher claims and marks delivered only after handoff; consumer dedup with uniqueness.
- **Why:** 1 authoritative durability mechanism for modest pilot loads, crash recovery. `LISTEN/NOTIFY` optional wakeup only, not durability.
- **Tradeoff:** Frequent polling/large payloads burden PG, scheduled periodic VACUUM/indexes; switch to RabbitMQ or cloud broker after measured queue lag or isolation threshold. Switching bus MUST preserve event schema, idempotency, and outbox.
- **SLO draft:** Queue enqueue acknowledgement commits with business TX; age-of-oldest alert e.g. >120s (tune pilot), backlog and dead-job counts tracked. Do not treat PG as infinite-throughput queue.

### ADR-016 payment responsibility — Stage 1 da `DEFERRED` (DEC-100: to'lov tizimdan tashqarida). Quyidagi talablar to'lov moduli qaytganda amal qiladi.
- Merchant designated merchant-of-record, tax/fiscal duties checked before live; our system generates intent and reflects verified settlement only. Card numbers never handled by platform. No auto approval from uploaded screenshot. Provider callback signature AND server-to-server verification per provider contract; unique `(merchant_id,provider,external_transaction_id)`.

## Open decisions (must be resolved in spikes, not invented)
| Open ID | Candidate | Evidence required | Safe failure behavior |
|---|---|---|---|
| A-01 | RLS actual implementation — **S0 spike (DEC-002)** | SQLAlchemy async checkout+pool integration test | app scope+deny unbound |
| A-02 | PG leased jobs capacity — **PG jobs tanlandi (DEC-003)**, benchmark S0/S5 da | 10x pilot synthetic load benchmark | degrade AI, preserve order |
| A-03 | payment provider choice — **`DEFERRED` (DEC-100)** | signed provider agreement + sandbox contract | to'lov tizimdan tashqarida |
| A-04 | local personal data processing — **UZ hosting baseline (DEC-013), huquqshunos xulosasi kutilmoqda** | counsel review for UZ and external inference payloads | no real PII until approved |
| A-05 | Uzbek STT and cost — **S5 da avval matn, voice beta bake-off'dan keyin (DEC-010, DEC-112)** | golden voice set and latency measurement | transcript UI + text fallback |
| A-06 | storefront subdomains | DNS/TLS automation and abuse protections | platform-hosted preview only |
| A-07 | exact retention and backup RPO — audio transkripsiyadan keyin o'chiriladi (DEC-117); qolganlari huquqshunos bilan | business/legal requirements + restore test | minimize PII, backups gated |

## Decision change record
Each ADR change requires: proposer, timestamp, changed constraint, options, rollback story, affected `TECH-*`, `BL-*`, `M*`, database migration/test tickets, founder approval. Do not silently shift between RabbitMQ, Kafka and PG queue across docs.
