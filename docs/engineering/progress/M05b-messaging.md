# 5b — Kanallar va yagona inbox: sayt chati, Telegram bot, xaridorga holat xabarlari

> **Holat:** backend bitdi (2026-10-26). Commit qilinmagan — founder ko'rib chiqishi kutilmoqda. Frontend (inbox, kanal sozlamalari, sayt chati vidjeti) parallel quriladi.
> **Reja:** [27-roadmap-and-tasks.md](../27-roadmap-and-tasks.md) — S2-01 (sayt chati), S2-02 (Telegram), S2-03 (inbox va operatorga uzatish), S2-04 (chiquvchi xabar va yetkazish), S2-05 (Instagram — flag ostida).
> **Baza:** [db/messaging.md](../db/messaging.md) (DEC-137, taklif), [db/notifications.md](../db/notifications.md) (`shop_message_templates`).
> **Kim o'qiydi:** founder va dasturchilar. 6-modul (AI sotuvchi) shu suhbatlar va fencing ustiga quriladi.

---

## 1. Nima bitdi — qisqacha

Xaridor saytdagi chatda yoki shopning Telegram botida yozadi — xabar panelda **bitta inbox**da paydo bo'ladi. Operator suhbatni oladi, javob yozadi, rasm biriktiradi, suhbatdan buyurtma qoralamasini ochadi yoki mavjud buyurtmaga bog'laydi. Buyurtma tasdiqlansa, tayyor bo'lsa, topshirilsa yoki bekor qilinsa — xaridorga shu kanal orqali **bir marta** xabar boradi.

```
Telegram ──webhook (yoki lokalda polling)──▶ provider_events (takror? → tashlanadi)
Sayt chati ──storefront API (cookie token)──▶       │
                                                    ▼
                          xaridor (customer_identities) ──▶ suhbat (conversations) ──▶ xabar (messages)
                                                    │
                     AI hali yo'q: suhbat ──▶ HUMAN_NEEDED ──▶ HANDOFF vazifasi + xodimlarga xabarnoma
                                                    │
Operator: olish ──▶ javob ──▶ messages (QUEUED) + outbox ──▶ channel_send ──▶ Telegram ──▶ SENT
                                                              │ 429/5xx ──▶ qayta (5 urinish) ──▶ FAILED + vazifa
                                                              └ timeout ──▶ UNKNOWN (qayta yuborilmaydi)
Buyurtma: confirmed / ready / completed / cancelled ──▶ order_status_notify ──▶ xaridorga bitta xabar
```

Panel tomonidan ko'rinadigani:

```
Inbox: ro'yxat (holat, kanal, mening / biriktirilmagan, o'qilmagan, teg, qidiruv) · hisoblagichlar
       suhbat: xabarlar lentasi, ichki izohlar, teglar, xaridor (telefon niqoblangan), buyurtmalar
       amallar: olish, biriktirish, yopish, qayta ochish, javob, rasm, buyurtma ochish / bog'lash
Sozlamalar: kanallar (sayt chati yoqish, bot tokeni bilan ulash, uzish) · xaridorga xabar matnlari
            (uz / ru / en, standartga qaytarish) · ish vaqti va eslatma daqiqasi (shop siyosati)
Realtime: yangi xabar, suhbat o'zgardi — sahifa o'zi yangilanadi (matn WS'da yo'q)
```

---

## 2. Rejadagi bandlar

- [x] **Baza** — `messaging` schemasidagi 9 jadval DBML bo'yicha (DEC-137): `channel_accounts`, `provider_events`, `customer_identities`, `conversations`, `messages`, `attachments`, `handoffs`, `conversation_notes`, `webchat_sessions`; outbox va `consumer_receipts`. Hammasi FORCE RLS; `channel_accounts` — "identity varianti" (webhook `account_ref` bilan topadi).
- [x] **Telegram adapteri** (S2-02):
  - ulash: `getMe` → token shifrlangan ustunda, webhook `setWebhook` + tasodifiy maxfiy so'z (bazada faqat xeshi);
  - webhook: maxfiy so'z doimiy vaqtda tekshiriladi, noto'g'ri bo'lsa `404`; guruh chati va bot xabarlari saqlanmaydi; takror update tashlanadi;
  - chiquvchi: `channel_send` tinglovchisi — 4096 belgidan uzun matn bo'linadi, 429 da `retry_after` hisobga olinadi, 5 urinishdan keyin `FAILED`, javobdan keyingi timeout — `UNKNOWN`;
  - lokal: `TELEGRAM_MODE=polling` (lokalda standart) — webhook o'rniga `getUpdates`, `make worker` ichida;
  - testlarda soxta klient (`FakeTelegramClient`), tarmoqqa chiqmaydi.
