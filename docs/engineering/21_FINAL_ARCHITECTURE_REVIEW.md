# TECH-21 — Final architecture cross-review, discrepancies and founder sign-off

**Status:** REVIEW UPDATED 2026-10-22 — founder baseline qarorlari (`../decisions/DECISION_REGISTER.md`) hujjatlarga kiritildi; production approval emas. This file explicitly refuses a false 'all production ready' statement. Scope review: written docs TECH-03–TECH-22 against business M01–M39.

## 1. Design-level consistency findings
| Check | Finding | Severity | Next action |
|---|---|---|---|
| 3 product stages across new docs | aligned, Stage 4 ideas explicitly future annex | PASS at concept level | keep legacy 4-stage docs marked superseded |
| DDD context ownership | C01–C19 reused in architecture docs | PASS at design level | code architecture/import tests |
| Merchant payment custody | Stage 1 da to'lov tizimdan tashqarida (DEC-100) | RESOLVED (baseline) | to'lov moduli qaytganda PSP/legal signoff |
| Order+stock atomicity | synchronous UoW + outbox, no event-only stock decrement | PASS design | integration race tests |
| Messaging human/AI speaker | version guard in worker/send | PASS design | gateway race E2E |
| AI monetary authority | forbidden to mutate price/stock/mark paid | PASS design | tool security test |
| Broker choice | PG outbox + PG leased jobs (DEC-003, ADR-005); C4 yangilandi | RESOLVED | S0 da runner, S5 da load benchmark |
| RLS vs app scope | App-layer + composite FK; RLS spike S0 da (DEC-002, ADR-026, TECH-23 §6) | PLANNED | S0 spike natijasi |
| Payment status after expired reserve | Stage 1 da to'lov yo'q; rezerv avtomatik tugamaydi, 72 soatlik review (DEC-104, DEC-106 closed) | RESOLVED | — |
| Voice production quality UZ | S5 da avval matnli hisobot; voice beta bake-off va golden set'dan keyin (DEC-112, DEC-010) | MITIGATED | golden set yig'ish |
| Legal/data residency | UZ hosting baseline (DEC-013), LLM'ga PII yo'q (DEC-016); huquqshunos xulosasi kutilmoqda | BLOCKER for real merchant PII | huquqshunos xulosasi |
| PC compatibility data source | reference hardware spec kutubxonasi (DEC-011, DEC-120, ADR-028) | RESOLVED (design) | `PC_COMPATIBILITY_ENGINE` hujjati, boshlang'ich to'ldirish |
| Meta (Instagram) access | Stage 1 kanali (DEC-116); founder kechikmaydi deb hisoblaydi | RISK | ariza S0 bilan |
| Cross-doc naming (statuslar, ID'lar, test raqamlari) | K-01…K-10 qo'llandi; engineering test ID'lari business/10 ga birlashtirildi | RESOLVED | — |
| Search S2 matching, S3 traffic | planned only | DEFERRED | Stage2/3 gates |
| Full UI screen-by-screen pixel wireframes | page contracts, basic schematic only | OPEN implementation detail | story UI review before sprint |
| Full executable SQL migrations/OpenAPI source | only design/examples | OPEN implementation | generate from code and contract tests |

## 2. Pending founder decisions
2026-10-22: D-01…D-10 `../decisions/DECISION_REGISTER.md` ga ko'chirildi va baseline sifatida hal qilindi (xarita — registr §4). Ochiq qolganlar: huquqshunos xulosasi (DEC-013), RPO/RTO aniq qiymatlari, RLS spike, LLM va STT bake-off natijalari.

## 3. Code-readiness threshold
**Scaffold (S0) coding uchun shart bajarildi:** ADR-001, 002, 004, 005, 008, 009 va ADR-021…030 baseline sifatida tasdiqlangan (2026-10-22). External provider integration and money/stock live activity MUST wait until dedicated tests and open blockers resolved. UX can proceed with contract mocks, but exact API specs and flows must be frozen for the slice before production integration.

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
