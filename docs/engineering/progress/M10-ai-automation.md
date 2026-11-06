# AI avtomatlashtirish (DEC-149) — pilotgacha 4 qism

> **Holat:** backend + panel bitdi (2026-11-02), commit qilinmagan — founder ko'rib chiqishi kutilmoqda.
> **Asos:** DEC-149 (founder tasdiqlagan), tafsilotlar — DEC-151 (taklif).
> **Umumiy qoida:** AI faqat o'qiydi, taklif qiladi va qoralama tayyorlaydi. Narxni, mahsulotni va buyurtmani odam tasdiqlaydi.

---

## 1. Yetkazib beruvchi narx ro'yxati

Ega yetkazib beruvchining Excel, CSV, PDF faylini yoki suratini yuklaydi. Tizim "N ta narxni yangilash"ni taklif qiladi.

```
Fayl yuklash (PRICE_LIST) ──▶ ro'yxat ochiladi (READING) ──▶ fonda AI qatorlarni o'qiydi
  ──▶ kod (SKU kodi / MPN) bo'yicha aniq moslash ──▶ qolganiga 5 nomzod, AI tanlaydi (shubhada — yo'q)
  ──▶ taklif narxi: yetkazib beruvchi narxi × kurs × (1 + ustama) → yaxlitlash ──▶ READY
Ega: ustama, yaxlitlash, qatorni tanlash, qo'lda moslash yoki narx ──▶ "N ta narxni yangilash" ──▶ APPLIED
```

- **Qo'llash:** har qator oddiy narx versiyasi bo'ladi: audit yoziladi, `catalog.price.changed` chiqadi, sabab "Narx ro'yxati: <yetkazib beruvchi>". Bitta qator xato bo'lsa, qolganlari baribir qo'llanadi.
- **Kim ishlatadi:** ega va menejer (`catalog.price_list.run`). Sotuvchi va omborchi ishlata olmaydi.
- **Joriy narx bilan teng qator:** `UNCHANGED` bo'ladi, yangi versiya yozilmaydi.
- **Dollar kursi:** kurs kerak bo'lib, kiritilmagan bo'lsa, qator `NO_RATE` holatida qoladi.
- **Chegaralar:** fayl 10 MB gacha, 500 tagacha qator.
- **Kod:**
  - `app/domains/catalog/price_lists/` (model, schema, `services/reading.py` — sof funksiyalar, `services/price_list_service.py`, `api/routes.py`, `subscribers.py`);
  - migratsiyalar `catalog_0007_price_lists`, `platform_0017_ai_automation`.
- **Panel:** Katalog → "Narx ro'yxati" bo'limi (yuklash, tarix, ko'rib chiqish sahifasi).

## 2. Telegram ovozli xabari

```
Xaridor ovoz yuboradi ──▶ xabar VOICE, biriktirma PENDING
  ──▶ fon vazifasi: Telegram'dan olinadi ──▶ AI matnga o'giradi ──▶ matn xabar ichiga, biriktirma PURGED
  ──▶ AI sotuvchi matnni kutadi (90 soniyagacha) ──▶ oddiy matnli xabar kabi javob beradi
```

- **Audio:** umuman saqlanmaydi (DEC-117), faqat matn qoladi.
- **Chegara:** 120 soniya va 3 MB gacha. Undan uzun bo'lsa, AI sozlanmagan bo'lsa yoki limit tugagan bo'lsa, ovoz o'girilmaydi va xabar avvalgidek operatorga boradi ("Telegram'da tinglang").
- **Panel:** suhbatda "🎤 Ovozli xabar — matnga o'girildi" belgisi va matn ko'rinadi.
- **Kod:** `app/domains/messaging/services/voice.py`, `sending.py` (`_transcribe`), `query_port.py` (`pending_media`), `sales_ai/agent.py` (kutish).

## 3. Mahsulot kartochkasi qoralamasi

- **Qanday ishlaydi:** "Yangi mahsulot" sahifasida "AI bilan to'ldirish" bloki bor. Ega surat yuklaydi yoki model nomini yozib, "To'ldirish"ni bosadi. AI nom, brend, toifa, MPN, variant, holat, xususiyatlar va tavsifni taklif qiladi.
- **Faqat bo'sh maydonlar to'ldiriladi:** ega yozgan narsa ustiga yozilmaydi. Mahsulotni ega o'zi saqlaydi (QORALAMA). Surat yaratilgandan keyin mahsulotga ulanadi.
- **Narx, kafolat, qoldiq:** AI'dan olinmaydi, xususiyat sifatida kelsa ham tashlanadi. Toifa faqat mavjud ro'yxatdan tanlanadi.
- **Kod:** `app/domains/catalog/products/services/card_draft.py`, `api/card_draft_routes.py` (`POST /products/ai-draft`, daqiqasiga 10 ta / xodim).

## 4. "So'rashdi, lekin bizda yo'q" va omborda yo'q tovar

- **Hisobot:** AI qidiruvi hech narsa topmagan (`NOT_FOUND`, "Katalogda yo'q") yoki faqat tugagan mahsulot topgan (`OUT_OF_STOCK`, "Tugagan") so'rovlar yig'iladi.
  - Panel: AI → "So'rashdi, lekin yo'q" (7/30/90 kun).
  - Har dushanba 09:00 da ega va menejerga xabarnoma keladi. Unda faqat soni bo'ladi, haftasiga bitta.
- **Omborda yo'q tovar:** AI sotuvchining yangi qoidasi bor. Avval omborda bor o'xshash variantni taklif qiladi. Xaridor baribir o'shani xohlasa:
  - **"Buyurtma asosida olib kelamiz" yoqilgan:** AI "olib kelib beramiz, narx va sanani menejer aniqlaydi" deydi. Agar ega muddat yozgan bo'lsa, faqat shu muddatni aytadi. So'ng lead yozadi va menejerga ulaydi.
  - **O'chiq (standart):** AI "hozir yo'q" deydi va menejerga ulaydi.
- **Prompt versiyasi:** `seller-2026-11-v2`.
- **Kod:** `app/domains/sales_ai/services/demand.py`, `jobs.py` (`sales_ai_demand_gaps_weekly`), `prompts.py` (11-qoida va siyosat), migratsiya `sales_ai_0004_special_order`.

## 5. Umumiy o'zgarishlar

- **LLM qatlami:** `MediaPart` qo'shildi (rasm, PDF, ovoz).
  - Gemini: uchalasini ham qabul qiladi.
  - Claude: rasm va PDF ni qabul qiladi; ovozda `unsupported_media` xatosi beradi.
- **Xarajat maqsadlari:** `PRICE_LIST_READ`, `VOICE_TRANSCRIBE`, `CARD_DRAFT`. Uchalasi ham shopning umumiy AI limitiga kiradi.
- **AI ishlamaganda:** AI sozlanmagan yoki limit tugagan bo'lsa, 422 `ai_unavailable` (`params.reason`) qaytadi.

## 6. Tekshiruv

- **Yangi integratsiya testlari:**
  - `test_price_lists.py` — 3 ta: o'qish, moslash, ustama, qo'llash, xato, kirish huquqi, izolyatsiya, kartochka qoralamasi;
  - `test_voice.py` — 3 ta;
  - `test_demand_gaps.py` — 2 ta.
- **Statik tekshiruvlar:** mypy (565 fayl), ruff, import-linter toza. Panel: typecheck va eslint toza.
- **Hali qilinmagan:** haqiqiy Gemini kaliti bilan sinov va brauzerda qo'lda sinov. O'zbekcha sinov to'plami (`engineering/16`) DEC-149 shartida bor, u keyingi qadam.
