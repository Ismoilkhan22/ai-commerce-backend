# `commerce` — leadlar va PC takliflari (qo'shimcha jadvallar)

> **Holat:** taklif, 2026-10-26. Qarorlar qabul qilingan, chunki founder ishni to'xtatmasdan davom ettirishni topshirgan. **Founder ko'rib chiqishi kutilmoqda.** Qarorlar oxirida. Diagramma: [`commerce_quotes.dbml`](commerce_quotes.dbml) → dbdiagram.io.
> **Kim o'qiydi:** founder va dasturchilar. Har jadval: nima uchun kerak → har maydon nima va nega → bog'lanishlar → misol.
> **Umumiy qoidalar** — [platform.md](platform.md) §0, pul — [catalog.md](catalog.md) §0. Tasdiqlangan [commerce.md](commerce.md) (DEC-134) o'zgarmaydi. Bu fayl uning §12 da va'da qilingan qo'shimchasi.
> **Hajm:** leadlar (FSM-05), PC takliflari (FSM-06), taklifni qabul qilish → DRAFT buyurtma (S3-05, S3-06). Moslik engine'i — kodda (qoidalar Python'da, jadvali yo'q; [17](../17-pc-compatibility-engine.md), [../ai/M06-architecture.md](../ai/M06-architecture.md) §3). AI — [sales_ai.md](sales_ai.md).

Misollarda **"TechPC"** shopi. Ega — **Ali**, menejer — **Vali**, operator — **Dilshod**. Xaridor **Jasur** Telegram'da yozdi: "10 mln gacha CS2 uchun kompyuter kerak".

---

## 0. Bu qo'shimchada yangi narsalar

- **Lead — "bu xaridor sotib olishi mumkin" degan yozuv.** U suhbatdan (AI yoki operator) yoki qo'lda yaratiladi. Ega "qancha odam qiziqdi, qanchasi oldi" degan savolga javob oladi.
- **Taklif — PC yig'ma uchun rasmiy narxli hujjat.** Ichida qismlar, narxlar, jami, muddat va moslik natijasi bor. Oddiy mahsulot taklifsiz, to'g'ridan buyurtma qoralamasiga ketadi (DEC-100e).
- **Versiyalar.** Yuborilgan taklif hech qachon o'zgarmaydi. O'zgarish kerak bo'lsa, yangi versiya ochiladi va eskisi tarixda qoladi (BL-043).
- **Narx AI'dan olinmaydi.** AI faqat "qaysi SKU, nechta" deydi. Narxni `commerce` katalogdan o'zi o'qib, nusxa qiladi (14 §4.6, BL-041).
- **Moslik muzlatiladi.** Har versiyada qaysi qoidalar versiyasi ishlatilgani va natija saqlanadi (BL-030). Xaridor qabul qilganda yana tekshiriladi.

---

## 1. `leads` — sotuv imkoniyati

**Nima uchun kerak:** Jasur "10 mln, CS2" dedi. AI uni lead qilib yozadi: byudjet 10 mln so'm, ish turi o'yin 1080p. Dilshod keyin leadlar ro'yxatida uni ko'radi, xaridor esdan chiqmaydi.

- **`number`** — shop ichida ketma-ket, ekranda "L-57". Hisoblagich `lead_counters` da, xuddi buyurtmalardagidek. Hisoblagich jadvallarida (`lead_counters`, `quote_counters`) RLS yo'q — `order_counters` kabi, ichida faqat shop ID va oxirgi raqam (QA 6a F18).
- **`status`** — FSM-05:
  ```
  Yangi (NEW) ──(byudjet va maqsad aniqlandi)──▶ Aniqlandi (QUALIFIED)
  Yangi / Aniqlandi ──(birinchi taklif yuborildi — avtomatik)──▶ Taklif berildi (QUOTED)
  Yangi / Aniqlandi / Taklif berildi ──(lead buyurtmasi topshirildi — faqat tizim)──▶ Yutildi (WON)
  Yangi / Aniqlandi / Taklif berildi ──(xodim, sabab bilan)──▶ Yo'qotildi (LOST)   [ochiq takliflar bekor]
  Yo'qotildi ──(xaridor qaytdi)──▶ Aniqlandi
  ```
  `NEW → QUOTED` (aniqlashsiz birinchi taklif) va `NEW → LOST` (spam, aloqasiz murojaat) — amaliy o'tishlar
  (QA 6a F9). business/05 FSM-05 da ular yo'q — founder tasdig'i kerak (M06a-quotes §9.4).
