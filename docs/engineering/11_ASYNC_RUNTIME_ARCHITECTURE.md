# TECH-11 — FastAPI async runtime, worker capacity and backpressure

**Status:** Baseline runtime design (ADR-004/005 — PG leased jobs tasdiqlangan, DEC-003; 2026-10-22). **Safety:** async is not automatic parallelism or transaction safety. Never call blocking vendor SDK or sync CPU-bound model within event loop.

## Execution classes
| Work | Execution | Why | Typical limit |
|---|---|---|---|
| Simple REST CRUD | `async def` + SQLAlchemy async | nonblocking database I/O | pool-bound concurrency |
| Quote validation light | synchronous deterministic pure compute in bounded thread if heavy | CPU spikes isolated | small CPU semaphore |
| AI orchestration | durable `ai` worker → async HTTP model calls | remote high latency, retry/handoff | tenant+global token limits |
| Voice ASR/TTS | audio job worker / provider | long running, potential audio CPU | stream size/time limits |
| Webhook ACK | FastAPI lightweight authenticated INSERT | no long provider call | p95 target validated |
| Imports and OCR | import workers, chunked parser | disk/CPU/memory risk | bounded file size and memory |
| Outbox + notifications | PG lease/poll separate process | durable network side effect | channel-specific quotas |
| Scheduler | single election/claim jobs | no duplicate tasks | distributed lease |
| Reports/exports | read-model bounded pagination job | avoid request timeout | tenant job cap |

## Asynchronous boundaries
- Every route sets deadline/timeout, DB connection opened late and returned early; NEVER hold DB TX while awaiting LLM/STT/Telegram/payment API. Use transaction→outbox→worker, then worker transaction for result.
- HTTP client (`httpx.AsyncClient`) reused by process with timeout, max connections, retry *only for safe requests*. SDK with sync calls offloaded `anyio.to_thread.run_sync` or run in dedicated worker.
- Request cancel interrupts uncommitted transaction; after commit client disconnect must not undo job; caller polls idempotency result/job status.
- Python GIL/CPU-bound media/image operations need process pool or external service, not many coroutines.

## Work queue model and isolation
Work classes `critical` (reservation expiry/payment reconciliation), `inbound` (webhook), `outbound`, `ai`, `bulk`. Use separate worker pools/limits even if same PostgreSQL job table. Critical jobs not starved by AI. Allocate concurrency by available pool and provider limits, not ad hoc unlimited `asyncio.gather`.

## Time budgets — initial hypotheses
| Operation | Proposed target | Timeout handling |
|---|---|---|
| Basic API GET p95 | < 500ms pilot | 503/429 if saturated |
| Webhook durable ACK p95 | < 1s with provider-spec caveat | provider retry safe |
| AI first useful answer p95 | < 12s excluding carrier latency | transparent human fallback |
| Voice report p95 | < 18s short request | transcript and text fallback |
| DB query | per-query statement timeout | abort UoW, no partial effect |
| Outbound message | provider-specific timeout | ambiguous send reconciled |

Only SLO candidates until measured under representative load.

## Backpressure and degradation
If PG pool saturates → global inflight limit; write endpoints return explicit temporary unavailable *before* doing side effects. If AI budget exhausted → switch to rule-based FAQ/human. If provider 429 → honor Retry-After, throttle per connection. If Redis missing → PG durable operations continue, nonessential realtime subscriptions/rate features degrade safely with conservative fallback. If object storage fails → no evidence/photo accepted as committed until persisted.

## Async worker invariants
Job has tenant ID+actor reference and traceparent but worker rehydrates current authorization. Lease renewal heartbeat while I/O; termination releases lease by expiry. On restart, no worker resumes by assuming prior external side effect failed. Use idempotent callbacks and provider transaction lookup. Enforce one in-flight channel message per conversation speaker version when needed.

## Capacity test design
Generate 10, 50, 200 active conversations and 10x pilot peak as **load profiles, not production capacity claims**; measure p50/p95/p99, DB connections and lock waits, worker queue age, LLM cost, Redis usage, delayed webhook ACK. Simulate provider 429, 5xx, burst 10k chat messages and DB failover/restart. Scaling decision only after empirical measurements.

## Pool hygiene and signals
SQLAlchemy pool size/max_overflow and PgBouncer support must be benchmarked (session/transaction pooling prepared statement caveats). `asyncpg` sessions never cross threads/tasks. Metrics: active connections, checkout wait, slow query traces, event loop lag, worker utilization, dead letter count, memory per job class.

## Test contracts
- Inject a sync `time.sleep` into bad route and verify lint prohibits; measure event loop latency baseline.
- Cancel HTTP client after DB commit: durable job completes exactly one authoritative state change.
- Kill worker during external send: replay reconciles before duplicate; delivery no exact-once guarantee.
- Exhaust AI concurrency: critical stock/payment paths still responsive.
- DB lock 10s: timeout and rollback cleanly, no dangling session or outbox.
