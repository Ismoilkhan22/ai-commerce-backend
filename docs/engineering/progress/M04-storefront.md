# 4-modul — Shop sayti (backend)

> **Holat:** backend bitdi — 2026-10-26. **Commit qilinmagan**, founder ko'rib chiqishini kutmoqda. Frontend (xaridor sayti `shop-storefront` va shop panelida "Shop sayti" bo'limi) — keyingi qadam.
> **TZ:** [db/storefront.dbml](../db/storefront.dbml) va [storefront.md](../db/storefront.md) (DEC-135), business/02 M07, DEC-115, DEC-121, DEC-128, DEC-134, DEC-136, [21](../21-frontend.md) §6, [08](../08-cache-and-realtime.md) §4–§5, [26](../26-privacy-and-retention.md) §8. Rejadagi band: S1-07.
> **Repo:** `ai-commerce-backend` (`feat/s0-foundation`).

---

## 1. Nima bitdi — qisqacha

Har shopning endi o'z sayti bor. Ega panelda logotip, rang, kontaktlar va uchta ma'lumot sahifasini yozadi, keyin saytni ochadi. Xaridor katalogni ko'radi, savatchani yig'adi va buyurtma so'rovini yuboradi. So'rov operatorga "Tasdiq kutilmoqda" holatida tushadi, mahsulot esa band qilinmaydi. Xaridor buyurtmasi holatini maxsus havola orqali kuzatadi.

```
Ega: "Shop sayti" ──▶ logotip, rang, telefon, sahifalar ──▶ "Ko'rib chiqish" (30 daqiqalik havola)
     ──▶ "Saytni ochish" (telefon majburiy) ──▶ Ochiq (LIVE) ⇄ Vaqtincha yopilgan (PAUSED)
Xaridor: techpc.platforma.uz ──▶ katalog (faqat chiqarilgan, so'mda) ──▶ mahsulot sahifasi (filial bo'yicha mavjudlik)
     ──▶ savatcha (brauzerda) ──▶ ism, telefon, olib ketish/yetkazish, rozilik ──▶ "Buyurtma berish"
     ──▶ commerce: narx va filial qayta tekshiriladi ──▶ "Tasdiq kutilmoqda" (biriktirilmagan, band yo'q)
     ──▶ "Qabul qilindi" + holat havolasi ──▶ /orders/{token}: Qabul qilindi → Tasdiqlandi → Tayyorlanmoqda → Tayyor → Topshirildi
```

Xaridor nima ko'radi — shop holati va sayt holati birga hal qiladi:

```
shop faol + sayt ochiq                       ──▶ sayt ishlaydi (LIVE)
shop qoralama yoki tekshiruvda, yoki sayt qoralama ──▶ "Sayt tez orada ochiladi" (COMING_SOON) — faqat shop nomi
shop to'xtatilgan yoki sayt to'xtatilgan     ──▶ "Vaqtincha ishlamayapti" (PAUSED), buyurtma qabul qilinmaydi
shop yopilgan yoki bunday manzil yo'q        ──▶ "Topilmadi" (404)
```

---

## 2. Rejadagi bandlar

**Bajarildi:**

