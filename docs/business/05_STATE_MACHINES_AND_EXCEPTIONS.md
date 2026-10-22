# 05 — Holatlar: buyurtma, taklif, suhbat va boshqalar qanday o'zgaradi

**Versiya:** v2 (2026-10-22, oddiy tilda qayta yozildi). Qarorlar: `../decisions/DECISION_REGISTER.md`.

## Bu hujjat nima uchun

Tizimdagi har bir muhim narsa — buyurtma, taklif, suhbat, shop akkaunti — ma'lum **holatlardan** o'tadi. Masalan, buyurtma avval "qoralama", keyin "tasdiqlandi", oxirida "topshirildi" bo'ladi. Bu hujjat:

- har bir narsaning qanday holatlari borligini,
- bir holatdan boshqasiga **kim** o'tkaza olishini,
- o'tishda **tizim nima qilishini** (masalan, mahsulotni band qiladi),
- **nima taqiqlanganini**

tushuntiradi. Dasturchilar ham, operatorlar ham, do'kon egasi ham shu qoidalarga tayanadi.

## Qanday o'qish kerak

```
Holat A ──(kim nima qiladi)──▶ Holat B   [tizim nima qiladi]
```

- Strelka ustidagi qavs — o'tishni kim yoki nima boshlaydi.
- Kvadrat qavs `[...]` — o'tish paytida tizim avtomatik bajaradigan ish.
- Har holatning yonida qavs ichida kodda qanday yozilishi beriladi, masalan "Qoralama (`DRAFT`)".
- Strelka bilan ko'rsatilmagan o'tish **mumkin emas**. Tizim uni rad etadi.

## Hamma holatlar uchun umumiy qoidalar

1. Holatni faqat tizimning tegishli amali o'zgartiradi. Hech kim bazada holatni qo'lda o'zgartirmaydi.
2. Har bir o'zgarish yozib qo'yiladi: kim, qachon, nima uchun (audit).
3. Ikki kishi bir vaqtda bitta narsani o'zgartirmoqchi bo'lsa, birinchisi o'tadi. Ikkinchisiga "ma'lumot o'zgardi, sahifani yangilang" deyiladi.
4. Bir xil amal ikki marta yuborilsa (masalan, tugma ikki marta bosilsa), u bir marta bajariladi.
5. "Kutilmoqda" degan holat hech qachon "bajarildi" degani emas.

Stage 1 da (birinchi bosqichda) **to'lov va yetkazish tizimdan tashqarida**: pulni shop o'zi oladi, yetkazishni o'zi tashkil qiladi (DEC-100, DEC-113). Shuning uchun to'lov va yetkazish holatlari bu bosqichda ishlatilmaydi (oxirida qisqacha berilgan).

---

# 1-qism. Savdo jarayoni (Stage 1 ning asosi)

Xaridor yozganidan mahsulotni olib ketguncha besh narsa holatini o'zgartiradi: **suhbat → lead → taklif → buyurtma → rezerv**. Quyida ularning har biri.

## Suhbat (FSM-04)

**Bu nima:** xaridor bilan Telegram, Instagram yoki saytdagi chat orqali yozishma. Eng muhim savol: hozir xaridorga **kim javob beradi** — AI yoki operator?

```
Yangi (NEW) ──(birinchi xabar keldi)──▶ AI javob beryapti (AI_ACTIVE)

AI javob beryapti ──(AI javob berdi, xaridor javobini kutyapti)──▶ Xaridor javobi kutilmoqda (WAITING_CUSTOMER)
AI javob beryapti ──(AI operatorni chaqirdi)──▶ Operator kerak (HUMAN_NEEDED)   [operatorga vazifa va xabar]

Operator kerak ──(operator suhbatni oldi)──▶ Operator javob beryapti (HUMAN_ACTIVE)   [AI endi yoza olmaydi]
Operator javob beryapti ──(operator javob berdi)──▶ Xaridor javobi kutilmoqda
Xaridor javobi kutilmoqda ──(xaridor yozdi)──▶ Operator javob beryapti   [agar suhbatni operator olgan bo'lsa]
Operator javob beryapti ──(operator "AI'ga qaytarish"ni bosdi)──▶ AI javob beryapti   [AI operatorning oxirgi javoblarini o'qiydi]
Operator javob beryapti ──(operator suhbatni yopdi)──▶ Yopildi (RESOLVED)

Yopildi ──(xaridor yana yozdi)──▶ Qayta ochildi (REOPENED)   [oldingi tarix saqlanadi]
```