- [x] **Sayt chati** (S2-01): anonim sessiya (token — sayt domenidagi httpOnly cookie, sayt ilovasi `X-Chat-Session` bilan uzatadi), `/api/v1/storefront/{slug}/chat/*`, javoblar polling bilan (4 s). Faqat ochiq (LIVE) saytda. IP va sessiya bo'yicha chegaralar.
- [x] **Inbox API** (S2-03): ro'yxat va filtrlar, hisoblagichlar, suhbat, xabarlar (seq bo'yicha sahifalash), javob (Idempotency-Key), olish, biriktirish (o'tkazish ham shu), yopish, qayta ochish, o'qildi, teglar, izohlar, rasm biriktirish, buyurtma qoralamasi va bog'lash, realtime signallar.
- [x] **Operatorga uzatish**: `handoffs` qatori + `HANDOFF` vazifasi + `staff.handoff` xabarnomasi (HIGH); `handoff_reminder_minutes` dan keyin bir marta eslatma; ish vaqtidan tashqarida (`inbox_hours`) xaridorga "ish vaqtida javob beramiz" xabari va eslatma ish boshlanguncha kutadi.
- [x] **Fencing** (12 §8): `speaker_mode` + `speaker_version`; operator olsa versiya oshadi; AI javobi navbatga qo'yishda ham, yuborishda ham tekshiriladi, eskisi `DISCARDED` (6-modul uchun kirish nuqtasi `AiReplyService.queue`).
- [x] **Xaridorga holat xabarlari** (S2-04, 20): tasdiqlandi, olib ketishga tayyor (faqat PICKUP), topshirildi, bekor qilindi. Matnlar kodda (uz / ru / en), shop o'z matnini saqlay oladi (versiyali). Bir buyurtma holatiga bitta xabar (`intent_key`).
- [x] **Instagram** (S2-05) — `FEATURE_CHANNEL_INSTAGRAM_DM` flag ostida: adapter, imzo tekshiruvi, webhook, 24 soatlik oyna. Flag o'chiq — endpointlar `404`.
- [x] **Demo ma'lumot** — `make seed`: ochiq saytlarda sayt chati, NoutbukUz'da soxta bot va har holatdagi suhbatlar (biri buyurtmaga bog'langan).
- [x] **Testlar** — 31 integratsion + 8 unit (bazasiz), seed testi kengaytirildi.

**Ataylab keyinga qoldirilganlar:**
- AI javobi (`AI_ACTIVE` yo'li, `RETURN_TO_AI`, `resume-ai` endpointi) — 6-modul. Hozir AI o'chiq: har yangi suhbat darhol operatorga.
- Instagram OAuth (Meta ilovasi tekshiruvi) — hozir `POST /shop/channels/instagram` access token bilan (flag ostida, faqat test uchun).
- Ovozli xabar, fayl, stiker — saqlanadi (turi, davomiyligi), lekin yuklab olinmaydi (`UNSUPPORTED_TYPE`). Transkripsiya — DEC-112, DEC-117 bilan.
- Xaridor ma'lumotini o'chirish so'rovi (26 §3, erasure) — 7-modul bilan; hozir 12 oylik saqlash ishi bor.
- Telegram Business, tayyor javoblar — 11-bo'lim (db/messaging.md).

**Kartadan farqlar:**
- Sayt chati javoblari — SSE emas, polling (1-qaror, quyida).
- Endpoint nomlari 11-hujjatdagi rejadan farq qiladi: `…/takeover` o'rniga `…/take`; `resume-ai` yo'q; Instagram `oauth-start/callback` o'rniga bitta `POST`. 11-hujjat yangilandi.

---

## 3. Fayllar xaritasi

```
app/domains/messaging/
├── domain_manifest.py        routerlar, FSM qoidalari, ruxsatlar, tinglovchilar, rejali ishlar
├── permissions.py            ega / menejer / operator ruxsatlari
├── state_machine.py          FSM-04 (suhbat) va FSM-03 (kanal) qoidalari
├── common.py                 sozlama, adapterlar, yordamchilar (xesh, niqob, ish vaqti, event)
├── schemas.py                API sxemalari (inbox, kanal, sayt chati)
├── models/orm.py             9 jadval
├── channels/
│   ├── base.py               umumiy kontrakt: InboundMessage, SendResult, xato turlari
│   ├── telegram.py           HTTP va soxta klient, update'ni o'girish, matnni bo'lish
│   └── instagram.py          HTTP va soxta klient, imzo, webhook'ni o'girish
├── services/
│   ├── inbound.py            kiruvchi xabar: takror, xaridor, suhbat, FSM
│   ├── core.py               suhbat holati, olish, operatorga uzatish, ish vaqti xabari
│   ├── outbound.py           chiquvchi xabarni yozish (navbat, event)
│   ├── sending.py            tashqi yuborish, qayta urinish, rasm yuklab olish
│   ├── inbox.py              inbox amallari va buyurtma porti
│   ├── views.py              ro'yxat va suhbat ko'rinishi
│   ├── channels.py           kanal ulash va uzish
│   ├── webchat.py            sayt chati sessiyasi va xabarlari
│   ├── notify.py             xaridorga buyurtma holati xabari
│   └── ai_replies.py         AI javobi uchun fencing'li kirish (6-modul)
├── api/
│   ├── routes.py             /shop/conversations/*
│   ├── channel_routes.py     /shop/channels/*
│   ├── webhook_routes.py     /webhooks/telegram/{account_ref}, /webhooks/instagram
│   └── public_routes.py      /storefront/{slug}/chat/*
├── subscribers.py            channel_send, attachment_fetch, order_status_notify
├── jobs.py                   eslatma, osilib qolgan yuborish, saqlash muddati, tozalash
└── providers.py              servislarni yig'ish
app/platform/notifications/
├── customer_templates.py     xaridor matnlari (uz / ru / en), o'zgaruvchilar tekshiruvi
└── services/customer_templates.py   shop matni: saqlash, standartga qaytarish, tanlash
app/workers/telegram_polling.py      lokal long polling
app/db/seed/messaging_seed.py        demo kanallar va suhbatlar
app/db/migrations/messaging/versions/messaging_0002_messaging_tables.py
app/db/migrations/platform/versions/platform_0010_messaging_support.py
tests/integration/test_messaging.py
tests/unit/test_messaging_units.py
```

---

## 4. Qaysi faylda nima bor

### 4.1 Baza va migratsiyalar

- **`messaging_0002`** — 9 jadval, outbox va `consumer_receipts`. RLS: 8 jadvalda oddiy `shop_isolation`; `channel_accounts` da uch variant — `shop_id`, yoki `app.channel_account_ref` (Telegram webhook URL'idagi tasodifiy ref), yoki `app.channel_external_ref` (`INSTAGRAM:<sahifa id>`). Sabab: webhook kelganda shop hali noma'lum, SECURITY DEFINER esa FORCE RLS'ni chetlab o'tmaydi.
- **`platform_0010`** — `platform.shop_message_templates` (+ RLS) va `stored_files.purpose` ga `CHAT_ATTACHMENT`.
- DBML'dan farq: `handoffs.reminded_at` qo'shildi (eslatma bir marta ketishi uchun). Indekslar: xabar niyati unikal (`uq_messages_intent`), bitta kutayotgan AI javobi, navbatdagilar, provayder xabar ID'si, suhbatda bitta ochiq uzatish, kanal turidan bitta faol akkaunt.

### 4.2 Kanallar (`channels/`)

- **`base.py`** — hamma kanal bir xil ko'rinishga keladi: `InboundMessage` (dedup kaliti, xaridor, matn, kontakt, rasm). Yuborish xatosi — `ChannelSendError(code, retryable, unknown, retry_after)`: 429/5xx/tarmoq — qayta; javobdan keyingi timeout — "noma'lum", qayta yuborilmaydi (06 §4.2); 403 — xaridor botni bloklagan; 401 — token bekor.
- **`telegram.py`** — `parse_update`: matn, rasm (eng kattasi), ovoz, fayl, stiker, kontakt (faqat **o'z** raqami qabul qilinadi), tahrir; `/operator` buyrug'i — "operator kerak". `split_text` — 4096 belgidan bo'lish. `HttpTelegramClient` — haqiqiy API; `FakeTelegramClient` — testlar va seed.
- **`instagram.py`** — `X-Hub-Signature-256` tekshiruvi, echo xabarlar tashlanadi, `WINDOW_HOURS = 24`.

### 4.3 Kiruvchi yo'l (`services/inbound.py`, `core.py`)

- **`InboundService.ingest`** — webhook, polling va sayt chati shu bitta funksiyadan o'tadi:
  1. `provider_events` ga `ON CONFLICT DO NOTHING` — takror bo'lsa shu yerda tugaydi;
  2. xaridor topiladi yoki yaratiladi (ism, username, til; telefon — shifrlangan + HMAC);
  3. suhbat topiladi yoki yaratiladi va qulflanadi (`FOR UPDATE`), xabar `seq` raqami oladi;
  4. rasm bo'lsa — `attachments` (`PENDING`), keyin `attachment_fetch` yuklab oladi;
  5. FSM-04: AI o'chiq bo'lgani uchun yangi yoki yopilgan suhbat → `HUMAN_NEEDED`, `speaker_mode = PAUSED`; operator suhbatida — `HUMAN_ACTIVE` qoladi;
  6. `messaging.message.received` event'i (matnsiz).
- **`ConversationCore`** — holat o'tishlari (USE: `validate_transition` + `transition_log`), olishda `speaker_version` +1, `open_handoff` (uzatish qatori, vazifa, xabarnoma, event; ish vaqtidan tashqarida xaridorga bitta xabar `after_hours:{handoff_id}`), `close_handoff`.

### 4.4 Chiquvchi yo'l (`outbound.py`, `sending.py`)

- **`MessageWriter.append_outbound`** — xabar `QUEUED` bo'lib yoziladi va `messaging.message.queued` event'i outbox'ga tushadi (bitta tranzaksiya). Sayt chati uchun tashqi chaqiruv yo'q — xabar darhol `SENT`.
- **`SendingService.send`** — uch qadam: tayyorlash tranzaksiyasi (`SENDING`, urinish +1) → tashqi chaqiruv (tranzaksiyasiz) → natija tranzaksiyasi. Natijalar:
  - muvaffaqiyat — `SENT`, provayder ID'si;
  - qayta urinish — `RetryLater` (arq), 5 urinishdan keyin `FAILED` + `MESSAGE_FAILED` vazifasi + `staff.message_failed` xabarnomasi;
  - timeout — `UNKNOWN`;
  - bloklangan — `customer_identities.blocked_at`, keyingi xabarlar navbatga qo'yilmaydi;
  - token bekor — kanal `DEGRADED` (FSM-03) + `CHANNEL_DEGRADED` vazifasi (egaga);
  - AI xabari — yuborishdan oldin `speaker_version` qayta tekshiriladi;
  - soxta akkaunt (seed) — tashqariga chiqmasdan `SENT`.
- **`fetch_attachments`** — faqat rasmlar, `CHAT_ATTACHMENT` maqsadi bilan fayl omboriga (`FileService.store_system`); boshqa turlar `FAILED UNSUPPORTED_TYPE`.
- **`mark_stuck_unknown`** — 5 daqiqadan beri `SENDING` bo'lsa `UNKNOWN`.

### 4.5 Inbox (`inbox.py`, `views.py`)

- **Doira:** ega va menejer — hammasi; operator — o'ziga biriktirilgan va biriktirilmagan suhbatlar; omborchi — umuman ko'rmaydi. Boshqa operatorning suhbati — `403` + `reason: other_operator` (QA 5b L3; boshqa shop — `404`).
- **Javob** — yopilgan suhbat o'zi qayta ochiladi (`REOPEN`), suhbat hali operatorniki bo'lmasa — olinadi (`TAKE_OVER`, ochiq uzatish `TAKEN`), keyin `WAITING_CUSTOMER`; o'qilgan deb belgilanadi.
- **Biriktirish** — menejer yoki ega; yangi mas'ulga `HANDOFF` vazifasi qayta ochiladi.
- **O'qildi** — versiyani oshirmaydi (If-Match talab qilinmaydi).
- **Qidiruv** — ism, username, telefon (HMAC orqali — telefon ochiq qidirilmaydi).
- **Buyurtma** — `ConversationOrdersPort` (commerce kodi import qilinmaydi, ADR-032): qoralama xaridor ismi, telefoni va tili bilan ochiladi; bog'lashda topshirilgan yoki bekor qilingan buyurtma rad etiladi.
- **`views.py`** — o'qilmaganlar soni, oxirgi xabar, mumkin bo'lgan amallar (`allowed_actions`), xaridor (telefon niqoblangan: `+99890 *** ** 67`), rasmlar uchun imzolangan havola.

### 4.6 Sayt chati (`webchat.py`, `api/public_routes.py`)

- Sessiya: `token_urlsafe(32)`, bazada faqat sha256, 30 kun (har faollikda suriladi). Har sessiya — alohida mehmon (`v_<tasodifiy>`).
- Xabar dedup kaliti — `{session_id}:{client_message_id}` (klient takror yuborsa ham bitta xabar).
- `contact` — mehmon ism va telefon qoldiradi (telefon shifrlangan).
- Chegaralar: sessiya ochish — IP bo'yicha 10/soat; o'qish — 60/daq; yozish — IP bo'yicha 20/daq va sessiya bo'yicha 10/daq.

### 4.7 Xaridorga xabar matnlari

- **`customer_templates.py`** — `customer.order_confirmed`, `customer.order_ready_pickup`, `customer.order_completed`, `customer.order_cancelled`, `customer.handoff_after_hours`; har birida majburiy va ruxsat etilgan o'zgaruvchilar (`order_number`, `total`, `address`, `phone` …). Shop matnida majburiy o'zgaruvchi yo'q yoki noma'lum o'zgaruvchi bor — `422`.
- **`CustomerTemplateService`** — shop matni versiyali (eskisi o'chirilmaydi, faol emas bo'ladi), audit bilan; `reset` — standartga qaytarish.
- **`notify.py`** — buyurtma event'idan keyin: suhbat bor va xaridorga yetib borsa (kanal ulangan, bloklanmagan, Instagram oynasi ochiq) — xaridor tilida bitta xabar. Summa: `4 800 000 so'm`, `4 800 000 сум`, `UZS 4,800,000`.

### 4.8 Platforma va boshqa domenlardagi o'zgarishlar

- `platform/storage` — `CHAT_ATTACHMENT` maqsadi, `store_system` (tizim yuklashi, ruxsatsiz), `read_bytes`.
- `platform/notifications` — xodim shablonlari `staff.handoff`, `staff.handoff_reminder`, `staff.message_failed`; vazifa turlari `HANDOFF`, `MESSAGE_FAILED`, `CHANNEL_DEGRADED`; havola turlari `conversation`, `channels`; `/shop/message-templates` endpointlari.
- `platform/shops` — siyosatda `handoff_reminder_minutes` va `inbox_hours` (kunlar, boshlanish, tugash; bo'sh — doim ish vaqti) API'ga chiqarildi.
- `platform/realtime` — `messaging.*` event'lari: `message.created` va `conversation.changed` signallari mas'ulga, oldingi mas'ulga, ega va menejerga (biriktirilmagan yoki operator kutayotgan bo'lsa — operatorlarga ham).
- `commerce` — buyurtmada `conversation_id` (yaratishda va `link_conversation`), `for_conversation`; buyurtma event'larida `conversation_id`.
- `app/workers/dev.py` — polling rejimida Telegram tsikli ham ishga tushadi.

---

## 5. Testlar

`make check` — yashil (ruff, mypy, import-linter, arxitektura testlari, hamma testlar). Yangi: `tests/integration/test_messaging.py` — 31, `tests/unit/test_messaging_units.py` — 8; seed testi (`test_platform_team_notes.py`) — messaging qismi qo'shildi.

Tekshirilgan holatlar:
- bot ulash: token shifrlangan, webhook maxfiy so'zi faqat xesh; noto'g'ri token — `422`; boshqa shopdagi bot — `already_connected`; boshqa bot ulansa eskisi `REPLACED`, uzish;
- webhook: noto'g'ri maxfiy so'z — `404`, takror update — bitta xabar, guruh chati saqlanmaydi;
- birinchi xabar → `HUMAN_NEEDED`, vazifa va xabarnoma; `/operator` buyrug'i;
- javob → worker yuboradi → `SENT`; takror Idempotency-Key — bitta xabar; 429 → qayta urinish; 5 xato → `FAILED` + vazifa; timeout → `UNKNOWN`; bloklangan xaridor;
- FSM: yopish, qayta ochish, yopilgan suhbatga javob; fencing — operator olgandan keyin AI javobi `DISCARDED`;
- kontakt, rasm, ovoz, tahrir; rasm yuklab olinadi;
- doira: operator boshqa suhbatni ko'rmaydi, biriktirish, omborchi kira olmaydi; boshqa shop — `404`; izoh, teg, o'qildi;
- Instagram flag o'chiq — `404`;
- sayt chati: boshqa shop sessiyasi ishlamaydi, operator javobi mehmonga ko'rinadi, sayt ochiq bo'lmasa — yopiq, so'rov chegarasi;
- buyurtma holati xabari: bir marta, xaridor tilida (ru), shop matni bilan, event qayta kelsa ham takrorlanmaydi; suhbatdan buyurtma va bog'lash; matnlar API;
- event, audit va log'da PII yo'q (skaner);
- eslatma (bir marta), ish vaqtidan tashqari xabar, saqlash muddati va tozalash ishlari, osilib qolgan yuborish;
- kontekstsiz so'rov RLS bilan hech narsa ko'rmaydi; polling.

---

## 6. Jarayonda topilgan muammolar

- **Bir bot bir nechta testda** — bot unikal indeksi to'qnashdi. Har test o'z boti bilan (`_bot()`).
- **`ARRAY.contains` ishlamadi** — umumiy `ARRAY` o'rniga PostgreSQL `ARRAY` turi.
- **Avtogeneratsiya `EncryptedString` ni migratsiyaga yozdi** — `sa.Text()` ga almashtirildi.
- **CHECK nomi ikki marta prefiks oldi** — `op.f("ck_stored_files_purpose")`.
- **SECURITY DEFINER FORCE RLS'ni chetlab o'tmaydi** — Instagram webhook uchun `app.channel_external_ref` varianti qo'shildi.
- **`list` nomli metodlar mypy'da builtin'ni yashirdi** — `list_accounts`, `list_conversations`.
- **Seed faqat birinchi marta ishlardi** — dev bazada frontend sinovi suhbat yaratgan edi; himoya "Telegram akkaunti bormi" ga o'zgartirildi.

---

## 7. Keyingi modulga meros

- **6-modul (AI sotuvchi):** `AiReplyService.queue(..., speaker_version=...)` — yagona kirish; `speaker_version` ni har AI ishining boshida oling va o'zgartirmang. AI yoqilganda `ConversationCore(ai_enabled=True)` — yangi suhbat `AI_ACTIVE` ga ketadi. `RETURN_TO_AI` va `resume-ai` endpointi shu modulda.
- **Kanal qo'shish** (Instagram izohlari, Telegram Business): `channels/` da adapter + `InboundMessage` ga o'girish; inbox o'zgarmaydi.
- **Xaridorga yangi xabar turi:** `CUSTOMER_TEMPLATES` ga kalit + `notify.py` dagi `ORDER_TEMPLATES`; niyat kaliti doim deterministik (`order:{id}:{status}` kabi).
- **Qoida:** xabar matni, telefon va ism event payload'iga, audit diff'iga va log'ga tushmaydi — xabar ID'si `aggregate_id` da yuradi.

---

## 8. Frontend uchun eslatmalar

- **Inbox:** `GET /api/v1/shop/conversations?status=HUMAN_NEEDED,HUMAN_ACTIVE&assigned=me|unassigned|<membership_id>&unread=true&channel=&tag=&q=&cursor=&limit=`; `GET …/counts`; suhbat — ETag, amallar `If-Match` bilan (`take`, `assign`, `resolve`, `reopen`, `PUT tags`); `allowed_actions` bo'yicha tugmalar. Xabarlar: `GET …/{id}/messages?after_seq=` (yangilar) yoki `before_seq=` (eskilar). Javob — `POST …/{id}/messages` + `Idempotency-Key` (`body` yoki `attachment_file_id`; rasm avval `/shop/files` ga `CHAT_ATTACHMENT` bilan). Realtime: `message.created` (`resource.id` — xabar, `conversation_id`), `conversation.changed` — kelganda tegishli so'rovni qayta yuboring.
- **Sayt chati vidjeti:** `POST /storefront/{slug}/chat/sessions` → `{token, expires_at, poll_interval_seconds}`; tokenni sayt ilovasi httpOnly cookie'da saqlaydi va har so'rovda `X-Chat-Session` header'i bilan API'ga uzatadi. `GET …/chat/messages?after_seq=` har `poll_interval_seconds` da; `POST …/chat/messages {client_message_id (8–64 belgi, brauzer yaratadi), body}`; `POST …/chat/contact {name, phone}` → `204`. `404` — sessiya eskirgan, yangisini oling; javobdagi `state` — chat holati (ochiq yoki yopiq); sayt ochiq bo'lmasa yoki chat yoqilmagan bo'lsa so'rov rad etiladi.
- **Kanal sozlamalari:** `GET /shop/channels`; `POST /shop/channels/webchat`; `POST /shop/channels/telegram {token}` + `Idempotency-Key` (faqat ega); `POST /shop/channels/{id}/disconnect` (`If-Match`); `is_fake` — seed akkaunti belgisi. Xaridor matnlari: `GET/PUT/DELETE /shop/message-templates/{key}/{locale}`. Ish vaqti: `PATCH /shop/policies {inbox_hours, handoff_reminder_minutes}`.

---

## 9. Frontend (2026-10-26)

### 9.1 Nima bitdi — qisqacha

Operator endi Telegram, Instagram va saytdagi chat suhbatlarini bitta "Suhbatlar" bo'limida ko'radi va javob beradi. Saytda pastki burchakda chat tugmasi paydo bo'ldi. Ega "Kanallar" bo'limida bot ulaydi, sayt chatini yoqadi va xaridorga ketadigan matnlarni o'zgartiradi.

```
Mehmon saytda yozadi ──▶ sayt serveri (token httpOnly cookie'da) ──▶ backend ──▶ realtime signal
   ──▶ operator ro'yxatida qayta yuklamasdan paydo bo'ladi ──▶ "Suhbatni olish" ──▶ javob (Enter)
   ──▶ mehmon javobni polling bilan ko'radi (4 soniyagacha)
Suhbatdan "Buyurtma yaratish" ──▶ buyurtma sahifasi ──▶ tasdiqlanganda xaridorga suhbat kanali orqali holat xabari
```

### 9.2 Sahifalar

- **`/[shop]/inbox`** (`messaging.conversation.view`; operator — o'ziniki va biriktirilmagan, menejer va ega — hammasi):
  - chapda ro'yxat: qidiruv (ism, @username, telefon), "Hammasi / Menga / Biriktirilmagan" (soni bilan), "Ochiq / Yopilgan / Hammasi", kanal, "O'qilmagan", teg; o'qilmaganlar belgisi, oxirgi xabar, holat; "Ko'proq yuklash";
  - menyuda "Suhbatlar" yonida o'qilmaganlar soni.
- **`/[shop]/inbox/[id]`** — suhbat:
  - sarlavha: xaridor, kanal, holat, mas'ul, "Javob kutmoqda" vaqti; tugmalar faqat `allowed_actions` bo'yicha (olish, boshqaga berish, yopish, qayta ochish);
  - operator nega kerakligi — sabab kodi tarjima qilinadi (`AI_UNAVAILABLE` → "Yangi murojaat — operator javob beradi"), xom kod ko'rinmaydi;
  - lenta: xabarlar `seq` bo'yicha, ichki izohlar (sariq, chiziqli) vaqt bo'yicha aralash, kun ajratgichlari; yuqoriga — "Avvalgi xabarlar" (ko'rinish joyida qoladi); pastda turgan bo'lsa yangi xabarda pastga tushadi;
  - yetkazish holati: navbatda (soat), yuborildi (ikki belgi), yuborilmadi (qizil + "qayta yozib ko'ring"), noma'lum (ogohlantirish);
  - rasmlar — imzoli havola bilan; yuklanmoqda / olinmadi holatlari;
  - javob maydoni: Enter — yuborish, Shift+Enter — yangi qator; "Xaridorga javob" / "Ichki izoh" rejimlari; bitta rasm (JPG/PNG/WebP, 5 MB); yuborilayotgan xabar darhol ko'rinadi, yuborilmasa "Qayta urinish" (o'sha kalit bilan — takror xabar bo'lmaydi) yoki "O'chirish";
  - kanal ulanmagan yoki xaridor bloklagan bo'lsa — javob maydoni sababi bilan yopiq;
  - o'ng ustun (keng ekranda) yoki "i" tugmasi: xaridor (ism, username, telefon, til, rozilik vaqti), teglar (qo'shish/olib tashlash), bog'langan buyurtmalar, "Buyurtma yaratish" (olish usuli va filial) va "Mavjud buyurtmani bog'lash" (raqami bo'yicha);
  - ochiq va ko'rinib turgan suhbat "o'qildi" bo'ladi; boshqa operatorning suhbati — "Ruxsat yo'q".
  - Telefonda: ro'yxat → suhbat → orqaga, alohida ekranlar.
- **`/[shop]/channels`** (`messaging.channel.view`; ulash — faqat ega):
  - Telegram: token (format brauzerda tekshiriladi), ulash / boshqa bot, rejim (webhook yoki lokal polling), bot nomi, oxirgi xabar va xato, "muammo bor" ogohlantirishi, sinov akkaunti belgisi, uzish (tasdiq bilan);
  - sayt chati: yoqish / uzish; Instagram — "Meta ruxsati kutilmoqda";
  - "Xaridorga xabarlar": har holat va har til uchun standart yoki shop matni; tahrirlash (majburiy va ruxsat etilgan o'zgaruvchilar ko'rsatiladi, xato — maydon ostida), "Standartga qaytarish".
- **`/[shop]/settings`** — yangi qism "Suhbatlar va operatorlar": operator kutilganda eslatma (daqiqa) va operatorlar ish vaqti (kunlar, boshlanish, tugash — tungi smena ham).
- **Sayt (`apps/shop-storefront`)** — chat vidjeti: pastki burchakdagi tugma → panel (telefonda — pastdan chiqadigan oyna). Sayt ochiq bo'lmasa yoki ko'rib chiqish rejimida — tugma yo'q.

### 9.3 Fayllar xaritasi

```
apps/shop-dashboard/src/
├── lib/inbox.ts                          turlar, so'rov kalitlari, filtrlar, holat ranglari, kanal belgilari
├── components/inbox/
│   ├── conversation-list.tsx             ro'yxat va filtrlar
│   ├── conversation-view.tsx             suhbat: sarlavha, amallar, lenta, javob, o'qildi
│   ├── message-list.tsx                  lenta (xabar, izoh, yuborilayotgan xabar)
│   ├── composer.tsx                      javob / izoh maydoni, rasm
│   ├── conversation-details.tsx          xaridor, teglar, buyurtmalar
│   ├── conversation-dialogs.tsx          boshqaga berish, buyurtma yaratish, bog'lash
│   ├── customer-templates.tsx            xaridorga xabar matnlari
│   └── inbox-badge.tsx                   menyudagi o'qilmaganlar soni
├── app/[shop]/inbox/{layout,page}.tsx, inbox/[id]/page.tsx
├── app/[shop]/channels/page.tsx
├── app/[shop]/settings/page.tsx          (+ ish vaqti, eslatma)
├── components/realtime.tsx               (+ conversation.changed, message.created)
├── components/shell.tsx                  (+ inbox uchun to'liq kenglik, belgi)
└── lib/nav.ts                            (+ "Suhbatlar", "Kanallar")
apps/shop-storefront/src/
├── components/chat-widget.tsx            vidjet: panel, polling, yuborish, aloqa formasi
├── app/[site]/chat-api/[action]/route.ts server proksi: cookie ↔ X-Chat-Session
└── app/[site]/(shop)/layout.tsx          (+ vidjet)
packages/i18n — ~240 ta yangi kalit (uz/ru/en); `fieldErrorText` ro'yxat parametrlarini vergul bilan ko'rsatadi
packages/auth/src/realtime.tsx            signal turiga `conversation_id`, `branch_id`
e2e/messaging.spec.ts                     2 ta yangi test
```

### 9.4 Muhim qarorlar

- **Chat sessiyasi faqat yozganda ochiladi.** Mehmon sahifani ochganda backend'ga so'rov ketmaydi; birinchi xabarda sayt serveri sessiya oladi va cookie'ga yozadi. Shunda IP bo'yicha soatlik sessiya chegarasi bekorga sarflanmaydi.
- **Token brauzerga hech qachon tushmaydi:** `cos.chat` — httpOnly, SameSite=Lax; sayt proksisi boshqa saytdan kelgan POST'ni (`Origin` mos emas) rad etadi. Sessiya eskirsa (`404`) — yangisi olinib, so'rov bir marta qayta yuboriladi (`client_message_id` takrorni ushlaydi).
- **Polling:** panel ochiq — backend aytgan oraliqda (hozir 4 s), yopiq va sessiya bor — 30 s (yangi javob belgisi uchun), tab yashirin — to'xtaydi.
- **Lenta yangilanishi** — `message.created` signalida xabarlar so'rovi qayta olinadi (yuklangan sahifalar bilan). Oddiy suhbatlarda bu arzon va doim to'g'ri tartibda.
- **Yuborilayotgan javob** — har urinishning o'z `Idempotency-Key` i (rasm uchun `…-file`). Qayta urinish o'sha kalit bilan, javob yo'qolsa ham takror xabar bo'lmaydi.
- **Inbox sahifasi to'liq kenglikda** (qolgan sahifalar 5xl chegarada qoladi): ro'yxat + suhbat + o'ng ustun bir ekranda.

### 9.5 Tekshiruv

- `pnpm check` (typecheck + lint) — toza; uchala production build e2e ichida.
- `pnpm test:e2e` — 21/21 (19 eski + 2 yangi):
  - **sayt chati:** mehmon yozadi (token faqat httpOnly cookie'da) → operator ro'yxatida jonli, o'qilmaganlar belgisi → oladi → ichki izoh (mehmonga ko'rinmaydi) → javob (ikki Enter — bitta xabar) → mehmon javobni ko'radi → aloqa formasi (rozilik majburiy) → suhbatdan buyurtma → tasdiqlanganda mehmon chatida `#raqam` bilan holat xabari; CSP xatosi yo'q;
  - **kanallar va ruxsatlar:** sayt chatini yoqish, Instagram belgisi, noto'g'ri token, xaridor matni (majburiy o'zgaruvchi xatosi, saqlash, standartga qaytarish), sozlamalarda ish vaqti va eslatma, ikkinchi operator boshqaning suhbatini ko'rmaydi va "Kanallar"ga kira olmaydi, telefonda ro'yxat → suhbat → orqaga, 390px da gorizontal aylantirish yo'q.
- Dev'da qo'lda: NoutbukUz'da sayt chati yoqildi (seed ham shuni qiladi), mehmon → operator → mehmon zanjiri ishladi; sinov suhbatlari yopildi.

### 9.6 Backend uchun ochiq masalalar

- **`PublicSite` da `chat_enabled` yo'q.** Sayt tugmani har doim ko'rsatadi; chat o'chiq bo'lsa, mehmon birinchi yozganda `CHANNEL_UNAVAILABLE` keladi va tugma yashiriladi. `chat_enabled` qo'shilsa, tugma umuman chiqmaydi (frontend maydonni allaqachon o'qiydi).
- **Mehmon ism/telefon qoldirganda signal yo'q** (`webchat.contact` `conversation.changed` yozmaydi) — operator ma'lumotni sahifani yangilagach ko'radi.
- **Telegram ulashning test rejimi yo'q** — e2e soxta token bilan faqat xato holatini tekshiradi; haqiqiy ulash qo'lda (bot tokeni bilan).
- **Buyurtmani raqami bo'yicha bog'lash** — alohida endpoint yo'q, frontend `GET /shop/orders?q=` dan aniq raqamni topadi.

## 10. QA tekshiruvi va tuzatishlar (2026-10-26)

Mustaqil QA 5b ni tekshirdi: 1 ta jiddiy (H1), 5 ta o'rtacha (M1–M5), 8 ta kichik (L1–L8) va kuzatuvlar. Frontend agenti 4 ta backend kamchiligini aytgan edi (a–d). Hammasi tuzatildi, har biriga test yozildi.

### 10.1 Jiddiy — H1: shop matni shablonidan in'ektsiya

- **Muammo:** `{0}`, `{hours.__class__}`, `{order_number:0>999999999}` yoki yolg'iz `}` tekshiruvdan o'tardi; render `str.format_map` bilan edi. Natija: ish vaqtidan tashqari eslatma 500 berardi va **xaridorning kiruvchi xabari yo'qolardi**, format bilan matnni gigabaytgacha "portlatish" mumkin edi.
- **Tuzatish (`app/platform/notifications/customer_templates.py`):**
  - matn `string.Formatter().parse` bilan bo'laklanadi; ruxsat faqat `{nom}` (ma'lum o'zgaruvchi). Yolg'iz qavs — `invalid_braces`; pozitsion, atribut/indeks, konversiya, format — `invalid_placeholder` (422). `{{` va `}}` — oddiy qavs;
  - render o'z almashtiruvchimiz bilan (format_map emas), natija 1500 belgigacha;
  - `safe_render` — xato bo'lsa standart matn (o'sha tilda) va ogohlantirish logi (matnsiz);
  - ish vaqtidan tashqari eslatma `SAVEPOINT` ichida, xato bo'lsa ham kiruvchi xabar saqlanadi (BL-032);
  - `platform_0011` migratsiyasi avval saqlangan noto'g'ri matnlarni faolsizlantiradi (shop standart matnga qaytadi).

### 10.2 O'rtacha

- **M1 — til:** sayt chatida mehmon tili `X-Customer-Locale` (sayt serveri `cos.locale` cookie'sidan) yoki `Accept-Language` bilan keladi va suhbat/xaridor yozuviga yoziladi (sayt chatida — joriy til). Buyurtma xabari tili: buyurtmaning `customer_locale` (event'ga qo'shildi) → suhbat tili → uz. Telegram — `language_code` (avvaldan).
- **M2 — rasm mehmonga:** sayt chati so'rovida rasmli xabarga qisqa muddatli imzoli `image_url` (5 daq) qaytadi; vidjet rasmni ko'rsatadi (CSP `img-src` backend manzilini allaqachon ruxsat qiladi).
- **M3 — buyurtmani boshqa suhbatga ko'chirish:** jim ko'chirilmaydi — `409 ORDER_LINKED_ELSEWHERE` (`details.order_version`). Ko'chirish — `relink: true` + `expected_version`; eski suhbatning `last_order_id` qolgan buyurtmaga yoki bo'shga o'tadi, ikkalasiga signal. Bog'lash endpointi endi `Idempotency-Key` bilan. Panel ko'chirishni tasdiqlatadi.
- **M4 — ish vaqti:** `start == end` — 422 `invalid_range`; takror kunlar olib tashlanadi (`[1,1,3]` → `[1,3]`); tungi smena (`22:00–06:00`) — ruxsat. Bazadagi eski `09:00–09:00` — "doim ish vaqti" deb hisoblanadi.
- **M5 — yuborilgan xabar "noma'lum":** `messages.sending_started_at` (`messaging_0003`): "osilib qolgan" — shu vaqtdan 5 daqiqa; rejali ish `UNKNOWN` qilgandan keyin kanal "qabul qildi" desa — `SENT`.

### 10.3 Kichik

- **L1:** Telegram parseri turlarni qat'iy tekshiradi (`username`, `language_code`, `file_size`, `file_id`, ism); kutilmagan xato — 200 va e'tiborsiz (Telegram qayta-qayta yubormaydi).
- **L2:** navbatdagi suhbat olinganda yoki biriktirilganda (`left_queue`) hamma operator signal oladi — "arvoh" qator qolmaydi.
- **L3:** boshqa operatorning suhbati — `403` + `reason: other_operator` (buyurtmalardagi bilan bir xil; boshqa shop — `404`). Hujjat (§4.5, engineering/10) moslandi.
- **L4:** sayt chati o'chirib qayta yoqilganda eski suhbatlar va mehmon sessiyalari yangi akkauntga o'tadi.
- **L5:** mehmon kontaktida `notice_version` (sayt rozilik matni versiyasi) yoziladi; ism ham telefon ham yo'q rozilik — 422.
- **L6:** suhbat ro'yxati va kartochkasida `assignee_name`; operator `/shop/members` ni chaqirmaydi (ro'yxat faqat biriktira oladiganlarga).
- **L7:** telefoni yo'q filialda "Tel: ." chiqmaydi (`{phone_line}`); ro'yxatda SYSTEM xabarga "siz:" qo'yilmaydi (`last_message.author_type`); soxta bot nomida "(soxta)" yo'q — belgi `is_fake` bilan.
- **L8:** bo'laklab yuborishda `messages.parts_sent`: qayta urinish to'xtagan bo'lakdan davom etadi. Rasm izohi 1024 belgidan uzun — izohga birinchi bo'lak, qolgani rasmdan keyin matn.

### 10.4 Kuzatuvlar va frontend so'ragani

- Sayt chati so'rovi sessiyani qulflamaydi va muddatni daqiqada bir suradi (har 4 soniyada yozuv yo'q). O'qish chegarasi — 120/daq per IP + sessiya.
- Production'da `STOREFRONT_TRUSTED_PROXY_HOPS=1` majburiy (engineering/22). Sayt CSP'sida `'unsafe-eval'` faqat dev rejimda.
- **(a)** `GET /storefront/{slug}/site` → `chat_enabled` (`ChatAvailabilityPort`, storefront messaging'ni import qilmaydi).
- **(b)** mehmon kontakti saqlanganda `messaging.conversation.contact_updated` — operator ekrani yangilanadi.
- **(c)** local/test: `900000001:TEST…` tokeni — soxta bot (tarmoqsiz), e2e Telegram ulashni sinaydi.
- **(d)** `GET /shop/orders?number=1042` — aniq raqam.

### 10.5 Testlar

- `tests/integration/test_messaging_qa_fixes.py` — 23 ta (H1 parametrlari bilan); `tests/unit/test_messaging_qa_fixes.py` — 17 ta.
- E2E (`messaging.spec.ts`): yolg'iz qavsli shablon — xato; Telegram test tokeni — "Ulangan"; mehmon rasmni ko'radi; ruscha sayt — suhbat tili `ru`; mehmon kontakti operatorga qayta yuklamasdan.

## Founder ko'rib chiqishi uchun qarorlar

Founder ishni to'xtatmasdan davom ettirishni va eng yaxshi variantni tanlashni topshirgan. Quyidagi qarorlar shu asosda qabul qilingan va kodda shunday qurilgan. O'zgarsa, kod moslanadi.

**1. Sayt chatida javoblar polling bilan keladi (har 4 soniya), SSE emas.**
- Nega: token sayt ilovasi orqali uzatiladi (DEC-137, 4-qaror) — oddiy so'rovlar Next.js orqali oson o'tadi, uzun oqim esa har proxy va hostingda alohida sozlash talab qiladi. Chat trafigi kichik.
- Muqobil: SSE (db/messaging.md dagi reja). Afzallik — javob darhol ko'rinadi, so'rovlar kam. Kamchilik — proxy, timeout va qayta ulanish murakkabligi.

**2. Lokalda Telegram — long polling, production'da — webhook.**
- Nega: lokal kompyuterda ochiq HTTPS manzil yo'q; polling bilan founder haqiqiy botni hech qanday tunnel'siz sinaydi. Ikkalasi bir xil kod yo'lidan o'tadi.
- Muqobil: lokalda ham webhook (ngrok kabi tunnel bilan). Kamchilik — har safar tunnel va manzil sozlash.

**3. AI yoqilmaguncha har yangi suhbat darhol operatorga (`HUMAN_NEEDED`).**
- Nega: xaridor javobsiz qolmasin; AI 6-modulda keladi. `speaker_mode = PAUSED` — "hozir hech kim javob bermayapti" (12 §8).
- Muqobil: suhbat `NEW` holatida kutadi. Kamchilik — operator chaqirilmaydi, xaridor kutib qoladi.

**4. FSM-04 ga qo'shimcha strelkalar.**
- Tanlov: operator suhbatni `AI_ACTIVE`, `WAITING_CUSTOMER` va `REOPENED` dan ham oladi; `WAITING_CUSTOMER`, `HUMAN_NEEDED`, `REOPENED` dan ham yopadi; xodim qayta ocha oladi; yopilgan suhbatga javob yozilsa — o'zi qayta ochiladi.
- Nega: inbox'da "javob kutilmoqda" yoki "operator kerak" suhbatini yopish va olish odatiy ish; aks holda tugma bor-u, amal yo'q.
- **business/05 ga shu strelkalarni qo'shishni founder tasdiqlashi kerak.**

**5. Xaridorga holat xabari — faqat suhbat bor bo'lsa va shu kanal orqali.**
- Tanlov: buyurtma suhbatga bog'langan (yoki suhbatdan ochilgan) bo'lsa — tasdiqlandi, tayyor (faqat olib ketish), topshirildi, bekor qilindi. Sayt formasidan kelgan, suhbatsiz buyurtmaga xabar yo'q (SMS — keyin).
- Nega: xaridor bilan aloqa kanali faqat suhbat; "bir marta" kafolati `intent_key` bilan.
- Yozuv joyi: `messaging.messages` (`origin = SYSTEM`) — `platform.notifications` da xaridor qatori yozilmaydi (20 dagi rejadan farq): xabar lentada ko'rinadi va yetkazish holati shu yerda.

**6. Xaridor matnlari — kodda standart, shop o'zinikini saqlaydi.**
- Tanlov: uz / ru / en standart matnlar; shop o'zgartirsa — yangi versiya, eskisi saqlanadi; majburiy o'zgaruvchi (`{order_number}`) tekshiriladi.
- Muqobil: faqat kod matnlari. Kamchilik — shop o'z ohangini qo'ya olmaydi.

**7. Ish vaqti (`inbox_hours`) va eslatma.**
- Tanlov: siyosatda kunlar va soat oralig'i (bo'sh — doim ochiq; tungi smena mumkin). Ish vaqtidan tashqari: xaridorga bitta "ish vaqtida javob beramiz" xabari, eslatma ish boshlanguncha kutadi. Eslatma — `handoff_reminder_minutes` (standart 15) dan keyin, bitta uzatishga bir marta.
- Muqobil: har N daqiqada takroriy eslatma. Kamchilik — xodim telefonida shovqin.

**8. Yuborish xatolari.**
- Tanlov: 5 urinish (429 da Telegram aytgan vaqt), keyin `FAILED` + vazifa; javobdan keyingi timeout — `UNKNOWN`, qayta yuborilmaydi (xaridor ikki marta olmasin), operator qaror qiladi; bloklangan xaridorga navbat qo'yilmaydi; token bekor — kanal `DEGRADED` va egaga vazifa.

**9. Rasmlardan boshqa fayllar yuklab olinmaydi.**
- Tanlov: ovoz, fayl, stiker — faqat turi va davomiyligi; inbox'da "ovozli xabar" belgisi. Operator rasm yubora oladi.
- Nega: Stage 1 da transkripsiya yo'q; fayllar xavfsizlik tekshiruvisiz saqlanmaydi.

**10. Bot almashtirish.**
- Tanlov: boshqa bot tokeni — eski bot `DISCONNECTED (REPLACED)`, yangisi ulanadi; o'sha botning yangi tokeni — token yangilanadi; boshqa shopda ulangan bot — `422 already_connected`.

**11. Instagram — flag ostida, access token bilan.**
- Tanlov: `FEATURE_CHANNEL_INSTAGRAM_DM` o'chiq (standart) — hamma Instagram endpointlari `404`. Ulash hozircha access token bilan (test uchun); OAuth — Meta ilovasi tekshiruvidan keyin.

**12. Saqlash muddati.**
- Tanlov: oxirgi faollikdan 12 oy — xabarlar, izohlar va rasmlar o'chiriladi, suhbat qatori (hisobot uchun) qoladi; webhook dedup yozuvlari — 30 kun; eskirgan sayt chati sessiyalari — 30 kundan keyin (26 §5).
