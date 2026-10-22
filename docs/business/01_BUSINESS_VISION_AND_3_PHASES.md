# 01 — Asosiy g'oya va uch bosqich

**Versiya:** v2 (2026-10-22, oddiy tilda qayta yozildi). Haqiqiy shoplar bilan tekshirish kutilmoqda.

## Bir jumlada

**AI Commerce OS & Network** — Instagram, Telegram va sayt orqali sotadigan mustaqil shoplarga katalog va ombor, tayyor sayt, AI sotuvchi, xaridorlar bazasi va buyurtmalarni boshqarishni beradigan, keyin esa ular rozilik bergan takliflarni bitta global AI qidiruvda narx, joylashuv va kafolat bo'yicha solishtirish imkonini beradigan platforma.

## Uchta asosiy tushuncha

- **Shop** — mustaqil do'kon: xodimlari, filiallari, buyurtmalari, ombori, AI'si va sayti bilan. Kodda `shop` (DEC-124).
- **Umumiy mahsulot** — bir xil brend + model + variant tavsifi (masalan, "RTX 5060 8GB"). U hech bir shopga tegishli emas. Stage 2 dan.
- **Shop taklifi** — aniq shopning shu mahsulot uchun narxi, filiali, holati (yangi yoki ishlatilgan), kafolati va qoldig'i. Umumiy qidiruvga faqat shop roziligi bilan chiqadi.

---

## Stage 1 — Shop uchun savdo tizimi

**Kimga:** avval PC, gaming PC va elektronika shoplari. Shopning sayti bormi-yo'qmi — farqi yo'q.

**Qanday muammoni hal qiladi:**
- Instagram Direct va Telegram'da xaridorlar javob kutib ketib qoladi.
- Narx va PC yig'ma har safar qaytadan tushuntiriladi.
- Ombor, suhbatlar va buyurtmalar turli joyda, bir-biriga bog'lanmagan.

**Nima beramiz:** kecha-kunduz ishlaydigan AI sotuvchi, Telegram/Instagram/sayt chati bitta inbox'da, fayldan katalog yuklash, tayyor sayt, PC moslik tekshiruvi va takliflar, xaridorlar bazasi, ombor va band qilish, buyurtmalar, xaridorga holat xabarlari, hisobotlar va hisobot yordamchisi (ovoz — keyinroq beta).

**Kim pul to'laydi:** shop — oylik obuna va kerak bo'lsa ulash xizmati uchun. Xaridor uchun bepul.

**Modullar:** `M01`–`M20` (`02`).

**Birinchi ishlaydigan versiya (DEC-100):**

```
Ega kiradi ──▶ shop va filial yaratadi ──▶ katalogni fayldan yuklaydi ──▶ narx (so'm/dollar) va qoldiq
   ──▶ sayt ochiladi + Telegram / Instagram / sayt chati ulanadi
   ──▶ xaridor yozadi ──▶ AI maslahat beradi (PC taklifi) ──▶ xaridor "olaman" deydi
   ──▶ AI buyurtma qoralamasini yaratadi va operatorni chaqiradi
   ──▶ operator xaridor bilan gaplashadi va tasdiqlaydi [mahsulot band qilinadi]
   ──▶ shop tayyorlaydi va topshiradi ──▶ xaridorga xabar ──▶ egaga hisobot
```

**To'lov va yetkazish tizimdan tashqarida** — shop o'zi pul oladi va o'zi yetkazadi. Ovozli hisobot — o'zbekcha sinovdan o'tgach beta.

**Stage 1 tugadi deb qachon hisoblanadi:** haqiqiy shopda yuqoridagi yo'l to'liq ishlaydi; buyurtma va stokda xato, boshqa shop ma'lumoti ko'rinishi — nol; shopni ulash va oylik to'lov sinovga tayyor. Xaridorlar uchun umumiy bozor hali yo'q.

---

## Stage 2 — Shoplar tarmog'i

**Kimga:** o'nlab va yuzlab shoplar, ayniqsa kassa yoki hisob dasturi ishlatadigan va ko'p filialli shoplar.

**Nima beramiz:** shop o'zi ro'yxatdan o'tadi; kassa va hisob dasturlari bilan bog'lanish; narx va qoldiq qaysi manbadan olinishi sozlanadi; bir xil mahsulotlar umumiy katalogga birlashadi; shop xohlasa takliflarini ommaviy qiladi; tashqi tizimlar uchun API.

**Kim pul to'laydi:** shop — obuna, yuqori tarif va integratsiyalar uchun. Global qidiruvda yuqori o'rinni pulga sotib bo'lmaydi.

**Modullar:** `M21`–`M30`; Stage 1 ning hamma imkoniyatlari davom etadi.

