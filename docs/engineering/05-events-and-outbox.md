# 05 — Event'lar va outbox

> **Versiya:** v2 (2026-10-22). ADR-032 (DEC-126), ADR-033 (DEC-003 D), K-08. Eski `09_EVENTS_OUTBOX_AND_JOBS` va `35_MODULE_INTERACTIONS_AND_EVENTS` o'rnini bosadi.
> **Kim o'qiydi:** backend dasturchilar.

## 1. Muammo

Domenlar bir-birini import qilmaydi (`00` 3–4-prinsiplar). Lekin ular bir-biriga ta'sir qilishi kerak: AI "olaman" eshitsa, `commerce` qoralama yaratishi; buyurtma tasdiqlansa, `reporting` hisobni yangilashi; mahsulot saytdan yashirilsa, `storefront` keshni tozalashi kerak.

Agar service COMMIT'dan keyin to'g'ridan-to'g'ri "xabar yuborsa", server shu ikki qadam o'rtasida o'chib qolganda xabar **yo'qoladi**. Agar COMMIT'dan oldin yuborsa, tranzaksiya bekor bo'lsa ham xabar **ketib qoladi**.

## 2. Yechim — transactional outbox

```
Service tranzaksiyasi:  biznes o'zgarishi + outbox_events qatori  ──COMMIT──▶ (ikkalasi ham bor yoki ikkalasi ham yo'q)
outbox_worker:          outbox_events ──▶ har subscriber uchun arq vazifasi ──▶ published_at
task_worker:            subscriber o'z tranzaksiyasida: consumer_receipts + o'z o'zgarishi ──COMMIT
```

