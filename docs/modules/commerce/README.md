# commerce

**Qatlam:** domain · **Schema:** `commerce` · **Slice:** S1 (ombor), S3 (lead, taklif), S4 (buyurtma) · **Egasi:** ___
**Biznes modullar:** M06, M12, M13 (keyin M25) · **Qoidalar:** BL-019…023, BL-109 (ombor), BL-042…045 (lead, taklif), BL-046…049, BL-111 (buyurtma); BR-X01, X03, X11, X13, X14 · **Holatlar:** FSM-05, FSM-06, FSM-07, FSM-08 (`../../business/05`)

## 1. Nima qiladi

Shopning savdo yadrosi: qoldiq va uning tarixi, band qilish, do'kondagi "tez sotuv", leadlar, PC takliflari va buyurtmalar. Buyurtmani tasdiqlash va mahsulotni band qilish **bitta tranzaksiyada** shu domen ichida bo'ladi — shuning uchun bu qismlar bitta domenda (DEC-126, ADR-032).

Nima qilmaydi: narxni belgilamaydi (`catalog`), xaridorga xabar yubormaydi (`messaging` / `platform/notifications`), to'lov va yetkazish yo'q (DEC-100, DEC-113). AI bu domenga faqat event orqali **qoralama** so'raydi.

## 2. Sub-modullar

| Sub-modul | Vazifasi | Asosiy jadvallar |
|---|---|---|
| `inventory` | Qoldiq (`on_hand`/`reserved`/`allocated`, qaytgan mahsulot — `quarantine_qty`), ledger, tuzatish so'rovlari, band qilish, tez sotuv | `stock_balances`, `stock_ledger`, `stock_adjustment_requests`, `reservations`, `quick_sales` |
| `leads` | Sotuv imkoniyatlari | `leads` |
| `quotes` | PC taklif: revision'lar, narx va moslik snapshot'i, ommaviy havola | `quotes`, `quote_revisions`, `quote_lines`, `quote_compatibility_snapshots` |
| `orders` | Buyurtma, qatorlar (narx/kurs/kafolat snapshot), izohlar, "to'landi" belgisi | `orders`, `order_lines`, `order_notes` |

Ustunlar va cheklovlar — [07-data-layer.md](../../engineering/07-data-layer.md) §4.4.

## 3. Holatlar

```
Buyurtma (FSM-08):
DRAFT ──SUBMIT──▶ PENDING_CONFIRMATION ──CONFIRM──▶ CONFIRMED ──START_PROCESSING──▶ PROCESSING ──COMPLETE──▶ COMPLETED
PENDING_CONFIRMATION | CONFIRMED | EXCEPTION ──CANCEL (menejer/ega, sabab)──▶ CANCELLED
PROCESSING ──RAISE_EXCEPTION──▶ EXCEPTION ──RESOLVE_TO_PROCESSING──▶ PROCESSING
Holatsiz amallar: MARK_READY (ready_at), MARK_PAID (paid_mark, DEC-100a)

Band qilish (FSM-07): ACTIVE ──ALLOCATE──▶ ALLOCATED ──CONSUME──▶ CONSUMED;  ACTIVE|ALLOCATED ──RELEASE──▶ RELEASED;  ACTIVE ──EXPIRE (menejer)──▶ EXPIRED

Taklif (FSM-06): DRAFT ──SUBMIT_FOR_REVIEW──▶ REVIEW ──APPROVE──▶ APPROVED ──SEND──▶ SENT ──ACCEPT──▶ ACCEPTED
                 SENT ──EXPIRE──▶ EXPIRED;  SENT ──REJECT──▶ REJECTED ──REVISE──▶ yangi revision DRAFT

Lead (FSM-05): NEW → QUALIFIED → QUOTED → WON | LOST
```
To'liq qoidalar va buyruqlar — [04-state-machines-and-use.md](../../engineering/04-state-machines-and-use.md) §4.1.

## 4. Event'lar

### Chiqaradi
| Event | Qachon | Kim tinglaydi |
|---|---|---|
| `commerce.stock.changed` | qoldiq o'zgardi | storefront, reporting |
| `commerce.quick_sale.recorded` | tez sotuv | reporting |
| `commerce.reservation.created` / `released` / `expired` | FSM-07 | reporting |
| `commerce.lead.created`, `commerce.lead.status_changed` | FSM-05 | messaging, reporting |
| `commerce.quote.drafted` / `approval_requested` / `approved` / `sent` / `expired` | FSM-06 | sales_ai, messaging, reporting |
| `commerce.order.drafted` / `submitted` / `confirmed` / `processing` / `ready` / `completed` / `cancelled` / `exception` / `paid_marked` | FSM-08 va holatsiz amallar | messaging, support, reporting |
| `commerce.import_stock.applied` | import qoldig'i qo'llandi | catalog, reporting |

