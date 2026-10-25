# 3-modul — Savdo: ombor, tez sotuv, buyurtmalar (backend)

> **Holat:** backend bitdi — 2026-10-26. **Commit qilinmagan**, founder ko'rib chiqishini kutmoqda. Frontend (shop paneli: "Ombor", "Tez sotuv", "Buyurtmalar") — keyingi qadam.
> **TZ:** [db/commerce.dbml](../db/commerce.dbml) va [commerce.md](../db/commerce.md) (DEC-134), [business/05](../../business/05_STATE_MACHINES_AND_EXCEPTIONS.md) FSM-07 va FSM-08, [12](../12-concurrency-and-transactions.md) §5–§7, [26](../26-privacy-and-retention.md) §4. Rejadagi bandlar: S1-05, S4-01…S4-04.
> **Repo:** `ai-commerce-backend` (`feat/s0-foundation`).

---

## 1. Nima bitdi — qisqacha

Shop endi omborini yuritadi, do'kondagi sotuvni bir bosishda kiritadi va buyurtmani qoralamadan topshirilguncha olib boradi. Har qoldiq o'zgarishi ombor daftariga yoziladi va o'chirilmaydi. Oxirgi donani ikki kishi bir vaqtda ololmaydi.

```
Kirim ──▶ qoldiq + ──▶ daftar (RECEIPT)
Tez sotuv ──▶ faqat sotuvga mavjuddan ──▶ qoldiq − ──▶ daftar (OFFLINE_SALE)
Tuzatish: omborchi so'raydi ──▶ ega/menejer tasdiqlaydi (qoldiq qayta tekshiriladi) ──▶ daftar
          ega/menejer o'zi ──▶ darhol qo'llanadi

Buyurtma: Qoralama ──▶ Tasdiq kutilmoqda ──▶ Tasdiqlandi (band) ──▶ Tayyorlanmoqda (ajratilgan)
          ──▶ Topshirildi (qoldiqdan bir marta chiqadi)
          Tasdiqlashda: qoldiq tartib bilan qulflanadi ──▶ yetmasa — hech narsa band qilinmaydi
                        so'mdagi narx (joriy narx × joriy kurs) o'zgargan bo'lsa — PRICE_CHANGED
                        ──▶ "narxlarni yangilash" (xaridor rozi) ──▶ qayta tasdiqlash
          72 soat olib ketilmasa ──▶ "ko'rib chiqish kerak" ──▶ menejer: kutamiz (yana 72 soat) yoki bekor
```

Xaridor telefoni va manzili bazada shifrlangan (AES-256-GCM). Telefon bo'yicha qidirish kalitli xesh orqali ishlaydi. Logga, audit diff'ga va takroriy so'rov jadvaliga ochiq holda tushmaydi.

## 2. Rejadagi bandlar

- [x] **PII shifrlash (26 §4):**
  - `cryptography` kutubxonasi qo'shildi (founder tasdig'i, vazifa kartasi);
  - `EncryptedString` turi (`app/shared/db/encryption.py`): AES-256-GCM, har qiymatda kalit identifikatori — rotatsiyada eski yozuvlar eski kalit bilan o'qiladi;
  - telefon bo'yicha qidirish — alohida kalitli HMAC-SHA256;
  - kalitlar sozlamada (`PII_ENCRYPTION_KEYS`, `PII_ACTIVE_KEY_ID`, `PII_HMAC_KEY`); lokal standart kalitlar staging va production'da rad etiladi.
- [x] **S1-05 — ombor:**
  - qoldiq (filial × SKU: qoldiq, band, ajratilgan, tekshiruvda; sotuvga mavjud hisoblanadi);
  - ombor daftari — faqat qo'shiladi (ilova roliga UPDATE/DELETE berilmagan), o'zgarishdan keyingi qiymatlar bilan;
  - kirim hujjati (bir nechta mahsulot, takrori qo'shib yuboriladi);
  - qo'lda tuzatish: sanoq farqi, "sotilmaydi" (tekshiruvga), sotuvga qaytarish, hisobdan chiqarish; dalil rasmi (yopiq fayl);
  - qoldiq ro'yxati (filial, qidiruv, "kam qolgan"), mahsulot tarixi;
  - daftar va qoldiqni solishtirish funksiyasi (har kecha ishlashi — S0-06).
- [x] **Tez sotuv (DEC-123):** mahsulot + miqdor, narx katalogdan avtomatik, faqat sotuvga mavjuddan; band mahsulot sotilmaydi (BL-109); bekor qilinmaydi.
- [x] **S4-01 — buyurtma va tasdiqlash:**
  - xodim yaratgan qoralama, shop ichida ketma-ket raqam;
  - qatorlarda nom, kod, narx, kurs va kafolat — nusxa;
  - tasdiqlash bitta tranzaksiyada: qoldiq qulfi tartib bilan, har qatorga band, daftarga RESERVE;
  - operator faqat o'ziga biriktirilganini tasdiqlaydi; biriktirilmaganini o'ziga oladi; menejer biriktiradi (DEC-108).
- [x] **S4-02 — tayyorlash, topshirish, bekor qilish:** band → ajratilgan → qoldiqdan chiqadi; bekor qilishda band bir marta bo'shaydi; "muammoli" holat va uni hal qilish.
- [x] **S4-03:** izohlar va qo'ng'iroq natijasi, olib ketish yoki yetkazish (manzil shifrlangan), "to'landi" belgisi (bir marta).
- [x] **S4-04 — narx o'zgarishi:** tasdiqlashda so'mdagi narx qayta hisoblanadi; farq bo'lsa — `PRICE_CHANGED` va hech narsa o'zgarmaydi; kurs eskirgan bo'lsa — `EXCHANGE_RATE_STALE` (BL-018).
- [x] **Chegirma (DEC-110):** rol limitigacha darhol, undan ko'pi — tasdiq so'rovi; tasdiqlanmaguncha summaga kirmaydi va buyurtmani tasdiqlab bo'lmaydi.
- [x] **"Ko'rib chiqish kerak"** — 24 soat tasdiqlanmagan va 72 soat olib ketilmagan buyurtmalar ro'yxati va menejer qarori (DEC-104, DEC-134).
- [x] **Xaridor ma'lumotini anonimlashtirish** — service funksiyasi (26 §2): faqat yakunlangan buyurtmalar.
- [x] **`StockQueryPort`** (`app/shared/contracts/commerce.py`) — 4-modul (sayt) uchun: faqat chiqarilgan SKU'lar, faol filiallar bo'yicha jami va olib ketish joylari alohida.
- [x] **Ruxsatlar** — 10 §6.3 bo'yicha (§4.7).
- [x] **Demo ma'lumot (`make seed`)** — TechPC va NoutbukUz (§4.8).

**Ataylab keyinga qoldirilganlar:**
- **Rejali ishlar va bildirishnomalar.** 24 va 72 soatlik eslatmalar hozir har so'rovda hisoblanadi ("ko'rib chiqish" ro'yxati, `needs_review` filtri). Menejerga vazifa va xabar — fon ishlari bilan (S0-06, 5-modul).
- **Event'lar** (`commerce.order.confirmed`, `commerce.stock.changed`). Outbox hali yo'q — kodda `TODO(S0-06)`.
- **Xaridorga holat xabarlari** (S4-06) — kanallar bilan (5-modul).
- **Kechki solishtirish** — funksiya bor (`StockService.reconcile`), rejali ish S0-06 bilan.
- **Saytdan buyurtma so'rovi** (4-modul), **AI qoralamasi va PC taklifi** (6-modul). `orders.source` da `STOREFRONT` va `AI` qiymatlari tayyor.
- **72 soat — shop sozlamasi emas, hozircha doimiy** (`RESERVATION_REVIEW_HOURS`). `shop_policies` ga ustun qo'shish va sozlamalar ekrani — keyin.
- **Anonimlashtirish so'rovi API'si** — platformadagi `privacy` moduli bilan (26 §2). Funksiya `DomainManifest.privacy_handlers` da ro'yxatga olingan.

**Kartadan va TZ'dan farqlar:**
- **Tuzatish yo'li `POST /shop/stock/adjustments`** (11 §9.4 da `adjustment-requests`). Jadval endi ega/menejerning to'g'ridan tuzatishini ham saqlaydi (DEC-134), shuning uchun nom umumiy.
- **Chegirma — qator ichida:** `PUT /orders/{id}/lines/{line_id}/discount` va `…/discount/approve|reject` (11 §9.4 da alohida `discount-requests`). Chegirma ustunlari `order_lines` da (commerce.dbml), alohida jadval yo'q.
- **Operator "own" ko'rinishi:** o'ziga biriktirilganlar **va** biriktirilmagan navbat — aks holda u buyurtmani o'ziga ola olmasdi. Omborchi faqat tasdiqlangandan keyingi buyurtmalarni ko'radi (tayyorlash uchun).
- **Qoralama qatorini o'chirish mumkin** (`order_lines` da DELETE ruxsati qoldi). Boshqa biznes jadvallarida DELETE yo'q; daftar, kirim va tez sotuvda UPDATE ham yo'q.
- **Takroriy so'rov buyurtmaning joriy holatini qaytaradi**, saqlangan javobni emas: javobda telefon va manzil bor, ular `idempotency_keys` ga ochiq yozilmasligi kerak (faqat buyurtma ID'si saqlanadi).
- **Tez sotuvda eskirgan kurs to'xtatmaydi** — sotuv allaqachon bo'lgan, uni yozmaslik qoldiqni buzardi. Eskirgan kurs faqat buyurtmani tasdiqlash va narxni yangilashni to'xtatadi (BL-018).
- **Band o'tishlari `transition_log` ga yozilmaydi** — ularning yozuvi ombor daftarida (RESERVE, ALLOCATE, SALE, RELEASE). FSM-07 qoidalari baribir har o'tishda tekshiriladi.
- **DBML'ga qo'shimchalar:** ro'yxatlar uchun `(shop_id, created_at)` indekslari (buyurtma, kirim, tez sotuv), "ko'rib chiqish" indeksi `(shop_id, review_at)`, tuzatish sababi ≥ 3 belgi va qator narxi > 0 tekshiruvlari. Diagramma yangilandi.
- **`CatalogQueryPort` kengaydi:** `product_status`, `sku_status`, `exchange_rate_effective_at`, `exchange_rate_stale` va `search_sku_ids()` (qoldiq ro'yxatida mahsulot nomi bo'yicha qidirish).