- **`source`** — `AI` yoki `STAFF`.
- **`conversation_id`**, **`customer_identity_id`** — qaysi suhbat va qaysi xaridor (`messaging`, FK'siz).
- **`customer_name`**, **`contact_phone_enc`**, **`contact_phone_hmac`**, **`consent_contact_at`** — kontakt **faqat rozilik bilan** saqlanadi (BL-042). Telefon shifrlangan, HMAC orqali shop ichida dublikat qidiriladi. Boshqa shop xaridori bilan hech qachon birlashtirilmaydi.
- **`requirements`** — AI slot'larining nusxasi: byudjet, ish turi, monitor kerakmi, brend afzalligi. Shaxsiy ma'lumot yo'q. **`budget_minor`** saralash uchun alohida ustunga chiqarilgan.
- **`assigned_membership_id`** — mas'ul operator.
- **`lost_reason`** — qimmat, mahsulot yo'q, mos emas, javob bermadi, raqobatchidan oldi yoki boshqa. AI taxmin qilsa, **`lost_reason_inferred = true`** bo'ladi va ekranda "ehtimoliy" deb ko'rsatiladi (business/05).
- **`won_order_id`** — leadni yutgan buyurtma.
- **`merged_into_lead_id`** — operator ikki leadni qo'lda birlashtirsa (Telegram va Instagram'dagi bir odam, M12), eski lead shunga ishora qiladi. Avtomatik birlashtirish yo'q.
- **`ai_request_id`** — AI tool'ining takror kaliti. Worker qayta ishga tushsa ham ikkinchi lead yaratilmaydi.

**Unikal:** bitta suhbatda bitta ochiq lead bo'ladi. AI ikkinchi marta "lead yoz" desa, mavjudi yangilanadi.
**Avtomatik o'tishlar** `commerce` event'lari orqali: taklif SENT → QUOTED, buyurtma COMPLETED → WON. 30 kun jimlikdan keyin rejali ish operatorga "yopilsinmi?" vazifasini beradi, lekin o'zi yopmaydi.
**RLS:** ha.

**Misol:** L-57, Jasur, QUALIFIED, byudjet 10 000 000 so'm, ish turi `GAMING_1080P`, mas'ul Dilshod.

---

## 2. `quotes` — PC taklifi

**Nima uchun kerak:** AI Jasurga 3 ta yig'ma variantini ko'rsatdi, Jasur ikkinchisini tanladi. AI taklif qoralamasini so'raydi, Vali tekshirib tasdiqlaydi, Dilshod uni Jasurga havola qilib yuboradi. Jasur havolani ochib "Qabul qilaman" deydi, tizimda DRAFT buyurtma paydo bo'ladi.

- **`number`** — "T-1042", hisoblagich `quote_counters` da.
- **`lead_id`** — har taklif bir leadga tegishli. Lead yo'q bo'lsa, taklif yaratilganda avtomatik ochiladi.
- **`status`** — FSM-06:
  ```
  Qoralama (DRAFT) ──(AI yoki operator "tekshiruvga")──▶ Tekshiruvda (REVIEW)        [moslik tekshiriladi, BLOCK bo'lsa o'tmaydi]
  Qoralama ──("faqat xavfli holatlar" rejimi: PASS, chegirma yo'q, summa chegaradan kichik)──▶ Tasdiqlandi   [avtomatik, DEC-102]
  Tekshiruvda ──(menejer o'z limiti ichida yoki ega)──▶ Tasdiqlandi (APPROVED)        [narxlar muzlaydi]
  Tekshiruvda ──(menejer qaytardi, sabab bilan)──▶ Qoralama                            [yangi versiya]
  Tasdiqlandi ──(xodim "Yuborish")──▶ Yuborildi (SENT)                                 [havola + suhbatga xabar, muddat boshlanadi]
  Yuborildi ──(xaridor "Qabul qilaman")──▶ Qabul qilindi (ACCEPTED)                    [DRAFT buyurtma]
  Yuborildi ──(muddat tugadi)──▶ Muddati o'tdi (EXPIRED)
  Yuborildi ──(xaridor rad etdi)──▶ Rad etildi (REJECTED)
  Rad etildi / Muddati o'tdi ──(operator qayta ishlaydi)──▶ yangi versiya, Qoralama
  Qoralama / Tekshiruvda / Tasdiqlandi ──(bekor)──▶ Bekor qilindi (CANCELLED)
  ```
  **Kim tasdiqlaydi:** menejer (chegirma limiti ichida, DEC-110) yoki ega. O'zi tuzgan taklifni o'zi tasdiqlay olmaydi (DEC-109). Pilotda har taklif tasdiqdan o'tadi (`shop_policies.quote_approval_mode = ALL`, DEC-102).
  **AI hech qachon tasdiqlamaydi va yubormaydi.** U xaridorga faqat "taklif tayyorlanmoqda, menejer tekshiradi" deydi.