**Eng muhim qoida:** bir vaqtda faqat bitta tomon javob yoza oladi — yo AI, yo operator. Operator suhbatni olgan zahoti AI tayyorlab turgan javob ham yuborilmaydi.

> **Misol:** AI xaridorga javob yozayotgan paytda operator "Suhbatni olish" tugmasini bosdi. AI javobi tayyor bo'lsa ham xaridorga ketmaydi. Xaridor faqat operator javobini ko'radi.

**AI qachon operatorni chaqiradi:** xaridor odam so'rasa; "olaman" desa (buyurtma qoralamasi yaratilgach); narx yoki mahsulot noaniq bo'lsa; xaridor norozi bo'lsa; kafolat, qaytarish yoki to'lov haqida so'rasa; chegirma so'rasa. To'liq ro'yxat — `engineering/26` §9.

## Lead — sotuv imkoniyati (FSM-05)

**Bu nima:** "bu xaridor biror narsa sotib olishi mumkin" degan yozuv. Shop egasi qancha xaridor qiziqdi va qanchasi sotib oldi, shuni ko'radi.

```
Yangi (NEW) ──(xaridor ehtiyojini aytdi: byudjet, maqsad)──▶ Aniqlandi (QUALIFIED)
Aniqlandi ──(PC uchun taklif yuborildi)──▶ Taklif berildi (QUOTED)
Aniqlandi yoki Taklif berildi ──(buyurtma topshirildi)──▶ Yutildi (WON)
Aniqlandi yoki Taklif berildi ──(xaridor voz kechdi)──▶ Yo'qotildi (LOST)   [sabab yoziladi]
Yo'qotildi ──(xaridor qaytib keldi)──▶ Aniqlandi
```

**Yo'qotish sababi tanlanadi:** qimmat, mahsulot yo'q, mos emas, javob bermadi, raqobatchidan oldi, boshqa. AI sababni taxmin qilsa, "ehtimoliy" deb belgilanadi.

## Taklif — PC yig'ma uchun (FSM-06)

**Bu nima:** xaridorga yuboriladigan rasmiy narxli taklif: qaysi qismlar, narxi, jami summa, qancha muddat amal qilishi. **Faqat PC yig'ma va maxsus narx uchun** ishlatiladi. Oddiy mahsulot (masalan, bitta videokarta) taklifsiz, to'g'ridan-to'g'ri buyurtmaga o'tadi (DEC-100e).

```
Qoralama (DRAFT) ──(AI yoki operator yig'mani tuzdi, tekshiruvga yubordi)──▶ Tekshiruvda (REVIEW)
                                                   [qismlar mosligi tekshiriladi]
Tekshiruvda ──(menejer yoki ega tasdiqladi)──▶ Tasdiqlandi (APPROVED)   [narxlar muzlatiladi, muddat boshlanadi]
Qoralama ──("faqat xavfli holatlarda" rejimi: qismlar mos, chegirma yo'q, summa chegaradan kichik)──▶ Tasdiqlandi   [avtomatik]
Tasdiqlandi ──(xaridorga yuborildi)──▶ Yuborildi (SENT)
Yuborildi ──(xaridor "qabul qilaman" dedi)──▶ Qabul qilindi (ACCEPTED)   [buyurtma qoralamasi yaratiladi]
Yuborildi ──(muddat tugadi)──▶ Muddati o'tdi (EXPIRED)
Yuborildi ──(xaridor rad etdi)──▶ Rad etildi (REJECTED)
Rad etildi ──(operator o'zgartiradi)──▶ yangi versiya, yana Qoralama
```

