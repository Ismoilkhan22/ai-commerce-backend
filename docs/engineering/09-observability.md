# 09 — Kuzatuv (observability): loglar, tracing, metrikalar, alertlar

> **Versiya:** v2 (2026-10-22). Eski `12_OBSERVABILITY_AND_TRACING` va `04_SYSTEM_ARCHITECTURE_C4` §10 o'rnini bosadi.
> **Qarorlar:** DEC-012 B (Grafana Cloud + Sentry, 2026-10-22 da bismuth bilan solishtirilib qayta tasdiqlandi), ADR-017, ADR-029.
> **Kim o'qiydi:** backend, ops (pilotda — founder).

## 1. Muammo va yechim

**Muammo:** bitta xaridor xabari 5 ta jarayondan o'tadi: webhook (API) → outbox → `outbox_worker` → arq `task_worker` (AI) → Telegram. Biror joyda xato bo'lsa, "qayerda to'xtadi?" degan savolga loglarsiz javob yo'q. Ikkinchi xavf — loglarga xaridor telefoni, chat matni yoki token tushib qolishi.

**Yechim:**
1. **Bitta `trace_id`** HTTP'dan tashqi chaqiruvgacha (bismuth 11-qoida).
2. **structlog JSON** — har qatorda bir xil maydonlar, PII yo'q.
3. **OpenTelemetry** — span'lar va metrikalar; eksport **Grafana Cloud** ga (Tempo — trace, Mimir — metrika, Loki — log).
4. **Sentry** — exception'lar.
5. **Alertlar** — Grafana alerting → founder Telegram'i.

**Qoida:** kodda faqat OpenTelemetry API va structlog ishlatiladi. Grafana Cloud — faqat eksport manzili. Self-hosted'ga o'tish (DEC-012 A) — konfiguratsiya o'zgarishi, kod emas.

**Muhim:** telemetriya ≠ biznes audit. Audit (`platform/audit`) — append-only, DB'da, tranzaksiya ichida, huquqiy dalil. Log va trace — texnik diagnostika, muddati bilan o'chiriladi (§9).

---

## 2. Kontekst zanjiri (correlation)

```
Klient ──traceparent?──▶ API
   RequestContextMiddleware:
     request_id = X-Request-ID (format to'g'ri bo'lsa) yoki yangi UUIDv7
     trace_id   = traceparent'dan (W3C, validatsiya) yoki yangi
     contextvars: trace_id, request_id, shop_id, actor_id, surface, domain
   ──▶ service ──▶ DB (db.transaction span)
   ──▶ outbox_events: event_id, traceparent, correlation_id, causation_id saqlanadi
outbox_worker: yangi span + LINK (producer span'iga) ──▶ subscriber yoki arq.enqueue(job_id=event_id, traceparent)
task_worker: yangi span + LINK ──▶ LLM / Telegram / Meta span'lari
```

