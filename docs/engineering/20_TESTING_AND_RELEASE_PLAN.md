# TECH-20 — Verification strategy, acceptance, stage gates

**Status:** Test design, NOT passing tests. Every `M01–M39`, `BL-001–BL-111`, `TECH-*` invariant must have traceable proof. Production readiness is objective, not number of written MD pages.

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

**Yagona raqamlash:** test ID'lari manbai — `../business/10_UAT_ACCEPTANCE_AND_RELEASES.md` (`TC-001…033`). Bu yerda engineering nuqtai nazaridan qanday isbotlanishi ko'rsatilgan (2026-10-22 da engineering'ning alohida raqamlashi bekor qilindi). Tenant izolyatsiyasi — `TC-ISO-01…10` (TECH-23 §7).

| Test ID | Given / when | Then | Qatlam |
|---|---|---|---|
| TC-001 | Merchant A accesses B order | 404 and zero leaked fields | API/security, TC-ISO |
| TC-002 | two operators confirm orders for last SKU | only one succeeds, ledger correct | PG concurrency |
| TC-003 | order confirm timeout after commit, same `Idempotency-Key` retried | same order/result, no extra hold | API + PG |
| TC-007 | AI hallucinates SKU, price or discount | rejected by tool guard and escalated | AI eval |
| TC-009 | AI worker prepares reply, operator takes over | stale AI send fails speaker version gate | worker race |
| TC-010 | webhook repeated 100× | one normalized inbound business event | integration |
| TC-012 | Uzbek “o'n million” transcribed differently | transcript confirmation before metric/output | voice eval (beta) |
| TC-013 | voice/text report query unauthorized for margin | access denied even with correct intent | security |
| TC-022 | worker dies between DB COMMIT and ACK | event replay idempotent | failpoint |
| TC-027 | online confirm va offline "tez sotuv" oxirgi dona uchun | faqat bittasi o'tadi | PG concurrency |
| TC-028 | xaridor "olaman" dedi | AI faqat `DRAFT`, stok o'zgarmaydi | AI eval + API |
| TC-029 | Sales boshqa operator buyurtmasini tasdiqlaydi / bekor qiladi | 403 + audit | security |
| TC-030 | takroriy `complete` | `on_hand` bir marta kamayadi | PG |
| TC-031 | price changes after approved quote / before confirm | `PRICE_CHANGED` 409, xaridordan qayta rozilik | API + PG |
| TC-032 | provider 429/timeout on outbound send | bounded retry, DLQ visible, no duplicate message intent | integration |
| TC-033 | restore from backup | data + outbox consistency, controlled reconciliation | DR drill |
| TC-015, TC-016, TC-024 | Stage 2/3 (public offer revoke, 5060/Ti, sponsored label) | — | N1/G1 gates |
| TC-004, TC-005, TC-006, TC-021 | to'lov stsenariylari | — | `DEFERRED` (DEC-100) |

## 3. Feature traceability rule
Maintain `requirements_trace.csv` or JSON: `{M-ID, BL-ID, FSM-ID, UI route, API route, entity owner, EVT-ID, TC-ID, release slice, status}`. CI fails for release-scope P0 function with missing `API`, test, role or UI representation. Not all future M31–M39 need implemented routes in Stage 1; they must have extension boundary documented.

## 4. S0–S5 release definitions
| Slice | End-to-end visible result | Minimum gate |
|---|---|---|
| S0 | merchant/staff auth (ADR-023), membership va rollar, platform audit, tracing/log middleware, outbox/jobs, CI, migrations | TC-ISO-01…10, health/ready, trace continuity API→worker |
| S1 | catalog/price (UZS/USD)/stock import, reference spec bog'lash, "tez sotuv", do'kon sayti (savatcha → buyurtma so'rovi) | SKU price version, stock ledger, TC-027 qismi |
| S2 | Telegram + Instagram + web chat, unified inbox, human takeover / resume | TC-010, TC-009, WS reconnect |
| S3 | AI sales (bake-off'dan keyin), PC compatibility, quote (Manager tasdig'i), AI buyurtma qoralamasi | AI eval, TC-007, TC-028, compatibility review |
| S4 | order FSM-08: confirm + rezerv, processing, complete, cancel, paid-mark (to'lovsiz) | TC-002, TC-003, TC-027, TC-029, TC-030, TC-031 |
| S5 | matnli hisobot-chat, kafolat murojaati, AI limitlari, backup/restore, pilot readiness; voice — beta (bake-off'dan keyin) | metric truth, TC-013, TC-033 |

## 5. Stage2/Stage3 gates
S2 network: self-service merchant opt-in, sync conflict UI, 0 private data leaks, product match false-merge benchmark, public offer revocation. S3 shopping: enough approved comparable offers and merchant locations, good result freshness and search p95, no sponsored ranking concealment, buyer referral consent. No geographic market growth guaranteed by technical test alone.

## 6. Release procedure
QA build signed artifact → staging migration+smoke → freeze versioned OpenAPI → run critical suites→ test kill switches → run backup restore evidence (periodic) → founder signoff → staged production rollout → post-deploy metrics review → rollback on critical invariant regression. Stock/order incidents pause affected action rather than continue blind retries.

## 7. Definition of Done per story
Business rule+permissions, typed DTO, migrations/index, idempotency/concurrency, audit, structured logs/tracing, UI complete states, unit/integration/e2e tests, documentation update, release flag, rollback/runbook, staging demo acceptance. A feature with only a route implementation is *not done*.
