# 19 — Hisobotlar: metrika registri va read model'lar

> **Versiya:** v2 (2026-10-22). Eski `29_REPORTING_METRICS_REGISTRY` o'rnini bosadi.
> **Domen:** `reporting` (schema `reporting`) → sub-modullar `metrics`, `read_models`, `assistant`.
> **Biznes:** M18, BL-063…066, DEC-100/100a, DEC-112, ADR-012.
> **Kim o'qiydi:** backend, frontend (dashboard), AI (hisobot yordamchisi).

## 1. Muammo

1. Ega "kecha nechta buyurtma topshirildi?" deb so'raydi. Dashboard, matnli yordamchi, ovoz va eksport **bir xil raqam** berishi kerak. Har joy o'z SQL'ini yozsa — raqamlar farq qiladi.
2. Raqamlar bir nechta domendan keladi (`commerce`, `messaging`, `platform/llm`). Bismuth qoidasi bo'yicha `reporting` boshqa schemalarga JOIN qila olmaydi (ADR-035).
3. AI raqam yoki formula o'ylab topmasligi kerak (BL-063).

## 2. Yechim

- **Metrika registri** (`reporting/metrics`) — har metrika uchun aniq formula, versiya, ruxsat. Dashboard, yordamchi, ovoz va eksport faqat shu registr orqali ishlaydi.
- **Read model'lar** (`reporting/read_models`) — boshqa domenlar event'laridan quriladigan lokal jadvallar (bismuth `11` Pattern C). Metrikalar faqat shu jadvallardan hisoblanadi.
- **AI** faqat registrdagi metrikani tanlaydi va argument beradi; hisoblash — backend; raqam javobga shablon bilan qo'yiladi.

```
commerce ──commerce.order.* / stock.* / quote.* / quick_sale.recorded──┐
messaging ──messaging.message.* / conversation.*──────────────────────┤──▶ reporting subscriber'lari
catalog ──catalog.product.* / price.changed────────────────────────────┘        │ (idempotent upsert)
                                                                                ▼
                                                      reporting.* read model jadvallari
                                                                                │
                         dashboard / hisobot yordamchisi / ovoz / eksport ──▶ metrika registri ──▶ SQL (faqat reporting schemasi)
platform/llm (AI xarajati) ──────── to'g'ridan-to'g'ri platform xizmati ───────┘
```

## 3. Read model'lar

| Jadval | Manba event'lar | Asosiy ustunlar |
|---|---|---|
| `order_facts` | `commerce.order.drafted|submitted|confirmed|processing|ready|completed|cancelled|exception|paid_marked` | `shop_id`, `order_id`, `status`, `source` (`AI`, `STOREFRONT`, `STAFF`), `channel`, `branch_id`, `assigned_staff_id`, `total_minor`, `currency`, `created_at`, `confirmed_at`, `completed_at`, `cancelled_at`, `cancel_reason`, `paid_mark_at`, `aggregate_version` |
| `order_line_facts` | `commerce.order.completed` (qatorlar payload'da: `sku_id`, `qty`, `line_total_minor`) | `shop_id`, `order_id`, `sku_id`, `category`, `qty`, `line_total_minor` |
| `quick_sale_facts` | `commerce.quick_sale.recorded` | `shop_id`, `branch_id`, `sku_id`, `qty`, `amount_minor`, `recorded_at` |
| `quote_facts` | `commerce.quote.drafted|approval_requested|approved|sent|expired` | `shop_id`, `quote_id`, `status`, `sent_at`, `accepted_order_id` |
| `lead_facts` | `commerce.lead.created|status_changed` | `shop_id`, `lead_id`, `channel`, `status` |
| `stock_facts` | `commerce.stock.changed`, `commerce.reservation.created|released|expired` | `shop_id`, `branch_id`, `sku_id`, `on_hand`, `available`, `active_reservations`, `oldest_reservation_at` |
| `conversation_facts` | `messaging.message.received|sent`, `messaging.conversation.handed_off|returned_to_ai` | `shop_id`, `conversation_id`, `channel`, `started_at`, `first_meaningful_reply_at`, `first_reply_author` (`AI`/`STAFF`), `handoff_count`, `last_handoff_reason`, `handoff_first_staff_reply_at`, `ai_reply_count` |
| `product_dim` | `catalog.product.published|hidden|archived`, `catalog.price.changed` | `shop_id`, `sku_id`, `title`, `category`, `current_price_minor`, `currency` |
| `projection_checkpoints` | — | `projection`, `shop_id`, `last_event_id`, `last_occurred_at` — `data_as_of` manbai |

### Read model qoidalari

1. **Idempotent:** har subscriber upsert qiladi va `aggregate_version` ni solishtiradi — eski versiya yangisini bosib o'tmaydi; bir event 3 marta kelsa natija bir xil.
2. **Payload yetarli bo'lishi kerak:** `commerce.order.*` event'lari `total_minor`, `currency`, `source`, `channel`, `branch_id`, `assigned_staff_id` ni o'z ichiga oladi (shaxsiy ma'lumotsiz). Kerakli maydon payload'da bo'lmasa — `05-events-and-outbox.md` dagi payload sxemasiga qo'shiladi, `reporting` Query Port orqali har event uchun so'ramaydi.
3. **Qayta qurish (rebuild):** outbox — doimiy event arxivi emas. Proyeksiyani noldan qurish uchun egasi domenning Query Port'idagi paginatsiyalangan "backfill" metodlari ishlatiladi (`CommerceQueryPort.list_orders_for_backfill(shop_id, cursor)`, `MessagingQueryPort.list_conversations_for_backfill(...)`). Rebuild — platforma admini buyrug'i, arq vazifasi, shop bo'yicha.
4. **Shaxsiy ma'lumot yo'q:** read model'larda xaridor ismi, telefoni, xabar matni saqlanmaydi.
5. Har read model jadvalida `shop_id NOT NULL` va RLS.