Qoidalar:
- Asinxron davomda **span link** ishlatiladi, soxta parent-child emas (vaqt oralig'i bor).
- `correlation_id` — bitta biznes oqim (masalan, bitta suhbatdagi bitta xaridor xabari); `causation_id` — shu event'ni keltirib chiqargan event.
- Worker `shop_id` ni payload'dan oladi, lekin ruxsat va holatni DB'dan qayta o'qiydi (`03` §5).
- Javobda `X-Request-ID` qaytariladi; xato envelope'ida `trace_id` (K-07) — support shu bilan qidiradi.
- `trace_id` — ishonch belgisi emas: klient yuborgan qiymat faqat format tekshiruvidan keyin qabul qilinadi.

---

## 3. Middleware zanjiri

`01` §5 dagi tartib, kuzatuv nuqtai nazaridan (birinchisi — eng tashqi):

| № | Middleware | Kuzatuv vazifasi |
|---|---|---|
| 1 | `RequestContextMiddleware` (`shared/tracing/middleware.py`) | `request_id`, `trace_id`, server span, contextvars |
| 2 | Access log | So'rov tugaganda bitta JSON qator (§4) |
| 3 | `I18nMiddleware` | `lang` contextvar |
| 4 | `ExceptionHandlingMiddleware` | `DomainError` → K-07; kutilmagan xato → 500 `INTERNAL_ERROR` + Sentry; ichki tafsilot javobga chiqmaydi |
| 5 | Rate limit (Redis) | `cos_api_rate_limited_total` |
| 6 | `SurfaceAuthMiddleware` | `actor_id`, `shop_id`, `surface` contextvars'ga (faqat server aniqlagan qiymat) |

Worker'larda xuddi shu contextvars task boshlanishida tiklanadi (`shared/tracing/context.py`).

---

## 4. Log sxemasi (structlog, JSON)

Har qatorda:

| Maydon | Misol | Izoh |
|---|---|---|
| `timestamp` | `2026-10-22T10:15:02.123Z` | UTC |
| `level` | `info` | §4.1 |
| `service` | `api` / `outbox-worker` / `task-worker` / `scheduler` | |
| `env`, `version` | `production`, `git-sha` | |
| `trace_id`, `span_id`, `request_id` | | |
| `correlation_id` | | async oqimlarda |
| `shop_id` | UUID | Ichki ID, PII emas. Loki label emas — faqat qidiruv maydoni |
| `actor_id` | UUID yoki `ai_agent` / `system` | Xodim ismi yoki telefoni emas |
| `domain` | `commerce` | `structlog.bind(domain=...)` |
| `event` | `order.confirmed` | Nima bo'ldi (qisqa kalit) |
| `route` yoki `job` | `/api/v1/shop/orders/{id}/confirm`, `ai_reply` | Route template, ID'siz |
| `outcome` | `ok` / `rejected` / `error` | |
| `error_code` | `INSUFFICIENT_AVAILABLE_STOCK` | K-07 katalogidan |
| `duration_ms` | `84` | |

```json
{"timestamp":"2026-10-22T10:15:02.123Z","level":"info","service":"api","env":"production",
 "trace_id":"4bf92f…","request_id":"0192…","shop_id":"0191…","actor_id":"0191…",
 "domain":"commerce","event":"order.confirm","route":"/api/v1/shop/orders/{order_id}/confirm",
 "outcome":"rejected","error_code":"INSUFFICIENT_AVAILABLE_STOCK","duration_ms":41}
```

### 4.1 Log darajalari
- `info` — biznes amallar, so'rovlar.
- `warning` — kutilgan rad etishlar (409, 422, 429), qayta urinishlar.
- `error` — 5xx, worker xatolari, dead-letter'ga tushish.
- `debug` — faqat `local`/`dev`.

### 4.2 Taqiqlangan (hech qachon logga yozilmaydi)
Xabar yoki chat matni, telefon, email, manzil, ism, karta, chek rasmi, signed URL, access/refresh token, bot token, Meta token, parol, prompt matni, LLM javob matni, audio, STT transkripti, xaridorning izohi. `shared/logging/filters.py` kalit nomlari va regex (telefon, email, token shakllari) bo'yicha maskalaydi — bu **ikkinchi qavat**; birinchi qavat — bunday narsani logga umuman uzatmaslik.

**Kirish logi va query string** (3-modul QA, 2026-10-26): qidiruv parametri xaridor telefonini olib kelishi mumkin (`GET /shop/orders?q=+998…`). Shuning uchun:
- uvicorn'ning o'z kirish logi o'chirilgan (`app/config/logging.py`; ishga tushirishda `--no-access-log` ham); uning o'rniga `RequestContextMiddleware` bitta `http.request` qatorini yozadi: metod, yo'l, holat, davomiylik va query parametrlarining **faqat nomlari** (`query_keys`), qiymatlarsiz;
- **proksi (nginx) va har qanday oldingi qatlam yo'lni query string'siz yozadi** (`$uri`, `$request_uri` emas); span'da `http.url` o'rniga route template.
- `path` maydonida haqiqiy yo'l emas, **route shabloni** yoziladi (`/api/v1/auth/invites/{token}/accept`, `/api/v1/shop/orders/{order_id}`): bir martalik havola tokeni va ID'lar logga tushmaydi (QA 2-tur N3). Route topilmagan so'rov (404) — yo'l bo'laklari niqoblanadi (`/api/v1/x/{seg}`). Ichma-ich router'larda (masalan `/api/v1/storefront/{slug}/…`) FastAPI route'ni middleware'ga bermaydi — u yerda ham niqoblash ishlaydi: shop slug'i (oddiy so'z) ko'rinadi, sayt buyurtmasi holat havolasi tokeni (43 belgi) doim `{seg}` (4-modul);
- SQLAlchemy engine'lari `hide_parameters=True` bilan: DB xatosi matnida (`IntegrityError` va h.k.) SQL parametrlari — telefon, ism — ko'rinmaydi, faqat "parameters hidden" (QA 2-tur N1).

