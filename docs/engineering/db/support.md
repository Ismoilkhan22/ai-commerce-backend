# `support` schemasi — kafolat va qaytarish murojaatlari

> **Holat:** taklif, 2026-10-27. Qarorlar qabul qilingan, chunki founder ishni to'xtatmasdan davom ettirishni topshirgan. **Founder ko'rib chiqishi kutilmoqda.** Qarorlar oxirida. Diagramma: [`support.dbml`](support.dbml) → dbdiagram.io.
> **Kim o'qiydi:** founder va dasturchilar. Har jadval: nima uchun kerak → har maydon nima va nega → bog'lanishlar → misol.
> **Umumiy qoidalar** — [platform.md](platform.md) §0, pul — [catalog.md](catalog.md) §0. Tasdiqlangan [commerce.md](commerce.md) (DEC-134) o'zgarmaydi; kerakli kichik qo'shimchalar §5 da.
> **Hajm:** kafolat murojaatlari (S5-02, M16, FSM-11, DEC-114, DEC-130), qaytgan mahsulot karantini, xaridorga murojaat xabarlari. §6 — 7-modulgacha qolgan xaridor xabarnomalari bo'shliqlari (20).

Misollarda **"TechPC"** shopi. Ega — **Ali**, menejer — **Vali**, operator — **Dilshod**, omborchi — **Bobur**. Filial — **Chilonzor**. Xaridor **Jasur** 2 oy oldin #1042 buyurtmada **"MSI GeForce RTX 4060 Ventus 2X"** oldi (kafolat 12 oy). Endi Telegram'da yozdi: "videokarta o'yinda ekranni o'chiryapti".

---

## 0. Bu schemada yangi narsalar

- **Murojaat — sotuv qatoriga bog'langan.** Kafolat shartlari (necha oy) sotuv paytidagidek nusxadan olinadi (BL-057). Ali bugun kafolatni 6 oyga tushirsa ham, Jasurning 12 oyi qoladi.
- **Uch manba.** Tizimdagi buyurtma qatori, do'kondagi tez sotuv qatori yoki tizimdan oldingi sotuv (chek bo'yicha). Pilotning birinchi oylarida kafolatdagi mahsulotlarning ko'pi tizimdan oldin sotilgan — ular ham daftarda emas, tizimda yuritiladi.
- **Qarorni odam qiladi.** Operator ochadi va ma'lumot yig'adi, qabul yoki rad — faqat menejer yoki ega (DEC-130, BL-058).
- **Ombor faqat commerce'da.** Support qoldiqqa o'zi tegmaydi: o'z tranzaksiyasida commerce port'ini chaqiradi, commerce daftarga yozadi (DEC-126). Quruvda event emas, port tanlandi: holat va daftar bitta COMMIT'da, dona yetmasa butun amal qaytadi. Qaytgan dona "tekshiruvda" (karantin) turadi va sotilmaydi (BL-059, BR-X11).
- **Pul tizimdan tashqarida** (DEC-100). Tizim faqat "qancha qaytarildi" degan ma'lumotni yozadi.

---

## 1. Murojaatning yo'li

```
Yangi (NEW) ──(operator ko'rib chiqishni boshladi, mahsulot qabul qilindi)──▶ Diagnostika (IN_REVIEW)
Diagnostika ──(menejer/ega qabul qildi + qaror turi: ta'mir / almashtirish / qaytarish)──▶ Qabul qilindi (APPROVED)
Diagnostika ──(menejer/ega rad etdi, sabab bilan)──▶ Rad etildi (REJECTED)              [yakuniy]
Qabul qilindi ──(xizmat boshlandi; mahsulot do'konda bo'lishi shart)──▶ Xizmatda (IN_SERVICE)
                 [almashtirish/qaytarish bo'lsa: eski dona karantinga — RETURN_QUARANTINE]
Xizmatda ──(ta'mirlandi / yangi dona berildi / pul qaytarildi — xaridorga topshirildi)──▶ Hal qilindi (RESOLVED)
                 [almashtirish bo'lsa: yangi dona ombordan — WARRANTY_REPLACEMENT]
Hal qilindi ──(xaridor tasdiqladi yoki 7 kun o'tdi)──▶ Yopildi (CLOSED)                   [yakuniy]
```