Uch xil narsani adashtirmang:
1. **Domen event** — sodir bo'lgan biznes fakt (`commerce.order.confirmed`). O'zgarmas, versiyalangan.
2. **Outbox qatori** — shu faktni tarqatish niyati. Qayta yuborilishi mumkin.
3. **Vazifa (arq job)** — bajariladigan ish (subscriber chaqiruvi, Telegram'ga yuborish). Retry va timeout'i bor (`06`).

Tashqi webhook (Telegram, Meta) — avval `messaging` da tekshiriladi va saqlanadi; u domen event emas, toki normallashtirilmaguncha (`13`).

**Kafolat:** at-least-once. Event bir necha marta yetib kelishi mumkin — har consumer idempotent. Tashqi effektlar (Telegram xabari) uchun exactly-once va'da qilinmaydi.

---

## 3. Event envelope (K-08)

```json
{
  "event_id": "0192f3c1-...",
  "event_type": "commerce.order.confirmed",
  "schema_version": 1,
  "shop_id": "0192a0b2-...",
  "aggregate_type": "commerce.order",
  "aggregate_id": "0192f3b0-...",
  "aggregate_version": 4,
  "occurred_at": "2026-10-22T09:00:00Z",
  "actor": {"kind": "STAFF", "id": "0192..."},
  "traceparent": "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01",
  "correlation_id": "req_01J...",
  "causation_id": "0192f3a9-...",
  "payload": {"order_id": "0192f3b0-...", "branch_id": "0192...", "line_count": 2, "total": {"amount_minor": 980000000, "currency": "UZS"}}
}
```

| Maydon | Qoida |
|---|---|
| `event_id` | UUIDv7; dedup kaliti |
| `event_type` | `<domain>.<entity>.<action>` o'tgan zamonda; versiya nomda emas, `schema_version` da |
| `shop_id` | Majburiy (platforma darajasidagi kam holatlardan tashqari); consumer shu bilan `set_config('app.shop_id')` qiladi |
| `aggregate_version` | Agregatning versiyasi — tartib uchun |
| `actor.kind` | `STAFF`, `AI`, `SYSTEM`, `CUSTOMER`, `PLATFORM_ADMIN` |
| `traceparent` | W3C; trace HTTP → outbox → arq → Telegram bo'ylab davom etadi |
| `correlation_id` | Dastlabki so'rov (`X-Request-ID`) |
| `causation_id` | Shu event'ni keltirib chiqargan event yoki buyruq ID'si |

Python modeli — `app/shared/events/envelope.py`. Payload modellari: boshqa domen tinglaydiganlar — `app/shared/contracts/events/<domain>.py`; faqat ichki ishlatiladiganlar — domenning `events.py`.

### 3.1 Payload qoidalari

- Faqat **ID va minimal fakt**. Xaridor ismi, telefoni, manzili, chat matni, token, fayl — YO'Q.
- Pul — `{"amount_minor", "currency"}` (ADR-025) yoki tekis `<nom>_minor` + `currency` (buyurtma event'larida `total_minor`, `currency` — `reporting` talabi).
- Qoldiq kabi o'zgaruvchan qiymat — **absolyut holat** (`available_after: 3`), delta emas; consumer qayta kelganda ikki marta qo'shmaydi.
- Kerakli boshqa ma'lumot — consumer Query Port orqali o'qiydi.
- `schema_version` oshganda: yangi maydon qo'shish — moslashuvchan (eski consumer e'tiborsiz qoldiradi); maydon olib tashlash yoki ma'nosini o'zgartirish — yangi versiya, ikkalasi bir muddat parallel chiqariladi.

---

## 4. Outbox jadvali

Har domen schemasida o'z jadvali (ADR-035) — event biznes o'zgarishi bilan **bitta schema ichida, bitta tranzaksiyada** yoziladi.

```sql
CREATE TABLE commerce.outbox_events (
    event_id         UUID PRIMARY KEY,
    event_type       TEXT NOT NULL,
    shop_id          UUID,
    aggregate_type   TEXT NOT NULL,
    aggregate_id     UUID NOT NULL,
    aggregate_version BIGINT NOT NULL,
    envelope         JSONB NOT NULL,
    status           TEXT NOT NULL DEFAULT 'PENDING',   -- PENDING | PUBLISHED | DEAD
    attempts         INT  NOT NULL DEFAULT 0,
    next_attempt_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_error       TEXT,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    published_at     TIMESTAMPTZ
);
CREATE INDEX outbox_due ON commerce.outbox_events (next_attempt_at) WHERE status = 'PENDING';
```

`platform` schemasida ham bor (`platform.shop.activated`, `platform.notification.customer_delivery_requested`). Yozish — `write_outbox(db, event)` (`app/shared/events/outbox.py`).

`PUBLISHED` qatorlar 7 kundan keyin o'chiriladi (`06` tozalash ishi); `DEAD` qatorlar qo'lda ko'rilmaguncha qoladi.

---

## 5. `outbox_worker` algoritmi

```
loop (har 200 ms yoki LISTEN outbox_new orqali uyg'onadi):
  har schema uchun (platform, catalog, commerce, messaging, sales_ai, storefront, support, reporting):
    BEGIN
      SELECT ... FROM <schema>.outbox_events
       WHERE status='PENDING' AND next_attempt_at <= now()
       ORDER BY created_at
       LIMIT 100
       FOR UPDATE SKIP LOCKED
      har qator uchun:
        subscribers = registry.for(event_type)
        har subscriber uchun:
            arq.enqueue_job("dispatch_event", event_id, schema, subscriber.name,
                            _job_id=f"{event_id}:{subscriber.name}")      # Redis bir xil job_id ni qayta qo'ymaydi
        UPDATE status='PUBLISHED', published_at=now()
      Redis xatosi bo'lsa:
        attempts += 1, next_attempt_at = now() + min(2^attempts s, 5 min), last_error
    COMMIT
```

- 1–2 nusxa ishlaydi; `SKIP LOCKED` tufayli bir qatorni ikkitasi olmaydi.
- `LISTEN/NOTIFY` faqat uyg'otish uchun, ishonchlilik uchun emas — poll baribir ishlaydi.
- Subscriber'i yo'q event ham `PUBLISHED` bo'ladi (kelajakdagi consumer uchun tarix — 7 kun).
- **Redis ishlamasa:** qatorlar `PENDING` qoladi va qayta urinadi; hech qachon Redis sabab `DEAD` bo'lmaydi. `DEAD` — faqat dasturiy xato (noma'lum `event_type`, envelope buzilgan). Alert: eng eski `PENDING` yoshi > 120 s (`09`).
- **Rekonsilyatsiya** (Redis ma'lumoti yo'qolsa): `published_at` 10 daqiqadan eski, lekin kutilgan subscriber uchun `consumer_receipts` yozuvi yo'q event'lar qayta navbatga qo'yiladi (`06` §5).

### 5.1 Inline subscriber (istisno)

Juda arzon va faqat o'z schemasiga tegadigan subscriber (`storefront` kesh invalidatsiyasi) `inline=True` bilan e'lon qilinishi mumkin — `outbox_worker` uni arq'siz, alohida tranzaksiyada chaqiradi. Xato bo'lsa — oddiy arq vazifasiga tushadi. Tashqi chaqiruvli subscriber hech qachon inline emas.

---

## 6. Subscriber qoidalari