---

## 5. Span'lar

| Span | Atributlar (faqat xavfsiz) | Xato holatlari |
|---|---|---|
| `http.server` | route template, status, surface | 429, 5xx |
| `db.transaction` | domain, davomiylik | lock timeout, deadlock |
| `use.transition` | entity_type, from, to, command | `INVALID_STATE_TRANSITION` |
| `commerce.inventory.reserve` | qatorlar soni | yetmadi, versiya to'qnashuvi |
| `commerce.order.confirm` | — | 409 xatolar |
| `webhook.verify` | provider, natija (bool) | soxta imzo, takror |
| `outbox.dispatch` | event_type, attempts, lag_ms | dead-letter |
| `arq.task` | task nomi, attempt, queue_age_ms | timeout, retry |
| `scheduler.job` | job nomi, leader (bool) | lock olinmadi |
| `ai.generate` | provider, model alias, input/output token soni | timeout, tool rad etildi |
| `ai.tool` | tool nomi, natija soni, outcome | ruxsat yo'q, eskirgan narx |
| `ai.validate_reply` | outcome, rad etish sababi | invented_price, unknown_sku |
| `catalog.compatibility.check` | ruleset versiyasi, natija (`PASS`/`REVIEW_REQUIRED`/`BLOCK`) | — |
| `channel.send` | provider, status class | 429, noaniq yetkazish |
| `storage.upload` | content type, hajm bucket | — |
| `reporting.metric.query` | metric key | ruxsat yo'q |

Span atributlarida §4.2 dagi narsalar yo'q. `shop_id` span atributi sifatida mumkin (Tempo'da qidirish uchun), lekin **metrika label'i emas** (§6.1).

---

## 6. Metrikalar

### 6.1 Nomlash va label qoidalari
- Muhim amal: `cos_<domain>_<entity>_<action>_total` (counter).
- Davomiylik: `cos_<domain>_<operation>_duration_seconds` (histogram).
- Holat: `cos_<area>_<name>` (gauge).
- **Label'larda yuqori kardinallik yo'q:** `shop_id`, `order_id`, `user_id`, `conversation_id` — TAQIQ. Ruxsat: `domain`, `route`, `status_class`, `provider`, `outcome`, `queue`, `job`, `plan_tier`, `error_code`.
- Shop bo'yicha xarajat va hajm — metrikada emas, `platform/billing` jadvalida (DB) va `19-reporting-metrics.md` hisobotlarida.

### 6.2 Stage 1 metrikalar ro'yxati

**API va DB**

| Metrika | Tur | Label'lar |
|---|---|---|
| `cos_api_requests_total` | counter | surface, route, status_class |
| `cos_api_request_duration_seconds` | histogram | surface, route, method |
| `cos_api_rate_limited_total` | counter | surface |
| `cos_db_transaction_duration_seconds` | histogram | domain |
| `cos_db_pool_in_use` | gauge | service |
| `cos_db_deadlocks_total` | counter | domain |

**Outbox, navbat, scheduler**

| Metrika | Tur | Label'lar |
|---|---|---|
| `cos_outbox_unpublished` | gauge | schema |
| `cos_outbox_oldest_age_seconds` | gauge | schema |
| `cos_outbox_dispatch_lag_seconds` | histogram | event_type |
| `cos_outbox_dead_total` | counter | event_type |
| `cos_arq_queue_depth` | gauge | queue |
| `cos_arq_oldest_job_age_seconds` | gauge | queue |
| `cos_arq_job_duration_seconds` | histogram | job |
| `cos_arq_job_retries_total` | counter | job, error_code |
| `cos_arq_job_failed_total` | counter | job |
| `cos_scheduler_job_lag_seconds` | histogram | job |
| `cos_scheduler_leader` | gauge (0/1) | instance |
| `cos_subscriber_duplicates_total` | counter | consumer |