## 3. Fayllar xaritasi

```
ai-commerce-backend/
├── app/shared/
│   ├── db/encryption.py                 # EncryptedString, PiiKeyring, encrypt/decrypt, search_hmac
│   └── contracts/commerce.py            # StockQueryPort, stock_status ("bor / kam qoldi / yo'q")
├── app/domains/commerce/
│   ├── domain_manifest.py               # shop router'lari, FSM-07/08, ruxsatlar, privacy handler
│   ├── permissions.py                   # commerce.* kodlari va rollar
│   ├── state_machine.py                 # ORDER_RULES, RESERVATION_RULES, majburlab bo'lmaydigan holatlar
│   ├── common.py                        # filial, shop siyosati, xodim nomlari, cursor
│   ├── schemas.py                       # MemberRef
│   ├── providers.py                     # CommerceServices — servislar bir marta yaratiladi
│   ├── query_port.py                    # StockQueryPortImpl
│   ├── inventory/
│   │   ├── models/orm.py                # StockBalance, StockLedger, StockReceipt, StockAdjustment
│   │   ├── schemas.py
│   │   ├── services/stock_service.py    # qoldiq o'zgarishi (yadro), kirim, tuzatish, ro'yxatlar, solishtirish
│   │   └── api/routes.py                # /shop/stock…
│   ├── quick_sales/
│   │   ├── models/orm.py                # QuickSale, QuickSaleLine
│   │   ├── schemas.py
│   │   ├── services/quick_sale_service.py
│   │   └── api/routes.py                # /shop/quick-sales…
│   └── orders/
│       ├── models/orm.py                # Order, OrderLine, OrderNote, OrderCounter, Reservation
│       ├── schemas.py
│       ├── access.py                    # kim ko'radi va kim tegadi ("own", filial, omborchi)
│       ├── services/pricing.py          # narx nusxasi, qator summasi, chegirma holati
│       ├── services/views.py            # kartochka, ro'yxat qatori, "ko'rib chiqish", allowed_actions
│       ├── services/order_service.py    # qoralama, qatorlar, chegirma, biriktirish, izoh, "to'landi", ro'yxatlar
│       ├── services/lifecycle_service.py# FSM-08 o'tishlari va band qilish (qoldiq bilan)
│       ├── services/privacy.py          # anonimlashtirish (26 §2)
│       └── api/routes.py                # /shop/orders…
├── app/db/migrations/commerce/versions/commerce_0002_commerce_tables.py
├── app/db/seed/commerce_seed.py         # demo savdo (dev_seed chaqiradi)
├── app/config/settings.py               # PII kalitlari
├── app/main.py                          # configure_pii, CommerceServices
├── app/dependencies.py                  # get_stock_query()
└── tests/
    ├── integration/test_commerce.py     # 31 test
    └── unit/test_commerce_units.py      # 22 test
```

## 4. Qaysi faylda nima bor

### 4.1 PII — `app/shared/db/encryption.py`

- **`EncryptedString`** — SQLAlchemy turi: bazada `v1.<kalit>.<nonce+shifr>` (TEXT), Python'da oddiy satr. NULL shifrlanmaydi.
- **AES-256-GCM, har safar yangi nonce:** bir xil raqam bazada har xil ko'rinadi; shifrlangan matn o'zgartirilsa o'qishda `PiiDecryptError`.
- **Rotatsiya:** yangi kalit ro'yxat oxiriga qo'shiladi va faol qilinadi; eski kalit eski yozuvlarni o'qish uchun qoladi.
- **`search_hmac()`** — telefon (E.164) uchun kalitli xesh; `orders.customer_phone_hmac` va qidiruv shu orqali.
- **Kalitlar `shared` ga tashqaridan beriladi** (`configure_pii`, `main.py` va seed'da) — `shared` sozlamalarni import qilmaydi (prinsip 1).

### 4.2 Ombor yadrosi — `inventory/services/stock_service.py`

- **`lock_balances()`** — qoldiq qatorlari doim `(branch_id, sku_id)` tartibida `FOR UPDATE`; kerak bo'lsa yo'q qatorni 0 bilan ochadi (`INSERT … ON CONFLICT DO NOTHING`, shu tartibda).
- **`apply(movements)`** — har qoldiq o'zgarishining yagona yo'li: yangi qiymatlar tekshiriladi (hech biri manfiy emas, band + ajratilgan ≤ qoldiq), qator yangilanadi, daftarga yozuv. Buzilsa — `INSUFFICIENT_AVAILABLE_STOCK` (oxirgi himoya; chaqiruvchilar oldinroq aniqroq xato beradi). Bazada ham `CHECK` bor.
- **Daftardagi unikal kalit** `(shop_id, reason, ref_type, ref_id, sku_id)` — bir hujjat bir SKU'ni bir sabab bilan bir marta o'zgartiradi.
- **Tuzatish:** `create_adjustment()` — `adjust_approve` bor xodimda darhol qo'llanadi, aks holda PENDING. So'rovda ham, tasdiqda ham `_check_adjustment()`: qoldiq band + ajratilgandan pastga tushmaydi, tekshiruvdagidan ko'p chiqarilmaydi.
- **`reconcile()`** — daftar yig'indisi va qoldiq farqlari (bo'sh — hammasi joyida).

