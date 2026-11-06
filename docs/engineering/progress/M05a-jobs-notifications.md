# 5a — Fon ishlari, xodim vazifalari va xabarnomalari, realtime

> **Holat:** backend bitdi (2026-10-26). Commit qilinmagan — founder ko'rib chiqishi kutilmoqda.
> **Reja:** [27-roadmap-and-tasks.md](../27-roadmap-and-tasks.md) — S0-06 (outbox, arq, scheduler), S2-06 (`platform/notifications`, `platform/realtime`), TD-01, TD-02.
> **Baza:** [db/jobs.md](../db/jobs.md), [db/notifications.md](../db/notifications.md) — DEC-138, DEC-139 (taklif, founder ko'rib chiqadi).
> **Kim o'qiydi:** founder va dasturchilar. 5b (chat, inbox, Telegram) va 5c (katalog importi) shu poydevor ustida quriladi.

---

## 1. Nima bitdi — qisqacha

Tizim endi "so'rov keldi → javob berdi" dan tashqari ham ishlaydi: hech kim so'rov yubormasa ham eslatma chiqadi, sayt keshi o'zi yangilanadi, xodim telefoniga xabar boradi. Asosiy qoida — ish **yo'qolmaydi**: "keyin qilinadigan ish" biznes o'zgarishi bilan bitta tranzaksiyada bazaga yoziladi (outbox), alohida jarayon uni bajaradi.

```
Service:        buyurtma tasdiqlandi + outbox qatori ──COMMIT──▶ (ikkalasi bor yoki ikkalasi yo'q)
outbox_worker:  outbox ──▶ arzon tinglovchilar shu zahoti (sayt keshi, panel signali)
                       └─▶ qolganlari uchun vazifa (Redis, arq) ──▶ PUBLISHED
task_worker:    tinglovchi: "bajarildi" belgisi + o'z ishi (Telegram'ga yuborish, SKU'larni qayta bog'lash)
scheduler:      har 15 daqiqa: "24 soatdan eski tasdiqlanmagan buyurtma bormi?" ──▶ vazifa + xabar
```

Xodim tomonidan ko'rinadigani:

```
Panel: 🔔 bildirishnomalar (o'qilgan / o'qilmagan) · ✅ vazifalar ("Kimdir biror narsa qilishi kerak")
       ⚡ WebSocket signali: yangi vazifa, xabar, buyurtma va qoldiq o'zgarishi — sahifa o'zi yangilanadi
Telegram: platforma boti — xodim bir martalik kod bilan ulaydi, xabarlar telefoniga ham keladi
```

Hech bir rejali ish buyurtma yoki bandni avtomatik bekor qilmaydi — faqat odamni chaqiradi (business/05, 4-qism).

---

## 2. Rejadagi bandlar

- [x] **Outbox** (05 §4): `platform`, `catalog`, `commerce`, `storefront` schemalarida `outbox_events` + `consumer_receipts`. `envelope jsonb` (DEC-138, 1-qaror). `write_outbox()` — biznes tranzaksiyasi ichida; payload'da PII tekshiruvi (taqiqlangan maydon — dasturchi xatosi).
- [x] **outbox_worker** (05 §5): `FOR UPDATE SKIP LOCKED`, 100 tadan; inline tinglovchilar shu zahoti; qolganlari arq'ga `job_id = event:consumer`. Redis ishlamasa — PENDING qoladi, 2, 4, 8 … s (≤ 5 daq).
- [x] **task_worker** (arq, 06 §4): `dispatch_event` (8 urinish, 2 s → ~4 daq + jitter, keyin dead-letter), `notification_send` (5 urinish, FSM-12).
- [x] **scheduler** (06 §5): APScheduler + PostgreSQL advisory lock (bitta leader), har ish `job:<nom>` qulfi bilan, natija `platform.job_runs` da.
- [x] **Dead-letter** (05 §7): `platform.dead_letters`; platforma panelida ro'yxat, "qayta yuborish", "qoldirish" (audit bilan).
- [x] **`TODO(S0-06)` lar** — hammasi yopildi (kodda `TODO(S0-06)` qolmadi):
  - katalog: `catalog.product.published/hidden/archived`, `catalog.price.changed`, `catalog.exchange_rate.updated`, `catalog.hardware_spec.updated`;
  - sayt keshi: `index_version` event bilan oshadi (oldin faqat 60 s TTL);
  - kutubxona modeli tasdiqlansa — har shopda bog'lanmagan SKU'lar qayta bog'lanadi (oldin qo'lda "Qayta tekshirish");
  - savdo: buyurtma (`drafted`, `submitted`, `confirmed`, `processing`, `ready`, `completed`, `cancelled`, `exception`, `paid_marked`, `assigned`), band (`created`, `released`, `expired`), qoldiq (`stock.changed`, absolyut qiymatlar), tez sotuv (`quick_sale.recorded`);
  - 24/72 soat eslatmalari → `staff_tasks` (+ xabar); buyurtma o'zgarsa vazifa o'zi yopiladi;
  - kechki ombor solishtiruvi → vazifa va alert, avtomatik tuzatish YO'Q;
  - kurs eskirdi → ega va menejerga vazifa, kunda bir marta; yangi kurs kiritilsa — o'zi yopiladi.