- **`current_revision_id`**, **`current_revision_no`** — oxirgi versiya.
- **`created_by_kind`**, **`created_by`** — `AI` yoki xodim.
- **`public_token_hash`** — xaridor havolasi `/q/{token}`. Bazada faqat sha256 saqlanadi, xuddi buyurtma kuzatuv havolasidek. Havola SENT bo'lganda yaratiladi.
- **`sent_at`**, **`sent_by`**, **`expires_at`** — yuborilgan vaqt, kim yuborgani va muddat. Muddat = yuborilgan vaqt + `quote_ttl_hours` (standart 24 soat, DEC-103).
- **`accepted_at`**, **`accepted_order_id`** — qabul va undan yaratilgan buyurtma.
- **`rejected_*`**, **`reject_reason`**, **`cancelled_at`**.

**Xaridor havolasi** sayt domenida ochiladi (`techpc.platforma.uz/q/{token}`). Unda qismlar, narxlar, jami, muddat va moslik xulosasi (xaridor tilida) ko'rinadi, shuningdek "Qabul qilaman" va "Rad etaman" tugmalari. Telefon va ichki izohlar yo'q.
**RLS:** ha.

---

## 3. `quote_revisions` — taklif versiyasi

**Nima uchun kerak:** taklifning har versiyasi to'liq nusxa. Vali qaytarsa yoki Jasur rad etsa, yangi versiya ochiladi. Eski versiya "nima yuborilgan edi" degan savolga javob bo'lib qoladi.

- **`revision`** — 1, 2, 3…
- **`requirements`** — byudjet va ish turi nusxasi.
- **`exchange_rate_id`**, **`exchange_rate_snapshot`** — dollarli qism bo'lsa, qaysi kurs bilan so'mga o'girilgan.
- **`subtotal_uzs_minor`**, **`discount_uzs_minor`**, **`total_uzs_minor`** — xaridor ko'radigan summalar, so'mda.
- **`compatibility_decision`**, **`ruleset_version`** — muzlagan moslik natijasi va qoidalar versiyasi. To'liq tafsilot `quote_compatibility_snapshots` da.
- **`created_by_kind`**, **`created_by`**, **`ai_turn_id`** — AI qoralamasi bo'lsa, qaysi AI navbatidan chiqqani (audit va baholash uchun).
- **`ai_request_id`** — AI tool'ining takror kaliti.
- **`submitted_at`** — tekshiruvga yuborilgan vaqt. Shu paytdan qatorlar, jami va kurs **o'zgarmaydi** (bazada trigger).
- **`approved_by`**, **`approved_at`**, **`approval_mode`** (`MANUAL` / `AUTO_RISKY_ONLY`), **`approval_note`** — tasdiq. Natija "tekshirish kerak" (REVIEW_REQUIRED) bo'lsa, tasdiqlovchi dalil yozishi **shart**: "BIOS F20 o'rnatilgan, omborda tekshirildi".
- **`returned_note`** — menejer qaytarsa, sababi.

**Narx qayerdan:** qatorlar yaratilganda `commerce` `CatalogQueryPort` orqali joriy narxni o'qiydi. AI yuborgan biror son ishlatilmaydi.
**Qabulda qayta tekshiruv:** Jasur ertaga qabul qilsa, narx va moslik joriy holat bilan solishtiriladi (DEC-127, DEC-134). Narx o'zgargan bo'lsa, havola "narx o'zgardi" deb yangi summani ko'rsatadi va qayta rozilik so'raydi. Buyurtma esa yangi narx bilan yaratiladi.
**RLS:** ha.

---

## 4. `quote_lines` — taklif qatori