**Kim tasdiqlaydi:** faqat menejer (o'z limiti ichida) yoki ega. Operator o'zi tuzgan taklifni o'zi tasdiqlay olmaydi (DEC-109). Pilot davrida **har bir taklif** tasdiqdan o'tadi. Keyin ega "faqat xavfli holatlarda tasdiqlash" rejimini yoqishi mumkin: summa katta bo'lsa, qismlar mosligi noaniq bo'lsa yoki chegirma bo'lsa (DEC-102).

**Qismlar mosligi:** tizim har yig'mani tekshiradi.
- **Mos** — yuborish mumkin.
- **Tekshirish kerak** — ma'lumot yetmaydi, masalan BIOS qo'llab-quvvatlashi noma'lum. Menejer sababini yozib tasdiqlashi kerak.
- **Mos emas** — masalan, protsessor soketi platanikiga to'g'ri kelmaydi. Bunday taklifni yuborib bo'lmaydi.

Batafsil: `engineering/25`.

**Muddat:** standart holatda 24 soat, shop o'zgartira oladi (DEC-103). Xaridor qabul qilganda narx va mavjudlik baribir qayta tekshiriladi.

**Taqiqlar:** yuborilgan taklif o'zgartirilmaydi. O'zgarish kerak bo'lsa, yangi versiya yaratiladi va eski taklif tarixda qoladi.

> **Misol:** xaridorga 9,8 mln so'mlik yig'ma yuborildi. Ertasiga shop videokarta narxini oshirdi. Yuborilgan taklif o'zgarmaydi. Xaridor ertaga "olaman" desa, tizim yangi narxni ko'rsatadi va xaridordan qayta rozilik so'raladi.

## Buyurtma (FSM-08)

**Bu nima:** xaridor olmoqchi bo'lgan narsaning yozuvi. Stage 1 da buyurtma **to'lovsiz**: pulni shop o'zi oladi.

```
                     (AI, sayt yoki operator yaratadi)
                                   │
                                   ▼
Qoralama (DRAFT) ──(operator ko'rib chiqishni boshladi / xaridor saytda yubordi)──▶ Tasdiq kutilmoqda (PENDING_CONFIRMATION)
                                                       [operatorga vazifa va xabar]

Tasdiq kutilmoqda ──(operator yoki menejer mahsulot borligini tasdiqladi)──▶ Tasdiqlandi (CONFIRMED)
                                                       [mahsulot shu xaridor uchun band qilinadi]

Tasdiqlandi ──(yig'ish yoki tayyorlash boshlandi)──▶ Tayyorlanmoqda (PROCESSING)

Tayyorlanmoqda ──("olib ketishga tayyor" tugmasi)──▶ Tayyorlanmoqda   [holat o'zgarmaydi, xaridorga xabar ketadi]

Tayyorlanmoqda ──(xaridor mahsulotni oldi)──▶ Topshirildi (COMPLETED)
                                                       [mahsulot ombordan chiqadi, lead "Yutildi"]

Qoralama ──(operator yoki xaridor bekor qildi)──▶ Bekor qilindi (CANCELLED)
Tasdiq kutilmoqda yoki Tasdiqlandi ──(menejer yoki ega bekor qildi, sabab bilan)──▶ Bekor qilindi
                                                       [band qilingan mahsulot bo'shatiladi]

Tayyorlanmoqda ──(muammo: mahsulot shikastlangan, xaridor bosh tortdi...)──▶ Muammoli (EXCEPTION)
Muammoli ──(menejer hal qildi)──▶ Tayyorlanmoqda yoki Bekor qilindi
```

**Har bir o'tish batafsil:**

**Qoralama → Tasdiq kutilmoqda**
- **Kim:** operator, yoki xaridorning o'zi saytda "Buyurtma berish" tugmasini bossa.
- **Tizim:** operatorga vazifa va xabar yuboradi.
- **Muhim:** qoralama mahsulotni band qilmaydi. AI yaratgan qoralamani albatta odam ko'rib chiqadi (DEC-100c, DEC-100d).

**Tasdiq kutilmoqda → Tasdiqlandi** — eng muhim qadam
- **Kim:** shu buyurtmaga biriktirilgan operator yoki menejer (DEC-108).
- **Tizim:** ombordagi qoldiqni shu zahoti qayta tekshiradi.
  - Mahsulot bor bo'lsa, uni shu xaridor uchun band qiladi.
  - Yo'q bo'lsa, tasdiqlamaydi va "mahsulot qolmagan" deydi; operator muqobil taklif qiladi.
  - Narx o'zgargan bo'lsa, avval xaridordan qayta rozilik olinadi.
- **Taqiq:** AI tasdiqlay olmaydi. Boshqa operatorga biriktirilgan buyurtmani tasdiqlab bo'lmaydi.
- **Misol:** omborda 1 ta RTX 4060 qoldi. Uni ikki operator bir vaqtda tasdiqlamoqchi bo'ldi, shu paytning o'zida do'konda ham sotildi. Faqat bittasi o'tadi, qolganlari "mahsulot qolmagan" xabarini oladi.

**Tasdiqlandi → Tayyorlanmoqda**
- **Kim:** operator, omborchi yoki menejer.
- **Tizim:** mahsulotni "band" holatidan "ajratilgan" holatiga o'tkazadi (pastda "Rezerv" bo'limiga qarang) va xaridorga xabar yuboradi.