### 4.3 Tez sotuv — `quick_sales/services/quick_sale_service.py`

- SKU narxi `CatalogQueryPort` dan; narxsiz yoki kurssiz dollar narxi — `PRODUCT_NOT_AVAILABLE` (`reason: NO_PRICE | NO_RATE`).
- Qoldiq qulflanadi, sotuvga mavjud yetmasa — `INSUFFICIENT_AVAILABLE_STOCK`; `details.lines[].reserved > 0` bo'lsa UI "online buyurtma uchun band qilingan" deydi (BL-109).

### 4.4 Buyurtma — `orders/services/`

- **`order_service.py`:**
  - qoralama yaratish: raqam `order_counters` dan shu tranzaksiyada (rollback bo'lsa raqam qaytadi);
  - qatorlar faqat chiqarilgan, faol va narxi bor SKU'dan (`PRODUCT_NOT_AVAILABLE`);
  - har qator o'zgarishi buyurtma versiyasini oshiradi — `If-Match` buyurtma versiyasi (agregat);
  - chegirma: `discount_limit()` — ega cheksiz, menejer va operator `shop_policies` limiti;
  - qidiruv: raqam (`#1042`), telefon (har qanday yozuvda — normallashtirib xesh), ism.
- **`lifecycle_service.py`:** `confirm()` — tartib 12 §5 bo'yicha (fayl boshidagi izohda). `start_processing`, `complete`, `cancel`, `raise_exception`, `resolve_exception`, `review_decision` — hammasi buyurtma → band → qoldiq tartibida qulflaydi va har o'tishni `transition_log` + audit'ga yozadi.
- **`views.py`:** kartochka (`allowed_actions` — shu xodim hozir qaysi tugmalarni bosa oladi), ro'yxat qatori (telefon niqoblangan: `+998 90 *** ** 67`), "ko'rib chiqish" belgisi.
- **`access.py`:** operator — o'ziniki va biriktirilmagan; omborchi — filial doirasida, tasdiqlangandan keyingilar; menejer/ega — filial doirasida hammasi.

### 4.5 API — `/api/v1/shop`

- **Ombor:** `GET /stock` (filial, SKU, `q`, `low_only`), `GET /stock/history?sku_id=`, `POST/GET /stock/receipts`, `GET /stock/receipts/{id}`, `POST/GET /stock/adjustments`, `GET /stock/adjustments/{id}`, `POST …/{id}/approve`, `POST …/{id}/reject`.
- **Tez sotuv:** `POST/GET /quick-sales`, `GET /quick-sales/{id}`.
- **Buyurtma — o'qish:** `GET /orders` (`status`, `branch_id`, `assigned=me|unassigned|<id>`, `q`, `needs_review`, `sort`, cursor), `GET /orders/counts`, `GET /orders/review-queue`, `GET /orders/{id}` (`ETag`).
- **Buyurtma — qoralama:** `POST /orders`, `PATCH /orders/{id}`, `POST /orders/{id}/lines`, `PATCH|DELETE /orders/{id}/lines/{line_id}`, `PUT …/lines/{line_id}/discount`, `POST …/discount/approve|reject`.
- **Buyurtma — o'tishlar:** `submit`, `confirm`, `refresh-prices`, `start-processing`, `mark-ready`, `complete`, `cancel`, `exception`, `resolve-exception`, `review-decision` — hammasi `POST /orders/{id}/<amal>`, `Idempotency-Key` + `If-Match`.
- **Buyurtma — boshqalar:** `take`, `assign`, `paid-mark`, `notes`.
- **201 javoblarida `Location`** (kirim, tuzatish, tez sotuv, buyurtma, qator). OpenAPI operationId'lari — `commerce_<nom>` (`commerce_confirm_order`).

### 4.6 Baza — `commerce_0002_commerce_tables`

- 11 ta jadval (commerce.dbml): qoldiq, daftar, kirim, tuzatish, tez sotuv va qatorlari, buyurtma, qatorlar, izohlar, raqam hisoblagichi, band.
- **RLS (FORCE)** — `order_counters` dan boshqa hammasida.
- **Huquqlar:** daftar, kirim, tez sotuv — faqat INSERT/SELECT; qoldiq, tuzatish, buyurtma, izoh, band, hisoblagich — DELETE yo'q.

### 4.7 Ruxsatlar (10 §6.3)

- **Ega va menejer:** hammasi (ombor, tuzatish tasdig'i, tez sotuv, buyurtmaning hamma amali, biriktirish, bekor qilish, chegirma berish va tasdiqlash). Menejer chegirmasi — `discount_limit_manager_pct` gacha, ega — cheksiz.
- **Operator (SALES):** qoldiqni ko'radi, tez sotuv, buyurtma yaratadi va o'zinikini tasdiqlaydi, tayyorlaydi, topshiradi, "to'landi", izoh; chegirmani faqat so'raydi. Bekor qila olmaydi (qoralamadan tashqari).
- **Omborchi (WAREHOUSE):** qoldiq, kirim, tuzatish so'rovi, tez sotuv; buyurtmani ko'radi (tasdiqlanganlarini), tayyorlaydi, izoh yozadi.
- **Yangi kod:** `commerce.order.assign` (ega, menejer) — 10 §6.3 ga qo'shildi.

### 4.8 Demo ma'lumot — `app/db/seed/commerce_seed.py`

- **TechPC:** ikki filialda boshlang'ich qoldiq (ba'zisi "kam qoldi"); 2 ta tez sotuv; 10 ta buyurtma — qoralama, tasdiq kutilayotgan (24 soatdan oshgani bilan), chegirma so'ralgani, yetkazish, dollar narxli (kurs 12 900 ga o'zgargani uchun tasdiqlashda "narx o'zgardi"), tasdiqlangan (biri 72 soatdan oshgan), tayyorlanayotgan va tayyor, topshirilgan va "to'landi", bekor qilingan, muammoli; omborchining tuzatish so'rovi va eganing "sotilmaydi" tuzatishi.
- **NoutbukUz:** uch filialda qoldiq, tez sotuv, 2 ta buyurtma (biri menejer tasdiqlagan).
- Qayta ishga tushirish xavfsiz: qoldig'i bor shop o'tkazib yuboriladi.