Bu business/05 FSM-11 ning o'zi. Topshiriqdagi "qabul → diagnostika → qaror → qaytarish" bosqichlari shu holatlarga mos keladi: qabul — `NEW` + `item_received_at`, diagnostika — `IN_REVIEW` + `DIAGNOSIS` izohi, qaror — `APPROVED`/`REJECTED` + `resolution`, xaridorga qaytarish — `RESOLVED`.

**Kim nima qiladi** (ruxsat kodlari — kodda, DEC-131):
- ochish, izoh, rasm, "mahsulot qabul qilindi", diagnostika — ega, menejer, operator; omborchi — qabul va diagnostika (`support.case.open`, `support.case.service`);
- qabul / rad — faqat ega va menejer (`support.case.decide`);
- xizmat va hal qilish — ega, menejer, omborchi.

**AI** murojaat ochmaydi. Xaridor kafolat haqida yozsa, AI operatorga uzatadi (`handoff_reason = WARRANTY`, BL-037), operator suhbatdan murojaat ochadi.

---

## 2. `cases` — murojaat

**Nima uchun kerak:** Dilshod Jasurning suhbatida "Kafolat murojaati" tugmasini bosadi, #1042 dagi RTX 4060 qatorini tanlaydi va muammoni yozadi. Tizim kafolat 12 oy, sotilganiga 2 oy bo'lganini ko'rsatadi: "kafolat ichida". Murojaat K-12 ochiladi, Vali'ga bildirishnoma ketadi.

**Raqam va turi:**
- **`number`** — "K-12", hisoblagich `case_counters` da (buyurtma raqamidan alohida).
- **`type`** — `WARRANTY` ("ishlamayapti") yoki `RETURN` ("qaytarmoqchiman", nuqsonsiz). Qaytarishga ruxsatni har doim odam beradi (BL-058).
- **`status`** — §1.
- **`created_via`** — panel, suhbat yoki buyurtma kartochkasi. Hisobotda "murojaatlar qayerdan keladi" uchun.

**Qaysi sotuv:**
- **`source`** — `ORDER_LINE`, `QUICK_SALE_LINE` yoki `EXTERNAL`.
- **`order_id`, `order_line_id`** — buyurtma va qator. Buyurtma shu shopniki va `COMPLETED` ekanini `CommerceQueryPort.get_order_for_support()` tekshiradi (05 §8.9).
- **`quick_sale_id`, `quick_sale_line_id`** — do'kondagi sotuv. Tez sotuvda xaridor ma'lumoti yo'q, shuning uchun xodim chekni ko'radi va kontaktni qo'lda yozadi.
- **`external_sale_ref`** — tizimdan oldingi sotuv: chek yoki kafolat taloni raqami. Bunday murojaatda qarorni doim menejer qiladi.

**Nima:**
- **`branch_id`** — murojaat qaysi filialda yuritiladi. Karantin shu filial qoldig'iga yoziladi.
- **`sku_id`, `product_id`, `title_snapshot`, `sku_code_snapshot`** — sotuv qatoridan nusxa. `EXTERNAL` da mahsulot katalogda topilmasa `sku_id` bo'sh: unda karantin yozilmaydi, murojaat baribir yuritiladi.
- **`qty`** — odatda 1. Ikki RAM planka ikkalasi ham buzilgan bo'lsa — 2. Bitta qatorga ochilgan ochiq murojaatlar yig'indisi qatordagi sondan oshmaydi (service tekshiradi).
- **`serial_number`** — ixtiyoriy seriya raqami. "Boshqa joydan olingan donani olib keldi" holatini ushlaydi.

