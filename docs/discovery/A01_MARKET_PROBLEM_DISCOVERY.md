# A01 — Bozor va muammo tadqiqoti: PC va elektronika shoplari

**Versiya:** v2 (2026-10-22, oddiy tilda qayta yozildi). **Holat:** qoralama — bu tadqiqot rejasi, natijalar hali yo'q.
**Kim qaror qiladi:** loyiha asoschisi.
**Bog'liq hujjatlar:** `../business/01` (g'oya), `../business/02` (modullar), `../business/13` (shopni ulash), `../business/14` (pilot kelishuvi va narxlar).

## 0. Bu hujjat nima uchun

Biz birdaniga umumiy bozor (marketplace) qurmaymiz. Avval **PC yig'adigan va elektronika sotadigan shoplarda haqiqiy, pulga ta'sir qiladigan muammo**ni topamiz. Keyin shunday shop uchun savdo tizimini quramiz: katalog, narx, ombor, sayt, AI sotuvchi, leadlar, takliflar, buyurtmalar, operatorga uzatish va hisobotlar.

> **Muhim:** quyidagi muammolar, raqamlar va g'oyalar hozircha **faraz**. Hali birorta shop bilan suhbat bu hujjatga kiritilmagan. Farazni fakt sifatida ishlatmaymiz.

### Javob topishimiz kerak bo'lgan 5 savol

1. Shopda qaysi muammo tez-tez uchraydi va haqiqatan pul yoki vaqt yo'qotadi?
2. Boshlash uchun eng kuchli taklif qaysi: kecha-kunduz AI chat, PC taklifi va moslik tekshiruvi, katalog va ombor — yoki ularning kichik birikmasi?
3. Kamida 3 ta shop ishonchli katalog va narxlarini berib, pilotda qatnashishga tayyormi?
4. Sinovdan keyin shop oylik to'lashi uchun qanday o'lchanadigan natija ko'rishi kerak?
5. Pilot shoplar uchun Telegram, Instagram va boshqa rasmiy integratsiyalardan qaysilari amalda mumkin?

## 1. Nimani tekshiramiz

| Mavzu | Tekshiramiz | Birinchi pilotda va'da qilmaymiz |
|---|---|---|
| Shop | PC yig'ish, videokarta, protsessor, xotira, disk, elektronika; filiallar va xodimlar | Hamma turdagi shoplarni birdan qamrash |
| Kanallar | Telegram, Instagram, saytdagi chat, telefon, mavjud sayt | Istalgan platformani ruxsatsiz avtomatlashtirish |
| Katalog | Mahsulotlar, variantlar, narx, ombor, yetkazib beruvchi, fayldan yuklash | Tekshirilmagan ma'lumotni "aniq" deb aytish |
| AI | Savollarga javob, ehtiyojni aniqlash, PC tavsiya, taklif qoralamasi, operatorga uzatish | Narx, to'lov yoki qoldiqni o'zicha tasdiqlash |
| Savdo | Lead → taklif → buyurtma → topshirish | O'z kuryerlarimiz, platforma orqali to'lov |
| Shop paneli | Katalog, inbox, buyurtmalar, hisobotlar, tayyor sayt | Birinchi kundan to'liq hisob dasturi o'rnini bosish |
| Kelajakdagi tarmoq | Shop o'z takliflarini ommaviy qilishga tayyormi? | Narxlarni solishtirishni 1-bosqichda ishga tushirish |

### Uch bosqich bilan bog'liqligi (BD-01)

- **Stage 1 — shop uchun savdo tizimi:** birinchi daromad keltiradigan, bitta shop uchun tizim.
- **Stage 2 — shoplar tarmog'i:** shop o'zi ulanadi, integratsiyalar, umumiy katalog, ommaviy takliflar (rozilik bilan).
- **Stage 3 — global AI qidiruv:** turli shoplarning narx, kafolat, joylashuv va qoldiqlarini solishtirish.
- Platforma orqali to'lov va logistika, ulgurji savdo, qishloq xo'jaligi — **uch bosqichga kirmaydi** (`business/11` §4).

**A01 asosan Stage 1 ni tekshiradi.** Stage 2 va 3 bo'yicha faqat kelajakka ta'sir qiladigan savollarni beramiz.

