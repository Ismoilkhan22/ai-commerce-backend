# 7-modul. 7b qism: kafolat murojaatlari (`support`), backend

> **Holat:** backend bitdi (2026-10-27), commit qilinmagan — founder ko'rib chiqishi kutilmoqda.
> **Asos:** [db/support.md](../db/support.md) va [.dbml](../db/support.dbml), DEC-145 (taklif), FSM-11 (business/05, o'zgarmagan), business/04 (ruxsatlar).
> Frontend ekranlari ("Kafolat murojaatlari", kartochka, "Xaridorga xabar berish" tugmasi) keyingi qism — bu qismda faqat backend.

---

## 1. Nima bitdi

Xaridor "mahsulot ishlamayapti" desa, xodim murojaat ochadi. Murojaat sotuv qatoriga bog'lanadi, kafolat muddati sotuv paytidagi nusxadan hisoblanadi, qarorni menejer yoki ega qiladi. Ombor yozuvlari commerce orqali, bitta tranzaksiyada tushadi.

```
Yangi (NEW) ──▶ Diagnostika (IN_REVIEW) ──▶ Qabul qilindi (APPROVED) ──▶ Xizmatda (IN_SERVICE) ──▶ Hal qilindi (RESOLVED) ──▶ Yopildi (CLOSED)
                       └──▶ Rad etildi (REJECTED)  [yakuniy, sabab majburiy]
Xizmatda: almashtirish yoki qaytarish bo'lsa, qaytgan dona karantinga tushadi (RETURN_QUARANTINE)
Hal qilindi: almashtirish bo'lsa, yangi dona ombordan chiqadi (WARRANTY_REPLACEMENT)
Hal qilindi ──(7 kun o'tdi)──▶ Yopildi: tizim o'zi yopadi (soatiga bir marta tekshiradi)
```

Murojaat uch joydan ochiladi:
- tizimdagi buyurtma qatori (buyurtma "Topshirildi" bo'lishi shart);
- do'kondagi tez sotuv qatori;
- tizimdan oldingi sotuv (chek raqami bilan). Bunda qarorni doim menejer qiladi va qabul qilishda izoh majburiy.

Qoidalar:
- **Kafolat muddati** — sotuv qatoridagi `warranty_months` nusxasidan, shop vaqt zonasida (BL-057). Katalog keyin o'zgarsa ham eski sotuvga ta'sir qilmaydi. Oxirgi kun ham kafolat ichida.
- **Muddat tugagan bo'lsa** murojaat ochilmaydi: 422 `WARRANTY_EXPIRED` (javobda muddat va oylar bor). Menejer yoki ega sabab yozib ochishi mumkin; sabab va kim ruxsat bergani murojaatda qoladi.
- **Qaror turi** (`resolution`): ta'mirlash (REPAIR), almashtirish (REPLACE), qaytarish (REFUND). Faqat menejer/ega tanlaydi.
- **Karantin faqat almashtirish va qaytarishda.** Ta'mirdagi mahsulot xaridorniki: omborga kirmaydi, daftarga hech narsa yozilmaydi.
- **Almashtirish:** avval qaytgan dona karantinga (xizmat boshlanganda), keyin yangi dona ombordan (hal qilinganda). Yangi dona boshqa model bo'lishi mumkin (menejer tanlaydi).
- **Karantindagi donani chiqarish** — mavjud "sotuvga qaytarish" (RESTOCK) yoki "hisobdan chiqarish" (WRITE_OFF) tuzatishi, `support_case_id` bilan. Bitta murojaat karantinga tushirgandan ko'p chiqarib bo'lmaydi, boshqa murojaatning donasiga tegib bo'lmaydi.
- **Xaridor ma'lumoti:** ism va telefon faqat murojaatning o'zida. Telefon shifrlangan, qidirish kalitli xesh orqali (buyurtmadagidek). Event, audit va idempotentlik jadvaliga tushmaydi.
- **Xaridorga xabar** faqat murojaat suhbatga bog'langan bo'lsa ketadi (buyurtma suhbatdan bo'lsa o'zi bog'lanadi). Suhbat bo'lmasa — jim.

---

## 2. Endpoint'lar (`/api/v1/shop/support/cases`)

O'qish:
- `GET /support/cases` — ro'yxat. Filtrlar: `status` (vergul bilan bir nechta), `resolution`, `source`, `branch_id`, `sku_id`, `assigned` (`me`, `unassigned` yoki xodim ID), `q` (K-12, telefon, ism, mahsulot nomi), `number`, `limit`, `cursor`.
- `GET /support/cases/{id}` — kartochka: sotuv va kafolat nusxasi, izohlar, rasmlar (imzoli havola), ombor holati (`stock`), tarix (`timeline`: o'tishlar va izohlar). `ETag` qaytadi.

Yozish (hammasi `Idempotency-Key` bilan):
- `POST /support/cases` — ochish (201). Ruxsat: ega, menejer, operator.
- `POST /{id}/start-review`, `/receive-item`, `/close`, `/notify-ready`, `/notes`, `/attachments` — ega, menejer, operator, omborchi (`support.case.service`).
- `POST /{id}/approve`, `/reject`, `/resolution`, `/assign` — faqat ega va menejer (`support.case.decide`).
- `POST /{id}/start-service`, `/resolve` — ega, menejer, omborchi (`support.case.fulfil`).
- Holat o'zgartiradigan amallar `If-Match: "vN"` talab qiladi (eski versiya — 409 `VERSION_CONFLICT`). Taqiqlangan o'tish — 409 `INVALID_STATE_TRANSITION`.
- Rasm yuklash: `POST /api/v1/shop/files?purpose=SUPPORT_EVIDENCE`, keyin `/attachments` bilan biriktiriladi (ko'pi bilan 10, yopiq fayl).

Realtime: `support.case.*` event'lari panelga faqat ID bilan signal beradi (`case.changed`).

---

## 3. Bajarilgan bandlar

- [x] Yangi domen `app/domains/support/`: `models/`, `services/` (ochish va izoh/rasm, o'tishlar va ombor, ko'rinish, anonimlashtirish), `api/routes.py`, `permissions.py`, `state_machine.py`, `events.py`, `jobs.py`, `providers.py`, `domain_manifest.py`.
- [x] Migratsiyalar (dev bazaga qo'llandi, `make migrate`):
  - `support_0002_support_tables` — `cases`, `case_notes`, `case_attachments` (RLS FORCE, DELETE olingan), `case_counters`, `outbox_events`, `consumer_receipts`;
  - `commerce_0010_warranty_support` — daftar sababi `WARRANTY_REPLACEMENT`, `stock_adjustments.support_case_id` va indeks;
  - `platform_0015_support_evidence_purpose` — fayl turi `SUPPORT_EVIDENCE`.
- [x] Domenlar orasidagi bog'lanish: `app/shared/contracts/support.py` (`SupportCommercePort`), commerce tomoni `SupportCommercePortImpl` (`query_port.py`), ulanish `app/dependencies.py` va `app/main.py`. Support commerce kodini import qilmaydi.
- [x] Commerce'ga kichik qo'shimchalar: `StockService.return_to_quarantine`, `issue_replacement`, `case_stock`; tuzatishda `support_case_id` tekshiruvi; tez sotuv qatori javobida `id` (murojaat shu qatordan ochiladi).
- [x] Xodimga: vazifa `SUPPORT_CASE_DECISION` (menejer/ega, qaror qabul qilinsa o'zi yopiladi) va xabarnoma `staff.support_case_opened`.
- [x] Xaridorga 4 ta shablon (uz/ru/en): `customer.support_case_opened`, `_approved`, `_rejected`, `_ready`. Yuboruvchi — messaging (`support_case_notify`), bir holatga bitta xabar. Rad sababi kodidan xaridor tilida chiqadi, erkin izoh ketmaydi.
- [x] Xato kodi `WARRANTY_EXPIRED` (422) va uch tilda tarjimasi.
- [x] Rejali ish `support_case_auto_close` (soatiga bir marta): hal qilinganiga 7 kun bo'lgan murojaat yopiladi, jurnalda `SYSTEM` va sabab `AUTO_CLOSE_7_DAYS`.
- [x] Anonimlashtirish: `erase_customer_handler` — faqat yakunlangan (rad etilgan yoki yopilgan) murojaatlar; ism, telefon va izoh matni tozalanadi.
- [x] `tests/architecture/fsm_spec.yaml` ga `support.case` (FSM-11 strelkalari).

---

## 4. Tekshiruv

- `tests/integration/test_support.py` — 21 test (haqiqiy PostgreSQL, HTTP orqali):
  - holatlar jadvali, If-Match, takroriy so'rov, taqiqlangan o'tishlar;
  - kafolat muddati: sotuv nusxasi (katalog emas), menejer ruxsati, tashqi sotuv, qaytarish turi, ochiq miqdor yig'indisi;
  - ombor: almashtirish, qaytarish, ta'mir, boshqa SKU bilan almashtirish, dona yetmasa to'liq qaytish, takroriy chaqiruvda bitta yozuv; har testda daftar yig'indisi qoldiqqa teng;
  - ruxsatlar (to'rt rol), RLS va boshqa shop (404, fayl, tuzatish), o'chirish huquqi yo'qligi;
  - telefon shifrlangan, event/audit/idempotentlikda ism, telefon, muammo matni yo'q;
  - rasmlar (tur, takror, 10 ta chegara, yopiq fayl), anonimlashtirish;
  - xaridorga 4 xabar: ruscha, bir marta, suhbatsiz — 422 va jim.
- `tests/unit/test_support_units.py` — 10 test: oy qo'shish, kafolat oxirgi kuni va zona, FSM-11 qoidalari, ruxsatlar, shablonlar, event'da PII so'zlari yo'q.

---

## 5. Ataylab keyinga

- Frontend ekranlari.
- Omborchiga "karantindagi dona" vazifasi (`SUPPORT_QUARANTINE_REVIEW`) va 3 kun harakatsiz murojaat vazifasi (`SUPPORT_CASE_STALE`) — hozircha kartochkada `stock` bor, vazifa yo'q.
- `reporting` ga qaytarishlar hisoboti (`refund_amount_minor` va `support.case.resolved` tayyor).
- Suhbatdagi rasmni murojaatga biriktirish (`source_message_id` maydoni bor, nusxalash yo'q).
- AI murojaat ochmaydi (faqat operatorga uzatadi) — o'zgarmagan.

---

## Founder ko'rib chiqishi uchun qarorlar

**Q1. Ombor yozuvi event orqali emas, to'g'ridan-to'g'ri chaqiruv orqali.**
- **Tanlov:** support commerce'ning ombor xizmatini `SupportCommercePort` orqali o'z tranzaksiyasida chaqiradi. Ombor yozuvi hamon faqat commerce kodida (DEC-126).
- **Nega:** event orqali bo'lsa holat "Xizmatda" bo'lib, daftarga yozuv keyinroq tushardi, xato bo'lsa ikkalasi ajralib qolardi. Bu yerda ikkalasi bitta COMMIT'da yoki ikkalasi ham yo'q.
- **Muqobil:** db/support.md dagi dastlabki reja: event + commerce tinglovchisi. Domenlar yana ajralgan, lekin "dona yo'q" holatini keyin hal qilish kerak.

**Q2. Almashtirish uchun dona yo'q bo'lsa — xato, vazifa emas.**
- **Tanlov:** "Hal qilindi" bosilganda yangi dona yetmasa, 409 xato chiqadi, murojaat "Xizmatda" qoladi, daftarga hech narsa yozilmaydi. Menejer dona kelgach qayta bosadi.
- **Nega:** band qilingan mahsulot hech qachon berilmaydi (BL-019), va "yarim hal qilingan" holat paydo bo'lmaydi.
- **Muqobil:** db/support.md dagidek menejerga alohida vazifa ochish (keyingi qadamda qo'shsa bo'ladi).

**Q3. Kafolat muddati tugagan sotuvga murojaat.**
- **Tanlov:** ochish 422 `WARRANTY_EXPIRED` bilan to'xtaydi; menejer/ega sabab yozib ochadi; keyin qabul qilishda izoh ham majburiy.
- **Nega:** operator "doimiy mijoz" deb o'zi istisno qila olmasin; qaror odamda (BL-058, DEC-130).
- **Muqobil:** muddati tugagan ham operator ochsin, faqat ogohlantirish chiqsin (db/support.md Q6 dagi dastlabki variant).

**Q4. "Qaytarish" turi (nuqsonsiz) kafolat muddati bilan bloklanmaydi.**
- **Tanlov:** `RETURN` turida muddat ma'lumot sifatida hisoblanadi, ochish bloklanmaydi.
- **Nega:** qaytarish shartlari kafolatdan boshqa (BL-058); ruxsatni odam beradi.
- **Muqobil:** qaytarish uchun alohida muddat sozlamasi (shop siyosatida) — hozircha yo'q.

**Q5. Rasm turi nomi `SUPPORT_EVIDENCE`.**
- **Tanlov:** db/support.dbml dagi nom. Yuklash ruxsati — `support.case.service` (operator va omborchi ham yuklay oladi).
- **Muqobil:** `WARRANTY_EVIDENCE` yoki umumiy `CASE_ATTACHMENT`. Nomni o'zgartirish bitta migratsiya.

**Q6. Ruxsatlar to'rt darajada.**
- **Tanlov:** ochish — ega, menejer, operator. Izoh, rasm, "mahsulot qabul qilindi", diagnostika, yopish — shularga va omborchiga. Xizmatni boshlash va hal qilish (ombor yozuvi bor) — ega, menejer, omborchi; operator emas. Qabul, rad, qaror turini o'zgartirish, mas'ul biriktirish — faqat ega va menejer.
- **Nega:** business/04 va db/support.md §1. Omborchi mahsulotni jismonan qabul qiladi va beradi, operator esa xaridor bilan gaplashadi.
- **Muqobil:** operator ham "hal qilindi" bossin (xaridorga topshirgan odam). Ombor yozuvi bor amalni operatorga bermaslik xavfsizroq.

**Q7. Ta'mirdan almashtirishga o'tish.**
- **Tanlov:** "Xizmatda" holatida menejer sabab bilan ta'mirni almashtirish yoki qaytarishga o'zgartira oladi; shu paytda qaytgan dona karantinga tushadi. Teskarisi (karantindagi donani ta'mirga qaytarish) taqiqlangan.
- **Nega:** "ta'mirlab bo'lmadi, almashtiramiz" hayotda ko'p; karantindagi donani ta'mirga qaytarsak, ombor raqamlari buziladi.
- **Muqobil:** o'zgartirishga yo'l qo'ymaslik, yangi murojaat ochish.

**Q8. "Qabul qilindi" xabari.**
- **Tanlov:** uchta holat avtomatik (ochildi, qabul qilindi, rad etildi), "tayyor" xabarini xodim tugma bilan yuboradi (bir murojaatga bitta). Diagnostika, xizmat va hal qilish haqida xabar ketmaydi.
- **Nega:** ichki bosqichlar xaridorga kerak emas; "tayyor" xabari mahsulot haqiqatan topshirishga tayyor bo'lganda ketishi kerak.
- **Muqobil:** har holatda avtomatik xabar.

**Q9. Karantindan chiqarish chegarasi.**
- **Tanlov:** `RESTOCK`/`WRITE_OFF` da `support_case_id` berilsa, o'sha murojaat shu SKU'ni shu filialda karantinga yozgan bo'lishi va chiqarilganlar yig'indisi karantinga tushganidan oshmasligi shart. Omborchi so'rovi ham hisobga olinadi.
- **Nega:** birovning donasini yoki ikki marta chiqarishni oldini oladi.
- **Muqobil:** oddiy karantin sonidan tekshirish (murojaatga bog'lamasdan).

**Q10. Tez sotuv qatori javobida `id`.**
- **Tanlov:** tasdiqlangan commerce API'ga bitta maydon qo'shildi (`lines[].id`). Murojaat shu qatordan ochiladi.
- **Nega:** busiz frontend tez sotuv qatorini murojaatga bog'lay olmaydi.
- **Muqobil:** yo'q (zarur).

**Q11. Avtomatik yopish vaqti.**
- **Tanlov:** hal qilinganiga 7 kun o'tsa tizim yopadi, tekshiruv soatiga bir marta. Bu bekor qilish emas, shuning uchun "hech narsa avtomatik bekor qilinmaydi" qoidasiga zid emas.
- **Muqobil:** faqat xodim yopadi (ro'yxat ochiq murojaatlar bilan to'lib ketadi).