## 5. Testlar

`make check` — yashil: **335 test** (2-moduldan keyin 282 edi, +53), ruff, mypy strict, import-linter.

- **`tests/integration/test_commerce.py` (31):**
  - kirim: qoldiq va daftar, takrori qo'shiladi, takroriy so'rov bitta kirim; boshqa shop SKU'si va filiali, yopiq filial;
  - tez sotuv: qoldiq kamayadi, band mahsulot sotilmaydi (TC-027), narxsiz/kurssiz — rad;
  - buyurtma to'liq yo'li: band → ajratilgan → topshirildi, ikkinchi "topshirildi" — 409, daftarda bitta SALE (TC-030); o'tishlar jurnali;
  - daftar va qoldiq solishtirish — farq yo'q;
  - **poyga:** oxirgi dona uchun ikki tasdiq va tez sotuv bir vaqtda — faqat bittasi o'tadi (TC-002/003); bitta kalit bilan 5 ta parallel tasdiq — bitta band (TC-CON-03); ko'p SKU'li buyurtmalar teskari tartibda — deadlock yo'q (TC-CON-10);
  - narx: kurs o'zgarsa `PRICE_CHANGED` (eski/yangi), "narxlarni yangilash" va qayta tasdiq; katalog narxi o'zgarsa ham; eskirgan kurs — `EXCHANGE_RATE_STALE`;
  - tuzatish: so'rov → tasdiqda qayta tekshiruv (TC-CON-12), rad etish sababi, ikkinchi qaror — 409; ega to'g'ridan; "sotilmaydi" → sotuvga qaytarish → hisobdan chiqarish; dalil fayli yopiq;
  - daftar, kirim, buyurtma — ilova roli UPDATE/DELETE qila olmaydi; qoldiq `CHECK` (band > qoldiq) — rad;
  - RLS: boshqa shop ma'lumoti API'da 404, ro'yxatlarda yo'q, 10 ta jadvalda boshqa shop kontekstida 0 qator;
  - rollar: operator, ikkinchi operator, omborchi, menejer — ruxsat matritsasi, "own", navbatdan olish, biriktirish;
  - qoralamani operator bekor qila oladi, keyin — faqat sabab bilan;
  - tasdiqlangan buyurtma o'zgarmaydi; eskirgan `If-Match` — 409;
  - validatsiya: xaridor ma'lumoti, yetkazish manzili, chiqarilmagan mahsulot, takror SKU, telefon formati, filialsiz tasdiq, qoldiq yetmasligi;
  - qator o'zgarishi jami va versiyani yangilaydi; yaratish idempotent, raqamlar ketma-ket va shop bo'yicha alohida;
  - chegirma: so'rov → tasdiqsiz tasdiqlab bo'lmaydi → menejer limitdan katta — 422 → ega tasdiqlaydi; menejer limit ichida — darhol;
  - PII: bazada shifrlangan, audit va `idempotency_keys` da yo'q; telefon har qanday yozuvda topiladi, raqam bo'yicha qidiruv;
  - anonimlashtirish: yakunlangani tozalanadi, jarayondagisiga tegilmaydi;
  - 72 soat: "kutamiz" va "bekor" (band — EXPIRED, mahsulot qaytadi, bitta RELEASE); 24 soat — navbat, hisoblagich, filtr;
  - muammoli holat: davom ettirish va bekor qilish (bitta RELEASE); "to'landi" bir marta; izoh idempotent;
  - `StockQueryPort`: chiqarilmagan SKU yo'q, filiallar bo'yicha mavjudlik.
- **`tests/unit/test_commerce_units.py` (22):** shifrlash (aylanish, buzilgan matn, rotatsiya, HMAC, kalit tekshiruvi), qator summasi yaxlitlash, chegirma holati va limitlari, mavjudlik holati, tuzatish tekshiruvi, cursor, "own" va omborchi ko'rinishi, `allowed_actions`, "ko'rib chiqish" belgisi, telefon niqobi, ruxsat matritsasi.
- **Boshqa:** seed testi savdo ma'lumotini ham tekshiradi (har holatdagi buyurtma soni, 72 soatdan oshgan band, telefon shifrlangan); production sozlamasida lokal PII kalitlari rad etiladi; FSM paritet testi (`fsm_spec.yaml`) — FSM-07 va FSM-08 qo'shildi.

## 6. Jarayonda topilgan muammolar

- **`dict(result.tuples())` — 500.** SQLAlchemy `Result` da `keys()` bor, `dict()` uni lug'at deb o'qiydi. Qatorlar to'g'ridan iteratsiya qilinadi (`.tuples()` 2.1 da eskirgan ham).
- **Katalog testi "3-modulgacha hech kimda STOCK_EVIDENCE ruxsati yo'q" deb kutardi** — endi ega yuklay oladi (yopiq fayl), operator — yo'q. Test yangilandi.
- **Production sozlamalari testlari** — PII kalit tekshiruvi oxiriga qo'yildi (boshqa tekshiruvlar tartibi o'zgarmasin), testlarga alohida kalitlar berildi.

## 7. Keyingi modulga meros

- **4-modul (sayt)** mavjudlikni `get_stock_query()` orqali o'qiydi: faqat chiqarilgan SKU, faol filiallar jami, olib ketish joylari alohida; `display_policy()` — `EXACT` yoki `STATUS_ONLY` (DEC-128). Saytdan buyurtma so'rovi `commerce` ning `storefront` router'ida bo'ladi: bitta tranzaksiyada qoralama + `SUBMIT` (`actor_type=CUSTOMER` uchun qoida tayyor), `source_request_id` unikal kaliti tayyor, `tracking_token_hash` ustuni tayyor.
- **Frontend** uchun: har buyurtma javobida `allowed_actions`; xatolar `details` bilan (`INSUFFICIENT_AVAILABLE_STOCK.lines[].reserved`, `PRICE_CHANGED.lines[].old/new`, `APPROVAL_REQUIRED.line_ids`); takroriy so'rov joriy holatni qaytaradi.
- **Qoldiqqa tegadigan har yangi amal** `StockService.apply()` orqali, daftar sababi va hujjat (`ref_type`, `ref_id`) bilan. Qulf tartibi: hujjat → band → qoldiq.
- **PII ustuni kerak bo'lsa** — `EncryptedString` + qidirish uchun `search_hmac`; audit diff'ga faqat maydon nomi.

---

## 8. Frontend (2026-10-26)

> **Repo:** `ai-commerce-frontend` (`feat/m1-frontend`). **Commit qilinmagan.** Dizayn — hozirgi qorong'i "Command center" uslubi.

### 8.1 Nima bitdi — qisqacha

Shop paneliga uchta bo'lim qo'shildi: "Buyurtmalar", "Tez sotuv", "Ombor". Hamma ekran haqiqiy API bilan ishlaydi. Qaysi tugma ko'rinishini server hal qiladi: buyurtma sahifasidagi amallar faqat `allowed_actions` bo'yicha chiqadi.