```python
# app/domains/commerce/subscribers.py
@subscribe("sales_ai.order_draft.requested", consumer="commerce.create_order_draft")
async def on_order_draft_requested(envelope: EventEnvelope, db: AsyncSession) -> None:
    payload = OrderDraftRequestedV1.model_validate(envelope.payload)   # app/shared/contracts/events/sales_ai.py
    await order_service.create_draft_from_ai(payload, envelope, db)
```

`dispatch_event` vazifasi (task_worker) har subscriber atrofida:

```
BEGIN
  set_config('app.shop_id', envelope.shop_id, true)
  INSERT INTO <consumer_schema>.consumer_receipts (consumer, event_id) ... ON CONFLICT DO NOTHING
  agar qator qo'shilmagan bo'lsa → allaqachon bajarilgan → COMMIT, chiqish
  subscriber(envelope, db)                 # o'z domenidagi o'zgarishlar + o'z outbox'i
COMMIT
```

```sql
CREATE TABLE commerce.consumer_receipts (
    consumer   TEXT NOT NULL,          -- 'commerce.on_order_draft_requested'
    event_id   UUID NOT NULL,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (consumer, event_id)
);
```

Qoidalar:
1. **Idempotent** — `consumer_receipts` dedup + biznes darajasida tabiiy kalit (masalan, `orders.source_event_id UNIQUE`).
2. **Ruxsat va holatni qayta o'qiydi** — envelope'dagi ma'lumotga ko'r-ko'rona ishonmaydi (shop to'xtatilgan bo'lishi, xodim o'chirilgan bo'lishi mumkin).
3. **Tranzaksiya ichida tashqi chaqiruv yo'q.** Tashqi ish kerak bo'lsa — o'z outbox'iga yangi event yoki vazifa niyatini yozadi.
4. **Tartib:** tartib muhim bo'lgan proyeksiyalar `last_applied_version` saqlaydi; kichik versiyani e'tiborsiz qoldiradi. Iloji bo'lsa — event'dagi deltaga emas, manbadan absolyut holatni o'qiydi.
5. **Xato turlari:** vaqtinchalik (DB lock, timeout) → retry; doimiy (validatsiya, noma'lum versiya) → darhol dead-letter.
6. Subscriber nomi (`consumer=`) — o'zgarmas; o'zgartirilsa dedup buziladi.

---

## 7. Dead-letter va qayta yuborish

- `dispatch_event` retry siyosati: 8 urinish, eksponensial (2 s → ~4 daqiqa) + jitter (`06`).
- Tugagach: `platform.dead_letters` ga yozuv — `event_id`, `event_type`, `consumer_name`, `shop_id`, `attempts`, `last_error` (PII'siz), `first_failed_at`. Sentry'ga `error`, alert (`09`).
- Platforma paneli: ro'yxat, sabab, **qayta yuborish** (`POST /api/v1/platform/dead-letters/{id}/replay`) — ruxsat `platform.dead_letter.replay`, audit yozuvi, asl `causation_id` saqlanadi.
- Qayta yuborish idempotent: `consumer_receipts` tufayli bajarilgan ish takrorlanmaydi.
- Butun proyeksiyani qayta qurish (`reporting`) — event tarixidan emas, manba jadvallardan (Query Port yoki eksport) qilinadi; buyurtma va qoldiq hech qachon event oqimidan tiklanmaydi.

---

## 8. Stage 1 event katalogi (kanonik)

**Yagona ro'yxat.** Yangi event — avval shu jadvalga, keyin domen `events.py` va `shared/contracts/events/` ga. "Consumer'lar" — boshqa domenlar (domen ichidagi reaksiyalar event'siz, to'g'ridan-to'g'ri).

Bildirishnomalar (xaridor va xodimga) event consumer'i emas: domen o'z service'ida `platform.notifications.request(...)` chaqiradi (`01` §3, `20`). Audit ham shunday.

### 8.1 `catalog`

| Event | Qachon | Payload | Consumer'lar | Idempotency |
|---|---|---|---|---|
| `catalog.product.published` | FSM-02 → `PUBLISHED` | `product_id`, `sku_ids[]`, `product_version` | storefront (kesh), reporting | `product_version` |
| `catalog.product.hidden` | → `HIDDEN` | `product_id`, `product_version` | storefront, reporting | `product_version` |
| `catalog.product.archived` | → `ARCHIVED` | `product_id`, `product_version` | storefront, reporting | `product_version` |
| `catalog.price.changed` | yangi narx versiyasi | `sku_id`, `price_version`, `price` (Money), `currency_source` (`UZS`/`USD`) | storefront, reporting | yuqori `price_version` g'olib |
| `catalog.exchange_rate.updated` | shop kursi yangilandi | `rate_id`, `base`, `quote`, `rate_micro`, `effective_at`, `source` | storefront (kesh), reporting | `rate_id` |
| `catalog.import.completed` | import tugadi; qoldiq ustunlari `catalog.import_stock_rows` ga bosqichlab yozilgan | `import_id`, `created`, `updated`, `failed`, `status`, `has_stock_rows` | commerce (qoldiq qatorlarini `CatalogQueryPort.get_import_stock_rows()` bilan o'qib, `RECEIPT`/`ADJUSTMENT` idempotent qo'llaydi), storefront (to'liq kesh tozalash), reporting | `import_id` |
| `catalog.pc_ruleset.activated` | PC moslik qoidalarining yangi versiyasi faollashdi (`pc-2026-10-v1` …) | `ruleset_id`, `version` | sales_ai (keshlangan tekshiruv natijalarini bekor qiladi), commerce (yangi takliflar shu versiya bilan) | `ruleset_id` |
| `catalog.hardware_spec.updated` | texnik ma'lumotlar kutubxonasidagi model yangilandi yoki SKU qayta bog'landi | `spec_id`, `spec_version`, `sku_ids[]` | sales_ai, storefront (kesh), reporting | `spec_id`+`spec_version` |

### 8.2 `commerce`

| Event | Qachon | Payload | Consumer'lar | Idempotency |
|---|---|---|---|---|
| `commerce.stock.changed` | `on_hand`/`reserved`/`allocated` o'zgardi (kirim, tuzatish, band, sotuv) | `sku_id`, `branch_id`, `on_hand`, `reserved`, `allocated`, `available`, `stock_version`, `reason` | storefront (kesh), reporting | absolyut qiymat, `stock_version` |
| `commerce.quick_sale.recorded` | do'kondagi tez sotuv (DEC-123) | `sale_id`, `sku_id`, `branch_id`, `qty`, `price` (Money) | reporting | `sale_id` |
| `commerce.reservation.created` | `CONFIRM` ichida | `reservation_id`, `order_id`, `lines[]` (sku, branch, qty) | reporting | `reservation_id` |
| `commerce.reservation.released` | `CANCEL` ichida | `reservation_id`, `order_id` | reporting | `reservation_id` |
| `commerce.reservation.expired` | menejer `EXPIRE` | `reservation_id`, `order_id` | reporting | `reservation_id` |
| `commerce.lead.created` | yangi lead | `lead_id`, `conversation_id?`, `source` | messaging (suhbatga bog'lash), reporting | `lead_id` |
| `commerce.lead.status_changed` | FSM-05 o'tishi | `lead_id`, `from`, `to`, `lost_reason?` | reporting | `lead_id` + `aggregate_version` |
| `commerce.quote.drafted` | taklif qoralamasi (AI yoki xodim) | `quote_id`, `revision`, `lead_id?`, `conversation_id?`, `compatibility` (`PASS`/`REVIEW_REQUIRED`/`BLOCK`) | sales_ai (suhbat konteksti), reporting | `quote_id`+`revision` |
| `commerce.quote.approval_requested` | → `REVIEW` | `quote_id`, `revision`, `compatibility` | reporting | `quote_id`+`revision` |
| `commerce.quote.approved` | → `APPROVED` | `quote_id`, `revision`, `total` (Money), `expires_at` | reporting | `quote_id`+`revision` |
| `commerce.quote.sent` | → `SENT` | `quote_id`, `revision`, `conversation_id?`, `public_token_id` | messaging (havolani suhbatga), reporting | `quote_id`+`revision` |
| `commerce.quote.expired` | → `EXPIRED` | `quote_id`, `revision` | sales_ai, reporting | `quote_id`+`revision` |
| `commerce.order.drafted` | `DRAFT` yaratildi (AI, sayt, xodim) | `order_id`, `total_minor`, `currency`, `source` (`AI`/`STOREFRONT`/`STAFF`), `channel?`, `branch_id`, `assigned_staff_id?`, `conversation_id?` | messaging (suhbatni buyurtmaga bog'lash), reporting | `order_id` |
| `commerce.order.submitted` | → `PENDING_CONFIRMATION` | `order_id`, `total_minor`, `currency`, `source` (`AI`/`STOREFRONT`/`STAFF`), `channel?`, `branch_id`, `assigned_staff_id?` | reporting | `order_id`+`aggregate_version` |
| `commerce.order.confirmed` | → `CONFIRMED` (band qilish bilan bitta TX) | `order_id`, `reservation_id`, `total_minor`, `currency`, `source` (`AI`/`STOREFRONT`/`STAFF`), `channel?`, `branch_id`, `assigned_staff_id?`, `fulfillment_method` | reporting | `order_id`+`aggregate_version` |
| `commerce.order.processing` | → `PROCESSING` | `order_id`, `total_minor`, `currency`, `source` (`AI`/`STOREFRONT`/`STAFF`), `channel?`, `branch_id`, `assigned_staff_id?` | reporting | `order_id`+`aggregate_version` |
| `commerce.order.ready` | `MARK_READY` (holat o'zgarmaydi, `ready_at`) | `order_id`, `ready_at`, `total_minor`, `currency`, `source` (`AI`/`STOREFRONT`/`STAFF`), `channel?`, `branch_id`, `assigned_staff_id?` | reporting | `order_id`+`ready_at` |
| `commerce.order.completed` | → `COMPLETED` (qoldiq kamaydi) | `order_id`, `total_minor`, `currency`, `source` (`AI`/`STOREFRONT`/`STAFF`), `channel?`, `branch_id`, `assigned_staff_id?`, `lines[]` (`sku_id`, `qty`, `unit_price_minor`), `lead_id?` | reporting, support (kafolat sanasi uchun konteks) | `order_id` |
| `commerce.order.cancelled` | → `CANCELLED` | `order_id`, `total_minor`, `currency`, `source` (`AI`/`STOREFRONT`/`STAFF`), `channel?`, `branch_id`, `assigned_staff_id?`, `reason_code`, `from_status` | reporting | `order_id` |
| `commerce.order.exception` | → `EXCEPTION` | `order_id`, `total_minor`, `currency`, `source` (`AI`/`STOREFRONT`/`STAFF`), `channel?`, `branch_id`, `assigned_staff_id?`, `reason_code` | reporting | `order_id`+`aggregate_version` |
| `commerce.import_stock.applied` | `catalog.import.completed` dan keyin import qoldiq qatorlari qo'llandi | `import_id`, `applied_rows`, `skipped_rows`, `branch_id` | catalog (import holati), reporting | `import_id` |
| `commerce.order.paid_marked` | `MARK_PAID` (DEC-100a, tekshirilmagan) | `order_id`, `total_minor`, `currency`, `source` (`AI`/`STOREFRONT`/`STAFF`), `channel?`, `branch_id`, `assigned_staff_id?`, `marked_by`, `amount_minor?` | reporting | `order_id` |

`commerce.order.ready` — holat emas, amal (`business/05`: "olib ketishga tayyor" holatni o'zgartirmaydi). Nom saqlandi.

### 8.3 `messaging`

| Event | Qachon | Payload | Consumer'lar | Idempotency |
|---|---|---|---|---|
| `messaging.message.received` | xaridor xabari saqlandi (dedup'dan keyin) | `conversation_id`, `message_id`, `channel` (`TELEGRAM`/`INSTAGRAM`/`WEBCHAT`), `speaker_mode`, `speaker_version`, `has_media` | sales_ai (agar `speaker_mode=AI`), reporting | `message_id` |
| `messaging.message.sent` | kanal yuborishni tasdiqladi | `conversation_id`, `message_id`, `author` (`AI`/`STAFF`/`NOTIFICATION`), `author_staff_id?`, `is_automated_greeting`, `notification_id?` | platform.notifications (FSM-12 → `SENT`), reporting | `message_id` |
| `messaging.message.failed` | yuborish yakuniy muvaffaqiyatsiz | `conversation_id`, `message_id`, `error_code`, `notification_id?` | platform.notifications (→ `FAILED`), reporting | `message_id` |
| `messaging.conversation.handed_off` | → `HUMAN_ACTIVE` (`TAKE_OVER`) | `conversation_id`, `speaker_version`, `operator_id` | sales_ai (kutilayotgan ishni bekor qilish), reporting | `conversation_id`+`speaker_version` |
| `messaging.conversation.returned_to_ai` | `RETURN_TO_AI` | `conversation_id`, `speaker_version` | sales_ai, reporting | `conversation_id`+`speaker_version` |
| `messaging.channel.connected` | FSM-03 → `CONNECTED` | `channel_id`, `channel_type` | sales_ai (agent kanalni biladi), reporting | `channel_id`+`aggregate_version` |
| `messaging.channel.disconnected` | → `DISCONNECTED` | `channel_id`, `channel_type`, `reason` | sales_ai, reporting | `channel_id`+`aggregate_version` |

Xabar matni payload'da yo'q — sales_ai `MessagingQueryPort.get_conversation_context()` bilan o'qiydi (redaction bilan, `14`).

### 8.4 `sales_ai`

| Event | Qachon | Payload | Consumer'lar | Idempotency |
|---|---|---|---|---|
| `sales_ai.reply.ready` | AI javobi tayyor va tekshirildi | `conversation_id`, `reply_id`, `speaker_version` (javob tayyorlangan paytdagi), `mode` (`AUTO`/`SUGGEST`) | messaging (`AUTO`: versiya mos bo'lsa yuboradi, aks holda tashlaydi — TC-009; `SUGGEST`: operatorga taklif sifatida ko'rsatadi) | `reply_id` |
| `sales_ai.reply.validation_failed` | AI javobi tekshiruvdan o'tmadi (narx/qoldiq katalogga mos emas, taqiqlangan da'vo — TC-007) | `conversation_id`, `reply_id`, `speaker_version`, `failure_codes[]` | messaging (javob yuborilmaydi; `REQUEST_HUMAN`), reporting | `reply_id` |
| `sales_ai.quote_approval.requested` | AI tuzgan taklifni menejer tasdig'iga yuborishni so'radi (tool `commerce.request_quote_approval`) | `request_id`, `quote_id`, `revision`, `conversation_id` | commerce (`SUBMIT_FOR_REVIEW`) | `request_id` |
| `sales_ai.handoff.requested` | AI operator chaqirdi | `conversation_id`, `speaker_version`, `reason_code` | messaging (`REQUEST_HUMAN`, operatorga vazifa) | `conversation_id`+`speaker_version`+`reason_code` |
| `sales_ai.order_draft.requested` | xaridor "olaman" (BL-110) | `request_id`, `conversation_id`, `contact_ref_id`, `lines[]` (sku_id, qty), `quote_id?`, `fulfillment_method?` | commerce (`DRAFT` yaratadi) | `request_id` → `orders.source_request_id UNIQUE` |
| `sales_ai.quote_draft.requested` | AI PC yig'ma tuzdi | `request_id`, `conversation_id`, `lead_id?`, `lines[]`, `compatibility_check_id` | commerce (taklif qoralamasi) | `request_id` |
| `sales_ai.lead_capture.requested` | AI ehtiyojni aniqladi | `request_id`, `conversation_id`, `budget?` (Money), `purpose_code?`, `lost_reason_hint?` | commerce (lead yaratish yoki `QUALIFY`) | `request_id` |

`reply_id` = `sales_ai.ai_turns.id`; javob matni event'da emas. messaging yuborishdan oldin uni `SalesAiQueryPort.get_reply(reply_id)` orqali oladi (`01` §3, `14` §3). `contact_ref_id` — xaridor kontaktiga havola; `commerce` uni `SalesAiQueryPort.resolve_contact_ref()` orqali bir marta o'qiydi (`14` §7).

### 8.5 `support`

| Event | Qachon | Payload | Consumer'lar | Idempotency |
|---|---|---|---|---|
| `support.case.opened` | FSM-11 `NEW` | `case_id`, `order_id`, `sku_id` | reporting | `case_id` |
| `support.case.status_changed` | FSM-11 o'tishi | `case_id`, `from`, `to`, `sku_id`, `branch_id?` | commerce (→ `IN_SERVICE` bo'lsa `quarantine_qty +1`, ledger `RETURN_QUARANTINE` — sotilmaydi, BR-X11), reporting | `case_id`+`aggregate_version` |
| `support.case.resolved` | → `RESOLVED` | `case_id`, `outcome` (`REPAIRED`/`REPLACED`/`RETURNED`), `sku_id`, `branch_id?` | commerce (tekshiruvdagi mahsulot bo'yicha omborchiga qaror vazifasi), reporting | `case_id` |

### 8.6 `platform`

| Event | Qachon | Payload | Consumer'lar | Idempotency |
|---|---|---|---|---|
| `platform.shop.activated` | FSM-01 → `ACTIVE` | `shop_id`, `slug` | storefront (sayt yoqiladi), sales_ai (agent yoqiladi), reporting | `shop_id`+`aggregate_version` |
| `platform.shop.suspended` | → `SUSPENDED` | `shop_id`, `reason_code` | storefront (yangi buyurtma yopiladi), sales_ai (agent o'chadi), messaging (avtomatik javob to'xtaydi) | `shop_id`+`aggregate_version` |
| `platform.staff.access_revoked` | a'zolik `DISABLED` yoki rol olib tashlandi | `principal_id`, `revoked_roles[]` | messaging (suhbatlarni qayta taqsimlash), commerce (buyurtmalar uchun qayta biriktirish vazifasi) | `principal_id`+`aggregate_version` |
| `platform.shop.policy_changed` | Shop sozlamalari (`shop_policies`) o'zgardi | `changed_fields[]` (masalan `stock_display`, `quote_ttl_hours`), `version` | storefront (`stock_display` → `public_products` qayta hisoblanadi, kesh tozalanadi), sales_ai (siyosat keshini yangilaydi), commerce (muddatlar) | `shop_id`+`version` |
| `platform.ai_quota.exhausted` | AI limiti tugadi (DEC-119) | `period`, `limit`, `used` | sales_ai (rejim `OFF`, yangi xabarlar operatorga) | `period` |
| `platform.notification.customer_delivery_requested` | xaridorga kanal orqali xabar kerak (FSM-12 `SCHEDULED`) | `notification_id`, `conversation_id`, `template_key`, `locale`, `rendered_ref` | messaging (shop kanali orqali yuboradi) | `notification_id` |
| `platform.privacy.export_requested` | xaridor ma'lumotlarini eksport so'rovi (`26`) | `request_id`, `subject_ref` (hash), `deadline_at` | commerce, messaging, support, sales_ai, reporting (o'z qismini tayyorlaydi) | `request_id`+consumer |
| `platform.privacy.erasure_requested` | xaridor ma'lumotini o'chirish/anonimlashtirish | `request_id`, `subject_ref`, `deadline_at` | commerce, messaging, support, sales_ai, reporting | `request_id`+consumer |
| `platform.privacy.shop_export_requested` | pilot tugadi / shop yopilmoqda — butun shop eksporti | `request_id`, `deadline_at` | barcha domenlar | `request_id`+consumer |
| `platform.privacy.shop_purge_requested` | eksportdan keyin shop ma'lumotini o'chirish (FSM-01 `CLOSED`) | `request_id`, `confirmed_by`, `not_before` | barcha domenlar | `request_id`+consumer |

Privacy event'lari — yangi `platform/privacy` moduli (`26`). Har domen consumer'i o'z qismini bajargach natijani `platform.privacy` service'iga yozadi (domen platform'ni to'g'ridan-to'g'ri chaqira oladi) — so'rov barcha domenlar tugatgandagina yopiladi. Batafsil `26`.

`platform.notification.customer_delivery_requested` seed ro'yxatda yo'q edi: platform shop kanal adapterlarini import qila olmaydi (adapterlar `messaging` da), shuning uchun xaridorga Telegram/Instagram orqali xabar faqat shu event bilan yetkaziladi. Xodimlarga ichki bildirishnoma (in-app, platformaning o'z Telegram boti) — `platform/notifications` ichida, event'siz.

### 8.7 Keyinga qoldirilgan

`payments.*` (DEC-100), `fulfillment.*` (DEC-113). Stage 2: `network.public_offer.published`, `network.public_offer.updated`, `network.public_offer.withdrawn`, `network.canonical_match.changed`, `network.pos_stock.received`. Stage 3: `marketplace.referral.consented`. Payload va consumer'lar domenlar qo'shilganda shu katalogga yoziladi (`28`).

### 8.8 `storefront`

| Event | Qachon | Payload | Consumer'lar | Idempotency |
|---|---|---|---|---|
| `storefront.site.updated` | Sayt sozlamalari o'zgardi (logo, kontaktlar, mavzu) | `site_id`, `version` | storefront (o'z keshini tozalaydi, `08` §4) | `site_id`+`version` |

`storefront.public_products` proyeksiyasi `catalog.product.*`, `catalog.price.changed`, `catalog.exchange_rate.updated` va `commerce.stock.changed` event'laridan quriladi (`07` §4.7).

### 8.9 Query Port'lar — domenlararo o'qish (to'liq ro'yxat)

Interfeys va DTO — `app/shared/contracts/<domain>.py`, implementatsiya — egasi domenda, ulanish — `app/dependencies.py` (ADR-032). Faqat o'qish.

| Port | Metod | Kim ishlatadi |
|---|---|---|
| `CatalogQueryPort` | `search`, `get_product`, `get_active_price` | sales_ai (tool'lar), commerce (buyurtma tasdiqlashda joriy narx, `12` §5.1) |
| | `check_compatibility`, `suggest_builds` | sales_ai, commerce (taklif) |
| | `get_import_stock_rows` | commerce (import qoldig'ini qo'llash, `18`) |
| | `get_public_projection`, `list_reference_specs` | storefront (proyeksiyani qayta qurish), reporting |
| `CommerceQueryPort` | `get_availability`, `get_stock_levels` | sales_ai, catalog (PC tavsiyasi), storefront (proyeksiyani qayta qurish) |
| | `get_order_status` | sales_ai (`commerce.lookup_order_status`) |
| | `get_order_for_support(order_id)` | support — buyurtma shu shopga tegishli va `COMPLETED` ekanini tekshirish, qatorlar va `warranty_snapshot` (kafolat shartlari, muddati) manbai (BL-057) |
| | `get_import_stock_results`, `list_orders_for_backfill` | catalog (import holati), reporting (read model'ni qayta qurish) |
| `MessagingQueryPort` | `get_conversation_context`, `list_conversations_for_backfill` | sales_ai, reporting |
| `SalesAiQueryPort` | `get_reply(reply_id)` | messaging — AI javob matni (`ai_turns`), event'da matn yo'q |
| | `resolve_contact_ref(contact_ref_id)` | commerce — xaridor kontakti (`14` §7) |
| `NetworkQueryPort` | (Stage 2) | marketplace (`28`) |

---

## 9. Event oqimi — asosiy zanjirlar

```
Xaridor yozdi:
  messaging.message.received ──▶ sales_ai ──▶ (LLM, Query Port'lar) ──▶ sales_ai.reply.ready ──▶ messaging ──▶ Telegram
                                                                     └─▶ messaging.message.sent ──▶ reporting

"Olaman":
  sales_ai.order_draft.requested ──▶ commerce: DRAFT ──▶ commerce.order.drafted ──▶ messaging (suhbatga bog'laydi)
  sales_ai.handoff.requested     ──▶ messaging: HUMAN_NEEDED, operatorga vazifa

Operator tasdiqladi (sinxron, commerce ichida):
  commerce.order.confirmed + commerce.reservation.created + commerce.stock.changed ──▶ storefront, reporting
  + platform.notifications.request("order.confirmed") ──▶ platform.notification.customer_delivery_requested ──▶ messaging ──▶ xaridor
```

---

## 10. Kuzatuv

| Metrika | Ma'nosi | Alert |
|---|---|---|
| `cos_outbox_pending{schema}` | navbatdagi qatorlar | — |
| `cos_outbox_oldest_pending_seconds{schema}` | eng eski `PENDING` yoshi | > 120 s |
| `cos_outbox_dead_total{schema}` | dasturiy xato | > 0 |
| `cos_event_dispatch_total{event_type, consumer, result}` | ok / retry / dead | — |
| `cos_event_dispatch_lag_seconds` | `occurred_at` → consumer COMMIT | p99 > 2 s |
| `cos_dead_letters_open` | ochiq dead-letter'lar | > 0 |
| `cos_event_duplicate_total{consumer}` | dedup ishlagan holatlar | ko'payishi — tekshirish |

Har dispatch span'i `traceparent` bilan bog'lanadi: Grafana'da bitta trace'da webhook → AI → yuborish ko'rinadi (`09`).

## 11. Testlar

1. COMMIT'dan keyin, dispatch'dan oldin worker o'ldirildi → event baribir yetib keladi.
2. Consumer COMMIT'dan keyin, ACK'dan oldin o'ldi → qayta kelganda `consumer_receipts` tufayli o'zgarish takrorlanmaydi (TC-022).
3. Bir xil `sales_ai.order_draft.requested` 3 marta → bitta `DRAFT` (`source_request_id UNIQUE`).
4. Narx versiyalari tartibsiz keldi (10, keyin 8) → storefront'da 10 qoladi.
5. Redis 5 daqiqa o'chirildi → outbox `PENDING` to'planadi, Redis qaytgach hammasi yetib boradi; yo'qolgan arq vazifalari rekonsilyatsiya bilan tiklanadi.
6. Noma'lum `event_type` → `DEAD`, alert; boshqa event'lar to'xtamaydi.
7. Payload'da PII yo'qligi — `tests/architecture/test_event_payloads.py` (taqiqlangan maydon nomlari ro'yxati: `phone`, `name`, `address`, `text`, `token` …).

## 12. Ochiq savollar

Hozircha yo'q (`SalesAiQueryPort` va platform → domen event'i `01` §3 ga qo'shildi).

## Keyingi qadam

→ [06-background-jobs.md](06-background-jobs.md) — arq vazifalari, rejali ishlar va retry siyosati
