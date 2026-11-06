# Stage 2 — shoplar tarmog'i: birinchi bo'lak (M21, M23, M24)

> **Holat:** backend + panel (2026-11-02), commit qilinmagan — founder ko'rib chiqishi kutilmoqda.
> **Asos:** `business/01` Stage 2, `engineering/28`, [db/network.md](../db/network.md), DEC-152 (taklif).
> **Stage 2 tugash mezoni (business/01):**
> - shop o'zi ulanadi — **M21 bor**;
> - ikki va undan ortiq shop bir xil modelni bitta umumiy mahsulotga bog'laydi — **M23, aniq MPN bo'yicha bor**;
> - qaytarib olingan taklif darhol ko'rinmaydi — **M24 bor**;
> - ma'lumot manbasi ko'rinadi — **bog'lash usuli va tarixi bor**.

---

## 1. M21 — shopning o'zi ro'yxatdan o'tishi

```
"Do'kon ochish" ──▶ telefon ──▶ SMS kod (6 raqam, 10 daqiqa) ──▶ do'kon nomi, STIR, ism, parol
  ──▶ shop DRAFT (signup_source=SELF) + ega ACTIVE + darhol panelga kiradi (/setup)
  ──▶ ega profilni to'ldiradi ──▶ "tekshiruvga yuborish" ──▶ platforma admini ACTIVE qiladi (o'zgarmagan FSM-01)
```

- **Flag:** `FEATURE_SELF_SIGNUP`, standart o'chiq (yopiq beta). O'chiq bo'lsa API 501 qaytaradi va kirish sahifasida havola ko'rinmaydi.
- **SMS:**
  - `SMS_PROVIDER=fake` — dev va testlar uchun;
  - `SMS_PROVIDER=eskiz` — haqiqiy yuborish, `ESKIZ_EMAIL`, `ESKIZ_PASSWORD`, `ESKIZ_FROM` bilan;
  - production'da `fake` bilan flag'ni yoqib bo'lmaydi.
- **Firibgarlikdan himoya:**
  - Kod va urinishlar: kod faqat xesh bilan saqlanadi, 5 ta urinish, qayta yuborish 60 soniyadan keyin, bitta telefonga kuniga 5 ta so'rov. Noto'g'ri urinish hisoblagichi rollback bo'lmaydi.
  - Limitlar: IP bo'yicha 10 ta yuborish/soat, telefon bo'yicha 3 ta/10 daqiqa.
  - STIR majburiy va noyob.
  - Shop baribir platforma tekshiruvidan o'tadi; panelda "o'zi ro'yxatdan o'tgan" belgisi (`signup_source`) ko'rinadi.
- **Hali yo'q:** tarifni o'zi tanlash (M26 bilan birga keladi).
- **Kod:**
  - `app/platform/sms/sender.py`;
  - `app/platform/shops/services/signup_service.py`, `api/signup_routes.py`;
  - migratsiya `platform_0018_self_signup`.
- **Panel:** `packages/auth/src/signup.tsx`, `apps/shop-dashboard/src/app/signup`.

## 2. M23 + M24 — umumiy mahsulot va ommaviy takliflar (`network` domeni)

- **Yangi sxema:** `network` (`schemas.sql`, alembic, `OUTBOX_SCHEMAS`).
- **Jadvallar:**
  - `canonical_products` — ochiq ma'lumot, RLS yo'q;
  - `sku_links` — shop ichida, yoki admin ko'rib chiqishida;
  - `public_offers` — shop ichida, yoki ommaviy o'qishda faqat ACTIVE qatorlar.
- **Ommaviy qilish:**
  - Standartda hammasi yopiq. Ega mahsulotni tanlab "Global qidiruvga chiqarish"ni bosadi. Faqat ACTIVE shop chiqara oladi, aks holda `SHOP_NOT_VERIFIED` xatosi.
  - Narxi yo'q yoki saytda chiqarilmagan mahsulot chiqmaydi va sababi ko'rsatiladi.