```
Ombor:     "Kirim qilish" → filial + mahsulotlar + miqdor → qoldiq oshadi
           "Tuzatish" → ega/menejer: darhol; omborchi: so'rov → "Tuzatishlar" → menejer tasdiqlaydi/rad etadi
           qatorni bosish → mahsulot tarixi (daftar: sabab, "Qoldiq: 3 → 2", kim)
Tez sotuv: filial (eslab qolinadi) → mahsulot qidirish → miqdor → "Sotish"
           band mahsulot → qator ostida "Online buyurtma uchun band qilingan"
Buyurtma:  "Yangi buyurtma" → xaridor, olish usuli, filial, mahsulotlar → qoralama
           → "Tasdiqlashga yuborish" → "Tasdiqlash (band qilish)"
               narx o'zgargan → "Xaridor rozi — narxlarni yangilash" → qayta tasdiqlash
               qoldiq yetmaydi / chegirma tasdiqlanmagan / kurs eskirgan → aniq sabab paneli
           → "Tayyorlashni boshlash" → "Olib ketishga tayyor" → "Topshirildi"
           muammo → "Muammoni hal qilish" (davom ettirish yoki bekor qilish)
"Ko'rib chiqish kerak": 24 soat tasdiqlanmagan va 72 soat olib ketilmagan → "Kutamiz" yoki "Bekor qilish"
```

### 8.2 Sahifalar

**Ombor** (menyuda — `commerce.stock.view`):
- `/[shop]/stock` — qoldiq:
  - qidiruv, filial filtri (filial bittadan ko'p bo'lsa), "Faqat kam qolganlar";
  - har qatorda: qoldiq, band, ajratilgan, tekshiruvda, mavjud va holat belgisi ("Bor / Kam qoldi / Yo'q");
  - telefonda beshta son bir qatorda yorliq bilan, kompyuterda ustunlar;
  - qatorni bosish — mahsulot tarixi oynasi (daftardan, "Yana ko'rsatish" bilan).
- `/[shop]/stock/receipts` — kirimlar ro'yxati; qatorni bosish — kirim tafsiloti (har mahsulot, "+N", keyingi qoldiq).
- `/[shop]/stock/adjustments` — tuzatishlar (`commerce.stock.adjust_request`):
  - holat tablari (standart — "Tasdiq kutmoqda");
  - sabab, kim so'radi, kim qaror qildi, "Qoldiq: 3 → 2", dalil rasmi havolasi (imzoli, yopiq fayl);
  - menejer va egada "Tasdiqlash" va "Rad etish" (sabab majburiy). Tasdiqdagi qayta tekshiruv xatosi tushunarli matn bilan.
- Kirim va tuzatish oynalari qoldiq sahifasidan ham ochiladi.

**Tez sotuv** — `/[shop]/quick-sale` (`commerce.quick_sale.create`):
- filial shu brauzerda eslab qolinadi (`localStorage`, bloklangan bo'lsa — faqat sahifada);
- mahsulot qidirish (shu filialdagi mavjud son bilan), miqdor, qator va jami summa (katalog narxi);
- server rad etsa — sabab qator ostida: band (online buyurtma), yetmaydi, narx yoki kurs yo'q;
- o'ngda — shu filialning oxirgi 10 ta sotuvi.

**Buyurtmalar** (`commerce.order.view`):
- `/[shop]/orders` — ro'yxat:
  - tablar: "Faol" (standart — topshirilgan va bekor qilinganlarsiz), har holat, "Hammasi" — sanoqlar bilan;
  - filtrlar: "Menga biriktirilgan", "Biriktirilmagan" (tasdiqlay oladiganlarda), "Ko'rib chiqish kerak";
  - qidiruv: raqam (#1042), telefon yoki ism;
  - qatorda: raqam, xaridor, niqoblangan telefon, olish usuli, filial, mas'ul, summa, holat, "tayyor", "to'langan", "ko'rib chiqish" belgilari.
- `/[shop]/orders/new` — yangi buyurtma (`commerce.order.create_draft`): xaridor (ism, telefon, xabarlar tili, izoh), olib ketish yoki yetkazish (manzil majburiy), filial, mahsulotlar va jami.
- `/[shop]/orders/[id]` — buyurtma:
  - amallar faqat `allowed_actions` bo'yicha: yuborish, tasdiqlash, tayyorlash, "tayyor", topshirish, o'ziga olish, biriktirish, "to'landi", muammo, muammoni hal qilish, bekor qilish;
  - tasdiqlash to'siqlari paneli: qoldiq (band bo'lsa "boshqa buyurtmalar uchun band qilingan"), narx (eski → yangi va "narxlarni yangilash" kelishuv izohi bilan), chegirma (qatorlar qizil bilan belgilanadi), eskirgan kurs (kurs sahifasiga havola), sotuvdan chiqqan mahsulot;
  - qatorlar: miqdor (Enter yoki maydondan chiqqanda saqlanadi), olib tashlash, mahsulot qo'shish, chegirma (operatorda — so'rov), chegirmani tasdiqlash yoki rad etish, band holati, dollar narxi va kursi, kafolat;
  - xaridor kartasi: to'liq telefon (`+998 90 123 45 67`) va manzil faqat shu yerda; tahrirlash — faqat o'zgargan maydonlar, `If-Match`;
  - izohlar va qo'ng'iroq natijalari, holat tarixi (vaqt va kim);
  - "Ko'rib chiqish kerak" ogohlantirishi va menejer qarori;
  - boshqa operatorning buyurtmasi — "Bu buyurtma boshqa operatorga biriktirilgan…" (403), yo'q buyurtma — "topilmadi".
- `/[shop]/orders/review` — ko'rib chiqish navbati: 72 soat (qaror tugmalari `commerce.order.cancel` bo'lsa) va 24 soat bo'limlari.

**Bosh sahifa** — "Buyurtmalar" kartasi (tasdiq kutilmoqda, tasdiqlandi, tayyorlanmoqda, "ko'rib chiqish kerak" havolasi) va "Ombor" kartasi (kam qolganlar, tasdiq kutayotgan tuzatishlar; 100 tadan ko'p bo'lsa "100+").

### 8.3 Fayllar xaritasi

```
ai-commerce-frontend/
├── apps/shop-dashboard/src/
│   ├── lib/
│   │   ├── commerce.ts                  # turlar, holatlar, query kalitlari, applyOrder/refreshStock, daftar o'zgarishlari
│   │   └── nav.ts                       # + Buyurtmalar, Tez sotuv, Ombor
│   ├── components/commerce/
│   │   ├── common.tsx                   # holat belgisi, Ombor tablari, filiallar (useBranchOptions), BranchSelect, telefon formati
│   │   ├── sku-picker.tsx               # mahsulot/variant tanlash: qidiruv, filialdagi mavjud son, narx
│   │   ├── stock-history.tsx            # mahsulot tarixi oynasi (daftar)
│   │   ├── receipt-dialog.tsx           # kirim oynasi
│   │   ├── adjustment-dialog.tsx        # tuzatish oynasi (+ dalil rasmi)
│   │   ├── order-form.tsx               # xaridor va olish usuli maydonlari
│   │   ├── order-actions.tsx            # buyruqlar (useOrderCommands), amal tugmalari, dialoglar, tasdiq to'siqlari, 72 soat qarori
│   │   ├── order-lines.tsx              # qatorlar: miqdor, qo'shish, olib tashlash, chegirma
│   │   └── order-details.tsx            # xaridor kartasi, izohlar, holat tarixi
│   └── app/[shop]/
│       ├── stock/page.tsx, stock/receipts/page.tsx, stock/adjustments/page.tsx
│       ├── quick-sale/page.tsx
│       ├── orders/page.tsx, orders/new/page.tsx, orders/[id]/page.tsx, orders/review/page.tsx
│       └── overview/page.tsx            # + buyurtmalar va ombor kartalari
├── packages/i18n/src/messages/{uz,ru,en}.ts  # +343 kalit har tilda
├── packages/api-client/src/schema.d.ts       # qayta generatsiya
└── e2e/commerce.spec.ts                      # 4 ta yangi test
```

