# 06 — Fon vazifalari va rejali ishlar

> **Versiya:** v2 (2026-10-22). ADR-033 (DEC-003 D). Eski `09_EVENTS_OUTBOX_AND_JOBS` (jobs qismi) va `11_ASYNC_RUNTIME_ARCHITECTURE` o'rnini bosadi.
> **Kim o'qiydi:** backend, infra.

## 1. Muammo

Ko'p ish HTTP so'rov ichida qilinmasligi kerak:
- AI javobi 5–15 soniya oladi; Telegram webhook esa 1 soniyada javob kutadi.
- Telegram/Instagram'ga yuborish xato berishi, 429 qaytarishi mumkin — qayta urinish kerak.
- 5000 qatorli katalog importi daqiqalab ishlaydi.
- "24 soat tasdiqlanmagan buyurtma" eslatmasi hech kim so'rov yubormasa ham ishlashi kerak.

API 3 nusxada ishlasa, rejali ish 3 marta bajarilmasligi kerak. Server o'chsa, vazifa yo'qolmasligi kerak.

## 2. Yechim — uchta jarayon

```
┌────────────────┐  outbox_events   ┌──────────────────┐   arq (Redis db=1)   ┌──────────────────┐
│ API / service  │ ───────────────▶ │ outbox_worker    │ ───────────────────▶ │ task_worker ×2–3 │
│ (TX + outbox)  │                  │ (1–2 nusxa)      │                      │ tashqi chaqiruv, │
└────────────────┘                  └──────────────────┘                      │ subscriber'lar   │
                                                                              └──────────────────┘
┌──────────────────────────────┐            arq
│ scheduler_worker (APScheduler│ ─────────────────────────────▲
│ + advisory lock, bitta leader│   og'ir ishni o'zi qilmaydi
└──────────────────────────────┘
```

Hammasi bitta Docker image, boshqa buyruq bilan: `outbox-worker`, `task-worker`, `scheduler` (`22`).

**Asosiy qoida:** service hech qachon to'g'ridan-to'g'ri `arq.enqueue_job()` qilmaydi. Vazifa **faqat outbox orqali** navbatga tushadi — COMMIT va enqueue o'rtasida server o'chsa ham yo'qolmaydi (ADR-033). Istisno: scheduler (DB holatidan qayta tiklanadigan ishlar) va task ichidan keyingi task (o'zi idempotent bo'lsa).

---

## 3. `outbox_worker`

Algoritm — [05-events-and-outbox.md](05-events-and-outbox.md) §5. Qisqacha: `FOR UPDATE SKIP LOCKED` bilan 100 tadan oladi, har subscriber uchun `dispatch_event` vazifasini `_job_id=f"{event_id}:{consumer}"` bilan qo'yadi, `PUBLISHED` belgilaydi. Redis ishlamasa — eksponensial kutish, qatorlar `PENDING` qoladi.

Tashqi effektli niyatlar ham shu yo'l bilan: masalan `messaging` yuborish uchun `outbound_messages` qatorini va `messaging.outbound.queued` ichki event'ini yozadi → `channel_send` vazifasi.

---

## 4. `task_worker` (arq)

### 4.1 Navbatlar va izolyatsiya

