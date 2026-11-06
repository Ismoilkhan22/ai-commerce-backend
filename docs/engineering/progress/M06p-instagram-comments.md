# 6+ modul: Instagram izohlari (`messaging` ga qo'shimcha), backend

> **Holat:** backend bitdi (2026-10-27), commit qilinmagan — founder ko'rib chiqishi kutilmoqda.
> **Asos:** [db/instagram_comments.md](../db/instagram_comments.md) va [.dbml](../db/instagram_comments.dbml), DEC-148 (taklif), DEC-132 (fon), DEC-119 (AI limiti).
> **Frontend:** `shop-dashboard/src/lib/ig-comments.ts` allaqachon bor edi. Backend shu kontraktga moslab yozildi (pastda — farqlar).
> **Flag:** hammasi `FEATURE_CHANNEL_INSTAGRAM_DM` ostida. Flag o'chiq bo'lsa panel endpoint'lari 404 qaytaradi (tokensiz ham), webhook ham 404.

---

## 1. Nima bitdi — oddiy so'z bilan

Instagram'da shopning postiga izoh yozishadi. Tizim endi shuni qiladi:

- **«+» yozgan odamga Direct'da bitta xabar yuboriladi.** «+» ni AI emas, oddiy qoida aniqlaydi ("+", "++", "+1", emoji va bo'shliqlar e'tiborsiz).
- **"Narxi qancha?" kabi savolga ham shunday.** Savolni ham qoida aniqlaydi (o'zbek lotin va kirill, rus, ingliz so'zlari).
- **Narx faqat katalogdan.** Xodim postga mahsulot bog'lagan bo'lsa — narx, qoldiq va mahsulot havolasi aytiladi. Bog'lanmagan bo'lsa — narxsiz umumiy javob: "Narx va mavjudlik bo'yicha shu yerga yozing".
- **Bir odamga bir postda bitta javob.** Jasur "+" ni 5 marta yozsa, Direct'ga bitta xabar ketadi.
- **Konkurs postida avtomatik javobni o'chirib qo'yish mumkin** (post bo'yicha tugma). Butun shop uchun ham alohida tugma bor.
- **Kayfiyatni AI baholaydi:** ijobiy, salbiy, neytral, spam. Ishonch 0.70 dan past bo'lsa — "aniqlanmagan". AI hech narsa yozmaydi va izohni o'chirmaydi.
- **AI limiti tugasa** kayfiyat baholash to'xtaydi, lekin «+» javoblari ishlayveradi (ular AI emas).
- **Javob inbox'ga tushmaydi.** Xaridor Direct'da javob yozgandagina oddiy suhbat ochiladi (mavjud Direct oqimi).

Hech narsa Meta'ga haqiqatda yuborilmaydi: kod soxta klient bilan sinalgan, haqiqiy chaqiruv Meta ruxsati kelgach ishlaydi.

---

## 2. Oqim

```
Meta webhook (field: comments) ──▶ /api/v1/webhooks/instagram     (Direct bilan bir xil manzil va imzo)
  BITTA tranzaksiya:
    provider_events (kind COMMENT) — takror bo'lsa hech narsa
    ig_posts topiladi/yaratiladi → ig_comments saqlanadi → qoida: PLUS | PRICE_QUESTION | NONE
    outbox [messaging.ig_comment.received]
  ──▶ 200 OK

Uchta mustaqil tinglovchi (bir-birini kutmaydi):
  ig_comment_reply   — qaror va javob navbati
      flag, shop sozlamasi, post sozlamasi, 7 kun, bir muallif-bir post tekshiriladi
      narx: CatalogQueryPort (post bog'langan mahsulot) → QUEUED yoki SKIPPED (sabab bilan)
  ig_reply_send      — Meta'ga yuborish (tranzaksiyadan tashqarida): SENDING → SENT | FAILED | SKIPPED
  ig_comment_classify — AI limiti bormi? → telefon/manzil yashiriladi → `light` model → kayfiyat
  ig_post_fetch      — post rasmi, havolasi, sarlavhasi (webhook ichida emas)
```

---

## 3. Endpoint'lar (`/api/v1/shop/instagram/*`)

- `GET /settings` — `feature_enabled`, `permission_granted` (Meta izohlar ruxsati), `auto_reply`, `sentiment`, `version`.
- `PATCH /settings` (If-Match) — `auto_reply?`, `sentiment?`. Meta ruxsati yo'q bo'lsa yoqib bo'lmaydi (422 `permission_missing`).
- `GET /templates` — ikkita shablon × uch til (6 qator). `PUT` va `DELETE /templates/{key}/{locale}` — o'zgartirish va standartga qaytarish. Shablon kalitlari: `customer.ig_comment_price_reply`, `customer.ig_comment_generic_reply`. Boshqa kalit — 404.
- `GET /posts?limit&cursor` — postlar, bog'langan mahsulotlar nomi bilan.
- `PATCH /posts/{id}` (If-Match) — `auto_reply_enabled`.
- `PUT /posts/{id}/products` (If-Match) — `product_ids[]`, ko'pi bilan 5 ta; faqat saytda ko'rinadigan mahsulot.
- `GET /comments?filter=all|plus|price|negative|unclassified&post_id&limit&cursor` — katta-kichik harf farqsiz; frontend yuboradigan `PRICE_QUESTION` ham qabul qilinadi.
- `GET /sentiment-summary?period=7d|30d|90d`.

**Ruxsatlar** (yangi, alohida):
- `messaging.instagram.view` — ega, menejer, operator (SALES). Hamma GET.
- `messaging.instagram.manage` — ega, menejer. Sozlama, shablon, post ↔ mahsulot, post tugmasi.
- Omborchi (WAREHOUSE) — hech narsa.

Nega alohida: frontend `messaging.channel.connect` ni taxmin qilgan edi, lekin u faqat egaga beriladi. Hujjatga ko'ra post ↔ mahsulot bog'lashni menejer (Vali) qiladi. Frontend'da ikki doimiyni almashtirish kerak: `IG_PERM_VIEW = "messaging.instagram.view"`, `IG_PERM_MANAGE = "messaging.instagram.manage"`.

---

## 4. Fayllar xaritasi

```
app/db/migrations/messaging/versions/messaging_0004_instagram_comments.py   5 jadval + RLS (FORCE) + provider_events.ig_comment_id
app/db/migrations/platform/versions/platform_0016_ai_usage_comment_classify.py   ai_usage.purpose ga COMMENT_CLASSIFY
app/domains/messaging/
├── models/ig.py                  ig_posts, ig_post_products, ig_comments, ig_comment_sentiments, ig_comment_replies
├── ig_rules.py                   «+» / narx qoidasi, til aniqlash (toza funksiyalar)
├── ig_schemas.py                 API kontraktlari (frontend nomlari bilan)
├── channels/instagram.py         + InboundComment, parse_comment_events, send_private_reply, fetch_media (soxta va haqiqiy klient)
├── services/
│   ├── ig_ingest.py              webhook: dedup → post → izoh → qoida → outbox
│   ├── ig_reply.py               qaror, matn (narx), yuborish, qayta urinish
│   ├── ig_classify.py            kayfiyat: limit, PII yashirish, `light` model, 0.70 chegara
│   ├── ig_media.py               post media ma'lumoti
│   ├── ig_panel.py               settings, shablon, post, izoh, hisobot
│   └── ig_common.py              event nomlari, kanal sozlamasi, event yozish
├── api/ig_routes.py              /instagram/* (flag dependency'si router darajasida)
├── api/webhook_routes.py         + izoh hodisalari (o'sha imzo tekshiruvi)
├── subscribers.py                + 4 tinglovchi
└── permissions.py                + messaging.instagram.view / manage
app/shared/contracts/sales_ai.py  + AiBudgetPort (messaging sales_ai kodini import qilmaydi)
app/domains/sales_ai/services/gate.py   + allowance() — AI limiti bormi
app/platform/llm/usage.py         + record_usage_entry (ai_usage id'sini qaytaradi)
app/platform/notifications/customer_templates.py   + 2 ta shablon (uz/ru/en)
tests/unit/test_instagram_comment_rules.py          41 test
tests/integration/test_instagram_comments.py        20 test
```

---

## 5. Tekshiruv

Testlar (haqiqiy PostgreSQL, Meta va LLM soxta):
- Takror webhook: bitta izoh, bitta `provider_events`, bitta javob; noto'g'ri imzo — 404.
- «+» qoidasi (11 xil yozilish) va narx so'rovi (o'zbek lotin/kirill, ru, en); bir muallif-bir post-bitta javob; boshqa post yoki muallif — yana javob.
- Narxli javob (katalogdan, qoldiq, havola) va narxsiz umumiy javob; yashirilgan mahsulot — umumiy javob; karusel (5 mahsulot); rus tilidagi savol — rus javobi.
- Post tugmasi, shop tugmasi, 7 kunlik oyna, Meta ruxsati yo'q — yoqib bo'lmaydi.
- Javob idempotent: bir event ikki marta qayta ishlansa ham bitta javob; qayta urinish (429) — baribir bitta xabar; Meta "oyna o'tdi" xatosi — `SKIPPED`, timeout — `FAILED` (qayta yuborilmaydi).
- Kayfiyat chegarasi: 0.93 — salbiy; 0.55 — "aniqlanmagan" (asl taxmin `raw_label` da); aynan 0.70 — o'tadi; buzuq javob — "aniqlanmagan". `ai_usage` da `COMMENT_CLASSIFY`. Telefon raqami modelga ketmaydi.
- AI limiti tugagan: model chaqirilmaydi, izoh `CLASSIFY_SKIPPED`, «+» javobi baribir ketadi. Provayder xatosi ham javobni to'xtatmaydi.
- Ruxsatlar (ega, menejer, operator, omborchi, tokensiz) va RLS: boshqa shop hech narsa ko'rmaydi; 5 jadvalda `FORCE ROW LEVEL SECURITY`; shop kontekstisiz runtime roli 0 qator ko'radi.
- Flag o'chiq: 10 ta endpoint hammasi 404 (tokensiz ham).
- Event'larda izoh matni, username va narx yo'q; kalit nomlari PII tekshiruvidan o'tadi; audit'da ham matn yo'q.
- Post media ma'lumoti fonda olinadi va post versiyasini oshirmaydi.

