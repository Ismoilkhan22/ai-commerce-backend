# `commerce` schemasi — ma'lumotlar lug'ati (ombor va buyurtmalar)

> **Holat:** ✅ tasdiqlangan — DEC-134 (2026-10-25). Founder qarorlari oxirida. Diagramma: [`commerce.dbml`](commerce.dbml) → dbdiagram.io.
> **Kim o'qiydi:** founder va dasturchilar. Har jadval quyidagi tartibda: nima uchun kerak → har maydon nima va nega shunday → bog'lanishlar → misol.
> **Umumiy qoidalar** (`id`, `shop_id`, `(shop_id, id)` bilan bog'lash, `version`, holat matn sifatida, o'chirish yo'qligi) — [platform.md](platform.md) §0. Pul butun sonda — [catalog.md](catalog.md) §0. Bu yerda takrorlanmaydi.
> **Hajm:** ombor (S1-05), tez sotuv (DEC-123), buyurtmalar va band qilish (S4), saytdan buyurtma so'rovi (DEC-115). Leadlar va PC takliflari (S3) keyin qo'shiladi — §12.

Misollarda **"TechPC"** shopi ishlatiladi. Ega — **Ali**, menejer — **Vali**, operator — **Dilshod**, omborchi — **Bobur**. Filiallar — **Chilonzor** va **Yunusobod**. Mahsulot — **"MSI GeForce RTX 4060 Ventus 2X"**, narxi 4 800 000 so'm.

---

## 0. Bu schemada yangi narsalar

- **Uch xil son.** Har filialda har mahsulot uchun: **qoldiq** (omborda jismonan bor), **band** (tasdiqlangan buyurtmaga va'da qilingan), **ajratilgan** (buyurtma uchun yig'ilyapti). **Sotuvga mavjud = qoldiq − band − ajratilgan.** Sayt, AI va tez sotuv faqat shu songa qaraydi. U hech qachon noldan kam bo'lmaydi (BL-019). Bundan tashqari **tekshiruvda** degan to'rtinchi son bor: qaytgan yoki shikastlangan mahsulot, u sotilmaydi.
- **Ombor daftari.** Qoldiqning har o'zgarishi alohida qator bo'lib yoziladi: nima sababdan, qaysi hujjat bilan, kim qildi. Daftar faqat to'ldiriladi, hech narsa o'chirilmaydi. Har kecha daftar yig'indisi qoldiq bilan solishtiriladi. Farq chiqsa — ogohlantirish.
- **Oxirgi dona himoyasi.** Ikki operator oxirgi RTX 4060 ni bir vaqtda tasdiqlasa yoki shu paytda Bobur uni do'konda sotsa — faqat bittasi o'tadi. Buning uchun qoldiq qatori amal davomida "qulflanadi" va boshqalar navbat kutadi (engineering/12). Qulf doim bir xil tartibda olinadi, shuning uchun ikki amal bir-birini abadiy kutib qolmaydi.
- **Nusxa (snapshot).** Buyurtma qatorida mahsulot nomi, kodi, narxi, valyutasi, kursi va kafolati **nusxa** qilib saqlanadi. Ertaga Vali narxni o'zgartirsa ham, kecha kelishilgan buyurtma o'zgarmaydi.
- **Xaridor ma'lumoti himoyada.** Ism, telefon va manzil buyurtmaning alohida ustunlarida turadi. Telefon va manzil shifrlangan. Logga, xabarlar navbatiga (outbox) va o'zgarishlar tarixiga tushmaydi. Xaridor so'rasa — o'chiriladi, buyurtma raqamlari esa hisobot uchun qoladi (engineering/26).

---

## 1. `stock_balances` — hozirgi qoldiq

**Nima uchun kerak:** "Chilonzorda nechta RTX 4060 bor, nechtasi band?" degan savolga bir zumda javob. Har filial × har SKU uchun bitta qator.

- **`(shop_id, branch_id, sku_id)`** — primary key. Filial `platform` da, SKU `catalog` da: boshqa schema, shuning uchun FK yo'q. Service ular shu shopniki ekanini tekshiradi.
- **`on_hand`** — qoldiq: omborda jismonan bor. Tekshiruvdagilar bunga kirmaydi.
- **`reserved`** — band: tasdiqlangan, lekin hali yig'ilmagan buyurtmalar uchun.
- **`allocated`** — ajratilgan: yig'ilayotgan yoki xaridorni kutayotgan buyurtmalar uchun.
- **`quarantine_qty`** — tekshiruvda: qaytgan yoki "sotilmaydi" deb belgilangan mahsulot. Sotuvga chiqmaydi (BR-X11).
- **`version`** — har o'zgarishda o'zi oshadi. Sahifa eskirganini bilish uchun.

**Bazaning o'zi tekshiradi:**
- hech bir son manfiy emas;
- `reserved + allocated <= on_hand` — ya'ni sotuvga mavjud hech qachon manfiy emas.

Bu oxirgi himoya. Asosiy himoya — qulf va amaldan oldingi tekshiruv.

**Sotuvga mavjud** saqlanmaydi, har safar hisoblanadi. Saqlansa, uchta son bilan kelishmay qolishi mumkin edi.
**Qator qachon paydo bo'ladi:** shu filialda shu SKU bo'yicha birinchi kirim yoki tuzatishda. Qatori yo'q SKU — sotuvga mavjud 0.
**RLS:** ha — qoldiq tijoriy ma'lumot (engineering/10 §4).

**Misol:** Chilonzorda RTX 4060: qoldiq 3, band 1, ajratilgan 1, tekshiruvda 0 → **sotuvga mavjud 1**. Sayt "bor" deydi (yoki "kam qoldi" — `stock_display` sozlamasiga qarab, DEC-128).

---

## 2. `stock_ledger` — ombor daftari

**Nima uchun kerak:** "Bu qoldiq qayerdan keldi?" degan savolga har doim aniq javob. Kim, qachon, nima sababdan o'zgartirdi — hammasi shu yerda (BL-022). Kechasi solishtirish ham shu jadval bo'yicha.

- **`branch_id`, `sku_id`** — qaysi qoldiq o'zgardi. `stock_balances` ga FK bilan bog'langan: yo'q qoldiq qatoriga yozib bo'lmaydi.
- **`reason`** — sabab:
  - `RECEIPT` — kirim (mahsulot keldi): qoldiq +;
  - `ADJUSTMENT` — sanoqda farq chiqdi: qoldiq ±;
  - `OFFLINE_SALE` — tez sotuv: qoldiq − (DEC-123);
  - `RESERVE` — buyurtma tasdiqlandi: band +;
  - `ALLOCATE` — yig'ish boshlandi: band −, ajratilgan +;
  - `RELEASE` — buyurtma bekor qilindi: band yoki ajratilgan −;
  - `SALE` — buyurtma topshirildi: ajratilgan −, qoldiq −;
  - `QUARANTINE_IN` — "sotilmaydi" deb belgilandi: qoldiq −, tekshiruvda +;
  - `RETURN_QUARANTINE` — xaridordan qaytdi: tekshiruvda + (kafolat moduli, S5);
  - `RESTOCK` — tekshiruvdan o'tdi: tekshiruvda −, qoldiq +;
  - `WRITE_OFF` — yaroqsiz, hisobdan chiqarildi: tekshiruvda −.
- **`delta_on_hand`, `delta_reserved`, `delta_allocated`, `delta_quarantine`** — har sonning qanchaga o'zgargani.
- **`on_hand_after` … `quarantine_after`** — o'zgarishdan keyingi sonlar. "Mahsulot tarixi" ekranida "qoldiq 3 → 2" deb ko'rsatish uchun, butun daftarni qayta hisoblamasdan.
- **`ref_type`, `ref_id`** — qaysi hujjat sabab bo'ldi: kirim, tuzatish, tez sotuv, band yoki (S5) kafolat murojaati. Bir ustun bir nechta jadvalga ishora qiladi, shuning uchun FK yo'q.
- **`actor_membership_id`** — kim qildi. Stage 1 da har o'zgarishni xodim qiladi. `NULL` faqat kelajakdagi tizim amali uchun (Stage 2, kassa dasturi bilan sinxron).

**Unikal:** `(shop_id, reason, ref_type, ref_id, sku_id)` — bitta hujjat bitta SKU'ni bir sabab bilan faqat bir marta o'zgartiradi. Shuning uchun "Topshirildi" tugmasi ikki marta bosilsa ham, qoldiq bir marta kamayadi (TC-030). Bekor qilish ikki marta kelsa ham, band bir marta bo'shaydi (BL-021).
**O'zgarmaydi:** ilova roli `UPDATE` / `DELETE` qila olmaydi. Xato yozuv o'chirilmaydi, teskari tuzatish yoziladi.
**RLS:** ha.

**Misol:** Dilshod 1042-buyurtmani tasdiqladi. Daftarga bitta qator tushdi: `RESERVE`, band +1, sabab hujjati — shu buyurtma qatorining bandi, kim — Dilshod.

---

## 3. `stock_receipts` — kirim hujjati

**Nima uchun kerak:** bir kunda 10 xil mahsulot keldi. Bobur ularni bitta "kirim" qilib kiritadi. Kirimlar ro'yxatida bitta yozuv ko'rinadi, ichida 10 qator.

- **`branch_id`** — qaysi filialga keldi.
- **`note`** — ixtiyoriy izoh: "yetkazib beruvchidan 2-partiya".
- **`received_by`** — kim qabul qildi.

**Qatorlar alohida jadvalda emas** — ular daftarda: `RECEIPT` sababli, shu kirimga ishora qiluvchi yozuvlar. Bir kirimda bir SKU bir marta (takrorlari qo'shib yuboriladi).
**Tasdiq kerak emas** (engineering/12 §6). Xato kirim o'chirilmaydi — tuzatish bilan to'g'rilanadi (§4).
**Tannarx** (sotib olish narxi) hozir yozilmaydi. Foyda hisoboti qo'shilganda kirim qatoriga qo'shiladi.

**Misol:** Bobur Chilonzorga 5 ta RTX 4060 va 3 ta Ryzen 5 7600 qabul qildi. 1 ta kirim hujjati, daftarda 2 ta `RECEIPT` qatori. RTX 4060 qoldig'i 3 → 8.

---

## 4. `stock_adjustments` — qo'lda tuzatish

**Nima uchun kerak:** kirim va sotuvdan tashqari har qoldiq o'zgarishi uchun hujjat: sababi, dalili, kim so'radi, kim tasdiqladi. Business/04 da omborchi **so'raydi**, ega yoki menejer **tasdiqlaydi**.

- **`kind`** — tuzatish turi:
  - `ADJUSTMENT` — sanoqda farq chiqdi (+ yoki −);
  - `QUARANTINE_IN` — mahsulotni "sotilmaydi" deb belgilash, masalan qutisi ezilgan (M06, 5-band);
  - `RESTOCK` — tekshiruvdan o'tdi, sotuvga qaytarish;
  - `WRITE_OFF` — yaroqsizni hisobdan chiqarish.
- **`delta`** — qancha. `ADJUSTMENT` da + yoki −, qolganlarida musbat son.
- **`reason`** — **majburiy** (BL-022). Sababsiz tuzatish qabul qilinmaydi.
- **`evidence_file_id`** — rasm yoki dalolatnoma (ixtiyoriy). Fayl `platform.stored_files` da. Buning uchun fayl turlariga `STOCK_EVIDENCE` qo'shiladi.
- **`status`** — `PENDING` (kutilmoqda, qoldiq hali o'zgarmagan) → `APPROVED` (qo'llandi) yoki `REJECTED` (rad etildi).
- **`requested_by`**, **`requested_at`** — kim va qachon so'radi.
- **`decided_by`**, **`decided_at`**, **`decision_note`** — kim tasdiqladi yoki rad etdi. Rad etilsa, sabab majburiy. Ega yoki menejer o'zi tuzatsa, yozuv darhol `APPROVED` bo'ladi va `decided_by` — o'zi.
- **`on_hand_before`**, **`on_hand_after`** — tasdiq paytidagi eski va yangi qoldiq. Business/04 §3: "tarixda eski va yangi qiymat saqlanadi".
- **`version`** — ikki menejer bir so'rovni bir vaqtda tasdiqlay olmaydi.

**Tasdiq paytida qayta tekshiriladi:** so'rov yozilgandan keyin qoldiq o'zgargan bo'lishi mumkin. Tuzatish qoldiqni band + ajratilgandan pastga tushira olmaydi (TC-CON-12). Tushirsa — tasdiqlab bo'lmaydi: avval menejer buyurtmalarni ko'rib chiqadi (M06).
**Qachon tasdiq shart:** omborchining har tuzatishi — tasdiq bilan; ega va menejer o'zi to'g'ridan tuzatadi. Limit sozlamasi yo'q (DEC-134).
**RLS:** taklif — engineering/10 §4 ro'yxatiga qo'shish.

**Misol:** Bobur sanoqda RTX 4060 ni 7 ta topdi, tizimda 8 ta. So'rov: `ADJUSTMENT`, −1, "sanoqda 1 ta kam chiqdi". Vali tasdiqladi → qoldiq 8 → 7, daftarda `ADJUSTMENT` qatori.

---

## 5. `quick_sales` — tez sotuv

**Nima uchun kerak:** do'konga kelgan xaridor peshtaxtadan RTX 4060 oldi. Qoldiq shu zahoti kamaymasa, AI online xaridorga "bor" deb yuboradi (DEC-123). Shuning uchun xodim bir bosishda sotuvni kiritadi: **mahsulot + miqdor**, xaridor ma'lumoti kerak emas.

- **`branch_id`** — qaysi filialda sotildi.
- **`total_minor`**, **`currency`** — jami summa, doim so'mda, katalog narxida.
- **`sold_by`** — kim sotdi (BL-109).
- **`created_at`** — qachon.

**Qoida:** faqat **sotuvga mavjud** sondan sotiladi. Mahsulot online buyurtmaga band bo'lsa, tizim sotishga ruxsat bermaydi: "Bu mahsulot online buyurtma uchun band qilingan" (BL-109, TC-027).
**Bekor qilinmaydi.** Xato bosilsa — tuzatish (+1) sabab bilan.
**Ikki marta bosish:** takroriy so'rov himoyasi (`platform.idempotency_keys`) ikkinchi bosishni birinchisining javobiga aylantiradi.
**Hisobotda** offline sotuvlar alohida ko'rinadi.
**RLS:** ha.

---

## 6. `quick_sale_lines` — tez sotuv qatorlari

**Nima uchun kerak:** bir sotuvda bir nechta mahsulot bo'lishi mumkin. Har mahsulot — alohida qator, xuddi buyurtma qatori kabi (§8).

- **`sku_id`** — nima sotildi.
- **`title_snapshot`**, **`sku_code_snapshot`** — sotuv paytidagi nom va kod.
- **`qty`** — nechta (`> 0`).
- **`price_version_id`**, **`unit_price_minor`**, **`currency`**, **`exchange_rate_snapshot`**, **`unit_price_uzs_minor`** — narx. **Avtomatik**, joriy katalog narxidan: DEC-123 bo'yicha xodim faqat mahsulot va miqdorni kiritadi. Do'konda savdolashib arzonroq sotilgan bo'lsa ham, hisobotda katalog narxi turadi.
- **`line_total_minor`** — qator summasi, so'mda.
- **`warranty_months`** — kafolat nusxasi (BL-057). Kafolat muddati keyin o'zgarsa ham, shu sotuvga ta'sir qilmaydi.

**Unikal:** bir sotuvda bir SKU — bitta qator (daftar kaliti bilan mos).
**RLS:** taklif — engineering/10 §4 ro'yxatiga qo'shish.

**Misol:** Bobur Chilonzorda 1 ta RTX 4060 sotdi. 1 ta tez sotuv, 1 ta qator, 4 800 000 so'm. Daftarda `OFFLINE_SALE`, qoldiq 7 → 6.

---

## 7. `orders` — buyurtma

**Nima uchun kerak:** xaridor olmoqchi bo'lgan narsa va uning qoralamadan topshirilguncha yo'li (FSM-08). Buyurtma uch joydan keladi: AI sotuvchi, shop sayti yoki xodim. Stage 1 da to'lov tizimdan tashqarida (DEC-100): pulni shop o'zi oladi.

**Raqam va kelib chiqishi:**
- **`number`** — shop ichida ketma-ket: 1, 2, 3… Xaridorga "#1042" deb ko'rsatiladi. Har shopning raqamlari alohida (§10).
- **`status`** — FSM-08:

  ```
  Qoralama (DRAFT) ──(operator ko'rib chiqdi / xaridor saytda yubordi)──▶ Tasdiq kutilmoqda (PENDING_CONFIRMATION)
  Tasdiq kutilmoqda ──(operator yoki menejer tasdiqladi)──▶ Tasdiqlandi (CONFIRMED)        [mahsulot band qilinadi]
  Tasdiqlandi ──(yig'ish boshlandi)──▶ Tayyorlanmoqda (PROCESSING)                        [band → ajratilgan]
  Tayyorlanmoqda ──("olib ketishga tayyor")──▶ Tayyorlanmoqda                             [holat o'zgarmaydi, xaridorga xabar]
  Tayyorlanmoqda ──(xaridor oldi)──▶ Topshirildi (COMPLETED)                              [qoldiq bir marta kamayadi]
  Qoralama ──(xodim yoki xaridor bekor qildi)──▶ Bekor qilindi (CANCELLED)
  Tasdiq kutilmoqda / Tasdiqlandi ──(menejer yoki ega, sabab bilan)──▶ Bekor qilindi       [band bo'shaydi]
  Tayyorlanmoqda ──(muammo)──▶ Muammoli (EXCEPTION) ──(menejer)──▶ Tayyorlanmoqda yoki Bekor qilindi
  ```

  Har o'tish `platform.transition_log` ga yoziladi. AI hech qanday o'tishni bajarmaydi, faqat qoralama yaratadi (BL-110).
- **`source`** — `AI`, `STOREFRONT` (sayt) yoki `STAFF` (xodim qo'lda).
- **`source_request_id`** — takror himoyasi (BL-046). AI uchun — AI so'rovining ID'si. Sayt uchun — buyurtma formasi ochilganda yaratilgan kalit. Xaridor "Buyurtma berish" ni ikki marta bossa yoki internet uzilib qayta yuborilsa, ikkinchi buyurtma yaratilmaydi, birinchisi qaytadi. **`(shop_id, source, source_request_id)` unikal.**
- **`conversation_id`**, **`customer_ref`** — chat orqali kelgan bo'lsa, qaysi suhbat va qaysi xaridor (`messaging` schemasi, FK'siz). Saytdan kelganda bo'sh.
- **`quote_id`**, **`quote_revision_id`** — PC taklifidan kelgan bo'lsa (S3). Hozir doim bo'sh (§12).

**Kim va qayerda:**
- **`branch_id`** — mahsulot qaysi filialdan band qilinadi. Olib ketishda — xaridor tanlagan filial (faqat ochiq va olib ketish joyi bo'lgan filial). Yetkazishda — operator tanlaydi. **Tasdiqlashdan oldin majburiy.** Bir buyurtma — bir filial (DEC-134).
- **`assigned_membership_id`** — mas'ul operator. Operator faqat o'ziga biriktirilgan buyurtmani tasdiqlaydi (DEC-108). Saytdan kelgan buyurtma biriktirilmagan holda navbatga tushadi: operator o'ziga oladi yoki menejer biriktiradi.
- **`fulfillment_method`** — `PICKUP` (olib ketadi) yoki `DELIVERY` (yetkazib beriladi). Yetkazishni shop o'zi tashkil qiladi, narxi operator bilan kelishiladi (DEC-113, DEC-100h).

**Xaridor ma'lumoti** (engineering/26):
- **`customer_name`** — ism.
- **`customer_phone_enc`** — telefon, **shifrlangan**. Bazani o'g'irlagan odam raqamni o'qiy olmaydi.
- **`customer_phone_hmac`** — telefonning "barmoq izi". Shifrlangan ustun bo'yicha qidirib bo'lmaydi, shuning uchun Dilshod "+998 90 123 45 67" ni qidirsa, tizim shu izni hisoblab topadi. Izdan raqamni qayta tiklab bo'lmaydi.
- **`delivery_address_enc`** — yetkazish manzili, shifrlangan. Yetkazishda majburiy.
- **`customer_locale`** — `uz`, `ru` yoki `en`. Xaridorga xabarlar shu tilda ketadi (UAT-M17).
- **`customer_comment`** — xaridor saytda yozgan izoh: "kechqurun qo'ng'iroq qiling".
- **`consent_version`** — sayt formasidagi rozilik matnining versiyasi ("ma'lumotlarim buyurtma uchun ishlatilishiga roziman", engineering/26 §8). Saytdan kelganda majburiy.
- **`pii_erased_at`** — xaridor ma'lumoti o'chirilgan vaqt. O'chirishda ism, telefon, manzil, izohlar tozalanadi. Qatorlar va summalar hisobot uchun qoladi.

**Pul:**
- **`currency`** — doim `UZS`: xaridor so'mda to'laydi (DEC-121).
- **`total_minor`** — qatorlar yig'indisi. Yetkazish narxi kirmaydi (DEC-100h).

**Vaqtlar va kim qildi:** `submitted_at`, `confirmed_at` + `confirmed_by`, `processing_at`, `ready_at`, `completed_at` + `completed_by`, `cancelled_at` + `cancelled_by`. Bular `transition_log` da ham bor, lekin ro'yxat, eslatma va hisobot uchun shu yerda turgani tezroq.
- **`submitted_at`** — 24 soatlik "tasdiqlanmagan" eslatmasi shundan hisoblanadi (DEC-104).
- **`ready_at`** — "olib ketishga tayyor" bosilgan vaqt. Holat o'zgarmaydi, xaridorga xabar ketadi.
- **`cancel_reason`** — tasdiq kutilayotgan, tasdiqlangan yoki muammoli buyurtmani bekor qilishda **majburiy** (BL-049).
- **`exception_reason`** — "muammoli" holat sababi: "mahsulot shikastlangan", "xaridor bosh tortdi".

**"To'landi" belgisi** (DEC-100a): **`paid_mark_at`**, **`paid_mark_by`**, **`paid_mark_method`** (`CASH`, `CARD`, `TRANSFER`, `OTHER`). Bu to'lov holati emas, xodimning belgisi. Tizim tekshirmaydi, hisobotda "tekshirilmagan" deb ko'rsatiladi. Uchala ustun birga to'ldiriladi.

**Boshqalar:**
- **`tracking_token_hash`** — saytdagi "buyurtmam qayerda?" havolasi uchun. Bazada havolaning o'zi emas, faqat xeshi turadi: baza sizib chiqsa ham, havolani tiklab bo'lmaydi.
- **`created_by`** — xodim qo'lda yaratsa, kim. AI va saytda bo'sh.
- **`version`** — Dilshod va Vali bir vaqtda tasdiqlasa, ikkinchisi "buyurtma o'zgardi" oladi.

**Bazaning o'zi tekshiradi:** tasdiqlangan va undan keyingi holatlarda filial va tasdiq vaqti bo'sh emas; jami manfiy emas; valyuta `UZS`.
**Indekslar:** holat bo'yicha ro'yxat (yangisi birinchi), "mening buyurtmalarim", telefon bo'yicha qidirish.
**RLS:** ha.

**Misol:** saytdan so'rov keldi: Jasur, +998 90 123 45 67, 1 ta RTX 4060, Chilonzordan olib ketadi. Buyurtma #1042 yaratildi, holati darhol "Tasdiq kutilmoqda". Mahsulot hali band emas. Dilshod o'ziga oldi, Jasurga qo'ng'iroq qildi va tasdiqladi: Chilonzorda 1 ta band bo'ldi.

---

## 8. `order_lines` — buyurtma qatori

**Nima uchun kerak:** buyurtmada nima, nechta va qanday narxda. Hammasi **nusxa**: katalog keyin o'zgarsa ham, buyurtma o'zgarmaydi.

- **`position`** — ko'rsatish tartibi.
- **`sku_id`**, **`product_id`** — `catalog` dagi SKU va mahsulot. Boshqa schema — FK yo'q. Qoralama yaratilganda service SKU shu shopniki, faol va saytda chiqarilgan ekanini tekshiradi.
- **`title_snapshot`** — nom + variant, buyurtma paytidagidek: "MSI GeForce RTX 4060 Ventus 2X · 8 GB".
- **`sku_code_snapshot`** — SKU kodi.
- **`qty`** — nechta (`> 0`).
- **`price_version_id`** — narx qaysi narx yozuvidan olingan. Tasdiqlashda joriy narx bilan solishtiriladi: farq bo'lsa — "narx o'zgardi", xaridordan qayta rozilik (DEC-127, TC-031).
- **`unit_price_minor`** + **`currency`** — narx o'z valyutasida (so'm yoki dollar), katalogdagidek.
- **`exchange_rate_id`** + **`exchange_rate_snapshot`** — dollar narxi bo'lsa, qaysi kurs bilan so'mga o'girilgan. Dollarda kurs majburiy.
- **`unit_price_uzs_minor`** — xaridor ko'radigan narx, so'mda. Yaxlitlanmaydi, eng yaqin so'mgacha (DEC-133).
- **`discount_pct`** — chegirma foizi, 0…100.
- **`discount_requested_by`**, **`discount_approved_by`**, **`discount_approved_at`** — kim so'radi, kim tasdiqladi (DEC-110). Operator chegirma bera olmaydi, faqat so'raydi. Menejer 5% gacha, undan ko'pini ega tasdiqlaydi (limitlar `shop_policies` da). Chegirma bor-u tasdiqlanmagan bo'lsa, buyurtmani tasdiqlab bo'lmaydi.
- **`line_total_minor`** — qator summasi so'mda: miqdor × narx × (1 − chegirma).
- **`warranty_months`** — kafolat nusxasi (BL-057, DEC-114). Kafolat murojaati (S5) shu qiymatga qaraydi.

**Unikal:** bir buyurtmada bir SKU — bitta qator. 2 ta kerak bo'lsa, `qty = 2`.
**Qachon o'zgaradi:** faqat qoralama va tasdiq kutilayotgan holatda (operator xaridor bilan kelishib, miqdorni yoki mahsulotni almashtiradi). Tasdiqlangandan keyin o'zgarmaydi: bekor qilinadi va yangi buyurtma ochiladi (DEC-134).
**RLS:** ha.

**Misol (dollar):** Ryzen 5 7600 narxi 200 dollar (`20000` sent), TechPC kursi 12 800. Qatorda: `unit_price_minor = 20000`, `currency = USD`, `exchange_rate_snapshot = 12800`, `unit_price_uzs_minor = 256000000` (2 560 000 so'm). Kurs ertaga 12 900 bo'lsa ham, bu qatordagi nusxa o'zgarmaydi. Lekin tasdiqlashda so'm narxi qayta hisoblanadi: endi 2 580 000 so'm, farq bor → "narx o'zgardi", xaridordan qayta rozilik (DEC-134).

---

## 9. `order_notes` — buyurtma izohlari

**Nima uchun kerak:** operator xaridor bilan telefonda gaplashadi va kelishuvni yozib qo'yadi (DEC-100g). Keyin boshqa xodim nima kelishilganini ko'radi.

- **`kind`** — `NOTE` (oddiy izoh) yoki `CALL_RESULT` (qo'ng'iroq natijasi / kelishuv).
- **`author_membership_id`** — kim yozdi.
- **`body`** — matn. Ichida telefon yoki manzil bo'lishi mumkin, shuning uchun xaridor ma'lumoti o'chirilganda matn ham tozalanadi.

**Faqat qo'shiladi**, tahrirlanmaydi: izoh — tarix.
**RLS:** ha.

**Misol:** Dilshod: "Jasur bilan gaplashdim, ertaga 18:00 da Chilonzordan oladi, naqd to'laydi".

---

## 10. `order_counters` — buyurtma raqami

**Nima uchun kerak:** har shop raqamlari 1 dan boshlanishi va bo'shliqsiz ketishi uchun. PostgreSQL'ning oddiy hisoblagichi hamma shop uchun bitta bo'lardi.

- **`shop_id`** — primary key, har shopga bitta qator.
- **`last_number`** — oxirgi berilgan raqam. Yangi buyurtma yaratilganda shu tranzaksiyada +1 qilinadi. Buyurtma yaratilmay qolsa, raqam ham qaytadi.

**RLS:** kerak emas — ichida faqat raqam bor.

---

## 11. `reservations` — band qilish

**Nima uchun kerak:** "bu mahsulot Jasurniki, boshqaga va'da qilma" degan belgi (FSM-07). Har buyurtma qatoriga bitta band.

- **`order_id`**, **`order_line_id`** — qaysi buyurtma va qaysi qator. FK uch ustun bilan: band boshqa buyurtmaning qatoriga bog'lanib qolmaydi.
- **`branch_id`**, **`sku_id`** — qaysi qoldiqdan. `stock_balances` ga FK bilan.
- **`qty`** — nechta (`> 0`).
- **`status`** — FSM-07:

  ```
  (buyurtma tasdiqlandi) ──▶ Band (ACTIVE)                    [band +qty]
  Band ──(yig'ish boshlandi)──▶ Ajratilgan (ALLOCATED)        [band −qty, ajratilgan +qty]
  Ajratilgan ──(topshirildi)──▶ Ishlatildi (CONSUMED)         [ajratilgan −qty, qoldiq −qty]
  Band / Ajratilgan ──(buyurtma bekor qilindi)──▶ Bo'shatildi (RELEASED)
  Band / Ajratilgan ──(menejer "muddati o'tdi" deb bekor qildi)──▶ Muddati o'tdi (EXPIRED)
  ```

  Har o'tish qoldiq va daftar bilan **bitta tranzaksiyada**.
- **`review_at`** — shu vaqtdan keyin menejerga "bekor qilinsinmi?" vazifasi tushadi (tasdiqdan 72 soat, DEC-104). Avtomatik bekor qilinmaydi. Menejer "kutamiz" desa, vaqt suriladi. "Bekor" desa, buyurtma bekor qilinadi, band `EXPIRED` bo'ladi (oddiy bekor qilishdan farqlash uchun). Band va ajratilgan bandlarga tegishli (DEC-134).
- **`allocated_at`**, **`closed_at`** — qachon ajratildi va qachon yopildi (ishlatildi, bo'shatildi yoki muddati o'tdi).
- **`version`** — bitta bandni ikki amal bir vaqtda yopa olmaydi.

**Bir marta qoidasi:** daftarda har band bir martadan `RESERVE`, `ALLOCATE` va oxirida `SALE` yoki `RELEASE` oladi. Unikal kalit takrorni bazaning o'zida to'xtatadi.
**RLS:** ha.

**Misol:** #1042 tasdiqlandi → band `ACTIVE`, Chilonzor RTX 4060: band 0 → 1. Bobur yig'ishni boshladi → `ALLOCATED`, band 1 → 0, ajratilgan 0 → 1. Jasur oldi → `CONSUMED`, ajratilgan 1 → 0, qoldiq 6 → 5.

---

## 12. Keyin qo'shiladigan narsalar

**PC taklifi (S3) qanday ulanadi.** `leads`, `quotes`, `quote_revisions`, `quote_lines` shu `commerce` schemasiga qo'shiladi. Xaridor taklifni qabul qilganda **qoralama buyurtma** yaratiladi:
- qatorlar taklif versiyasidan nusxa olinadi (narx katalogdan emas, taklifdan);
- `quote_id` va `quote_revision_id` to'ldiriladi, `(shop_id, quote_revision_id) → quote_revisions` FK qo'shiladi;
- `source` ga `QUOTE` qo'shiladi;
- tasdiqlashda narx taklif versiyasi bilan solishtiriladi (engineering/12 §5, 8-qadam).

Hozirgi jadvallarni o'zgartirish kerak bo'lmaydi.

**Savatcha bazada saqlanmaydi.** Xaridor savatchasi brauzerda turadi (4-modul — sayt). Bazaga faqat yuborilgan so'rov tushadi: shu bilan tashlab ketilgan savatchalar bazani to'ldirmaydi.

**Kam qolgan mahsulot ogohlantirishi** (M06, 6-band) — alohida jadval kerak emas: sotuvga mavjud son `shop_policies.low_stock_threshold` dan kam bo'lsa, vazifa yaratiladi.

---

## Bog'lanishlar xaritasi

```
orders ──< order_lines ──< reservations >── stock_balances ──< stock_ledger
  │                          (orders ga ham     │                  │
  └─< order_notes             to'g'ridan FK)    └─< stock_adjustments
                                                                   │ ref_type + ref_id (FK'siz):
quick_sales ──< quick_sale_lines                                   ├─ ─ ▶ stock_receipts
                                                                   ├─ ─ ▶ stock_adjustments
order_counters — har shopga bitta qator (raqam)                    ├─ ─ ▶ quick_sales
                                                                   └─ ─ ▶ reservations

──<  bir → ko'p (FK, shop_id bilan)      ─ ─▶  ishora, FK'siz
Boshqa schemalar (faqat uuid, FK'siz): catalog.skus, price_versions, exchange_rates;
platform.branches, memberships, stored_files; messaging.conversations, customer_identities
```

---

## engineering/07 §4.4 dan farqlar (taklif)

- **`stock_balances`** — nomlar 07 dagidek: `quarantine_qty`, `version`. Engineering/12 §6.1 dagi SQL'da `inspection` va `stock_version` deyilgan — 07 tanlandi.
- **`stock_ledger`:**
  - `delta_quarantine` va `*_after` ustunlari qo'shildi (tekshiruvdagi son va "mahsulot tarixi" uchun);
  - `idempotency_key` olib tashlandi: takrorni unikal kalit va `platform.idempotency_keys` ushlaydi;
  - sabablar: `CONSUME` olib tashlandi (topshirishda `SALE` yoziladi, engineering/12 §6); `RETURN_RESTOCK` → `RESTOCK` (qaytgan va "sotilmaydi" mahsulot uchun bitta); `QUARANTINE_IN` va `WRITE_OFF` qo'shildi (M06, 5-band);
  - tez sotuv sababi — `OFFLINE_SALE` (DEC-123 va 07 dagidek; engineering/12 §6 da `QUICK_SALE` deyilgan).
- **`stock_adjustment_requests` → `stock_adjustments`.** Ega yoki menejerning to'g'ridan tuzatishi ham shu yerga yoziladi (darhol `APPROVED`). Shunda har tuzatishning sababi bitta joyda. `kind`, `on_hand_before/after`, `decision_note` qo'shildi.
- **`stock_receipts` qo'shildi** — kirim hujjati. 07 da kirim faqat daftar qatori edi, izoh va guruhlash uchun joy yo'q edi.
- **`quick_sales.lines` (JSONB) → `quick_sale_lines` jadvali** — buyurtma qatori bilan bir xil tuzilma; hisobotda SKU bo'yicha yig'ish oson.
- **`orders`:**
  - `agreement_note` olib tashlandi — kelishuv `order_notes` da (`CALL_RESULT`), tarixi bilan;
  - xaridor ustunlari qo'shildi: `customer_name`, `customer_phone_enc`, `customer_phone_hmac`, `customer_locale`, `customer_comment`, `consent_version`, `pii_erased_at` (engineering/26 §4, §8);
  - `source_request_id` (engineering/12 §9), `quote_revision_id`, `created_by` qo'shildi;
  - holat vaqtlari va kim qilgani: `confirmed_by` (engineering/12 §5, 11-qadam), `completed_by`, `cancelled_by` va boshqalar;
  - mas'ul operator — `assigned_membership_id` (07 dagidek; engineering/12 §5 da `assigned_to`).
- **`order_lines`:** nom va kod nusxasi, `exchange_rate_id`, `unit_price_uzs_minor`, `line_total_minor`, chegirma tasdig'i ustunlari qo'shildi. `warranty_snapshot` (JSONB) → `warranty_months`: katalogda faqat oy bor.
- **`reservations`** — har qatorga bitta (07 dagidek). Engineering/12 §5 dagi "reservation := INSERT ACTIVE (order_id, lines)" buyurtmaga bitta bandga o'xshab o'qiladi — qatorga bitta bo'ladi. `stock_balances` ga FK, `allocated_at`, `closed_at` qo'shildi.
- **`order_counters` qo'shildi** — shop ichida ketma-ket raqam uchun.

---

## Founder qarorlari — DEC-134 (2026-10-25)

Hujjatlarda hal qilinmagan yoki bir-biriga zid 5 ta savol bo'yicha. Bulardan oldin hal bo'lganlar: band qilish faqat tasdiqda (DEC-100b), saytdan so'rov band qilmaydi (M07), tez sotuvda xaridor ma'lumoti kerak emas (DEC-123), raqam shop ichida ketma-ket (07).

**1. 72 soatlik "bekor qilinsinmi?" vazifasi — band va ajratilgan bandlarga.**
Hisob tasdiqdan boshlanadi. Tayyor turgan, lekin xaridor olib ketmagan buyurtma ham menejerga eslatiladi. Menejer "bekor" desa, buyurtma tayyorlanayotgan bo'lsa ham bekor qilinadi, band "muddati o'tdi" bo'ladi va mahsulot sotuvga qaytadi. FSM-07 va FSM-08 ga shu o'tishlar qo'shildi (`business/05`).

**2. Bir buyurtma — bitta filial.**
Hamma qator shu filial qoldig'idan band qilinadi, yetmasa — "qolmagan". Boshqa filialdagi mahsulot avval ikki tuzatish bilan ko'chiriladi yoki alohida buyurtma ochiladi.

**3. Tasdiqlangan buyurtma o'zgartirilmaydi.**
Xaridor fikrini o'zgartirsa, menejer yoki ega buyurtmani sabab bilan bekor qiladi (band bo'shaydi), operator yangi buyurtma ochadi. Qatorlar faqat qoralama va tasdiq kutilayotgan holatda o'zgaradi.

**4. Omborchining har tuzatishi tasdiq bilan.**
Omborchi so'raydi, menejer yoki ega tasdiqlaydi. Ega va menejer o'zi to'g'ridan tuzatadi: yozuv darhol "tasdiqlangan", sabab majburiy, daftarga tushadi. Limit sozlamasi yo'q.

**5. Kurs o'zgarsa — tasdiqlashdagi narx, farq bo'lsa xaridordan so'raladi.**
Tasdiqlashda har qatorning so'mdagi narxi qayta hisoblanadi: joriy narx × joriy kurs. So'ralgan paytdagi so'm narxidan farq qilsa, buyurtma tasdiqlanmaydi: "narx o'zgardi", operator xaridordan yangi narxga rozilik oladi va qatorlarni yangilaydi (DEC-127, BL-047). Xaridor ko'rgan summa jim o'zgarmaydi, kurs farqini shop ham ko'tarmaydi.
