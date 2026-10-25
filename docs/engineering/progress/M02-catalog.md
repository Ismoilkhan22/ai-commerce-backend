# 2-modul — Katalog (backend)

> **Holat:** backend bitdi — 2026-10-25. **Commit qilinmagan**, founder ko'rib chiqishini kutmoqda. Frontend (shop paneli sahifalari va platforma kutubxonasi) — keyingi qadam.
> **TZ:** [db/catalog.dbml](../db/catalog.dbml) va [catalog.md](../db/catalog.md) (DEC-133), [business/05](../../business/05_STATE_MACHINES_AND_EXCEPTIONS.md) FSM-02, [17](../17-pc-compatibility-engine.md) §4–5 va §10. Rejadagi bandlar: S0-08, S1-02, S1-03, S1-04.
> **Repo:** `ai-commerce-backend` (`feat/s0-foundation`).

---

## 1. Nima bitdi — qisqacha

Shop endi mahsulot qo'shadi, narx qo'yadi va saytga chiqaradi. Platforma jamoasi esa PC qismlarining texnik ma'lumotlar kutubxonasini yuritadi. Kutubxonaga bir kishi kiritadi, boshqa kishi tasdiqlaydi.

```
Shop: mahsulot (qoralama) + variant (SKU) + narx ──▶ "Chiqarish" ──▶ narx va majburiy maydonlar tekshiriladi ──▶ Chiqarilgan
      SKU'da model yoki MPN bor ──▶ kutubxonadagi modelga avtomatik bog'lanadi (faqat aniq bitta mos kelsa)
      kutubxonada yo'q model ──▶ "yangi model qo'shing" so'rovi ──▶ platforma navbati
Platforma: admin modelni kiritadi ──▶ kutubxona muharriri tasdiqlaydi ──▶ shoplarga ko'rinadi
           so'rovni hal qiladi ──▶ shopning SKU'si o'sha modelga bog'lanadi
Rasm: fayl yuklanadi (turi fayl ichidan aniqlanadi) ──▶ mahsulotga ulanadi ──▶ ochiq manzildan beriladi
```

Dollardagi narx xaridorga so'mda, shop kursi bo'yicha ko'rsatiladi. Yaxlitlanmaydi: 300 $ × 12 835 = 3 850 500 so'm.

## 2. Rejadagi bandlar

- [x] **S0-08 — fayllar:**
  - `FileStorage` porti va lokal disk adapteri;
  - `platform.stored_files` jadvali;
  - yuklash: hajm ≤ 5 MB, tur fayl ichidan (JPEG, PNG, WebP);
  - ochiq manzil (mahsulot rasmi) va yopiq fayl uchun 5 daqiqalik imzoli havola.
- [x] **S1-02 — mahsulot va SKU:**
  - toifalar (platforma ro'yxati, 3 tilda, 19 ta boshlang'ich);
  - mahsulot, variantlar, rasmlar (ko'pi bilan 10 ta, tartibi bilan);
  - FSM-02: ega yoki menejer to'g'ridan chiqaradi, arxivlashni faqat ega qiladi;
  - `UNIQUE (shop_id, sku_code)`;
  - ro'yxat: cursor bilan sahifalash, holat, toifa, qidiruv va saralash.
- [x] **S1-03 — narx va kurs:**
  - narx versiyalari o'zgarmaydi (ilova roli UPDATE/DELETE qila olmaydi);
  - joriy narx ko'rsatkichi `If-Match` bilan;
  - so'm va dollar; shop kursi (qo'lda), 3 kundan eskisi "eskirgan";
  - so'mga o'girishda yaxlitlanmaydi.
- [x] **S1-04 — texnik ma'lumotlar kutubxonasi:**
  - platforma paneli: kiritish, o'zgarish taklifi, ikkinchi odam tasdig'i, rad etish, eskirgan deb belgilash;
  - har tur uchun atributlar sxemasi (17 §4.1);
  - SKU'ni avtomatik bog'lash (MPN, keyin brend + model), qo'lda bog'lash;
  - shopning "yangi model" so'rovi va platforma navbati.
- [x] **Ruxsatlar:** `catalog.*` kodlari (10 §6.2) va `catalog.product.archive` (faqat ega). Platforma uchun `platform.spec.view` va `platform.category.edit`.
- [x] **Demo ma'lumot (`make seed`):**
  - kutubxonada 13 ta model (12 tasi tasdiqlangan, 1 tasi tasdiq navbatida);
  - 3 ta shopda 18 ta mahsulot, dollar va so'm narxlari bilan;
  - 4 ta rasm, 1 ta "yangi model" so'rovi;
  - KompyuterPro'da kurs eskirgan (4 kunlik).
- [x] **`CatalogQueryPort`** (`app/shared/contracts/catalog.py`): 3-modul buyurtma qoralamasida narx nusxasini va tasdiqlashdagi joriy narxni shu orqali oladi (12 §5.1, DEC-134).

**Ataylab keyinga qoldirilganlar:**
- **"Tekshiruvda" (IN_REVIEW) strelkalari.** Holat bazada bor, endpoint yo'q: katalog xodimi roli qo'shilganda ishlatiladi (DEC-133).
- **Event'lar** (`catalog.price.changed`, `catalog.product.published`). Outbox jadvali hali yo'q, kodda `TODO(S0-06)` izohi turibdi. Ungacha sayt va AI narxni to'g'ridan katalogdan o'qiydi.
- **Production fayl ombori (S3-mos adapter)** — deploy bilan (S0-10). Port tayyor, yangi kutubxona qo'shilmadi (TD-03).
- **Omborda yetim qolgan fayllarni tozalash.** Tranzaksiya bekor bo'lsa yoki rasm olib tashlansa, fayl diskda qoladi. Tozalash fon ishi bilan qilinadi (S0-06).
- **Yangi model tasdiqlanganda hamma shoplardagi SKU'larni qayta bog'lash.** RLS tufayli bu har shop uchun alohida ish bo'ladi. Hozircha shop o'zi "Qayta tekshirish" (`POST /shop/skus/auto-link`) ni bosadi, so'rov orqali kelgan SKU esa avtomatik bog'lanadi.
- **Katalog importi** (5-modul) va **PC moslik tekshiruvi** (6-modul).
- **Platforma ro'yxatlarida cursor.** Kutubxona va shop so'rovlari navbati hozircha `offset` bilan ishlaydi (engineering/11 §4.1 cursor talab qiladi). Navbatlar kichik; frontend shu ko'rinishda qurilgan. Chegara qo'yildi (`offset ≤ 100 000`), cursor'ga o'tish — keyin.

