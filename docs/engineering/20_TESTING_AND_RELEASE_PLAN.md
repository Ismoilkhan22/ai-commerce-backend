# TECH-20 — Verification strategy, acceptance, stage gates

**Status:** Test design, NOT passing tests. Every `M01–M39`, `BL-001–BL-108`, `TECH-*` invariant must have traceable proof. Production readiness is objective, not number of written MD pages.

## 1. Test pyramid / environments
| Layer | Test target | Infrastructure | Ship gate |
|---|---|---|---|
| Domain unit | deterministic invariants, PC rules, FSM transition errors | no DB | always |
| Application/unit | permissions, orchestration, idempotency paths | fakes + typed ports | always |
| PG integration | real SQL isolation, locks, unique, outbox | ephemeral PostgreSQL | Stage1 all writes |
| Integration contract | Telegram/Meta/PSP sandbox, webhook signing | fake/sandbox providers | enable per provider |
| API contract | OpenAPI schema, stable errors, generated client | test app | CI |
| UI E2E | onboarding→catalog→quote→order + failure UX | Playwright + staging | each vertical slice |
| Concurrency/fault | 2+ buyers, duplicate events, worker crash | PG + failpoints/barriers | critical release gate |
| AI eval | grounded outputs, authorization, STT numeric slots | frozen test sets | before auto-response |
| Security | A/B tenants, OWASP, SSRF, CSP, secret scan | staging | critical release gate |
| Load/DR | p95/p99, pool, queue lag, backup restore | realistic staging | production launch |

## 2. Critical acceptance scenarios (all must pass)
| Test ID | Given / when | Then |
|---|---|---|
| TC-001 | Merchant A accesses B order | 403/404 and zero leaked fields |
| TC-002 | two users reserve last SKU | only one succeeds, ledger correct |
| TC-003 | order API timeout after commit, same idempotency key retried | same order/result, no extra hold |
| TC-004 | webhook repeated 100× | one normalized inbound business event |
| TC-005 | AI hallucinates discounted price | rejected by tool guard and escalated |
| TC-006 | user sends screenshot of transfer | payment remains unverified |
| TC-007 | signed valid PSP callback repeated | one verified settlement record |
| TC-008 | payment arrives after hold expiry | exception workflow, no negative stock |
| TC-009 | AI worker prepares reply, operator takes over | stale AI send fails speaker version gate |
| TC-010 | price changes after approved quote | acceptance requires refresh/approval policy |
| TC-011 | provider 429/timeout | bounded retry, DLQ visible, no blind payment duplicate |
| TC-012 | worker dies between DB COMMIT and ACK | event replay idempotent |
| TC-013 | audio voice query unauthorized for margin | access denied even with correct intent |
| TC-014 | Uzbek “o'n million” transcribed differently | transcript confirmation before metric/output |
| TC-015 | Stage2 public offer withdrawn while index lags | anonymous query denied immediately |
| TC-016 | Stage2 product variant 5060/5060 Ti | not merged; reviewer evidence |
| TC-017 | search sponsored offers | labeled independently of organic rank |
| TC-018 | restore from backup | data+outbox consistency and controlled reconciliation |

## 3. Feature traceability rule
Maintain `requirements_trace.csv` or JSON: `{M-ID, BL-ID, FSM-ID, UI route, API route, entity owner, EVT-ID, TC-ID, release slice, status}`. CI fails for release-scope P0 function with missing `API`, test, role or UI representation. Not all future M31–M39 need implemented routes in Stage 1; they must have extension boundary documented.

## 4. S0–S5 release definitions
| Slice | End-to-end visible result | Minimum gate |
|---|---|---|
| S0 | tenant/staff auth, branches, pipeline/observability, migrations | isolation+health traces |
| S1 | catalog/price/stock import, merchant site preview | SKU price version and stock test |
| S2 | channel connection + unified inbox/human takeover | webhook dedup and WS reconnect |
| S3 | AI sales + PC builder + lead/quote | eval, pricing ground, compatibility review |
| S4 | order/reservation/payment review/fulfillment | concurrency+ledger+provider test |
| S5 | reporting/voice read-only, subscription and operational pilot | metric truth, ASR beta, disaster restore |

## 5. Stage2/Stage3 gates
S2 network: self-service merchant opt-in, sync conflict UI, 0 private data leaks, product match false-merge benchmark, public offer revocation. S3 shopping: enough approved comparable offers and merchant locations, good result freshness and search p95, no sponsored ranking concealment, buyer referral consent. No geographic market growth guaranteed by technical test alone.

## 6. Release procedure
QA build signed artifact → staging migration+smoke → freeze versioned OpenAPI → run critical suites→ test kill switches → run backup restore evidence (periodic) → founder signoff → staged production rollout → post-deploy metrics review → rollback on critical invariant regression. Payment/stock incidents pause affected action rather than continue blind retries.

## 7. Definition of Done per story
Business rule+permissions, typed DTO, migrations/index, idempotency/concurrency, audit, structured logs/tracing, UI complete states, unit/integration/e2e tests, documentation update, release flag, rollback/runbook, staging demo acceptance. A feature with only a route implementation is *not done*.