- **Proyeksiyada nima bor:** nom, brend, toifa, narx, holat, kafolat va mavjudlik (bor / kam / yo'q). Tannarx, xaridor va aniq qoldiq yo'q.
- **Bog'lash:**
  - brend va MPN aniq mos kelsa, mavjud umumiy mahsulotga bog'lanadi;
  - umumiy mahsulot yo'q bo'lsa, yangisi yaratiladi;
  - MPN yoki brend yo'q bo'lsa, platforma navbatiga tushadi.
  - Nom o'xshashligi bo'yicha hech qachon bog'lanmaydi.
- **Yangilanish (event'lardan):**
  - Tinglanadigan event'lar: narx, mahsulot holati, SKU, kurs, qoldiq. Har o'zgarishda `listing_version` +1 va `network.public_offer.updated|withdrawn` chiqadi.
  - Ega yopgan taklif avtomatik qaytmaydi. Tizim sababi (narx yo'q, sotuvda yo'q, shop to'xtatilgan) tuzalsa, taklif o'zi qaytadi.
- **Yopish:** bitta tranzaksiyada `WITHDRAWN` bo'ladi va outbox'ga yoziladi.
- **Shop holati:** shop to'xtatilsa yoki yopilsa, hamma takliflari `SUSPENDED` bo'ladi. Qayta faollashsa, takliflar qaytadi.
- **Platforma admini (navbat):**
  - mavjud umumiy mahsulotni qidirib bog'laydi, yoki yangisini yaratadi, yoki "bog'lanmaydi" deydi;
  - har qaror audit'ga yoziladi va `network.canonical_match.changed` chiqadi;
  - ruxsat: `platform.network.review` (PLATFORM_ADMIN, SPEC_EDITOR).
- **Import qoidasi:** `network` `catalog` va `commerce` kodini import qilmaydi. Bu import-linter shartnomasi bilan tekshiriladi (TC-NET-04). Ma'lumot faqat `CatalogQueryPort.network_facts` va `StockQueryPort.availability` orqali olinadi.
- **Kod:** `app/domains/network/`, migratsiya `network_0001`, `network_0002`.

## 3. M25 — filiallar orasida ko'chirish

```
Jo'natish (manba filial) ──▶ daftarda TRANSFER_OUT: manbadan −qty (band qilingani ketmaydi) ──▶ IN_TRANSIT
   yo'lda: hech qaysi filialda sotuvga mavjud emas (BL-082)
Qabul ──▶ TRANSFER_IN: +kelgan son ──▶ RECEIVED; kam kelsa — kamomad va ega/menejerga vazifa
Bekor (yo'lda bo'lsa) ──▶ manbaga qaytadi ──▶ CANCELLED
```

- **Filial doirasi:** omborchi faqat o'z filialidan jo'natadi va o'z filialiga qabul qiladi.
- **To'ldirish tavsiyasi:** bir filialda tovar tugagan, boshqasida 2 va undan ko'p bo'lsa, ortiqchaning yarmini ko'chirish taklif qilinadi.
- **Kod:** `commerce/inventory/services/transfer_service.py`, migratsiya `commerce_0011`.

## 4. M26 — tariflar va hisob-fakturalar

```
Yangi shop ──▶ TRIAL (PILOT, 30 kun)
Davr tugashiga 5 kun qolganda ──▶ hisob (ISSUED), egaga xabar
Davr tugadi: to'langan ──▶ yangi davr ACTIVE (tanlangan tarif shu yerda kuchga kiradi)
             to'lanmagan, 7 kun o'tdi ──▶ PAST_DUE (savdo to'xtamaydi; to'xtatish — platforma qarori)
```

- **Tariflar:** PILOT, Start, PC Pro, Business. Limitlar: filial, xodim, mahsulot, AI javoblari. Narxlarni founder platforma panelida kiritadi; narx kiritilmaguncha hisob chiqmaydi.
- **To'lov:** tizimdan tashqarida (DEC-100). Admin "to'landi" deb izoh bilan belgilaydi, avtomatik yechib olish yo'q (BL-083).
- **Kod:** `app/platform/billing/`, migratsiya `platform_0019`, rejali ish `billing_cycle` (har kuni 06:00).

## 5. M29 — "Tasdiqlangan do'kon" va shikoyatlar

- **Belgi:** faqat admin beradi. Dalil matni majburiy, muddat 1…24 oy. Muddati o'tsa belgi o'zi ko'rinmaydi, olib tashlash sabab bilan qilinadi (BL-087). Global qidiruvda ko'rinadi.
- **Shikoyat:** xaridor global qidiruvdan yuboradi, shaxsi yozilmaydi. Admin rad etadi yoki taklifni yashiradi (`PLATFORM_REPORT`). Yashirilgan taklifni ega o'zi qaytara olmaydi (BL-088).
- **Kod:** `network/services/trust.py`, migratsiya `network_0004`.

## 6. M30 + M22 — hamkor API va kassa/ERP qoldig'i

- **Kalitlar:**
  - Faqat ega yaratadi. Sir bir marta ko'rsatiladi, bazada HMAC xesh saqlanadi.
  - Ruxsatlar: `catalog.read`, `stock.read`, `prices.write`, `stock.write`.
  - Tezlik: kalitga 120 so'rov/daqiqa. Bekor qilingan kalit darhol 401 qaytaradi (BL-089).
- **Endpoint'lar** (`/api/v1/partner`):
  - `GET /skus`;
  - `PUT /skus/{id}/price` — oddiy narx versiyasi va audit, `actor` = kalit;
  - `PUT /stock`;
  - `GET /stock/reports/{id}`.
- **Qoldiq qoidalari (BR-X12, TC-019):**
  - `network` qoldiqni yozmaydi, faqat event chiqaradi.
  - Yozishdan oldin `commerce` tekshiradi:
    - eski ma'lumot (`observed_at` oxirgi daftar yozuvidan oldin) — `STALE`, ustidan yozilmaydi;
    - band qilinganidan kam — `BELOW_COMMITTED`.
  - Tekshiruvdan o'tgan farq tuzatish bo'ladi: standartda tasdiqqa tushadi, kalitda "avtomatik qo'llash" yoqilgan bo'lsa darhol qo'llanadi.
- **Kod:** `network/services/api_keys.py`, `api/partner_routes.py`, `commerce/inventory/services/pos_stock.py`, migratsiyalar `network_0005`, `network_0006`.

## 7. Tekshiruv

- **Testlar:**
  - `test_self_signup.py` (3);
  - `test_network.py` (2);
  - `test_marketplace.py` (3);
  - `test_partner_api.py` (2);
  - `test_transfers.py` (2);
  - `test_billing.py` (2).
- **Statik tekshiruvlar:** mypy, ruff, import-linter toza.

## 8. Stage 2 da qolganlari

- **M27** — AI bilim markazi. Asosiy qismi (FAQ va siyosatlar, faqat tasdiqlangani AI'ga beriladi) 6b da bor. Alohida "bilim markazi" ekrani keyin qo'shiladi.
- **M22** — konkret ERP/kassa ulagichlari (1C va boshqalar) birinchi tasdiqlangan hamkor bilan quriladi. Umumiy ulagich (hamkor API) tayyor.