Natija: `make check` o'tdi (ruff, mypy, import-linter, 981 test). Shundan yangi: 41 unit va 20 integratsiya testi. Migratsiyalar dev bazaga (5433) `make migrate` bilan qo'llangan.

---

## 6. Ataylab keyinga

- **Salbiy izohga vazifa va javob qoralamasi** (`IG_NEGATIVE_COMMENT`, `PUBLIC_STAFF` + `DRAFT`). Hozir salbiy izoh "Salbiy" filtrida ko'rinadi, lekin menejerga vazifa ochilmaydi. Vazifa turi va bildirishnoma shabloni kerak (kichik, lekin alohida qaror).
- **Xaridor Direct'da javob yozganda suhbatni izohga bog'lash** (`reply_to` → `ig_comments.conversation_id`, event `ig_comment.linked`). Hozir `conversation_id` doim bo'sh; Direct suhbati oddiy oqim bilan ochiladi.
- **Xodimning Direct/ommaviy javobi** (`PRIVATE_STAFF`, `PUBLIC_STAFF`) va kayfiyatni qo'lda tuzatish (`STAFF` manbasi). Jadvallar tayyor, endpoint yo'q.
- **`IG_REPLY_FAILED` vazifasi** va kanal `DEGRADED` bo'lishi (token bekor qilinganda) — yuborish xatosi hozir faqat izohning javob holatida ko'rinadi.
- **12 oylik tozalash** (`ig_comments` matni) va xaridorni o'chirish so'rovi (`pii_erased_at`). Izoh o'chirilganda matn darhol tozalanadi (bor).
- **Hisobot** (`reporting`) tinglovchilari. Event'lar yoziladi, iste'molchi yo'q.
- **Haqiqiy Meta chaqiruvi:** `send_private_reply` va `fetch_media` yozilgan, lekin hech qachon haqiqiy Meta bilan sinalmagan. Xato kodlari (7 kun o'tdi, allaqachon javob berilgan) taxminiy — app review paytida tekshiriladi. Meta ruxsati (`scopes`) hozir faqat soxta klientdan keladi; haqiqiy klient bo'sh qaytaradi. Standart sozlama ikkalasi yoqiq, shuning uchun ishlash to'xtamaydi — faqat aniq "yoqish" so'rovi (PATCH true) rad etiladi.

---

## 7. Hujjatlarga ta'siri (egasi yangilaydi)

Men tegmadim (sizning qoidangiz): DECISION_REGISTER, business/*, engineering/13, engineering/27. Yangilash kerak:
- **05 (event'lar):** payload kalit nomlari dbml'dagidan farq qiladi. `comment_id` → `item_id`, `has_text` → `has_content`. Sabab: event PII tekshiruvi `comment`, `text`, `name` so'zlarini taqiqlaydi (`app/shared/events/pii.py`).
- **10 (ruxsatlar):** `messaging.instagram.view`, `messaging.instagram.manage`.
- **13:** `InstagramClient` ga `send_private_reply` va `fetch_media`; xato kodlari `REPLY_WINDOW_EXPIRED`, `ALREADY_REPLIED`.
- **dbml:** `skip_reason` qiymatlari kodda 8 ta (hujjatdagi bilan bir xil). Qo'shimcha: `ig_comments.trigger` doim `NONE` — shopning o'z izohida.

---

## Founder ko'rib chiqishi uchun qarorlar

**Q1. Alohida ruxsat kodlari.**
- **Tanlov:** `messaging.instagram.view` (ega, menejer, operator) va `messaging.instagram.manage` (ega, menejer).
- **Nega:** frontend taxmin qilgan `messaging.channel.connect` faqat egada; menejer post ↔ mahsulot bog'lay olmas edi (db/instagram_comments.md §3).
- **Muqobil:** mavjud ikki kodni ishlatish — frontend o'zgarmaydi, lekin faqat ega boshqaradi.

**Q2. Flag — bitta global.**
- **Tanlov:** `FEATURE_CHANNEL_INSTAGRAM_DM` (Direct bilan umumiy). Dbml'dagi alohida `channel.instagram_comments` flag'i hali yo'q.
- **Nega:** topshiriq shunday; Meta izohlar ruxsati kelmaguncha ikkalasi ham o'chiq.
- **Muqobil:** izohlar uchun alohida flag — Direct yoqiq, izohlar o'chiq holatga imkon beradi.

**Q3. Meta ruxsati yo'q bo'lsa sozlamani yoqib bo'lmaydi.**
- **Tanlov:** `scopes` da `instagram_manage_comments` bo'lmasa `auto_reply`/`sentiment` ni yoqish 422. O'chirish mumkin.
- **Nega:** dbml §7.2. Hozir haqiqiy klient ruxsatlarni aniqlamaydi (bo'sh): standart holatda ikkalasi yoqiq turadi, lekin o'chirib qayta yoqib bo'lmaydi. Ruxsatni aniqlash Meta app review bilan qo'shiladi.
- **Muqobil:** ruxsatni tekshirmaslik — Meta xato qaytarganda bilinadi.

**Q4. Karusel post: javobda hammasi.**
- **Tanlov:** birinchi mahsulot shablon bilan, qolganlari "• Nom — narx" qatorlari. Variantlari har xil narxli bo'lsa "...dan boshlab".
- **Nega:** "Salom!" 5 marta takrorlanmasin. Bog'lanishda variant tanlanmaydi (frontend faqat `product_ids` yuboradi), shuning uchun eng arzon variant narxi.
- **Muqobil:** har mahsulot uchun alohida to'liq shablon (uzun, takroriy).

**Q5. Narx va qoldiq javob paytida.**
- **Tanlov:** narx va "bor/oz qoldi/yo'q" javob yuborilayotganda katalogdan o'qiladi, qoldiq shopning `stock_display` sozlamasi bo'yicha (EXACT bo'lsa "12 dona bor"). Mahsulot yashirilgan yoki narxsiz bo'lsa — umumiy javob.
- **Nega:** eskirgan narx aytilmasin (BL-038, DEC-128).
- **Muqobil:** post bog'langanda narxni saqlab qo'yish — tez, lekin eskirishi mumkin.

**Q6. Yuborishda aniqlanmagan xato (timeout).**
- **Tanlov:** `FAILED`, qayta yuborilmaydi. 429/5xx — 5 martagacha qayta urinish.
- **Nega:** Private Reply faqat bir marta mumkin; yuborildimi noma'lum bo'lsa ikki marta yuborish xavfi bor (messaging'dagi `UNKNOWN` qoidasi kabi).
- **Muqobil:** timeout'da ham qayta urinish — Meta "allaqachon javob berilgan" desa `SKIPPED` bo'ladi, lekin bu xato kodiga tayanadi.

**Q7. Event kalit nomlari dbml'dan farq qiladi.**
- **Tanlov:** `item_id`, `has_content` (dbml'da `comment_id`, `has_text`).
- **Nega:** event PII tekshiruvi `comment`/`text` so'zlarini kalit nomida taqiqlaydi; tekshiruvni bo'shatish xavfliroq.
- **Muqobil:** tekshiruvga istisno qo'shish — tavsiya etilmaydi.

**Q8. Salbiy izoh: vazifa va qoralama keyingi qadamda.**
- **Tanlov:** hozir faqat baholash va "Salbiy" filtri. Menejerga vazifa va AI qoralamasi alohida qadam.
- **Nega:** DEC-148 jadvalida yo'q, vazifa turi va bildirishnoma shabloni alohida qaror talab qiladi (db §7.4).
- **Muqobil:** shu qadamda qo'shish — taxminan yarim kun.

**Q9. Kanal versiyasi har webhook'da oshmaydi.**
- **Tanlov:** `last_webhook_at` Core UPDATE bilan yoziladi (Direct oqimida ham). Post `comment_count` va media ma'lumoti ham post versiyasini oshirmaydi.
- **Nega:** aks holda har kelgan izoh/xabar panelning `If-Match` ini buzardi (sozlamani saqlashda 409 chiqaverardi).
- **Muqobil:** versiya oshaversin — panel har saqlashda qayta yuklashi kerak bo'ladi.