- [x] **TD-01** — `audit_partition_create` (har oy 25-sanasi): `platform.ensure_monthly_partitions(12)` — `app_migrator` egaligidagi SECURITY DEFINER funksiya.
- [x] **TD-02** — `idempotency_cleanup` (har soat): muddati o'tgan `idempotency_keys`.
- [x] **Tozalash** — `outbox_cleanup` (03:00): PUBLISHED 14 kun, belgilar 7 kun, ish jurnali 30 kun; `notifications_cleanup` (03:15): xabarnomalar 90 kun, kodlar 1 kun.
- [x] **Rekonsilyatsiya** — `outbox_reconcile` (har 5 daq): Redis yo'qotgan vazifalar va tinch soati tugagan xabarlar qayta navbatga.
- [x] **platform/notifications**: bildirishnomalar markazi, vazifalar, xodim sozlamasi (tinch soat, bot yoqish/o'chirish, o'chirilgan turlar), platforma botiga ulanish (bir martalik kod, faqat xeshi).
- [x] **platform/realtime**: `POST /api/v1/auth/ws-ticket` → `WS /api/v1/ws`; signal faqat ID bilan; har heartbeat'da sessiya va a'zolik bazadan qayta tekshiriladi.
- [x] **`shop_policies`**: `handoff_reminder_minutes` (15), `inbox_hours` (ixtiyoriy) — 5b uchun.
- [x] **Demo**: seed rejali ishlarni bir marta ishga tushiradi → demo shoplarda vazifa va xabarlar.

**Ataylab keyinga qoldirilgan:**
- Xaridorga xabar (`customer.*` shablonlari, `shop_message_templates`, `platform.notification.customer_delivery_requested`) — 5b, xaridor kanallari bilan.
- `HANDOFF`, `INSTAGRAM_WINDOW_CLOSED`, `CHANNEL_DEGRADED`, `IMPORT_REVIEW` vazifa turlari — 5b/5c.
- Platforma paneli realtime'i (ticket hozir faqat shop paneli uchun).
- `DISCOUNT_APPROVAL` vazifasi — chegirma so'rovi hozir buyurtma kartochkasida ko'rinadi; vazifaga aylantirish frontend bilan birga kelishiladi.
- Metrikalar (`cos_outbox_*`, `cos_queue_*`) — S0-05 monitoring bilan; hozircha `job_runs` va loglar.

**Kartadan farqlar** — §8 dagi qarorlar.

---

## 3. Fayllar xaritasi

```
app/shared/events/                 umumiy: event, outbox, tinglovchi va rejali ish e'loni
├── envelope.py                    EventEnvelope (K-08): event_id, shop_id, agregat, actor, trace, payload
├── models.py                      outbox_events + consumer_receipts jadvallari (har outbox schemasida)
├── outbox.py                      write_outbox() — biznes tranzaksiyasi ichida
├── pii.py                         payload'da taqiqlangan maydonlar (telefon, ism, manzil, matn, token)
└── registry.py                    Subscriber, @subscriber, SubscriberRegistry, ScheduledJob, JobResult, RetryLater
app/shared/realtime/broker.py      RedisBroker (db2) / MemoryBroker: a'zolik kanali, seq, bir martalik ticket
app/platform/jobs/                 dead-letter, ish jurnali, platforma tozalash ishlari
├── models/orm.py                  DeadLetter, JobRun
├── api/platform_routes.py         /platform/dead-letters, /platform/jobs
├── services/maintenance.py        idempotency_cleanup (TD-02), partition_create (TD-01), outbox_cleanup
├── services/shops.py              open_shop_ids() — rejali ishlar uchun shoplar ro'yxati
└── manifest.py
app/platform/notifications/        xodim xabarnomalari, vazifalar, platforma boti
├── models/orm.py                  Notification, StaffTask, StaffNotificationSettings, StaffTelegramLink, TelegramLinkCode
├── templates.py                   xodim matnlari (uz/ru/en), versiya staff-2026-10-v1
├── telegram.py                    HttpTelegramSender / LoggingTelegramSender / FakeTelegramSender
├── services/recipients.py         rol + filial bo'yicha faol xodimlar
├── services/notifications.py      notify_staff(), markaz, o'qilgan, sozlama
├── services/tasks.py              TaskService: open/resolve (domen), list/done/assign (panel)
├── services/delivery.py           TelegramDelivery: o'qish TX → yuborish → yozish TX; tinch soat
├── services/telegram_link.py      bir martalik kod, /start bilan ulash, uzish
├── api/routes.py                  /shop/notifications, /shop/tasks, /shop/me/notification-settings, /shop/me/telegram-link
├── api/webhook_routes.py          /webhooks/platform-telegram (sir sarlavhasi)
├── subscribers.py                 platform.notification.created → botga; notifications_cleanup
├── providers.py, manifest.py
app/platform/realtime/             WebSocket
├── api/routes.py                  POST /auth/ws-ticket, WS /api/v1/ws
├── subscribers.py                 realtime_fanout: event → kimga signal (bazadan)
└── manifest.py
app/workers/                       fon jarayonlari (composition root)
├── runtime.py                     WorkerRuntime: API bilan bir xil servislar + tinglovchilar + ishlar
├── queue.py                       ArqQueue / RecordingQueue
├── dispatch.py                    run_subscriber (consumer_receipts), deliver, dead_letter
├── outbox_worker.py               dispatch_pending, run_forever
├── task_worker.py                 arq WorkerSettings: dispatch_event, notification_send
├── scheduler.py                   leader, run_job (job_runs), APScheduler
├── reconcile.py                   outbox_reconcile
└── dev.py                         lokal: uchalasi bitta jarayonda (make worker)
app/domains/commerce/events.py     buyurtma, band, qoldiq event'lari (PII'siz payload)
app/domains/commerce/jobs.py       order_confirm_reminder, reservation_review, stock_reconcile
app/domains/catalog/subscribers.py relink_on_spec_updated, exchange_rate_staleness
app/domains/storefront/subscribers.py  invalidate_site_cache (inline)
app/db/seed/notifications_seed.py  rejali ishlarni bir marta — demo vazifalar
migratsiyalar: platform_0009, catalog_0004, commerce_0004, storefront_0003
testlar: tests/unit/test_jobs_units.py, tests/integration/test_jobs_events.py,
         tests/integration/test_realtime_notifications.py
```

---

## 4. Qaysi faylda nima bor

### 4.1 Event yozish — `app/shared/events/outbox.py`

