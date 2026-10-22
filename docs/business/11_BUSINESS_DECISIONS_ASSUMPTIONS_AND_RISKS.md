# 11 — Asosiy biznes qarorlari, farazlar va xavflar

**Versiya:** v2 (2026-10-22, oddiy tilda qayta yozildi).

## Bu hujjat nima uchun

Loyiha boshida ko'p narsa hali tekshirilmagan. Ba'zi narsalarni "shunday bo'ladi" deb qaror qildik, ba'zilari esa faraz. Bu hujjat ularni aralashtirib yubormaslik uchun:
1. **Asosiy qarorlar** — loyihaning yo'nalishini belgilaydigan, o'zgartirish qiyin bo'lgan qarorlar.
2. **Ochiq savollar** — kod boshlanishidan oldin javob berilishi kerak bo'lgan savollar (hammasi hal qilindi, qiymatlari registrda).
3. **Xavflar** — nima noto'g'ri ketishi mumkin va bunga qarshi nima qilamiz.
4. **Uch bosqichga kirmaydigan narsalar.**

Aniq qarorlarning to'liq ro'yxati va ularning sabablari — `../decisions/DECISION_REGISTER.md`.

---

## 1. Asosiy qarorlar

| ID | Qaror | Nega | Qachon qayta ko'rib chiqiladi |
|---|---|---|---|
| BD-01 | Loyiha **aniq 3 bosqichdan** iborat: shop uchun savdo tizimi → shoplar tarmog'i → xaridor uchun global AI qidiruv | Avval shop pul to'laydigan foyda olsin, keyin tarmoq kuchi ishlaydi | Talab boshqa yo'nalishni alohida mahsulot qilishni talab qilsa |
| BD-02 | PC va elektronika shoplaridan boshlaymiz. Tizim yadrosi umumiy, PC moslik — qo'shimcha modul | Bu sohada maslahat berib sotish eng og'ir | Pilot boshqa soha arzonroq ekanini ko'rsatsa |
| BD-03 | Xaridor bilan munosabat va shop sayti — shopniki | Mustaqil shoplar shunda qo'shilishga ko'proq rozi bo'ladi | Platforma orqali to'lov modeli kelishilsa |
| BD-04 | Shop mahsulotlari umumiy qidiruvga faqat shop roziligi bilan chiqadi, standart holatda yopiq | Shop ishonchi va ma'lumotlarini himoya qilish | Faqat aniq siyosat bilan, tarif majburlashi bilan emas |
| BD-05 | Shop AI'si va xaridorning global AI'si — alohida | Manfaatlari va ko'radigan ma'lumotlari boshqa | Hech qachon birlashtirilmaydi |
| BD-06 | Narx, stok, moslik va to'lov — AI emas, aniq qoidalar bilan hisoblanadi | AI xatosi qimmatga tushadi | Hech qachon yumshatilmaydi |
| BD-07 | Ovozli yordamchi avval faqat o'qiydi, hech narsani o'zgartirmaydi | Ovozni noto'g'ri tushunish xavfli | Buyruqlarni tasdiqlash jarayoni sinalgandan keyin |
| BD-08 | Pul shopga tushadi. **Stage 1 da to'lov tizimdan tashqarida — shop o'zi oladi** (DEC-100) | Hisob-kitob va huquqiy masalalar sodda | Litsenziyali to'lov tizimi ulanishga tayyor bo'lsa |
| BD-09 | **Telegram, Instagram va saytdagi chat — Stage 1 da birga** (DEC-116). Meta arizasi S0 bilan topshiriladi. Norasmiy usullar (scraping) ishlatilmaydi | Ko'p shoplar Instagram orqali sotadi | Meta ruxsati pilot sanasiga kelmasa, Instagram'siz boshlaymiz (DEC-116a) |
| BD-10 | Global qidiruvga xaridor kelishidan oldin shopga savdo tizimini sotamiz | Ikki tomonli bozorni noldan boshlash muammosidan qochish | Global qidiruvda haqiqiy xaridorlar oqimi paydo bo'lsa |
| BD-11 | Backend va frontend alohida repo'larda; server sozlamalari backend ichida | Bitta asoschi uchun soddaroq | Alohida DevOps jamoasi paydo bo'lsa |
| BD-12 | Bitta dastur ichida aniq ajratilgan modullar (modular monolith) | Murakkablik nazoratda, har modulning egasi aniq | Yuklama faktlari boshqacha talab qilsa |