**Kanallar (messaging)**

| Metrika | Tur | Label'lar |
|---|---|---|
| `cos_messaging_webhook_received_total` | counter | provider, outcome |
| `cos_messaging_webhook_duplicates_total` | counter | provider |
| `cos_messaging_webhook_invalid_signature_total` | counter | provider |
| `cos_messaging_webhook_ack_duration_seconds` | histogram | provider |
| `cos_messaging_message_sent_total` | counter | provider, outcome |
| `cos_messaging_send_failed_total` | counter | provider, error_code |
| `cos_messaging_channel_degraded` | gauge | provider |
| `cos_messaging_handoff_requested_total` | counter | reason |
| `cos_messaging_stale_ai_reply_dropped_total` | counter | — |

**AI (`sales_ai`, `platform/llm`)**

| Metrika | Tur | Label'lar |
|---|---|---|
| `cos_sales_ai_first_reply_duration_seconds` | histogram | channel |
| `cos_llm_request_duration_seconds` | histogram | provider, model_alias |
| `cos_llm_requests_total` | counter | provider, model_alias, outcome |
| `cos_llm_tokens_total` | counter | provider, model_alias, direction |
| `cos_llm_cost_minor_total` | counter | provider, plan_tier |
| `cos_sales_ai_tool_calls_total` | counter | tool, outcome |
| `cos_sales_ai_reply_rejected_total` | counter | reason (`invented_price`, `unknown_sku`, `forbidden_claim`, ...) |
| `cos_sales_ai_order_draft_requested_total` | counter | — |
| `cos_sales_ai_turns_total` | counter | outcome (`SENT_TO_MESSAGING`, `DISCARDED`, `HANDOFF`) |
| `cos_sales_ai_turn_duration_seconds` | histogram | mode |
| `cos_sales_ai_handoff_total` | counter | reason (AI o'zi operator chaqirgan holatlar) |
| `cos_billing_ai_quota_exhausted_total` | counter | plan_tier |

**Savdo va ombor (`commerce`, `catalog`)**

| Metrika | Tur | Label'lar |
|---|---|---|
| `cos_commerce_order_drafted_total` | counter | source (`ai`, `storefront`, `staff`) |
| `cos_commerce_order_confirmed_total` | counter | — |
| `cos_commerce_order_confirm_conflict_total` | counter | error_code (`INSUFFICIENT_AVAILABLE_STOCK`, `PRICE_CHANGED`, `VERSION_CONFLICT`) |
| `cos_commerce_order_completed_total` | counter | — |
| `cos_commerce_order_cancelled_total` | counter | reason |
| `cos_commerce_order_pending_confirmation_age_seconds` | gauge (eng eskisi) | — |
| `cos_commerce_order_confirm_duration_seconds` | histogram | — |
| `cos_commerce_stock_reserve_conflict_total` | counter | — |
| `cos_commerce_stock_negative_total` | counter | — (har qanday qiymat > 0 — alert) |
| `cos_commerce_stock_ledger_mismatch_total` | counter | — |
| `cos_commerce_quick_sale_total` | counter | — |
| `cos_commerce_quote_approved_total` | counter | — |
| `cos_catalog_compatibility_checked_total` | counter | result |
| `cos_catalog_import_rows_total` | counter | outcome |
| `cos_catalog_exchange_rate_age_seconds` | gauge | currency |

**Xavfsizlik va izolyatsiya**

| Metrika | Tur | Label'lar |
|---|---|---|
| `cos_security_auth_denied_total` | counter | surface, reason |
| `cos_security_permission_denied_total` | counter | permission |
| `cos_security_rls_violation_total` | counter | schema (har qanday > 0 — SEV-1) |
| `cos_security_cross_shop_access_attempt_total` | counter | domain |
| `cos_security_break_glass_active` | gauge | — |

**Hisobot va ovoz (S5)**

| Metrika | Tur | Label'lar |
|---|---|---|
| `cos_reporting_query_duration_seconds` | histogram | metric_key |
| `cos_reporting_unauthorized_metric_total` | counter | metric_key |
| `cos_reporting_voice_transcript_corrected_total` | counter | language |
| `cos_reporting_projection_lag_seconds` | gauge | projection |
| `cos_reporting_assistant_unmapped_total` | counter | — (registrga mos kelmagan savollar) |

`cos_security_rls_violation_total` — RLS policy rad etgan so'rov (PostgreSQL `insufficient_privilege` / `new row violates row-level security policy` xatosi `ExceptionHandlingMiddleware` da shu counter'ga tushadi). Normal ishda doim 0 — app-layer filtri birinchi qavat.

