# TECH-29 — Hisobot metrikalari registri

**Status:** Baseline (2026-10-22). M18, BL-063…066, DEC-100/100a (to'lov tizimdan tashqarida), DEC-112 (avval matnli hisobot), ADR-012 asosida.
**Kim uchun:** backend (reporting context), frontend (dashboard), AI (Business Copilot tool — TECH-26 §14).

**Asosiy qoida:** dashboard, matnli hisobot-chat, ovoz va eksport — hammasi **shu registrdagi** metrikalarni ishlatadi. AI yangi metrika "o'ylab topa" olmaydi, SQL yozmaydi (BL-063).

---

## 1. Har bir metrika nimani o'z ichiga oladi

| Maydon | Ma'nosi |
|---|---|
| `metric_id` | Barqaror ID (`orders_completed_count`) |
| `version` | Formula o'zgarsa yangi versiya; eski hisobotlar qaysi versiya bilan hisoblangani saqlanadi |
| `definition` | Odam tilidagi ta'rif (uz/ru/en) — UI'da "bu raqam nima?" tugmasi |
| `formula` | Aniq hisoblash (manba jadval, filtr, vaqt maydoni) |
| `time_field` | Qaysi sana bo'yicha davr hisoblanadi (masalan, `completed_at`, `created_at`) |
| `unit` | `count`, `money`, `percent`, `seconds` |
| `dimensions` | Ruxsat etilgan guruhlash: `day`, `week`, `month`, `branch`, `channel`, `category`, `sales_user` |
| `filters` | Ruxsat etilgan filtrlar |
| `permission` | Kim ko'radi (TECH-10 permission kodi) |
| `quality_flags` | Ma'lumot to'liq bo'lmasa qo'shiladigan belgilar |

## 2. Umumiy qoidalar

- **Davr va timezone:** davr chegaralari merchant timezone'ida (`Asia/Tashkent`); "bugun", "kecha", "shu hafta" (dushanbadan), "shu oy" shu timezone bo'yicha. Javobda doim `period.from`, `period.to`, `timezone`.
- **Valyuta:** summalar valyuta bo'yicha alohida; UZS va USD hech qachon jim qo'shilmaydi. Stage 1 da buyurtmalar UZS da (DEC-121), shuning uchun summa metrikalari UZS.
- **`data_as_of`:** read model oxirgi yangilangan vaqt; har javobda ko'rsatiladi (BL-066). Stage 1 da hisobotlar to'g'ridan-to'g'ri tranzaksion jadvallardan (kichik hajm) yoki 5 daqiqalik aggregate'lardan — `data_as_of` ikkalasida ham.
- **Ma'lumot yo'q ≠ nol:** hisoblab bo'lmasa `null` + `quality_flags`; haqiqatan nol bo'lsa `0` (TC-014).
- **Bekor qilingan buyurtmalar** summa va son metrikalariga kirmaydi (alohida metrika bor).

## 3. Stage 1 metrikalari

### 3.1 Buyurtmalar va sotuv

| `metric_id` | Formula | `time_field` | Unit | Permission |
|---|---|---|---|---|
| `orders_completed_count` | `COMPLETED` buyurtmalar soni | `completed_at` | count | `reports.read` |
| `orders_completed_amount` | `COMPLETED` buyurtmalar `total` yig'indisi | `completed_at` | money | `reports.read` (Sales — faqat o'ziniki) |
| `orders_average_amount` | `orders_completed_amount / orders_completed_count` | `completed_at` | money | `reports.read` |
| `orders_paid_marked_amount` | `COMPLETED` va `paid_mark_at` bor buyurtmalar summasi — **tekshirilmagan** (DEC-100a) | `completed_at` | money | `reports.read` + Finance/Owner/Manager |
| `orders_unpaid_marked_amount` | `COMPLETED`, lekin `paid_mark_at` yo'q — "olinmagan pul" ehtimoli | `completed_at` | money | Owner, Manager, Finance |
| `orders_pending_confirmation_count` | hozir `PENDING_CONFIRMATION` holatidagilar (snapshot) | — | count | `reports.read` |
| `orders_pending_confirmation_overdue_count` | `PENDING_CONFIRMATION` > `order_confirm_reminder_hours` | — | count | `reports.read` |
| `orders_cancelled_count` | `CANCELLED` buyurtmalar soni, sabab bo'yicha guruhlash | `cancelled_at` | count | `reports.read` |
| `orders_by_source` | buyurtmalar `source` bo'yicha (`AI`, `STOREFRONT`, `STAFF`) | `created_at` | count | `reports.read` |
| `offline_sales_count` / `offline_sales_units` | "tez sotuv" yozuvlari (DEC-123) | `created_at` | count | `reports.read` |
| `top_products_by_units` | `COMPLETED` buyurtma qatorlari + offline sotuv, SKU bo'yicha dona | `completed_at` | count | `reports.read` |

### 3.2 Suhbat va sotuv voronkasi

