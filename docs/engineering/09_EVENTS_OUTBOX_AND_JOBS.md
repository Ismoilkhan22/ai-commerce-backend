# TECH-09 — Event contracts, transactional outbox, durable jobs

**Status:** Baseline Stage 1 operational design (2026-10-22): PostgreSQL outbox + PG leased jobs **tanlangan** (DEC-003, ADR-005); event envelope — K-08 (quyida, yagona format). **References:** TECH-03 19 contexts, TECH-07 concurrency, TECH-12 telemetry, business 09 module relations. At-least-once, **not exactly-once external side effects**.

## 1. Three different entities — never confuse
1. **Domain event** = committed business fact (`order.created.v1`); immutable schema version.
2. **Outbox message** = transactionally persisted dispatch intent; can be replayed.
3. **Job** = scheduled/executing task with lease/retry/result; may be created by event consumer or transaction.
Webhook raw delivery is in an **inbox event** first with provider dedup, not a domain event until authenticated/normalized.

## Envelope schema
```json
{
 "event_id":"uuid","event_type":"inventory.stock_changed.v1",
 "merchant_id":"uuid","aggregate_type":"stock_balance","aggregate_id":"uuid",
 "aggregate_version":8,"occurred_at":"2026-10-21T09:00:00Z",
 "producer":"inventory","schema_version":1,"traceparent":"00-...-...-01",
 "correlation_id":"request-or-workflow-id","causation_id":"command-or-event-id",
 "actor":{"kind":"merchant_user","id":"uuid"},
 "payload":{"sku_id":"uuid","branch_id":"uuid","available_after":3}
}
```
No PII, bank/card number, conversation raw text or provider token in event payload; reference encrypted/private records by UUID.

**K-08:** bu envelope barcha hujjat va kod uchun yagona. TECH-03 §10.1 dagi `tenant_id`/`trace_id` varianti bilan almashtirildi (`merchant_id`, `traceparent`).

## Event owner / consumers
| Event | Producer | Consumer(s) | Processing contract |
|---|---|---|---|
| `conversation.message_received.v1` | C08 | C09 AI router, C10 lead | dedup provider event; speaker guard |
| `conversation.handoff_requested.v1` | C08 | C14 notification | one active handoff per version |
| `catalog.sku_published.v1` | C03 | C06 web; C09 search view | index upsert revision |
| `pricing.price_changed.v1` | C04 | C06,C09; C18 Stage2 | latest version wins |
| `inventory.stock_changed.v1` | C05 | C06,C15; C18 Stage2 | fetch absolute state, not `+=` |
| `quote.approved.v1` | C10 | C14 send | immutable quote snapshot |
| `order.created.v1` | C11 | C08 operator task, C14 | `DRAFT` (AI/storefront/staff); stok band emas |
| `order.submitted.v1` | C11 | C14 | `PENDING_CONFIRMATION`; 24 soatlik eslatma job (DEC-104) |
| `order.confirmed.v1` | C11 | C14,C15 | order + reservation bitta tranzaksiyada commit qilingan (ADR-021) |
| `order.completed.v1` | C11 | C10 lead WON, C14, C15 | stok `CONSUMED` allaqachon commit qilingan |
| `order.cancelled.v1` | C11 | C10 lead LOST, C14, C15 | no second release |
| `inventory.offline_sale.v1` | C05 | C06, C15 | absolute state qayta o'qiladi (DEC-123) |
| `payment.verified.v1` — `DEFERRED` (DEC-100) | C12 | C11,C14,C15 | settlement uniqueness |
| `shipment.delivered.v1` — `DEFERRED` (DEC-113) | C13 | C14,C15 | delivery proof check |
| `public_offer.withdrawn.v1` S2 | C18 | index/projection | immediate DB read-time revoke |
| `canonical_product.match_changed.v1` S2 | C18 | C19 search | reversible merge/split |

