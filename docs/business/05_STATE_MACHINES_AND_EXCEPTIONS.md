# 05 — FSM: BIZNES STATUSLAR, TRANSITIONS, TIMEOUT VA EXCEPTIONS

**Versiya:** v1.0 | **Holat:** Normative logical FSM. Concrete enum/DB state migration keyingi technical documentda.  
**Umumiy qoida:** satrda ko‘rsatilmagan transition `REJECT`, har bir transition tenant, actor, permitted state, version/idempotency va audit talab qiladi.

## Global transition invariants

1. Statuslar faqat domain operation orqali o‘zgaradi; admin UI table update qilmaydi.
2. Har bir terminal holatda trigger, sabab va tegishli kompensatsiya aniq saqlanadi.
3. `pending_*` hech qachon haqiqiy `paid/delivered` holatni anglatmaydi.
4. External callbacks out-of-order va duplicated kelishi mumkin, FSM unique replay policy qo‘llaydi.
5. Late payment, cancelled delivery, failed refund uchun exception queue mavjud.
6. Role va mutable entity `version` tekshirilmasdan transition commit emas.

## FSM-01 — Merchant account

| From | Trigger | To | Authorized actor | Side effect / guard |
|---|---|---|---|---|
| draft | submit | pending_verification | Owner | Checklist lock, verification request |
| pending_verification | verify | active | Platform Admin/verified workflow | Enable permitted shop channels |
| active | suspend | suspended | Platform Admin | Stop new checkout/publish, preserve existing obligations |
| suspended | restore | active | Platform Admin | Revalidate billing and permissions |
| active | close | closed | Owner + Platform Admin | Export and public takedown; retention |

**No-go:** wrong actor, expired prior version, duplicate side effect, invalid sequence → business conflict/review, never silent success.

## FSM-02 — Product publication

| From | Trigger | To | Authorized actor | Side effect / guard |
|---|---|---|---|---|
| draft | submit | in_review | Catalog Manager | Required field validation |
| in_review | approve | published | Manager | Increment version + storefront publish |
| published | hide | hidden | Manager | Block new quotes and hide public |
| hidden | republish | published | Manager | Revalidate price+stock |
| published | archive | archived | Owner | Retain historical order snapshots |

**No-go:** wrong actor, expired prior version, duplicate side effect, invalid sequence → business conflict/review, never silent success.

## FSM-03 — Channel connectivity

| From | Trigger | To | Authorized actor | Side effect / guard |
|---|---|---|---|---|
| pending | authorize | connected | Owner | Token stored and webhook verified |
| connected | provider_error | degraded | System | Manual fallback + alert |
| degraded | reauthorize | connected | Owner | Verify webhook delivery |
| connected | revoke | disconnected | Owner | Disable outbound and rotate secret |

**No-go:** wrong actor, expired prior version, duplicate side effect, invalid sequence → business conflict/review, never silent success.

## FSM-04 — Conversation

| From | Trigger | To | Authorized actor | Side effect / guard |
|---|---|---|---|---|
| new | assign_ai | ai_active | System | Acquire conversation send authority |
| ai_active | need_human | human_needed | AI/System | Create operator task |
| human_needed | takeover | human_active | Sales | Revoke AI send authority atomically |
| human_active | reply_wait | waiting_customer | Sales | Send permitted channel response |
| waiting_customer | customer_reply | human_active | Sales/System | Set inbox unread |
| ai_active | reply_wait | waiting_customer | AI | Send verified answer |
| human_active | resolve | resolved | Sales | Close SLA and audit |
| resolved | new_message | reopened | System | Reopen with original context |

**No-go:** wrong actor, expired prior version, duplicate side effect, invalid sequence → business conflict/review, never silent success.

## FSM-05 — Lead

| From | Trigger | To | Authorized actor | Side effect / guard |
|---|---|---|---|---|
| new | qualify | qualified | Sales/AI authorized | Store consented requirements |
| qualified | prepare_quote | quoted | Sales | Link approved quote |
| qualified | lose | lost | Sales | Record reason |
| quoted | accept | won | Sales/System | Link order id |
| quoted | lose | lost | Sales | Record reason |
| lost | reopen | qualified | Sales | Recover with fresh data |

**No-go:** wrong actor, expired prior version, duplicate side effect, invalid sequence → business conflict/review, never silent success.

## FSM-06 — Quote

| From | Trigger | To | Authorized actor | Side effect / guard |
|---|---|---|---|---|
| draft | submit_review | review | Sales | Calculate all line values and compatibility |
| review | approve | approved | Manager | Freeze snapshot and validity |
| approved | send | sent | Sales/System | Channel-policy check |
| sent | customer_accept | accepted | Customer | Recheck validity on order creation |
| sent | expire | expired | Scheduler | Requote required |
| sent | reject | rejected | Customer | Allow revised quote |
| rejected | revise | draft | Sales | New version only |