**Tayyorlanmoqda → Topshirildi**
- **Kim:** operator yoki menejer.
- **Tizim:** mahsulot ombor qoldig'idan chiqariladi, faqat bir marta. Lead "Yutildi" bo'ladi.
- **Qo'shimcha:** pul olinganini xodim xohlasa "to'landi" deb belgilaydi. Tizim buni tekshirmaydi, hisobotda "tekshirilmagan" deb ko'rsatiladi (DEC-100a).

**Bekor qilish**
- **Kim:** faqat menejer yoki ega, sababi yozilishi shart. Operator bekor qila olmaydi (DEC-108).
- **Tizim:** band qilingan mahsulot bo'shatiladi, faqat bir marta. Lead "Yo'qotildi" bo'ladi.
- **Pul qaytarish** kerak bo'lsa, buni shop o'zi tizimdan tashqarida qiladi. Tizimda izoh qoldiriladi.

**Topshirilgan buyurtma** qaytarib ochilmaydi. Mahsulot qaytarilsa yoki nosoz bo'lsa, kafolat murojaati ochiladi (pastda).

**Ma'lumotlar:** buyurtmada xaridorning tanlovi saqlanadi — olib ketadimi (`PICKUP`) yoki yetkazib beriladimi (`DELIVERY`), yetkazilsa manzil. Yetkazish narxi operator bilan gaplashib kelishiladi (DEC-100h).

## Rezerv — mahsulotni band qilish (FSM-07)

**Bu nima:** buyurtma uchun ombordagi mahsulotni "bu sotilgan, boshqaga va'da qilma" deb belgilash. Ombordagi har bir mahsulot uchun uch xil son yuritiladi:

- **Qoldiq** (`on_hand`) — omborda jismonan nechta bor.
- **Band** (`reserved`) — tasdiqlangan, lekin hali tayyorlanmagan buyurtmalar uchun.
- **Ajratilgan** (`allocated`) — tayyorlanayotgan buyurtmalar uchun.

**Sotuvga mavjud** = qoldiq − band − ajratilgan. AI va sayt xaridorga faqat shu sonni asos qilib "bor" deydi.