- **`position`** — tartib.
- **`role`** — yig'madagi o'rni: CPU, ona plata, RAM, GPU, disk, quvvat bloki, korpus, sovutgich, monitor, periferiya, xizmat yoki boshqa. Katalog toifasidan olinadi.
- **`sku_id`**, **`product_id`**, **`title_snapshot`**, **`sku_code_snapshot`** — nima va qanday nomda.
- **`qty`** — nechta.
- **`price_version_id`**, **`unit_price_minor`**, **`currency`**, **`unit_price_uzs_minor`** — narx o'z valyutasida va so'mda (aniq so'mgacha, DEC-133).
- **`discount_pct`** — faqat xodim qo'yadi. AI chegirma qo'ya olmaydi (DEC-110). Tasdiqlovchining limiti tekshiriladi.
- **`line_total_uzs_minor`**, **`warranty_months`** — summa va kafolat nusxasi.
- **`spec_id`**, **`spec_version`** — qaysi texnik ma'lumot versiyasi bilan tekshirilgani (BL-030).

**Unikal:** bitta versiyada bitta SKU faqat bir qatorda bo'ladi (2 ta RAM kerak bo'lsa, `qty = 2`). Ko'pi bilan 15 qator.

**Misol (T-1042, 1-versiya):** Ryzen 5 7600 (200 $ × 12 850), B650M ona plata, 2×16 GB DDR5, RTX 4060, 1 TB NVMe, 650 W blok, korpus. Jami 9 870 000 so'm, natija PASS.

---

## 5. `quote_compatibility_snapshots` — muzlagan moslik natijasi

**Nima uchun kerak:** "bu yig'ma qachon va qaysi qoidalar bilan tekshirilgan edi?" degan savolga javob. Qoida keyin xato chiqsa, ta'sirlangan takliflarni topish mumkin bo'ladi (17 §9).

- **`stage`** — tekshiruv bosqichi: `SUBMIT` (tekshiruvga yuborishda), `APPROVAL` (tasdiqlashda, faqat ruleset yoki spec o'zgargan bo'lsa), `ACCEPT` (xaridor qabul qilganda).
- **`ruleset_version`**, **`decision`**, **`can_publish`**, **`findings`**, **`spec_versions`**, **`estimated_power_w`** — engine natijasi (17 §7). Tushuntirish matni saqlanmaydi: u kerak bo'lganda xaridor tilida qoida shablonidan qayta yasaladi.

**Faqat qo'shiladi**, o'zgarmaydi. Har bosqichda bitta yozuv.
**Qoida yoki spec o'zgarsa:** yuborilmagan takliflar qayta tekshiriladi. Yuborilgan taklif o'zgarmaydi, lekin qabulda yana tekshiriladi.
**RLS:** ha.

---

## 6. Taklifni qabul qilish → buyurtma

```
Jasur /q/{token} da "Qabul qilaman" ──▶ narx va moslik qayta tekshiriladi (ACCEPT snapshot)
   ├─ farq yo'q ──▶ quote ACCEPTED ──▶ DRAFT buyurtma (source QUOTE, quote_id, quote_revision_id, lead_id)
   │                 qatorlar revision'dan nusxa ──▶ operatorga vazifa; band qilish yo'q (DEC-100b)
   └─ farq bor  ──▶ "narx o'zgardi: 9 870 000 → 9 920 000" ──▶ Jasur yana rozi bo'lsa — yangi narx bilan DRAFT buyurtma
Buyurtmani operator 3-moduldagidek tasdiqlaydi (DEC-134 — tasdiqlashda yana narx tekshiruvi).
```

**`commerce.dbml` ga ta'sir** (tasdiqlangan faylga migratsiyada qo'shiladi):
- `order_source` ga `QUOTE` qo'shiladi;
- `orders.quote_id` va `orders.quote_revision_id` ga FK;
- yangi ixtiyoriy `orders.lead_id`. U AI buyurtma qoralamasida ham to'ldiriladi, shunda lead WON avtomatik bo'ladi.

---

## Bog'lanishlar xaritasi

```
lead_counters        quote_counters
leads ──< quotes ──< quote_revisions ──< quote_lines
  ▲          │              └──< quote_compatibility_snapshots
  └─ merged_into_lead_id     │
                            └─ ─ ▶ orders.quote_revision_id  (qabuldan DRAFT buyurtma)
leads ─ ─ ▶ messaging.conversations / customer_identities     quote_revisions ─ ─ ▶ sales_ai.ai_turns
```

---

## engineering/07 §4.4 dan farqlar