## 4. Metrika registri

Registr — kodda (`reporting/metrics/registry.py`), versiyalangan (`metric_registry_version = "2026-10-v1"`). DB'da emas: formula o'zgarishi kod review'dan o'tadi.

| Maydon | Ma'nosi |
|---|---|
| `metric_id` | Barqaror ID (`orders_completed_count`) |
| `version` | Formula o'zgarsa yangi versiya; javobda qaysi versiya ishlatilgani ko'rsatiladi |
| `definition` | Odam tilidagi ta'rif (uz/ru/en) — UI'dagi "bu raqam nima?" |
| `source` | Read model jadvali va formula (SQLAlchemy ifodasi) |
| `time_field` | Davr qaysi sana bo'yicha (`completed_at`, `created_at`) |
| `unit` | `count`, `money`, `percent`, `seconds` |
| `dimensions` | Ruxsat etilgan guruhlash: `day`, `week`, `month`, `branch`, `channel`, `category`, `staff` |
| `filters` | Ruxsat etilgan filtrlar |
| `permission` | Ruxsat kodi (§6) |
| `row_scope` | `ALL` yoki `OWN` (operator — faqat o'ziga biriktirilganlar) |
| `quality_rules` | Qachon `quality_flags` qo'shiladi |

## 5. Umumiy qoidalar

- **Davr va vaqt zonasi:** chegaralar shop vaqt zonasida (`Asia/Tashkent`, `platform/shops` sozlamasi). "Bugun", "kecha", "shu hafta" (dushanbadan), "shu oy". Javobda doim `period.from`, `period.to`, `timezone`.
- **Valyuta:** summalar valyuta bo'yicha alohida; UZS va USD hech qachon jim qo'shilmaydi. Stage 1 da buyurtmalar UZS da (DEC-121).
- **`data_as_of`:** tegishli proyeksiyaning `last_occurred_at` qiymati (eng eski). Har javobda (BL-066).
- **Ma'lumot yo'q ≠ nol:** hisoblab bo'lmasa `null` + flag; haqiqatan nol bo'lsa `0` (TC-014).
- **Bekor qilingan buyurtmalar** summa va son metrikalariga kirmaydi (alohida metrika bor).

## 6. Ruxsatlar (`../business/04` ga mos)

| Ruxsat kodi | Ega | Menejer | Operator | Omborchi | Moliya | Tahlilchi |
|---|---|---|---|---|---|---|
| `reporting.report.read` | Ha | Ha (o'z filiallari) | O'ziniki (`row_scope=OWN`) | O'z filiali (stok metrikalari) | Ha | Ha (umumiy) |
| `reporting.staff_breakdown.read` (xodim bo'yicha guruhlash) | Ha | Ha | — | — | Ha | — |
| `reporting.ai_cost.read` | Ha | — | — | — | — | — |
| `reporting.margin.read` (tannarx, foyda) | Ha | Ruxsat bilan | — | — | Ruxsat bilan | — |
| `reporting.export.run` | Ha | Ha | — | — | Ha | Ha |

Hisobot yordamchisi har doim **so'rayotgan foydalanuvchining** ruxsatlari bilan ishlaydi (`04` §2). Ruxsat yo'q metrika so'ralsa — o'sha metrika `FORBIDDEN`, qiymat oshkor qilinmaydi, urinish audit'ga yoziladi (TC-013).

## 7. Stage 1 metrikalari

### 7.1 Buyurtmalar va sotuv (`order_facts`, `order_line_facts`, `quick_sale_facts`)

| `metric_id` | Formula | `time_field` | Unit | Ruxsat |
|---|---|---|---|---|
| `orders_completed_count` | `COMPLETED` buyurtmalar soni | `completed_at` | count | `reporting.report.read` |
| `orders_completed_amount` | `COMPLETED` `total_minor` yig'indisi | `completed_at` | money | `reporting.report.read` (operator — o'ziniki) |
| `orders_average_amount` | amount / count | `completed_at` | money | `reporting.report.read` |
| `orders_paid_marked_amount` | `COMPLETED` va `paid_mark_at` bor — **tekshirilmagan** (DEC-100a) | `completed_at` | money | Ega, menejer, moliya |
| `orders_unpaid_marked_amount` | `COMPLETED`, `paid_mark_at` yo'q | `completed_at` | money | Ega, menejer, moliya |
| `orders_pending_confirmation_count` | hozir `PENDING_CONFIRMATION` (snapshot) | — | count | `reporting.report.read` |
| `orders_pending_confirmation_overdue_count` | `PENDING_CONFIRMATION` > 24 soat (shop sozlamasi) | — | count | `reporting.report.read` |
| `orders_cancelled_count` | `CANCELLED`, sabab bo'yicha | `cancelled_at` | count | `reporting.report.read` |
| `orders_by_source` | `source` bo'yicha | `created_at` | count | `reporting.report.read` |
| `offline_sales_count` / `offline_sales_units` | "tez sotuv" (DEC-123) | `recorded_at` | count | `reporting.report.read` |
| `top_products_by_units` | `order_line_facts` + `quick_sale_facts`, SKU bo'yicha | `completed_at` | count | `reporting.report.read` |

### 7.2 Suhbatlar va sotuv voronkasi (`conversation_facts`, `lead_facts`, `quote_facts`)

| `metric_id` | Formula | Unit | Ruxsat |
|---|---|---|---|
| `conversations_started_count` | yangi suhbatlar, kanal bo'yicha | count | `reporting.report.read` |
| `leads_by_channel` | yangi leadlar, kanal bo'yicha | count | `reporting.report.read` |
| `first_response_time_p50` / `_p90` | birinchi mazmunli javobgacha (AI yoki operator); avtomatik salom hisoblanmaydi | seconds | Ega, menejer |
| `handoff_count` | operatorga uzatishlar, sabab bo'yicha | count | Ega, menejer |
| `handoff_response_time_p50` | uzatishdan operatorning birinchi javobigacha | seconds | Ega, menejer |
| `conversion_conversation_to_order` | buyurtma qoralamasi yaratilgan suhbatlar / barcha suhbatlar | percent | Ega, menejer |
| `conversion_order_to_completed` | `COMPLETED` / (`COMPLETED` + `CANCELLED`) | percent | Ega, menejer |
| `quotes_sent_count`, `quotes_accepted_count` | PC takliflar | count | `reporting.report.read` |

"Mazmunli javob" belgisi `messaging.message.sent` payload'idagi `is_automated_greeting = false` dan olinadi.

### 7.3 AI

| `metric_id` | Manba | Unit | Ruxsat |
|---|---|---|---|
| `ai_replies_count` | `conversation_facts.ai_reply_count` | count | Ega, menejer |
| `ai_handoff_rate` | AI boshlagan suhbatlardan operatorga o'tganlari | percent | Ega, menejer |
| `ai_cost_amount` | `platform/llm` ishlatilish hisobi (to'g'ridan-to'g'ri platform xizmati: `llm.usage.summary(shop_id, period)`) | money | `reporting.ai_cost.read` |
| `ai_validation_failures_count` | `sales_ai.reply.validation_failed` event'i (`14` §8) | count | Ega |

### 7.4 Stok (`stock_facts`)

| `metric_id` | Formula | Unit | Ruxsat |
|---|---|---|---|
| `stock_low_count` | `available` ≤ shop chegarasi bo'lgan SKU'lar | count | Ega, menejer, omborchi |
| `stock_value_amount` | `on_hand × joriy sotuv narxi` (`product_dim`; tannarx emas) | money | Ega, menejer |
| `reservations_review_due_count` | 72 soatdan oshgan faol band qilishlar (DEC-104) | count | Ega, menejer |

### 7.5 Hozircha yo'q

| Metrika | Holat |
|---|---|
| `profit_gross`, marja | Tannarx Stage 1 da kiritilmaydi. So'ralsa — "tannarx ma'lumoti yo'q" (`NO_COST_DATA`), raqam aytilmaydi |
| `sales_paid_gross` (tekshirilgan to'lov) | DEFERRED — `payments` domeni bilan (DEC-100) |
| Reklama atributsiyasi | Stage 2 |

## 8. Quality flag'lar

| Flag | Qachon |
|---|---|
| `UNVERIFIED_PAID_MARK` | Summa "to'landi" belgisiga asoslangan |
| `PARTIAL_PERIOD` | Davr hali tugamagan |
| `STALE_DATA` | `data_as_of` 15 daqiqadan eski (proyeksiya orqada) |
| `NO_COST_DATA` | Foyda so'raldi, tannarx yo'q |
| `MIXED_CURRENCY_EXCLUDED` | USD qiymatlar UZS summaga kiritilmadi |
| `FEW_SAMPLES` | Percentil uchun 20 tadan kam yozuv |

## 9. So'rov kontrakti

`POST /api/v1/shop/reports/queries` (ruxsat: `reporting.report.read`) va AI tool `reporting.query_metric` — bitta sxema:

```json
{
  "metric_ids": ["orders_completed_count", "orders_completed_amount"],
  "period": {"preset": "LAST_7_DAYS"},
  "group_by": ["day"],
  "filters": {"channel": ["TELEGRAM", "INSTAGRAM"]}
}
```

```json
{
  "metric_registry_version": "2026-10-v1",
  "period": {"from": "2026-10-15T00:00:00+05:00", "to": "2026-10-22T00:00:00+05:00"},
  "timezone": "Asia/Tashkent",
  "data_as_of": "2026-10-22T09:10:00Z",
  "results": [
    {"metric_id": "orders_completed_count", "unit": "count", "rows": [{"day": "2026-10-21", "value": 4}], "total": 19, "quality_flags": []},
    {"metric_id": "orders_completed_amount", "unit": "money", "currency": "UZS",
     "rows": [{"day": "2026-10-21", "value_minor": 4200000000}], "total_minor": 21500000000, "quality_flags": ["PARTIAL_PERIOD"]}
  ]
}
```

Preset'lar: `TODAY`, `YESTERDAY`, `LAST_7_DAYS`, `THIS_WEEK`, `LAST_WEEK`, `THIS_MONTH`, `LAST_MONTH` yoki `{from, to}` (≤ 366 kun). Eksport: `POST /api/v1/shop/reports/exports` → arq → CSV/XLSX `platform/storage` da (signed URL, 24 soat).

## 10. Hisobot yordamchisi (matn, S5, DEC-112)

`reporting/assistant`:
1. Foydalanuvchi savoli → `platform/llm` (redaction'dan keyin) faqat `reporting.query_metric` argumentlarini tuzadi: metrika, davr, guruhlash.
2. Backend argumentlarni registr bo'yicha tekshiradi va hisoblaydi.
3. Javob: raqamlar **shablon bilan** qo'yiladi (LLM raqamni qayta yozmaydi); LLM faqat qisqa izoh qo'shadi; har javobda davr, vaqt zonasi, `data_as_of`, flag'lar.
4. Savolni registrdagi metrikaga moslab bo'lmasa — "bu ko'rsatkich hozircha yo'q" va eng yaqin mavjud metrikalar.
5. AI limiti tugagan bo'lsa (`platform.ai_quota.exhausted`) — yordamchi o'chadi, dashboard ishlayveradi (BL-069).

Ovozli savol — beta, xuddi shu kontrakt orqali: [15-voice-assistant.md](15-voice-assistant.md).

## 11. Kuzatuv

- `cos_reporting_projection_lag_seconds{projection}` — alert: > 15 daqiqa.
- `cos_reporting_query_duration_seconds{metric_id}`.
- `cos_reporting_assistant_unmapped_total` — registrga mos kelmagan savollar (yangi metrika ehtiyoji).

## 12. Testlar

| ID | Sinov | Natija |
|---|---|---|
| TC-REP-01 | 3 COMPLETED, 1 CANCELLED, 1 PENDING | `orders_completed_count = 3` |
| TC-REP-02 | "Kecha" — Toshkent 23:30 dagi buyurtma | Kechaga kiradi |
| TC-REP-03 | Hech qanday buyurtma yo'q | `0`, `null` emas (TC-014) |
| TC-REP-04 | "Foydam qancha?" | `NO_COST_DATA`, raqam yo'q |
| TC-REP-05 | Operator boshqa operator summasini so'raydi | Faqat o'zinikilar (TC-013) |
| TC-REP-06 | A shop hisoboti | B ma'lumoti 0 (TC-ISO) |
| TC-REP-07 | `commerce.order.completed` 3 marta, tartibsiz versiyalar bilan | Read model to'g'ri, ikki marta sanalmaydi |
| TC-REP-08 | Proyeksiya rebuild | Rebuild'dan oldin va keyin raqamlar bir xil |

## Keyingi qadam

→ [15-voice-assistant.md](15-voice-assistant.md) — ovozli savollar (beta)
→ [05-events-and-outbox.md](05-events-and-outbox.md) — payload sxemalari
