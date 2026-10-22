# 05 — FSM: BIZNES STATUSLAR, TRANSITIONS, TIMEOUT VA EXCEPTIONS

**Versiya:** v1.0 | **Holat:** Normative logical FSM. Concrete enum/DB state migration keyingi technical documentda.  
**Umumiy qoida:** satrda ko‘rsatilmagan transition `REJECT`, har bir transition tenant, actor, permitted state, version/idempotency va audit talab qiladi.
**Nomlash (K-02, K-03):** status qiymatlari `UPPER_SNAKE`; bu fayl API, DB va UI uchun status nomlarining yagona manbai. Order, Payment va Shipment statuslari alohida saqlanadi.
**Stage 1 baseline (2026-10-22, `decisions/DECISION_REGISTER.md`):** to'lov tizimdan tashqarida (DEC-100) — FSM-09 `DEFERRED`; yetkazish moduli yo'q (DEC-113) — FSM-10 `DEFERRED`; FSM-04/06/07/08 qarorlarga moslab yangilandi.

## Global transition invariants

1. Statuslar faqat domain operation orqali o‘zgaradi; admin UI table update qilmaydi.
2. Har bir terminal holatda trigger, sabab va tegishli kompensatsiya aniq saqlanadi.
3. `PENDING_*` hech qachon haqiqiy yakunlangan holatni anglatmaydi; Stage 1 da "to'landi" faqat merchant qo'ygan, tekshirilmagan belgi (DEC-100a).
4. External callbacks out-of-order va duplicated kelishi mumkin, FSM unique replay policy qo‘llaydi.
5. Bekor qilingan buyurtma, rezerv konflikti va qaytarilgan mahsulot uchun exception queue mavjud (to'lov exception'lari to'lov moduli bilan qaytadi).
6. Role va mutable entity `version` tekshirilmasdan transition commit emas.

## FSM-01 — Merchant account

| From | Trigger | To | Authorized actor | Side effect / guard |
|---|---|---|---|---|
| DRAFT | submit | PENDING_VERIFICATION | Owner | Checklist lock, verification request |
| PENDING_VERIFICATION | verify | ACTIVE | Platform Admin/verified workflow | Enable permitted shop channels |
| ACTIVE | suspend | SUSPENDED | Platform Admin | Stop new checkout/publish, preserve existing obligations |
| SUSPENDED | restore | ACTIVE | Platform Admin | Revalidate billing and permissions |
| ACTIVE | close | CLOSED | Owner + Platform Admin | Export and public takedown; retention |

**No-go:** wrong actor, expired prior version, duplicate side effect, invalid sequence → business conflict/review, never silent success.

## FSM-02 — Product publication

| From | Trigger | To | Authorized actor | Side effect / guard |
|---|---|---|---|---|
| DRAFT | submit | IN_REVIEW | Catalog Manager | Required field validation |
| IN_REVIEW | approve | PUBLISHED | Manager | Increment version + storefront publish |
| PUBLISHED | hide | HIDDEN | Manager | Block new quotes and hide public |
| HIDDEN | republish | PUBLISHED | Manager | Revalidate price+stock |
| PUBLISHED | archive | ARCHIVED | Owner | Retain historical order snapshots |

**No-go:** wrong actor, expired prior version, duplicate side effect, invalid sequence → business conflict/review, never silent success.

## FSM-03 — Channel connectivity

| From | Trigger | To | Authorized actor | Side effect / guard |
|---|---|---|---|---|
| PENDING | authorize | CONNECTED | Owner | Token stored and webhook verified |
| CONNECTED | provider_error | DEGRADED | System | Manual fallback + alert |
| DEGRADED | reauthorize | CONNECTED | Owner | Verify webhook delivery |
| CONNECTED | revoke | DISCONNECTED | Owner | Disable outbound and rotate secret |

**No-go:** wrong actor, expired prior version, duplicate side effect, invalid sequence → business conflict/review, never silent success.

## FSM-04 — Conversation

| From | Trigger | To | Authorized actor | Side effect / guard |
|---|---|---|---|---|
| NEW | assign_ai | AI_ACTIVE | System | Acquire conversation send authority |
| AI_ACTIVE | need_human | HUMAN_NEEDED | AI/System | Create operator task |
| HUMAN_NEEDED | takeover | HUMAN_ACTIVE | Sales | Revoke AI send authority atomically |
| HUMAN_ACTIVE | reply_wait | WAITING_CUSTOMER | Sales | Send permitted channel response |
| WAITING_CUSTOMER | customer_reply | HUMAN_ACTIVE | Sales/System | Set inbox unread |
| AI_ACTIVE | reply_wait | WAITING_CUSTOMER | AI | Send verified answer |
| HUMAN_ACTIVE | resolve | RESOLVED | Sales | Close SLA and audit |
| HUMAN_ACTIVE | resume_ai | AI_ACTIVE | Sales/Manager | Explicit action only; `speaker_version` oshadi, AI oxirgi operator javobining qisqa mazmunini oladi, operator va'dalarini bekor qilmaydi (SAGA-S04) |
| RESOLVED | new_message | REOPENED | System | Reopen with original context |

**No-go:** wrong actor, expired prior version, duplicate side effect, invalid sequence → business conflict/review, never silent success.

## FSM-05 — Lead

| From | Trigger | To | Authorized actor | Side effect / guard |
|---|---|---|---|---|
| NEW | qualify | QUALIFIED | Sales/AI authorized | Store consented requirements |
| QUALIFIED | prepare_quote | QUOTED | Sales | Link approved quote |
| QUALIFIED | lose | LOST | Sales | Record reason |
| QUOTED | accept | WON | Sales/System | Link order id |
| QUOTED | lose | LOST | Sales | Record reason |
| LOST | reopen | QUALIFIED | Sales | Recover with fresh data |

**No-go:** wrong actor, expired prior version, duplicate side effect, invalid sequence → business conflict/review, never silent success.

## FSM-06 — Quote

**Qo'llanish (DEC-100e):** quote faqat online PC yig'ma va maxsus narx uchun; oddiy online xarid to'g'ridan-to'g'ri buyurtma qoralamasiga (FSM-08 `DRAFT`) o'tadi. **Tasdiqlash (DEC-102, DEC-109):** merchant policy `quote_approval_mode` — `ALWAYS` (pilot default) yoki `RISK_ONLY`; tasdiqlovchi faqat Manager (limit ichida) yoki Owner, Sales emas. **Muddat (DEC-103):** `quote_ttl_hours`, default 24.

| From | Trigger | To | Authorized actor | Side effect / guard |
|---|---|---|---|---|
| DRAFT | submit_review | REVIEW | Sales/AI (draft) | Calculate all line values and compatibility (`PASS/REVIEW_REQUIRED/BLOCK`); `BLOCK` bo'lsa submit rad etiladi |
| DRAFT | auto_approve | APPROVED | System | Faqat `RISK_ONLY` rejimida: compatibility `PASS`, chegirma yo'q, summa threshold ichida; snapshot va muddat muzlatiladi |
| REVIEW | approve | APPROVED | Manager/Owner | Freeze snapshot and validity; `REVIEW_REQUIRED` bo'lsa dalil bilan |
| APPROVED | send | SENT | Sales/System | Channel-policy check |
| SENT | customer_accept | ACCEPTED | Customer | Recheck validity on order creation |
| SENT | expire | EXPIRED | Scheduler | Requote required |
| SENT | reject | REJECTED | Customer | Allow revised quote |
| REJECTED | revise | DRAFT | Sales | New version only |

**No-go:** wrong actor, expired prior version, duplicate side effect, invalid sequence → business conflict/review, never silent success.

## FSM-07 — Reservation

**Baseline (K-05, DEC-105, DEC-104):** rezerv buyurtma `CONFIRMED` bo'lganda yaratiladi (buyurtma so'rovi stokni band qilmaydi). Avtomatik muddat yo'q: `reservation_review_hours` (default 72) o'tsa menejerga "bekor qilinsinmi?" vazifasi; `EXPIRED` faqat menejer qarori bilan.