```
(buyurtma tasdiqlandi) ──▶ Faol (ACTIVE)             [band +1]
Faol ──(buyurtma tayyorlanmoqda)──▶ Ajratilgan (ALLOCATED)   [band −1, ajratilgan +1]
Ajratilgan ──(buyurtma topshirildi)──▶ Ishlatildi (CONSUMED)   [ajratilgan −1, qoldiq −1]
Faol yoki Ajratilgan ──(buyurtma bekor qilindi)──▶ Bo'shatildi (RELEASED)   [band yoki ajratilgan −1]
Faol ──(menejer "muddati o'tdi" deb bekor qildi)──▶ Muddati o'tdi (EXPIRED)
```

**Qoidalar:**
- Sotuvga mavjud son hech qachon noldan kam bo'lmaydi.
- Rezerv **avtomatik bekor bo'lmaydi.** Mahsulot 72 soatdan ko'p band turib qolsa (xaridor olib ketmasa), menejerga "bekor qilinsinmi?" degan vazifa tushadi. Qarorni odam qabul qiladi (DEC-104).
- Do'kondagi oddiy sotuv ("tez sotuv" tugmasi) qoldiqni darhol kamaytiradi. Agar mahsulot band qilingan bo'lsa, tizim uni sotishga ruxsat bermaydi (DEC-123).

---

# 2-qism. Shop va uning sozlamalari

## Shop akkaunti (FSM-01)

```
Qoralama (DRAFT) ──(ega ro'yxatdan o'tish ma'lumotlarini yubordi)──▶ Tekshiruvda (PENDING_VERIFICATION)
Tekshiruvda ──(platforma jamoasi faollashtirdi)──▶ Faol (ACTIVE)
Faol ──(platforma to'xtatdi: qoidabuzarlik, to'lov yo'q)──▶ To'xtatilgan (SUSPENDED)
To'xtatilgan ──(muammo hal qilindi)──▶ Faol
Faol ──(ega va platforma yopishga kelishdi)──▶ Yopilgan (CLOSED)   [ma'lumot eksporti, keyin o'chirish]
```

- Stage 1 da har shopni platforma jamoasi qo'lda faollashtiradi: katalogni tekshiradi, sozlaydi (DEC-122, `business/13`).
- To'xtatilgan shopda yangi savdo bo'lmaydi, lekin mavjud buyurtmalarni oxiriga yetkazish mumkin.

## Xodim (a'zolik)

```
Taklif qilindi (INVITED) ──(xodim taklifni qabul qildi)──▶ Faol (ACTIVE)
Faol ──(ega o'chirdi)──▶ O'chirilgan (DISABLED)   [barcha sessiyalari darhol tugaydi]
```

Oxirgi egani o'chirib bo'lmaydi: avval boshqa ega tayinlanadi.

## Mahsulotni saytga chiqarish (FSM-02)

```
Qoralama (DRAFT) ──(katalog xodimi tekshiruvga yubordi)──▶ Tekshiruvda (IN_REVIEW)   [majburiy maydonlar tekshiriladi]
Tekshiruvda ──(menejer tasdiqladi)──▶ Chiqarilgan (PUBLISHED)   [sayt va AI ko'radi]
Chiqarilgan ──(menejer yashirdi)──▶ Yashirilgan (HIDDEN)   [yangi buyurtmaga kirmaydi]
Yashirilgan ──(qayta chiqarildi)──▶ Chiqarilgan   [narx va qoldiq qayta tekshiriladi]
Chiqarilgan ──(ega arxivladi)──▶ Arxivda (ARCHIVED)   [eski buyurtmalardagi ma'lumot saqlanadi]
```

Narxi yo'q mahsulot saytga chiqmaydi.

## Kanal ulanishi — Telegram, Instagram (FSM-03)

