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