| From | Trigger | To | Authorized actor | Side effect / guard |
|---|---|---|---|---|
| — | reserve | ACTIVE | Order confirm workflow | Atomic: stock row lock, `available >= qty`, `reserved += qty`; order `CONFIRMED` bilan bitta tranzaksiya |
| ACTIVE | allocate | ALLOCATED | Order workflow (`PROCESSING`) | `reserved -= qty`, `allocated += qty` |
| ACTIVE | cancel | RELEASED | Order workflow (order `CANCELLED`) | Idempotent release, `reserved -= qty` |
| ACTIVE | expire | EXPIRED | Manager (review vazifasidan) | Idempotent release; buyurtma `CANCELLED` yoki qayta tasdiq |
| ALLOCATED | consume | CONSUMED | Order workflow (`COMPLETED`) | `allocated -= qty`, `on_hand -= qty`, ledger `SALE` — bir marta |
| ALLOCATED | cancel | RELEASED | Manager | `allocated -= qty`; audit sababi bilan |

**No-go:** wrong actor, expired prior version, duplicate side effect, invalid sequence → business conflict/review, never silent success.

## FSM-08 — Order

**Stage 1 savdo oqimi (DEC-100):** buyurtma to'lovsiz; AI yoki storefront faqat `DRAFT` yaratadi (DEC-100c/d); har buyurtmani odam tasdiqlaydi; to'lovni do'kon tizimdan tashqarida oladi. Buyurtmada `fulfillment_method` (`PICKUP` / `DELIVERY`) va manzil saqlanadi (DEC-113); yetkazish narxi operator bilan kelishiladi (DEC-100h). Ixtiyoriy `paid_marked` belgisi (kim, qachon, usul) — DEC-100a.