Bular **biznes qarorlari**. Texnik qarorlar (navbat tizimi, ma'lumotlar bazasida shoplarni ajratish va h.k.) — `engineering/` hujjatlarida va registrda.

---

## 2. Ochiq savollar — hal qilindi

Kod boshlanishidan oldin javob kerak bo'lgan savollar. **2026-10-22 da hammasi registrga ko'chirildi va founder tomonidan boshlang'ich qiymat sifatida hal qilindi.** Bu ro'yxat tarix uchun; amaldagi qiymatlar registrda (§4 da xaritasi).

| Ref | Savol | Javob topilguncha xavfsiz yo'l |
|---|---|---|
| O-01 | PC shopda sotuvning qaysi bosqichi eng og'ir? | AI inbox va taklif demosi, natija kafolatisiz |
| O-02 | Band qilish qancha davom etadi, bekor qilish muddatlari qanday? | Shop o'zi belgilaydi, tizim taxmin qilmaydi |
| O-03 | Narx qancha vaqt amal qiladi, chegirma chegarasi qancha? | Noaniq bo'lsa — odam tasdig'i |
| O-04 | Stokning asosiy manbai kassa dasturimi yoki dashboard'mi? | Har maydon uchun ustuvorlik, nizoni odam hal qiladi |
| O-05 | Qo'lda to'lovni qanday tekshirish kerak? | Moliya xodimi bank tushumi bilan solishtiradi |
| O-06 | Yetkazish qoidalari va hamkorlar | Olib ketish va yetkazish holatlarini shop o'zi boshqaradi |
| O-07 | Qaytarish, kafolat va soliq majburiyatlari | Har shop uchun yoziladi, tizim qoida o'ylab topmaydi |
| O-08 | O'zbek, rus, ingliz tillarida ovozni tanish sifati | Faqat o'qiydigan beta, matnni tuzatish imkoniyati bilan |
| O-09 | Instagram/Meta va WhatsApp rasmiy ruxsatlari | Ruxsat tasdiqlanmaguncha o'chiq |
| O-10 | Ommaviy taklif qancha vaqtda eskirgan hisoblanadi? | Eskirganini yashirish yoki ogohlantirish, shop sozlaydi |
| O-11 | Rozilik, shaxsiy ma'lumot va saqlash muddati bo'yicha qonun | Kam ma'lumot yig'ish, huquqshunos tekshiruvi |
| O-12 | Reklama va yo'naltirish uchun daromad sxemasi | Xaridorlar oqimi isbotlanmaguncha o'chiq |
| O-13 | Global qidiruvda tartiblash va kafolat sifatini baholash | Faqat dalil asosida, ochiq va xolis tartib |
| O-14 | Bir xaridorni turli kanallarda bitta odam deb bog'lash | Faqat bitta shop ichida, aniq rozilik bilan |
| O-15 | AI, server, qo'llab-quvvatlash va to'lov xarajatlari bitta shopga qancha tushadi? | Birinchi pilotdan boshlab har kunlik xarajat hisobi |

---

## 3. Asosiy xavflar va ularga qarshi choralar

| Xavf | Boshida ehtimoli | Zarari | Minimal chora |
|---|---|---|---|
| PC qismlari mosligi noto'g'ri aniqlandi | O'rtacha | Juda katta | Aniq qoidalar; noma'lum bo'lsa "tekshirish kerak"; odam tasdig'i |
| Bitta mahsulot ikki marta sotildi | O'rtacha | Juda katta | Bir vaqtdagi tasdiqlarda faqat bittasi o'tadi; ombor tarixi; maxsus sinovlar (TC-002, TC-027) |
| Soxta to'lov cheki | Yuqori | Juda katta | Chek rasmi hech qachon "to'landi" degani emas; Stage 1 da to'lov tizimdan tashqarida |
| AI noto'g'ri narx aytdi | O'rtacha | Juda katta | AI narxni faqat katalogdan oladi; eskirgan narx — operatorga |
| Meta Instagram ruxsatini bermadi | O'rtacha | O'rtacha | Telegram va sayt bilan boshlash; ruxsat kelganda yoqish |
| Bir shop ma'lumoti boshqasiga ko'rindi | Mutlaqo yo'l qo'yilmaydi | Juda katta | Standart holatda hamma narsa yopiq; maxsus sinovlar va o'zgarishlar tarixi |
| Bitta shopga AI xarajati juda katta | O'rtacha | Katta | Limitlar; lead va buyurtma bo'yicha xarajat hisobi; AI'ni o'chirish tugmasi |
| Global katalogda turli mahsulotlar bitta deb birlashtirildi | Tekshiruvsiz yuqori | Katta | Variant dalillari, odam tekshiruvi, bekor qilish imkoniyati |
| Eskirgan taklif ommaviy ko'rinib qoldi | Ko'p shop bo'lganda yuqori | Katta | Qaytarib olish darhol kuchga kiradi; yangilik nazorati |
| Shoplar qiziqmayapti | Noma'lum | Biznes uchun juda katta | Pullik pilot, foydani o'lchash, bitta tor sohadan boshlash |
| Tashqi xizmat (Telegram, Meta, AI) ishlamay qoldi | O'rtacha | Katta | Xabarlar yo'qolmaydi va qayta yuboriladi; operator davom ettiradi |
| Ovozda raqam noto'g'ri tushunildi | O'zbek-rus aralash nutqda yuqori | Katta | Matnni ko'rsatib tasdiqlash; ovoz orqali hech narsa o'zgartirilmaydi |

---

## 4. Uch bosqichga kirmaydigan narsalar

Bular keyinchalik alohida yo'nalish bo'lishi mumkin, lekin hozirgi rejaga kirmaydi:
- **Qishloq xo'jaligi va fermerlar:** mahsulot navlari, kg/tonna, tez buziladigan mahsulot, sovuq zanjir, mavsumiy narxlar, ulgurji xarid.
- **Platforma orqali to'lov:** pulni platformada saqlash, shoplar o'rtasida taqsimlash, xaridorni himoya qilish, nizolarni hal qilish, yuk sug'urtasi.
- **Xalqaro savdo:** chet elga sotish, har davlat soliqlari, valyuta hisob-kitoblari.
- **AI marketing:** video va kontent yaratish, ijtimoiy tarmoqlardagi fikrlarni tahlil qilish (shopga qo'shimcha xizmat sifatida).
- **Ulgurji va logistika:** yetkazib beruvchilardan xarid, moliyalashtirish, ko'p omborli logistika, murakkab talab prognozi.

**Kengaytirish qoidasi:** yangi yo'nalish shop, katalog, narx kabi asosiy tushunchalarni qayta ishlatishi mumkin. Lekin o'ziga xos qoidalar (o'lchov birligi, holatlar, huquqiy talablar) uchun alohida biznes hujjati yoziladi. PC ombori qoidalari tez buziladigan mahsulotga tekshiruvsiz qo'llanilmaydi.

---

## 5. Tasdiqlash holati

- **Biznes doirasi:** boshlang'ich qarorlar qabul qilingan (registr), haqiqiy shoplar bilan tekshirish kutilmoqda.
- **Narx va daromad:** faqat gipoteza; shoplar qancha to'lashga tayyorligi hali tasdiqlanmagan (`14`).
- **Huquqiy va integratsiyalar:** ishga tushirishdan oldin tashqi tekshiruv kerak.
- **Texnik tomoni:** kod, integratsiyalar, yuklama sinovi va provayder ruxsatlari hali yo'q.