### 8.4 Muhim qarorlar

- **Tugmalar faqat `allowed_actions` bo'yicha.** Rol, "o'ziniki", holat va tasdiqlanmagan chegirma — hammasini server hisoblaydi. Frontend o'zi qoida takrorlamaydi.
- **Buyruq kaliti (`Idempotency-Key`) server xatosidan keyin yangilanadi.** Buyurtma buyruqlari `If-Match` versiyasi bilan ketadi, va takror himoyasi versiyani ham hisobga oladi. Narx yangilangach eski kalit bilan qayta tasdiqlash "boshqa so'rov" bo'lardi. Tarmoq uzilsa — o'sha kalit qayta ketadi (21 §4). Ikki marta bosish — `useGuardedMutate`.
- **Operator va omborchi filiallarni qoldiqdan oladi.** Ularda `/shop/branches` ga ruxsat yo'q (§8.6). Olib ketish joyi ekanini server tekshiradi.
- **Mahsulot tanlash oynasi sahifada, popover emas.** Dialog ichida ham bir xil ishlaydi. Bir variantli mahsulot bir bosishda tanlanadi.
- **"Faol" tab standart.** Ro'yxat — ish uchun; topshirilgan va bekor qilinganlar o'z tablarida (katalogdagi "arxivsiz Hammasi" bilan bir xil yondashuv).
- **Holat tarixi buyurtmadagi vaqtlardan.** Alohida jurnal endpointi yo'q; yuborish, tayyorlash va "tayyor" uchun kim qilgani ko'rsatilmaydi.
- **"Kutamiz" xabaridagi 72 soat — frontenddagi doimiy** (`RESERVATION_REVIEW_HOURS`), backend'dagi bilan bir xil. Sozlamaga aylansa, javobdan olinadi.

### 8.5 Tekshiruv

- `pnpm api:generate`, `pnpm check` (typecheck + lint) — toza.
- Ikkala production build (`next build`) — e2e ichida.
- **Playwright — 12/12** (8 ta eski + 4 ta yangi, alohida baza va backend :8001):
  1. kirim (UI) → operator buyurtma ochadi, yuboradi, tasdiqlaydi → oxirgi dona band → tez sotuv "Online buyurtma uchun band qilingan" bilan rad etiladi → omborchi tayyorlaydi ("Topshirildi" tugmasi unda yo'q) → operator "Topshirildi" ni ikki marta bosadi → qoldiq 0, daftarda bitta `SALE`; mahsulot tarixida 4 ta yozuv;
  2. buyurtmadan keyin narx 4 800 000 → 5 000 000 so'm → tasdiqlashda "narx o'zgardi" (eski → yangi) → kelishuv izohi bilan narxlar yangilanadi → tasdiqlanadi;
  3. omborchi −1 tuzatish so'raydi (qoldiq o'zgarmaydi) → menejer tasdiqlaydi → "Qoldiq: 3 → 2";
  4. ikkinchi operator: birinchisining buyurtmasi ro'yxatda yo'q, manzil bilan ochilmaydi, server 403 qaytaradi; 390px da 9 ta savdo sahifasi gorizontal aylantirishsiz.
- **Qo'lda (dev server, `FE ` prefiksli buyurtmalar, keyin bekor qilindi):** ega chegirmasi darhol, biriktirish, operator chegirma so'rovi (tasdiqlash tugmasi yashiriladi), ega tasdig'i, tasdiqlash, "to'landi" (karta), izoh, tayyorlash, "tayyor", muammo → bekor qilish (band bo'shadi); tez sotuv muvaffaqiyati va filialni eslab qolish. 1440px va 390px skrinshotlar — sahifa enidan oshmaydi.

### 8.6 Backend uchun topilganlar

- **Operator va omborchi filiallar ro'yxatini ola olmaydi** (`GET /shop/branches` — `shops.settings.view`). Hozir filiallar qoldiq yozuvlaridan olinadi (100 qatorgacha). Shuning uchun yangi shopda (qoldiq yo'q) omborchi birinchi kirimni qila olmaydi, operator buyurtmaga filial tanlay olmaydi. Taklif: savdo rollari uchun faqat o'qish uchun filiallar ro'yxati (id, nom, olib ketish joyi).
- **OpenAPI sxema nomlari to'qnashgan:** `app__domains__commerce__orders__schemas__ReviewQueue` va `…__NoteIn`. `OrderReviewQueue` / `OrderNoteIn` deb nomlansa, generatsiya qilingan turlar toza bo'ladi.
- **SKU qidiruv endpointi yo'q.** Tanlash oynasi mahsulotlar ro'yxati + mahsulot kartochkasi (ikki so'rov). `GET /shop/skus?q=` (nom, kod, narx, mavjud son) bir so'rovda berardi.
- **Buyurtma o'tishlari jurnali API'da yo'q** — tarix vaqtlardan quriladi (§8.4).
- **Kuzatuv (tekshirilmagan):** dev bazada QA agentining tez sotuvlari orasida arxivlangan va qoralama mahsulotlar bor ("QA Commerce Archived …", "QA Commerce Draft …"). Arxivlangan mahsulotni tez sotuvda sotish ataylabmi — tekshirish kerak.

**Holat (2026-10-26):** to'rttasi ham hal qilindi (§9.4); arxiv va qoralama mahsulotni tez sotish endi rad etiladi (§9.2, F4).

### 8.7 Ochiq qolganlar

- Ko'rib chiqish navbatidagi "Kutamiz" va "Bekor qilish" e2e'da yo'q: 72 soat oldingi bandni test ichida yaratib bo'lmaydi (seed'da bor, qo'lda tekshiriladi).
- Buyurtma ro'yxatida filial filtri yo'q (API'da bor) — ko'p filialli shoplar uchun keyin.

---

## 9. QA tekshiruvi va tuzatishlar (2026-10-26)

Mustaqil QA agenti backendni tashqaridan sinadi: 0 ta jiddiy, 2 ta o'rtacha, 8 ta kichik topilma. Asosiy qism mustahkam chiqdi: oxirgi dona poygasi, daftar = qoldiq, FSM-07/08 (84 tekshiruv), narx qayta tekshiruvi, rollar va shoplar orasidagi himoya, shifrlash. Founder qarori: DEC-136 (kirim tasdiqsiz; faqat to'xtatilgan va yopilgan shop sota olmaydi).

```
QA hisoboti ──▶ founder: 2 ta biznes savol (DEC-136) ──▶ backend tuzatishlari + regressiya testlari
   ──▶ frontend moslashtirildi ──▶ backend 362 test, e2e 13/13
```

### 9.1 O'rtacha topilmalar

- **F1 — to'xtatilgan shop sotardi.** `app/platform/shops/services/sales_gate.py` (yangi): `ensure_shop_can_sell()` — `SUSPENDED` / `CLOSED` da buyurtma yaratish va tez sotuv → `409 SHOP_NOT_ACTIVE`, `details.shop_status`. Mavjud buyurtmalar (tasdiq, tayyorlash, topshirish, bekor qilish), kirim va tuzatish ishlayveradi. 4-modul (saytdan so'rov) ham shuni chaqiradi. Frontend: `shop_status = SUSPENDED` bo'lsa sessiya tugamaydi, "Shop vaqtincha to'xtatilgan…" xabari; `CLOSED` — avvalgidek chiqib ketish.
- **F2 — telefon kirish logiga tushardi** (`?q=+998…`). Uvicorn kirish logi o'chirildi (`app/config/logging.py`); o'rniga `RequestContextMiddleware` bitta `http.request` qatori yozadi: metod, yo'l, holat, davomiylik va query parametrlarining **faqat nomlari** (`query_keys`). 09 §4.2 va 22 ga: proksi yo'lni query string'siz yozadi. Ishga tushirish buyrug'iga `--no-access-log` (23, frontend README).