## 2. Kimlar bilan gaplashamiz

| Kim | Nima ish qiladi | Qaysi muammosini tekshiramiz | Biz nima bera olamiz |
|---|---|---|---|
| Shop egasi | Foyda, xodimlar, savdo nazorati | Yo'qotilgan mijoz, noaniq statistika, samarasiz ish | Ko'proq tasdiqlangan buyurtma, tejalgan vaqt |
| Sotuv menejeri yoki operator | Xabarlarga javob, ehtiyojni aniqlash, qayta bog'lanish | Takroriy savollar, kech javob, unutilgan xaridor | AI yordamchi, inbox, eslatmalar |
| PC yig'uvchi usta | Qismlar mosligi, yig'ma tuzish | Har PC taklifini qo'lda yig'ish | PC yig'ish va moslik tekshiruvi |
| Omborchi | Qoldiq va narxni dolzarb saqlash | Excel, kassa dasturi va yetkazib beruvchi ma'lumotlari mos kelmasligi | Katalog va ombor bir joyda |
| Xaridor | Narx va mos yig'mani topish | Instagram → Telegram → menejer o'rtasida sarson bo'lish | Tez va tekshirilgan taklif |

**Birinchi ideal mijoz (faraz):** ko'p maslahat talab qiladigan PC shop; xaridorlardan ko'p xabar keladi; katalog va narxlarni faylga chiqara oladi; takliflarni tasdiqlaydigan menejeri bor; egasi pilot natijasini o'lchashga tayyor.

> Obunachilar soni yoki Instagram sahifasining chiroyliligi yetarli mezon emas.

## 3. Farazlar ro'yxati

| ID | Faraz | Qanday dalil yig'amiz | Nima rad etadi | Mumkin bo'lgan yechim |
|---|---|---|---|---|
| HYP-001 | Kech javob tufayli xaridorlar yo'qoladi | Oxirgi 7–14 kunlik xabarlar, javob vaqti, real misollar | Hammaga tez javob beriladi va xabarlar kam | AI birinchi javob + operatorga uzatish |
| HYP-002 | PC yig'ma uchun narxli taklif tayyorlash ko'p vaqt oladi | Taklif tuzishni kuzatish va vaqtini o'lchash | Takliflar allaqachon tez tayyorlanadi | PC taklif tuzish vositasi |
| HYP-003 | Narx va qoldiq turli joylarda tarqoq | Excel, kassa, yetkazib beruvchi, chat xaritasi; mos kelmagan qiymatlar | Yaxshi ishlaydigan yagona manba bor | Katalogni yuklash va sinxronlash |
| HYP-004 | Xaridorlar kuzatuvsiz qolib ketadi | Javobsiz yoki unutilgan suhbatlar | Ishlaydigan qayta bog'lanish tizimi bor | Leadlar ro'yxati + eslatmalar |
| HYP-005 | Ish vaqtidan tashqari ham talab bor | Kechasi va dam olish kunlari kelgan jiddiy so'rovlar | Bunday so'rovlar juda kam | Kecha-kunduz AI — faqat foydasi bo'lsa |
| HYP-006 | Saytsiz shopga tayyor sayt kerak | Sayt bormi, katalogni ulashishda muammo bormi | Mavjud sayt yetarli | Avtomatik sayt |
| HYP-007 | Ovozli hisobot uchun pul to'lashadi | Ega qaysi raqamlarni so'raydi, ovozni ishlatarmidi | Ovoz kerak emas deyishadi | Keyinroq, qo'shimcha xizmat sifatida |
| HYP-008 | Shop kelajakda takliflarini ommaviy qiladi | Rozilik, qaysi ma'lumotlar ochiq bo'lishi mumkin, raqobatchidan xavotir | Narx solishtirishga qarshi | Faqat rozilik bilan chiqarish |
| HYP-009 | Aniqlik "aqlli" chatbotdan muhimroq | Noto'g'ri narx yoki qoldiq tufayli muammolar | Dalil yo'q (baribir noto'g'ri ma'lumot bermaymiz) | Aniq qoidalar + odam tasdig'i |
| HYP-010 | Shop pul to'lashga tayyor | Qaror qiluvchi bilan pullik davom etish sharti | "Zo'r g'oya" deyishadi, lekin majburiyat olishmaydi | Tarif va doirani qayta ko'rish |