**No-go:** wrong actor, expired prior version, duplicate side effect, invalid sequence → business conflict/review, never silent success.

## FSM-07 — Reservation

| From | Trigger | To | Authorized actor | Side effect / guard |
|---|---|---|---|---|
| requested | reserve | active | Inventory Service | Atomic available stock guard |
| active | allocate | allocated | Order Service | Confirm sale intent |
| active | expire | released | Scheduler | Idempotent release |
| active | cancel | released | Order Service | Idempotent release |
| allocated | fulfill | consumed | Fulfillment | Ledger sale once |
| allocated | cancel | released | Manager | Conditional compensation |

**No-go:** wrong actor, expired prior version, duplicate side effect, invalid sequence → business conflict/review, never silent success.

## FSM-08 — Order

| From | Trigger | To | Authorized actor | Side effect / guard |
|---|---|---|---|---|
| draft | submit | pending_confirmation | Customer/Sales | Check quote/lines |
| pending_confirmation | confirm | confirmed | Manager/System policy | Fresh pricing+stock, reserve |
| confirmed | pack | processing | Warehouse | Allocate SKU |
| processing | finish | completed | System/Manager | Require fulfillment completed |
| pending_confirmation | cancel | cancelled | Customer/Manager | Release reservations |
| confirmed | cancel | cancelled | Manager | Reconcile payment and stock |
| processing | cancel_review | exception | Manager | Manual recovery and refund check |
| exception | resolve_cancel | cancelled | Manager | Compensate side effects |
| exception | resume | processing | Manager | Audit resolution |

**No-go:** wrong actor, expired prior version, duplicate side effect, invalid sequence → business conflict/review, never silent success.

## FSM-09 — Payment

| From | Trigger | To | Authorized actor | Side effect / guard |
|---|---|---|---|---|
| initiated | await_provider | awaiting_confirmation | Customer | Generate instructions |
| awaiting_confirmation | verify | verified | System/Cashier | Verify callback or actual settlement |
| awaiting_confirmation | fail | failed | System | Release/hold order by policy |
| awaiting_confirmation | cancel | cancelled | Manager | Check late webhook risk |
| verified | request_refund | refund_pending | Manager | Eligibility and amount approval |
| refund_pending | complete_refund | refunded | Payment worker | Provider evidence + ledger |
| refund_pending | provider_fail | refund_failed | System | Keep case open |

**No-go:** wrong actor, expired prior version, duplicate side effect, invalid sequence → business conflict/review, never silent success.

## FSM-10 — Shipment

| From | Trigger | To | Authorized actor | Side effect / guard |
|---|---|---|---|---|
| pending | prepare | ready | Warehouse | Verify contents |
| ready | assign | assigned | Manager | Pick courier |
| assigned | dispatch | in_transit | Courier | Track handoff |
| in_transit | deliver | delivered | Courier/Customer proof | Evidence required |
| in_transit | fail | exception | Courier | Record reason |
| exception | reschedule | assigned | Manager | Notify buyer |
| exception | return | returned | Manager | Return and inventory inspection |

**No-go:** wrong actor, expired prior version, duplicate side effect, invalid sequence → business conflict/review, never silent success.

## FSM-11 — Return / Warranty

| From | Trigger | To | Authorized actor | Side effect / guard |
|---|---|---|---|---|
| new | review | in_review | Support | Gather evidence |
| in_review | approve | approved | Manager | Return instructions |
| in_review | reject | rejected | Manager | Reason + appeal option |
| approved | receive | in_service | Warehouse/Support | Inspect and track |
| in_service | resolve | resolved | Support | Refund/repair/replace evidence |
| resolved | close | closed | Support | Customer confirmation where possible |

**No-go:** wrong actor, expired prior version, duplicate side effect, invalid sequence → business conflict/review, never silent success.

## FSM-12 — Notification

| From | Trigger | To | Authorized actor | Side effect / guard |
|---|---|---|---|---|
| pending | schedule | scheduled | Worker | Respect opt-out/quiet hour |
| scheduled | send | sent | Worker | Store provider message id |
| scheduled | retry | scheduled | Worker | Bounded backoff |
| scheduled | fail | failed | Worker | Open DLQ/support task |
| pending | suppress | suppressed | Policy | Record suppression reason |

**No-go:** wrong actor, expired prior version, duplicate side effect, invalid sequence → business conflict/review, never silent success.

## FSM-13 — Integration connection