**Kafolat:**
- **`sold_at`** — sotuv vaqti: buyurtma topshirilgan vaqt, tez sotuv vaqti yoki chekdagi sana.
- **`warranty_months`** — qatordagi nusxa (BL-057, DEC-114). Katalogdan **o'qilmaydi** (tashqi sotuvda xodim yozadi, bo'sh qolsa SKU'ning joriy qiymati).
- **`warranty_override_reason`, `warranty_override_by`** (7b) — kafolat muddati tugagan sotuvga murojaat faqat menejer/ega sabab bilan ochadi; oddiy holatda ochish 422 `WARRANTY_EXPIRED`. Qaytarish (`RETURN`) turi muddat bilan bloklanmaydi: ruxsatni odam beradi (BL-058).
- **`warranty_until`** — `sold_at + oylar`, shop vaqt zonasida.
- **`within_warranty`** — ochilgan paytda hisoblanadi. `false` bo'lsa ekranda qizil ogohlantirish chiqadi. Qabul qilish mumkin, lekin faqat menejer yoki ega, izoh bilan (M16: "ogohlantiradi, qarorni menejer qabul qiladi").

**Muammo va xaridor:**
- **`problem_description`** — muammo matni. Forma "telefon va manzil yozmang" deb ogohlantiradi; kontakt alohida maydonlarda.
- **`customer_name`**, **`contact_phone_enc`**, **`contact_phone_hmac`** — buyurtmadagidek: telefon shifrlangan, qidiruv HMAC orqali (commerce.md §7). Buyurtmadan avtomatik nusxa olinadi, tez sotuv va tashqi sotuvda xodim yozadi.
- **`customer_identity_id`**, **`conversation_id`** — qaysi xaridor va suhbat. Xaridorga xabarlar faqat suhbat bor bo'lsa ketadi (§4).
- **`customer_locale`** — xabarlar tili.
- **`pii_erased_at`** — xaridor so'rovi bilan ism va telefon tozalangan vaqt.