- [x] `storefront.sites` va `storefront.pages` jadvallari (DBML bo'yicha), RLS (FORCE).
- [x] Shop paneli API: sozlamalarni o'qish (ega, menejer), o'zgartirish va ochish/yopish (faqat ega), uchta tayyor sahifa, ko'rib chiqish tokeni.
- [x] Sayt holati: qoralama → ochiq ⇄ to'xtatilgan, `transition_log` va audit bilan.
- [x] storefront.md §8 takliflari:
  - `shop_policies.delivery_enabled` — yetkazish o'chiq bo'lsa, formada faqat olib ketish;
  - `SITE_LOGO` fayl turi — ochiq, 2 MB gacha.
- [x] Ommaviy API `/api/v1/storefront/{slug}/*`: sayt, toifalar, katalog, mahsulot, sahifa, filiallar, maxfiylik siyosati.
- [x] Xavfsiz o'qish (storefront.md §5):
  - slug → shop (10 daqiqa keshda), shop holati har so'rovda bazadan;
  - READ ONLY tranzaksiya, shop konteksti (RLS);
  - faqat ochiq maydonlar (TC-SEC-09).
- [x] Kesh (08 §4): ro'yxat va mahsulot 60 s + jitter, sozlamalar 300 s; mahsulot holati har so'rovda qayta tekshiriladi (UAT-M07).
- [x] Buyurtma so'rovi (DEC-115) — `commerce` ichida:
  - takror himoyasi (`source_request_id`);
  - rozilik versiyasi tekshiriladi;
  - filialda yo'q mahsulot ham qabul qilinadi va belgilanadi (DEC-135);
  - telefon shifrlangan;
  - band qilinmaydi.
- [x] Holat sahifasi: token bo'yicha, PII'siz, bazada faqat tokenning xeshi.
- [x] So'rovlar chegarasi: o'qish, buyurtma so'rovi va holat sahifasi uchun.
- [x] Sayt uchun alohida CORS: cookie'siz, faqat sayt manzillari.
- [x] Demo ma'lumot: 5 ta sayt — 3 ta ochiq, TechPC qoralama, ByteShop to'xtatilgan shop.

**Ataylab keyinga qoldirildi:**

- `public_products` nusxa jadvali va shopning o'z domeni (`site_domains`) — DEC-135. Fon ishlari bilan (5-modul).
- Kesh invalidatsiyasi katalog va ombor event'lari bilan (08 §4.3). Hozir ro'yxat 60 s da o'zi yangilanadi, mahsulot holati esa darhol tekshiriladi. Event'lar — S0-06.
- Stampede himoyasi (08 §4.4) — pilot hajmida kerak emas.
- Qidiruv uchun trigram indeksi (pg_trgm). Kengaytma o'rnatish migratsiya roliga qo'shimcha huquq talab qiladi. Pilot hajmida (shop ichida bir necha ming mahsulot) oddiy `ILIKE` yetadi.
- Katalogdagi qo'shimcha filtrlar: narx oralig'i, brend, holati, "faqat borlari" (storefront.md §8). Hozir bor: toifa, matn bo'yicha qidiruv va saralash.
- Captcha (10 §5.2) — keyin.
- Xaridorga Telegram yoki SMS xabar — 5-modul. Hozir xaridor holatni havoladan ko'radi.
- SVG logotip — tozalovchisiz u skript tashiy oladi, shuning uchun hozir faqat PNG, JPEG va WebP.

**Kartadan va DBML'dan farqlar:**

- **`sites` va `pages` da RLS bor**, DBML esa "RLS kerak emas" degan edi. Ma'lumot ochiq, lekin sayt o'qishi baribir shop kontekstini o'rnatadi. RLS esa panel boshqa shop sozlamasiga tegolmasligini bazaning o'zida kafolatlaydi. DBML va storefront.md yangilandi.
- **Rang kontrasti.** WCAG 1.4.11 qoidasi qo'llandi: asosiy rang fonga nisbatan kamida 3:1, oq fonda `#FFFFFF`, to'q fonda `#0F172A` ga nisbatan. Tugma ustidagi matn rangini (oq yoki qora) tizim o'zi tanlaydi (`accent_text_color`).
- **SKU kodi ommaviy javobda yo'q**, DBML'dagi `public_products` dagidek. Qidiruv esa SKU kodi bo'yicha ham ishlaydi.
- **Kursi eskirgan dollar narxi saytda ko'rsatiladi.** Saytdagi narx baribir "taxminiy". Tasdiqlashda eskirgan kurs operatorni to'xtatadi (DEC-134). Kursi umuman yo'q narx esa ko'rsatilmaydi (BL-012).
- **Holat sahifasi sayt to'xtatilganda ham ishlaydi:** xaridor o'z buyurtmasini ko'radi. Faqat shop yopilsa — 404.

---

## 3. Fayllar xaritasi

```
app/
├── shared/
│   ├── cache/
│   │   ├── __init__.py              # Cache, MemoryCache, RedisCache
│   │   ├── backends.py              # get/set/delete/incr; Redis uzilsa — xato yutiladi, javob DB'dan
│   │   └── keys.py                  # cos:v1:shop:{id}:… va cos:v1:global:… — parametrlar hash'lanadi
│   ├── consent.py                   # rozilik versiyasi, matn barmoq izi (26 §8)
│   ├── storefront_cors.py           # sayt CORS'i: cookie'siz, regex bo'yicha manzillar
│   ├── contracts/storefront.py      # SitePort, SiteAccess, ensure_open
│   ├── contracts/catalog.py         # + ommaviy tiplar va metodlar (public_*)
│   ├── errors/{base,catalog}.py     # + SITE_NOT_AVAILABLE
│   ├── request_guard.py             # storefront yo'llari butunlay qayta urinilmaydi (rate limit tashqarida)
│   └── i18n/locales/{uz,ru,en}.yml  # + consent.*, privacy.*, errors.SITE_NOT_AVAILABLE
├── platform/
│   ├── shops/{models/orm.py, schemas.py, services/shop_service.py}   # delivery_enabled
│   └── storage/{models/orm.py, schemas.py, services/file_service.py} # SITE_LOGO
├── domains/
│   ├── catalog/query_port.py        # public_categories / public_products / public_product / public_visible
│   ├── storefront/                  # YANGI domen
│   │   ├── domain_manifest.py       # shop + storefront surface, SITE_RULES, ruxsatlar
│   │   ├── models/orm.py            # Site, Page
│   │   ├── schemas.py               # panel va ommaviy sxemalar (ruxsat etilgan maydonlar)
│   │   ├── permissions.py           # storefront.site.view (ega, menejer), .edit (ega)
│   │   ├── state_machine.py         # PUBLISH, PAUSE, RESUME
│   │   ├── common.py                # slug, kontrast, PreviewSigner, kesh kalitlari va cached_json
│   │   ├── site_gate.py             # SitePort: slug → shop → holat, shop konteksti
│   │   ├── providers.py
│   │   ├── services/site_service.py   # panel: sozlamalar, sahifalar, ochish/yopish, ko'rib chiqish
│   │   ├── services/public_service.py # ommaviy o'qish + kesh
│   │   └── api/{routes.py, public_routes.py}
│   └── commerce/
│       ├── orders/storefront_schemas.py
│       ├── orders/services/storefront_service.py  # buyurtma so'rovi, holat sahifasi
│       ├── orders/api/storefront_routes.py        # /order-requests, /orders/{token}
│       ├── orders/services/order_service.py       # next_order_number, add_lines (umumiy)
│       ├── providers.py                           # + storefront, site, stock porti
│       └── domain_manifest.py                     # + storefront router
├── db/
│   ├── migrations/storefront/versions/storefront_0002_sites_pages.py
│   ├── migrations/platform/versions/platform_0007_storefront_support.py
│   ├── seed/storefront_seed.py      # 5 ta demo sayt
│   └── models.py                    # storefront modellari ro'yxatda
├── config/settings.py               # storefront_public_url, storefront_cors_origin_regex
└── main.py                          # kesh, storefront servislari, sayt CORS'i
tests/
├── integration/test_storefront.py   # 14 ta
├── unit/test_storefront_units.py    # 25 ta
└── architecture/fsm_spec.yaml       # + storefront.site
```

---

## 4. Qaysi faylda nima bor

### 4.1 Saytni topish — `storefront/site_gate.py`

- **`SiteGate.resolve(db, slug, preview_token)`:**
  - slug formati noto'g'ri, bunday shop yo'q yoki shop yopilgan — bir xil 404, shop borligini taxmin qilib bo'lmaydi;
  - `slug → shop_id` 10 daqiqa keshda; shop qatori esa har so'rovda bazadan (to'xtatish darhol ishlaydi). Slug o'zgargan bo'lsa, kesh o'chiriladi va qayta qidiriladi;
  - `set_shop_context` — narx, kurs, qoldiq va fayllar RLS bilan faqat shu shopniki;
  - natija `SiteAccess`: `state` va `preview`.