```
Kutilmoqda (PENDING) ──(ega ruxsat berdi, sinov xabari o'tdi)──▶ Ulangan (CONNECTED)
Ulangan ──(xatolar ko'paydi yoki token muddati yaqin)──▶ Muammoli (DEGRADED)   [egaga ogohlantirish]
Muammoli ──(ega qayta uladi)──▶ Ulangan
Ulangan yoki Muammoli ──(ega uzdi yoki ruxsat olib tashlandi)──▶ Uzilgan (DISCONNECTED)   [xabar yuborish to'xtaydi]
```

Ruxsat yo'q kanalni "ulangan" deb ko'rsatish taqiqlanadi.

---

# 3-qism. Sotuvdan keyin va xabarlar

## Kafolat murojaati (FSM-11)

**Bu nima:** xaridor "mahsulot ishlamayapti" yoki "qaytarmoqchiman" deb murojaat qilganda ochiladi (DEC-114).

```
Yangi (NEW) ──(operator ko'rib chiqishni boshladi)──▶ Ko'rib chiqilmoqda (IN_REVIEW)
Ko'rib chiqilmoqda ──(menejer qabul qildi)──▶ Qabul qilindi (APPROVED)
Ko'rib chiqilmoqda ──(menejer rad etdi, sabab bilan)──▶ Rad etildi (REJECTED)
Qabul qilindi ──(mahsulot qabul qilindi, tekshirilmoqda)──▶ Xizmatda (IN_SERVICE)   [omborda "tekshiruvda" deb turadi, sotilmaydi]
Xizmatda ──(ta'mirlandi / almashtirildi / qaytarildi)──▶ Hal qilindi (RESOLVED)
Hal qilindi ──(xaridor tasdiqladi yoki muddat o'tdi)──▶ Yopildi (CLOSED)
```

- Kafolat shartlari mahsulot sotilgan paytdagidek saqlanadi. Keyin shop shartlarni o'zgartirsa ham, eski sotuvga ta'sir qilmaydi.
- Qaytarilgan mahsulot tekshirilmaguncha qayta sotuvga chiqmaydi.
- Pul qaytarish shop tomonidan tizimdan tashqarida qilinadi.

## Xabar yuborish (FSM-12)

```
Kutilmoqda (PENDING) ──(yuborish vaqti keldi)──▶ Rejalashtirilgan (SCHEDULED)
Rejalashtirilgan ──(muvaffaqiyatli yuborildi)──▶ Yuborildi (SENT)
Rejalashtirilgan ──(xato, qayta urinish)──▶ Rejalashtirilgan   [5 martagacha]
Rejalashtirilgan ──(5 marta xato)──▶ Yuborilmadi (FAILED)   [xodimga vazifa]
Kutilmoqda ──(xaridor rad etgan yoki kanal qoidasi ruxsat bermaydi)──▶ To'xtatildi (SUPPRESSED)
```

Bitta hodisa uchun xaridorga bitta xabar ketadi, hatto hodisa takror kelsa ham.

---

# 4-qism. Kutish muddatlari (eslatmalar)

| Nima kutyapti | Qancha vaqtdan keyin | Nima bo'ladi |
|---|---|---|
| PC taklifi | 24 soat (shop sozlaydi) | Taklif "Muddati o'tdi" bo'ladi, xaridorga yangi taklif kerak |
| Tasdiq kutayotgan buyurtma | 24 soat | Operator va menejerga eslatma. Avtomatik bekor qilinmaydi |
| Band qilingan, lekin olib ketilmagan mahsulot | 72 soat | Menejerga "bekor qilinsinmi?" vazifasi |
| Operatorni kutayotgan suhbat | shop sozlaydi | Menejerga eslatma |

Hech qanday buyurtma yoki rezerv avtomatik bekor qilinmaydi: qarorni har doim odam qabul qiladi.

---

# 5-qism. Bir nechta narsa birga o'zgaradigan holatlar