Ikkita arq navbati (Redis **db1**; db0 — kesh va rate limit, db2 — pub/sub va WS ticket'lar, `08` §3):

| Navbat | Ishlar | `max_jobs` (har worker) | Nega |
|---|---|---|---|
| `default` (`arq:queue`) | `dispatch_event`, `channel_send`, `notification_send`, `ai_reply`, `voice_transcribe`, eslatmalar | 20 | Tez va muhim ishlar |
| `low` (`arq:queue:low`) | `catalog_import`, `report_export`, `media_process`, `audio_purge` | 2 | Og'ir ishlar tez ishlarni to'sib qo'ymasin |

`default` ichida turlar bo'yicha semaphore'lar: `ai_reply` ≤ 5 parallel (+ shop va global token limiti), `channel_send` ≤ 10 (+ shop-kanal throttle), `dispatch_event` uchun cheklov yo'q (qisqa). Shu tufayli buyurtma/qoldiq subscriber'lari AI kutib qolmaydi. Pilotda: 2 ta `task-worker` (`default`) + 1 ta `task-worker --queue low`.

### 4.2 Vazifalar ro'yxati

| Vazifa | Navbat | Kim qo'yadi | Idempotency kaliti | Retry | Timeout | Muvaffaqiyatsiz bo'lsa |
|---|---|---|---|---|---|---|
| `dispatch_event` | default | outbox_worker | `consumed_events (consumer, event_id)` | 8, eksp. 2 s → 4 daq + jitter | 30 s | dead-letter (`05` §7) |
| `ai_reply` | default | `messaging.message.received` subscriber (sales_ai) | `ai_reply:{conversation_id}:{message_id}` | 2 (faqat LLM 5xx/timeout) | 45 s | `sales_ai.handoff.requested` (sabab `AI_UNAVAILABLE`), xaridorga "operator javob beradi" |
| `channel_send` | default | messaging (`outbound_messages`) | `outbound_message_id` (provayderga idempotency kaliti bo'lsa — beriladi) | 5; 429 → `Retry-After`; 4xx (403 bloklangan) → yo'q | 15 s | `messaging.message.failed`, vazifa xodimga (TC-011, TC-032) |
| `notification_send` | default | platform.notifications (in-app, platforma boti) | `notification_id` | 5 (FSM-12) | 15 s | FSM-12 `FAILED`, xodimga vazifa |
| `catalog_import` | low | catalog (`imports`) | `import_id` + qator raqami (bo'laklab, davom ettiriladi) | 3, to'xtagan joyidan | 10 daq (bo'laklar 500 qator) | import `FAILED`, xatolar fayli (`18`) |
| `media_process` | low | catalog (rasm yuklandi) | `file_id` | 3 | 60 s | rasm "qayta ishlanmadi" |
| `report_export` | low | reporting | `export_id` | 3 | 5 daq | eksport `FAILED`, qayta urinish tugmasi |
| `voice_transcribe` (beta) | default | reporting.assistant | `audio_id` | 2 | 60 s | "matn bilan yozing" (`15`) |
| `audio_purge` | low | scheduler | `audio_id` | 3 | 30 s | alert (DEC-117) |

**Retry qoidalari (xato turi bo'yicha):**
- Vaqtinchalik (timeout, 5xx, DB lock) → retry, eksponensial + jitter.
- 429 → `Retry-After` ga amal qilinadi; shop/kanal throttle kamaytiriladi.
- 4xx (noto'g'ri so'rov, ruxsat yo'q) → retry yo'q, darhol yakuniy xato.
- **Noaniq natija** (tashqi chaqiruv timeout — yuborildimi yo'qmi noma'lum) → ko'r-ko'rona qayta yuborilmaydi: avval provayderdan holat so'raladi yoki operatorga belgi. Telegram uchun takror xabar ehtimoli qabul qilinadi va `duplicate_suspected` bilan belgilanadi.

### 4.3 Vazifa kodi qoidalari

```python
# app/workers/tasks/ai_reply.py
async def ai_reply(ctx, *, shop_id: str, conversation_id: str, message_id: str, traceparent: str) -> None:
    with tracer.start_as_current_span("ai_reply", context=extract(traceparent)):
        async with session_scope(shop_id=shop_id) as db:          # set_config('app.shop_id')
            await sales_ai_agent.reply(UUID(conversation_id), UUID(message_id), db)
```
- Payload'da faqat ID'lar, `shop_id`, `traceparent`. Matn, PII — yo'q.
- **`ai_reply` eskirish qoidasi:** vazifa boshlanganda trigger bo'lgan xabar 10 daqiqadan eski bo'lsa — vazifa **tashlanadi** (`cos_task_total{task="ai_reply", result="stale_dropped"}`), suhbat `HUMAN_NEEDED` ga o'tkaziladi. Navbat tiqilib qolgandan keyin xaridorga kechikkan, kontekstdan uzilgan AI javobi ketmasligi uchun.
- **AI rejimlari** (`sales_ai` sozlamasi, `14`): `AUTO` — javob tekshiruvdan o'tsa yuboriladi; `SUGGEST` — javob operatorga taklif sifatida ko'rsatiladi, yubormaydi (pilotning 1-haftasi, `../business/13`); `OFF` — `ai_reply` umuman navbatga qo'yilmaydi, xabar operatorga.
- Worker ruxsat va holatni **DB'dan qayta o'qiydi** (shop to'xtatilganmi, suhbatni operator olganmi, xodim o'chirilganmi).
- DB tranzaksiyasi tashqi chaqiruv paytida ochiq turmaydi: o'qish TX → LLM/Telegram → yozish TX.
- Bloklovchi SDK — `anyio.to_thread.run_sync`; CPU og'ir ish (rasm) — alohida jarayon.
- Har vazifa uchun `max_tries`, `timeout` aniq; cheksiz `asyncio.gather` yo'q — semaphore bilan.

---

## 5. `scheduler_worker`

### 5.1 Leader va lock

```python
async def main():
    async with engine.connect() as conn:
        while not await try_advisory_lock(conn, "scheduler_leader"):   # pg_try_advisory_lock(hashtext(...))
            await asyncio.sleep(10)                                   # boshqa nusxa leader
        scheduler = AsyncIOScheduler(timezone="Asia/Tashkent")
        register_jobs(scheduler)                                      # DomainManifest.scheduled_jobs dan
        scheduler.start()
        await keep_alive(conn)                                        # ulanish uzilsa lock bo'shaydi → boshqa nusxa oladi
```
- Leader ulanishi uzilsa, PostgreSQL lock'ni o'zi bo'shatadi; boshqa nusxa 10 s ichida oladi.
- Har rejali ish qo'shimcha ravishda `job:<name>` advisory lock bilan (ikki leader bir lahzada bo'lib qolsa ham).
- Scheduler faqat **tekshiradi va navbatga qo'yadi** yoki 100 qatorlik bo'laklarda tez DB yangilash qiladi. Har ish ≤ 5 daqiqa.
- Har ish idempotent: kalit `<job>:<entity_id>:<window>`; ikki marta ishlasa ham bitta vazifa/eslatma.

### 5.2 Rejali ishlar ro'yxati (Stage 1)

| Ish | Jadval | Egasi | Nima qiladi | Idempotency kaliti | Qoida |
|---|---|---|---|---|---|
| `order_confirm_reminder` | har 15 daq | commerce | `PENDING_CONFIRMATION` > 24 soat → operator va menejerga eslatma; **bekor qilmaydi** | `order_reminder:{order_id}:24h` | DEC-104 |
| `reservation_review` | har 15 daq | commerce | `ACTIVE` rezerv > 72 soat (`shop_policy.reservation_review_hours`) → menejerga "bekor qilinsinmi?" vazifasi; holat o'zgarmaydi | `reservation_review:{reservation_id}:72h` | DEC-104 |
| `quote_expiry` | har 5 daq | commerce | `SENT` va `expires_at < now()` → `EXPIRE` (USE orqali), `commerce.quote.expired` | holat o'tishining o'zi (takror `SENT` emas) | DEC-103 |
| `conversation_waiting_reminder` | har 5 daq | messaging | `HUMAN_NEEDED` > shop sozlagan vaqt → menejerga eslatma | `conv_waiting:{conversation_id}:{speaker_version}` | `business/05` 4-qism |
| `exchange_rate_staleness` | har soat | catalog | shop kursi 3 kundan eski → egaga ogohlantirish; yangi taklif yakuniy narxi bloklanadi | `fx_stale:{shop_id}:{date}` | BL-018, UAT-M05 |
| `exchange_rate_fetch` | har kuni 09:30 | catalog | Markaziy bank kursini olib, "MB kursi" tanlagan shoplar uchun yangilaydi | `fx_fetch:{date}` | DEC-121 |
| `channel_health_check` | har 30 daq | messaging | token muddati yaqin / xatolar ko'p → `DEGRADED`, egaga ogohlantirish | `channel_health:{channel_id}:{hour}` | FSM-03 |
| `audit_partition_create` | har oy 25-sanasi | platform/audit | keyingi oy partitsiyalari (`audit.events`, `platform.transition_log`) | partition nomi | `07` |
| `audio_purge` | har soat | reporting | transkripsiya qilingan audio fayllarni o'chiradi | `audio_id` | DEC-117 |
| `outbox_reconcile` (`app.workers.reconcile_tasks`) | har 5 daq | workers | `PUBLISHED` > 10 daq, lekin kutilgan consumer uchun `consumed_events` yo'q → `dispatch_event` qayta qo'yiladi | `{event_id}:{consumer}` | ADR-033 |
| `outbox_cleanup` | har kuni 03:00 | platform | `PUBLISHED` > 7 kun va `consumed_events` > 30 kun — o'chirish (bo'laklab) | — | — |
| `idempotency_cleanup` | har kuni 03:30 | platform | idempotency yozuvlari > 7 kun — o'chirish | — | — |
| `retention_purge` | har kuni 04:00 | platform | `26` dagi muddatlar bo'yicha (huquqshunos tasdig'idan keyin yoqiladi) | `retention:{table}:{date}` | `26` |
| `ai_usage_rollup` | har 10 daq | platform/billing | AI xarajatini shop bo'yicha yig'adi; limitga yaqin → ogohlantirish; tugasa → `platform.ai_quota.exhausted` | `ai_quota:{shop_id}:{period}` | DEC-119 |

Vaqtlar `Asia/Tashkent`; shop sozlamalari (`shop_policy`) o'qiladi. Hech bir rejali ish buyurtma yoki rezervni **avtomatik bekor qilmaydi** (`business/05` 4-qism).

---

## 6. Redis yo'qolsa yoki ishlamasa

| Holat | Nima bo'ladi | Tiklanish |
|---|---|---|
| Redis o'chdi | API ishlayveradi (yozish, buyurtma, tasdiqlash — PostgreSQL'da). Outbox `PENDING` to'planadi. Kesh yo'q → DB'dan o'qiladi. Rate limit — `08` §5.3 dagi konservativ fallback. WS realtime to'xtaydi (dashboard REST poll'ga o'tadi). | Redis qaytgach outbox_worker hammasini yuboradi |
| Redis qayta ishga tushdi, AOF'dan oxirgi ~1 s yo'qoldi | Ba'zi `PUBLISHED` qilingan arq vazifalari yo'q | `app.workers.reconcile_tasks` 5–15 daqiqada qayta qo'yadi: (1) outbox — `consumed_events` yo'q consumer'lar; (2) tashqi niyatlar — `messaging.outbound_messages` `PENDING` > 5 daq, `catalog.imports` `RUNNING` heartbeat'siz > 10 daq, `platform.notifications` `SCHEDULED` > 5 daq |
| arq vazifasi bajarilish o'rtasida worker o'ldi | arq qayta beradi (`max_tries`) | idempotency kaliti ikki marta bajarishdan saqlaydi (TC-022) |
| Rejali ish o'tkazib yuborildi (scheduler o'chiq edi) | — | Ishlar "oxirgi ishga tushgandan beri" emas, **holat bo'yicha** tanlaydi (`created_at < now() - 24h AND reminder_sent_at IS NULL`) — keyingi ishga tushishda yetib oladi |