### 9.2 Kichik topilmalar

- **F3** — qoldiq ustuni INTEGER chegarasidan oshsa 500 edi → 422 `max_value` (kirimda `lines[i].qty`, tuzatishda `delta`; so'rov paytida ham tekshiriladi).
- **F4** — tez sotuv faqat `PUBLISHED` / `HIDDEN` mahsulot va faol SKU (qoralama va arxiv → 409 `PRODUCT_NOT_AVAILABLE`, `product_status`). Arxivdagi SKU qoldig'i endi hisobdan chiqariladi: faqat kamaytiruvchi tuzatish (`ADJUSTMENT` < 0, `QUARANTINE_IN`, `WRITE_OFF`); kirim va oshiruvchi tuzatish → 409. Tasdiq paytida ham qayta tekshiriladi.
- **F5** — biriktirishda xodimning filial doirasi buyurtma filialini qamrashi shart → 422 `membership_id / invalid_choice`. Frontend: xato dialogda, maydon ostida ("Bu xodim buyurtma filialida ishlamaydi…"), dialog yopilmaydi.
- **F6** — telefon qat'iy (`app/shared/phone.py`): harf — rad; `+998`/`998` bilan aynan 12 raqam; 9 raqam faqat mamlakat kodisiz. "+998 99 1234" endi boshqa raqamga aylanmaydi. Login, xodim taklifi va shop telefoni ham shu qoida. Frontend: xuddi shu tekshiruv forma ichida.
- **F7** — tuzatish javobidagi imzoli havola takroriy so'rov jadvaliga yozilardi va 5 daqiqadan keyin eskirardi → endi faqat ID saqlanadi, takrorda yangi havola bilan joriy holat.
- **F8** — `allowed_actions` da `APPROVE_DISCOUNT` faqat xodim limiti yetadigan chegirma bo'lsa (`discount_limit` → `commerce/common.py`).
- **F9** — izoh qo'shishda `Location` (buyurtma kartochkasi).
- **F10** — tasdiq va narx yangilashdagi `PRODUCT_NOT_AVAILABLE` da `product_status`, `sku_status` (yaratishdagi bilan bir xil shakl). Frontend: har qator uchun sabab ("saytdan yashirilgan", "arxivda", "narxi yo'q"…).

### 9.3 Kuzatuvlar bo'yicha

- Muammoli (`EXCEPTION`) buyurtma ham 72 soatlik ko'rib chiqishga kiradi (ajratilgan mahsulotni ushlab turadi). FSM-08 ga `EXPIRE: EXCEPTION → CANCELLED` qo'shildi (`state_machine.py`, `fsm_spec.yaml`). `business/05` dagi FSM-08 matniga ham shu qatorni qo'shish kerak — founder hujjati, tegilmadi.
- Omborchi kartochkada xaridor ismini va yashirilgan telefonni ko'radi; manzil — faqat yetkazishda (10 §6.8 ga yozildi).
- Xaridor ismi, izohi va buyurtma izohidan ko'rinmas belgilar (yo'nalish almashtiruvchi, nol kenglikdagi) olib tashlanadi — `CleanText` (`app/shared/text.py`); fayl nomi tozalovchisi ham shu ro'yxatdan foydalanadi.

### 9.4 Frontend so'ragan endpoint'lar

