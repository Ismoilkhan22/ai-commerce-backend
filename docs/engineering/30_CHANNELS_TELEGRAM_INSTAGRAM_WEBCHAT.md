# TECH-30 — Kanallar: Telegram bot, Instagram Direct, web chat

**Status:** Baseline (2026-10-22). DEC-116 (uchala kanal Stage 1 da), M09, M10, BL-031…037, TECH-13 (umumiy integratsiya arxitekturasi).
**Muhim:** provayder imkoniyatlari va cheklovlari integratsiya boshlanishidan oldin rasmiy hujjatlardan qayta tekshiriladi (TECH-13 §8). Bu yerda yozilganlar — 2026-10 holatidagi rejalash uchun asos.

---

## 1. Umumiy model

Uchala kanal bitta normallashtirilgan xabar modeliga keltiriladi; inbox, AI va operator kanal farqini bilmaydi (faqat `channel` maydoni va kanal cheklovlari).

```python
class InboundMessage(BaseModel):
    channel: Literal["TELEGRAM", "INSTAGRAM", "WEB_CHAT"]
    channel_account_id: UUID          # do'konning ulangan akkaunti → merchant_id shu orqali
    provider_event_id: str            # dedup kaliti
    external_user_id: str             # Telegram user id, IG scoped id, web visitor id
    sent_at: datetime
    kind: Literal["TEXT", "IMAGE", "VOICE", "FILE", "CONTACT", "LOCATION", "STICKER", "UNSUPPORTED"]
    text: str | None
    attachment_ref: str | None        # private storage'ga yuklangan fayl
    reply_to_provider_id: str | None
```

**Har kanalda bir xil:**
- Webhook → imzo/secret tekshiruvi → `provider_events` ga durable yozish → 2xx (BL-032). Qayta ishlash worker'da.
- Dedup: `(channel_account_id, provider_event_id)` noyob.
- Merchant faqat `channel_account_id` → `merchant_id` server mapping'i orqali aniqlanadi (TECH-23).
- Chiquvchi xabar faqat outbox orqali, `speaker_version` tekshiruvi bilan (TECH-07 §6).
- Tokenlar secret manager'da (`token_secret_ref`), frontend'ga hech qachon qaytmaydi.

## 2. Telegram bot

### 2.1 Ulash

1. Do'kon egasi @BotFather'da bot yaratadi (yoki onboarding jamoasi yordam beradi — business/13).
2. Dashboard → Kanallar → Telegram → bot token kiritiladi.
3. Backend: `getMe` bilan tekshiradi, `setWebhook` chaqiradi: URL `https://api.<domen>/api/v1/webhooks/telegram/{account_ref}`, `secret_token` (tasodifiy, har akkaunt uchun alohida), `allowed_updates: ["message", "edited_message", "callback_query"]`.
4. Bot buyruqlari ro'yxati `setMyCommands` bilan uch tilda o'rnatiladi.
5. Holat: `PENDING → CONNECTED` (FSM-03).

**Webhook tekshiruvi:** `X-Telegram-Bot-Api-Secret-Token` header'i saqlangan qiymat bilan solishtiriladi; mos kelmasa 401. `account_ref` — tasodifiy, taxmin qilib bo'lmaydigan ID (lekin yagona himoya emas).

### 2.2 Buyruqlar va tugmalar

| Buyruq | Vazifasi |
|---|---|
| `/start` | Salomlashish (do'kon nomi, AI ekanini aytish), til tanlash tugmalari (O'zbekcha / Русский / English) |
| `/catalog` | Kategoriyalar tugmalari yoki storefront havolasi |
| `/operator` | Operatorga uzatish (`CUSTOMER_REQUEST`) |
| `/order` | Xaridorning oxirgi buyurtmasi holati |
| `/lang` | Tilni o'zgartirish |