---

## 7. Alertlar

Raqamlar — boshlang'ich taxmin (`00` §4), pilotda kalibrlanadi. Alertlar Grafana alerting → founder Telegram'i; SEV-1 — qo'shimcha telefon qo'ng'irog'i (OnCall yoki shunga o'xshash). Runbook havolasi har alertda bor.

| Alert | Shart | Daraja | Runbook |
|---|---|---|---|
| Boshqa shop ma'lumoti | `cos_security_rls_violation_total` yoki `cos_security_cross_shop_access_attempt_total` o'sishi > 0 | SEV-1 | RB-05 |
| Stok minus / ledger mos emas | `cos_commerce_stock_negative_total` yoki `..._ledger_mismatch_total` > 0 | SEV-1 | RB-03 |
| AI noto'g'ri narx o'tib ketdi | Operator belgilagan `ai_wrong_fact` hodisasi (audit) > 0 | SEV-1 | RB-02 |
| API 5xx | 5xx ulushi > 2% 5 daqiqa | SEV-2 | RB-07 |
| API sekin | p95 (yozish) > 500 ms 10 daqiqa; p95 (o'qish) > 300 ms 10 daqiqa | SEV-3 | — |
| Outbox to'xtadi | `cos_outbox_oldest_age_seconds` > 120 s 10 daqiqa | SEV-2 | RB-06 |
| arq navbati | `cos_arq_oldest_job_age_seconds` > 120 s 10 daqiqa | SEV-2 | RB-12 |
| Dead-letter | `cos_outbox_dead_total` yoki `cos_arq_job_failed_total` o'sishi > 0 | SEV-3 (to'lov/buyurtma event'i bo'lsa SEV-2) | RB-13 |
| Scheduler | `sum(cos_scheduler_leader)` = 0 yoki > 1 5 daqiqa; `cos_scheduler_job_lag_seconds` p95 > 30 s | SEV-2 | RB-14 |
| Redis | `/health/ready` Redis xatosi 2 daqiqa | SEV-2 | RB-11 |
| Webhook ACK | p95 > 1 s 10 daqiqa | SEV-3 | RB-04 |
| Kanal uzildi | `cos_messaging_channel_degraded` = 1 | SEV-2 | RB-04 |
| LLM ishlamayapti | `cos_llm_requests_total{outcome="provider_error"}` ulushi > 20% 5 daqiqa | SEV-2 | RB-01 |
| AI javob sekin | `cos_sales_ai_first_reply_duration_seconds` p90 > 15 s 15 daqiqa | SEV-3 | RB-01 |
| AI xarajati | Kunlik `cos_llm_cost_minor_total` o'sishi o'tgan 7 kun o'rtachasidan 3× | SEV-3 | RB-01 |
| Kutayotgan buyurtma | `cos_commerce_order_pending_confirmation_age_seconds` > 24 soat | SEV-3 (shopga eslatma ketadi, DEC-104) | — |
| Kurs eskirgan | `cos_catalog_exchange_rate_age_seconds` > 3 kun | SEV-3 | — |
| Backup | Oxirgi muvaffaqiyatli backup > 26 soat oldin | SEV-2 | RB-08 |
| Break-glass | `cos_security_break_glass_active` = 1 4 soatdan ko'p | SEV-2 | RB-10 |

Alert ishlashi **sinalmaguncha "sozlangan" deyilmaydi**: staging'da har SEV-1/2 alert uchun sintetik signal yuborilib, Telegram'ga yetib kelgani tekshiriladi (`25` §6).

---

## 8. Dashboard'lar (Grafana Cloud)

| Dashboard | Panellar |
|---|---|
| **Umumiy holat** | API RPS, p95, 5xx; outbox va arq navbat yoshi; scheduler leader; Redis, DB holati |
| **Kanallar** | Webhook qabul/dublikat/soxta imzo; yuborish xatolari provider bo'yicha; degraded kanallar |
| **AI** | Birinchi javob vaqti, LLM latency, xato ulushi, token va xarajat (plan_tier bo'yicha), rad etilgan javoblar sababi, handoff sabablari |
| **Savdo** | Qoralama → tasdiq → topshirish; tasdiqlash to'qnashuvlari; kutayotgan buyurtma yoshi; tez sotuvlar |
| **Xavfsizlik** | Auth/permission rad etishlar, RLS buzilishi (0 bo'lishi kerak), break-glass |
| **Worker'lar** | Task davomiyligi, retry, failed; dead-letter soni |

---

## 9. Sentry, eksport va saqlash

- **Sentry:** API va worker'lardagi kutilmagan exception'lar; `DomainError` (kutilgan 4xx) yuborilmaydi. `before_send` hook'i request body, header'lar (`Authorization`, `Cookie`), query string'ni olib tashlaydi; `user` sifatida faqat `actor_id`. Release = git SHA.
- **Eksport:** OTel SDK → OTLP → Grafana Cloud (bevosita yoki yengil OTel Collector konteyneri orqali — collector redaction processor'i uchinchi qavat).
- **Ma'lumot joyi:** telemetriya xorijda (Grafana Cloud), shuning uchun PII yo'qligi qat'iy talab (DEC-012, DEC-013). Biznes ma'lumoti va audit — O'zbekistondagi DB'da.
- **Saqlash muddati (taklif):** log — 30 kun, trace — 14 kun, metrika — 13 oy (Grafana Cloud tarifiga bog'liq), Sentry — 30 kun. Audit — `26-privacy-and-retention.md` bo'yicha.

---

## 10. Biznes audit va texnik log farqi

| | Audit (`platform/audit`) | Log / trace |
|---|---|---|
| Maqsad | Kim nima o'zgartirdi — huquqiy va biznes dalil | Texnik diagnostika |
| Qayerda | PostgreSQL `audit` schemasi (UZ) | Grafana Cloud |
| Qachon yoziladi | O'zgarish bilan **bitta tranzaksiyada** | Asinxron, yo'qolishi mumkin |
| Kim ko'radi | Shop egasi (o'z shopini), platforma (break-glass) | Faqat platforma jamoasi |
| Shaxsiy ma'lumot | Kerakli minimum (masalan, eski va yangi narx) | Yo'q |
| Saqlash | Uzoq (`26`) | 14–30 kun |

Holat o'tishlari tarixi — `platform.transition_log` (ADR-034), uchinchi manba. Hodisani tekshirishda: avval audit va transition log (nima bo'ldi), keyin `trace_id` bo'yicha log va trace (qanday bo'ldi).

---

## 11. Qabul mezonlari

- [ ] Bitta Telegram xabari uchun webhook → outbox → AI → yuborish zanjiri Tempo'da bitta `trace_id` (link'lar bilan) ko'rinadi
- [ ] Log va trace snapshot'ida telefon, email, token, chat matni regex skanerida 0 ta topilma (CI testi, fixture bilan)
- [ ] Metrikalarda `shop_id` label yo'q (CI testi `/metrics` ni tekshiradi)
- [ ] Har SEV-1/2 alert staging'da sinab ko'rilgan
- [ ] Sentry'ga request body ketmasligi tekshirilgan

## Keyingi qadam

→ [10-security-tenancy-rbac.md](10-security-tenancy-rbac.md) — shop izolyatsiyasi va ruxsatlar
→ [25-operations-runbooks.md](25-operations-runbooks.md) — alertlarga javob