**Kartadan farqlar:**
- **RLS hamma shop jadvallarida yoqildi** (FORCE): mahsulot, SKU, rasm, narx, joriy narx, kurs, SKU bog'lanishi va fayllar. 10 §4 faqat narx va kursni talab qiladi. Bitta istisno — `spec_requests`: u platformaning umumiy navbati, shop paneli `shop_id` bo'yicha filtrlaydi.
- **`platform.stored_files.shop_id` → `platform.shops` FK qo'shildi.** Bitta schema ichida bo'lgani uchun ruxsat etilgan, platformadagi boshqa jadvallar kabi.
- **`file_purpose` ga `STOCK_EVIDENCE` qo'shildi** — stok tuzatish dalili, 3-modul uchun. DBML ham yangilandi.
- **Fayl multipart emas, so'rov tanasida yuklanadi:** `POST /shop/files?purpose=…&filename=…`. `python-multipart` kutubxonasi kerak bo'lmadi, frontendda esa oddiy `fetch(body: file)` yetadi.
- **Spec bog'lash (`PUT /skus/{id}/spec-link`) `If-Match` siz.** Bog'lanishda versiya ustuni yo'q, amal esa "shu modelga bog'la" degani: takrorlansa ham natija bir xil.
- **Birinchi narx uchun `If-Match: "v0"`** ("hali narx yo'q").
- **Mahsulotni bitta so'rovda yaratish mumkin:** kartochka + variantlar + narxlar birga keladi (ko'p mahsulotda variant bitta).

## 3. Fayllar xaritasi

```
ai-commerce-backend/
├── app/shared/
│   ├── money.py                         # to_uzs_minor — dollar → so'm (yaxlitlanmaydi, DEC-133)
│   ├── pagination.py                    # cursor (11 §4.1)
│   └── contracts/catalog.py             # CatalogQueryPort + SkuSnapshot (boshqa domenlar uchun)
├── app/platform/storage/                # S0-08
│   ├── ports.py                         # FileStorage porti
│   ├── local.py                         # LocalDiskStorage — dev va test (var/storage)
│   ├── sniff.py                         # fayl turini ichidan aniqlash
│   ├── signing.py                       # UrlSigner — yopiq fayl havolasi (HMAC, 5 daqiqa)
│   ├── models/orm.py                    # StoredFile
│   ├── schemas.py, providers.py, manifest.py
│   ├── services/file_service.py         # FileService: yuklash, havola, ochiq manzildan berish
│   └── api/routes.py, public_routes.py  # /shop/files, /public/files/{key}
├── app/domains/catalog/
│   ├── domain_manifest.py               # shop va platforma router'lari, FSM-02, ruxsatlar
│   ├── permissions.py                   # catalog.* va rollar
│   ├── providers.py                     # CatalogServices — servislar bir marta yaratiladi
│   ├── query_port.py                    # CatalogQueryPortImpl
│   ├── products/
│   │   ├── models/orm.py                # Category, Product, Sku, ProductMedia
│   │   ├── schemas.py                   # DTO'lar
│   │   ├── state_machine.py             # FSM-02 qoidalari
│   │   ├── services/category_service.py, product_service.py
│   │   └── api/routes.py, platform_routes.py
│   ├── pricing/
│   │   ├── models/orm.py                # PriceVersion, CurrentPrice, ExchangeRate
│   │   ├── schemas.py
│   │   ├── services/pricing_service.py
│   │   └── api/routes.py
│   └── pc_specs/
│       ├── models/orm.py                # ReferenceHardwareSpec, …Version, SkuSpecLink, SpecRequest
│       ├── normalize.py                 # MPN va model nomini solishtirish
│       ├── attributes.py                # har tur uchun atributlar sxemasi
│       ├── schemas.py
│       ├── services/link_service.py     # shop: bog'lash va so'rovlar
│       ├── services/spec_service.py     # platforma: kutubxona va so'rovlar navbati
│       └── api/routes.py, platform_routes.py
├── app/db/migrations/platform/versions/platform_0006_stored_files.py
├── app/db/migrations/catalog/versions/catalog_0002_catalog_tables.py
├── app/db/seed/catalog_seed.py          # demo katalog (dev_seed chaqiradi)
├── app/main.py                          # FileService va CatalogServices ulanadi
├── app/dependencies.py                  # get_catalog_query()
└── tests/
    ├── integration/test_catalog.py      # 22 test
    └── unit/test_catalog_units.py       # 19 test
```

## 4. Qaysi faylda nima bor

### 4.1 Fayllar — `app/platform/storage`