| From | Trigger | To | Authorized actor | Side effect / guard |
|---|---|---|---|---|
| draft | authorize | authorized | Owner | Store scoped secrets |
| authorized | initial_sync | syncing | Worker | Dry-run and cursor |
| syncing | healthy | healthy | Worker | Publish mapped data |
| healthy | error | degraded | System | Hold unsafe field sync and alert |
| degraded | recover | healthy | Worker | Reconcile source version |
| healthy | revoke | revoked | Owner | Stop sync and rotate secrets |

**No-go:** wrong actor, expired prior version, duplicate side effect, invalid sequence → business conflict/review, never silent success.

## FSM-14 — Public offer

| From | Trigger | To | Authorized actor | Side effect / guard |
|---|---|---|---|---|
| private | opt_in | pending_validation | Owner | Explicit fields and terms |
| pending_validation | publish | published | System | Validate price/condition/branch |
| published | age_out | stale | System | Hide or clearly flag policy |
| stale | reverify | published | Merchant/Sync | Update version |
| published | withdraw | withdrawn | Owner | Priority takedown event |
| published | hide | hidden | Moderator | Fraud/wrong-price review |

**No-go:** wrong actor, expired prior version, duplicate side effect, invalid sequence → business conflict/review, never silent success.

## FSM-15 — Product match

| From | Trigger | To | Authorized actor | Side effect / guard |
|---|---|---|---|---|
| unmatched | generate_candidates | candidate | Matching Engine | Evidence, attributes and confidence |
| candidate | request_review | review | Catalog Reviewer | Diff variants |
| candidate | auto_accept | matched | Rules (high confidence only) | Link reversible canonical ref |
| review | approve | matched | Catalog Reviewer | Audit match |
| review | reject | rejected | Catalog Reviewer | Retain aliases without merge |
| matched | split | review | Catalog Reviewer | Protect active offers during undo |

**No-go:** wrong actor, expired prior version, duplicate side effect, invalid sequence → business conflict/review, never silent success.

## FSM-16 — Merchant verification

| From | Trigger | To | Authorized actor | Side effect / guard |
|---|---|---|---|---|
| unverified | submit | in_review | Owner | Upload business evidence |
| in_review | approve | verified | Verification Team | Set expiry and proof |
| in_review | reject | rejected | Verification Team | Reason and appeal |
| verified | expire | expired | Scheduler | Remove verified badge |

**No-go:** wrong actor, expired prior version, duplicate side effect, invalid sequence → business conflict/review, never silent success.

## FSM-17 — Global referral

| From | Trigger | To | Authorized actor | Side effect / guard |
|---|---|---|---|---|
| created | send | delivered | System | Permission-controlled handoff |
| delivered | ack | acknowledged | Merchant | Record response SLA |
| acknowledged | sale | converted | Merchant/System | Optional attribution proof |
| delivered | timeout | expired | System | Do not invent conversion |
| acknowledged | lose | lost | Merchant | Reason stored |

**No-go:** wrong actor, expired prior version, duplicate side effect, invalid sequence → business conflict/review, never silent success.

## FSM-18 — Buyer price alert

| From | Trigger | To | Authorized actor | Side effect / guard |
|---|---|---|---|---|
| active | offer_meets_threshold | triggered | Alert Worker | Fresh offer & consent check |
| active | expire | expired | System | Auto-disable |
| active | unsubscribe | cancelled | Buyer | Immediate stop |
| triggered | reenable | active | Buyer | Explicit action |

**No-go:** wrong actor, expired prior version, duplicate side effect, invalid sequence → business conflict/review, never silent success.

## Multi-FSM sagas / compensations

### SAGA-S01: Confirmed order and stock
- Pre-check quote+stock → create order intent → atomically reserve → order confirm → notify.
- `reserve failed`: order remains pending/requires reprice; no «confirmed» UI.
- Notification failed: order state valid; notification queued/replayed.
- `order cancel`: unlock reservation exactly once; if payment already verified create refund/reconciliation task, no implicit cash reversal.

### SAGA-S02: Payment and fulfillment
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

## Timers to decide per merchant policy

| Timer | Triggers | Safe default behavior (no fabricated duration) |
|---|---|---|
| Quote expiry | `quote.valid_until` | Stop accept, force new quote |
| Reservation expiry | `reservation.expires_at` | Release if active, otherwise no-op |
| Merchant handoff SLA | `task.due_at` | Escalate assigned operator/manager |
| Payment proof review SLA | `payment.review_due_at` | Pending reminder, not auto-paid |
| Public offer freshness | `last_verified_at + freshness_policy` | Stale hide/warn; no cheapest claim |
| Integration sync health | `last_successful_sync_at` | Mark degraded, restrict affected data |
| Price alert cooldown | `alert.last_notified_at` | Dedup until policy threshold |