- **`leads`:** `number`, `source`, rozilik bilan kontakt ustunlari (`contact_phone_enc` + HMAC, `consent_contact_at`), `requirements` (JSONB), `lost_reason_inferred`, `won_order_id`, `merged_into_lead_id`, `ai_request_id` qo'shildi. 07 dagi `customer_ref` → `customer_identity_id`.
- **`quotes`:** `CANCELLED` holati qo'shildi (yuborilmagan taklif yangi versiya bilan almashganda), `number`, `conversation_id`, `sent_*`, `accepted_order_id`, `rejected_*` qo'shildi.
- **`quote_revisions`:** jami summalar so'mda (`*_uzs_minor`), `submitted_at` (muzlash nuqtasi), `approval_mode`, `approval_note`, `returned_note`, `ai_turn_id`, `ai_request_id` qo'shildi. 07 dagi `compatibility_snapshot_id` → teskari bog'lanish (snapshot revision'ga ishora qiladi, bosqich bilan).
- **`quote_lines`:** `role`, nom va kod nusxasi, `unit_price_uzs_minor`, `line_total_uzs_minor`, `warranty_months`, `spec_id`/`spec_version` qo'shildi.
- **`quote_compatibility_snapshots`:** `stage` qo'shildi. Bir versiyaga bir nechta bosqich (SUBMIT/APPROVAL/ACCEPT) yoziladi.

---

## Founder ko'rib chiqishi uchun qarorlar

**Q1. Lead kim tomonidan va qachon yaratiladi?**
- **Tanlov:** AI ehtiyoj aniq bo'lganda (`capture_lead`) yoki xodim qo'lda. Bitta suhbatda bitta ochiq lead.
- **Nega:** takroriy leadlar hisobotni buzadi.
- **Muqobil:** har yangi suhbat avtomatik lead. Ro'yxat "salom" yozganlar bilan to'lib ketadi.

**Q2. Lead avtomatik yopiladimi?**
- **Tanlov:** WON avtomatik (buyurtma topshirilganda). LOST faqat xodim yopadi; 30 kun jimlikdan keyin vazifa beriladi.
- **Nega:** "yo'qotildi" sababi odam qarori.
- **Muqobil:** 30 kunda avtomatik LOST (`NO_RESPONSE`).

**Q3. Taklif raqami alohida hisoblagichdami?**
- **Tanlov:** ha, "T-1042" (`quote_counters`), buyurtmalarnikidan alohida.
- **Nega:** xaridor va xodim chalkashmaydi.
- **Muqobil:** UUID ko'rsatish yoki buyurtma raqamini ishlatish.

**Q4. Taklifni xaridorga kim yuboradi?**
- **Tanlov:** faqat xodim ("Yuborish" tugmasi), tasdiqdan keyin. AI yubormaydi.
- **Nega:** DEC-100c ruhi: AI faqat qoralama.
- **Muqobil:** tasdiqlangan taklifni AI o'zi suhbatga yuboradi (AUTO rejimida). Tezroq, lekin xavf ko'proq.

**Q5. Xaridor taklifni qanday qabul qiladi?**
- **Tanlov:** havola (`/q/{token}`, sayt domenida) va "Qabul qilaman" tugmasi. Suhbatda "olaman" desa, AI yoki operator havolani eslatadi yoki xodim qabulni qo'lda belgilaydi.
- **Nega:** aniq rozilik izi va narx o'zgarganda qayta rozilik joyi bo'ladi.
- **Muqobil:** faqat chatdagi "ha" so'zi. Izi noaniq.

**Q6. Qabuldagi narx o'zgarishi.**
- **Tanlov:** qabulda narx va moslik qayta tekshiriladi. Farq bo'lsa, havolada yangi summa ko'rsatiladi va qayta rozilik so'raladi (DEC-127/134 bilan bir xil).
- **Muqobil:** muddat ichida taklif narxi kafolatlanadi. Kurs va narx farqini shop ko'taradi.

**Q7. Moslik natijasi qachon muzlatiladi?**
- **Tanlov:** uch bosqichda yoziladi: tekshiruvga yuborishda, tasdiqlashda (agar ruleset yoki spec o'zgargan bo'lsa) va qabulda.
- **Nega:** 17 §9 va BL-030.
- **Muqobil:** faqat bitta snapshot. Qabuldagi tekshiruv izi qolmaydi.

**Q8. Chegirma taklifda.**
- **Tanlov:** faqat xodim qatorga foiz qo'yadi. Tasdiqlovchining limiti tekshiriladi (DEC-110). Chegirmali taklif "faqat xavfli holatlar" rejimida ham doim qo'lda tasdiqlanadi.
- **Muqobil:** taklif darajasidagi umumiy chegirma. Qator bo'yicha hisob murakkablashadi.