| `metric_id` | Formula | Unit | Permission |
|---|---|---|---|
| `conversations_started_count` | yangi suhbatlar, kanal bo'yicha | count | `reports.read` |
| `leads_by_channel` | yangi leadlar, kanal bo'yicha (Telegram / Instagram / web) | count | `reports.read` |
| `first_response_time_p50` / `_p90` | birinchi mazmunli javobgacha vaqt (AI yoki operator); avtomatik salom hisobga olinmaydi | seconds | Owner, Manager |
| `handoff_count` | operatorga uzatishlar, `reason` bo'yicha (TECH-26 §9) | count | Owner, Manager |
| `handoff_response_time_p50` | handoff'dan operator birinchi javobigacha | seconds | Owner, Manager |
| `conversion_conversation_to_order` | `DRAFT` buyurtma yaratilgan suhbatlar / barcha suhbatlar | percent | Owner, Manager |
| `conversion_order_to_completed` | `COMPLETED` / (`COMPLETED` + `CANCELLED`), cohort bo'yicha | percent | Owner, Manager |
| `quotes_sent_count`, `quotes_accepted_count` | PC quote'lar | count | `reports.read` |

### 3.3 AI

| `metric_id` | Formula | Unit | Permission |
|---|---|---|---|
| `ai_replies_count` | AI yuborgan javoblar | count | Owner, Manager |
| `ai_handoff_rate` | AI suhbatlaridan operatorga o'tganlari | percent | Owner, Manager |
| `ai_cost_amount` | LLM xarajati (merchant'ga ko'rsatiladi, limit bilan solishtirish) | money | Owner |
| `ai_validation_failures_count` | javob tekshiruvidan o'tmaganlar (TECH-26 §8) | count | Owner |

### 3.4 Stok

| `metric_id` | Formula | Unit | Permission |
|---|---|---|---|
| `stock_low_count` | `available` ≤ merchant chegarasi bo'lgan SKU'lar | count | Owner, Manager, Warehouse |
| `stock_value_amount` | `on_hand × joriy sotuv narxi` (tannarx emas) | money | Owner, Manager |
| `reservations_review_due_count` | 72 soatdan oshgan faol rezervlar (DEC-104) | count | Owner, Manager |

### 3.5 Hozircha yo'q (sabab bilan)

| Metrika | Holat |
|---|---|
| `profit_gross`, margin | Tannarx (COGS) Stage 1 da kiritilmaydi → hisoblanmaydi; so'ralsa "tannarx ma'lumoti yo'q" deb javob (BL-063, AC: foydani o'ylab topmaslik) |
| `sales_paid_gross` (tekshirilgan to'lov) | `DEFERRED` — to'lov moduli bilan (DEC-100) |
| Reklama atributsiyasi | Stage 2 |

## 4. Quality flags

| Flag | Qachon |
|---|---|
| `UNVERIFIED_PAID_MARK` | summa "to'landi" belgisiga asoslangan |
| `PARTIAL_PERIOD` | davr hali tugamagan (masalan, "bugun") |
| `STALE_DATA` | `data_as_of` 15 daqiqadan eski |
| `NO_COST_DATA` | foyda so'raldi, tannarx yo'q |
| `MIXED_CURRENCY_EXCLUDED` | USD qiymatlar UZS summaga kiritilmadi |
| `FEW_SAMPLES` | percentil uchun 20 tadan kam yozuv |

## 5. So'rov kontrakti

`POST /api/v1/merchant/reports/queries` (va AI tool `reports.query_metric` — xuddi shu sxema):

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
    {"metric_id": "orders_completed_amount", "unit": "money", "currency": "UZS", "rows": [{"day": "2026-10-21", "value_minor": 4200000000}], "total_minor": 21500000000, "quality_flags": ["PARTIAL_PERIOD"]}
  ]
}
```

Period preset'lari: `TODAY`, `YESTERDAY`, `LAST_7_DAYS`, `THIS_WEEK`, `LAST_WEEK`, `THIS_MONTH`, `LAST_MONTH`, yoki `{from, to}` (≤ 366 kun). Ruxsat yo'q metrika so'ralsa — o'sha metrika `FORBIDDEN` bilan, boshqalari qaytadi; qiymat oshkor qilinmaydi (TC-013).

## 6. Matnli hisobot-chat (S5, DEC-112)

1. Foydalanuvchi savoli → LLM faqat `reports.query_metric` argumentlarini tuzadi (metrika, davr, guruhlash).
2. Backend hisoblaydi.
3. Javob: raqamlar **shablon bilan** chiqariladi (LLM raqamni qayta yozmaydi), LLM faqat qisqa izoh qo'shadi; har javobda davr, timezone, `data_as_of`, flag'lar.
4. Savolni registrdagi metrikaga moslab bo'lmasa — "bu ko'rsatkich hozircha yo'q" va eng yaqin mavjud metrikalar ro'yxati.

## 7. Testlar

| ID | Sinov | Natija |
|---|---|---|
| TC-REP-01 | Seed: 3 COMPLETED, 1 CANCELLED, 1 PENDING | `orders_completed_count = 3`, bekor qilingan kirmaydi |
| TC-REP-02 | "Kecha" — Toshkent vaqti bilan 23:30 dagi buyurtma | kechaga kiradi (UTC'da boshqa kun bo'lsa ham) |
| TC-REP-03 | Hech qanday buyurtma yo'q | `0`, `null` emas |
| TC-REP-04 | "Foydam qancha?" | `NO_COST_DATA`, raqam aytilmaydi |
| TC-REP-05 | Sales boshqa operator summasini so'raydi | faqat o'z buyurtmalari |
| TC-REP-06 | A do'kon hisoboti | B ma'lumoti 0 (TC-ISO) |