**Buyurtmani tasdiqlash.** Tizim bir vaqtda uchta ishni bajaradi: qoldiqni tekshiradi, mahsulotni band qiladi, buyurtmani "Tasdiqlandi" qiladi. Uchalasi birga bajariladi yoki birortasi ham bajarilmaydi. Mahsulot yetmasa, buyurtma "Tasdiq kutilmoqda" holatida qoladi va xaridorga "tasdiqlandi" degan xabar ketmaydi.

**Buyurtmani bekor qilish.** Band qilingan mahsulot aynan bir marta bo'shatiladi. Bekor qilish tugmasi ikki marta bosilsa ham, qoldiq ikki marta qaytmaydi.

**Operator suhbatni olishi.** AI hali javob tayyorlayotgan bo'lsa ham, uni yuborishdan oldin tizim "hozir kim javob beradi?" deb qayta tekshiradi. Operator olgan bo'lsa, AI javobi tashlab yuboriladi.

**Xabar yuborilmay qolishi.** Buyurtma holati baribir to'g'ri saqlanadi; xabar qayta yuboriladi. Buyurtma xabar yuborilganmi-yo'qmi, shunga bog'liq emas.

---

# 6-qism. Keyingi bosqichlar uchun (hozir ishlatilmaydi)

## To'lov (FSM-09) — keyinga qoldirilgan (DEC-100)

To'lov moduli qo'shilganda: to'lov boshlandi → tasdiq kutilmoqda → tasdiqlandi (to'lov provayderi yoki bank tekshiruvi bilan) / muvaffaqiyatsiz / bekor; tasdiqlangan to'lovni qaytarish alohida jarayon. Asosiy qoida: chek rasmi hech qachon "to'landi" degani emas.

## Yetkazish (FSM-10) — keyinga qoldirilgan (DEC-113)

Yetkazish moduli qo'shilganda: tayyor → kuryerga berildi → yo'lda → yetkazildi (dalil bilan) / muammo → qayta rejalashtirildi yoki qaytarildi. Hozircha yetkazish buyurtmaning "Tayyorlanmoqda → Topshirildi" qadamlari ichida.

## Stage 2 (shoplar tarmog'i)

- **Integratsiya ulanishi (FSM-13):** qoralama → ruxsat berildi → sinxronlanmoqda → sog'lom / muammoli → bekor qilingan. Tashqi tizim (POS, ERP) bilan ma'lumot almashish.
- **Ommaviy taklif (FSM-14):** yopiq → tekshiruvda → chiqarilgan → eskirgan / qaytarib olingan / yashirilgan. Shop roziligi bilan mahsulotini global qidiruvga chiqarish. Shop rozilikni qaytarib olsa, mahsulot darhol ko'rinmay qoladi.
- **Mahsulot moslash (FSM-15):** moslanmagan → nomzod → tekshiruvda → moslangan / rad etilgan; moslash bekor qilinishi mumkin. Turli shoplardagi bir xil modelni bir-biriga bog'lash. Shubha bo'lsa, avtomatik birlashtirilmaydi.
- **Shopni tasdiqlash (FSM-16):** tasdiqlanmagan → tekshiruvda → tasdiqlangan (muddati bilan) / rad etilgan → muddati o'tgan. "Tasdiqlangan shop" belgisi uchun.

## Stage 3 (global qidiruv)

- **Xaridorni shopga yo'naltirish (FSM-17):** yaratildi → yetkazildi → shop javob berdi → sotuv bo'ldi / yo'qotildi; javob bo'lmasa muddati o'tadi.
- **Narx ogohlantirishi (FSM-18):** faol → ishga tushdi / muddati o'tdi / xaridor bekor qildi.

---

**Kodda ishlatiladigan nomlar:** har holatning qavs ichidagi nomi (`DRAFT`, `CONFIRMED` …) API va bazada aynan shunday yoziladi. Barcha boshqa hujjatlar holat nomlarini shu yerdan oladi.
