# AI Commerce OS & Network — biznes hujjatlari

**Versiya:** v2 (2026-10-22, oddiy tilda qayta yozildi).

## Loyiha nima haqida

Instagram, Telegram va sayt orqali sotadigan mustaqil shoplar uchun platforma. Uch bosqichda quriladi:
1. **Shop uchun savdo tizimi** — katalog, ombor, sayt, AI sotuvchi, inbox, buyurtmalar, hisobotlar.
2. **Shoplar tarmog'i** — shoplar o'zi ulanadi, kassa dasturlari bilan bog'lanadi, bir xil mahsulotlar umumiy katalogga birlashadi.
3. **Global AI qidiruv** — xaridor bir nechta shop takliflarini narx, joylashuv va kafolat bo'yicha solishtiradi.

Qishloq xo'jaligi, platforma orqali to'lov, xalqaro savdo — bu uch bosqichga kirmaydi, keyingi yo'nalishlar (`11` §4).

## Hujjatlar ro'yxati

| № | Hujjat | Nima haqida |
|---|---|---|
| 00 | `00_README_AND_SCOPE.md` | Shu fayl: loyiha qisqacha, hujjatlar ro'yxati, asosiy qoidalar |
| 01 | `01_BUSINESS_VISION_AND_3_PHASES.md` | G'oya, 3 bosqich: kimga, nima, kim pul to'laydi |
| 02 | `02_ALL_BUSINESS_MODULES.md` | 39 ta modul: har biri nima qiladi, kim ishlatadi, qabul mezonlari |
| 03 | `03_BUSINESS_RULES_108.md` | 111 ta biznes qoida (fayl nomidagi "108" tarixiy) |
| 04 | `04_ROLES_PERMISSIONS_AND_APPROVALS.md` | Kim nima qila oladi, qaysi amallar tasdiq talab qiladi |
| 05 | `05_STATE_MACHINES_AND_EXCEPTIONS.md` | Buyurtma, taklif, suhbat va boshqalarning holatlari — strelkalar bilan |
| 06 | `06_UI_SITEMAP_AND_USER_FLOWS.md` | Sahifalar ro'yxati va foydalanuvchi qadamlari |
| 08 | `08_AI_AND_CHANNEL_BUSINESS_CONTRACTS.md` | AI nima qila oladi va nima qila olmaydi, kanallar |
| 10 | `10_UAT_ACCEPTANCE_AND_RELEASES.md` | Qabul sinovlari va ish qaysi bo'laklarda chiqariladi |
| 11 | `11_BUSINESS_DECISIONS_ASSUMPTIONS_AND_RISKS.md` | Asosiy qarorlar, farazlar, xavflar |
| 13 | `13_MERCHANT_ONBOARDING_PLAYBOOK.md` | Pilot shopni ulash qadamlari |
| 14 | `14_PILOT_AGREEMENT_AND_PRICING.md` | Pilot shartnomasi qoralamasi va narx gipotezalari (qoralama) |

**Boshqa joydagi hujjatlar:**
- Barcha qarorlar va ularning sabablari — `../decisions/DECISION_REGISTER.md`.
- Atamalar lug'ati — `../GLOSSARY.md`.
- Bozor va muammo tadqiqoti — `../discovery/A01_MARKET_PROBLEM_DISCOVERY.md`.
- Dasturchilar uchun hujjatlar — `../engineering/`. Ilgari bu yerda bo'lgan `07` (ma'lumotlar tuzilmasi), `09` (modullar o'zaro aloqasi), `12` (bog'lanish indeksi) endi `engineering/34`, `35`, `36` da (DEC-125).

## Hujjatlar qanday bog'langan

Har bir narsaning o'z raqami bor, hujjatlar bir-biriga shu raqamlar orqali havola qiladi:
- `M01`…`M39` — modullar (`02`)
- `BL-001`…`BL-111` — biznes qoidalar (`03`)
- `FSM-01`… — holatlar ketma-ketligi (`05`)
- `UAT-M01`…, `TC-001`… — sinovlar (`10`)
- `DEC-001`… — qarorlar (registr)

## Hech qachon buzilmaydigan qoidalar

1. **Shop o'z katalogi, xaridorlari va savdo tarixining egasi.** Umumiy qidiruvga faqat shop roziligi bilan chiqadi.
2. **Umumiy katalog ≠ shop ombori.** Bir xil model umumiy katalogda bitta, lekin har shopning narxi, qoldig'i va taklifi alohida.
3. **AI narx, qoldiq, to'lov yoki foyda raqamini o'zi o'ylab topmaydi.** Hammasi tizimdagi ma'lumotdan olinadi.
4. **Chek rasmi — "to'landi" degani emas.** Stage 1 da to'lov tizimdan tashqarida; "to'landi" — shop qo'ygan, tekshirilmagan belgi (DEC-100a).
5. **Band qilish ≠ sotish.** Band qilish qachon boshlanib, qachon tugashi nazorat qilinadi.
6. **Shop AI'si ≠ xaridorning global AI'si.** Shopning ichki ma'lumoti hech qachon umumiy qidiruvga chiqmaydi.
7. **Jami narx** faqat barcha xarajatlar (yetkazish ham) ma'lum bo'lsa ko'rsatiladi. Aks holda — "yetkazish narxi noma'lum".
8. Operator va AI bir suhbatda bir vaqtda turli javob yubormaydi.
9. Har bir muhim o'zgarishda kim, qaysi shopda, qachon qilgani yozib qo'yiladi.
10. Mos kelmaydigan mahsulot, eskirgan narx, noto'g'ri rol — **amal to'xtatiladi va odamga yuboriladi**, jim o'tkazib yuborilmaydi.

## Ishlash tartibi

1. Biznes xususiyatlari — `01` va `02`; qoidalar — faqat `03`.
2. Biror narsa o'zgarsa, qaysi modul (`Mxx`) va qoida (`BL-xxx`) ekanini ko'rsating; sahifa, holat va sinovlarga ta'sirini birga ko'ring.
3. Uch bosqich bir vaqtda qurilmaydi. Stage 1 bo'laklarga bo'lingan (`10` §1).
4. Qaror o'zgarsa, registrda `CHANGED (sana): eski → yangi` deb yoziladi.

## Bu hujjatlar nimani almashtirmaydi

Bu hujjatlar biznes mantiqini tushuntiradi. Ular haqiqiy shoplar bilan tekshiruv, shartnomalar va Telegram/Meta ruxsatlari o'rnini bosmaydi. Texnik loyiha (ma'lumotlar bazasi, API, kod) — `engineering/` da.