**Bosqichlar:**
- **`item_received_at`, `item_received_by`** — mahsulot do'konga jismonan topshirildi. Murojaat suhbatda oldin ochilib, xaridor ertaga olib kelishi mumkin. Mahsulotsiz `IN_SERVICE` ga o'tib bo'lmaydi.
- **`diagnosed_at`, `diagnosed_by`** — diagnostika xulosasi yozildi (matni `case_notes` da, `DIAGNOSIS`).
- **`resolution`** — qaror turi: `REPAIR` (ta'mir), `REPLACE` (almashtirish), `REFUND` (qaytarish). Xizmat paytida menejer sabab bilan o'zgartira oladi: "ta'mirlab bo'lmadi, almashtiramiz".
- **`replacement_sku_id`** — almashtirishda beriladigan SKU. Standart — o'sha SKU; model tugagan bo'lsa menejer boshqasini tanlaydi.
- **`decided_by`, `decided_at`, `decision_note`, `reject_reason`** — qaror. Rad etilsa sabab majburiy: muddat tugagan, nuqson topilmadi, mexanik shikast, bu shopniki emas, qaytarish shartiga mos emas yoki boshqa.
- **`service_started_at`**, **`outcome`**, **`resolved_at`**, **`resolved_by`** — hal qilish. `outcome` qaror turiga mos bo'lishi shart (CHECK).
- **`refund_amount_minor`** — qaytarishda xaridorga berilgan summa (so'm). Faqat ma'lumot: pulni shop o'zi beradi. Hisobotda "qaytarishlar" summasi shundan.
- **`closed_at`, `closed_by`** — yopilish. Bo'sh `closed_by` — 7 kundan keyin tizim yopdi.
- **`opened_by`, `assigned_membership_id`** — kim ochdi va kim mas'ul.

**RLS:** ha.

**Misol:** K-12, `WARRANTY`, `ORDER_LINE` (#1042, RTX 4060), Chilonzor, 1 dona, kafolat 12 oy → 2027-08-25 gacha, kafolat ichida. Jasur ertasi kuni videokartani olib keldi: Bobur "qabul qilindi" bosdi (`IN_REVIEW`). Diagnostika: "ventilyator podshipnigi, qizib o'chadi". Vali qabul qildi: `REPLACE`. Bobur xizmatni boshladi — eski dona karantinga. Yangi RTX 4060 Jasurga berildi — `RESOLVED`, `REPLACED`. 7 kundan keyin `CLOSED`.

---

## 3. `case_notes` va `case_attachments`

**`case_notes` — ichki izohlar.** Diagnostika natijasi, xaridor bilan qo'ng'iroq, oddiy izoh (`kind`). Xaridorga ko'rinmaydi. Faqat qo'shiladi, `order_notes` kabi.
**Misol:** `DIAGNOSIS` — "FurMark 5 daqiqa: 92°C, ventilyator 0 RPM. Podshipnik."

**`case_attachments` — rasmlar.** Xaridor chatda yuborgan rasm yoki Bobur olgan surat. Fayl `platform.stored_files` da, private, yangi tur `SUPPORT_EVIDENCE`. Chatdagi rasm nusxalanmaydi, faqat havola qo'shiladi (`source_message_id`). Ko'pi bilan 10 ta.

**`case_counters`** — raqam hisoblagichi, `order_counters` kabi (RLS yo'q).

---

## 4. Ombor bilan bog'lanish

```
Support (IN_SERVICE, REPLACE/REFUND) ──SupportCommercePort.quarantine_returned──▶ commerce StockService
    ──▶ daftar: RETURN_QUARANTINE, tekshiruvda +1 (ref_type SUPPORT_CASE, ref_id = K-12)
    (omborchiga "karantinni ko'rib chiqish" vazifasi — keyingi qadam, 7b da qurilmadi)

Bobur dona tekshiradi:
    ├─ butun (qaytarish, qutisi ochilgan xolos) ──▶ stock_adjustments RESTOCK (support_case_id = K-12)  ──▶ tekshiruvda −1, qoldiq +1
    └─ shikastlangan / nuqsonli               ──▶ stock_adjustments WRITE_OFF (support_case_id = K-12) ──▶ tekshiruvda −1
    Omborchi tuzatishi — har doim menejer tasdig'i bilan (DEC-134), ega/menejer — darhol.

Support (RESOLVED, REPLACED) ──SupportCommercePort.issue_replacement──▶ commerce: WARRANTY_REPLACEMENT, qoldiq −1 (replacement_sku_id)
```

- **Ta'mir (`REPAIR`) omborga kirmaydi.** Bu xaridor mahsuloti: ta'mirlanib, egasiga qaytadi. Uni karantinga yozsak, keyin uni "hisobdan chiqarish" kerak bo'lardi — bu noto'g'ri yozuv. Mahsulot do'kondaligi murojaatning o'zida (`item_received_at`) ko'rinadi.
- **Takror himoyasi** — daftarning unikal kaliti `(reason, ref_type, ref_id, sku_id)`: bir murojaat bir marta karantinga, bir marta almashtirishga yoziladi, event 3 marta kelsa ham.
- **Almashtirish uchun dona yo'q bo'lsa.** "Hal qilindi" bosilganda commerce sotuvga mavjud sonni tekshiradi (qulf ostida). Yetmasa — 409 `INSUFFICIENT_AVAILABLE_STOCK`, murojaat `IN_SERVICE` da qoladi, daftarga hech narsa yozilmaydi; dona kelgach (yoki karantindagi dona `RESTOCK` bo'lgach) amal qaytariladi. "Dona yo'q" vazifasi qurilmadi: xato to'g'ridan-to'g'ri ekranda chiqadi. Sotuvga mavjud son hech qachon manfiy bo'lmaydi (BL-019).
- **Murojaat kartochkasida ombor holati** — `CommerceQueryPort.get_case_stock(case_id)`: karantinda / sotuvga qaytarildi / hisobdan chiqarildi / almashtirish yozildi.
- **AI karantindagi donani "bor" demaydi** — u faqat sotuvga mavjud songa qaraydi, karantin unga kirmaydi (M16 qabul mezoni).

---

## 5. `commerce.dbml` ga ta'sir

Tasdiqlangan faylga migratsiyada qo'shiladi (commerce_quotes.md §6 dagi kabi):
1. `ledger_reason` ga **`WARRANTY_REPLACEMENT`** — kafolat bo'yicha yangi dona berildi: qoldiq −qty, `ref_type = SUPPORT_CASE`. `ref_type` da `SUPPORT_CASE` allaqachon bor.
2. `stock_adjustments` ga ixtiyoriy **`support_case_id`** (FK'siz) va indeks `(shop_id, support_case_id)`.
3. `CommerceQueryPort` ga `get_quick_sale_for_support()` va `get_case_stock()`.
4. `platform.file_purpose` ga `SUPPORT_EVIDENCE`.

**05 §8.5 event payload'lariga qo'shimcha** (05 ni tegishli muallif yangilaydi): `support.case.status_changed` va `support.case.resolved` ga `type`, `resolution`, `qty`, `replacement_sku_id?`, `branch_id` (majburiy). Commerce faqat shu maydonlar bilan qaror qiladi: `IN_SERVICE` + `REPLACE/REFUND` + `sku_id` → karantin; `REPAIR` → hech narsa.

---

## 6. Xaridor xabarnomalari: 7-modul va Stage 1 uchun qolgan bo'shliqlar

5b da qurilgan: `customer.order_confirmed`, `customer.order_ready_pickup`, `customer.order_completed`, `customer.order_cancelled`, `customer.handoff_after_hours`. 6b da AI uzatishda o'zi "operator tez orada javob beradi" deydi. Yangi jadval kerak emas: kalit — `customer_templates.py` da, yozuv — `platform.notifications` da (notifications.md). Faqat bo'shliqlar:

**Yangi kalitlar (quriladi):**
- **`customer.support_case_opened`** — "Murojaatingiz K-{case_number} qabul qilindi.{item_line} Natija haqida shu yerga yozamiz." `{item_line}` — " Mahsulot: …." (tashqi sotuvda bo'sh: u xodim yozgan erkin matn). Murojaat ochilganda.
- **`customer.support_case_approved`** (7b da "qabul qilindi" xabari) — "K-{case_number}: murojaatingiz qabul qilindi — {resolution_line}." `{resolution_line}`: ta'mirlaymiz / almashtiramiz / qaytarishni rasmiylashtiramiz.
- **`customer.support_case_rejected`** — "K-{case_number}: afsuski, kafolat bo'yicha qabul qilib bo'lmadi. {reason_line}Savollar bo'lsa, shu yerga yozing." Sabab matni — rad sababi kodidan, xaridor tilida; erkin izoh ketmaydi.
- **`customer.support_case_ready`** — "K-{case_number}: mahsulotingiz tayyor. Manzil: {shop_address}. {phone_line}" Ta'mir yoki almashtirish tugaganda, xaridorga topshirishdan oldin xodim "Xaridorga xabar berish" bosadi.
  Shu bilan murojaat holatlari xaridorga 4 ta xabar bilan yetadi. Niyat kaliti `support:{case_id}:{template}` — bir holatga bitta xabar (BL-060).
- **`customer.price_changed`** — 20 da bor, kodda yo'q. Buyurtma tasdiqlashda `PRICE_CHANGED` chiqqanda operator "Xaridorga yuborish" ni bosadi. Niyat kaliti `price:{order_id}:{order_version}`.
- **`customer.quote_expired`** — taklif muddati tugaganda, suhbat bo'lsa, bitta xabar.
- **`customer.ai_greeting`** — faqat AI `AUTO` rejimida, yangi suhbatning birinchi xabariga: xaridor AI bilan gaplashayotganini bilishi kerak. AI o'chiq bo'lsa salom yo'q, operator o'zi yozadi.
- Instagram izohlari uchun ikki kalit — [instagram_comments.md](instagram_comments.md) §5.

**Ataylab qurilmaydi (qaror):**
- `customer.order_processing` — M17 ro'yxatida yo'q, "tasdiqlandi" va "tayyor" orasida ortiqcha shovqin.
- `customer.order_received` — AI qoralamasida AI javobining o'zi buni aytadi (BR-X14). Saytdan kelgan so'rovda suhbat yo'q, xaridor tasdiq sahifasini va kuzatuv havolasini ko'radi.
- `customer.quote_sent` avtomatik emas — 6a qarori: havolani operator yuboradi. Faqat inbox'da "Taklifni yuborish" bosilganda matn shablondan tayyor bo'lib chiqadi (front, jadval yo'q).
- Suhbatsiz buyurtma va murojaatga SMS — Stage 2.

**Xodimga yangi vazifa turlari** (`staff_tasks.type`, kodda): `SUPPORT_CASE_DECISION` (diagnostika yozildi → menejer/ega), `SUPPORT_QUARANTINE_REVIEW` (karantindagi dona → omborchi, menejer), `SUPPORT_REPLACEMENT_FAILED` (dona yo'q → menejer), `SUPPORT_CASE_STALE` (3 kun harakatsiz → mas'ul). Bildirishnoma `staff.support_case_opened` 20 da bor.

---

## 7. Hayot sikli va shaxsiy ma'lumot

- Murojaat o'chirilmaydi. Xaridor so'rasa (`platform.privacy.erasure_requested`) — `customer_name`, `contact_phone_*` tozalanadi, `pii_erased_at` yoziladi. Izohlarda telefon bo'lishi mumkin: ular ham shu so'rovda telefon naqshi bo'yicha maskalanadi.
- Saqlash muddati — buyurtmalar bilan bir xil, huquqshunos bilan aniqlanadi (26 §5).
- Event payload'larida faqat ID, holat va kodlar. Ism, telefon, muammo matni — yo'q.
- `RESOLVED` dan 7 kun o'tsa rejali ish `CLOSED` qiladi (FSM-11: "muddat o'tdi"). Bu bekor qilish emas, shuning uchun "hech narsa avtomatik bekor qilinmaydi" qoidasiga zid emas.

---

## Bog'lanishlar xaritasi

```
case_counters (har shopga bitta qator)
cases ──< case_notes
  └────< case_attachments ─ ─ ▶ platform.stored_files (SUPPORT_EVIDENCE)
cases ─ ─ ▶ commerce.orders / order_lines / quick_sales / quick_sale_lines   (sotuv manbai)
cases ─ ─ ▶ messaging.conversations / customer_identities                    (xaridorga xabar)
commerce.stock_ledger.ref_id (ref_type SUPPORT_CASE) ─ ─ ▶ cases           (karantin, almashtirish)
commerce.stock_adjustments.support_case_id ─ ─ ▶ cases                    (RESTOCK / WRITE_OFF)

──<  bir → ko'p (FK, shop_id bilan)      ─ ─▶  ishora, FK'siz (boshqa schema)
```

---

## engineering/07 §4.8 dan farqlar

- `source`, `quick_sale_*`, `external_sale_ref` qo'shildi (tez sotuv va tizimdan oldingi sotuv).
- `warranty_snapshot` (JSONB) → `warranty_months` + `warranty_until` + `within_warranty`: commerce'da kafolat faqat oy sifatida saqlanadi.
- Ledger sababi `RETURN_RESTOCK` → commerce'dagi `RESTOCK` tuzatishi (commerce.md da nom allaqachon shunday). `WARRANTY_REPLACEMENT` qo'shildi.
- `case_notes`, `case_attachments`, `case_counters` qo'shildi; xaridor kontakti shifrlangan ustunlarda.
- DEC-114 da "`modules/fulfillment` ichida" deyilgan; 07 va 27 da `support` domeni. Shu yerda `support` tanlandi (27 S5-02 bilan mos).

---

## Founder ko'rib chiqishi uchun qarorlar

**Q1. Murojaat qaysi sotuvdan ochiladi?**
- **Tanlov:** buyurtma qatori, tez sotuv qatori va tizimdan oldingi sotuv (chek raqami bilan, doim menejer qarori).
- **Nega:** PC shopda sotuvning katta qismi do'konda bo'ladi; pilotning birinchi oylarida kafolatdagi mahsulotlarning deyarli hammasi tizimdan oldin sotilgan.
- **Kamchilik:** tez sotuv va tashqi sotuvda xaridorni tizim tasdiqlay olmaydi — xodim chekni ko'radi.
- **Muqobil:** faqat buyurtma qatori (07, M16). Sodda, lekin murojaatlarning ko'pi daftarda qoladi.

**Q2. FSM-11 o'zgaradimi?**
- **Tanlov:** yo'q. Diagnostika — `IN_REVIEW` ichida (`item_received_at`, `DIAGNOSIS` izohi), qaror turi — `resolution` maydoni.
- **Nega:** business/05 ga tegmaymiz, holatlar soni kam qoladi.
- **Muqobil:** alohida `RECEIVED`, `DIAGNOSTICS` holatlari. Aniqroq, lekin business/05 ni o'zgartirish kerak.

**Q3. Ta'mirdagi mahsulot karantinga yoziladimi?**
- **Tanlov:** yo'q. Karantin faqat almashtirish va qaytarishda — dona shopga qaytganda.
- **Nega:** ta'mirdagi mahsulot xaridorniki. Uni qoldiqqa yozish keyin soxta "hisobdan chiqarish"ni talab qiladi.
- **Muqobil:** 07 §4.8 dagidek har `IN_SERVICE` da karantin. Hamma narsa bir xil, lekin ombor raqamlari buziladi.

**Q4. Almashtirishda yangi dona qanday chiqadi?**
- **Tanlov:** yangi daftar sababi `WARRANTY_REPLACEMENT` (commerce'ga kichik qo'shimcha), event orqali.
- **Nega:** hisobotda sotuv va sanoq farqidan alohida ko'rinadi; takror himoyasi daftar kaliti bilan.
- **Muqobil:** omborchi qo'lda `ADJUSTMENT −1` qiladi. Commerce o'zgarmaydi, lekin unutiladi va sabab erkin matnda qoladi.

**Q5. Murojaatlar `support` domenidami yoki commerce ichidami?**
- **Tanlov:** alohida `support` (07, 27).
- **Nega:** commerce allaqachon katta; murojaat qoldiqqa kam ta'sir qiladi.
- **Kamchilik:** almashtirish event orqali, kam holatda "dona yo'q" vazifasi bilan tugaydi.
- **Muqobil:** commerce ichida — almashtirish bitta tranzaksiyada, lekin commerce yana o'sadi.

**Q6. Kafolatdan tashqari murojaat.**
- **Tanlov:** ochish mumkin, ogohlantirish bilan. Qabul qilish faqat menejer/ega va izoh bilan.
- **Nega:** M16 "Nima noto'g'ri ketishi mumkin" jadvali.
- **Muqobil:** muddat tugagan bo'lsa ochib bo'lmaydi. Doimiy mijozga istisno qilib bo'lmaydi.

**Q7. Pul qaytarish summasi yoziladimi?**
- **Tanlov:** ha, ixtiyoriy `refund_amount_minor`, faqat ma'lumot uchun.
- **Nega:** hisobotda sof sotuv va foyda to'g'ri chiqadi (reporting.md).
- **Muqobil:** yozilmaydi (DEC-100 ga qat'iy). Sotuv summasi qaytarishlarsiz ko'rinadi.

**Q8. Avtomatik yopish.**
- **Tanlov:** `RESOLVED` dan 7 kun keyin `CLOSED`.
- **Muqobil:** faqat xodim yopadi. Ro'yxat ochiq murojaatlar bilan to'lib ketadi.

**Q9. Xaridorga murojaat xabarlari.**
- **Tanlov:** 4 ta (ochildi, qabul qilindi, rad etildi, tayyor), faqat suhbat bo'lsa. "Tayyor" xabarini xodim bosadi.
- **Muqobil:** har holatda avtomatik xabar. Ichki holatlar (diagnostika) xaridorga kerak emas.

**Q10. Qolgan xaridor xabarnomalari (§6).**
- **Tanlov:** quriladi — `price_changed`, `quote_expired`, `ai_greeting` (faqat AI yoqiq). Qurilmaydi — `order_processing`, avtomatik `order_received` va `quote_sent`, SMS.
- **Nega:** M17 ro'yxati va 6a qarori; AI bilan gaplashayotganini xaridor bilishi kerak.
- **Muqobil:** 20 dagi matritsa to'liq. Shovqin ko'payadi, 6a qarori buziladi.
