# TECH-21 — Final architecture cross-review, discrepancies and founder sign-off

**Status:** INITIAL DOCUMENT REVIEW, NOT FINAL APPROVAL. This file explicitly refuses a false 'all production ready' statement. Scope review: written docs TECH-03–TECH-22 against business M01–M39.

## 1. Design-level consistency findings
| Check | Finding | Severity | Next action |
|---|---|---|---|
| 3 product stages across new docs | aligned, Stage 4 ideas explicitly future annex | PASS at concept level | keep legacy 4-stage docs marked superseded |
| DDD context ownership | C01–C19 reused in architecture docs | PASS at design level | code architecture/import tests |
| Merchant payment custody | merchant of record throughout | PASS candidate | PSP/legal signoff |
| Order+stock atomicity | synchronous UoW + outbox, no event-only stock decrement | PASS design | integration race tests |
| Messaging human/AI speaker | version guard in worker/send | PASS design | gateway race E2E |
| AI monetary authority | forbidden to mutate price/stock/mark paid | PASS design | tool security test |
| Broker choice | TECH-05 proposes PG jobs; old TECH-04 notes broker TBD | NEED ADR APPROVAL | approve PG job queue or change C4 |
| RLS vs app scope | SQLAlchemy async RLS spike still open | OPEN technical risk | establish explicit tested approach |
| Payment status after expired reserve | exception policy unspecified by merchant | BLOCKER for auto charge/confirmation | owner-approved FSM branch |
| Voice production quality UZ | evaluation not performed | BLOCKER for auto-speech claims | golden set pilot |
| Legal/data residency/PSP contracts | externally unverified | BLOCKER for real merchant PII/PSP | legal/provider evidence |
| Search S2 matching, S3 traffic | planned only | DEFERRED | Stage2/3 gates |
| Full UI screen-by-screen pixel wireframes | page contracts, basic schematic only | OPEN implementation detail | story UI review before sprint |
| Full executable SQL migrations/OpenAPI source | only design/examples | OPEN implementation | generate from code and contract tests |

## 2. Pending founder decisions
`D-01` approve 3-stage scope and first PC/electronics vertical; `D-02` tenant isolation/RLS plan; `D-03` job broker strategy; `D-04` reservation TTL and failed late payments; `D-05` accepted merchant source for stock; `D-06` manual payment process; `D-07` AI/voice data policy; `D-08` first merchant-specific channel access; `D-09` RPO/RTO and hosting; `D-10` legal/privacy data processing.

## 3. Code-readiness threshold
**Architecture base may support scaffold coding after founder confirms ADR-001,002,004,005,008,009 and scope.** External provider integration and money/stock live activity MUST wait until dedicated tests and open blockers resolved. UX can proceed with contract mocks, but exact API specs and flows must be frozen for the slice before production integration.

## 4. Document-to-implementation trace
| Story | Business | API | Entity | Events/jobs | UI | Acceptance |
|---|---|---|---|---|---|---|
| Merchant onboarding | M01–M03 | TECH-08 auth/merchant | C01/C02 | merchant activated | settings/onboard | TC-001 |
| Catalog import | M04–M06 | products/import | C03–C05 | import+SKU published | catalog+stock | TC-010 + bulk error |
| AI inbox | M09–M12 | channels/conversations | C08–C10 | incoming+handoff | inbox | TC-004,009 |
| Order+hold | M12–M14 | orders/payments | C10–C12 | order created/payment verified | quotes/orders/finance | TC-002,003,006,008 |
| Reports voice | M18–M19 | reports/voice | C15+C09 | voice query | voice+overview | TC-013,014 |
| Public search | M23–M39 | Stage2/3 endpoints | C18/C19 | publication changes | shopping web | TC-015..017 |

This mapping is conceptual: **per-field schema, actual OpenAPI/JSON Schema contract and runnable tests are deliverables of implementation**. Do not mark checked simply because a document exists.

## 5. Review outcome
- **Design document inventory:** mostly drafted and linked; `v1.0 design baseline candidate`.
- **Business validation:** 15 open decisions remain from business package; not all merchant policy values confirmed.
- **Production-readiness:** NOT YET; code/infra/integration/sandbox testing, licensing, measured capacity and approval pending.
- **Next action:** founder review decision register and kick off S0; revisit report after S0 tests, again before paid pilot.