### Tinglaydi
| Event | Kimdan | Nima qiladi |
|---|---|---|
| `sales_ai.order_draft.requested` | sales_ai | `DRAFT` buyurtma (qoldiq o'zgarmaydi, TC-028); `source_request_id UNIQUE` |
| `sales_ai.quote_draft.requested` | sales_ai | Taklif qoralamasi |
| `sales_ai.quote_approval.requested` | sales_ai | `SUBMIT_FOR_REVIEW` |
| `sales_ai.lead_capture.requested` | sales_ai | Lead yaratish yoki `QUALIFY` |
| `catalog.import.completed` (`has_stock_rows`) | catalog | `CatalogQueryPort.get_import_stock_rows()` → `RECEIPT`/`ADJUSTMENT` |
| `catalog.pc_ruleset.activated` | catalog | Yangi takliflar yangi qoidalar versiyasi bilan |
| `support.case.status_changed`, `support.case.resolved` | support | `IN_SERVICE` → `quarantine_qty +1` (ledger `RETURN_QUARANTINE`, sotilmaydi, BR-X11); hal qilinganda omborchiga qaror vazifasi (`RETURN_RESTOCK`) |
| `platform.shop.policy_changed` | platform | Muddatlar (taklif TTL, eslatmalar) yangilanadi |
| `platform.staff.access_revoked` | platform | Buyurtmalarni qayta biriktirish vazifasi |
| `platform.privacy.*` | platform | `privacy_handlers` |

Payload'lar — [05-events-and-outbox.md](../../engineering/05-events-and-outbox.md) §8.2.

## 5. Query Port (`CommerceQueryPort`)

| Metod | Kim ishlatadi |
|---|---|
| `get_availability` | sales_ai (tool `catalog.get_price_stock`), storefront |
| `get_stock_levels` | storefront, reporting |
| `get_order_status` | sales_ai (`commerce.lookup_order_status`) |
| `get_order_for_support` | support (buyurtma tekshiruvi, `warranty_snapshot`) |
| `get_import_stock_results` | catalog (import holati) |
| `list_orders_for_backfill` | reporting (read model qayta qurish) |

Interfeys — `app/shared/contracts/commerce.py`.

## 6. API

`shop` surface: `/shop/stock`, `/shop/stock/receipts`, `/shop/stock/adjustment-requests`, `/shop/quick-sales`, `/shop/leads`, `/shop/quotes`, `/shop/orders` (+ `/submit`, `/confirm`, `/start-processing`, `/mark-ready`, `/complete`, `/cancel`, `/exception`, `/resolve-exception`, `/paid-mark`, `/notes`), `/shop/discount-requests`.
`storefront` surface: `POST /storefront/{slug}/order-requests`, `GET /storefront/{slug}/orders/{tracking_token}`, `GET|POST /storefront/{slug}/quotes/{token}[/accept|/reject]`.

Yozish amallari — `Idempotency-Key`, holat o'tishlari — `If-Match`. To'liq ro'yxat — [11](../../engineering/11-api-conventions-errors-i18n.md) §9.4, §9.8. Tasdiqlash algoritmi — [12](../../engineering/12-concurrency-and-transactions.md) §5.

Asosiy xatolar: `INSUFFICIENT_AVAILABLE_STOCK`, `PRICE_CHANGED`, `QUOTE_EXPIRED`, `VERSION_CONFLICT`, `INVALID_STATE_TRANSITION`, `SELF_APPROVAL_NOT_ALLOWED`, `APPROVAL_REQUIRED`, `EXCHANGE_RATE_STALE`, `BRANCH_CLOSED`.

## 7. Ruxsatlar

`commerce.stock.view|receive|adjust_request|adjust_approve`, `commerce.quick_sale.create`, `commerce.lead.view|edit`, `commerce.quote.draft|view|approve|send`, `commerce.order.view|create_draft|confirm|process|complete|cancel|paid_mark|note`, `commerce.discount.apply|request|approve`. Rollar bo'yicha jadval — [10](../../engineering/10-security-tenancy-rbac.md) §6.3 (manba: `business/04`). Operator faqat o'ziga biriktirilgan buyurtmani tasdiqlaydi va hech qaysini bekor qila olmaydi (DEC-108, TC-029).

## 8. Fon va rejali ishlar

| Ish | Qachon | Idempotency kaliti |
|---|---|---|
| `order_confirm_reminder` | har 15 daq; `PENDING_CONFIRMATION` > 24 soat | `order_reminder:{order_id}:24h` |
| `reservation_review` | har 15 daq; `ACTIVE` > 72 soat → menejerga vazifa | `reservation_review:{reservation_id}:72h` |
| `quote_expiry` | har 5 daq; `SENT` va muddat o'tgan → `EXPIRE` | holat o'tishi |

Hech bir rejali ish buyurtma yoki rezervni avtomatik bekor qilmaydi (DEC-104). Batafsil — [06](../../engineering/06-background-jobs.md) §5.2.

## 9. Metrikalar

`cos_commerce_order_drafted_total`, `cos_commerce_order_confirmed_total`, `cos_commerce_order_confirm_conflict_total`, `cos_commerce_order_completed_total`, `cos_commerce_order_cancelled_total`, `cos_commerce_order_pending_confirmation_age_seconds`, `cos_commerce_order_confirm_duration_seconds`, `cos_commerce_stock_reserve_conflict_total`, `cos_commerce_stock_negative_total`, `cos_commerce_stock_ledger_mismatch_total`, `cos_commerce_quick_sale_total`, `cos_commerce_quote_approved_total` — [09-observability.md](../../engineering/09-observability.md).

## 10. Testlar

- Concurrency: TC-002 (oxirgi mahsulot), TC-003 (takror tasdiq), TC-027 (tez sotuv va online), TC-030 (topshirish bir marta) — `tests/concurrency/`.
- TC-028 (AI faqat qoralama), TC-029 (operator huquqi), TC-031 (narx o'zgardi), TC-020 (qaytgan mahsulot), TC-001 / TC-ISO.
- UAT-M06, UAT-M12, UAT-M13 (`../../business/10`).

## 11. Ochiq savollar

1. Stage 2 da `payments` qaytsa — `commerce` ichida sub-modulmi yoki alohida domen (ADR-032 "Neytral").

Hal qilinganlar (founder, 2026-10-22): tasdiqlashda narx — sinxron `CatalogQueryPort.get_active_price()` ([12](../../engineering/12-concurrency-and-transactions.md) §5.1); saytda qoldiq ko'rsatish — shop sozlamasi `stock_display` ([08](../../engineering/08-cache-and-realtime.md) §4.5).