- **`site_state(shop_status, site_status)`** — xaridor nima ko'radi (§1 dagi jadval).
- **`ensure_open(access, for_order=False)`** (`shared/contracts/storefront.py`):
  - o'qishga LIVE yoki egasining ko'rib chiqish rejimi kerak;
  - buyurtmaga faqat LIVE (ko'rib chiqish rejimida emas);
  - aks holda 409 `SITE_NOT_AVAILABLE` va `details.state`.

### 4.2 Ommaviy o'qish — `storefront/services/public_service.py`

- **`site`** — ochiq bo'lsa: rang (`accent_text_color` bilan), logotip, kontaktlar (Telegram/Instagram havolasini tizim yasaydi), chiqarilgan sahifalar menyusi, `delivery_enabled`, `stock_display`, olib ketish joylari soni, rozilik matni va versiyasi, rekvizitlar. Ochiq bo'lmasa — faqat holat va shop nomi.
- **`categories`** — mahsuloti bor toifalar va ularning ota toifalari, nomlari 3 tilda.
- **`products`** — kesh kaliti: shop + `index_version` + filtrlar hash'i:
  - toifa filtri bolalarini ham oladi;
  - kartochkada umumiy holat — variantlardan eng yaxshisi;
  - aniq son faqat `EXACT` siyosatda (DEC-128).
- **`product`** — avval `public_visible` (har so'rovda), keyin keshdan. Filial bo'yicha mavjudlik faqat 2 va undan ko'p ochiq olib ketish joyi bo'lsa (DEC-135). Qatori yo'q filial — "yo'q".
- **`privacy`** — platforma shabloni (backend tarjimasi) + shop rekvizitlari, xaridor tilida (`Accept-Language`).
- Rasm va logotip havolalari — faqat ochiq fayllar.

### 4.3 Katalogning ommaviy metodlari — `catalog/query_port.py`

- **"Ko'rinadigan variant"** — faol SKU, joriy narxi bor, so'mdagi narxi aniq. So'mga o'girish SQL'da: `round(amount × rate / 100) × 100`. Bu `to_uzs_minor` bilan aynan bir xil: eng yaqin butun so'm, 0.5 yuqoriga.
- **`public_products`** — mahsulot bo'yicha eng arzon variant narxi:
  - saralash: yangilar, arzon, qimmat;
  - qidiruv: nom, brend, faol SKU kodi;
  - cursor buzilgan bo'lsa — 422.
- **`public_product`, `public_visible`, `public_categories`.**
- Tannarx, MPN, model nomi, SKU kodi va ichki maydonlar natijaga umuman kirmaydi.

### 4.4 Shop paneli — `storefront/services/site_service.py`

- **`update`** (PATCH):
  - birinchi saqlashda yozuv yaratiladi (`If-Match: "v0"`);
  - telefon E.164 ga keltiriladi, rang katta harfga o'tadi;
  - logotip shu shopning `SITE_LOGO` fayli bo'lishi kerak; eskisi `DELETED` bo'ladi;
  - rang yoki fon o'zgarsa, kontrast tekshiriladi;
  - ochiq saytda telefonni o'chirib bo'lmaydi;
  - auditga faqat maydon nomlari yoziladi; kesh tozalanadi.
- **`transition`** — PUBLISH/RESUME telefonsiz bo'lmaydi. Holat `transition_log` va auditga yoziladi.
- **`pages` / `save_page`** — uchala tur doim qaytadi (yozilmagani standart sarlavha va `version: 0` bilan). Sahifa saytsiz bo'lmaydi: kerak bo'lsa qoralama sayt yaratiladi. Markdown'da HTML teg va `javascript:` havola rad etiladi.
- **`preview_token`** — `PreviewSigner`:
  - token tuzilishi `{shop_id}.{muddat}.{HMAC}`, 30 daqiqa amal qiladi;
  - bazada saqlanmaydi; kalit JWT kalitidan alohida maqsad bilan olinadi;
  - takroriy so'rovga yangi token beriladi.

### 4.5 Buyurtma so'rovi — `commerce/orders/services/storefront_service.py`

- **`request`**, bitta tranzaksiyada:
  - shop savdo qila oladimi;
  - rozilik versiyasi joriy versiyaga tengmi;
  - yetkazish yoqilganmi va manzil bormi; olib ketishda filial — ochiq olib ketish joyi;
  - SKU takrorlanmagan va shu shopniki;
  - mahsulot ko'rinadigan;
  - keyin qoralama → `SUBMIT` (aktor `CUSTOMER`) → "Tasdiq kutilmoqda", `submitted_at`.
- **Takror himoyasi** (`Idempotency-Key` = `source_request_id`):
  - `platform.idempotency_keys` ga faqat buyurtma ID'si yoziladi;
  - takroriy so'rovda o'sha buyurtma va yangi token qaytadi (eski havola bekor bo'ladi);
  - idempotency yozuvi eskirgan bo'lsa ham, `source_request_id` ikkinchi buyurtmani to'xtatadi.
- **Javob:** raqam, xaridorga ko'rinadigan holat, token va `tracking_path`, qatorlar `available_in_branch` bilan.
- **`track`** — token formati va xeshi bo'yicha, solishtirish doimiy vaqtda (`hmac.compare_digest`). Telefon, manzil va izoh javobda yo'q. Ichki "muammoli" holat xaridorga "tayyorlanmoqda" bo'lib ko'rinadi.

### 4.6 API

```
Shop paneli (/api/v1/shop/storefront):
  GET    ""                     storefront.site.view   — sozlamalar, state, site_url, publish_problems
  PATCH  ""                     storefront.site.edit   — If-Match ("v0" — birinchi)
  POST   /publish|/pause|/resume  .edit                — If-Match + Idempotency-Key
  POST   /preview               .view                  — Idempotency-Key; token bazada yo'q
  GET    /pages                 .view
  PUT    /pages/{kind}          .edit                  — If-Match ("v0" — birinchi)
Ommaviy (/api/v1/storefront/{slug}) — anonim:
  GET /site  /categories  /products  /products/{id}  /pages/{kind}  /branches  /privacy
  POST /order-requests (Idempotency-Key)   GET /orders/{token}
Logotip: POST /api/v1/shop/files?purpose=SITE_LOGO (ega)
```

**So'rov chegaralari:**
- o'qish — IP + shop bo'yicha 120/daq;
- buyurtma so'rovi — 10 daqiqada IP + shop + telefon xeshi bo'yicha 5 ta, IP + shop bo'yicha 20 ta;
- holat sahifasi — IP bo'yicha 30/daq.

Storefront yo'llari deadlock'da butunlay qayta urinilmaydi: rate limit hisoblagichi tranzaksiyadan tashqarida.

### 4.7 Baza

- **`storefront_0002`:**
  - `sites` (PK `shop_id`; CHECK: holat, fon, `#RRGGBB`);
  - `pages` (`(shop_id, kind)` unikal; FK → `sites`);
  - ikkalasida RLS (FORCE).
- **`platform_0007`:** `shop_policies.delivery_enabled` (standart `true`), `stored_files.purpose` ga `SITE_LOGO`.

### 4.8 Ruxsatlar

- **Ega:** `storefront.site.view` va `storefront.site.edit`, logotip yuklash ham shu yerga kiradi.
- **Menejer:** faqat `storefront.site.view` — ko'radi va ko'rib chiqish havolasini oladi.
- **Operator va omborchi:** yo'q.

### 4.9 Demo ma'lumot — `app/db/seed/storefront_seed.py`

- **Ochiq (LIVE):**
  - NoutbukUz — ko'k, oq fon;
  - KompyuterPro — yashil;
  - Hi-Tech Samarqand — sariq, to'q fon.
- **TechPC** — sozlangan qoralama (shop tekshiruvda).
- **ByteShop** — sayt ochiq, shop to'xtatilgan.

Har saytda: logotip (PNG, tarmoqsiz yasaladi), 3 ta chiqarilgan sahifa (o'zbekcha), kontaktlar. Seed ishlab turgan server keshini tozalamaydi: sozlama 5 daqiqagacha eski ko'rinishi mumkin.

---

## 5. Testlar

`make check` — **412 ta test o'tdi** (oldin 373). ruff, mypy strict va import-linter toza.

**Integratsiya** (`tests/integration/test_storefront.py`, 14 ta):

- **Ommaviy javob maydonlari (TC-SEC-09).** Sayt, kartochka, mahsulot, variant va filial javoblarida maydonlar to'plami aniq tekshiriladi. SKU kodi, MPN, narx versiyasi, `amount_minor`, `created_by` javobda yo'q.
- **Sayt holatlari:** yo'q slug, qoralama, ochiq, to'xtatilgan sayt, to'xtatilgan shop (keshsiz, darhol), yopilgan shop.
- **Ko'rib chiqish tokeni:** query va header orqali ishlaydi. Boshqa shop tokeni, eskirgan va buzilgan token kuchsiz. Ko'rib chiqishda buyurtma — 409.
- **Ruxsatlar:** menejer ko'radi, lekin o'zgartira, ocha va sahifa yoza olmaydi. Operator 403 oladi.
- **Sozlama tekshiruvlari:** `v0`, versiya to'qnashuvi, och rang (`low_contrast`), noto'g'ri username/email/telefon, telefonsiz ochish, ochiq saytda telefonni o'chirish, HTML va `javascript:` sahifada. Chiqarilmagan sahifa menyuda yo'q. Maxfiylik siyosati rus tilida.
- **Kesh izolyatsiyasi:** ikki shop bir xil parametrlar bilan — har biri faqat o'zinikini ko'radi.
- **Yashirilgan mahsulot:** kesh bo'lsa ham darhol 404, buyurtma so'rovi 409.
- **Dollar narxi:** kursi yo'q bo'lsa ko'rinmaydi; kurs bilan aniq so'm (300 $ × 12 835 = 3 850 500 so'm).
- **Filial bo'yicha mavjudlik:** 2 ta olib ketish joyida ko'rsatiladi, 1 tasida yo'q.
- **Buyurtma so'rovi, to'liq yo'l:**
  - 201 va "Qabul qilindi"; filialda yo'q qator belgilanadi;
  - takroriy so'rov — o'sha raqam va yangi token, eski havola 404; boshqa tana bilan — 409;
  - panelda "Tasdiq kutilmoqda", `STOREFRONT`, biriktirilmagan, band yo'q, qoldiq o'zgarmagan;
  - bazada telefon shifrlangan, token xesh bilan, rozilik versiyasi bor;
  - takror jadvalida token va telefon yo'q;
  - jurnalda `CUSTOMER`/`SUBMIT`;
  - holat sahifasi PII'siz; tasdiqdan keyin "Tasdiqlandi"; sayt to'xtatilganda ham ko'rinadi.
- **Buyurtma so'rovi tekshiruvlari:** rozilik yo'q yoki eski, filialsiz olib ketish, manzilsiz yetkazish, boshqa shop SKU'si va filiali, noto'g'ri telefon, yetkazish o'chirilgan (siyosat orqali), to'xtatilgan shop.
- **Chegaralar:** 6-so'rov 429; boshqa telefon alohida hisoblanadi; `Retry-After` bor; o'qishda 121-so'rov 429.
- **RLS:** kontekstsiz — 0 qator; boshqa shop konteksti — 0 qator; ikkala jadvalda FORCE.
- **Logotip:** menejer yuklay olmaydi; ochiq fayl va havola saytda chiqadi; almashtirilganda eskisi `DELETED`; mahsulot rasmini logotip qilib bo'lmaydi.

**Unit** (`tests/unit/test_storefront_units.py`, 25 ta):
- slug (lotin va kirill), kontrast va tugma matni rangi;
- ko'rib chiqish tokeni: shop, muddat, imzo, buzilgan shakllar;
- rozilik matni barmoq izi — matn o'zgarsa versiya ham o'zgarishi shart;
- sayt holati jadvali va `ensure_open`;
- kesh kalitlari va xotira keshi (TTL, `INCR`);
- sayt CORS'i: ruxsat etilgan manzil, begona manzil, preflight, panel yo'li;
- sxemalar (HTML, username, email, rang);
- xaridorga ko'rinadigan holat; token formati.

**Seed testi** — 5 ta sayt (4 tasi ochiq), 15 ta chiqarilgan sahifa, fayllar 4 → 9. Qayta yugurish hech narsa qo'shmaydi.

---

## 6. Jarayonda topilgan muammolar

- **`updated_at` lazy-load.** Saqlashdan keyin `updated_at` (server `onupdate`) o'qilganda async sessiyada `MissingGreenlet` chiqdi. `flush` dan keyin `refresh` qo'shildi.
- **HTML tekshiruvi juda qattiq edi.** "a < b" kabi oddiy matnni ham rad etdi. Endi faqat `<` dan keyin darhol harf, `/`, `!` yoki `?` kelsa (haqiqiy teg) rad etiladi.
- **Kirish logida route shabloni.** Ichki router'lar ichida FastAPI route'ni middleware'ga bermaydi, shuning uchun yo'l niqoblanib yoziladi (`redact_path`). Holat havolasi tokeni 43 belgi — u doim `{seg}` bo'lib niqoblanadi va logga tushmaydi. Ko'rib chiqish tokeni query'da keladi, uning qiymati esa logga yozilmaydi.

---

## 7. Keyingi modulga meros

- **Frontend (xaridor sayti va "Shop sayti" bo'limi):**
  - **Host → slug:** `{slug}.platforma.uz` (dev'da `{slug}.localhost:3002`) — birinchi bo'lak slug.
  - **Ko'rib chiqish:** `preview_url` dagi `?preview=` → `X-Storefront-Preview` header'i.
  - **Rozilik:** `site.consent.version` buyurtma so'roviga yuboriladi.
  - **Holat havolasi:** `tracking_path` sayt manziliga qo'shiladi.
  - **Mahsulot havolasi:** `/p/{id}/{slug}`; slug farq qilsa `canonical_path` ga yo'naltiriladi.
  - **Sayt holati xatolari:** `SITE_NOT_AVAILABLE` (`details.state`) va 404.
  - **Panel xatolari:** `accent_color` / `low_contrast`, `contact_phone` / `required`.
- **5-modul (fon ishlari):**
  - katalog va ombor event'lari `…:storefront:index_version` ni oshiradi;
  - `public_products` nusxasi;
  - xaridorga holat xabarlari;
  - sayt chati.
- **Prod:**
  - `STOREFRONT_PUBLIC_URL` = `https://{slug}.platforma.uz`;
  - `STOREFRONT_CORS_ORIGIN_REGEX` = prod domeni;
  - Nginx faqat platforma domenini o'tkazadi;
  - kirish logida query qatori yo'q (09).

---

## 8. Frontend (2026-10-26)

### 8.1 Nima bitdi — qisqacha

Xaridor endi shopning o'z saytida mahsulotni topadi, savatchaga soladi va buyurtma so'rovini yuboradi. Shop egasi saytni paneldagi "Sayt" bo'limida sozlaydi va ochadi.

```
Ega (panel → Sayt): logotip, rang, fon, shior, aloqa ──▶ 3 ta sahifa matni ──▶ "Ko'rib chiqish" (30 daqiqa) ──▶ "Saytni ochish"
Xaridor ({slug}.platforma.uz): katalog / qidiruv ──▶ mahsulot ──▶ savatcha (brauzerda) ──▶ buyurtma (rozilik bilan)
        ──▶ "Qabul qilindi" + holat havolasi ──▶ operator tasdiqlasa, holat sahifasida "Tasdiqlandi"
Operator (panel → Buyurtmalar): "Sayt" belgisi ──▶ "O'ziga olish" ──▶ tasdiqlash (filialda yetmasa — ogohlantirish)
```

### 8.2 Sahifalar

**Shop sayti (`apps/shop-storefront`, dev — `http://{slug}.localhost:3002`):**
- `/` — bosh sahifa: shop nomi va shiori, toifalar, saralash, mahsulotlar to'ri ("Yana ko'rsatish" — cursor bilan), qidiruv `/?q=`.
- `/p/{id}/{nom}` — mahsulot: rasmlar, variantlar, aniq so'm narx, mavjudlik (DEC-128), 2+ olib ketish joyi bo'lsa filiallar bo'yicha, kafolat, xususiyatlar, "taxminiy" izohi (BL-026). Nom boshqacha bo'lsa — to'g'ri manzilga 308.
- `/cart` — savatcha, `/checkout` — buyurtma so'rovi.
- `/orders/{token}` — holat sahifasi (yangi so'rovdan keyin `?new=1` bilan "Qabul qilindi" va havolani nusxalash). Sayt to'xtatilganda ham ishlaydi.
- `/info/about`, `/info/delivery`, `/info/warranty`, `/privacy`.
- `/robots.txt`, `/sitemap.xml` — har shop uchun alohida; sitemap'da faqat chiqarilgan mahsulotlar.
- Holat ekranlari: "Tez orada ochiladi", "Vaqtincha ishlamayapti", "mavjud emas", "Bunday sayt topilmadi".

**Shop paneli:**
- `/{shop}/site` — "Sayt": holat, manzil, "Saytni ochish" / "To'xtatish" / "Qayta ochish" (ega), "Ko'rib chiqish", ochishga to'sqinlik qilayotgan maydonlar ro'yxati; ko'rinish va aloqa formasi (rang namunasi bilan); 3 ta sahifa muharriri ("Ko'rinishi" yorlig'i bilan); yetkazib berish holati. Menejer — faqat ko'radi.
- `/{shop}/settings` — "Saytda yetkazib berishni taklif qilish" (`delivery_enabled`).
- Bosh sahifa — "Shop sayti" kartochkasi (holat va havola).
- Buyurtmalar — saytdan kelganida "Sayt" belgisi; tasdiqlanmagan buyurtmada filialda yetmaydigan qator — "Filialda yetarli emas (bor: N)".

### 8.3 Fayllar xaritasi

```
apps/shop-storefront/
├── src/proxy.ts                     # Host → slug → ichki /{slug}/...; ?preview= → sessiya cookie'si
├── src/lib/
│   ├── api.ts                       # server: ommaviy API (kesh qoidalari), getSite, openSite
│   ├── client-api.ts                # brauzer: cookie'siz client (til + ko'rib chiqish header'i)
│   ├── cart.ts                      # savatcha (localStorage, shop bo'yicha)
│   ├── host.ts, server-config.ts    # ruxsat etilgan domenlar
│   ├── locale.ts, format.ts, catalog.ts, attributes.ts, origin.ts
├── src/components/
│   ├── site-provider.tsx            # til, sayt, API, savatcha konteksti
│   ├── chrome.tsx, header-parts.tsx # sarlavha, qidiruv, til, savatcha tugmasi, pastki qism, holat ekranlari
│   ├── product-card.tsx, catalog-parts.tsx, stock-label.tsx
│   ├── product-gallery.tsx, product-purchase.tsx
│   ├── cart-lines.ts, cart-view.tsx, checkout-form.tsx, copy-link.tsx
└── src/app/
    ├── layout.tsx                   # til va shop rangi/foni <html> da
    ├── [site]/layout.tsx            # sayt metadata, kontekst
    ├── [site]/(shop)/...            # katalog, mahsulot, savatcha, buyurtma, sahifalar (faqat ochiq sayt yoki ko'rib chiqish)
    ├── [site]/orders/[token]/       # holat sahifasi
    └── [site]/robots.txt, sitemap.xml
apps/shop-dashboard/src/
├── app/[shop]/site/page.tsx
├── components/site/{site-status, site-settings, site-pages}.tsx
└── lib/site.ts
packages/
├── i18n/src/core.ts                 # React'siz tarjima (sayt serverida)
└── app-kit/src/markdown.tsx         # xavfsiz Markdown (sayt va panel ko'rinishi)
e2e/storefront.spec.ts
```

### 8.4 Muhim qarorlar

- **Host → slug proxy'da.** Tashqi yo'lga doim Host'dagi slug qo'shiladi, shuning uchun boshqa shop sahifasiga yo'l orqali o'tib bo'lmaydi. Ruxsat etilmagan domen — 404.
- **Kesh.** Ro'yxatlar Next keshida 30–60 soniya (backend ham keshlaydi). Sayt holati va mahsulot sahifasi — har so'rovda, shuning uchun yashirilgan mahsulot va to'xtatilgan sayt darhol ko'rinadi. Ko'rib chiqish javobi hech qachon keshlanmaydi. Yopiq saytda do'kon sahifalari ma'lumot so'ramaydi.
- **Til — cookie'da.** Server ham, brauzer ham bir tilda chizadi; til almashsa sahifa serverdan qayta chiziladi.
- **Ko'rib chiqish tokeni** manzil satridan olinib, httpOnly sessiya cookie'siga yoziladi; buyurtma tugmasi o'chiq.
- **Savatcha** `{product_id, sku_id, qty}` (hujjatda `{sku_id, qty}`): ommaviy API mahsulotni id bo'yicha beradi, narx har safar qayta olinadi. Yashirilgan mahsulot savatchada "mavjud emas" bo'lib belgilanadi va buyurtmaga kirmaydi.
- **Hozir yo'q mahsulot** savatchaga qo'shilmaydi (tugma o'rniga "Hozir mavjud emas"). Filialda yo'q mahsulot esa qabul qilinadi — buyurtma formasida "operator muqobil taklif qiladi" deb belgilanadi.
- **Buyurtma tugmasi:** `Idempotency-Key` urinish boshida bir marta; ikki marta bosilsa bitta buyurtma. Rad etilgan so'rovdan keyin (masalan, maydon xatosi) yangi kalit.
- **Markdown** o'zimizniki, kichik qism: HTML hech qachon chiqarilmaydi, havola faqat http(s)/mailto/tel.
- **Holat sahifasi** qidiruvga tushmaydi va tashqi havolaga Referer bermaydi (token sizib chiqmasin).
- **Rang:** tugma matni backend bergan `accent_text_color`; matnli havolalar urg'u rangida emas (3:1 kontrast matnga yetmaydi) — chiziq urg'u rangida.

### 8.5 Tekshiruv

- `pnpm check` — toza (typecheck + lint, hamma paket va app).
- `pnpm test:e2e` — 15/15 (13 eski + 2 yangi), uchala production build e2e ichida; e2e backend `--no-proxy-headers` bilan (`make run` dagidek).
- Yangi e2e:
  1. Ega sozlaydi (telefon, shior, sahifa, Markdown ko'rinishi) → ko'rib chiqish banneri → ochadi; xaridor qidiradi → mahsulot → savatcha → rozilik majburiy → ikki marta bosish = bitta buyurtma → "Qabul qilindi"; panelda "Sayt", biriktirilmagan → operator oladi va tasdiqlaydi → holat sahifasida "Tasdiqlandi". Ochilishdan oldin — "Tez orada ochiladi".
  2. Yashirilgan mahsulot havolasi — "mavjud emas"; ma'lumot sahifasi; to'xtatilgan sayt; 390px da sayt sahifalari va paneldagi "Sayt" bo'limi enidan oshmaydi.

### 8.6 Backend bilan kelishilganlar (QA tuzatishlaridan keyin)

- **Xaridor IP'si.** Backend sayt serverini (127.0.0.1) ishonchli proksi deb biladi. Sayt keshsiz so'rovlarda `X-Forwarded-For: <xaridor IP>` yuboradi — faqat bitta tekshirilgan IP, kelgan so'rovning o'z zanjiridan, o'ngdan `STOREFRONT_TRUSTED_PROXY_HOPS`-qiymat (o'zimizning nginx qo'shgani). Chap tomondagilar va query hech qachon ishlatilmaydi. `STOREFRONT_TRUSTED_PROXY_HOPS=0` (dev, standart) — proksi yo'q, IP yuborilmaydi: Next sarlavha bo'lmasagina soket manzilini qo'yadi, demak bor sarlavhani mijoz yozgan bo'lishi mumkin. Prod (nginx `$proxy_add_x_forwarded_for`) — `1`. Keshlanadigan so'rovlarda IP yuborilmaydi.
- **Filialda yetadimi** — `OrderLineOut.available_in_branch` / `available_qty` (faqat qoralama va tasdiq kutilayotgan, filiali bor buyurtmada). Panel endi alohida qoldiq so'rovlarini yubormaydi.
- **Buyurtma so'rovi:** `qty` doim JSON butun son; xato tafsilotidan faqat yuborilgan `sku_id` o'qiladi.

### 8.7 Ochiq qolganlar

- Narx oralig'i, brend va "faqat borlari" filtrlari (backend'da ham yo'q).
- Rasmni kattalashtirish (lightbox) va mahsulot sahifasida "o'xshash mahsulotlar".
- Sayt chati (5-modul) va AI maslahatchi (6-modul).

---

## 9. QA tekshiruvi va tuzatishlar (2026-10-26)

Mustaqil QA agenti ommaviy sayt API'sini, buyurtma so'rovini, holat sahifasini va paneldagi sozlamalarni buzishga urindi. Jiddiy muammo yo'q: 2 ta o'rtacha, 2 ta kichik va 4 ta mayda topilma. Shoplararo himoya, ruxsat etilgan maydonlar (TC-SEC-09), rozilik, narx va filial tekshiruvi, takror himoyasi, RLS, holat sahifasida PII yo'qligi — hammasi o'tdi, 500 xato bitta ham chiqmadi. Hammasi tuzatildi, har biriga test yozildi.

### 9.1 O'rtacha topilmalar

- **F1 — sayt javobida `Access-Control-Allow-Credentials: true` bor edi.** Panel CORS'i butun ilovaga ulangan edi va sayt yo'llariga ham sarlavha qo'shardi.
  - Endi `PanelCorsMiddleware` (`app/shared/storefront_cors.py`) sayt yo'llarida umuman ishlamaydi. Sayt CORS'i ichkaridan kelgan `Access-Control-Allow-Credentials` va begona `Allow-Origin` ni o'chiradi; `Vary: Origin` bir marta (F6 ham shu bilan yopildi).
  - Panel manzili (`localhost:3000`) sayt yo'lida aks ettirilmaydi; sayt manzili panel API'sida ruxsatsiz.
- **F2 — takroriy so'rov jadvalidagi barmoq izi orqali telefonni topish mumkin edi.** `request_hash` oddiy SHA-256 edi; buyurtmaning qolgan maydonlari bazada ochiq, telefon esa ~10⁷ variant — oflayn tanlab topilardi.
  - Endi barcha operatsiyalar uchun server kaliti bilan HMAC: `h1:` + hex (`IDEMPOTENCY_HASH_KEY`, lokal standart staging/production'da rad etiladi).
  - **O'tish qarori:** eski (kalitsiz) yozuvlar 24 soatda eskiradi. Shu muddatda ular eski usulda solishtiriladi (`legacy_request_hash`), shuning uchun deploy paytida qayta yuborilgan so'rov xato olmaydi. Yangi yozuvlar faqat kalitli. Bu o'tish kodi keyingi relizda olib tashlanadi.

### 9.2 Kichik va mayda topilmalar

- **F3 — `X-Forwarded-For` bilan rate limitni chetlab o'tish.** uvicorn lokal ulanishda XFF'ga o'zi ishonardi.
  - Yangi `app/shared/client_ip.py` va `TRUSTED_PROXIES` sozlamasi (IP yoki CIDR, JSON ro'yxat). XFF faqat ishonchli manzildan kelsa o'qiladi; zanjirdan o'ngdan birinchi ishonchsiz manzil olinadi. Auth, sayt o'qish va buyurtma so'rovi chegaralari hammasi shu yordamchi orqali.
  - Shop sayti serveri (SSR) API'ni bitta IP'dan chaqirib, xaridor IP'sini XFF'da beradi: sayt serveri ishonchli ro'yxatda bo'lsa, 120/daq har xaridorga alohida. Lokal standart — `127.0.0.1`, `::1` (lokalda XFF soxtalash ataylab mumkin). Prod — nginx va sayt serverining ichki manzili (22 §8).
  - uvicorn endi `--no-proxy-headers` bilan (`make run`, 22 §2): XFF'ni faqat ilova o'qiydi.
- **F4 — keshdagi mahsulot sahifasida arxivlangan variant 60 soniyagacha ko'rinardi.**
  - Endi har so'rovda arzon so'rov: hozir ko'rinadigan variantlar va ularning joriy so'm narxi (`CatalogQueryPort.public_live_variants`, eski `public_visible` o'rniga). Keshdan olingan sahifadan ko'rinmaydigan variantlar olib tashlanadi, narx joriyga almashtiriladi. Keshda faqat og'ir qism (matn, rasm, qoldiq).
  - Ro'yxatdagi "narxi …dan" 60 soniyagacha eski bo'lishi mumkin — bu hujjatdagi "taxminiy" qoidasi (BL-026).
- **F5 — `BRANCH_CLOSED` tafsilotida filial ID'si qaytardi.** Buyurtma so'rovi xatolarida `*_id` kalitlari olib tashlanadi (`public_error_details`); qatorlarda faqat xaridor o'zi yuborgan `sku_id` qoladi (11 §6.3 ruxsat beradi). Maydon xatolari (yo'l + kod) o'zgarmaydi.
- **F7 — bir soniyada so'ralgan ko'rib chiqish tokenlari bir xil edi.** Token endi `{shop}.{exp}.{nonce}.{sig}`: tasodifiy `nonce` imzoga kiradi, tekshiruv baribir holatsiz. Eski 3 qismli tokenlar endi o'tmaydi (ular 30 daqiqalik edi).
- **F8 — `qty` uchun `"2"` va `true` qabul qilinardi; telefon oxiridagi yangi qator o'tib ketardi.** Sayt `qty` — qat'iy butun son. Telefon, email, slug va holat tokeni tekshiruvlari `fullmatch` bilan (`$` yangi qatordan oldin ham mos kelardi).

### 9.3 Frontend agenti so'ragan o'zgarishlar

- **SSR va so'rov chegarasi** — F3 dagi ishonchli proksi bilan hal qilindi. Lokal va e2e'da sayt serveri `127.0.0.1` dan keladi va standart ro'yxatda bor — e2e muhitiga yangi o'zgaruvchi kerak emas.
- **`OrderLineOut.available_in_branch` va `available_qty`.** Buyurtma `DRAFT` yoki `PENDING_CONFIRMATION` va filial tanlangan bo'lsa — tanlangan filialdagi sotuvga mavjud son va "yetadimi" belgisi; boshqa holatda `null`. Bitta buyurtma — bitta so'rov (`OrderViews.branch_available`). Buyurtmani ko'ra oladigan xodimgina ko'radi (filial doirasi oldingi qoidalar bilan).

### 9.4 Testlar

- Yangi: `tests/unit/test_storefront_qa_fixes.py` (17), `tests/integration/test_storefront_qa_fixes.py` (5), idempotency o'tish testi (`test_use_idempotency_audit.py`) va kalitli hash testi (`test_idempotency_audit_units.py`).
- Tekshirilganlar: sayt va panel yo'llarida CORS sarlavhalari (ruxsat etilgan, begona, panel manzili; preflight); soxta XFF ishonchsiz manzildan; ishonchli proksi zanjiri; `TRUSTED_PROXIES` va `IDEMPOTENCY_HASH_KEY` sozlama tekshiruvi; noyob ko'rib chiqish tokenlari; qat'iy `qty` va telefon; keshdagi sahifada arxivlangan variant va yangi narx darhol; `BRANCH_CLOSED` tafsilotsiz; buyurtma so'rovi barmoq izi `h1:`; paneldagi qatorlarda filial mavjudligi (qoralama, bekor qilingan, tasdiqlangan, saytdan kelgan).

### 9.5 QA 2-tur (2026-10-26): natija va tuzatishlar

1-tur tuzatishlari (F1–F8) hammasi tasdiqlandi, F2 — qisman: eski kalitsiz qatorlar bazada qolgan edi. 2-turda topilganlar va nima qilindi:

**Backend**
- **F2 qoldig'i** — `platform_0008`: kalitsiz barmoq izli qatorlar o'chirildi va CHECK qo'shildi — endi faqat `h1:` (HMAC). Eski usulda solishtirish kodi olib tashlandi. Muddati o'tgan qatorlarni muntazam tozalash — TD-02, 5a-modulda (fon ishlari).
- **B1** — bir nechta `X-Forwarded-For` qatori bitta zanjirga birlashtiriladi, keyin o'ngdan o'qiladi.
- **U1 (backend)** — sayt serverining o'zi (ishonchli proksi, xaridor IP'sisiz) alohida chelak oladi: `sf-ssr:{slug}`, `STOREFRONT_SSR_READ_LIMIT_PER_MINUTE` (standart 3000). Xaridorlar SSR'ni, SSR xaridorlarni to'xtatib qo'ya olmaydi.
- **U6 (backend)** — `PublicSite.shop.url`: saytning kanonik manzili sozlamadan (`STOREFRONT_PUBLIC_URL`).
- **U11 (backend)** — sahifa matni (`body_md`) `CleanText`: yo'nalish va nol kenglikdagi belgilar olib tashlanadi, qatorlar va formatlash qoladi. `javascript:` ichiga nol kenglikdagi belgi qo'yib aylanib o'tish ham ushlanadi.

**Frontend (shop sayti)**
- **U1** — 429, 5xx va aloqa yo'qligi "topilmadi" emas: "Sayt vaqtincha band — birozdan keyin urinib ko'ring" va "qayta urinish". Faqat haqiqiy 404 — "topilmadi". Ro'yxatni olib bo'lmasa — xato va qayta urinish. robots.txt va sitemap.xml — `503` + `Retry-After`. Sahifa uchun aniq `503` ni Next App Router bera olmaydi — xato chegarasi `5xx` qaytaradi (qidiruv tizimi uchun baribir "vaqtincha").
- **U3, U5** — Next'ning ma'lumot keshi olib tashlandi, hamma o'qish `no-store`; kesh faqat backend'da. Ro'yxat va ma'lumot sahifalari endi eskirib qolmaydi; ega saqlagani saytda darhol.
- **U2** — javob yo'qolsa kalit bilan birga birinchi yuborilgan tana saqlanadi. Xaridor formani o'zgartirib qayta yuborsa va backend `IDEMPOTENCY_KEY_REUSED` desa — birinchi tana shu kalit bilan qayta yuboriladi, buyurtma qaytadi, xaridor uning sahifasiga "avvalgi ma'lumotlar bilan qabul qilingan" xabari bilan o'tadi. Yangi kalit avtomatik yaratilmaydi.
- **U4** — holat bosqichlari telefonda vertikal ro'yxat, kengroq ekranda 5 ta teng bo'lak; e2e 360px da uz va ru da ustma-ust tushmasligini tekshiradi.
- **U6** — canonical, og:url, sitemap va robots manzillari `site.shop.url` dan; `Host` va `X-Forwarded-Proto` hisobga olinmaydi.
- **U7** — xavfsizlik sarlavhalari: CSP har so'rovga nonce bilan (`proxy.ts`), `X-Frame-Options: DENY`, `nosniff`, `Referrer-Policy`, `Permissions-Policy` (`next.config.ts`). Rasm manzillari: backend va `STOREFRONT_ASSET_ORIGINS` (prod CDN). E2E konsolda CSP xatosi yo'qligini tekshiradi.
- **U8** — noto'g'ri yuborishda fokus birinchi xato maydonga; savatcha rasmi havolasi nomli; panel telefon menyusi tugmasi nomli.
- **U9** — faollashtirilmagan shopda "Saytni ochish" oynasi: xaridorlarga platforma faollashtirgandan keyin ochiladi.
- **U10 / DEC-141** — hozir yo'q mahsulot ham savatchaga qo'shiladi va so'raladi: "Hozir mavjud emas — operator muddat va muqobilni aytadi"; panelda filial yetishmovchiligi belgisi.
- **U11** — Markdown havolasida bir daraja muvozanatli qavs: `[Wiki](https://…/A_(b))`.
- **U12** — har indekslanadigan sahifada canonical va og:url, rasm bo'lmasa og:image — logotip; qidiruv/toifa/saralash — `noindex,follow`; shop ichidagi yo'q manzil — shop sarlavhasi va menyusi bilan "topilmadi"; uzun shop nomi telefonda 2 qatorga o'raladi.

**Qarorlar** (founder ko'rib chiqadi): kesh faqat backend'da; filtrli manzillar `noindex,follow` + canonical bosh sahifaga; sahifa uchun aniq `503` o'rniga xato chegarasi (Next cheklovi); CSP `style-src 'unsafe-inline'` (React `style` atributlari va bildirishnomalar uchun).

**Tekshiruv:** backend `make check` — 439 test; frontend `pnpm check` toza; e2e 16/16 (yangi: javob yo'qolishi, hozir yo'q mahsulot, holat bosqichlari, sarlavhalar va CSP).
