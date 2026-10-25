# `catalog` schemasi — ma'lumotlar lug'ati

> **Holat:** tasdiqlangan — founder qarorlari DEC-133 (2026-10-25). Diagramma: [`catalog.dbml`](catalog.dbml) → dbdiagram.io.
> **Kim o'qiydi:** founder va dasturchilar. Har jadval quyidagi tartibda: nima uchun kerak → har maydon nima va nega shunday → bog'lanishlar → misol.
> **Umumiy qoidalar** (`id`, `shop_id`, `(shop_id, id)` bilan bog'lash, `version`, holat matn sifatida, o'chirish yo'qligi) — [platform.md](platform.md) §0. Bu yerda takrorlanmaydi.

Misollarda **"TechPC"** shopi ishlatiladi. Ega — **Ali**, menejer — **Vali**. Mahsulot — **"MSI GeForce RTX 4060 Ventus 2X"**.

---

## 0. Bu schemada yangi narsalar

- **Pul butun son bilan saqlanadi.** `amount_minor` — tiyin yoki sentda: 4 500 000 so'm = `450000000`, 300 dollar = `30000`. Kasr son (float) pulda xato beradi (0.1 + 0.2 ≠ 0.3), butun son esa hech qachon xato qilmaydi (ADR-025).
- **O'zgarmaydigan jadvallar.** Narx va kurs tarixi faqat qo'shiladi. Ilova roliga `UPDATE` va `DELETE` huquqi berilmaydi. Shunda "kecha bu mahsulot qancha turgan edi?" degan savolga har doim aniq javob bor.
- **Ikki xil egalik.** Mahsulot, narx va kurs — shopniki (`shop_id` bor). Toifalar va texnik ma'lumotlar kutubxonasi — platformaniki: `shop_id` yo'q, hamma shop bir xil ma'lumotni o'qiydi, faqat platforma jamoasi yozadi (DEC-011, DEC-120).

---

## 1. `categories` — toifalar (platforma ma'lumotnomasi)

**Nima uchun kerak:** "Protsessor", "Videokarta", "Noutbuk" kabi toifalar. Sayt menyusi, filtrlar va AI qidiruvi shularga tayanadi. PC qismi toifasi texnik kutubxona bilan bog'lanadi, shu sababli moslik tekshiruvi qaysi mahsulot qaysi tur ekanini biladi.

- **`code`** — `GPU`, `CPU`, `LAPTOP`. Kodda va API'da shu ishlatiladi, nom esa tarjima qilinadi. Kod o'zgarmaydi, nomni o'zgartirsa bo'ladi.
- **`parent_code`** — ichma-ich toifa uchun (masalan, `PC_PARTS` → `GPU`). Menyu daraxtini quradi.
- **`name_uz`, `name_ru`, `name_en`** — uch tildagi nom. Uchta alohida ustun va uchalasi majburiy, shuning uchun sayt hech qachon "nomsiz toifa" ko'rsatmaydi.
- **`spec_category`** — PC qismi bo'lsa, kutubxonadagi turi (`CPU`, `GPU`, ...). Monitor, sichqoncha kabi toifalarda `NULL` bo'ladi, ular uchun moslik tekshirilmaydi (engineering/17 §4).
- **`position`**, **`is_active`** — menyudagi tartib va toifani yashirish. O'chirilgan toifaga yangi mahsulot qo'shilmaydi, eskilari qoladi.

**Kim yozadi:** platforma jamoasi. Boshlang'ich ro'yxat migratsiya bilan qo'shiladi. Shop faqat tanlaydi (DEC-133).

---

## 2. `products` — mahsulot kartochkasi

**Nima uchun kerak:** xaridor saytda ko'radigan kartochka: nomi, toifasi, brendi, tavsifi, rasmlari. Narx va qoldiq bu yerda emas, variantda (`skus`) turadi, chunki bitta kartochkada bir nechta variant bo'lishi mumkin.

- **`category_code`** — toifa. Majburiy: toifasiz mahsulot menyuda ham, AI qidiruvida ham topilmaydi.
- **`brand`** — "MSI". Texnik kutubxonaga avtomatik bog'lashda ishlatiladi (brend + model).
- **`title`** — "MSI GeForce RTX 4060 Ventus 2X".
- **`description`** — tavsif, shop tilida. Tarjima Stage 1 da yo'q: AI javobni xaridor tiliga o'zi o'giradi.
- **`status`** — FSM-02 (DEC-133):

  ```
  Qoralama (DRAFT) ──(ega/menejer: chiqardi)──▶ Chiqarilgan (PUBLISHED)   [narx va majburiy maydonlar tekshiriladi]
  Chiqarilgan ──(yashirdi)──▶ Yashirilgan (HIDDEN) ──(qayta chiqardi)──▶ Chiqarilgan
  Qoralama / Chiqarilgan / Yashirilgan ──(ega: arxivladi)──▶ Arxivda (ARCHIVED)
  ```

  Har o'tish `platform.transition_log` ga yoziladi.
- **`published_at`**, **`archived_at`** — qachon chiqarilgan va qachon arxivlangan. Hisobot va saralash uchun.
- **`created_by`** — kim qo'shgan (a'zolik ID'si). Bu boshqa schema, shuning uchun FK yo'q, faqat UUID.
- **`version`** — Ali va Vali bir vaqtda tahrirlasa, ikkinchisi `VERSION_CONFLICT` oladi.

**Saytga chiqish sharti (BL-012):** toifa va nom bor, kamida bitta `ACTIVE` SKU bor va uning narxi bor. Shart bajarilmasa, mahsulot qoralamada qoladi va javobda nimasi yetishmayotgani aytiladi.

**Indekslar:** `(shop_id, status)` — "chiqarilganlar" va "qoralamalar" ro'yxati, `(shop_id, category_code)` — toifa bo'yicha filtr.

---

## 3. `skus` — sotiladigan variant

**Nima uchun kerak:** xaridor aynan nimani sotib olishi. "RTX 4060 yangi" va "RTX 4060 ishlatilgan" — narxi, qoldig'i va kafolati har xil, shuning uchun ular ikkita SKU. Narx (§5), qoldiq (3-modul) va buyurtma qatori SKU'ga bog'lanadi.

- **`sku_code`** — shop ichidagi kod, masalan `MSI-4060-V2X-N`. **`(shop_id, sku_code)` unikal** (BL-011): ikki xil SKU'ga bir xil kod berib bo'lmaydi. Boshqa shopda xuddi shu kod bo'lishi mumkin.
- **`variant_name`** — "8 GB, qora". Mahsulotning variantlari bitta bo'lsa — bo'sh.
- **`condition`** — `NEW` / `USED` / `REFURBISHED`. BL-011 bo'yicha variantning bir qismi.
- **`mpn`** — ishlab chiqaruvchi kodi, kiritilganicha (`V516-012R`).
- **`mpn_normalized`** — xuddi shu kod katta harfda, bo'shliq va chiziqchasiz (`V516012R`). Odamlar kodni har xil yozadi. Solishtirish shu ustun bo'yicha bo'ladi, ko'rsatish esa asl yozuv bilan.
- **`model_name`** — model nomi, kiritilganicha. MPN yo'q bo'lsa, brend + model bo'yicha bog'lanadi.
- **`attributes`** — variant xususiyatlari: `{"rang": "qora", "xotira_gb": 8}`. Har toifada xususiyatlar har xil, shuning uchun alohida ustunlar o'rniga JSONB ishlatiladi. PC qismlarining **texnik** ma'lumotlari bu yerda emas, kutubxonada (§8): shop ularni kiritmaydi.
- **`warranty_months`** — kafolat, oy. Sotilganda buyurtma qatoriga nusxa olinadi. Shunda keyin shop kafolatni o'zgartirsa ham, eski sotuvga ta'sir qilmaydi (FSM-11).
- **`status`** — `ACTIVE` / `ARCHIVED`. Variant sotuvdan olinsa, arxivlanadi, lekin o'chirilmaydi: eski buyurtmalar unga bog'langan.

**Bog'lanish:** `(shop_id, product_id) → products`. Boshqa shop mahsulotiga variant qo'shib bo'lmaydi.

---

## 4. `product_media` — mahsulot rasmlari

**Nima uchun kerak:** kartochkadagi rasmlar va ularning tartibi.

- **`file_id`** — `platform.stored_files` dagi fayl (§12). Bu boshqa schema, shuning uchun FK yo'q. Service rasm **shu shopniki** ekanini va turi `PRODUCT_IMAGE` ekanini tekshiradi. Aks holda birovning fayl ID'sini taxmin qilib, o'z mahsulotiga ulab olish mumkin bo'lardi (TC-ISO-05).
- **`position`** — tartib, `0` asosiy rasm hisoblanadi.

**Cheklov:** bitta mahsulotga ko'pi bilan 10 ta rasm (kodda). **Bog'lanish:** mahsulot bilan birga yashaydi (`cascade`).

---

## 5. `price_versions` — narx tarixi

**Nima uchun kerak:** BL-015 bo'yicha narxda valyuta, versiya va manba bo'lishi shart. BL-016 bo'yicha yuborilgan taklifdagi narx keyin o'zgarmaydi. Buning uchun har narx alohida va o'zgarmas yozuv bo'lishi kerak.

- **`amount_minor`** — narx butun sonda. **`CHECK > 0`**: nol va manfiy narx yo'q (BL-015).
- **`currency`** — `UZS` yoki `USD` (DEC-121). Dollardagi narx xaridorga so'mda, shop kursi bo'yicha ko'rsatiladi (§7).
- **`source`** — `MANUAL` (xodim kiritdi) yoki `IMPORT` (fayldan). "Bu narx qayerdan keldi?" degan savolga javob.
- **`reason`** — ixtiyoriy izoh: "yangi partiya qimmatroq keldi".
- **`created_by`**, **`created_at`** — kim va qachon.

**O'zgarmaydi:** narx o'zgarsa, yangi qator qo'shiladi. Ilova roli `UPDATE` / `DELETE` qila olmaydi.
**RLS:** narx tijoriy sir, shuning uchun bazaning o'zi ham shop bo'yicha filtrlaydi (engineering/10 §4).
**Misol:** Vali 1-oktabrda 4 500 000 so'm qo'ydi, 15-oktabrda 4 800 000 so'mga o'zgartirdi. Jadvalda ikkala narx qoladi. 10-oktabrda yuborilgan taklif 4 500 000 so'mlik qatorga bog'langan bo'lib qoladi.

---

## 6. `current_prices` — hozirgi narx

**Nima uchun kerak:** sayt, AI va buyurtma "hozir qancha?" deb tez-tez so'raydi. Bu jadval har SKU uchun bitta qator saqlaydi va u `price_versions` dagi joriy yozuvni ko'rsatadi.

- **`(shop_id, sku_id)`** — primary key: bir SKU'ning bitta joriy narxi bor.
- **`price_version_id`** — joriy narx yozuvi. FK **`(shop_id, sku_id, price_version_id)`** uchala ustun bilan bog'langan: boshqa SKU'ning narxini tasodifan ko'rsatib bo'lmaydi, buni baza o'zi tekshiradi.
- **`version`** — Ali va Vali bir vaqtda narx o'zgartirsa, ikkinchisi `VERSION_CONFLICT` oladi va eski sahifa ustidan yozib yubormaydi.

**Nega SKU ichida ustun emas:** narx o'zgarishi va SKU tahriri (nomi, kafolat) bir-biriga xalaqit bermasligi kerak. Agar narx `skus` ichida bo'lsa, menejer narxni o'zgartirganda boshqa xodimning variant nomini tahrirlashi `VERSION_CONFLICT` bilan yiqilardi.

---

## 7. `exchange_rates` — shop kursi

**Nima uchun kerak:** DEC-121 bo'yicha shop narxni dollarda yuritishi mumkin, lekin xaridorga har doim so'm ko'rsatiladi. Kurs shopning o'ziniki: bozor kursi Markaziy bank kursidan farq qiladi.

- **`base` / `quote`** — `USD` / `UZS`. Stage 1 da faqat shu juftlik. Ustunlar keyinroq boshqa valyuta qo'shilishi uchun turibdi.
- **`rate`** — 1 dollar necha so'm: `12800.000000`. `numeric` aniq son (float emas), `CHECK > 0`.
- **`source`** — `MANUAL` yoki `CBU`. Markaziy bank kursini avtomatik olish fon ishi, u 5-modulda keladi.
- **`effective_at`** — qachondan amal qiladi. Joriy kurs — eng oxirgisi.
- **`created_by`** — kim kiritgan.

**Hisoblash (UAT-M05):** 300 dollar = `30000` sent × 12 800 = `384000000` tiyin = **3 840 000 so'm**. **Yaxlitlanmaydi** (DEC-133): 300 × 12 835 = 3 850 500 so'm shundayligicha ko'rsatiladi. Kursda kasr bo'lsa, faqat eng yaqin so'mgacha.
**Eskirish:** kurs 3 kundan eski bo'lsa, API buni `is_stale` bilan bildiradi. "Yangi taklif berilmaydi" qoidasi (BL-018) takliflar bilan birga 3-modulda keladi.
**O'zgarmaydi va RLS** — narx kabi.

---

## 8. `reference_hardware_specs` — texnik ma'lumotlar kutubxonasi (platforma)

**Nima uchun kerak:** PC yig'ishda "bu protsessor shu plataga tushadimi?" degan savolga javob berish uchun socket, RAM turi, GPU uzunligi, blok quvvati kerak. Shoplarning Excel fayllarida bular odatda yo'q. Shuning uchun platforma bir marta to'g'ri kiritadi, shoplar esa o'z SKU'sini shunga bog'laydi (DEC-011).

- **`category`** — `CPU`, `MOTHERBOARD`, `GPU`, `RAM`, `PSU`, `CASE`, `CPU_COOLER`, `STORAGE`.
- **`brand`**, **`model_name`** — "MSI", "GeForce RTX 4060 Ti".
- **`model_normalized`** — solishtirish uchun (`GEFORCERTX4060TI`). `Ti`, `SUPER`, `OC` saqlanadi: "RTX 4060" va "RTX 4060 Ti" har xil chiqadi.
- **`variant_key`** — bir model ichidagi farq: `8GB` / `16GB`. Farq yo'q bo'lsa — bo'sh.
- **`mpn` / `mpn_normalized`** — ishlab chiqaruvchi kodi. Bo'lsa, kutubxonada yagona.
- **`attributes`** — texnik ma'lumot, toifaga qarab (engineering/17 §4.1). Masalan, GPU uchun: `{"length_mm": 199, "board_power_w": 115, "power_connectors": [{"type": "PCIE_8PIN", "count": 1}]}`. Har toifaning sxemasi kodda tekshiriladi. **Yo'q atribut "noma'lum" degani**, nol emas: noma'lum bo'lsa, natija "tekshirish kerak" bo'ladi, "mos" emas.
- **`source_url`** — ishlab chiqaruvchi sahifasi. **Majburiy** (DEC-120): har qiymatning manbasi bo'lishi kerak.
- **`status`** — `DRAFT` (hali tasdiqlanmagan, bog'lanmaydi) → `APPROVED` → `RETIRED`.
- **`version`** — tasdiqlangan ma'lumot versiyasi. Takliflar keyin "qaysi versiya bo'yicha tekshirilgan" deb shunga murojaat qiladi.
- **`created_by`**, **`approved_by`**, **`approved_at`** — kim kiritgan va kim tasdiqlagan.

**Unikal:** `(category, brand, model_normalized, variant_key)` — bitta model ikki marta kiritilmaydi. `mpn_normalized` NULL bo'lmasa, u ham unikal.

---

## 9. `reference_hardware_spec_versions` — kutubxona o'zgarishlari va tasdiq

**Nima uchun kerak:** engineering/17 §10 dagi "ikki ko'z" qoidasi. Bir odamning xatosi (masalan, GPU uzunligini 199 o'rniga 299 deb yozish) yuzlab yig'mani noto'g'ri qiladi. Shuning uchun har yangi spec va har o'zgarish avval taklif bo'lib turadi, ikkinchi odam tasdiqlaydi.

- **`(spec_id, version)`** — primary key: har o'zgarish alohida versiya.
- **`brand` … `source_url`** — taklif qilingan ma'lumotning to'liq nusxasi.
- **`status`** — `PENDING` → `APPROVED` / `REJECTED`.
- **`proposed_by`** / **`reviewed_by`** — taklif qilgan va tekshirgan. **Bir odam bo'lishi mumkin emas** (`SELF_APPROVAL_NOT_ALLOWED`).
- **`review_note`** — rad etilsa, sabab majburiy.

**Qanday ishlaydi:**

```
Yangi model: asosiy yozuv DRAFT + 1-versiya PENDING ──(boshqa odam tasdiqladi)──▶ asosiy yozuv APPROVED
O'zgarish:   asosiy yozuv APPROVED (eski ma'lumot ishlayveradi) + yangi versiya PENDING
             ──(tasdiqlandi)──▶ ma'lumot asosiy yozuvga ko'chadi, version oshadi
             ──(rad etildi)──▶ asosiy yozuv o'zgarmaydi
```

Bonus: kutubxonaning to'liq tarixi ham shu jadvalda.

---

## 10. `sku_spec_links` — shop SKU'si ↔ kutubxonadagi model

**Nima uchun kerak:** TechPC'ning "MSI-4060-V2X-N" SKU'si kutubxonadagi qaysi model ekanini bilish uchun. Shunda shop texnik ma'lumot kiritmaydi.

- **`(shop_id, sku_id)`** — primary key: bitta SKU bitta modelga bog'lanadi.
- **`spec_id`** — kutubxonadagi model. Faqat `APPROVED` spec'ga bog'lash mumkin (service tekshiradi).
- **`method`** — qanday bog'langan (engineering/17 §5):
  - `AUTO_MPN` — MPN aniq mos keldi;
  - `AUTO_MODEL` — brend + model aniq mos keldi;
  - `MANUAL` — bir nechta nomzod chiqdi va xodim o'zi tanladi.
- **`linked_by`** — `MANUAL` bo'lsa, kim tanlagan.

**Qoidalar:**
- Avtomatik bog'lash faqat **aniq bitta** nomzod bo'lsa ishlaydi. "RTX 5060" ↔ "RTX 5060 Ti", "8GB" ↔ "16GB", "DDR4" ↔ "DDR5" hech qachon avtomatik birlashmaydi.
- Bog'lanmagan SKU sotiladi, lekin PC yig'mada "tekshirish kerak" (`REVIEW_REQUIRED`) bo'ladi.

---

## 11. `spec_requests` — "yangi model qo'shing" so'rovi

**Nima uchun kerak:** shop sotadigan model kutubxonada bo'lmasa, shop so'rov yuboradi va platforma jamoasi 2 ish kunida qo'shadi (DEC-120).

- **`sku_id`** — qaysi SKU uchun (ixtiyoriy).
- **`category`**, **`brand`**, **`model_name`**, **`mpn`**, **`source_url`**, **`comment`** — shop bilgan ma'lumot.
- **`status`** — `OPEN` → `RESOLVED` / `REJECTED`.
- **`resolved_spec_id`** — qo'shilgan (yoki topilgan) model. So'rov hal bo'lganda so'ralgan SKU shu modelga avtomatik bog'lanadi.
- **`resolution_note`** — rad etilsa, sabab ("bu PC qismi emas").

**Indeks:** `(status, created_at)` — platformaning umumiy navbati, hamma shoplar bo'yicha. Platforma xodimi shu jadvaldagi model nomlarini ko'radi, shopning boshqa ma'lumotini ko'rmaydi.

---

## 12. `platform.stored_files` — fayllar (S0-08)

**Nima uchun kerak:** rasm va boshqa fayllar haqidagi yozuv. Faylning o'zi MinIO'da (S3) turadi, bazada blob saqlanmaydi (ADR-014). Bu jadval `platform` schemasida, chunki keyin import fayllari va hisobot eksportlari ham shu yerda bo'ladi. Katalog uning birinchi foydalanuvchisi.

- **`purpose`** — `PRODUCT_IMAGE` (hozir), `IMPORT_FILE` va `EXPORT_FILE` (keyin).
- **`object_key`** — ombordagi yo'l: `shops/{shop_id}/product_image/{id}`. Fayl nomi yo'lga yozilmaydi: yo'lni taxmin qilib bo'lmaydi.
- **`is_public`** — mahsulot rasmi ochiq (DEC-133): sayt va brauzer keshlaydi. Qolgan fayllar 5 daqiqalik imzoli havola bilan beriladi.
- **Ombor:** `FileStorage` porti. Production'da S3-mos ombor, lokal va testda disk (`MinIO` obrazi Docker Hub'dan endi yuklanmaydi — TD-03 shu bilan yopiladi).
- **`mime_type`** — fayl **ichidan** aniqlanadi, nomidan emas. `.jpg` deb nomlangan dastur fayli o'tib ketmaydi. Ruxsat: JPEG, PNG, WebP.
- **`size_bytes`** — rasm uchun ko'pi bilan 5 MB.
- **`sha256`** — fayl butunligi; bir rasm ikki marta yuklansa, aniqlanadi.
- **`original_name`** — foydalanuvchiga ko'rsatish uchun. Logga yozilmaydi.
- **`status`** — `ACTIVE` / `DELETED`. Mahsulotdan olib tashlangan rasm `DELETED` bo'ladi. Ombordan haqiqiy o'chirish keyin fon ishida qilinadi.
- **`retention_until`** — saqlash muddati (engineering/26). Rasm uchun `NULL`: mahsulot bilan birga yashaydi.

**RLS:** shop bo'yicha (engineering/10 §4).

---

## Bog'lanishlar xaritasi

```
categories (platforma) ──< products ──< skus ──< price_versions
                              │          │  └── current_prices ──▶ price_versions (aynan shu SKU'niki)
                              │          ├── sku_spec_links >── reference_hardware_specs (platforma)
                              │          └─< spec_requests ─ ─ ─▶ reference_hardware_specs   └─< reference_hardware_spec_versions
                              └─< product_media ─ ─ ─▶ platform.stored_files (FK'siz, boshqa schema)

exchange_rates — shopniki, hech narsaga bog'lanmagan (narxni ko'rsatishda ishlatiladi)
```

---

## engineering/07 §4.3 dan farqlar (taklif)

- **`discount_rules` jadvali yo'q** (DEC-133). Chegirma limitlari allaqachon `platform.shop_policies` da. Taklif va buyurtmadagi aniq chegirma va uning tasdig'i `commerce` da (3-modul).
- **`currencies` jadvali yo'q.** Ikki valyuta uchun `CHECK (currency IN ('UZS','USD'))` yetarli. Har valyutaning minor birligi (UZS — 2, USD — 2) kodda (ADR-025).
- **`price_versions` da `valid_from` / `valid_to` yo'q.** Kelajakdagi sanaga narx qo'yish talabi yo'q, o'zgarmas yozuvda esa `valid_to` ni yangilab bo'lmaydi. Joriy narx `current_prices` da.
- **`categories` jadvali qo'shildi.** 07 da `category` oddiy matn edi. Business M04 toifalar va uch tilli nomlarni talab qiladi (2-savol).
- **`reference_hardware_spec_versions` qo'shildi** — engineering/17 §4.2 va §10 dagi kabi ("ikki ko'z").
- **`sku_spec_links.linked_by` → `method` + `linked_by`.** Eski nom "qanday bog'langan" ma'noni bildirardi. Endi `method` — qanday, `linked_by` — kim.
- **Keyingi modullarga:** `catalog_imports` va qatorlari — 5-modul (arq kerak), `pc_rulesets` va `build_profiles` — 6-modul (moslik engine'i).

---

## Founder qarorlari (2026-10-25, DEC-133)

1. **Saytga chiqarish:** ega va menejer qoralamani to'g'ridan chiqaradi. "Tekshiruvda" holati keyin katalog xodimi qo'shilganda ishlatiladi. Arxivlashni faqat ega qiladi: qoralama, chiqarilgan va yashirilgan holatdan.
2. **Toifalar:** hamma shop uchun bitta ro'yxat. Platforma jamoasi yuritadi, shop faqat tanlaydi.
3. **So'm narxi yaxlitlanmaydi:** aniq so'mgacha ko'rsatiladi.
4. **Mahsulot rasmlari ochiq.** Import fayllari va eksportlar yopiq.
5. **"Aksiya" jadvali Stage 1 da yo'q.**
