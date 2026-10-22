# reporting

**Qatlam:** domain · **Schema:** `reporting` · **Slice:** S5 (ovoz — beta, S5+) · **Egasi:** ___
**Biznes modullar:** M18 · **Qoidalar:** BL-063, BL-064, BL-065, BL-066, DEC-100a, DEC-112, ADR-012 · **Holatlar:** o'z FSM'i yo'q

## 1. Nima qiladi

Dashboard, matnli hisobot yordamchisi, ovoz va eksport uchun **bitta raqam manbai**. Raqamlar boshqa domenlar event'laridan quriladigan lokal read model'lardan hisoblanadi. Boshqa schemalarga JOIN yo'q (ADR-035).

Har metrikaning aniq formulasi bor (BL-063). AI faqat metrika tanlaydi va argument beradi, raqam o'ylab topmaydi. Har javobda davr, vaqt zonasi va `data_as_of` bor (BL-066). Ma'lumot yo'q bo'lsa `null` + flag, haqiqiy nol bo'lsa `0` (TC-014).

Bu domen qilmaydi:
- boshqa domen ma'lumotini o'zgartirish;
- tannarx va foyda hisoblash — Stage 1 da tannarx yo'q, `NO_COST_DATA`.

Batafsil: [19-reporting-metrics.md](../../engineering/19-reporting-metrics.md), ovoz — [15-voice-assistant.md](../../engineering/15-voice-assistant.md).

## 2. Sub-modullar

| Sub-modul | Vazifasi | Asosiy jadvallar |
|---|---|---|
| `metrics` | Metrika registri (kodda, `metric_registry_version = "2026-10-v1"`), so'rov kontrakti, quality flag'lar | — (registr kodda) |
| `read_models` | Event subscriber'lari, idempotent upsert, rebuild | `order_facts`, `order_line_facts`, `quick_sale_facts`, `quote_facts`, `lead_facts`, `stock_facts`, `conversation_facts`, `support_case_facts`, `product_dim`, `projection_checkpoints` (`19` §3, `07` §4.9) |
| `assistant` | Matnli hisobot yordamchisi, ovoz (beta) | — |

## 3. Holatlar

Domenning o'z holatlar ketma-ketligi yo'q. Read model qatorlari `aggregate_version` bo'yicha yangilanadi: eski versiya yangisini bosib o'tmaydi.

## 4. Event'lar

### Chiqaradi

Yo'q.

### Tinglaydi (`19` §3, `05` §8)

| Event | Kimdan | Nima qiladi |
|---|---|---|
| `commerce.order.drafted` / `submitted` / `confirmed` / `processing` / `ready` / `completed` / `cancelled` / `exception` / `paid_marked` | commerce | `order_facts`, `order_line_facts` (`completed` dagi qatorlardan) |
| `commerce.quick_sale.recorded` | commerce | `quick_sale_facts` |
| `commerce.quote.*`, `commerce.lead.*` | commerce | `quote_facts`, `lead_facts` |
| `commerce.stock.changed`, `commerce.reservation.created` / `released` / `expired` | commerce | `stock_facts` |
| `messaging.message.received` / `sent`, `messaging.conversation.handed_off` / `returned_to_ai` | messaging | `conversation_facts`. "Mazmunli javob" — `is_automated_greeting = false` |
| `catalog.product.*`, `catalog.price.changed` | catalog | `product_dim` |
| `sales_ai.reply.validation_failed` | sales_ai | `ai_validation_failures_count` |
| `support.case.*` | support | `05` da iste'molchi sifatida ko'rsatilgan; `19` read model'larida jadvali yo'q (§11) |
| `platform.privacy.*` | platform/privacy | O'z qismi — read model'larda shaxsiy ma'lumot yo'q ([26](../../engineering/26-privacy-and-retention.md)) |

**AI xarajati** — event emas. Platform xizmati to'g'ridan-to'g'ri chaqiriladi: `llm.usage.summary(shop_id, period)`.

## 5. Query Port

**Beradi:** yo'q.

**Ishlatadi** (faqat rebuild uchun, paginatsiyalangan):
- `CommerceQueryPort.list_orders_for_backfill`;
- `MessagingQueryPort.list_conversations_for_backfill`.

## 6. API (`shop` surface)

| Metod va yo'l | Ruxsat | Idempotency |
|---|---|---|
| `GET /shop/reports/summary`, `POST /shop/reports/queries` | `reporting.report.read` (+ `reporting.margin.read`, `reporting.staff_breakdown.read`, `reporting.ai_cost.read`) | — / Idem |
| `POST /shop/reports/assistant/messages` | `reporting.assistant.ask` | Idem |
| `POST /shop/reports/exports` (202, arq) | `reporting.export.run` | Idem |
| `POST /shop/reports/voice/transcriptions` (beta, flag `reporting.voice`, 202) | `reporting.assistant.ask` | Idem |

- Manba: [11](../../engineering/11-api-conventions-errors-i18n.md) §9.9.
- So'rov va javob sxemasi: [19](../../engineering/19-reporting-metrics.md) §9.
- AI tool: `reporting.query_metric` — xuddi shu sxema.

## 7. Ruxsatlar ([10](../../engineering/10-security-tenancy-rbac.md))

| Kod | Ega | Menejer | Operator | Omborchi | Moliya | Tahlilchi |
|---|---|---|---|---|---|---|
| `reporting.report.read` | ✓ | ✓ | o'ziniki | o'z filiali | ✓ | umumiy |
| `reporting.staff_breakdown.read` | ✓ | ✓ | — | — | ✓ | — |
| `reporting.ai_cost.read` | ✓ | — | — | — | ✓ | — |
| `reporting.margin.read` | ✓ | ruxsat bilan | — | — | ruxsat bilan | ruxsat bilan |
| `reporting.export.run` | ✓ (qo'shimcha tasdiq) | ✓ | — | — | ✓ | umumiy |
| `reporting.assistant.ask` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |

- Yordamchi har doim so'rayotgan foydalanuvchining ruxsatlari bilan ishlaydi.
- Ruxsatsiz metrika → `FORBIDDEN`, urinish audit'ga yoziladi (TC-013).

## 8. Fon va rejali ishlar

| Ish | Qachon | Idempotency kaliti |
|---|---|---|
| `report_export` (arq, `low`) | Eksport so'rovi | `export_id` |
| `voice_transcribe` (arq, beta) | Ovozli savol | `audio_id` |
| `audio_purge` (scheduler) | Har soat (DEC-117) | `audio_id` |
| Proyeksiya rebuild (arq, platforma admini buyrug'i) | Qo'lda | shop + proyeksiya |

## 9. Metrikalar

- `cos_reporting_query_duration_seconds`, `cos_reporting_unauthorized_metric_total`, `cos_reporting_voice_transcript_corrected_total` ([09](../../engineering/09-observability.md))
- `cos_reporting_projection_lag_seconds` (alert > 15 daqiqa), `cos_reporting_assistant_unmapped_total` ([19](../../engineering/19-reporting-metrics.md) §11, [09](../../engineering/09-observability.md))

## 10. Testlar

- TC-012, TC-013, TC-014, UAT-M18
- TC-REP-01…08 ([19](../../engineering/19-reporting-metrics.md) §12)
- Ovoz testlari: [15](../../engineering/15-voice-assistant.md) §10
- TC-ISO — A shop hisobotida B ma'lumoti yo'q

## 11. Ochiq savollar

Hozircha yo'q.