- `GET /shop/branches/options` — filial tanlash har xodimga ochiq (id, nom, holat, olib ketish joyi). Omborchi yangi shopda (qoldiq yo'q) ham birinchi kirimni kirita oladi; qoldiqdan filial olish aylanma yo'li olib tashlandi.
- `GET /shop/skus?q=&branch_id=` — SKU tanlash bitta so'rovda: nom, kod, holat, joriy narx, `orderable` / `quick_sellable`, filialdagi sotuvga mavjud son. `SkuPicker` qayta yozildi: yaroqsiz variant ko'rinadi, lekin sababi bilan o'chirilgan.
- `GET /shop/orders/{id}/history` — `transition_log` dan: kim, qachon, qaysi o'tish, sabab. Kartochkadagi "Holat tarixi" endi har qadamni kim qilganini ko'rsatadi.
- OpenAPI'dagi to'qnashgan nomlar tozalandi: `SpecNoteIn`, `SpecReviewQueue`, `SpecReviewQueueItem`, `OrderNoteIn`, `OrderReviewQueue`, `VerificationQueueItem` — `app__…` nomlar qolmadi.

### 9.5 Fayllar

```
app/platform/shops/services/sales_gate.py       yangi — yangi savdo va shop holati
app/shared/phone.py                             qat'iy telefon
app/shared/text.py                              CleanText, ko'rinmas belgilar
app/shared/tracing/middleware.py                http.request kirish logi (query nomlari)
app/config/logging.py                           uvicorn.access o'chirilgan
app/domains/commerce/inventory/…                chegara, arxiv qoidasi, SKU tanlash, idempotency
app/domains/commerce/orders/…                   biriktirish doirasi, tarix, sabablar, omborchi ko'rinishi, EXCEPTION
app/domains/catalog/query_port.py               pick_sku_ids, nom va variant alohida
tests/integration/test_commerce_qa_fixes.py     15 ta regressiya testi
tests/unit/test_access_log.py                   kirish logida telefon yo'q
```

### 9.6 Testlar

- Backend `make check`: **362 passed** (oldin 335), ruff, mypy strict, import-linter toza.
- Frontend `pnpm check` toza; e2e **13/13** (yangi: omborchi yangi shopda birinchi kirim; qoralama mahsulot tez sotuvda o'chirilgan va server 409; asosiy oqimda holat tarixi — "Bobur Omborchi").
- Migratsiya kerak bo'lmadi.

### 9.7 QA 2-tur (2026-10-26): tekshiruv natijasi va tuzatishlar

QA 2-tur 1-turning 10 ta topilmasidan 7 tasini "tuzatildi", 3 tasini (F5, F6, F7) "qisman" deb topdi. Yangi: backend'da 5 ta (N1–N5), interfeysda 6 ta (U1–U6) kichik topilma va ikki kuzatuv. Hammasi tuzatildi.

**Backend**
- **N1 / F6 — telefonda faqat ASCII raqamlar.** Python'da `\d` arab va to'liq kenglikdagi raqamlarni ham ushlardi: "+998٩٠…" saqlanib, qidiruvda topilmay qolardi, taklifda esa baza CHECK'i 500 berardi. Endi `[0-9]` (`app/shared/phone.py`), nusxalashdagi "qattiq" bo'shliq (U+00A0, U+202F) ruxsat. Taklif, buyurtma, filial — 422 `invalid_format`; login — 401 (avvalgidek); qidiruvda — shunchaki topilmaydi.
- **SQL parametrlari logga chiqmaydi.** Hamma engine `hide_parameters=True` (runtime, migratsiya, test): `IntegrityError` matnida telefon va ism yo'q, faqat "parameters hidden". Test: CHECK buzilganda xato matnida qiymat yo'q.
- **N2 — to'xtatilgan shopda mavjud buyurtmani "o'stirib" bo'lmaydi.** Aniq qoida (SUSPENDED / CLOSED):
  ```
  RAD (409 SHOP_NOT_ACTIVE): yangi buyurtma, tez sotuv, qator qo'shish, miqdorni oshirish,
                             qoralamani yuborish, narxni yangilash (jami oshsa)
  RUXSAT:                    yuborilgan buyurtmani tasdiqlash, tayyorlash, topshirish, bekor qilish,
                             muammo / hal qilish, izoh, "to'landi", miqdorni kamaytirish, qatorni olib tashlash,
                             chegirma, mijoz ma'lumotini tuzatish
  ```
- **N3 — kirish logida yo'l emas, route shabloni.** `path=/api/v1/auth/invites/{token}/accept` — bir martalik havola tokeni va ID'lar logga tushmaydi; route topilmasa (404) — bo'laklar niqoblanadi (`/api/v1/x/{seg}`). `unhandled_exception` logida ham shunday.
- **N4 / F7 — fayl yuklashning takroriy so'rovi.** Takroriy so'rovlar jadvaliga faqat fayl ID'si yoziladi; takroriy so'rovda yangi imzoli havola beriladi. Boshqa `run_idempotent` chaqiruvlari tekshirildi: imzoli havola yoki maxfiy narsa qaytaradigan boshqasi yo'q (taklif havolalari avvaldan `stored=` bilan).
- **N5 — ko'rinmas belgilar kengaytirildi.** Unicode "format" (Cf) toifasining hammasi + U+00AD, U+034F, U+180E, U+2028/U+2029, U+2060–U+2064, U+FEFF, hangul to'ldiruvchilari. Emoji buzilmaydi: emoji orasidagi ZWJ va bayroq teglari qoladi. Fayl nomi tozalovchisi ham shu funksiyadan.
- **F5 — filial almashsa, mas'ul xodim tekshiriladi.** Biriktirilgan buyurtmaning filiali (PATCH) xodim doirasidan tashqariga o'tsa — 422 `branch_id / out_of_scope` (jim o'zgartirish yo'q: avval boshqasiga biriktiriladi).
- **U3 — "olib ketishga tayyor" ni kim bosgani.** `orders.ready_by` (migratsiya `commerce_0003`), FSM-08 ga `MARK_READY` (Tayyorlanmoqda → Tayyorlanmoqda) qo'shildi — `transition_log` ga yoziladi, tarixda kim bosgani ko'rinadi. Ikkinchi bosish tarixga yozilmaydi.
- **U4 — `FORBIDDEN` sababi.** Buyurtmada `details.reason`: `other_operator`, `not_confirmed` (omborchi), `other_branch`, `not_assigned`.
- **Platforma: ochiq buyurtmali shop yopilmaydi** (FSM-01, TC-023 — "mavjud buyurtmalar oxiriga yetkaziladi"). Tasdiq kutayotgan, tasdiqlangan, tayyorlanayotgan yoki muammoli buyurtma bo'lsa — 409 `SHOP_HAS_OPEN_ORDERS`, `details.open_orders` (holat bo'yicha soni). Qoralama hisoblanmaydi. Platforma `commerce` ni import qilmaydi: `OrderQueryPort` (`app/shared/contracts/commerce.py`) orqali, ulanish — `app/dependencies.py`.

**Frontend**
- **U1** — bosh sahifadagi buyurtma va ombor kartalari telefonda qator ko'rinishida (nom chapda, son o'ngda): "Tayyorlanmoqda" endi kesilmaydi.
- **U2** — kirimda noto'g'ri miqdor ostida matn: "1 dan 100 000 gacha butun son".
- **U3** — holat tarixida "Olib ketishga tayyor" kim bosgani bilan (eski buyurtmalarda `ready_by` dan).
- **U4** — omborchi tasdiqlanmagan buyurtmani ochsa: "Bu buyurtma hali tasdiqlanmagan…"; qolgan sabablar ham alohida matn.
- **U5** — dalil rasmi xatosi (tur, hajm, server) dalil maydoni ostida, toast emas.
- **U6** — yangi buyurtmada "mahsulot qo'shing" xatosi mijoz maydonlari xatolari bilan birga, birinchi bosishda.
- **To'xtatilgan shop** — bosh sahifa, buyurtmalar, yangi buyurtma va tez sotuvda ogohlantirish; "Yangi buyurtma" va "Sotish" o'chiq.
- **Platforma paneli** — yopish dialogida ochiq buyurtmalar ro'yxati (holat: soni).
- Yangi matnlar uch tilda: `validation.out_of_scope`, `errors.codes.SHOP_HAS_OPEN_ORDERS`, `orders.forbiddenReason.*`, `commerce.qtyRange`, `admin.openOrdersLine`.

**Fayllar**
```
app/shared/phone.py                                  faqat ASCII raqamlar
app/shared/text.py                                   strip_invisible — Cf toifasi, emoji saqlanadi
app/shared/tracing/middleware.py                     route_path, redact_path
app/shared/db/session.py, migrations/env_common.py   hide_parameters
app/shared/contracts/commerce.py                     OrderQueryPort, OPEN_ORDER_STATUSES
app/shared/errors/{base,catalog}.py, i18n/locales    SHOP_HAS_OPEN_ORDERS
app/platform/shops/services/shop_service.py          yopishdan oldin ochiq buyurtmalar
app/platform/storage/api/routes.py                   yuklash: stored= / on_replay=
app/domains/commerce/query_port.py                   OrderQueryPortImpl
app/domains/commerce/orders/…                        o'stirish taqiqi, filial–xodim, MARK_READY, ready_by, sabablar
app/db/migrations/commerce/versions/commerce_0003_order_ready_by.py
tests/integration/test_commerce_qa_round2.py         9 ta regressiya testi
tests/unit/test_access_log.py                        route shabloni, niqoblash
frontend: components/sales-gate.tsx (yangi), overview, orders, orders/new, orders/[id], quick-sale,
          commerce/{receipt-dialog, adjustment-dialog, order-details}, platform transition-dialog,
          app-kit formatCount, i18n (uz/ru/en), e2e/commerce.spec.ts
```

**Testlar**
- Backend `make check`: **373 passed** (oldin 362), ruff, mypy strict, import-linter toza. Migratsiya `commerce_0003` dev bazaga qo'llandi.
- Frontend `pnpm check` toza; e2e **13/13** (qo'shilgan tekshiruvlar: tarixda "Olib ketishga tayyor — Bobur Omborchi", kirimda miqdor xatosi matni, 390px da bosh sahifa kartasida matn kesilmasligi).