**Stage 2 tugadi deb qachon hisoblanadi:** shop o'zi ulanadi; ikki va undan ortiq shop bir xil modelni to'g'ri bitta umumiy mahsulotga bog'laydi; shop taklifini qaytarib olsa, u darhol ko'rinmaydi; ma'lumot qayerdan kelgani ko'rinadi. Umumiy tarmoq hali yopiq beta bo'lishi mumkin.

---

## Stage 3 — Global AI qidiruv

**Kimga:** O'zbekistondagi xaridorlar va yangi mijoz izlayotgan shoplar.

**Nima beramiz:** sayt va Telegram orqali global qidiruv; bir mahsulotni turli shoplarda narx, yetkazish, kafolat va holat bo'yicha solishtirish; xarita, filial, olib ketish; faqat ochiq ma'lumotga tayanadigan AI maslahatchi; xaridor roziligi bilan shopga yo'naltirish; narx tushganda xabar berish.

**Kim pul to'laydi:** boshida — shop obunasi. Keyinroq — aniq "reklama" deb belgilangan o'rinlar va tasdiqlangan yo'naltirishlar uchun to'lov. Xaridor qidiruv uchun pul to'lamaydi.

**Modullar:** `M31`–`M39`.

**Stage 3 tugadi deb qachon hisoblanadi:** ko'p qidiriladigan mahsulotlarda kamida 2 ta dolzarb, solishtirsa bo'ladigan taklif bor; eskirgan yoki noto'g'ri takliflar nazorat qilinadi; tartiblash xolis; xaridorga haqiqiy foyda ma'lumotlar bilan tasdiqlangan.

---

## Hozir qilmaydigan narsalar

- O'z omborimiz va yetkazish tizimimiz, barcha shoplar pulini platforma orqali o'tkazish, xaridorni himoya qilish va nizolarni hal qilish — Stage 1 da qurilmaydi.
- Qishloq xo'jaligi, ulgurji savdo, xalqaro soliqlar, boshqa brend ostidagi bozor, AI marketing — alohida yo'nalishlar (`11` §4).
- Ijtimoiy tarmoqlarni norasmiy usullar bilan avtomatlashtirish qabul qilinmaydi. Har kanal faqat rasmiy ruxsat bo'lsa yoqiladi.

## Nimani va'da qilamiz va qanday tekshiramiz

| Kim uchun | Va'da | Nimani o'lchaymiz |
|---|---|---|
| Shop | Xaridorga tez javob va operatorga tayyor lead | Birinchi javob vaqti, kechikkan javoblar, sifatli leadlar |
| Shop | Narx va qoldiq bir joyda | Narx yangiligi, noto'g'ri narx holatlari, qoldiq farqlari |
| Shop | Saytsiz ham online savdo | Ochilgan saytlar, taklif so'rovlari, buyurtmalar |
| Shop | Egaga ishonchli hisobot | Raqamlar to'g'riligi, ovozni tanish aniqligi |
| Shoplar tarmog'i | Shopni tez ulash | Ulash vaqti, sinxronlash holati, yordamga ketgan vaqt |
| Xaridor | To'g'ri va qulay taklifni solishtirish | To'g'ri solishtirishlar, noto'g'ri narx ulushi, yo'naltirishlar |

## Uch bosqich qanday bog'langan

```
Shopning o'z ma'lumotlari va savdo tizimi (Stage 1)
   ──▶ shop rozilik bergan ommaviy takliflar (Stage 2)
   ──▶ umumiy mahsulot va tekshirilgan takliflar (Stage 2)
   ──▶ xaridorning global qidiruvi va AI maslahatchisi (Stage 3)
   ──▶ xaridor roziligi bilan shopga yo'naltirish
   ──▶ yana shopning savdo tizimiga (Stage 1)
```

**Asosiy tamoyil:** shop savdo tizimi uchun alohida pul to'laydi va undan foyda oladi. Global qidiruvga qo'shilish majburiy emas.

## Cheklovlar

1. Shop birinchi foydani global qidiruvda xaridorlar bo'lmasa ham oladi.
2. Katalog yoki qoldiq noaniq bo'lsa, AI sotmaydi — taklif operatorga o'tadi.
3. AI uchala tilda (o'zbek, rus, ingliz) ishlaydi, lekin ovozni tanish sifati sinovsiz kafolatlanmaydi.
4. Xaridorning shaxsiy ma'lumoti va buyurtmalari shop ichida qoladi, global qidiruvga chiqmaydi.
5. Batafsil: modullar — `02`, qoidalar — `03`, holatlar — `05`, sahifalar — `06`, sinovlar — `10`.
