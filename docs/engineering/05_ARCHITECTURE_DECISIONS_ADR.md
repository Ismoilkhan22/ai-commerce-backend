# TECH-05 — Architecture Decision Records (ADR)

**Status:** Proposed for founder approval · **Scope:** 3 stages; only Stage 1 implementation commitments. **Sources:** TECH-03, TECH-04, M01–M39, BL-001–BL-108. **Owner:** Founder.

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
| ADR-016 | External payments to merchant account, verified callback / authorized finance approval | platform custody | reduces regulated money flow | marketplace split payments required |
| ADR-017 | OpenTelemetry W3C `traceparent`, request ID, structured logs, Prometheus+Grafana, error collector | uncorrelated print logs | incidents and async lineage | tracing storage costs exceed budget |
| ADR-018 | Stage 2 public offer is merchant opt-in projection, separate from private SKU | expose merchant DB to public search | privacy, revocation | never weaken boundary |
| ADR-019 | Storefront checkout rechecks authoritative price/availability under lock | rely on search cache | avoid stale quote and oversell | never relax invariant |
| ADR-020 | Docker Compose on sized VM/managed PostgreSQL as candidate pilot; prod isolated secrets/backups | Kubernetes on day one | operational simplicity | HA/scale goals demand orchestration |

## Formal option comparisons and implementation consequences

### ADR-001 Modular monolith / DDD
- **Context:** M01–M39 map to C01–C19; business modules are not deployable services. C01–C16 mostly Stage 1, C17–C18 Stage 2, C19 Stage 3.
- **Decision:** One application package; routing and workers call public `application` APIs, domain has no FastAPI/ORM imports. Domain events are returned by aggregates; same-UoW cross-context flow coordinated in an application orchestrator rather than chained eventual handlers.
- **Consequences:** Imports enforced by architecture tests, versions of public ports; no internal HTTP and no cross-context repository access. A context may share DB process but not mutate another context's table except through explicit synchronous UoW orchestration exception documented in ADR-021.
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

### ADR-016 payment responsibility
- Merchant designated merchant-of-record, tax/fiscal duties checked before live; our system generates intent and reflects verified settlement only. Card numbers never handled by platform. No auto approval from uploaded screenshot. Provider callback signature AND server-to-server verification per provider contract; unique `(merchant_id,provider,external_transaction_id)`.

## Open decisions (must be resolved in spikes, not invented)
| Open ID | Candidate | Evidence required | Safe failure behavior |
|---|---|---|---|
| A-01 | RLS actual implementation | SQLAlchemy async checkout+pool integration test | app scope+deny unbound |
| A-02 | PG leased jobs capacity | 10x pilot synthetic load benchmark | degrade AI, preserve order |
| A-03 | payment provider choice | signed provider agreement + sandbox contract | manual finance approval |
| A-04 | local personal data processing | counsel review for UZ and external inference payloads | no real PII until approved |
| A-05 | Uzbek STT and cost | golden voice set and latency measurement | transcript UI + text fallback |
| A-06 | storefront subdomains | DNS/TLS automation and abuse protections | platform-hosted preview only |
| A-07 | exact retention and backup RPO | business/legal requirements + restore test | minimize PII, backups gated |

## Decision change record
Each ADR change requires: proposer, timestamp, changed constraint, options, rollback story, affected `TECH-*`, `BL-*`, `M*`, database migration/test tickets, founder approval. Do not silently shift between RabbitMQ, Kafka and PG queue across docs.