| From | Trigger | To | Authorized actor | Side effect / guard |
|---|---|---|---|---|
| — | create_draft | DRAFT | AI (`orders.create_draft`), Storefront buyer, Sales | Stok band qilinmaydi; narx qatorga snapshot qilinadi (oddiy xarid) yoki approved quote'dan nusxalanadi (PC) |
| DRAFT | submit | PENDING_CONFIRMATION | Sales / Storefront buyer | Operatorga vazifa + xabar (M17); `order_confirm_reminder_hours` (default 24) taymeri |
| PENDING_CONFIRMATION | confirm | CONFIRMED | Sales (o'ziga biriktirilgan) / Manager (DEC-108) | Fresh price + stock check under lock; rezerv `ACTIVE` (FSM-07); narx o'zgargan bo'lsa xaridordan qayta rozilik |
| CONFIRMED | start_processing | PROCESSING | Sales / Warehouse / Manager | Rezerv `ALLOCATED`; xaridorga status xabari |
| PROCESSING | mark_ready | PROCESSING | Sales / Warehouse / Manager | Status o'zgarmaydi: `ready_at` yoziladi, PICKUP bo'lsa xaridorga `customer.order_ready_pickup` (TECH-31) |
| PROCESSING | complete | COMPLETED | Sales / Manager | Xaridorga topshirildi; rezerv `CONSUMED`, `on_hand` kamayadi; Lead `WON` |
| DRAFT | discard | CANCELLED | Sales / Buyer | Hech qanday stok effekti yo'q |
| PENDING_CONFIRMATION | cancel | CANCELLED | Manager / Owner | Sabab majburiy; Lead `LOST` + sabab |
| CONFIRMED | cancel | CANCELLED | Manager / Owner | Rezerv `RELEASED` (idempotent) |
| PROCESSING | cancel_review | EXCEPTION | Manager | Qo'lda tiklash (mahsulot qaytishi, stok tekshiruvi) |
| EXCEPTION | resolve_cancel | CANCELLED | Manager | Kompensatsiya: rezerv/allocation bo'shatiladi, audit |
| EXCEPTION | resume | PROCESSING | Manager | Audit resolution |

**No-go:** wrong actor, expired prior version, duplicate side effect, invalid sequence → business conflict/review, never silent success.

## FSM-09 — Payment — `DEFERRED` (DEC-100, DEC-111)

> Stage 1 da tizim orqali to'lov yo'q: to'lovni do'kon o'zi oladi. Quyidagi FSM to'lov moduli (M14) qaytganda ishlatiladi; ungacha faqat buyurtmadagi ixtiyoriy "to'landi" belgisi (DEC-100a).

| From | Trigger | To | Authorized actor | Side effect / guard |
|---|---|---|---|---|
| INITIATED | await_provider | AWAITING_CONFIRMATION | Customer | Generate instructions |
| AWAITING_CONFIRMATION | verify | VERIFIED | System/Cashier | Verify callback or actual settlement |
| AWAITING_CONFIRMATION | fail | FAILED | System | Release/hold order by policy |
| AWAITING_CONFIRMATION | cancel | CANCELLED | Manager | Check late webhook risk |
| VERIFIED | request_refund | REFUND_PENDING | Manager | Eligibility and amount approval |
| REFUND_PENDING | complete_refund | REFUNDED | Payment worker | Provider evidence + ledger |
| REFUND_PENDING | provider_fail | REFUND_FAILED | System | Keep case open |

**No-go:** wrong actor, expired prior version, duplicate side effect, invalid sequence → business conflict/review, never silent success.

## FSM-10 — Shipment — `DEFERRED` (DEC-113)

> Stage 1 da yetkazish moduli, kuryer roli va kuryer ekrani yo'q; yetkazishni do'kon o'zi tashkil qiladi, holat FSM-08 (`PROCESSING → COMPLETED`) orqali yuritiladi. Quyidagi FSM yetkazish hamkori yoki kuryer ekraniga talab paydo bo'lganda ishlatiladi.

| From | Trigger | To | Authorized actor | Side effect / guard |
|---|---|---|---|---|
| PENDING | prepare | READY | Warehouse | Verify contents |
| READY | assign | ASSIGNED | Manager | Pick courier |
| ASSIGNED | dispatch | IN_TRANSIT | Courier | Track handoff |
| IN_TRANSIT | deliver | DELIVERED | Courier/Customer proof | Evidence required |
| IN_TRANSIT | fail | EXCEPTION | Courier | Record reason |
| EXCEPTION | reschedule | ASSIGNED | Manager | Notify buyer |
| EXCEPTION | return | RETURNED | Manager | Return and inventory inspection |

**No-go:** wrong actor, expired prior version, duplicate side effect, invalid sequence → business conflict/review, never silent success.

## FSM-11 — Return / Warranty

| From | Trigger | To | Authorized actor | Side effect / guard |
|---|---|---|---|---|
| NEW | review | IN_REVIEW | Support | Gather evidence |
| IN_REVIEW | approve | APPROVED | Manager | Return instructions |
| IN_REVIEW | reject | REJECTED | Manager | Reason + appeal option |
| APPROVED | receive | IN_SERVICE | Warehouse/Support | Inspect and track |
| IN_SERVICE | resolve | RESOLVED | Support | Refund/repair/replace evidence |
| RESOLVED | close | CLOSED | Support | Customer confirmation where possible |

**No-go:** wrong actor, expired prior version, duplicate side effect, invalid sequence → business conflict/review, never silent success.

## FSM-12 — Notification

| From | Trigger | To | Authorized actor | Side effect / guard |
|---|---|---|---|---|
| PENDING | schedule | SCHEDULED | Worker | Respect opt-out/quiet hour |
| SCHEDULED | send | SENT | Worker | Store provider message id |
| SCHEDULED | retry | SCHEDULED | Worker | Bounded backoff |
| SCHEDULED | fail | FAILED | Worker | Open DLQ/support task |
| PENDING | suppress | SUPPRESSED | Policy | Record suppression reason |

**No-go:** wrong actor, expired prior version, duplicate side effect, invalid sequence → business conflict/review, never silent success.

## FSM-13 — Integration connection

| From | Trigger | To | Authorized actor | Side effect / guard |
|---|---|---|---|---|
| DRAFT | authorize | AUTHORIZED | Owner | Store scoped secrets |
| AUTHORIZED | initial_sync | SYNCING | Worker | Dry-run and cursor |
| SYNCING | healthy | HEALTHY | Worker | Publish mapped data |
| HEALTHY | error | DEGRADED | System | Hold unsafe field sync and alert |
| DEGRADED | recover | HEALTHY | Worker | Reconcile source version |
| HEALTHY | revoke | REVOKED | Owner | Stop sync and rotate secrets |

**No-go:** wrong actor, expired prior version, duplicate side effect, invalid sequence → business conflict/review, never silent success.

## FSM-14 — Public offer

| From | Trigger | To | Authorized actor | Side effect / guard |
|---|---|---|---|---|
| PRIVATE | opt_in | PENDING_VALIDATION | Owner | Explicit fields and terms |
| PENDING_VALIDATION | publish | PUBLISHED | System | Validate price/condition/branch |
| PUBLISHED | age_out | STALE | System | Hide or clearly flag policy |
| STALE | reverify | PUBLISHED | Merchant/Sync | Update version |
| PUBLISHED | withdraw | WITHDRAWN | Owner | Priority takedown event |
| PUBLISHED | hide | HIDDEN | Moderator | Fraud/wrong-price review |

**No-go:** wrong actor, expired prior version, duplicate side effect, invalid sequence → business conflict/review, never silent success.

## FSM-15 — Product match

| From | Trigger | To | Authorized actor | Side effect / guard |
|---|---|---|---|---|
| UNMATCHED | generate_candidates | CANDIDATE | Matching Engine | Evidence, attributes and confidence |
| CANDIDATE | request_review | REVIEW | Catalog Reviewer | Diff variants |
| CANDIDATE | auto_accept | MATCHED | Rules (high confidence only) | Link reversible canonical ref |
| REVIEW | approve | MATCHED | Catalog Reviewer | Audit match |
| REVIEW | reject | REJECTED | Catalog Reviewer | Retain aliases without merge |
| MATCHED | split | REVIEW | Catalog Reviewer | Protect active offers during undo |

**No-go:** wrong actor, expired prior version, duplicate side effect, invalid sequence → business conflict/review, never silent success.

## FSM-16 — Merchant verification

| From | Trigger | To | Authorized actor | Side effect / guard |
|---|---|---|---|---|
| UNVERIFIED | submit | IN_REVIEW | Owner | Upload business evidence |
| IN_REVIEW | approve | VERIFIED | Verification Team | Set expiry and proof |
| IN_REVIEW | reject | REJECTED | Verification Team | Reason and appeal |
| VERIFIED | expire | EXPIRED | Scheduler | Remove verified badge |

**No-go:** wrong actor, expired prior version, duplicate side effect, invalid sequence → business conflict/review, never silent success.

## FSM-17 — Global referral

| From | Trigger | To | Authorized actor | Side effect / guard |
|---|---|---|---|---|
| CREATED | send | DELIVERED | System | Permission-controlled handoff |
| DELIVERED | ack | ACKNOWLEDGED | Merchant | Record response SLA |
| ACKNOWLEDGED | sale | CONVERTED | Merchant/System | Optional attribution proof |
| DELIVERED | timeout | EXPIRED | System | Do not invent conversion |
| ACKNOWLEDGED | lose | LOST | Merchant | Reason stored |

**No-go:** wrong actor, expired prior version, duplicate side effect, invalid sequence → business conflict/review, never silent success.

## FSM-18 — Buyer price alert

| From | Trigger | To | Authorized actor | Side effect / guard |
|---|---|---|---|---|
| ACTIVE | offer_meets_threshold | TRIGGERED | Alert Worker | Fresh offer & consent check |
| ACTIVE | expire | EXPIRED | System | Auto-disable |
| ACTIVE | unsubscribe | CANCELLED | Buyer | Immediate stop |
| TRIGGERED | reenable | ACTIVE | Buyer | Explicit action |

**No-go:** wrong actor, expired prior version, duplicate side effect, invalid sequence → business conflict/review, never silent success.

## Multi-FSM sagas / compensations

### SAGA-S01: Confirmed order and stock (Stage 1, to'lovsiz — DEC-100)
- Operator/manager `confirm` → bitta tranzaksiyada: narx va stok qulf bilan qayta tekshiriladi → rezerv `ACTIVE` → order `CONFIRMED` → outbox (xaridorga xabar).
- `reserve failed` (stok tugagan): order `PENDING_CONFIRMATION` da qoladi, operatorga muqobil taklif vazifasi; «confirmed» UI ko'rsatilmaydi.
- Notification failed: order state valid; notification queued/replayed.
- `order cancel`: rezerv aynan bir marta bo'shatiladi; to'lov tizimdan tashqarida bo'lgani uchun pul qaytarish do'kon tomonidan, tizimda faqat izoh/audit.
- `COMPLETED`: allocation `CONSUMED`, `on_hand` bir marta kamayadi (ledger `SALE`).

### SAGA-S02: Payment and fulfillment — `DEFERRED` (DEC-100, DEC-113; to'lov va yetkazish modullari qaytganda amal qiladi)
- Provider/manual verification must match amount+currency+merchant.
- `payment verified` can arrive before/after fulfilment setup; shipped/debit should not be inferred from proof.
- Late payment after cancellation/expiry routes to exception queue; compensate via new reserved order or authorized refund, after buyer consent.

### SAGA-S03: Global public index
- Merchant opts in → validate fields and canonical linkage → outbox publishes index task → verified search result.
- Merchant opts out → immediately fail closed at offer visibility endpoint + high-priority takedown event; old index hit rejected on read.
- Merge/split canonical product requires recomputing linked offer grouping without rewriting merchant offer history.

### SAGA-S04: Human takeover
- `AI_ACTIVE` → `HUMAN_NEEDED` → operator `HUMAN_ACTIVE`; AI generation may continue, but send permission is rechecked just before outbound.
- Operator resolution → optionally return to AI with explicit action; no uncontrolled ping-pong.

### SAGA-S05: Provider integration recovery
- Webhook accepted only after durable message/event record; background worker handles business mutation.
- Failure uses bounded retry; permanent provider failure sets degraded and merchant action notification.
- Retry must not duplicate order/notification/refund; dead-letter replay by authorized support.

## Timers (merchant policy, baseline default'lar — `decisions/DECISION_REGISTER.md`)

| Timer | Triggers | Baseline default | Behavior |
|---|---|---|---|
| Quote expiry | `quote.valid_until` | 24 soat (DEC-103) | Stop accept, force new quote; qabulda narx/stok qayta tekshiriladi |
| Order confirm reminder | `order.submitted_at + order_confirm_reminder_hours` | 24 soat (DEC-104) | `PENDING_CONFIRMATION` buyurtma bo'yicha menejerga eslatma; avtomatik bekor yo'q |
| Reservation review | `reservation.created_at + reservation_review_hours` | 72 soat (DEC-104) | Menejerga "bekor qilinsinmi?" vazifasi; `EXPIRED` faqat menejer qarori bilan |
| Merchant handoff SLA | `task.due_at` | merchant sozlaydi | Escalate assigned operator/manager |
| Payment proof review SLA | `payment.review_due_at` | — | `DEFERRED` (DEC-100) |
| Public offer freshness | `last_verified_at + freshness_policy` | Stale hide/warn; no cheapest claim |
| Integration sync health | `last_successful_sync_at` | Mark degraded, restrict affected data |
| Price alert cooldown | `alert.last_notified_at` | Dedup until policy threshold |
