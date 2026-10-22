# 13 — Integratsiyalar va kanallar (Telegram, Instagram, sayt chati)

> **Versiya:** v2 (2026-10-22). Eski `13_INTEGRATION_ARCHITECTURE` va `30_CHANNELS_TELEGRAM_INSTAGRAM_WEBCHAT` o'rnini bosadi.
> **Domen:** `messaging` → `channels` sub-moduli (M09) va `conversations` (M10). **Qarorlar:** DEC-116 (uchala kanal Stage 1 da), DEC-116a, ADR-015, ADR-032, ADR-033.
> **Kim o'qiydi:** backend dasturchi.
> **Muhim:** provayder imkoniyatlari va cheklovlari integratsiyani yozishdan oldin rasmiy hujjatlardan qayta tekshiriladi (§9). Bu yerdagilar — 2026-10 holatidagi reja.

## 1. Muammo va yechim

**Muammo:** har kanal (Telegram, Instagram, sayt chati) o'z formatida, o'z cheklovlari bilan ishlaydi. Agar inbox, AI va operator har kanalni alohida bilsa — kod uch barobar ko'payadi va xatolar kanalga qarab farqlanadi. Tashqi provayder webhook'ni bir necha marta yuboradi, sekin javob bersak qayta yuboradi, ba'zan umuman ishlamaydi.

**Yechim:**
1. Har kanal — `messaging/channels/adapters/` dagi bitta **adapter**. Adapter tashqi formatni yagona `InboundMessage` ga aylantiradi va `ChannelPort.send()` orqali yuboradi. Inbox, AI va operator kanal farqini bilmaydi (faqat `channel` maydoni va cheklovlar).
2. **Webhook tez javob beradi:** imzo tekshiriladi → dedup → xabar saqlanadi + outbox → `200 OK`. AI va boshqa ishlar keyin, worker'da (BL-032).
3. **Chiquvchi xabar faqat arq orqali** (`channel_send` task), `speaker_version` tekshiruvi bilan.

**Qoida:** domen kodi Telegram SDK yoki Meta API'ni import qilmaydi — faqat `ChannelPort`.

---

## 2. Adapter kontrakti

```python
# app/domains/messaging/channels/adapters/base.py
class ChannelPort(Protocol):
    channel: ChannelType                                   # TELEGRAM | INSTAGRAM | WEB_CHAT

    async def verify_webhook(self, raw_body: bytes, headers: Mapping[str, str],
                             account: ChannelAccount) -> None: ...      # yiqilsa WebhookAuthError
    def parse(self, raw_body: bytes, account: ChannelAccount) -> list[InboundMessage]: ...
    async def send(self, account: ChannelAccount, recipient_ref: str,
                   message: OutboundMessage, idempotency_ref: str) -> SendResult: ...
    async def health_check(self, account: ChannelAccount) -> ChannelHealth: ...
```

```python
class InboundMessage(BaseModel):
    channel: Literal["TELEGRAM", "INSTAGRAM", "WEB_CHAT"]
    channel_account_id: UUID          # shopning ulangan akkaunti → shop_id faqat shu orqali (server mapping)
    provider_event_id: str            # dedup kaliti
    external_user_id: str             # Telegram user id, IG scoped id, sayt visitor_id
    sent_at: datetime
    kind: Literal["TEXT", "IMAGE", "VOICE", "FILE", "CONTACT", "LOCATION", "STICKER", "UNSUPPORTED"]
    text: str | None
    attachment_ref: str | None        # platform/storage'dagi private fayl
    reply_to_provider_id: str | None
```

**Adapter xatolari (yagona taksonomiya):**

| Kod | Ma'nosi | Worker nima qiladi |
|---|---|---|
| `AUTH_REVOKED` | Token bekor, ruxsat olib tashlangan | Kanal → `DISCONNECTED`, yuborish to'xtaydi, egaga xabar |
| `RATE_LIMITED` | 429, `retry_after` bilan | `retry_after` dan keyin qayta (arq `Retry(defer=...)`) |
| `WINDOW_CLOSED` | Instagram 24 soatlik oyna yopiq | Yubormaydi, operatorga vazifa |
| `TIMEOUT_AMBIGUOUS` | Javob kelmadi — yuborildimi noma'lum | Bir marta qayta (provayder idempotency bo'lsa), aks holda `UNKNOWN` belgisi va operator ko'radi |
| `VALIDATION_ERROR` | Xabar formati noto'g'ri (masalan, juda uzun) | Qayta urinmaydi, `messaging.message.failed` |
| `UNAVAILABLE` | Provayder ishlamayapti | Eksponensial qayta urinish, keyin dead-letter |
| `NOT_SUPPORTED` | Kanal bu turdagi xabarni qo'llamaydi | Matnga aylantiriladi yoki havola |