## Outbox dispatch flow
```mermaid
sequenceDiagram
 participant API as App UoW
 participant DB as PostgreSQL
 participant W as Outbox dispatcher
 participant C as Consumer
 API->>DB: BEGIN + domain write + outbox
 API->>DB: COMMIT
 W->>DB: Claim due rows SKIP LOCKED
 DB-->>W: event + lease
 W->>C: Deliver event
 C->>DB: BEGIN + receipt insert + state mutation
 C->>DB: COMMIT
 C-->>W: ACK
 W->>DB: Mark published / handoff recorded
```
If consumer crashes after commit and before ACK, replay finds `(consumer_name,event_id)` receipt unique and no-ops. If outbox dispatcher itself crashes before mark, event may deliver again; no loss by design.

## Jobs (specific payload, retry, recovery)
| Job type | Queue | Attempt policy candidate | Failure handling |
|---|---|---|---|
| `inbound_normalize` | high | 3, quick jitter | invalid signed payload quarantined |
| `ai_draft_answer` | ai | 2, deadline bounded | handoff human; no spam |
| `channel_send` | external | provider-aware (up to 5) | store provider receipt, ambiguous delivery reconcile |
| `order_confirm_reminder` | critical | periodic scan, idempotent | `PENDING_CONFIRMATION` > 24 soat → menejer vazifasi (DEC-104) |
| `reservation_review` | critical | periodic scan, idempotent | `ACTIVE` rezerv > 72 soat → "bekor qilinsinmi?" vazifasi; holat o'zgarmaydi (DEC-104) |
| `quote_expire` | critical | 5 short | `SENT` → `EXPIRED` (24 soat default, DEC-103) |
| `audio_purge` | bulk | 3 | transkripsiyadan keyin audio o'chiriladi, audit (DEC-117) |
| `payment_reconcile` — `DEFERRED` (DEC-100) | finance | periodic capped | manual finance alert for UNKNOWN |
| `catalog_import` | bulk | resume rows/chunks | error CSV, reject partial commit by policy |
| `report_export` | bulk | 3 | report job failed with retry button |
| `voice_transcription` | ai | 2, no endless replay | ask text clarification |
| `sync_partner` S2 | external | rate-limit guided | conflict queue, fail closed stock |
| `public_reindex` S2 | search | retry/backoff | tombstones visible immediately |

**Values are proposed defaults**, not universal: retry based on error classification. 4xx/invalid input generally permanent; 429 honors Retry-After; timeout ambiguous for outbound financial/notification and MUST reconcile rather than blindly repeat.

## Leasing, scheduling and DLQ
`job_id`, queue, priority, `payload_ref`, tenant, created_at, due_at, lease_owner, lease_until, heartbeat_at, attempts, max_attempts, status (`READY/RUNNING/SUCCEEDED/DEAD/CANCELLED`), failure_code, `traceparent`, last_result_ref. Poller uses `FOR UPDATE SKIP LOCKED` with small transaction; do not hold lock while calling external API. Lease expiry redispatch; high-cost AI checks job state and budget before retry. Dead jobs require UI showing safe retry controls; operator replay creates explicit audit log and preserves original causality.

## Ordering and replay
- Aggregate event carries `aggregate_version`; consumers maintain `last_applied_version`, hold or backfill gaps, ignore lower versions. Some projections can recalculate from source of truth instead of buffering history.
- Outbox backlog alarm, oldest job age, stuck lease, DLQ count, replay rate, duplicate provider events; dashboards per tenant with redacted identifiers.
- Full backfill rebuilds derived reports/search projections from authoritative DB; no business order/payment derived from event stream only.

## Proof tests
1. Crash after business COMMIT before dispatch → event eventually observed.
2. Crash consumer after DB COMMIT before ACK → no duplicate state mutation.
3. Same provider message 50x → 1 normalized business effect.
4. Worker restarts mid AI send → exactly-one *intent*, provider duplicates possible; tagged and remediated.
5. Out-of-order price versions 10,8 → final 10; opt-out immediately blocks public.
6. DB unavailable → webhook does NOT 2xx without durable inbox.
7. Publisher 429/rate-limit → backoff/jitter and operator sees backlog.
