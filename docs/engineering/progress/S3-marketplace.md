# Stage 3 — global qidiruv (M31–M39)

> **Holat:** backend + xaridor sayti `apps/marketplace` (2026-11-03), commit qilinmagan — founder ko'rib chiqishi kutilmoqda.
> **Asos:** `business/01` Stage 3, `engineering/28`, [db/marketplace.md](../db/marketplace.md), DEC-153, DEC-154 (taklif).
> **Ommaga e'lon qilish sharti (`engineering/28` §13):** yetarli shop qamrovi, tekshirilgan solishtirishlar, reklama oshkoraligi va yo'naltirish auditi tayyor bo'lmaguncha ochilmaydi. Kod tayyor, ochish — founder qarori.

---

## 1. Nima bitdi

- **M31 global qidiruv:** `GET /public/marketplace/search` faqat ACTIVE shoplarning ACTIVE takliflarini qaytaradi.
  - Natijalar umumiy mahsulot bo'yicha guruhlanadi: narx oralig'i, nechta do'konda borligi, omborda borlari soni ko'rinadi.
  - Har so'rov jadvalning o'zidan o'qiydi: qaytarib olingan taklif darhol yo'qoladi, kechikadigan indeks yo'q (TC-015).
- **M32 narx solishtirish:** `GET /products/{id}` hamma takliflarni narx bo'yicha beradi.
  - Holat, kafolat, mavjudlik va oxirgi tekshiruv vaqti ko'rinadi.
  - "Eng arzon" yorlig'i yo'q, chunki yetkazish narxi noma'lum (BL-092).
- **M33 xarita va masofa:**
  - Olib ketish filiallari faqat shop `branch` maydonini yoqqanda ko'rinadi.
  - Masofa xaridor joylashuvini bergandagina hisoblanadi, saqlanmaydi va "to'g'ri chiziq bo'yicha" deb yoziladi (BL-095, BL-096).
- **M34 global AI maslahatchi:** `POST /advisor`.
  - Ikkita tool bor: ommaviy qidiruv va solishtirish. Shop AI tool'lari, tannarx va suhbatlar unga ochiq emas (BL-098).
  - Javob manbalar ro'yxati bilan qaytadi. PII yashiriladi.
  - Xarajat platformaga yoziladi (`MARKET_ADVISOR`). Limit: IP bo'yicha 10 ta/daqiqa va 60 ta/kun.
- **M35 shopga yo'naltirish:** `POST /offers/{id}/visit` taklif hali ACTIVE ekanini qayta tekshiradi va shop saytidagi mahsulot sahifasi manzilini beradi. Yozuv shaxsiz (IP xeshi).
- **M36 narx ogohlantirishi:** global bot orqali ishlaydi.
  - Xaridor o'zi yoqadi va bir bosishda bekor qiladi.
  - Narx faqat yangi tekshirilgan narx bo'yicha va 24 soatda ko'pi bilan bir marta xabar qilinadi (BL-102, BL-103).
  - Hozircha xaridor identifikatori Telegram chat'i (SMS va parolsiz).
- **M37 reklama:**
  - Reklama oddiy natijalardan alohida (`sponsored`, ko'pi 2 ta), "Reklama" deb belgilanadi.
  - Oddiy saralash va AI maslahatchiga ta'sir qilmaydi.
  - Har kampaniyani platforma tasdiqlaydi, bosishlar sanaladi (BL-099, BL-104).
- **M38 SEO:**
  - `GET /sitemap` faqat amaldagi takliflari bor umumiy mahsulotlarni beradi.
  - Saytda har mahsulot uchun bitta asosiy manzil va JSON-LD (Product + AggregateOffer) bor (BL-106, BL-107).
- **M39 global Telegram bot:** `/webhooks/global-telegram`.
  - Shop botlaridan alohida token va jadvallar ishlatadi (BL-108).
  - Qidiruv, "Ko'rish" va "Narx tushsa xabar ber" bor.
  - Chat raqami shifrlangan, bot bloklansa xabar yuborish to'xtaydi.

## 2. Sozlamalar

- `MARKETPLACE_PUBLIC_URL` — xaridor sayti manzili.
- `GLOBAL_BOT_TOKEN`, `GLOBAL_BOT_USERNAME`, `GLOBAL_BOT_WEBHOOK_SECRET` — bo'sh bo'lsa bot o'chiq.
- Xaridor sayti: `NEXT_PUBLIC_API_URL`, `API_INTERNAL_URL`, `MARKETPLACE_PUBLIC_URL`, `NEXT_PUBLIC_GLOBAL_BOT_USERNAME`.

## 3. Tekshiruv

- **Testlar:**
  - `test_marketplace.py` (6 ta): qidiruv, solishtirish, yo'naltirish, yopilgan taklif, narx yashirilishi, belgi va shikoyat, AI maslahatchi, sitemap, xarita, reklama;
  - `test_global_bot.py` (1 ta).
- **Statik tekshiruvlar:** mypy, ruff, import-linter toza.

## 4. Keyin

- Pullik reklama hisobi (hozir — hisob-faktura orqali, qo'lda).
- Telefon raqamli xaridor akkaunti (saqlanganlar saytda).
- Alohida qidiruv servisi — hajm o'sganda (`engineering/28` §9).
- Oltin to'plam (500–1000 juftlik) bilan bog'lash sifatini o'lchash.