---

## 3. Kiruvchi xabar oqimi

```
Provayder ──POST /api/v1/webhooks/{channel}/{account_ref}──▶ API
  1. Xom tana o'lchami ≤ 1 MB, deadline 3 s
  2. account_ref → channel_account (server mapping) → shop_id; kanal CONNECTED/DEGRADED emasmi? → 404
  3. adapter.verify_webhook(raw_body, headers) — yiqilsa 401 + cos_messaging_webhook_invalid_signature_total
  4. Har InboundMessage uchun, BITTA tranzaksiyada (set_config('app.shop_id')):
       INSERT messaging.provider_events (provider, channel_account_id, provider_event_id) — UNIQUE
         ├─ takror (conflict) → hech narsa qilinmaydi (TC-010)
         └─ yangi → conversation topiladi/yaratiladi (FSM-04: NEW → AI_ACTIVE yoki REOPENED)
                  → message saqlanadi
                  → outbox [messaging.message.received]
  5. COMMIT ──▶ 200 OK   (AI kutilmaydi)
outbox_worker ──▶ sales_ai subscriber (AI javobi, 14-…) va reporting subscriber
```

**Dedup kaliti:** `UNIQUE (provider, channel_account_id, provider_event_id)` — Telegram `update_id`, Meta `mid`, sayt chati — klient yaratgan `client_message_id`.

**Shop qanday aniqlanadi:** faqat `channel_account_id → shop_id` server mapping'i orqali. Webhook tanasidagi hech qanday maydon shopni belgilamaydi (00, 13-qoida).

**Media:** rasm, ovoz, fayl provayderdan arq task'ida yuklab olinadi va `platform/storage` ga private saqlanadi (`attachment_ref`). Webhook ichida yuklab olinmaydi.

---

## 4. Chiquvchi xabar oqimi

```
Kim yuboradi:
  • AI: sales_ai ──outbox [sales_ai.reply.ready]──▶ messaging subscriber
  • Operator: POST /api/v1/shop/conversations/{id}/messages (Idempotency-Key)
  • Tizim xabarnomasi: platform/notifications (20-…) → messaging send
messaging service, BITTA tranzaksiya:
  1. conversation FOR UPDATE
  2. AI javobi bo'lsa: speaker_mode == AI va speaker_version == event'dagi versiya?
       └─ yo'q → javob tashlanadi, cos_sales_ai_reply_discarded_total (TC-009)
  3. outbound_message (status QUEUED, message_intent_id) + outbox [arq: channel_send, job_id=message_intent_id]
COMMIT
task_worker: channel_send(message_intent_id)
  ├─ kanal holati CONNECTED/DEGRADED? Instagram oynasi ochiqmi?
  ├─ adapter.send(..., idempotency_ref=message_intent_id)
  ├─ OK → status SENT + outbox [messaging.message.sent]
  └─ xato → §2 jadvali; oxirgi xato → status FAILED + outbox [messaging.message.failed]
```

