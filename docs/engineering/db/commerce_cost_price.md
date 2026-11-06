# `commerce` — tannarx (sotib olish narxi): kichik qo'shimcha taklifi

> **Holat:** taklif, 2026-10-27. Qarorlar qabul qilingan, chunki founder ishni to'xtatmasdan davom ettirishni topshirgan. **Founder ko'rib chiqishi kutilmoqda.** Diagramma: [`commerce_cost_price.dbml`](commerce_cost_price.dbml).
> **Nega alohida fayl:** [commerce.md](commerce.md) §3 da tannarx ataylab keyinga qoldirilgan ("foyda hisoboti qo'shilganda kirim qatoriga qo'shiladi"). Tasdiqlangan `commerce.dbml` (DEC-134) o'zgarmaydi; bu — unga qo'shiladigan minimal o'zgarish. Foyda hisoboti — [reporting.md](reporting.md).

Misol: **TechPC**, ega **Ali**, menejer **Vali**, omborchi **Bobur**. Mahsulot — **RTX 4060**, sotuv narxi 4 800 000 so'm.

---

## 0. Muammo oddiy so'z bilan

Ali "o'tgan oy qancha foyda qildim?" deb so'raydi. Sotuv summasi bor, lekin RTX 4060 ni necha pulga olgani tizimda yo'q. Hozir hisobot "tannarx ma'lumoti yo'q" deydi (19 §7.6). Tannarx bitta joyda — kirimda — kiritilsa, qolganini tizim o'zi hisoblaydi.

---

## 1. Usul: o'rtacha tortilgan tannarx

Uch variant ko'rildi:

- **Har kirim qatori o'z narxi bilan, partiyalar bo'yicha (FIFO).** Eng aniq: "birinchi kelgan dona birinchi sotildi". Lekin har sotuvda qaysi partiyadan chiqqanini kuzatish kerak. Band qilish, tez sotuv, karantin va qaytarishda partiya hisobi juda murakkablashadi. Kichik PC shop buni tekshira olmaydi.
- **SKU'da bitta qo'lda yozilgan "tannarx" maydoni.** Eng oddiy. Lekin dollar kursi va yetkazib beruvchi narxi o'zgarib turadi, maydon eskiradi va foyda noto'g'ri chiqadi.
- **O'rtacha tortilgan tannarx — tanlandi.** Har kirimda tizim o'rtachani yangilaydi. Sotuvda shu o'rtacha nusxa qilinadi. Buxgalteriyada keng tarqalgan usul, partiya kuzatuvi kerak emas.

