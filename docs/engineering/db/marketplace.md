# Stage 3 — global qidiruv, narx solishtirish, shopga yo'naltirish (M31, M32, M35) — birinchi bo'lak

> **Holat:** dizayn, PROPOSED (2026-11-02, Claude — founder ko'rib chiqadi). Asos: `engineering/28` §7–§11, BL-090…101.
> **Qoida:** global qidiruv faqat ommaviy ma'lumotni o'qiydi (`network.public_offers` ACTIVE, ommaviy RLS varianti). Shoplarning ichki ma'lumoti (tannarx, xaridor, qoldiq soni, chat) unga ochiq emas.

---

## Oqim

```
Xaridor ──▶ GET /public/marketplace/search?q=&category=&max_price=&in_stock=
   ──▶ NetworkQueryPort.search: ACTIVE takliflar (faqat ACTIVE shoplar) ──▶ umumiy mahsulot bo'yicha guruh
   ──▶ natija: mahsulot, takliflar soni, eng past va eng yuqori narx, "omborda bor" takliflar soni
Xaridor ──▶ GET /public/marketplace/products/{canonical_id} ──▶ shu mahsulotning hamma takliflari:
   shop, narx, holat, kafolat, mavjudlik, oxirgi tekshiruv vaqti — narx bo'yicha
Xaridor "Do'konga o'tish" ──▶ POST /public/marketplace/offers/{offer_id}/visit
   ──▶ taklif hali ACTIVE ekani qayta tekshiriladi (read-time deny, BL-080)
   ──▶ yo'naltirish yozuvi (shaxsiy ma'lumotsiz) ──▶ shop saytidagi mahsulot sahifasi manzili
```

## Qoidalar

- **Qaytarib olingan taklif ko'rinmaydi** (BR-X07, TC-015). Har so'rov jadvalning o'zidan o'qiydi; alohida kechikadigan indeks yo'q.
- **Narx bo'yicha saralash.** "Eng arzon" degan yorliq yo'q: yetkazish narxi noma'lum (BL-092, TC-017). Faqat "narx bo'yicha" saralanadi.
- **Ishonch belgilari:** narx so'mda (dollar narxi shop kursi bilan, kursi yo'q bo'lsa ommaviy bo'lmaydi) va "oxirgi tekshirilgan" vaqt ko'rsatiladi.
- **Umumiy mahsulotga bog'lanmagan taklif** alohida natija bo'lib chiqadi va solishtirishga qo'shilmaydi.
- **Yo'naltirish yozuvi** (`network.referrals`): `offer_id`, `shop_id`, vaqt, IP xeshi. Xaridor shaxsi yozilmaydi. Shop panelida "global qidiruvdan kelganlar" soni ko'rinadi.
- **Reklama:** reklama o'rinlari, global AI maslahatchi, xarita, xaridor akkaunti va global Telegram bot keyingi bo'laklarda keladi (M33, M34, M36, M37, M39).

---

## Xaridor akkaunti (buyers) — SMS kod bilan kirish va saqlanadigan tarix

> **Holat:** amalga oshirildi (migratsiya `network_0010`). Hamma jadval `network` sxemasida, **platforma darajasi, RLS yo'q** (`global_bot_chats` kabi). `buyers` o'chsa, bolalari `on delete cascade` bilan o'chadi.

```
POST /public/marketplace/auth/start {phone}  ──▶ SMS kod (6 raqam, 10 daq; qayta yuborish 60 s; 5 urinish; so'rovga 5 yuborish; telefonga kuniga 5 so'rov)
POST /public/marketplace/auth/verify {request_id, code} ──▶ xaridor (birinchi kirishda yaratiladi) + session_token
Authorization: Bearer <session_id>.<sir>  ──▶ /me/*, ixtiyoriy: /search, /products/{id}, /advisor
```

- **`buyers`**: `phone_hash` (HMAC, unique), `phone_enc` (shifrlangan), `name`, `locale` (uz|ru|en), `created_at`, `last_seen_at`.
- **`buyer_login_codes`**: `phone_hash`, `phone_enc` (faqat kod tasdiqlanguncha; keyin null), `code_hash`, `attempts`, `sends`, `last_sent_at`, `expires_at`, `consumed_at`, `ip_hash`. Kunlik ish 1 kundan eskisini o'chiradi.
- **`buyer_sessions`**: `buyer_id`, `token_hash` (sirning sha256), `expires_at` (60 kun), `revoked_at`, `user_agent`, `last_used_at`. Sirpanuvchi: `last_used_at` 1 kundan eski bo'lsa, `expires_at` yana 60 kunga suriladi. Muddati o'tgan/bekor qilinganiga 7 kun bo'lgani kunlik ishda o'chadi (`buyer_cleanup`).
- **`buyer_views`**: PK `(buyer_id, canonical_id)`, `viewed_at`; upsert; eng yangi 200.
- **`buyer_searches`**: `query`, `category`, `searched_at`; oxirgisi bilan bir xil bo'lsa yozilmaydi; eng yangi 100.
- **`buyer_favorites`**: PK `(buyer_id, canonical_id)`, `saved_price_uzs_minor` (saqlash paytidagi eng past narx), `saved_at`; ko'pi 200.
- **`buyer_advisor_messages`**: `role` (user|assistant), `text`, `sources` (jsonb), `created_at`; eng yangi 200 (ko'rsatiladigani 100).

Qoidalar: tarix yozuvi asosiy javobdan alohida qisqa tranzaksiyada, xatosi faqat logga yoziladi; faqat kirgan xaridor uchun. Mahsulot hozir ommaviy bo'lmasa, tarixdan tushadi, sevimlilarda qoladi (hozirgi maydonlar null). Telefon, kod va token logga yozilmaydi; `DELETE /me` hammasini butunlay o'chiradi. `dev_code` faqat `FakeSmsSender` bilan qaytadi (prod'da fake SMS taqiqlangan).