---

## 7. Backpressure va degradatsiya

| Bosim | Javob |
|---|---|
| DB pool to'lmoqda | API global inflight limiti; yozish endpoint'lari side-effect'dan **oldin** `503 SERVICE_UNAVAILABLE` + `Retry-After` |
| `ai_reply` kutayotganlar > 50 yoki eng eskisi > 60 s | Yangi suhbatlarga AI o'rniga "operator tez orada javob beradi" + `HUMAN_NEEDED`; buyurtma va qoldiq vazifalari ta'sirlanmaydi |
| Shop AI limiti tugadi | `platform.ai_quota.exhausted` → `sales_ai` rejimi `OFF`, hamma xabar operatorga (BL-067, BL-069) |
| LLM provayder ishlamaydi | 2 urinish, keyin handoff; circuit breaker 5 daq (ketma-ket 5 xato) |
| Telegram/Meta 429 | `Retry-After`, shop kanali bo'yicha throttle; navbat o'sishi alert |
| Import katta | Bir shop bir vaqtda 1 ta import; bo'laklar 500 qator |

Qoida: degradatsiyada **buyurtma, qoldiq va tasdiqlash yo'li ishlashda davom etadi** — faqat AI va qulayliklar o'chadi.

---

## 8. Kuzatuv

| Metrika | Alert |
|---|---|
| `cos_queue_depth{queue}` | `default` > 200, `low` > 20 |
| `cos_queue_oldest_seconds{queue}` | `default` > 120 s, `low` > 900 s |
| `cos_task_total{task, result="ok|retry|failed"}` | `failed` > 5/10 daq |
| `cos_task_duration_seconds{task}` | p95 > timeout × 0.8 |
| `cos_scheduler_leader` (0/1, har nusxa) | yig'indisi ≠ 1 (5 daq) |
| `cos_scheduled_job_lag_seconds{job}` | > 30 s |
| `cos_scheduled_job_last_success_timestamp{job}` | jadvaldan 3 baravar eski |
| `cos_ai_cost_amount{shop}` (minor UZS) | limitning 80% |

Har vazifa span'i outbox'dagi `traceparent` ga bog'langan (`09`).

## 9. Testlar

1. Scheduler 3 nusxada → har rejali ish bir marta (`cos_scheduler_leader` yig'indisi 1).
2. Leader o'ldirildi → 15 s ichida boshqa nusxa leader, o'tkazib yuborilgan eslatma keyingi ishga tushishda yuboriladi.
3. `ai_reply` paytida operator suhbatni oldi → javob yuborilmaydi (TC-009).
4. `channel_send` — Telegram 429 3 marta → `Retry-After` hurmat qilinadi, bitta xabar (TC-032).
5. `channel_send` — 403 (bot bloklangan) → retry yo'q, `messaging.message.failed`, vazifa (TC-011).
6. Worker `catalog_import` o'rtasida o'ldirildi → davom etganda takror mahsulot yo'q.
7. AI navbati to'lib ketganda buyurtma tasdiqlash p95 o'zgarmaydi.
8. `time.sleep` yoki `requests` import qilingan vazifa — lint xatosi (ruff qoidasi).

## Keyingi qadam

→ [07-data-layer.md](07-data-layer.md) — schemalar va jadvallar
→ [08-cache-and-realtime.md](08-cache-and-realtime.md) — Redis va WebSocket