- Inline tugmalar: mahsulot kartochkasida "Batafsil", "Olaman", "Operator"; quote xabarida "Taklifni ko'rish" (storefront havolasi).
- "Olaman" tugmasi AI orqali emas, to'g'ridan-to'g'ri `orders.create_draft` oqimini boshlaydi (kontakt so'raladi).
- Kontakt: "Raqamni yuborish" tugmasi (`request_contact`) — xaridor roziligi bilan telefon olinadi (BL-036, BL-042).

### 2.3 Xabar turlari va cheklovlar

| Tur | Qo'llab-quvvatlash |
|---|---|
| Matn | ✅ (bitta xabar ≤ 4096 belgi; uzunroq bo'lsa bo'linadi) |
| Rasm | ✅ kiruvchi (private storage'ga, Stage 1 da AI rasmni tahlil qilmaydi — operator ko'radi); chiquvchi — mahsulot rasmi |
| Ovozli xabar | ✅ kiruvchi: Stage 1 da operatorga ko'rsatiladi; STT voice beta bilan (DEC-112), audio transkripsiyadan keyin o'chiriladi (DEC-117) |
| Fayl, stiker, joylashuv | kiruvchi — operatorga ko'rsatiladi; AI "matn bilan yozing" deydi |
| Guruh chatlar | Stage 1 da yo'q — bot faqat shaxsiy chatlarda javob beradi |

- Bot foydalanuvchiga birinchi bo'lib yoza olmaydi; faqat foydalanuvchi `/start` bosgan yoki yozgan bo'lsa (BL-033).
- Rate limit: Telegram cheklovlariga mos ravishda har bot uchun chiquvchi navbat throttle qilinadi; 429 da `retry_after` ga amal qilinadi.

### 2.4 Telegram Business (feature flag)

Do'kon egasining shaxsiy Telegram akkauntiga botni ulash (business connection). Stage 1 da feature flag ostida; foydalanish uchun egasining Telegram Premium/Business sozlamasi va bot ruxsatlari kerak. Pilotda talab bo'lsa yoqiladi.

## 3. Instagram Direct (Meta)

### 3.1 Meta tekshiruvi — S0 dan boshlanadigan ishlar

| # | Ish | Mas'ul |
|---|---|---|
| 1 | Meta Business akkaunti va biznes verifikatsiyasi (kompaniya hujjatlari) | Founder |
| 2 | Meta Developer'da ilova (app) yaratish | Founder / dev |
| 3 | Privacy policy va terms sahifalari (public URL) — TECH-32 asosida | Founder + huquqshunos |
| 4 | Ma'lumotlarni o'chirish so'rovi URL / callback | Dev |
| 5 | Kerakli ruxsatlar ro'yxati (Instagram xabarlarini o'qish va yuborish, akkaunt ma'lumoti) — joriy nomlari ariza paytida rasmiy hujjatdan olinadi | Dev |
| 6 | App review: screencast (do'kon ulash, xabar kelishi, javob yuborish), foydalanish tavsifi | Founder + dev |
| 7 | Test: Meta test foydalanuvchilari va pilot do'konning professional Instagram akkaunti | Dev |

### 3.2 Ulash (do'kon tomonidan)

1. Do'konning Instagram akkaunti **professional** (Business yoki Creator) bo'lishi kerak.
2. Dashboard → Kanallar → Instagram → Meta OAuth oqimi (`state` va PKCE bilan); do'kon kerakli ruxsatlarni beradi.
3. Backend uzoq muddatli token oladi, secret manager'ga saqlaydi, muddatini kuzatadi (tugashidan oldin yangilash yoki egaga eslatma).
4. Webhook obunasi: kiruvchi xabarlar.

**Webhook tekshiruvi:** `X-Hub-Signature-256` — xom tana bo'yicha HMAC-SHA256 (app secret bilan); obuna paytida `hub.challenge` tekshiruvi.

### 3.3 Cheklovlar (rejalash uchun, ariza paytida tasdiqlanadi)

- Xabar yuborish faqat xaridor yozgan suhbatga va Meta belgilagan **javob oynasi** ichida (standart — oxirgi xaridor xabaridan keyin 24 soat). Oyna yopilgan bo'lsa — AI yubormaydi; operatorga vazifa: "javob oynasi yopilgan" (BL-033).
- Sovuq (birinchi bo'lib) xabar, ommaviy xabar — yo'q (business/08 §5).
- Inline tugmalar va mahsulot kartochkalari imkoniyatlari cheklangan — Stage 1 da matn + storefront havolasi.
- Token bekor qilinsa yoki ruxsat olib tashlansa → `DEGRADED` / `DISCONNECTED`, outbound to'xtaydi, egaga xabar (FSM-03).

## 4. Web chat (storefront widget)

| Mavzu | Qoida |
|---|---|
| Joylashuv | Storefront sahifalarida (S1), keyin istalgan saytga `<script>` snippet (taklif: Stage 1 oxirida) |
| Transport | REST (xabar yuborish) + WebSocket (javoblarni olish); WS uzilsa polling |
| Mehmon identifikatsiyasi | Brauzerda tasodifiy `visitor_id` (httpOnly cookie, storefront domenida); login talab qilinmaydi |
| Kontakt | Xaridor ixtiyoriy ravishda telefon/ism kiritadi (buyurtma uchun majburiy), rozilik belgisi bilan |
| Spam himoyasi | IP va `visitor_id` bo'yicha rate limit; shubhali faollikda oddiy challenge |
| Tarix | Xuddi shu brauzerda suhbat davom etadi; boshqa qurilmada — yangi suhbat (Stage 1) |
| Javob oynasi | Cheklov yo'q (o'z kanalimiz) |
| Endpointlar | `POST /api/v1/storefront/{slug}/chat/messages`, `GET …/chat/messages?after=`, WS `/ws/v1/storefront/{slug}/chat?ticket=` |

## 5. Kanal holati va monitoring

| Holat (FSM-03) | Belgisi | Harakat |
|---|---|---|
| `CONNECTED` | webhook kelyapti, outbound ishlayapti | — |
| `DEGRADED` | ketma-ket outbound xatolari, token muddati yaqin, webhook 24 soat jim | egaga dashboard + Telegram ogohlantirishi |
| `DISCONNECTED` | token bekor, ruxsat olib tashlangan | outbound to'xtaydi, inbox'da banner, qayta ulash tugmasi |

Metrikalar: `webhook_duplicates_total{channel}`, `webhook_invalid_signature_total{channel}`, `outbound_failures_total{channel, error_class}`, `channel_window_closed_total{channel}` (TECH-12).

## 6. Testlar

| ID | Sinov | Natija |
|---|---|---|
| TC-CH-01 | Telegram webhook noto'g'ri secret bilan | 401, event yozilmaydi |
| TC-CH-02 | Bir xil `update_id` 5 marta | bitta xabar inbox'da |
| TC-CH-03 | Instagram: 24 soatdan keyin javob | yuborilmaydi, operator vazifasi |
| TC-CH-04 | Instagram token bekor qilindi | `DISCONNECTED`, outbound to'xtadi, egaga xabar |
| TC-CH-05 | Operator suhbatni oldi, AI javobi navbatda | AI javobi yuborilmaydi (TC-009) |
| TC-CH-06 | Web chat: boshqa do'kon `slug`i bilan suhbat ID'si | 404 |
| TC-CH-07 | 5000 belgili AI javobi Telegram'ga | bo'linib yuboriladi, tartib saqlanadi |