- **`FileService.upload()`:**
  - ruxsat fayl maqsadiga qarab tekshiriladi: mahsulot rasmi uchun `catalog.product.edit`, stok dalili uchun `commerce.stock.adjust_request` (3-modulgacha hech kimda yo'q);
  - hajm va tur: **fayl ichidan** (magic bytes). `.jpg` deb nomlangan HTML fayli 415 oladi;
  - kalit: `shops/{shop_id}/product_image/{id}-{tasodifiy}.png`. Fayl nomi kalitga yozilmaydi, shuning uchun manzilni taxmin qilib bo'lmaydi;
  - yozuv va audit bitta tranzaksiyada.
- **`routes.py`:** so'rov tanasi DB tranzaksiyasi ochilishidan **oldin** o'qiladi. Sekin yuklash ulanishni band qilmaydi (`idle_in_transaction` 10 s).
- **`public_routes.py` — `GET /api/v1/public/files/{key}`:**
  - shop konteksti kalitdan olinadi (RLS);
  - ochiq fayl yil davomida keshlanadi (`immutable`);
  - yopiq faylga faqat amal qilayotgan imzo bilan kirish mumkin;
  - topilmasa, o'chirilgan bo'lsa yoki imzo noto'g'ri bo'lsa — bir xil 404.
  Production'da ochiq rasmlar to'g'ridan ombor yoki CDN'dan beriladi.
- **`LocalDiskStorage`:**
  - yarim yozilgan fayl ko'rinmaydi (vaqtinchalik fayl, keyin rename);
  - `..` va ildizdan tashqariga chiqadigan kalit rad etiladi;
  - disk ishi alohida thread'da, async'ni to'xtatmaydi.

### 4.2 Mahsulot — `products/services/product_service.py`

- **`create()`:**
  - toifa mavjud va faol bo'lishi kerak;
  - kartochka va variantlar bitta tranzaksiyada. Takror SKU kodi `skus[0].sku_code / not_unique` xatosini beradi;
  - har SKU uchun narx (v0) va avtomatik bog'lash.
- **`update()` (PATCH):**
  - yuborilmagan maydon o'zgarmaydi, `If-Match` tekshiriladi;
  - brend yoki toifa o'zgarsa, SKU'lar qayta bog'lanadi.
- **`transition()` — FSM-02:**
  - bitta "Chiqarish" tugmasi qoralamadan PUBLISH, yashirilgandan REPUBLISH qiladi;
  - har o'tish `transition_log` va audit'ga yoziladi.
- **`_ensure_publishable()` — chiqarishdan oldin (BL-012):**
  - kamida bitta faol SKU bo'lishi kerak;
  - shu SKU'ning narxi bo'lishi kerak;
  - narx dollarda bo'lsa, shop kursi ham kerak.
  Shart bajarilmasa — `VALIDATION_FAILED`, `fields` da nima yetishmayotgani yoziladi (`skus`, `price` yoki `exchange_rate`).
- **Arxivdagi mahsulot o'zgartirilmaydi** (`INVALID_STATE_TRANSITION`, BL-014).
- **Saytdagi mahsulotning oxirgi faol SKU'si arxivlanmaydi.** Avval mahsulotni yashirish kerak.
- **Rasmlar:**
  - fayl shu shopniki, faol va `PRODUCT_IMAGE` turida bo'lishi kerak. Birovning fayl ID'si bilan 422 qaytadi (TC-ISO-05);
  - olib tashlangan rasm `DELETED` bo'ladi va endi berilmaydi.
- **`list_products()`:**
  - cursor = saralash qiymati + `id`;
  - har mahsulotda variantlar soni, eng arzon so'm narxi va asosiy rasm qaytadi;
  - SKU, narx va rasmlar sahifa uchun bitta so'rov bilan olinadi (har mahsulotga alohida so'rov yo'q).

### 4.3 Narx — `pricing/services/pricing_service.py`

- **`apply_price()`:**
  1. joriy ko'rsatkich qulflanadi (`FOR UPDATE`);
  2. `If-Match` tekshiriladi;
  3. yangi o'zgarmas qator yoziladi;
  4. ko'rsatkich yangi qatorga o'tadi.
  Narx o'zgarmagan bo'lsa, yangi versiya yozilmaydi. Ikki kishi birinchi narxni bir vaqtda qo'ysa — `VERSION_CONFLICT`.
- **`uzs_amount()`:** `to_uzs_minor` orqali. Kursdagi kasr tufayli chiqqan tiyinlar eng yaqin so'mgacha yaxlitlanadi, so'mning o'zi esa yaxlitlanmaydi.
- **`add_rate()`:** kelajak sanasi bilan kurs kiritib bo'lmaydi. `is_stale` — 72 soatdan eski.

### 4.4 Texnik kutubxona — `pc_specs/`

- **`normalize.py`:** katta harf, belgilarsiz: `V516-012R` → `V516012R`. `Ti`, `SUPER`, xotira hajmi saqlanadi, shuning uchun "RTX 5060" va "RTX 5060 Ti" hech qachon bir xil chiqmaydi.
- **`attributes.py`:**
  - 8 tur uchun Pydantic sxema;
  - yo'q atribut "noma'lum" degani, bazaga yozilmaydi;
  - noma'lum kalit rad etiladi (`attributes.colour`).
- **`spec_service.py` (platforma):**
  - `create` — qoralama va 1-taklif;
  - `propose` — o'zgarish taklifi. Bir vaqtda faqat bitta taklif kutishi mumkin;
  - `approve` — taklif qilgan odam o'zi tasdiqlay olmaydi (`SELF_APPROVAL_NOT_ALLOWED`). Ma'lumot asosiy yozuvga ko'chadi, `version` oshadi;
  - `reject` — sabab majburiy;
  - `retire` — kutayotgan takliflar rad etiladi;
  - takror model (brend, katta-kichik harfga qaramay, + model + variant) va takror MPN — `not_unique`;
  - so'rovni hal qilish so'ralgan SKU'ni shop kontekstida bog'laydi. Shop o'zi bog'lagan bo'lsa, tegmaydi.
- **`link_service.py` (shop):**
  - avtomatik bog'lash faqat **aniq bitta** nomzod bo'lsa: avval MPN, keyin brend + model;
  - ikki variant (8GB / 16GB) chiqsa, bog'lanmaydi, xodim `spec-candidates` dan tanlaydi;
  - xodim tanlagan (MANUAL) bog'lanishni avtomatika o'zgartirmaydi;
  - boshqa turdagi modelni bog'lab bo'lmaydi.

### 4.5 API

**Shop paneli (`/api/v1/shop`):**
- `GET /categories`
- `GET /products` — `status`, `category`, `q`, `sort` (`-updated_at`, `-created_at`, `title`), `limit`, `cursor`
- `GET /products/counts`, `POST /products`, `GET/PATCH /products/{id}`
- `POST /products/{id}/publish`, `…/hide`, `…/archive`
- `POST /products/{id}/skus`, `PATCH /skus/{id}`, `POST /skus/{id}/archive`
- `POST /products/{id}/media`, `DELETE /products/{id}/media/{media_id}`, `PUT /products/{id}/media/order`
- `PUT /skus/{id}/price`, `GET /skus/{id}/price-history`
- `GET/POST /exchange-rates`
- `GET /hardware-specs`, `GET /skus/{id}/spec-candidates`, `PUT/DELETE /skus/{id}/spec-link`, `POST /skus/auto-link`
- `GET/POST /hardware-spec-requests`
- `POST /files`, `GET /files/{id}`

**Platforma paneli (`/api/v1/platform`):**
- `GET/POST /catalog/categories`, `PATCH /catalog/categories/{code}`
- `GET/POST /hardware-specs`, `GET /hardware-specs/review-queue`, `GET /hardware-specs/{id}`
- `POST /hardware-specs/{id}/versions`, `…/versions/{n}/approve`, `…/versions/{n}/reject`, `…/retire`
- `GET /hardware-spec-requests`, `POST …/{id}/resolve`, `POST …/{id}/reject`

**Ochiq:** `GET /api/v1/public/files/{key}`.

Yozish so'rovlari `Idempotency-Key` bilan, tahrir esa `If-Match` bilan. OpenAPI'da operation id'lar barqaror: `catalog_list_products`, `platform_approve_hardware_spec_version`, `files_upload_file` va boshqalar.

### 4.6 Ruxsatlar

- **Ega:** hammasi, arxivlash ham.
- **Menejer:** hammasi, arxivlashdan tashqari.
- **Operator va omborchi:** mahsulot va narxni faqat ko'radi.
- **Platforma admini:** kutubxona, toifalar, so'rovlar.
- **Kutubxona muharriri:** kutubxona va so'rovlar.
- **Yordam (support):** kutubxonani faqat ko'radi.

## 5. Testlar

- [x] Backend `make check` → **246 passed** (oldin 205, +41). ruff, mypy strict va import-linter xatosiz.
- [x] `test_catalog.py` (22 ta, haqiqiy PostgreSQL, HTTP orqali):
  - FSM-02 to'liq yo'li va `transition_log`; arxivdagi mahsulot o'zgarmaydi;
  - chiqarish shartlari: SKU, narx, dollar uchun kurs;
  - rollar: menejer arxivlay olmaydi; operator va omborchi faqat ko'radi;
  - SKU kodi shop ichida yagona, boshqa shopda mumkin;
  - takroriy so'rov: bir xil javob; boshqa tana bilan — `IDEMPOTENCY_KEY_REUSED`;
  - `If-Match`: mahsulot va narx (`v0`, eskirgan versiya); narx tarixi;
  - narx va kurs tarixini ilova roli o'zgartira olmaydi (`InsufficientPrivilege`);
  - dollar → so'm yaxlitlanmasdan (12 800, 12 835, 12 800.123456);
  - kurs eskirishi va kelajak sanasi;
  - saytdagi mahsulotning oxirgi SKU'si arxivlanmaydi;
  - cursor bilan sahifalash, filtrlar, qidiruv (SKU kodi bo'yicha ham), sanoqlar;
  - yuklash: tur ichidan, 413, 415, ruxsatsiz 403; yopiq fayl va imzo (soxta, muddati o'tgan);
  - rasmlar: ulash, tartib, olib tashlash;
  - A shop B shopning mahsulot, narx va fayliga tegolmaydi (404), birovning faylini ulay olmaydi;
  - RLS: kontekstsiz va boshqa shop kontekstida 8 ta jadvalda 0 qator;
  - ikki ko'z: o'zini tasdiqlay olmaydi; o'zgarish tasdiqgacha ishlamaydi; rad etish; atribut va takror model xatolari;
  - yordam roli kutubxonani ko'radi, yoza olmaydi;
  - avtomatik bog'lash: model, MPN (boshqacha yozilgan), ikki variant, kutubxonada yo'q; qo'lda bog'lash saqlanadi; boshqa tur rad etiladi;
  - "yangi model" so'rovi hal qilinganda SKU bog'lanadi; qayta hal qilib bo'lmaydi;
  - toifalar platformada; faol emas toifaga mahsulot qo'shilmaydi; aylana ota toifa rad etiladi;
  - `CatalogQueryPort` narx nusxasini beradi, boshqa shop SKU'sini bermaydi.
- [x] `test_catalog_units.py` (19 ta): so'mga o'girish, normallashtirish (Ti va variantlar), fayl turi, imzo, disk adapteri (`..`), kalitdan shop, atributlar sxemasi, cursor.
- [x] Migratsiyalar: hamma schema yuqoriga va pastga o'tadi, ORM bilan farq yo'q (`alembic check`).
- [x] Demo seed testi: 18 mahsulot, 12 tasdiqlangan model, 13 bog'lanish, 1 so'rov, 4 rasm; qayta ishga tushirilsa takrorlamaydi.
- [x] Dev bazada (`commerce_os_dev`) migratsiya va seed bajarildi. Ishlab turgan backend :8000 da tekshirildi:
  - ro'yxat va sanoqlar;
  - rasm ochiq manzildan;
  - TechPC kursi va KompyuterPro'ning eskirgan kursi;
  - tasdiq navbati va so'rovlar navbati.

## 6. Jarayonda topilgan muammolar

- **PostgreSQL nom chegarasi (63 belgi).** Uchta avtomatik constraint nomi uzun chiqdi: spec unikalligi, versiya FK, joriy narx FK. Ularga qo'lda qisqa nom berildi, aks holda `alembic check` farq ko'rsatardi.
- **Flush'dan keyingi eski ustunlar.** `updated_at` bazada yangilanadi, async rejimda esa uni o'qish xato beradi. Javob yig'ishdan oldin qator qayta o'qiladi (`populate_existing` / `refresh`).
- **Chiqarish va idempotency.** Avval buyruq (PUBLISH yoki REPUBLISH) route'da tanlanardi. Shunda takroriy so'rov boshqa operatsiya bo'lib qolardi. Tuzatildi: kalit bitta (`catalog.product.publish:{id}`), buyruqni servis qulf ostida tanlaydi.
- **SQLAlchemy 2.1 eskirgan chaqiruvlari.** `Result.tuples()` va `distinct(col)` o'rniga Row'ni to'g'ridan ochish va `distinct_on` ishlatildi.
- **MinIO.** Obrazi Docker Hub'dan yuklanmaydi. U `docker-compose.yml` va `make up` dan olib tashlandi, dev'da fayllar `var/storage` da (git'ga kirmaydi).

## 7. Keyingi modulga meros

- **3-modul (ombor va buyurtmalar):**
  - SKU va narxni faqat `app.dependencies.get_catalog_query()` orqali oladi. `SkuSnapshot` da nom, kod, `price_version_id`, narx, kurs ID'si, so'm narxi va kafolat bor;
  - tasdiqlashda shu port qayta chaqiriladi va so'm narxi solishtiriladi (DEC-134);
  - stok dalili rasmi: `POST /shop/files?purpose=STOCK_EVIDENCE`. Yuklash uchun ruxsat `commerce.stock.adjust_request` rollarga qo'shilishi kerak.
- **Frontend (2-modul):**
  - `pnpm api:generate`, keyin sahifalar: mahsulotlar ro'yxati (tablar — `counts`), kartochka (variantlar, narx, rasmlar, bog'lanish), kurslar;
  - platforma panelida kutubxona, tasdiq navbati va so'rovlar.
  - Rasm yuklash: `fetch(POST /shop/files?purpose=PRODUCT_IMAGE, body: file)`, keyin `POST /products/{id}/media`.
- **Qoidalar:**
  - shop jadvaliga RLS siyosati bir xil (`shop_isolation`);
  - o'zgarmas tarix jadvallariga `REVOKE UPDATE, DELETE`;
  - DTO'da pul `amount_minor` + `currency`, kurs esa matn (`"12800.000000"`).

---

## 8. Frontend (2026-10-25)

> **Repo:** `ai-commerce-frontend` (`feat/m1-frontend`). **Commit qilinmagan.** Dizayn — hozirgi qorong'i "Command center" uslubi.

### 8.1 Nima bitdi — qisqacha

Shop paneliga "Katalog" bo'limi, platforma paneliga texnik kutubxona, shop so'rovlari va toifalar qo'shildi. Hamma ekran haqiqiy API bilan ishlaydi: ma'lumot bazadan keladi, soxta ma'lumot yo'q.

```
Shop: Katalog → "Mahsulot qo'shish" → toifa, nom, SKU, narx → qoralama
      kartochka → rasm yuklash → "Saytga chiqarish" (yetishmasa — nima yetishmayotgani ro'yxati)
      → "Yashirish" ⇄ "Qayta chiqarish" → "Arxivlash" (faqat ega, tasdiq oynasi)
      SKU → "Kutubxonaga bog'lash" → nomzodlar / qidiruv → topilmasa "Yangi model so'rash"
Platforma: Shop so'rovlari → "Modelni kiritish" (so'rovdan to'ldirilgan) → tasdiq navbati
      → boshqa odam "Tasdiqlash" → so'rov → "Kutubxonadan tanlash" → shop varianti bog'lanadi
```

### 8.2 Sahifalar

**Shop paneli** (`apps/shop-dashboard`, menyuda "Katalog" — `catalog.product.view`):
- `/[shop]/catalog` — mahsulotlar:
  - holat tablari sanoqlar bilan; "Hammasi" — arxivdagilarsiz, arxiv o'z tabida;
  - qidiruv (nom, brend, SKU kodi, MPN), toifa filtri, saralash;
  - "Yana ko'rsatish" (cursor);
  - qatorda: rasm, nom, brend, toifa, variantlar soni, eng arzon narx, holat.
- `/[shop]/catalog/new` — yangi mahsulot: kartochka, birinchi variant va narx bitta so'rovda (qoralama).
- `/[shop]/catalog/[id]` — kartochka:
  - holat tugmalari: chiqarish / qayta chiqarish, yashirish, arxivlash (ruxsatga qarab);
  - variantlar: qo'shish (narxi bilan), tahrirlash, arxivlash;
  - narx oynasi: so'm yoki dollar, sabab, so'mdagi oldindan ko'rish, narx tarixi; birinchi narx `If-Match: "v0"`;
  - kutubxonaga bog'lanish holati (MPN / model / qo'lda), bog'lash, uzish, "Qayta tekshirish";
  - rasmlar: yuklash (ko'pi bilan 10 ta), tartib, olib tashlash;
  - asosiy ma'lumotlar: faqat o'zgargan maydon yuboriladi; toifa o'zgarib bog'lanish olib tashlansa — xabar;
  - arxivdagi mahsulot faqat o'qish uchun.
- `/[shop]/catalog/rates` — dollar kursi: joriy kurs, "Amalda / Eskirgan" belgisi, yangi kurs, tarix.
- `/[shop]/catalog/requests` — "yangi model" so'rovlari va platforma javobi.
- Bosh sahifa — katalog kartasi: holatlar bo'yicha sanoq va kurs ogohlantirishi.

**Platforma paneli** (`apps/platform-admin`):
- `/library` — modellar: qidiruv, tur va holat filtri, "Model qo'shish" (`platform.spec.edit`).
- `/library/review` — tasdiq navbati; o'z taklifi "Sizning taklifingiz" belgisi bilan.
- `/library/[id]` — model:
  - kutayotgan taklif: joriy ma'lumot bilan farqi;
  - tasdiqlash yoki rad etish (sabab bilan); o'z taklifida tugma yo'q, "boshqa odam tasdiqlashi kerak";
  - o'zgarish taklif qilish, eskirgan deb belgilash, versiyalar tarixi.
- `/spec-requests` — hamma shoplar so'rovlari: kutubxonadan tanlash (faqat tasdiqlangan, shu tur), so'rovdan model kiritish, rad etish.
- `/categories` — toifalar daraxti, 3 tilda; qo'shish va tahrirlash faqat admin (`platform.category.edit`).
- Kutubxona muharriri (SPEC_EDITOR) kirganda bosh sahifa o'rniga `/library` ga tushadi.
- Menyu va ⌘K buyruqlari ruxsatga qarab.

### 8.3 Fayllar xaritasi

```
ai-commerce-frontend/
├── packages/app-kit/src/money.ts            # pul: ko'rsatish, kiritish, dollar → so'm (backend bilan bir xil yaxlitlash), kurs
├── packages/app-kit/src/index.tsx           # useMoney() — tildagi "so'm / сум / UZS" bilan
├── packages/i18n/src/index.tsx              # qat'iy chegara (gt/lt) matni
├── packages/i18n/src/messages/{uz,ru,en}.ts # katalog, kutubxona, toifalar, xususiyatlar, jurnal amallari (+378 kalit)
├── apps/shop-dashboard/src/
│   ├── lib/catalog.ts                       # turlar, so'rov kalitlari, toifalar daraxti, applyProduct()
│   ├── lib/nav.ts                           # menyuda "Katalog"
│   ├── components/catalog/
│   │   ├── common.tsx                       # holat belgisi, katalog tablari, kurs ogohlantirishi
│   │   ├── forms.tsx                        # mahsulot, SKU, narx maydonlari va mijoz tekshiruvi
│   │   ├── lifecycle.tsx                    # FSM-02 tugmalari, chiqarish shartlari, arxiv oynasi
│   │   ├── sku-section.tsx                  # variantlar, narx oynasi va tarixi, bog'lash
│   │   ├── media-card.tsx                   # rasmlar: yuklash, tartib, olib tashlash
│   │   ├── spec-link.tsx                    # kutubxonaga bog'lash oynasi
│   │   └── spec-request.tsx                 # "yangi model" so'rovi oynasi
│   └── app/[shop]/catalog/{page, new, [id], rates, requests}
├── apps/platform-admin/src/
│   ├── lib/library.ts                       # turlar, kalitlar, 8 tur uchun atributlar sxemasi (17 §4.1)
│   ├── components/{spec-dialog, note-dialog, library-tabs}.tsx
│   ├── components/{shell, command-palette}.tsx   # yangi menyu bandlari va buyruqlar
│   └── app/(admin)/{library, library/review, library/[id], spec-requests, categories}
└── e2e/catalog.spec.ts                      # 3 ta oqim
```

### 8.4 Muhim qarorlar

- **Pul faqat butun son.** So'm ko'rsatilganda tiyin bo'lsa ko'rinadi (`4 750 000,50 so'm`); dollar narxining so'mdagi oldindan ko'rinishi backend'dagi `to_uzs_minor` bilan bir xil hisoblanadi (BigInt, ROUND_HALF_UP). Haqiqiy narxni baribir server beradi.
- **Rasm yuklash** — fayl so'rov tanasida (`Content-Type` — fayl turi), har mahsulotga yangi fayl. Tur va hajm mijozda ham tekshiriladi, asosiy tekshiruv — serverda.
- **Idempotency-Key** har buyruqqa alohida (chiqarish, yashirish, arxivlash), xatodan keyin qayta bosilsa o'sha kalit.
- **"Yangi model" so'rovi** variantdan ochilsa, turi mahsulot toifasidan olinadi va o'zgartirilmaydi (server ham tekshiradi).
- **Texnik atributlar formasi** backend sxemasidan ko'chirilgan: bo'sh maydon — "noma'lum" (0 emas); ro'yxatlar vergul bilan, ulagichlar `PCIE_8PIN x2`, BIOS `protsessor | versiya`.

### 8.5 Tekshiruv

- [x] `pnpm api:generate` (backend QA tuzatishlaridan keyin qayta) → `pnpm check` (typecheck + lint) xatosiz.
- [x] Ikkala `next build` — e2e ichida, muvaffaqiyatli.
- [x] Playwright — **8/8** (alohida muhit: `commerce_os_e2e`, :8001, :3100/:3101). 1-modulning 5 ta testi o'zgarmay o'tdi, katalogning 3 ta yangi testi:
  - ega mahsulot yaratadi → narx (so'm, aniq) → rasm (yuklanadi va ochiladi) → narxni o'zgartiradi (`4 750 000,50`) → chiqaradi → yashiradi → ro'yxatda tab va qidiruv → menejerda "Arxivlash" yo'q va server 403 qaytaradi → ega arxivlaydi (faqat o'qish) → telefonda (390px) 5 ta katalog sahifasi enidan oshmaydi;
  - dollar narxi: kurs yo'q — ogohlantirish va "chiqarib bo'lmaydi: avval kurs"; kurs 12 835 → `3 850 500 so'm`, chiqariladi; oldindan ko'rish `299.99 $ → 3 850 372 so'm`;
  - kutubxona: shop so'rovi (turi qulflangan) → muharrir `/library` ga tushadi, so'rovdan model kiritadi → o'zi tasdiqlay olmaydi → admin tasdiqlaydi va so'rovni hal qiladi → shop variantida model ko'rinadi, so'rov "Qo'shildi" → platformaning 5 ta kutubxona sahifasi telefonda enidan oshmaydi.
- [x] Dev serverlarda (:3000/:3001) demo ma'lumot bilan skrinshotlar ko'rib chiqildi.

### 8.6 Jarayonda topilgan muammolar

- **E2E'da rasm ochilmadi.** Backend ochiq fayl manzilini `PUBLIC_FILES_URL` dan quradi (standart — :8000). E2E backend'i :8001 da, shuning uchun `e2e/env.ts` ga `PUBLIC_FILES_URL` qo'shildi.
- **Test poygasi.** Ro'yxatdagi toifa filtri ham "Toifa" deb nomlangan; test yangi sahifa ochilishini kutmasdan filtrni tanlab qo'ygan. Test endi sarlavhani kutadi.
- **"Hammasi" tabida arxiv.** Demo shopda 65 ta arxivdagi QA mahsuloti ro'yxatni to'ldirib yubordi. "Hammasi" endi arxivsiz (`status` = qoralama, tekshiruvda, saytda, yashirilgan), bosh sahifadagi sanoq ham shunday.

### 8.7 Ochiq qolganlar

- Backend o'zgartirilmadi. Frontend uchun to'siq bo'lgan backend xatosi topilmadi.
- Dev bazadagi TechPC'da QA agenti yaratgan ko'p "QA …" mahsulot va kutubxona yozuvi bor — demo uchun tozalash kerak bo'lishi mumkin.
- Kutubxona ro'yxatida "eskirgan"larni standart yashirish uchun backend `status` filtri ko'p qiymatni qabul qilishi kerak (hozir bitta) — keyin.

---

## 9. QA tekshiruvi va tuzatishlar (2026-10-25)

Mustaqil QA agenti backend'ni HTTP orqali tekshirdi: 6 ta o'rtacha va 17 ta kichik muammo, jiddiysi yo'q. Rollar, shoplar izolyatsiyasi, narx tarixi va "ikki ko'z" bo'yicha 119 ta tekshiruv o'tgan edi. Hammasi tuzatildi, har biriga test yozildi.

### 9.1 Umumiy himoya — `app/shared/request_guard.py` (yangi)

So'rov endpoint'ga yetguncha:
```
yo'lda NUL (%00) ──▶ 404
query'da NUL ──▶ 422, maydon — parametr nomi (q)
JSON'da NUL yoki NaN/Infinity ──▶ 422, maydon yo'li (skus[0].variant_name)
JSON 1 MB dan katta ──▶ 413
deadlock / serialization ──▶ butun so'rov qayta (3 urinishgacha) ──▶ baribir bo'lmasa 409 VERSION_CONFLICT
```
- Avval NUL belgisi PostgreSQL'ga yetib, 500 berardi — ochiq rasm manzilida tokensiz ham (M1).
- Qayta urinish engineering/12 §3 bo'yicha. Fayl yuklash qayta urinilmaydi (tanasini qayta yuborib bo'lmaydi) — darhol 409.

### 9.2 O'rtacha topilmalar

- **M1 — NUL belgisi.** Umumiy himoya (9.1) va `Text` tipi (`app/shared/text.py`): bo'shliq kesiladi, keyin uzunlik tekshiriladi, NUL rad etiladi.
- **M2 — kurs vaqti.** `effective_at` faqat vaqt mintaqasi bilan (`2026-10-25T09:00:00+05:00`); mintaqasizi — 422 `invalid_format`, 2000-yildan oldingisi — 422 `min_value`.
- **M3 — avtomatik bog'lash.** Brend + model bo'yicha topilgan modelda:
  - varianti ("8GB") SKU'da ko'rinishi shart — variant nomi, mahsulot nomi yoki atributlarda;
  - SKU boshqa hajmni aytsa ("16GB") yoki MPN'i zid bo'lsa — bog'lanmaydi;
  - hajmlar GB'da solishtiriladi ("1TB" = `capacity_gb: 1000`);
  - shubha bo'lsa — bog'lanmaydi, xodim nomzodlardan tanlaydi (nomzodlar ro'yxati o'zgarmadi).
- **M4 — so'rov va boshqa tur.** "Yangi model" so'rovida tur SKU mahsuloti turi bilan bir xil bo'lishi shart (`category/invalid_choice`). Hal qilishda yana tekshiriladi: mahsulot toifasi almashgan bo'lsa — 422, arxivda bo'lsa — 409 (L10 ham shu). Navbatda SKU'ning hozirgi turi ko'rinadi (`sku_spec_category`).
- **M5 — toifa almashsa.** Boshqa turdagi modelga bog'lanish (qo'lda bo'lsa ham) uziladi, jurnalda sababi `category_changed`.
- **M6 — bitta fayl, ikki mahsulot.** Endi bitta fayl faqat bitta mahsulot rasmi bo'ladi: ikkinchisiga ulash — 409 `FILE_IN_USE` (yangi kod, uz/ru/en). Bazada unikal cheklov ham bor. O'chirilgan faylga havola endi ko'rsatilmaydi.

### 9.3 Kichik topilmalar

- **L1** — SKU atributida NaN, Infinity va 2^53 dan katta son — 422.
- **L2** — buzilgan cursor (noto'g'ri tur, NUL, mintaqasiz vaqt) — 422 `cursor/invalid_format`.
- **L3** — platforma ro'yxatlarida `offset ≤ 100 000`, yo'ldagi versiya raqami `1…1 000 000` — 422.
- **L4** — deadlock'da qayta urinish (9.1). Toifa va yangi ota toifa bir xil tartibda qulflanadi: "A → B" va "B → A" bir vaqtda kelsa, biri o'tadi, ikkinchisi aylanani ko'radi (422).
- **L5, L6** — faqat bo'shliqdan iborat izoh, brend, nom — 422 (bo'shliq uzunlikdan oldin kesiladi).
- **L7** — arxivdagi mahsulotning SKU'sini arxivlab bo'lmaydi — 409.
- **L8** — kutubxonada brend katta-kichik harfsiz solishtiriladi (`brand_normalized`). Yagonalik va MPN yagonaligi faqat eskirmagan modellar orasida; parallel kiritishni bazadagi indeks ushlaydi.
- **L9** — xodim uzgan bog'lanishni avtomatika qayta tiklamaydi (`spec_autolink_blocked`). Xodim o'zi bog'lasa yoki platforma so'rovni hal qilsa — taqiq olinadi.
- **L11** — fayl yuklashda avval token tekshiriladi (bazasiz), keyin tana o'qiladi: anonim 6 MB so'rov endi 401.
- **L12** — rasm tuzilmasi tekshiriladi: PNG (IHDR, IDAT, IEND), JPEG (SOF segmenti), WebP (RIFF hajmi, VP8 bo'lagi). 3 baytlik "JPEG" va PNG sarlavhasi + HTML — 415.
- **L13** — `PATCH /shop/skus/{id}` javobidagi `ETag` — SKU versiyasi.
- **L14** — `?status=PUBLISHED,HIDDEN` ham ishlaydi.
- **L15** — 201 javoblarida `Location`: mahsulot, SKU (mahsulotga), fayl, kutubxona modeli va taklif, toifa. Toifa uchun `GET /platform/catalog/categories/{code}` qo'shildi. Kurs va shop so'rovida alohida o'qish manzili yo'q — `Location` qo'yilmadi.
- **L16** — qat'iy chegara: narx `0` → `{"min": 1}`, kurs `0` → `{"min": "0.000001"}` (11 §6.3 yangilandi).
- **L17** — dollar narxi ko'pi bilan `9 007 199 254` sent (~90 mln $): eng katta kursda ham so'mdagi narx brauzer aniq o'qiydigan son ichida qoladi.

### 9.4 Kuzatuvlar bo'yicha qarorlar

- **SKU kodi katta-kichik harfsiz yagona** ("ABC-1" = "abc-1"). Service tranzaksiya qulfi bilan tekshiradi, bazada `lower(sku_code)` indeksi. Unikal indeks emas: dev bazada QA yaratgan bitta shunday juft bor, migratsiya ma'lumotni o'chirmaydi.
- **Fayl nomidan yo'nalish belgilari olib tashlanadi** (U+202A–U+202E, U+2066–U+2069): `rasm\u202egnp.exe` ekranda `rasmexe.png` bo'lib ko'rinmaydi.
- **So'mga o'girish** — eng yaqin butun so'm, 0.5 yuqoriga (`0.01 $ × 12 850 = 129 so'm`). Bu DEC-133 "aniq so'mgacha", mingliklarga yaxlitlash emas. catalog.md matni aniqlashtirildi.
- **O'zgarishsiz qoldi:**
  - faol emas toifadagi eski mahsulotni chiqarish mumkin — faolsizlantirish faqat yangi mahsulotni to'xtatadi;
  - eskirgan modelni qaytarish amali yo'q. Lekin endi shu modelni qayta kiritish mumkin (yagonalik eskirganlarni hisobga olmaydi).

### 9.5 Baza — `catalog_0003_qa_fixes`

- `reference_hardware_specs.brand_normalized` (mavjud yozuvlar migratsiyada to'ldirildi); model va MPN unikal indekslari — `status <> 'RETIRED'` bilan.
- `skus.spec_autolink_blocked` va `(shop_id, lower(sku_code))` indeksi.
- `product_media (shop_id, file_id)` unikal.
- `commerce_os_dev` ga qo'llandi, QA ma'lumotiga tegilmadi.

### 9.6 Frontend bilishi kerak bo'lgan o'zgarishlar

- `effective_at` — mintaqasi bilan yuborilsin (`new Date(local).toISOString()`) yoki umuman yuborilmasin (hozirdan).
- Boshqa mahsulotdagi rasmni ulash — 409 `FILE_IN_USE` (`details.product_id`). Odatiy oqim (har rasm yangi yuklanadi) o'zgarmaydi.
- `SkuOut.spec_autolink_blocked` (yangi maydon). Bog'lanishni uzish yoki qo'lda bog'lash SKU versiyasini oshiradi — keyingi `PATCH` dan oldin mahsulotni qayta o'qish kerak.
- `PATCH /shop/skus/{id}` `ETag` — SKU versiyasi.
- "Yangi model" so'rovida `category` SKU mahsuloti turi bilan bir xil bo'lishi shart.
- `PlatformSpecRequestOut.sku_spec_category` (yangi maydon) — so'rov turi bilan farq qilsa, hal qilib bo'lmaydi.
- Yangi xato kodi `FILE_IN_USE`, yangi `params.exclusive` va `params.expected`.

### 9.7 Testlar

- [x] `make check` → **278 passed** (oldin 246). ruff, mypy strict, import-linter xatosiz.
- [x] `tests/integration/test_catalog_qa_fixes.py` (17 ta, HTTP orqali) — har topilma uchun bitta: avval 500 yoki noto'g'ri natija bergan so'rov endi to'g'ri javob beradi. Parallel holatlar (ota toifa almashinuvi, kutubxonaga parallel kiritish) bir necha marta takroran o'tdi.
- [x] `tests/unit/test_catalog_qa_fixes.py` (15 ta): NUL/NaN yo'llari, `Text` tipi, qayta urinish (3 urinish, xuddi shu tana; boshqa baza xatosi qayta urinilmaydi), qat'iy chegara, dollar chegarasi, variant qoidasi, rasm tuzilmasi, fayl nomi.
- [x] Mavjud testlardagi soxta rasm baytlari haqiqiy tuzilmali rasmlarga almashtirildi (`tests/images.py`).
- [x] Seed testi: 13 ta bog'lanish saqlanib qoldi ("1TB" ↔ `capacity_gb: 1000`).

### 9.8 QA 2-tur (2026-10-25): tekshiruv natijasi va tuzatishlar

QA agenti 23 ta tuzatishni qayta tekshirdi: 22 tasi tuzatilgan, 1 tasi qisman (`Location` ikki endpoint'da yo'q edi). Yangi topilmalar: backend'da 2 ta kichik, interfeysda 1 ta o'rtacha va 10 ta kichik. Hammasi tuzatildi:

**Backend**
- **B1 — `Location`.** Yangi `GET /shop/exchange-rates/{rate_id}` va `GET /shop/hardware-spec-requests/{request_id}` (ro'yxat bilan bir xil ruxsat; boshqa shopniki — 404). Ikkala `201` javobida endi `Location` bor.
- **B2 — PNG oxiridagi qo'shimcha baytlar.** Tekshiruv endi bo'laklar bo'yicha yuradi: IHDR → kamida bitta IDAT → IEND. IEND'dan keyingi baytlar e'tiborsiz (ba'zi dasturlar qo'shadi), kesilgan bo'lak — rad.
- **Qayta urinish va rate limit.** `/api/v1/auth/` yo'llari deadlock'da butun so'rov sifatida qayta bajarilmaydi: u yerda tranzaksiyadan tashqari effekt bor (login urinishlari hisoblagichi), qayta urinish uni ikki marta oshirardi. Test bilan.

**Interfeys**
- **U1 — abadiy skeleton.** Umumiy `QueryError` (app-kit): tushunarli matn, murojaat raqami va "Qayta urinish" tugmasi; tarmoq uzilsa — o'z matni. Katalog, kutubxona va boshqa hamma ro'yxat va detal sahifalarida. Manzildagi noto'g'ri id (422) — "topilmadi".
- **U2 — ikki marta bosish.** `useGuardedMutate` (app-kit): mutatsiya tugaguncha takroriy bosish e'tiborsiz. "Chiqarish", "Yashirish", "Arxivlash", "Tasdiqlash", sabab dialogi (rad etish, eskirgan deb belgilash). Bitta buyruq ishlayotganda boshqa tugmalar o'chiq. O'zimizning takroriy so'rovimiz (`REQUEST_IN_PROGRESS`) endi xato deb ko'rsatilmaydi.
- **U3 — fokus.** Dialog yopilganda (Escape, Bekor qilish, saqlandi) fokus uni ochgan tugmaga qaytadi — markazda, `@cos/ui` Dialog'da. Menyu bandidan ochilgan dialog — menyu tugmasiga.
- **U4 — "Close".** Dialogni yopish tugmasining nomi foydalanuvchi tilida (`UiTextProvider`: `@cos/ui` tilni bilmaydi, matnni app-kit beradi).
- **U5 — chegaralar birligi.** Narx va kurs maydonidagi "ko'pi bilan / kamida" xabarida qiymat foydalanuvchi birligida: sent → "$90,071,992.54", tiyin → so'm, kurs mingliklar bilan.
- **U6 — noma'lum xato kodi.** Backend'ning inglizcha matni ko'rsatilmaydi, umumiy "Kutilmagan xato" matni chiqadi (11 §8.8).
- **"Xato kodi" → "Murojaat raqami"** (ru "Номер обращения", en "Reference ID") — qo'llab-quvvatlash shu raqam bilan logdan topadi.
- **U7 — pul ko'rinishi (11 §8.7).** uz `4 800 000 so'm`, ru `4 800 000 сум`, en `UZS 4,800,000`; dollar hamma tilda `$1,250.00`. Kurs ham tilga qarab ("12 850" / "12,850").
- **U8 — telefon sarlavhasi.** Platforma panelida telefonda bitta ixcham qator: "Menyu" tugmasi (bandlar nomi bilan), joriy bo'lim nomi, qidiruv, til, foydalanuvchi — shop paneli bilan bir xil. Til tanlash telefonda qisqa kod (UZ / RU / EN), ochilgan ro'yxatda to'liq nomlar.
- **U9 — uzun qiymatlar.** Bo'shliqsiz uzun SKU kodi, variant, model va MPN katalog va kutubxona sahifalarida qatorga bo'linadi; dialog matni ham.
- **U10 — platformadagi "Ruxsat yo'q".** "Platforma administratoriga murojaat qiling" (shop egasiga emas).
- **U11 — toifalar ro'yxati telefonda.** Har qator bir xil: chapda nom va belgilar, o'ngda doim tahrir tugmasi.

**Tekshiruv**
- [x] Backend `make check` → **282 passed**. ruff, mypy strict, import-linter xatosiz.
- [x] Frontend `pnpm api:generate`, `pnpm check` — xatosiz.
- [x] E2E → **8/8**. Yangi tekshiruvlar:
  - 64 belgili SKU kodi bilan telefonda sahifa enidan oshmaydi;
  - "Chiqarish" ikki marta bosilsa — bitta so'rov, xato yo'q;
  - Escape'dan keyin fokus "Arxivlash" tugmasida;
  - platforma sarlavhasi telefonda bir qator, "Menyu" ochiladi va o'tadi.
