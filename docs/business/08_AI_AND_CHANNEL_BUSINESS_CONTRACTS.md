# 08 — AI va kanallar: AI nima qila oladi va nima qila olmaydi

**Versiya:** v2 (2026-10-22, oddiy tilda qayta yozildi). Texnik tafsilot (tool'lar, prompt, xavfsizlik qatlamlari): `engineering/26`. Kanallar texnikasi: `engineering/30`.

## Bu hujjat nima uchun

Tizimda AI xaridorlar bilan gaplashadi va egaga hisobot beradi. Bu hujjat biznes nuqtai nazaridan javob beradi:
- AI qanday vazifalarni bajaradi,
- qanday ma'lumotga tayanadi,
- nimani **hech qachon** qilmaydi,
- qachon operatorni chaqiradi,
- xaridor qaysi kanallarda yozishi mumkin.

**Asosiy tamoyil:** AI — yordamchi, qaror qiluvchi emas. U tushunadi, savol beradi, tavsiya qiladi va tushuntiradi. Narx, qoldiq, moslik va buyurtma tasdig'i esa tizim qoidalari va odamlar zimmasida.

---

## 1. Uch xil AI

| AI | Qayerda ishlaydi | Nima ko'radi | Nima qila oladi | Nima qila olmaydi |
|---|---|---|---|---|
| **AI sotuvchi** (Stage 1) | Shop Telegram boti, Instagram, saytdagi chat | Faqat shu shopning katalogi, narxlari, qoldig'i, FAQ | Javob berish, mahsulot va PC tavsiya qilish, lead va taklif qoralamasi, **buyurtma qoralamasi**, operatorni chaqirish | Buyurtmani tasdiqlash, narx yoki chegirma berish, stokni o'zgartirish, boshqa shop ma'lumotini ko'rish |
| **AI hisobot yordamchisi** (Stage 1) | Shop paneli | Foydalanuvchiga ruxsat etilgan raqamlar | Raqamlar bilan javob, grafik, eksport | Hech narsani o'zgartirish, ruxsatdan tashqari raqam ko'rsatish |
| **Global AI maslahatchi** (Stage 3) | Global qidiruv sayti va boti | Faqat shoplar ochiq chiqargan takliflar | Solishtirish, tushuntirish, xaridorni shopga yo'naltirish | Shoplarning ichki ma'lumotiga kirish (tannarx, savdo, xaridorlar) |

Uchalasi bir-biridan to'liq ajratilgan: har birining ma'lumoti va ruxsatlari alohida.

---

## 2. AI sotuvchi qanday ishlaydi

```
1. Xaridor yozadi ──▶ Xabar saqlanadi   [qaysi shop, qaysi kanal — tizim aniqlaydi]
2. Hozir kim javob beradi — AI yoki operator? ──(operator olgan bo'lsa)──▶ AI jim turadi
3. AI tilni aniqlaydi (o'zbek lotin/kirill, rus, ingliz) va shu tilda javob beradi
4. AI kerakli savollarni beradi: nima kerak, byudjet, maqsad, olib ketish yoki yetkazish
5. AI katalogdan qidiradi   [faqat shu shop, narx va qoldiq tizimdan]
6. PC yig'ma bo'lsa ──▶ moslik tekshiriladi   [qoidalar hal qiladi, AI faqat tushuntiradi]
7. AI 1–3 variant taklif qiladi: afzalliklari, kamchiliklari, narx qancha muddat amal qilishi
8. Xaridor tayyor bo'lsa:
     - PC yig'ma ──▶ taklif qoralamasi ──▶ menejer tasdiqlaydi ──▶ xaridorga havola
     - "Olaman" ──▶ buyurtma qoralamasi ──▶ operatorni chaqiradi
       [xaridorga: "buyurtmangiz qabul qilindi, operator bog'lanadi"]
9. Buyurtmadan keyin AI faqat tizimdagi holatni aytadi ("tayyorlanmoqda" va h.k.)
```

### AI qanday ma'lumotga tayanadi

| Ma'lumot | Manba |
|---|---|
| Mahsulotlar, variantlar | Shop katalogi (faqat saytga chiqarilganlar) |
| Narx | Tizimdagi joriy narx (dollarda bo'lsa — shop kursi bo'yicha so'mda) |
| Mavjudligi | Ombordagi "sotuvga mavjud" son |
| PC mosligi | Moslik tekshiruvi natijasi (`engineering/25`) |
| Ish vaqti, yetkazish, kafolat, qaytarish | Shop tasdiqlagan FAQ va siyosatlar |
| Buyurtma holati | Faqat shu xaridorning buyurtmasi |

Bu ro'yxatda bo'lmagan narsani AI aytmaydi. Masalan, shop siyosatida yozilmagan bo'lsa, "1 yil kafolat" deb va'da qilmaydi.

### AI hech qachon qilmaydigan narsalar

- Narxni o'ylab topish yoki o'zgartirish.
- Chegirma berish yoki va'da qilish (so'ralsa operatorga uzatadi).
- "Buyurtma tasdiqlandi", "band qilindi", "to'landi" deyish (buni tizim va odam qiladi).
- "Omborda bor" deyish, agar tizimda yo'q bo'lsa.
- "Mos keladi" deyish, agar moslik tekshiruvi "mos" demagan bo'lsa.
- Boshqa shop haqida ma'lumot berish.
- Xaridor matnidagi "buyruqlarni" bajarish ("narxni e'tiborsiz qoldir", "sen adminsan").
- O'zini odam qilib ko'rsatish: birinchi xabarda AI ekanini aytadi.
- Xaridorning telefoni, manzili kabi shaxsiy ma'lumotini tashqi AI servisiga yuborish (DEC-016).

### AI qachon operatorni chaqiradi

| Holat | Xaridorga nima deyiladi | Shopda nima bo'ladi |
|---|---|---|
| Xaridor odam bilan gaplashmoqchi | "Operatorga ulayapman" | Operatorga vazifa |
| Xaridor "olaman" dedi | "Buyurtmangiz qabul qilindi, operator bog'lanadi" | Buyurtma qoralamasi + operatorga vazifa |
| Mahsulot katalogda yo'q | "Aniq bunday mahsulot topilmadi" + o'xshashlar | Katalogga qo'shish tavsiyasi |
| Narx yo'q yoki eskirgan | "Narxni operator aniqlab beradi" | Operatorga vazifa |
| PC mosligi "tekshirish kerak" | "Mosligini mutaxassis tekshirib beradi" | Menejerga tasdiq vazifasi |
| Chegirma so'raldi | "Bu savolni operatorga beraman" | Operatorga vazifa |
| To'lov haqida so'raldi | "To'lov shop bilan kelishiladi, operator bog'lanadi" | Operatorga vazifa |
| Kafolat, nosozlik, qaytarish | "Operatorga ulayapman" | Operatorga vazifa |
| Xaridor norozi, shikoyat qiladi | Uzr so'raydi va operatorni chaqiradi; siyosat o'ylab topmaydi | Muhim vazifa |
| AI ishlamayapti yoki limiti tugadi | "Operator tez orada javob beradi" | Xabarlar operator navbatiga |
| Ish vaqtidan tashqari | Shop ish vaqtini aytadi | Ertalab operatorga |

### AI ish rejimlari

| Rejim | Ma'nosi |
|---|---|
| O'chiq | AI javob bermaydi, hammasi operatorga |
| Operator tasdiqlaydi | AI javob yozadi, operator ko'rib yuboradi (pilotning birinchi haftasi uchun tavsiya) |
| O'zi yuboradi | AI o'zi javob beradi, xavfli holatlarda operatorni chaqiradi |

Rejimni ega tanlaydi. Har qanday payt AI'ni o'chirish mumkin, bunda savdo to'xtamaydi.

---

## 3. AI hisobot yordamchisi

**Nima qiladi:** ega yoki menejer yozma savol beradi — "Kecha nechta buyurtma topshirildi?", "Bu oy eng ko'p qaysi videokarta sotildi?" — va raqam bilan javob oladi.

```
Savol ──▶ Tizim uni ruxsat etilgan ko'rsatkichga aylantiradi
  ──▶ Foydalanuvchining ruxsati tekshiriladi
  ──▶ Raqam hisoblanadi   [AI emas, tizim hisoblaydi]
  ──▶ Javob: raqam + davr + vaqt zonasi + "ma'lumot qachon yangilangan"
```

**Stage 1 da qaysi savollarga javob beradi:**
- topshirilgan buyurtmalar soni va summasi;
- eng ko'p sotilgan mahsulotlar va PC yig'malar;
- kanallar bo'yicha suhbatlar va leadlar;
- javob vaqti;
- tasdiq kutayotgan buyurtmalar;
- kam qolgan mahsulotlar;
- kunlik, haftalik, oylik o'zgarish;
- "to'landi" deb belgilangan summa (tekshirilmagan deb ko'rsatiladi).

**Javob bermaydigan holatlar:**
- **Foyda** — tannarx kiritilmagan, shuning uchun "tannarx ma'lumoti yo'q" deydi.
- Ro'yxatda yo'q ko'rsatkich — "bu ko'rsatkich hozircha yo'q" va eng yaqin mavjudlarini aytadi.
- Ruxsat yo'q raqam — "ruxsat yo'q", raqam ko'rsatilmaydi.
- O'zgartirish so'rovi ("qoldiqni 100 qil", "pul qaytar") — bajarilmaydi; hisobot yordamchisi faqat o'qiydi.

**Ovozli savol** (o'zbek, rus, ingliz) — keyinroq (DEC-112). Avval ovozni matnga aylantirish sifati o'zbek tilida sinovdan o'tkaziladi. Ovoz qo'shilganda ega gapiradi, matn ekranda ko'rsatiladi, ega tasdiqlaydi; summa noaniq eshitilsa ("15 mln" yoki "50 mln"), qayta so'raladi.

**Namuna savollar:**
- O'zbekcha: "Oxirgi 7 kunda Chilonzor filialida nechta buyurtma topshirildi? O'tgan hafta bilan solishtir."
- Ruscha: "Покажи пять самых продаваемых видеокарт за этот месяц."
- Inglizcha: "How many orders were completed today?"

---

## 4. Global AI maslahatchi (Stage 3)

- Aynan bir xil modelni o'xshashlaridan ajratadi va nima uchun tavsiya qilayotganini tushuntiradi.
- Narx, yetkazish, kafolat, holat va oxirgi yangilanishni ko'rsatadi; noma'lum ma'lumotni "noma'lum" deydi.
- Xaridor joylashuvini bermasa, shahar bo'yicha qidiradi.
- Reklama o'rinlari aniq belgilanadi va tavsiyaga ta'sir qilmaydi.
- Xaridorni shopga faqat u qayerga yo'naltirilayotganini ko'rib, rozilik bergandan keyin yo'naltiradi.

---

## 5. Kanallar

| Kanal | Qachon | Nima qila oladi | Shart |
|---|---|---|---|
| Saytdagi chat | Stage 1 | Xabar, mahsulot ko'rsatish, buyurtma | Bizning kanalimiz; tashqi servislar ishlamasa ham ishlaydi |
| Telegram bot | Stage 1 | Xaridor yozgan chatda javob, mahsulot kartochkalari, buyurtma holati | Shop bot ochadi; bot xaridorga birinchi bo'lib yoza olmaydi |
| Telegram Business | Keyinroq | Egasining shaxsiy Telegram akkauntiga ulanish | Egasining ruxsati; pilotda kerak bo'lsa yoqiladi |
| Instagram Direct | Stage 1 (DEC-116) | Xaridor yozgan suhbatda javob | Meta rasmiy ruxsati kerak (ariza ish boshlanishi bilan topshiriladi); 24 soatlik javob muddati |
| Facebook Messenger | Keyinroq | Shop sahifasi suhbatlari | Meta ruxsati |
| WhatsApp Business | Stage 2 | Shablon va suhbat xabarlari | Rasmiy ulanish va to'lovlar |
| Global sayt va Telegram bot | Stage 3 | Global qidiruv | Shop botlaridan alohida |

**Qat'iy taqiqlar:** rasmiy ruxsatsiz ulanish, saytlardan ma'lumot o'g'irlash (scraping), shaxsiy akkauntlarni parol bilan avtomatlashtirish, xaridorlarga ommaviy so'ralmagan xabarlar.

Ruxsat olinmagan kanal tizimda "ishlayapti" deb ko'rsatilmaydi.

---

## 6. AI'ni o'rgatish va sinash

- **Shop ma'lumotida AI o'qitilmaydi** — faqat shop alohida rozilik bersa va ma'lumot anonimlashtirilgan bo'lsa (DEC-118).
- **Sinov to'plamlari** (AI ishga tushirilishidan oldin): o'zbek, rus, ingliz tilidagi savollar; xatolar va translit; noto'g'ri variant; mahsulot yo'q; narx eskirgan; PC mosligi; boshqa shop ma'lumotini so'rash; AI'ni aldashga urinishlar.
- **Qat'iy talab:** sinovda noto'g'ri narx, mavjud bo'lmagan mahsulot yoki "tasdiqlandi" degan javob — **birorta ham bo'lmasligi** kerak.
- **Model:** tayyor AI modeli ishlatiladi (bir haftalik solishtirishdan keyin tanlanadi, DEC-009). O'z modelini noldan o'qitish rejada yo'q.

Batafsil: `engineering/17`, `engineering/26` §13.