Har faraz holati: **tekshirilmagan**, **tasdiqlandi**, **aralash**, **rad etildi**. Holat faqat dalil (`EVD-###`) bilan o'zgaradi. Qarama-qarshi misollar ham saqlanadi.

## 4. Tadqiqot rejasi

### 4.1 Kimni tanlaymiz

**Maqsad:** 15–20 ta shopga murojaat qilish, 8–12 ta jiddiy suhbat o'tkazish, ulardan 3–5 ta pilot nomzod. Bu reja, natija emas.

Turli shoplar bo'lishi kerak:
- PC yig'uvchilar va faqat qism sotuvchilar;
- asosan Instagram'da, asosan Telegram'da va asosan saytda sotuvchilar;
- kichik jamoali va bir nechta sotuvchi yoki filiali borlar;
- Excel bilan va kassa yoki hisob dasturi bilan ishlaydiganlar;
- tayyor PC va buyurtma asosida yig'ishni aralashtiradiganlar.

### 4.2 Suhbat qoidalari

1. "Bizning AI sizga kerakmi?" deb so'rashdan oldin hozir qanday ishlashini bilib olamiz.
2. Oxirgi **haqiqiy** holatlarni so'raymiz, "kelajakda nima qilardingiz" degan taxminlarga tayanmaymiz.
3. Vaqt va hajmni iloji bo'lsa o'zimiz kuzatamiz; ko'rmagan raqamni "taxmin" deb belgilaymiz.
4. Chat namunalarini faqat ruxsat bilan olamiz; telefon, manzil, ism, karta, chek kabi shaxsiy ma'lumotlarni yashiramiz. Ruxsatsiz xom ma'lumotni tashqi AI xizmatiga yubormaymiz.
5. Rasman tasdiqlanmagan Instagram yoki to'lov imkoniyatlarini va'da qilmaymiz.
6. Har suhbat oxirida bitta aniq keyingi qadamni kelishamiz: fayl namunasi, demo sanasi, pilot uchun mas'ul odam yoki rad javobi.

### 4.3 30 daqiqalik suhbat tartibi

| Vaqt | Nima haqida |
|---|---|
| 0–5 daqiqa | Shop qanday ishlaydi: filiallar, jamoa, sotuv kanallari |
| 5–15 daqiqa | Oxirgi haqiqiy savdo va yo'qotilgan yoki kechikkan xaridor |
| 15–22 daqiqa | Katalog, taklif tuzish, ombor, narx, to'lov |
| 22–27 daqiqa | Vaqt va pulga ta'siri, hozirgi dasturlar, nimaga pul to'lashga tayyor |
| 27–30 daqiqa | Demo yoki pilotga tayyorlik, ma'lumot berish shartlari |

## 5. Shoplarga beriladigan 22 ta savol

**Savdo va xabarlar**
1. Asosiy mahsulotlaringiz qaysilar? Buyurtma asosida PC yig'ish qancha qismini tashkil qiladi?
2. Kuniga yoki haftasiga nechta **haqiqiy savdo so'rovi** keladi va qayerdan?
3. Oxirgi xaridor yozganidan buyurtmagacha qanday qadamlar bo'lganini ko'rsata olasizmi?
4. Qaysi savollar ko'p takrorlanadi? Javob berishning qaysi qismi eng ko'p vaqt oladi?
5. Ish vaqtidan tashqari yozganlarga nima bo'ladi?

**PC yig'ish, narx, yetkazib beruvchi**
6. Xaridor byudjetini aytgandan keyin taklif tayyorlash necha daqiqa oladi? Oxirgi uchta misolni ko'rsata olasizmi?
7. Protsessor, ona plata, xotira, quvvat bloki, korpus va BIOS mosligini kim tekshiradi?
8. Narxlar qayerda saqlanadi, qanchalik tez-tez o'zgaradi, dollar kursi ishlatiladimi?
9. Sizda yo'q qismni yetkazib beruvchidan yoki boshqa filialdan olib kelasizmi? Haqiqiy qoldiq qayerdan ma'lum bo'ladi?
10. Xaridorga berilgan narxli taklif qancha muddat amal qiladi va uni kim yakuniy tasdiqlaydi?