`write_outbox(db, schema=..., event_type=..., actor=..., shop_id=..., aggregate_type=..., aggregate_id=..., aggregate_version=..., payload=...)`:
- payload JSON'ga aylantiriladi va **PII tekshiruvidan** o'tadi (`pii.py`: maydon nomidagi so'z — `phone`, `name`, `address`, `comment`, `text`, `token` …). Topilsa — xato, event yozilmaydi;
- envelope'ga `traceparent` (so'rovning trace_id'si) va `correlation_id` (X-Request-ID) qo'shiladi — trace HTTP → outbox → arq bo'ylab davom etadi;
- qator `<schema>.outbox_events` ga `PENDING` holatida — shu tranzaksiya COMMIT bo'lsagina.

Domenda: `commerce/events.py` (`order_event`, `reservation_event`, `stock_changed`), katalog servislari to'g'ridan `write_outbox`. Buyurtma event'ida erkin matnli sabab yo'q — faqat `reason_code` (masalan `EXPIRED`).

### 4.2 Tarqatish — `app/workers/outbox_worker.py`, `dispatch.py`

```
dispatch_schema(schema):
  BEGIN
    100 ta PENDING (next_attempt_at ≤ now) FOR UPDATE SKIP LOCKED
    har event: buzilgan envelope → DEAD
               inline tinglovchi → ro'yxatga (COMMIT'dan keyin bajariladi)
               boshqasi → enqueue("dispatch_event", job_id=f"{event_id}:{consumer}")
               navbat xatosi → attempts+1, next_attempt_at = now + min(2^n, 300 s)
    muvaffaqiyatlilar → PUBLISHED
  COMMIT
  inline tinglovchilar (xato bo'lsa — oddiy vazifaga tushadi)
```

`run_subscriber` (05 §6): tranzaksiyali tinglovchi — event shopi kontekstida `consumer_receipts` belgisi + ish bitta COMMIT'da; belgi bor bo'lsa — ish qilinmaydi (TC-022). Tranzaksiyasiz tinglovchi (Telegram, ko'p shopli ish) — belgi tekshiriladi, ish, keyin belgi.
`deliver` — `dispatch_event` yadrosi: 8-urinishgacha xato qayta ko'tariladi (arq retry), 8-da dead-letter. Dead-letter'da xato **matni emas, turi** (`ValueError`, `TelegramSendError:BLOCKED`) — matnda PII bo'lishi mumkin.

### 4.3 Rejali ishlar — `app/workers/scheduler.py`

- Leader: `pg_try_advisory_lock('scheduler_leader')`, ulanish AUTOCOMMIT (ochiq tranzaksiya 10 s'da uzilardi), har 30 s `SELECT 1`. Leader o'lsa — boshqa nusxa 10 s ichida oladi.
- `run_job`: `job:<nom>` qulfi (band bo'lsa — `SKIPPED`), `job_runs` ga `RUNNING` → `OK`/`FAILED` (xato turi), `processed`, `affected`, `details`.
- Oraliqli ishlar jarayon ishga tushishi bilan bir marta ham ishlaydi (holat bo'yicha — o'tkazib yuborilganlar yetib olinadi).
- Vaqt — `Asia/Tashkent`.

Ishlar ro'yxati (manifest'lardan yig'iladi):
- `order_confirm_reminder` (15 daq), `reservation_review` (15 daq), `stock_reconcile` (03:30) — commerce;
- `exchange_rate_staleness` (soatlik) — catalog;
- `idempotency_cleanup` (soatlik), `audit_partition_create` (oyning 25-si, 03:00), `outbox_cleanup` (03:00) — platform/jobs;
- `notifications_cleanup` (03:15) — platform/notifications;
- `outbox_reconcile` (5 daq) — workers.

### 4.4 Vazifalar — `app/platform/notifications/services/tasks.py`

Domen chaqiradi: `open(...)` — `dedup_key` bilan (`order_reminder:{order_id}:24h`), takroriy chaqiruv `None`; `resolve(subject...)` — sabab yo'qolganda `RESOLVED`. Har ochilish/yopilish — `platform.task.created/closed` event'i (panel signali).

Qayerda ochiladi va yopiladi:
- `ORDER_CONFIRM_REMINDER` — rejali ish; buyurtma tasdiq kutishdan chiqsa (`_finish` → `_resolve_tasks`) yopiladi;
- `RESERVATION_REVIEW` — rejali ish (`due_at` = band muddati); "Kutamiz" qarorida joriy oyna yopiladi, yangi muddat kelganda yangi vazifa; buyurtma yakunlansa — hammasi;
- `ADJUSTMENT_APPROVAL` — omborchi tuzatish so'raganda; tasdiqlash yoki rad etishda yopiladi;
- `STOCK_RECONCILE_MISMATCH` (HIGH) — kechki solishtiruv;
- `EXCHANGE_RATE_STALE` — kurs eskirdi; yangi kurs kiritilsa yopiladi.

Kim ko'radi: ega va menejer — filial doirasidagi hammasini; operator va omborchi — o'ziga biriktirilganini yoki o'z roliga (filiali bo'yicha). `assign` — faqat ega/menejer, xodim filialni qamrashi shart. `done` va `assign` — If-Match + Idempotency-Key.

### 4.5 Xabarnomalar — `notifications.py`, `delivery.py`, `telegram_link.py`

`notify_staff(...)`: qabul qiluvchilar (aniq xodimlar va/yoki rol + filial) → har biriga o'z tilida matn → qator (`dedup_key` unikal, BL-060) → `platform.notification.created`. O'zi qilgan amal haqida o'ziga xabar ketmaydi (`exclude`).

Botga yetkazish (FSM-12), tashqi chaqiruv tranzaksiyadan tashqarida:
```
o'qish TX: ulanmagan → SUPPRESSED (NOT_LINKED) · bot o'chirilgan/turi o'chirilgan → SUPPRESSED (MUTED)
           tinch soat (HIGH emas) → SCHEDULED, scheduled_at = tinch soat oxiri
           aks holda attempts+1
Telegram'ga yuborish
yozish TX: SENT · 403 (bot bloklangan) → FAILED + ulanish uziladi · vaqtinchalik xato → qayta (5 marta), keyin FAILED
```
`SENT`/`FAILED`/`SUPPRESSED` bo'lsa qayta yuborilmaydi — event qayta kelsa ham bitta xabar.

Ulash: panel `POST /shop/me/telegram-link` → 10 daqiqalik kod (faqat javobda, bazada SHA-256) va `https://t.me/<bot>?start=<kod>` → bot webhook'i `/start <kod>` → `staff_telegram_links`. Bitta Telegram akkaunt — bitta odam (boshqasiga ulangan bo'lsa, eski ulanish uziladi). Kod bir martalik.

### 4.6 Realtime — `app/platform/realtime/`

```
POST /api/v1/auth/ws-ticket (Bearer)  → {"ticket", "expires_in": 30, "path": "/api/v1/ws"}   (Redis db2, xeshi bilan)
WS   /api/v1/ws?ticket=…              → {"type": "hello", "seq": 41, "heartbeat_seconds": 25}
                                        {"type": "task.created", "shop_id", "resource": {"kind", "id", "version"}, "seq": 42, "trace_id"}
                                        {"type": "ping"}
yopilish: 4401 — ticket yo'q/eskirgan, sessiya bekor, xodim o'chirilgan · 4403 — shop yopilgan
```
- Kanal har a'zolikka alohida (`cos:v1:rt:m:{membership_id}`) — keng shop kanali yo'q, operator boshqaning signalini olmaydi.
- `seq` — a'zolik bo'yicha Redis'da oshadi; klient bo'shliqni ko'rsa ro'yxatlarni REST'dan qayta yuklaydi (DEC-139, 3-qaror).
- Turlar: `notification.created`, `task.created`, `task.closed`, `order.changed`, `stock.changed`. Ichida matn, ism, telefon yo'q.
- Kimga — `realtime_fanout` (inline tinglovchi) bazadan hal qiladi: buyurtma → biriktirilgan operator, ega/menejer (filial), tasdiqlangandan keyin omborchi, biriktirilmagan navbat bo'lsa operatorlar; qoldiq → qoldiqni ko'radigan rollar (filial); vazifa → biriktirilgan xodim, rol egalari, ega/menejer.

### 4.7 API

Shop paneli (`/api/v1/shop`):
- `GET /notifications?unread=&cursor=&limit=` · `GET /notifications/unread-count` · `POST /notifications/{id}/read` · `POST /notifications/read-all`
- `GET /tasks?status=OPEN&type=&cursor=&limit=` · `POST /tasks/{id}/done` · `POST /tasks/{id}/assign` (`{"membership_id"}`)
- `GET|PUT /me/notification-settings` (birinchi saqlash `If-Match: "v0"`)
- `GET|POST|DELETE /me/telegram-link`

Auth: `POST /api/v1/auth/ws-ticket`. Realtime: `WS /api/v1/ws`.
Webhook: `POST /api/v1/webhooks/platform-telegram` (`X-Telegram-Bot-Api-Secret-Token`).
Platforma paneli: `GET /platform/dead-letters?status=`, `POST /platform/dead-letters/{id}/replay|ignore` (`{"note"}`), `GET /platform/jobs` (har ishning oxirgi holati va oxirgi muvaffaqiyati).

### 4.8 Baza va ruxsatlar

- `platform_0009`: outbox, receipts, dead_letters, job_runs, notifications, staff_tasks, staff_notification_settings, staff_telegram_links, telegram_link_codes; `shop_policies` ga ikki ustun; RLS (FORCE) — notifications, staff_tasks, staff_notification_settings; `platform.ensure_monthly_partitions` (SECURITY DEFINER, faqat partitsiya; EXECUTE — `app_runtime`).
- `catalog_0004`, `commerce_0004`, `storefront_0003`: shu schemadagi outbox va receipts.
- Ruxsatlar: `platform.dead_letter.view`, `platform.dead_letter.replay` — platforma admini. Vazifalar — mavjud `staff.task.view` (hamma rol). Bildirishnoma va sozlama — har xodimning o'ziniki.

### 4.9 Ishga tushirish (lokal)

```
make worker          # outbox_worker + task_worker + scheduler — bitta jarayonda (app/workers/dev.py)
make outbox-worker   # alohida (production'dagidek)
make task-worker     # arq app.workers.task_worker.WorkerSettings
make scheduler
```
Redis: kesh va rate limit — db0, arq — db1 (`ARQ_REDIS_URL`), realtime — db2 (`REALTIME_REDIS_URL`). Bot tokeni yo'q bo'lsa xabar yuborilmaydi (faqat log), webhook siri yo'q bo'lsa webhook 404.

---

## 5. Testlar

`make check` — **481 passed** (oldin 439, +42), ruff, mypy strict, import-linter toza.

- `tests/unit/test_jobs_units.py` (17): payload PII tekshiruvi; tinglovchi mosligi (`commerce.order.*`) va nom takrori; rejali ish jadvali; retry kechikishi va chegarasi; dead-letter xato kodi matnsiz; shablonlar uch tilda; vazifa havolalari; tinch soat (tun bo'yi oyna); MemoryBroker seq va bir martalik/eskirgan ticket; bot `/start` faqat shaxsiy chatda.
- `tests/integration/test_jobs_events.py` (17):
  - tranzaksiya bekor bo'lsa event yo'q, COMMIT bo'lsa bor;
  - narx/chiqarish event'lari sayt keshini eskirtiradi, event'lar PUBLISHED, belgi yoziladi;
  - bir event 3 marta kelsa ham tinglovchi bir marta (TC-022);
  - yiqiladigan tinglovchi: 7 marta retry, 8-da dead-letter (matnsiz), admin "qayta yuborish", rekonsilyatsiya yangi job_id bilan qayta qo'yadi;
  - navbat (Redis) ishlamasa — PENDING, attempts=1, keyinroq;
  - 24 soat eslatmasi: bitta vazifa (ikki marta ishlasa ham), xabar, `job_runs` OK, tasdiqlansa RESOLVED;
  - 72 soat: vazifa, "Kutamiz" — yopiladi, qayta ishlasa yangisi yo'q;
  - tuzatish so'rovi — menejer va egaga vazifa (omborchiga emas), tasdiqda yopiladi;
  - kechki solishtiruv — HIGH vazifa, qoldiq o'zgarmaydi, kunda bitta;
  - eskirgan kurs — vazifa, yangi kursda yopiladi;
  - vazifa `assign` (If-Match, faqat ega/menejer) va `done`;
  - kutubxona modeli tasdiqlansa — boshqa shopdagi SKU `AUTO_MPN` bilan bog'lanadi;
  - TD-01: funksiya ilova roli bilan partitsiya yaratadi, yangi partitsiyada UPDATE huquqi yo'q;
  - TD-02: muddati o'tgan kalit o'chadi, yangisi qoladi;
  - xabarnomalar shaxsiy (boshqa xodim/shop 404), RLS: boshqa shop konteksti va kontekstsiz — 0 qator;
  - to'liq buyurtma yo'lidagi barcha event'larda telefon va ism yo'q, taqiqlangan maydon yo'q.
- `tests/integration/test_realtime_notifications.py` (8): bot sir sarlavhasi, noto'g'ri kod, ulash, xabar bir marta (SENT), o'chirilgan → SUPPRESSED/MUTED, bloklangan → FAILED + uzildi, kod bir martalik; WS ticket bir martalik va majburiy, eskirgan ticket, signal faqat o'z egasiga (boshqa shop kelmaydi), COMMIT bo'lgan event → panel signali (`seq` oshadi, matn yo'q), sessiya bekor qilinsa ulanish 4401 bilan yopiladi.
- Seed testi: 4 turdagi demo vazifa, qayta seed yangisini yaratmaydi.

---

## 6. Jarayonda topilgan muammolar

- **FORCE RLS va SECURITY DEFINER.** Jadvallar `FORCE ROW LEVEL SECURITY` bilan — egasi (`app_migrator`) ham siyosatga bo'ysunadi, shuning uchun shoplararo SELECT uchun SECURITY DEFINER yordam bermaydi. Yechim: shoplar ro'yxati RLS'siz `platform.shops` dan, har shop alohida tranzaksiyada o'z konteksti bilan. SECURITY DEFINER faqat partitsiya DDL uchun qoldi.
- **Ochiq tranzaksiyadagi qulf.** `idle_in_transaction_session_timeout` = 10 s: advisory lock ulanishi tranzaksiyada tursa uziladi — qulf ulanishlari AUTOCOMMIT'ga o'tkazildi.
- **arq takror himoyasi.** arq bir xil `job_id` natijasini `keep_result` davomida eslaydi — qayta yuborilgan dead-letter yangi `job_id` (`…:replay:<vaqt>`) bilan qo'yiladi; `keep_result` 60 s.
- **Testlarda boshqa fayllarning event'lari.** Sessiya bo'yi bitta baza — oldingi testlar qoldirgan PENDING event'lar navbatga aralashmasligi uchun 5a testlari boshida ularni PUBLISHED qiladi.

---

## 7. Keyingi modulga meros

- **5b (chat, inbox, Telegram):** `messaging` schemasiga `OUTBOX_SCHEMAS` ga qo'shiladi (migratsiya + `app/shared/events/models.py`); `channel_send` — task_worker funksiyasi; xaridorga xabar — `notify_customer` (xuddi `notify_staff` kabi) va `platform.notification.customer_delivery_requested`; `HANDOFF` vazifasi va `handoff_reminder_minutes`; realtime turlari `conversation.*`.
- **5c (import):** `catalog_import` qoldig'i event bilan commerce'ga (`catalog.import.completed`), og'ir ish `low` navbatda.
- **Qoida:** service hech qachon arq'ga o'zi vazifa qo'ymaydi — faqat `write_outbox`; tashqi chaqiruvli tinglovchi `transactional=False` va o'z holati bilan idempotent; tinglovchi nomi (`consumer`) o'zgarmaydi.
- **Frontend:** bildirishnomalar markazi (qo'ng'iroqcha + ro'yxat), vazifalar sahifasi (`link.route` → panel manzili: `order` → `/orders/{id}`, `adjustment` → `/stock/adjustments`, `stock` → `/stock`, `exchange_rates` → `/catalog/rates`, `notification_settings` → profil), profilda sozlama va "Telegram'ga ulash", WS klienti (ticket → ulanish → `seq` bo'shlig'ida qayta yuklash, 4401 → yangi ticket).

---

## 8. Founder ko'rib chiqishi uchun qarorlar

Founder 2026-10-26 da qarorlarni topshirgan; o'zgarsa kod moslanadi. DEC-138, DEC-139 (db/jobs.md, db/notifications.md) dagilardan tashqari, qurish paytida qabul qilinganlar:

1. **Scheduler — APScheduler (arq cron emas).**
   - Nega: leader va jadval Redis'ga bog'liq emas; Redis o'chsa ham eslatma vazifalari bazada yaratiladi (06 §2 dagi arxitektura).
   - Muqobil: arq cron — bitta jarayon kam, lekin Redis'siz rejali ish ham to'xtaydi.
2. **"Ko'rib chiqish kerak" ro'yxati (3-modul API) hisoblangan holda qoldi, vazifalar unga qo'shimcha.**
   - Nega: API buzilmaydi; ro'yxat buyurtma holatidan darhol to'g'ri (scheduler 15 daqiqa kechiksa ham). Vazifalar — eslatma, biriktirish va umumiy "vazifalar" sahifasi uchun.
   - Muqobil: ro'yxatni to'liq `staff_tasks` dan o'qish — bitta manba, lekin 15 daqiqagacha kechikish va API versiyasi kerak.
3. **Shoplararo ishlar — SECURITY DEFINER SELECT funksiyalarisiz.** Shoplar ro'yxati RLS'siz jadvaldan, har shop o'z kontekstida (§6). SECURITY DEFINER — faqat partitsiya yaratish. DEC-138 3-qarorining ruhiga mos, lekin funksiyalar kamroq.
4. **Platforma boti ulanish jadvallari RLS'siz** (`principals` kabi identity jadval). Webhook kodni xeshi bo'yicha, yetkazish ishi qabul qiluvchining ulanishini "joriy odam" kontekstisiz o'qiydi. DBML "o'zim" RLS variantini taklif qilgan edi.
5. **Realtime kanali har a'zolikka alohida, `seq` a'zolik bo'yicha.** Keng shop kanali + filtr o'rniga: signal hech qachon ruxsatsiz xodimga yetmaydi, bo'shliqni aniqlash ishonchli.
   - Muqobil: rol/filial kanallari — Redis'da kamroq PUBLISH, lekin `seq` bo'shlig'i ma'nosiz bo'lib qoladi.
6. **WebSocket manzili `/api/v1/ws`** (08 dagi `/ws/v1/inbox` va 10/21 dagi `/ws` o'rniga) — Nginx'da `/api` yo'nalishi bitta; hujjatlar moslandi.
7. **Bildirishnomani o'qish (`read`, `read-all`) — Idempotency-Key'siz.** Tabiatan idempotent. Vazifa `done`/`assign` — Idempotency-Key va If-Match bilan.
8. **Buyurtma event'larida erkin matnli sabab yo'q** — faqat `reason_code`. Bekor qilish sababi xaridor ma'lumotini o'z ichiga olishi mumkin.
9. **`commerce.order.assigned` event'i qo'shildi** (05 katalogida yo'q edi) — yangi mas'ul operator panelda darhol ko'radi. 05 §8.2 ga yozildi.
10. **Bitta Telegram akkaunt — bitta xodim.** Boshqa xodim o'sha akkaunt bilan ulansa, eski ulanish uziladi.

---

## 9. Frontend (2026-10-26)

### 9.1 Nima bitdi — qisqacha

Shop panelida xodim endi vazifalarni bitta sahifada ko'radi, sarlavhada bildirishnomalar qo'ng'iroqchasi bor, ro'yxatlar esa sahifani qayta yuklamasdan o'zi yangilanadi. Profilda xodim Telegram'ga qaysi xabarlar va qachon kelishini tanlaydi va platforma botiga ulanadi. Platforma panelida admin rejali ishlar holatini va bajarilmay qolgan event'larni ko'radi.

```
Panel ochildi ──▶ POST /auth/ws-ticket ──▶ WS /api/v1/ws ──▶ hello (seq)
Signal (order.changed, task.created, …) ──▶ tegishli ro'yxat REST'dan qayta olinadi (ma'lumotning o'zi signalda yo'q)
seq sakradi / qayta ulanishda hello.seq oshgan ──▶ asosiy ro'yxatlar to'liq yangilanadi
Uzildi ──▶ 1 s … 30 s kutib qayta ulanadi · 4401 ──▶ yangi ticket · 4403 ──▶ shop yopilgan (chiqib ketish)
```

### 9.2 Sahifalar va komponentlar

- **Sarlavha** (shop paneli): jonli yangilanish nuqtasi (yashil — ulangan, sariq — ulanmoqda, kulrang — uzilgan) va **qo'ng'iroqcha**: o'qilmaganlar soni, oxirgi 15 ta bildirishnoma, "O'qilmaganlar" filtri, "Hammasini o'qildi". Bosilganda o'qilgan bo'ladi va havolasi bo'yicha sahifaga o'tadi (buyurtma, tuzatishlar, ombor, kurs, profil).
- **"Vazifalar" — `/[shop]/tasks`**: holat tablari (ochiq soni bilan), tur filtri, "Menga / Biriktirilmagan" filtri, "Ko'proq yuklash". Har vazifada matn (tur va raqamlardan, uch tilda), muhimlik, kimga biriktirilgani, muddati; "Ochish", "Biriktirish" (faqat ega va menejer, filial doirasidan tashqari xodim — maydon ostida xato), "Bajarildi" (If-Match va Idempotency-Key, ikki marta bosish himoyasi). "Ko'rib chiqish kerak" sahifasi bilan ikki tomonlama havola.
- **Profil**: "Bildirishnomalar" kartasi (Telegram'ga yuborish, tinch soatlar — ikkalasi birga, Telegram'ga keladigan turlar; muhimi — "har doim keladi", o'chirib bo'lmaydi; birinchi saqlash `If-Match "v0"`) va "Telegram bot" kartasi (holat, bir martalik kod `/start <kod>` nusxa olish bilan, qolgan vaqt, `t.me` tugmasi, kod kutilayotganda holat har 4 soniyada tekshiriladi; uzish tasdiq bilan; bot sozlanmagan bo'lsa ogohlantirish).
- **Platforma paneli `/jobs` — "Fon ishlari"** (`platform.dead_letter.view`): rejali ishlar (oxirgi ishga tushish, oxirgi muvaffaqiyat, xato kodi) va bajarilmagan event'lar (holat tablari, "Qayta yuborish" / "E'tiborsiz qoldirish" sabab bilan — `platform.dead_letter.replay`). Menyu va ⌘K'da ham bor.

### 9.3 Fayllar xaritasi

```
packages/auth/src/realtime.tsx            # RealtimeClient (ticket, seq, qayta ulanish, heartbeat nazorati, yashirin tab) + RealtimeProvider
packages/auth/src/provider.tsx            # AuthValue'ga baseUrl (WS manzili uchun)
packages/auth/src/account.tsx             # AccountScreen panelga xos kartalarni qabul qiladi
apps/shop-dashboard/src/lib/notify.ts      # so'rov kalitlari, vazifa matni, havola → panel manzili, resync
apps/shop-dashboard/src/components/realtime.tsx            # signal → qaysi so'rov eskirdi; yozib turilganda kartochka kechiktiriladi
apps/shop-dashboard/src/components/notification-bell.tsx   # qo'ng'iroqcha
apps/shop-dashboard/src/components/notify/{notification-settings,telegram-link}.tsx
apps/shop-dashboard/src/app/[shop]/tasks/page.tsx
apps/platform-admin/src/app/(admin)/jobs/page.tsx
e2e/{services.ts, fixtures.ts, global-teardown.ts, notifications.spec.ts}
```

### 9.4 Muhim qarorlar

- **Realtime klienti `@cos/auth` da**, signal → so'rov moslashi esa shop panelining o'zida (so'rov kalitlari panelga xos). Har tabda bitta ulanish, sahifalar almashganda qayta ochilmaydi.
- **Ma'lumot signaldan olinmaydi** — signal faqat "eskirdi" deydi, keyin REST. Takroriy signal (seq ≤ oxirgi) e'tiborsiz.
- **Yozib turgan matn sakramaydi**: ochiq buyurtma kartochkasi signal kelganda, foydalanuvchi forma maydonida bo'lsa, maydondan chiqqach yangilanadi; ro'yxatlar darhol.
- **Yashirin tab 5 daqiqadan keyin ulanishni yopadi**, qaytilganda qayta ulanadi va bo'shliq bo'lsa ro'yxatlar yangilanadi. Server 2,5 heartbeat davomida jim bo'lsa — ulanish o'lik deb qayta ulanadi.
- **"Menga / Biriktirilmagan" filtri yuklangan sahifalar ichida** (backend'da biriktirish filtri yo'q). Ega/menejer o'z a'zolik id'sini xodimlar ro'yxatidan topadi; boshqa rollar faqat o'ziga yoki o'z roliga tegishli vazifani ko'radi.
- **Telegram turlari faqat Telegram uchun o'chiriladi** — panelda bildirishnoma doim bor (backend `muted_types` ham faqat botga ta'sir qiladi).

### 9.5 E2E

- Worker'ni `global-setup` o'zi ishga tushiradi (`uv run python -m app.workers.dev`, e2e bazasi va e2e Redis bilan), `global-teardown` to'xtatadi. Playwright `webServer` emas — portsiz jarayon.
- Realtime ikki jarayon orasida Redis orqali o'tgani uchun e2e backend `RATE_LIMIT_BACKEND=redis` (backend'da realtime va kesh shu sozlamaga bog'langan). Dev Redis'ga tegmaydi: e2e db3 (kesh, chegaralar), db4 (navbat), db5 (realtime); yugurish boshida tozalanadi.
- Redis chegarasida `RATE_LIMIT_MEMORY_SCALE` ishlamaydi — shuning uchun har test oldidan `cos:v1:ratelimit:*` kalitlari o'chiriladi (`e2e/fixtures.ts`) va testlar bitta jarayonda (`workers: 1`): parallel testlar bitta IP'ning havola orqali kirish chegarasini (10/daq) birga to'ldirardi.
- Yangi testlar (`notifications.spec.ts`):
  1. Menejer buyurtmalar ro'yxatida → operator boshqa oynada tasdiqlaydi → menejerda holat qayta yuklamasdan "Tasdiqlandi"; omborchi tuzatish so'raydi → menejerning vazifalar sahifasida vazifa va qo'ng'iroqchada "1" jonli paydo bo'ladi; bildirishnoma → tuzatishlar sahifasi, son 0; vazifani o'ziga biriktiradi va "Bajarildi" (ikki marta bosish — bitta).
  2. Profil (390px): tinch soat juftligi xatosi, sozlamalar saqlanadi va qayta ochilganda (API'da ham) to'g'ri; muhim tur o'chirilmaydi; Telegram kodi `/start …`, qolgan vaqt, `t.me/cos_e2e_bot?start=…`; vazifalar sahifasi va qo'ng'iroqcha telefon eniga sig'adi.
  3. Platforma: "Fon ishlari" sahifasi ochiladi.
- Natija: `pnpm test:e2e` — 19/19 (16 eski + 3 yangi), ikki marta ketma-ket.

### 9.6 Backend uchun eslatmalar

- `GET /shop/tasks` da biriktirish filtri (`assignee=me|unassigned`) yo'q — frontend yuklangan sahifa ichida ajratadi; vazifa ko'p bo'lsa backend filtri kerak.
- `MeOut` da `membership_id` yo'q — "menga" uchun ega/menejer xodimlar ro'yxatidan topadi, boshqa rollarga bu kerak emas (ular faqat o'ziniki ko'radi).
- Redis so'rovlar chegarasida ko'paytirgich yo'q va realtime `rate_limit_backend` ga bog'langan — e2e buning uchun chegaralarni o'zi tozalaydi.

---

## 10. QA tekshiruvi va tuzatishlar (2026-10-26)

Mustaqil QA 5a backendini tekshirdi: jiddiy muammo yo'q, 4 ta o'rtacha (F1–F4), 7 ta kichik (F5–F11) va 7 ta kuzatuv (I1–I7). Frontend agenti 3 ta backend kamchiligini aytgan edi. Hammasi tuzatildi, har biriga test yozildi. Migratsiya kerak bo'lmadi.

### 10.1 O'rtacha topilmalar

- **F1 — dead-letter'ni qayta yuborish ishlamay qolardi.** Endi "Qayta yuborish" tinglovchini **darhol** navbatga qo'yadi (API'dan, `app/platform/jobs/services/queue.py`). Navbat ishlamasa — `outbox_reconcile` `REPLAYED` yozuvni event yoshidan qat'i nazar qayta qo'yadi (avval 1 kundan eskisi tushib qolardi). Event 14 kunlik saqlashdan keyin tozalangan bo'lsa — `409` (`reason: event_purged`), soxta "REPLAYED" yo'q. `outbox_cleanup` ochiq (`OPEN`) yoki oxirgi 1 kunda qayta yuborilgan dead-letter'li event'ni o'chirmaydi.
- **F2 — sozlamani parallel birinchi saqlash 500 berardi.** Yo'q qatorni `FOR UPDATE` qulflamaydi; endi `INSERT … ON CONFLICT DO NOTHING`: bittasi yozadi, qolganlari `409 VERSION_CONFLICT`.
- **F3 — mahsulot matni o'zgarsa sayt keshi eskirmasdi.** Yangi event'lar: `catalog.product.updated` (o'zgargan maydon nomlari), `catalog.sku.changed` (yaratildi / o'zgardi / arxivlandi), `catalog.media.changed` (rasm qo'shildi / olindi / tartibi). Sayt tinglovchisi ularda ham `index_version` ni oshiradi — ega saqlagani saytda darhol.
- **F4 — event tartibi uchun versiya ishlatib bo'lmasdi.**
  - `commerce.stock.changed` agregati — filial × SKU qatori: ID `uuid5(ns, "{branch_id}:{sku_id}")`, versiya — shu qator versiyasi.
  - Band event'lari endi har band uchun bitta, o'z agregati bilan (`commerce.reservation`, band versiyasi) — buyurtma versiyasi bilan to'qnashmaydi.
  - Buyurtma event'i yozilishidan oldin flush: `aggregate_version` — o'zgarishdan keyingi versiya.

### 10.2 Kichik topilmalar

- **F5 —** orqaga sanalgan (o'zi eskirgan) kurs "kurs eskirgan" vazifasini yopmaydi. Vazifa kaliti kun bo'yicha emas, oxirgi kurs vaqti bo'yicha: bitta eskirish davri — bitta vazifa, har kuni dublikat yo'q.
- **F6 —** uvicorn'ning `"WebSocket /api/v1/ws?ticket=…" [accepted]` xabari endi query'siz (`RedactQueryFilter`, `app/config/logging.py`).
- **F7 —** omborchi tasdiqlangan buyurtma bekor qilinganda ham signal oladi (`from_status` hisobga olinadi): ro'yxatida "arvoh" buyurtma qolmaydi. Operatorlar navbatidan olingan yoki tasdiqlangan buyurtma ham signal beradi.
- **F8 —** vazifani kim olishi va yopishi — tur bo'yicha (tasdiq vazifalari — ega va menejer; tasdiq eslatmasi — operator ham). So'rov egasi o'z tasdiq vazifasini ololmaydi va yopolmaydi (`params.requested_by`).
- **F9 —** yangi so'rov sxemalarida noma'lum maydon — 422 (`extra="forbid"`); `quiet_from` = `quiet_to` — 422; offset'li vaqt — 422; `muted_types` — faqat ma'lum shablon kalitlari va HIGH bo'lmaganlari.
- **F10 —** buyurtma event'lari 05 §8.2 bilan moslandi: `cancelled` va `exception` da `reason_code`; `completed` da `lines[]`; `confirmed` da `reservation_ids[]`; `paid_marked` da `marked_by`; saytdan kelgan buyurtma ham avval `drafted`. Shartnoma o'zgargan joylar 05 §8.2 da yozildi.
- **F11 —**
  - WS ticket — xodimga 30/daq;
  - bir xodimda ko'pi bilan 5 ulanish (Redis ZSET, eskirgan ulanish hisobga olinmaydi); oshsa yangi ulanish `4429` bilan yopiladi;
  - `/api/v1/shop/*` uchun umumiy limit 300/daq (xodim + shop, token imzosidan, bazasiz).

### 10.3 Kuzatuvlar

- **I1 —** WS handshake `Origin` ni tekshiradi: panel manzili bo'lmasa — rad (`1008`). Sarlavhasiz mijozga ruxsat (ticket baribir Bearer bilan olinadi).
- **I2 —** `/platform/jobs` hamma ro'yxatdagi ishni ko'rsatadi, hech ishlamaganini ham: jadval (`schedule`), taxminiy oraliq va `overdue` (3 × oraliq).
- **I3 —** bot parseri qat'iy: aynan `/start <kod>` (yoki `/start@bot <kod>`), ID — bool emas va int64 ichida.
- **I4 —** `staff.new_order` — HIGH (20 §8).
- **I5 —** `staff.task.assign` — haqiqiy ruxsat (ega, menejer), 10 §6 ga qo'shildi.
- **I6 —** `platform.shop.activated` / `suspended` / `closed` event'lari yoziladi (05 §8.6).
- **I7 —** ombor farqi vazifasi shop egasida qoladi; qo'shimcha ravishda `job_runs.details.alert` → `/platform/jobs` da `alert: true`.

### 10.4 Frontend so'ragani

- `GET /shop/tasks?assigned=me|unassigned|<membership_id>` — serverda filtr.
- `MeOut.membership_id` — joriy a'zolik (shop panelida).
- `RATE_LIMIT_SCALE` — Redis va xotira limiterida ishlaydi, faqat local/test (staging/production'da 1 dan katta bo'lsa ishga tushmaydi). Eski nomi `RATE_LIMIT_MEMORY_SCALE` ham o'qiladi.

### 10.5 Testlar

- `tests/integration/test_jobs_qa_fixes.py` — 20 ta: replay (darhol va 3 kun keyin), tozalangan event, parallel saqlash, kesh eskirishi, agregatlar, payload'lar, orqaga sanalgan kurs, omborchi signali, vazifa rollari, sozlama tekshiruvi, ticket limiti va ulanish chegarasi, Origin, `/shop` limiti, `/platform/jobs`, shop event'i, `assigned` filtri va `membership_id`.
- `tests/unit/test_jobs_qa_fixes.py` — 12 ta: log filtri, cron oralig'i, bot parseri, sozlama sxemasi, vazifa rollari, qoldiq agregati, ulanish chegarasi, `RATE_LIMIT_SCALE`.
- `make check`: **513 passed**, ruff, mypy, import-linter toza.