**Rate limit va 429 (TC-032):**
- Har `channel_account` uchun Redis token bucket (Telegram: bitta chatga ~1 xabar/s, bot bo'yicha umumiy limit — qiymatlar konfiguratsiyada).
- 429 kelsa — `retry_after` ga amal qilinadi, maksimal 5 urinish; xabar takrorlanmaydi (`message_intent_id`).
- Yuborilmagan xabar inbox'da "yuborilmadi" belgisi bilan ko'rinadi, "yuborildi" deb ko'rsatilmaydi (TC-011).

**Uzun xabar:** kanal limitidan uzun matn (Telegram 4096 belgi) bo'linadi; bo'laklar ketma-ket bitta task'da yuboriladi, tartib saqlanadi.

---

## 5. Kanal holati (FSM-03)

`../business/05` dagi strelkalar, `channels/state_machine.py` da:

```
PENDING ──(ega ruxsat berdi, sinov xabari o'tdi)──▶ CONNECTED          [messaging.channel.connected]
CONNECTED ──(xatolar ko'paydi / token muddati yaqin / 24 soat jim)──▶ DEGRADED   [egaga ogohlantirish]
DEGRADED ──(ega qayta uladi yoki health check o'tdi)──▶ CONNECTED
CONNECTED | DEGRADED ──(ega uzdi / AUTH_REVOKED)──▶ DISCONNECTED       [messaging.channel.disconnected, yuborish to'xtaydi]
```

**Rejali ish:** `channel_health_check` (scheduler, har 30 daqiqa, advisory lock) — har ulangan akkauntda `health_check()`, token muddati, oxirgi webhook vaqti. Ruxsatsiz kanalni "ulangan" deb ko'rsatish taqiqlanadi.

**Akkaunt yozuvi** (`messaging.channel_accounts`): `shop_id, channel, account_ref, external_account_id, status, scopes, token_secret_ref, webhook_secret_ref, subscribed_events, rate_policy, token_expires_at, last_webhook_at, last_health_check_at`. Token va secret'lar faqat secret store'da (`*_secret_ref`), API javobida hech qachon qaytmaydi.

---

## 6. Telegram bot

### 6.1 Ulash
1. Shop egasi @BotFather'da bot yaratadi (yoki ulash jamoasi yordam beradi — `../business/13`).
2. Dashboard → Kanallar → Telegram → bot token kiritiladi (`POST /api/v1/shop/channels/telegram`, ruxsat `messaging.channel.connect` — faqat ega).
3. Backend: `getMe` bilan tekshiradi, `setWebhook`: URL `https://api.<domen>/api/v1/webhooks/telegram/{account_ref}`, har akkaunt uchun alohida tasodifiy `secret_token`, `allowed_updates: ["message", "edited_message", "callback_query"]`.
4. `setMyCommands` uch tilda.
5. FSM-03: `PENDING → CONNECTED`.

**Webhook tekshiruvi:** `X-Telegram-Bot-Api-Secret-Token` saqlangan qiymat bilan constant-time solishtiriladi; mos kelmasa 401. `account_ref` — taxmin qilib bo'lmaydigan ID, lekin yagona himoya emas.

### 6.2 Buyruqlar va tugmalar

| Buyruq | Vazifasi |
|---|---|
| `/start` | Salomlashish (shop nomi, AI ekanini aytish), til tanlash tugmalari |
| `/catalog` | Kategoriyalar yoki sayt havolasi |
| `/operator` | Operatorga uzatish (`CUSTOMER_REQUEST`) |
| `/order` | Xaridorning oxirgi buyurtmasi holati |
| `/lang` | Tilni o'zgartirish |

- Inline tugmalar: mahsulot kartochkasida "Batafsil", "Olaman", "Operator"; taklif xabarida "Taklifni ko'rish" (sayt havolasi).
- "Olaman" tugmasi (`callback_query`) oddiy xabar kabi saqlanadi, lekin `intent_hint = PURCHASE_INTENT` belgisi bilan. AI agent buni taxmin qilmaydi — kontaktni so'raydi va `commerce.create_order_draft` tool'ini chaqiradi (`14` §4). Natija: faqat `DRAFT` buyurtma, qoldiq o'zgarmaydi (TC-028).
- Kontakt: "Raqamni yuborish" tugmasi (`request_contact`) — xaridor roziligi bilan (BL-036, BL-042).

### 6.3 Xabar turlari

| Tur | Stage 1 |
|---|---|
| Matn | ✅ ≤ 4096 belgi, uzunroq bo'linadi |
| Rasm | Kiruvchi — storage'ga, AI tahlil qilmaydi, operator ko'radi; chiquvchi — mahsulot rasmi |
| Ovozli xabar | Kiruvchi — operatorga ko'rsatiladi; STT faqat ovozli hisobot beta bilan (DEC-112), audio transkripsiyadan keyin o'chiriladi (DEC-117) |
| Fayl, stiker, joylashuv | Operatorga ko'rsatiladi; AI "matn bilan yozing" deydi |
| Guruh chatlar | Yo'q — bot faqat shaxsiy chatda javob beradi |

Bot foydalanuvchiga birinchi bo'lib yoza olmaydi (BL-033).

### 6.4 Telegram Business (feature flag)
Egasining shaxsiy Telegram akkauntiga botni ulash (business connection). Stage 1 da feature flag ostida, pilotda talab bo'lsa yoqiladi.

---

## 7. Instagram Direct (Meta)

### 7.1 Meta tekshiruvi — S0 dan (DEC-116, `27` S0-00)

| # | Ish | Mas'ul |
|---|---|---|
| 1 | Meta Business akkaunti va biznes verifikatsiyasi | Founder |
| 2 | Meta Developer'da ilova | Founder / dev |
| 3 | Privacy policy va terms (public URL) — `26-privacy-and-retention.md` asosida | Founder + huquqshunos |
| 4 | Ma'lumot o'chirish so'rovi callback'i | Dev |
| 5 | Kerakli ruxsatlar ro'yxati — joriy nomlar ariza paytida rasmiy hujjatdan | Dev |
| 6 | App review: screencast (ulash, xabar kelishi, javob), foydalanish tavsifi | Founder + dev |
| 7 | Test: Meta test foydalanuvchilari va pilot shopning professional akkaunti | Dev |

**DEC-116a:** Meta ruxsati pilot sanasiga kelmasa — pilot Telegram + sayt chati bilan boshlanadi, Instagram ruxsat kelganda yoqiladi (feature flag `channel.instagram`).

### 7.2 Ulash
1. Shopning Instagram akkaunti **professional** (Business yoki Creator).
2. Dashboard → Kanallar → Instagram → Meta OAuth (`state` + PKCE).
3. Backend uzoq muddatli token oladi, secret store'ga saqlaydi, `token_expires_at` kuzatiladi (tugashidan oldin yangilash yoki egaga eslatma).
4. Webhook obunasi: kiruvchi xabarlar.

**Webhook tekshiruvi:** `X-Hub-Signature-256` — xom tana bo'yicha HMAC-SHA256 (app secret); obunada `hub.challenge`.

### 7.3 Cheklovlar (ariza paytida tasdiqlanadi)
- Xabar faqat xaridor yozgan suhbatga va **javob oynasi** ichida (standart — xaridorning oxirgi xabaridan 24 soat). Oyna yopiq → `WINDOW_CLOSED`, AI yubormaydi, operatorga vazifa (BL-033).
- Sovuq va ommaviy xabar — yo'q.
- Stage 1 da matn + sayt havolasi (kartochkalar cheklangan).
- Token bekor → `AUTH_REVOKED` → `DISCONNECTED`, egaga xabar.

---

## 8. Sayt chati (storefront widget)

Sayt chati ham `messaging` adapteri (`WEB_CHAT`), lekin webhook o'rniga `storefront` surface endpoint'lari.

| Mavzu | Qoida |
|---|---|
| Joylashuv | Shop sayti sahifalarida (S1); keyin istalgan saytga `<script>` snippet |
| Transport | REST (yuborish) + SSE (javoblar, server → brauzer, `08` §6.6); SSE uzilsa `GET …/chat/messages?after=` polling. Xodimlar WebSocket'idan butunlay alohida |
| Mehmon | `visitor_id` — httpOnly cookie, sayt domenida; login yo'q |
| Kontakt | Ixtiyoriy telefon/ism (buyurtma uchun majburiy), rozilik belgisi bilan |
| Spam | IP va `visitor_id` bo'yicha rate limit; shubhada oddiy challenge |
| Tarix | Shu brauzerda davom etadi; boshqa qurilmada — yangi suhbat |
| Javob oynasi | Cheklov yo'q |
| Endpoint'lar | `POST /api/v1/storefront/{slug}/chat/sessions`, `POST …/chat/messages`, `GET …/chat/messages?after=`, SSE `GET …/chat/sessions/{session_id}/events` |

Boshqa shop `slug`i bilan suhbat ID'si so'ralsa — 404 (TC-CH-06).

---

## 9. Provayder tekshiruv varag'i

Har integratsiya uchun `docs/modules/messaging/providers/<provider>.md`: rasmiy hujjat versiyasi va sanasi, ruxsatlar va review natijasi, sandbox akkaunt, rate limit'lar, javob oynalari, webhook tekshiruvi, token bekor qilish tartibi, testlar. Qo'llab-quvvatlanmaydigan imkoniyat — standart holatda o'chiq.

**Kanallar imkoniyatlari (reja):**

| Kanal | Stage | Holat |
|---|---|---|
| Sayt chati | 1 (S1–S2) | P0 |
| Telegram bot | 1 (S2) | P0 |
| Instagram Direct | 1 (S2) | P0, Meta review majburiy (DEC-116) |
| Telegram Business | 1 | Feature flag |
| Facebook Messenger, WhatsApp Business | keyin | Va'da yo'q, tadqiqot |
| TikTok va boshqalar | — | Rasmiy imkoniyat tasdiqlanmaguncha yo'q |

---

## 10. Boshqa integratsiyalar

| Integratsiya | Holat | Qayerda |
|---|---|---|
| To'lov provayderlari | **DEFERRED** (DEC-100) — Stage 1 da to'lov tizimdan tashqarida. Qaytganda: kelajakdagi `payments` domeni, `PaymentVerificationPort`, chek rasmi hech qachon avtomatik "to'landi" emas (ADR-016) | `payments` (keyin) |
| Yetkazish xizmatlari | **DEFERRED** (DEC-113) | `fulfillment` (keyin) |
| Kassa (POS), ERP, marketplace sinxronlash | **Stage 2** — `network` domenidagi anti-corruption adapterlar: maydon bo'yicha manba ustuvorligi, `origin_id`/`external_revision`/`sync_cursor` bilan "ping-pong"dan himoya, mos kelmaganlar qo'lda ko'rib chiqiladi, qoldiq invariantini buzmaydi (TC-019) | `28-network-and-global-search.md` |
| Xarita va geo | **Stage 3** — filial koordinatalari shopniki; litsenziyali xarita servisi; ETA "taxminiy" deb belgilanadi | `28` |

---

## 11. Xavfsizlik va kuzatuv

- Secret'lar secret store'da, `*_secret_ref` orqali; OAuth `state` + PKCE; token bekor qilish va rotatsiya — runbook (`25`).
- Tashqi so'rovlar uchun egress allowlist; har provayder uchun circuit breaker va rate bucket.
- Span'lar: `messaging.webhook`, `messaging.channel_send` (provayder javob kodi bilan, xabar matnisiz).
- Metrikalar: `cos_messaging_webhook_duplicates_total{channel}`, `cos_messaging_webhook_invalid_signature_total{channel}`, `cos_messaging_outbound_failures_total{channel,error_class}`, `cos_messaging_channel_window_closed_total{channel}`, `cos_messaging_webhook_ack_duration_seconds`.

## 12. Testlar

| ID | Sinov | Natija |
|---|---|---|
| TC-CH-01 | Telegram webhook noto'g'ri secret bilan | 401, hech narsa yozilmaydi |
| TC-CH-02 | Bir xil `update_id` 5 marta (TC-010) | Bitta xabar, bitta AI javobi |
| TC-CH-03 | Instagram: 24 soatdan keyin javob | Yuborilmaydi, operator vazifasi |
| TC-CH-04 | Instagram token bekor qilindi (TC-011) | `DISCONNECTED`, yuborish to'xtadi, egaga xabar, "yuborildi" ko'rsatilmaydi |
| TC-CH-05 | Operator suhbatni oldi, AI javobi navbatda (TC-009) | AI javobi yuborilmaydi |
| TC-CH-06 | Sayt chati: boshqa shop `slug`i bilan suhbat ID'si | 404 |
| TC-CH-07 | 5000 belgili javob Telegram'ga | Bo'linib, tartib bilan yuboriladi |
| TC-CH-08 | Telegram 429 `retry_after=5` (TC-032) | 5 s dan keyin qayta, takror xabar yo'q |
| TC-CH-09 | Webhook ichida DB yozuvi COMMIT'dan oldin worker o'chdi | Provayder qayta yuboradi, dedup bitta xabar qoldiradi |

## Keyingi qadam

→ [14-ai-sales-agent-and-tools.md](14-ai-sales-agent-and-tools.md) — AI sotuvchi va tool'lar
→ [05-events-and-outbox.md](05-events-and-outbox.md) — `messaging.*` event'lari