**Formula** (shop bo'yicha, hamma filial birga):

```
yangi o'rtacha = (eski o'rtacha × kirimdan oldingi qoldiq + kirim narxi × kirim soni) / (oldingi qoldiq + kirim soni)
oldingi qoldiq = hamma filiallardagi qoldiq + tekshiruvdagilar
```

**Misol:** omborda 3 ta RTX 4060, o'rtacha 4 000 000 so'm. Bobur 5 ta kiritdi, Vali tannarxni 300 $ deb yozdi, kurs 12 800 → 3 840 000 so'm.
`(4 000 000 × 3 + 3 840 000 × 5) / 8 = 3 900 000 so'm`. Ertaga 1 tasi 4 800 000 ga sotildi: qatorga tannarx 3 900 000 nusxa qilinadi, foyda 900 000 so'm.

---

## 2. `stock_receipt_costs` — kirim qatorining tannarxi

**Nima uchun kerak:** kirim qatorlari daftarda turadi (commerce.md §3). Daftar umumiy va faqat to'ldiriladi, unga pul ustunlarini qo'shish uni chalkashtiradi. Shuning uchun tannarx alohida kichik jadvalda: bir kirim × bir SKU = bir qator.

- **`receipt_id`, `sku_id`, `qty`** — qaysi kirim, qaysi mahsulot, nechta (daftardagi son nusxasi).
- **`unit_cost_minor`, `cost_currency`, `exchange_rate_id`, `exchange_rate_snapshot`** — narx asl valyutada. Yetkazib beruvchilar ko'pincha dollarda sotadi.
- **`unit_cost_uzs_minor`** — so'mga o'girilgan narx, kirim paytidagi shop kursi bilan. Foyda so'mda hisoblanadi, chunki sotuv ham so'mda (DEC-121).
- **`late_entry`** — tannarx kirimdan keyin qo'shildi.
- **`entered_by`** — kim kiritdi.

**Kim kiritadi:** faqat `commerce.cost.edit` ruxsati borlar (ega; menejer — ega ruxsat bersa). Bobur kirimni tannarxsiz kiritadi, Vali keyin "Tannarxni to'ldirish" ro'yxatidan qo'shadi (`LATE_ENTRY`).
**Kim ko'radi:** operator va omborchi hech qayerda ko'rmaydi (BL-065), API javobida ham.
**O'zgarmaydi.** Xato bo'lsa ega o'rtachani qo'lda to'g'rilaydi (`MANUAL_SET`, izoh bilan).
**RLS:** ha.

---

## 3. `sku_costs` — joriy o'rtacha tannarx

**Nima uchun kerak:** sotuv paytida "bu donaning tannarxi qancha?" degan savolga bir qator o'qib javob berish uchun.

- **`avg_unit_cost_uzs_minor`** — joriy o'rtacha, so'mda.
- **`basis_qty`** — oxirgi hisobdagi qoldiq. Ekranda "8 dona bo'yicha o'rtacha" deb tushuntirish uchun.
- **`cost_version`** — har o'zgarishda +1. Hisobot event'larni shu bilan tartiblaydi.
- **`last_reason`** — oxirgi o'zgarish sababi.

**Qachon o'zgaradi:** faqat tannarxli kirim, kechikkan tannarx, qo'lda to'g'rilash yoki import bilan. Sotuv, band qilish va tuzatish o'rtachani o'zgartirmaydi: o'rtacha usulida dona chiqsa, qolganlarning o'rtachasi o'zgarmaydi.
**Qator yo'q** — "tannarx noma'lum". Sotuv qatorida tannarx bo'sh qoladi, hisobot shu sotuvni foydaga qo'shmaydi va buni aytadi.
**Qulf:** kirim qoldiq qatorlarini qulflaydi (commerce.md §0); `sku_costs` qatori shu tranzaksiyada, qoldiqdan keyin qulflanadi.

---

## 4. `sku_cost_changes` — tannarx tarixi

"RTX 4060 tannarxi nega 3 900 000 bo'ldi?" Har o'zgarish bitta qator: sabab, oldingi va keyingi o'rtacha, qoldiq, kirim soni va narxi, kim qildi. Qo'lda to'g'rilashda izoh majburiy. Faqat qo'shiladi.

---

## 5. Mavjud jadvallarga qo'shimchalar

1. **`order_lines.unit_cost_uzs_minor`** — buyurtma **topshirilganda** (`COMPLETE`) joriy o'rtachadan nusxa. Shu paytda qoldiq kamayadi va foyda muzlaydi. Ertaga tannarx o'zgarsa ham, kechagi sotuv foydasi o'zgarmaydi.
2. **`quick_sale_lines.unit_cost_uzs_minor`** — tez sotuv paytida nusxa.
3. **`stock_adjustments.unit_cost_uzs_minor`** — hisobdan chiqarish va kamomad tasdiqlanganda nusxa. Hisobotda "yo'qotishlar qiymati" uchun.
4. **Event'lar** (05 §8.2, egasi yangilaydi): `commerce.order.completed` qatorlariga `unit_cost_uzs_minor?`; `commerce.quick_sale.recorded` qatorlariga `line_total_minor`, `unit_cost_uzs_minor?`, `sold_by`; yangi **`commerce.sku_cost.changed`** (`sku_id`, `avg_unit_cost_uzs_minor`, `cost_version`) — ombor qiymati hisoboti uchun.
5. **Katalog importi** — ixtiyoriy "tannarx" ustuni. Tizimgacha bo'lgan qoldiq birinchi kundanoq tannarxli bo'ladi (`IMPORT`).

Tizim ishga tushgan kuni omborda tannarxsiz qoldiq bo'ladi. Ega uni import yoki "Tannarxni kiritish" ekrani orqali bir marta kiritadi (`MANUAL_SET`). Kiritmasa, o'sha mahsulotlar sotuvi foydaga kirmaydi va hisobot buni ochiq aytadi.

---

## Bog'lanishlar xaritasi

```
stock_receipts ──< stock_receipt_costs ─ ─ ▶ sku_cost_changes (ref_id)
                                         └─ ─ ▶ sku_costs (o'rtacha yangilanadi)
sku_costs ─ ─ ▶ order_lines / quick_sale_lines / stock_adjustments .unit_cost_uzs_minor   (nusxa)
sku_costs ──commerce.sku_cost.changed──▶ reporting.sku_cost_dim
```

---

## Founder ko'rib chiqishi uchun qarorlar

**C1. Tannarx usuli.**
- **Tanlov:** o'rtacha tortilgan tannarx.
- **Afzallik:** partiya kuzatuvi yo'q; band, karantin va qaytarish hisobi o'zgarmaydi; buxgalteriya usuli.
- **Kamchilik:** narx keskin o'zgarganda bitta sotuv foydasi "o'rtacha" bo'ladi, aniq partiyaniki emas.
- **Muqobil:** FIFO partiyalar (aniqroq, ancha murakkab) yoki SKU'da qo'lda tannarx (oddiy, tez eskiradi).

**C2. O'rtacha qaysi darajada?**
- **Tanlov:** shop bo'yicha (hamma filial birga).
- **Nega:** Stage 1 da filiallararo ko'chirish yo'q, xarid odatda markazdan.
- **Muqobil:** filial × SKU. Ko'chirish paydo bo'lganda kerak bo'ladi (Stage 2).

**C3. Tannarx valyutasi.**
- **Tanlov:** asl valyuta va kurs saqlanadi, hisob so'mda (kirim kursi bilan).
- **Nega:** sotuv so'mda; kurs farqi foydaga ta'sir qiladi va bu haqiqiy iqtisodiy natija.
- **Muqobil:** dollarda o'rtacha. Dollar xaridli shopga qulay, lekin so'mdagi sotuv bilan solishtirish uchun baribir o'girish kerak.

**C4. Kim kiritadi va ko'radi?**
- **Tanlov:** ega; menejer — ega ruxsat bersa. Omborchi kirimni tannarxsiz kiritadi, tannarxni keyin menejer qo'shadi.
- **Nega:** BL-065; omborchi ko'pincha xarid narxini bilmaydi.
- **Muqobil:** omborchi ham kiritadi. Tezroq, lekin narx omborchiga ochiq bo'ladi.

**C5. Kechikkan tannarx qanday hisoblanadi?**
- **Tanlov:** kiritilgan paytdagi qoldiq bilan qayta o'rtachalanadi (taxminiy) va `late_entry` belgisi qo'yiladi.
- **Nega:** orqaga qarab hamma sotuvlarni qayta hisoblash murakkab va xatoga moyil.
- **Muqobil:** tannarxsiz kirimni taqiqlash. Aniq, lekin omborchi ishini to'xtatadi.

**C6. Foyda qachon muzlaydi?**
- **Tanlov:** buyurtma topshirilganda (`COMPLETE`) va tez sotuv paytida.
- **Muqobil:** tasdiqlashda. Band va topshirish orasida yangi kirim bo'lsa, tannarx eskirgan bo'ladi.