**Xaridorlar, ombor, buyurtmalar**
11. Xabarlarga kim javob beradi? Suhbat boshqa menejerga qanday o'tkaziladi?
12. Oxirgi marta xaridor unutilib qolganda nima bo'lgan? Buni qanday bilib qoldingiz?
13. Qoldiqning asosiy manbai nima: Excel, kassa dasturi, yetkazib beruvchi chati yoki boshqa?
14. Oxirgi bitta mahsulotga ikki xaridor buyurtma bersa nima qilasiz? Band qilib qo'yasizmi?
15. Buyurtma, bekor qilish, qaytarish, kafolat, yetkazish holatlarini qayerda yuritasiz?
16. Xaridor to'laganini qanday tasdiqlaysiz? Chek rasmi yetarlimi yoki pul tushganini tekshirasizmi?

**Qaror va pul**
17. Qaysi dasturlardan voz kechishni istamaysiz? Ulardan ma'lumotni faylga chiqarsa yoki ulansa bo'ladimi?
18. Sotuvchi kuniga takroriy savollarga taxminan qancha vaqt sarflaydi? Buni o'lchash mumkinmi?
19. Har kuni bilishni xohlaydigan 3 ta raqamingiz qaysi? Ovoz bilan so'rash qulaymi yoki yozma hisobotmi?
20. Faqat bitta jarayonni tezlashtira olsak, qaysi birini tanlardingiz? Nega?
21. Yangi xizmatni sotib olishga kim qaror qiladi? 30 kunlik pilotdan keyin pul to'lashingiz uchun nima bo'lishi kerak?
22. Kelajakda mahsulotlaringiz boshqa shoplar bilan narx solishtirishda ko'rinishiga rozimisiz? Qaysi ma'lumotlar ochiq bo'lishi mumkin?

**Qo'shimcha savollar:** "Oxirgi marta qachon bo'lgan?", "Ekranda ko'rsata olasizmi?", "Qancha vaqt ketdi?", "Kim tasdiqladi?", "Nima noto'g'ri ketdi?"

## 6. Kuzatiladigan savdo jarayoni

Har shopda quyidagi yo'lni kuzatamiz va qayerda uzilishini belgilaymiz:

```
Xaridor yozdi ──▶ Kimdir ko'rdi va javobgar belgilandimi?
                     ├─ Yo'q ──▶ Javobsiz yoki kechikkan xaridor
                     └─ Ha ──▶ Byudjet va ehtiyoj aniqlanadi
                               ──▶ Narx va qoldiq ishonchlimi?
                                     ├─ Yo'q ──▶ Menejer yoki yetkazib beruvchi tekshiradi ──┐
                                     └─ Ha ─────────────────────────────────────────────────┴──▶ Taklif tayyorlanadi
                                                                                                    ──▶ Xaridor rozimi?
                                                                                                          ├─ Yo'q ──▶ Sababi, qayta bog'lanish
                                                                                                          └─ Ha ──▶ Band qilish, to'lov
                                                                                                                    ──▶ Buyurtma tasdiqlandi
                                                                                                                    ──▶ Olib ketish yoki yetkazish
                                                                                                                    ──▶ Berildi / qaytarildi / fikr
```

Har shopda e'tibor beramiz: xabar qaysi kanaldan keldi, necha marta boshqa odamga o'tdi, taklif qancha vaqtda tayyorlandi, nima qo'lda ko'chirildi, narx qayerdan olindi, mahsulot band qilindimi, to'lov qanday tasdiqlandi, oxirgi holat nima bo'ldi.

### Dalillarni qanday yozib boramiz

| Maydon | Nima yoziladi |
|---|---|
| `evidence_id` | `EVD-001` |
| `shop_code` | `S-001`; roziliksiz haqiqiy shop nomini ochiqlamaymiz |
| `date`, `role` | Sana; kim bilan gaplashildi (ega, operator, omborchi) |
| `source_type` | Suhbat / kuzatuv / shaxsiy ma'lumoti yashirilgan chat / ruxsat bilan olingan fayl |
| `finding` | Aynan nima ko'rildi — izoh emas, fakt |
| `related_hypothesis` | `HYP-001` va h.k. |
| `confidence` | Past / o'rta / yuqori va nega |
| `counter_evidence` | Qarama-qarshi misol |
| `privacy_and_consent` | Rozilik, nima yashirildi, qancha saqlanadi |
| `next_validation` | Keyin qanday dalil kerak |

**Dalil kuchi:** kuzatilgan haqiqiy ish yoki fayl — kuchli; yaqinda bo'lgan batafsil misol — o'rta; umumiy fikr — zaif.

## 7. Asosiy ko'rsatkichlar

Pilotdan oldin va pilot davomida shu ko'rsatkichlarni o'lchaymiz:

| ID | Ko'rsatkich | Qanday o'lchanadi | E'tibor bering |
|---|---|---|---|
| KPI-001 | Savdo so'rovlari soni | Takror va spamsiz, jiddiy so'rovlar | Xabarlar soni emas, alohida so'rovlar |
| KPI-002 | Birinchi javob vaqti (o'rtacha va eng sekin 10%) | Birinchi mazmunli javobgacha vaqt | Avtomatik "salom" hisoblanmaydi |
| KPI-003 | Sifatli lead ulushi | Byudjeti, maqsadi va kontakti aniq leadlar | Mezon oldindan kelishiladi |
| KPI-004 | Taklif tayyorlash vaqti | Ma'lumot yetarli bo'lgandan yuborilgunga qadar | Tayyor PC va buyurtma yig'ma alohida |
| KPI-005 | Taklifdan buyurtmaga o'tish | Tasdiqlangan buyurtmalar / takliflar | Vaqt bo'yicha guruhlab |
| KPI-006 | Haqiqiy buyurtmalar | Topshirilgan buyurtmalar | Hammasini AI'ga yozib qo'ymaslik |
| KPI-007 | Noto'g'ri narx yoki qoldiq holatlari | Xaridorga noto'g'ri ma'lumot berilgan holatlar | Maqsad — nol |
| KPI-008 | Xodim vaqti | Ish vaqti namunasi | O'zi aytgan raqam noaniq bo'lishi mumkin |
| KPI-009 | Shopga qo'shimcha foyda | Qo'shimcha savdodan foyda, xarajatlarni ayirib | Foydani o'ylab topmaslik |
| KPI-010 | Bitta AI suhbat narxi | AI + ovoz + server + kanallar xarajati | Oylik to'lov bilan solishtiriladi |
| KPI-011 | Operatorga uzatish ulushi | Operatorga o'tgan suhbatlar / AI suhbatlari | Juda past bo'lishi ham xavfli |
| KPI-012 | Katalog yangiligi | Tekshirilgan narx va qoldiq ulushi | Yetkazib beruvchi qoldig'i alohida |

Iloji bo'lsa pilotdan **7–14 kun oldin** boshlang'ich o'lchov, pilot davomida **2–4 hafta** o'lchov olamiz. Boshqa reklama kampaniyalari ta'sirini hisobga olmasdan "AI savdoni oshirdi" demaymiz.

### Shoplar jadvali (hali to'ldirilmagan)

| Shop | So'rov/kun | Taklif vaqti | Katalog manbai | Qaror qiluvchi | Pilot | Dalil | Holat |
|---|---|---|---|---|---|---|---|
| S-001 | — | — | — | — | — | — | Kutilmoqda |
| S-002 | — | — | — | — | — | — | Kutilmoqda |
| S-003 | — | — | — | — | — | — | Kutilmoqda |

## 8. Pilot shopni saralash (100 ballik)

| Mezon | Ball | Qanday tekshiriladi |
|---|---:|---|
| Muntazam keladigan savdo so'rovlari | 20 | Kuzatilgan yoki hujjatlangan hajm |
| Ishonchli katalog, narx va qoldiqni olish imkoniyati | 25 | Fayl namunasi yoki ko'rsatib berish |
| Ega yoki menejerning vaqti va qaror qilish huquqi | 20 | Pilot uchun mas'ul odam, haftalik fikr |
| Haqiqiy, qimmatga tushadigan muammo va o'lchanadigan ko'rsatkich | 20 | Dalil, boshlang'ich o'lchov |
| Rasmiy integratsiya va shaxsiy ma'lumot bo'yicha imkoniyat | 15 | Kanallar mosligi, rozilik |
| **Jami** | **100** | |

- **80–100:** kuchli nomzod (jiddiy muammo bo'lmasa).
- **60–79:** cheklangan doirada sinash mumkin.
- **0–59:** suhbatlar davom etadi; majburlab ulamaymiz.

**To'xtash holatlari:** ma'lumotga qonuniy kirish yo'q; haqiqiy narx manbai yo'q; norasmiy usullar (scraping) talab qilinadi; chek rasmini tekshirmasdan to'lovni tasdiqlashni so'rashadi; natijani o'lchashga umuman rozi emas.

## 9. Sinov taklifi va demo ssenariylari

### Shopga aytiladigan taklif (faraz)

> "Mahsulotlaringizni yagona katalogga ulaymiz va Telegram, Instagram hamda saytingizdagi chatda AI bilan xaridorlarga javob beramiz. Xaridorning byudjeti va ehtiyojiga mos PC narxli taklifini tayyorlaymiz va tasdiqlash uchun menejeringizga yuboramiz. Xaridor 'olaman' desa, buyurtma qoralamasi tayyorlanadi va operatoringiz bog'lanadi. Hamma suhbat va buyurtmalar bir joyda; natijani raqamlarda ko'rasiz."

**Va'da qilmaymiz:** 100% avtomatik sotuv, xatosiz AI, istalgan Instagram akkauntiga darhol ulanish yoki kafolatlangan daromad.

### Pilot chegaralari

- Maqsad — 3–5 ta haqiqiy shop; cheksiz bepul xizmat emas.
- 30 kunlik bepul pilot, keyin pullik (DEC-119). Shartlar — `business/14`.
- 1–2 kanal va katalogning ishonchli qismi bilan boshlash mumkin.
- AI faqat taklif va buyurtma **qoralamasi**ni tayyorlaydi; tekshirilmagan narx, qoldiq yoki moslikni tasdiqlamaydi.
- Odam istalgan payt suhbatni ola oladi; AI'ni bir tugma bilan o'chirish mumkin.
- To'lov va yetkazish tizimdan tashqarida — shop o'zi qiladi (DEC-100).
- Shop ma'lumotlari shop ichida qoladi; umumiy qidiruvga faqat alohida rozilik bilan.
- Muvaffaqiyat: javob vaqti, taklif vaqti, sifatli leadlar, operator vaqti, haqiqiy buyurtmalar, AI xarajati, aniqlik.

### Beshta demo ssenariy

1. **Katalog:** Excel faylni yuklash → xatolarni tekshirish → tasdiqlash → mahsulot shop saytida ko'rinadi.
2. **AI PC maslahat:** "10 mln so'mgacha Premiere va CS2 uchun" → ehtiyojni aniqlash → katalogdagi mahsulotlar → moslik tekshiruvi → taklif qoralamasi → menejer tasdig'i.
3. **Lead:** unutilayotgan suhbat → operatorga biriktirish → eslatma → natija.
4. **Buyurtma:** xaridor "olaman" → AI qoralama yaratadi → operator tasdiqlaydi va mahsulot band qilinadi → xaridorga xabar; bir xil so'rov ikki marta kelsa qoldiq ikki marta kamaymaydi.
5. **Ovozli hisobot (namoyish):** ega o'zbek, rus yoki ingliz tilida bitta raqamni so'raydi → tizim ruxsat etilgan umumiy raqamni sana va manbasi bilan aytadi; ovoz orqali hech narsa o'zgartirilmaydi.

Demoda ishlatilgan raqamlar **namuna** yoki shop ruxsat bergan haqiqiy ma'lumot ekani aniq ko'rsatiladi.

## 10. Erta aniqlanishi kerak bo'lgan xavflar

| ID | Savol yoki xavf | Boshlang'ich himoya | Batafsil |
|---|---|---|---|
| RISK-001 | Instagram'ga rasmiy ulanish mumkinmi? | Telegram va sayt bilan boshlash; kanallar imkoniyatlari jadvali | `engineering/30` |
| RISK-002 | Narx juda tez o'zgaradimi? | Narx yangiligi nazorati, taklifda narx qotiriladi, tasdiq | `business/03` |
| RISK-003 | Oxirgi mahsulot ikki kanalda sotilib ketadimi? | Bir vaqtdagi tasdiqlarda faqat bittasi o'tadi; takroriy so'rov himoyasi | `business/05`, `business/10` (TC-002, TC-027) |
| RISK-004 | AI qism yoki narxni o'ylab topadimi? | AI faqat tizimdagi ma'lumotdan foydalanadi; aniq qoidalar; odam tekshiruvi | `business/08`, `engineering/26` |
| RISK-005 | Shopning maxfiy ma'lumoti boshqalarga chiqib ketadimi? | Shoplar to'liq ajratilgan; ommaviy taklif faqat rozilik bilan | `engineering/23` |
| RISK-006 | Soxta chek bilan to'lov tasdiqlanadimi? | Stage 1 da to'lov tizimdan tashqarida; keyin — faqat haqiqiy tushum bilan | `business/03`, DEC-100 |
| RISK-007 | Chat, audio va shaxsiy ma'lumotlar qonuniy ishlanadimi? | Xabardor qilish va rozilik, kam ma'lumot yig'ish, saqlash muddati | `engineering/32` |
| RISK-008 | Tizim to'xtab qolsa yoki xabar takror kelsa nima bo'ladi? | Xabarlar yo'qolmaydi, qayta yuboriladi, takrorlanmaydi | `business/10` (TC-010, TC-022) |
| RISK-009 | Shop katalogni yangilamasa nima bo'ladi? | Eskirgan narx nazorati, ulashda yordam | `business/02`, `business/13` |
| RISK-010 | Ovoz orqali maxfiy moliyaviy ma'lumot chiqib ketadimi? | Har kim faqat o'z ruxsatidagi raqamni oladi, ovoz bilan o'zgartirish yo'q | `business/08` |

Bu hujjat xavflarni qayd qiladi; texnik yechimlar `engineering/` hujjatlarida va qarorlar registrida.

## 11. Suhbatlardan keyin qanday qaror qilamiz

```
Suhbatlar va dalillar ──▶ Muntazam, qimmatga tushadigan muammo bormi?
   ├─ Yo'q ──▶ Boshqa mijoz turi yoki boshqa muammoni tanlash
   └─ Ha ──▶ Ishonchli katalog va narx bormi?
              ├─ Yo'q ──▶ Avval leadlarni yig'ish va operatorga uzatishdan boshlash ──┐
              └─ Ha ──▶ Eng og'ir jarayon — PC taklifimi?                              │
                         ├─ Ha ──▶ AI PC taklifi + moslik tekshiruvi ──────────────────┤
                         └─ Yo'q ──▶ AI javob + qayta bog'lanish ──────────────────────┤
                                                                                         ▼
                                                  Pilot uchun mas'ul odam va ko'rsatkichlar bormi?
                                                     ├─ Yo'q ──▶ Suhbatlar davom etadi
                                                     └─ Ha ──▶ Cheklangan demo va pilot ──▶ Stage 1 doirasi
```

**Boshlaymiz:** kamida 3 ta shop muammoni dalil bilan tasdiqlaydi, ruxsat bilan olingan katalog namunasi bor, pilot uchun mas'ul odam va boshlang'ich o'lchov aniq, integratsiya xavfsiz qilinishi mumkin.

**O'zgartiramiz:** muammo bor, lekin narx va qoldiq ma'lumoti ishonchsiz — AI orqali buyurtma emas, leadlarni yig'ish va menejerga uzatishdan boshlaymiz.

**Qilmaymiz:** norasmiy usullar (scraping), shubhali to'lovni avtomatik tasdiqlash, shoplar o'rtasida ma'lumot uzatish yoki asossiz aniq narx va'da qilish talab qilinsa.

## 12. Har suhbatdan keyin to'ldiriladigan shablon

```yaml
shop_code: S-001
interview_date: null        # suhbat sanasi
respondent_role: null       # kim bilan gaplashildi
segment: null               # shop turi
branches_count: null        # filiallar soni
channels: []                # sotuv kanallari
observed_recent_workflow: null  # kuzatilgan oxirgi savdo jarayoni
main_pains: []              # asosiy muammolar
quantitative_baseline: {}   # boshlang'ich raqamlar
price_stock_source: null    # narx va qoldiq manbai
channel_readiness: null     # kanallar ulanishga tayyormi
public_offer_opt_in_interest: null  # ommaviy taklifga qiziqish
pilot_decision_maker: null  # pilot bo'yicha qaror qiluvchi
pilot_next_step: null       # keyingi qadam
evidence_ids: []            # dalillar
privacy_consent: null       # rozilik
hypothesis_updates: []      # farazlar bo'yicha o'zgarishlar
open_questions: []          # ochiq savollar
```

Bu faylga xaridorlarning shaxsiy ma'lumotlari, parollar yoki asl chek rasmlari qo'yilmaydi.

## 13. Hujjat qachon "tasdiqlangan" bo'ladi

- [ ] Yetarli son va turdagi shoplar bilan haqiqiy suhbatlar o'tkazilgan.
- [ ] Har muhim xulosaga dalil (`EVD-###`) biriktirilgan.
- [ ] Qarama-qarshi misollar ham ko'rsatilgan.
- [ ] Eng kuchli 3 ta muammo qanchalik tez-tez uchrashi, qanchaga tushishi va pul to'lashga tayyorlik bo'yicha saralangan.
- [ ] Kamida 3 ta shop uchun boshlang'ich o'lchov usuli aniqlangan.
- [ ] Katalog, narx, kanallar va pilot bo'yicha qaror qiluvchi tekshirilgan.
- [ ] Stage 1 ning asosiy imkoniyati va "birinchi kundan qilmaymiz" ro'yxati taklif qilingan.
- [ ] Pilotga huquqiy yoki texnik to'siq qolmagan yoki aniq cheklangan.
- [ ] Asoschi A01 ni tasdiqlagan.

### Natijalar qaysi hujjatlarga o'tadi

| Hujjat | A01 dan nima kerak |
|---|---|
| `business/14` — pilot kelishuvi va narxlar | Muammoning pul qiymati, xabarlar hajmi, narxga sezgirlik, AI xarajati taxmini |
| `business/10` — bosqichlar | Eng kuchli boshlang'ich imkoniyat, ustuvorliklar, chiqarib tashlanadiganlar |
| `business/13` — shopni ulash | Shop majburiyatlari, ma'lumot olish yo'li, boshlang'ich o'lchov |
| `business/03` — qoidalar | Haqiqiy narx, band qilish, taklif, to'lov va yetkazish qoidalari |
| `business/02` — modullar | Tasdiqlangan foydalanuvchi vazifalari va qabul talablari |
| `business/08`, `engineering/26` — AI | Haqiqiy savol namunalari, operatorga uzatish holatlari, AI sinovlari uchun misollar |

## 14. Hozircha ochiq qolgan savollar

Ko'p savollarga 2026-10-22 da boshlang'ich javob berildi (registr: DEC-100…123). Suhbatlar ularni tasdiqlashi yoki o'zgartirishi kerak:
1. Asosiy imkoniyat qaysi — AI chat, PC taklifi, lead kuzatuvi yoki birikmasi?
2. Pilotda qaysi rasmiy kanallar amalda ulanadi? (Boshlang'ich javob: Telegram + Instagram + sayt chati, DEC-116.)
3. Shop katalogi qanchalik toza va narx/qoldiq qanday yangilanadi?
4. Taklif narxi qancha vaqt amal qiladi? (Boshlang'ich javob: 24 soat.)
5. Shop oladigan qo'shimcha foyda oylik to'lov va AI xarajatini oqlaydimi?
6. Shoplar kelajakdagi ommaviy narx solishtirishga qanday qaraydi?
7. Ovozli hisobot alohida pullik bo'ladimi yoki keyinroq qo'shiladimi?

**Keyingi amaliy qadam:** avval 5 ta shop bilan suhbat, dalillar yig'ish, farazlar holatini yangilash. Shundan keyin A01 tasdiqlanadi, `14` dagi narxlar dalil asosida to'ldiriladi.
