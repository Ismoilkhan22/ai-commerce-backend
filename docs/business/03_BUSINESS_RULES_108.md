# 03 — Biznes qoidalari

**Versiya:** v2 (2026-10-22, oddiy tilda qayta yozildi). 111 ta qoida: `BL-001` … `BL-111`. Fayl nomidagi "108" tarixiy qoldi.

## Bu hujjat nima uchun

Bu yerda tizim **har doim** amal qilishi shart bo'lgan qoidalar yozilgan. Qoida buzilsa, amal bajarilmaydi yoki odam tasdig'iga yuboriladi. Dasturchilar shu qoidalarni kodga, sinovchilar esa testlarga aylantiradi.

**Har qoidada uchta narsa bor:**
- **Qachon** — qaysi vaziyatda qo'llaniladi.
- **Qoida** — tizim nima qilishi shart.
- **Aks holda** — qoida bajarilmasa nima bo'ladi.

**Belgilar:**
- ⏸ — qoida keyingi bosqichga qoldirilgan modulga tegishli (hozir ishlatilmaydi).
- Raqamlar (masalan, "24 soat", "5%") — boshlang'ich qiymatlar, shop sozlamalarda o'zgartira oladi (`decisions/DECISION_REGISTER.md`).

---

# Stage 1 qoidalari

## Shop va xodimlar

| ID | Qachon | Qoida | Aks holda |
|---|---|---|---|
| BL-001 | Shop ro'yxatdan o'tadi | Kamida bitta tasdiqlangan ega bo'ladi | Ega tasdiqlanmaguncha shop faollashmaydi |
| BL-002 | Kimdir ma'lumot o'qiydi yoki yozadi | Faqat o'z shopi ma'lumotiga ruxsat | Boshqa shop ma'lumoti so'ralsa "topilmadi" deyiladi va bu urinish yozib qo'yiladi |
| BL-003 | Shop ishga tushiriladi | Egasi, kontaktlari va shartlar tasdiqlangan bo'lishi kerak; Stage 1 da platforma jamoasi faollashtiradi | Shop "tekshiruvda" holatida qoladi |
| BL-004 | Shop to'xtatiladi yoki yopiladi | Yangi savdo va saytga chiqarish to'xtaydi | Mavjud buyurtmalarni yakunlashga ruxsat beriladi |
| BL-005 | Xodim biror amal qiladi | Rol, filial va egalik tekshiriladi; ruxsat berilmagan narsa taqiqlangan | Rad etiladi va yozib qo'yiladi |
| BL-006 | Katta chegirma, katta stok tuzatish | Limitdan oshsa yuqoriroq rol tasdiqlaydi | Tasdiq kelguncha hech narsa o'zgarmaydi |
| BL-007 | Ega o'zini o'chirmoqchi | Oxirgi egani o'chirib bo'lmaydi | "Avval boshqa ega tayinlang" |
| BL-008 | AI biror amal qilmoqchi | AI ham ruxsatlardan tashqariga chiqa olmaydi | Amal rad etiladi, suhbat operatorga uzatiladi |

## Filiallar

| ID | Qachon | Qoida | Aks holda |
|---|---|---|---|
| BL-009 | Filial manzili saytga chiqariladi | Manzil va xaritadagi joyni shop tasdiqlagan bo'lishi kerak | Tasdiqlanmagan joy ko'rsatilmaydi |
| BL-010 | Filial yopiq yoki ish vaqti o'zgardi | Olib ketish taklifi filial holatiga qarab beriladi | Yopiq filialdan olib ketish taklif qilinmaydi |

## Katalog

| ID | Qachon | Qoida | Aks holda |
|---|---|---|---|
| BL-011 | Yangi variant (SKU) qo'shiladi | Shop ichida SKU kodi yagona; variant va holat (yangi/ishlatilgan) alohida saqlanadi | Takror kod qabul qilinmaydi |
| BL-012 | Mahsulot saytga chiqariladi | Narx va majburiy maydonlar to'ldirilgan bo'lishi kerak | Mahsulot qoralamada qoladi |
| BL-013 | Fayldan yuklash | Avval sinov; xato qatorlar ko'rsatiladi; faqat tanlangan to'g'ri qatorlar saqlanadi | Qaysi qatorlar o'tdi va qaysilari o'tmadi — hisobot |
| BL-014 | Mahsulot arxivlanadi | Yangi buyurtmaga kirmaydi | Eski buyurtmalardagi ma'lumot o'chirilmaydi |

## Narx va chegirma

| ID | Qachon | Qoida | Aks holda |
|---|---|---|---|
| BL-015 | Narx belgilanadi | Narxda valyuta, versiya va manba bo'ladi; pul butun son sifatida saqlanadi | Noto'g'ri narx (manfiy, nol, valyutasiz) qabul qilinmaydi |
| BL-016 | Narx o'zgardi | Yuborilgan taklifdagi narx o'zgarmaydi; buyurtma tasdiqlanganda yangi narx tekshiriladi | Xaridordan qayta rozilik so'raladi |
| BL-017 | Chegirma beriladi | Operator 0% (faqat so'raydi), menejer 5% gacha, undan yuqorisi — ega; tannarx operatorga ko'rinmaydi | Limitdan katta chegirma tasdiqga yuboriladi |
| BL-018 | Narx dollarda | Xaridorga shop kursi bo'yicha so'mda ko'rsatiladi; kurs manbai va vaqti saqlanadi | Kurs eskirgan bo'lsa, yakuniy taklif berilmaydi |

## Ombor

| ID | Qachon | Qoida | Aks holda |
|---|---|---|---|
| BL-019 | Mahsulot mavjudligi ko'rsatiladi | Sotuvga mavjud = qoldiq − band − ajratilgan; hech qachon noldan kam emas | Manfiy chiqsa sotuv to'xtatiladi va tekshiriladi |
| BL-020 | Buyurtma tasdiqlanadi | Mahsulot borligini tekshirish va band qilish bitta amalda | Yetmasa band qilinmaydi va tasdiqlanmaydi |
| BL-021 | Band bekor qilinadi | Faqat faol band bo'shatiladi; ikkinchi marta bo'shatish hech narsa qilmaydi | — |
| BL-022 | Stok tuzatiladi | Sababi, kim qilgani, vaqti va kerak bo'lsa tasdiq bilan | Sababsiz tuzatish qabul qilinmaydi |
| BL-023 | Ikki buyurtma bitta oxirgi mahsulotga | Faqat bittasi o'tadi | Ikkinchisiga "mahsulot qolmagan" |
| BL-109 | Do'konda oddiy sotuv ("tez sotuv") | Qoldiq darhol kamayadi; kim, qachon yozib qo'yiladi | Sotuvga mavjud sondan ko'p sotib bo'lmaydi |

## Shop sayti

| ID | Qachon | Qoida | Aks holda |
|---|---|---|---|
| BL-024 | Sayt mahsulot ko'rsatadi | Faqat shu shopning chiqarilgan mahsulotlari | — |
| BL-025 | Sayt manzili | Manzil yagona; o'z domeni bo'lsa tasdiqlanadi | Domen tasdiqlanmaguncha platforma manzili ishlatiladi |
| BL-026 | Mavjudlik eskirgan | Saytda belgilanadi; buyurtmada qayta tekshiriladi | Eski ma'lumot bilan buyurtma tasdiqlanmaydi |

## PC yig'ish

| ID | Qachon | Qoida | Aks holda |
|---|---|---|---|
| BL-027 | PC qismlari tanlandi | Moslikni AI emas, qat'iy qoidalar tekshiradi | "Mos emas" bo'lsa taklif yuborilmaydi |
| BL-028 | Qism haqida muhim ma'lumot noma'lum | Natija "tekshirish kerak", hech qachon "mos" emas | Menejer dalil bilan tasdiqlaydi |
| BL-029 | PC tavsiya qilinadi | Faqat narxi bor va sotuvda mavjud qismlar | Mavjud bo'lmagan qism tavsiya qilinmaydi |
| BL-030 | Moslik qoidalari yangilandi | Taklifda qaysi qoidalar versiyasi ishlatilgani saqlanadi | Yuborilmagan takliflar qayta tekshiriladi |

## Kanallar va suhbatlar

| ID | Qachon | Qoida | Aks holda |
|---|---|---|---|
| BL-031 | Kanal ulanadi | Faqat rasmiy ruxsat bilan; kalitlar xavfsiz joyda saqlanadi | Ruxsat bo'lmasa "ulangan" deb ko'rsatilmaydi |
| BL-032 | Xabar keladi | Avval tekshiriladi va saqlanadi, keyin qayta ishlanadi | Takror kelgan xabar bir marta hisoblanadi |
| BL-033 | Xaridorga xabar yuboriladi | Kanal qoidalariga amal qilinadi (masalan, Instagram'da 24 soat) | Yuborib bo'lmasa operatorga vazifa |
| BL-034 | Suhbatda javob yoziladi | Bir vaqtda faqat bitta tomon: AI yoki operator | Eskirgan javob yuborilmaydi |
| BL-035 | Xabarlar tartibsiz yoki takror keldi | Vaqt va xabar raqami bo'yicha to'g'ri tartib | Bitta xabarga ikki marta javob berilmaydi |
| BL-036 | Kontakt va marketing | Kontakt uchun ruxsat va reklama uchun ruxsat alohida | Reklamaga ruxsat bo'lmasa, reklama xabari yuborilmaydi |
| BL-037 | AI ishonchsiz yoki shikoyat, to'lov, kafolat | AI operatorga uzatadi | Operator navbatiga tushadi |

## AI sotuvchi

| ID | Qachon | Qoida | Aks holda |
|---|---|---|---|
| BL-038 | AI mahsulot haqida gapiradi | Faqat tizimdan olingan mahsulot, narx va qoldiq | Tasdiqlanmagan ma'lumot aytilmaydi |
| BL-039 | Xaridor matni yoki hujjatda "buyruq" bor | AI ularni bajarmaydi; shaxsiy ma'lumot tashqi AI'ga yuborilmaydi | Shubhali so'rov operatorga uzatiladi |
| BL-040 | AI limiti tugadi yoki AI ishlamayapti | Xaridorga operator mavjudligi aytiladi | Xabarlar operatorga ketadi |
| BL-041 | Taklif tuziladi | Narx, chegirma va yetkazishni tizim hisoblaydi | AI holatni o'zgartira olmaydi |
| BL-110 | Xaridor "olaman" dedi | AI faqat buyurtma qoralamasini yaratadi va operatorni chaqiradi; mahsulot band qilinmaydi | AI "tasdiqlandi" yoki "band qilindi" demaydi |

## Leadlar va takliflar

| ID | Qachon | Qoida | Aks holda |
|---|---|---|---|
| BL-042 | Lead yaratiladi | Kontakt faqat rozilik bilan; dublikatlar faqat shop ichida birlashtiriladi | Boshqa shop xaridori bilan birlashtirilmaydi |
| BL-043 | Taklif yaratiladi | Mahsulotlar, narxlar, holat va kafolat shartlari muzlatiladi | To'liq bo'lmagan taklif yuborilmaydi |
| BL-044 | Taklif muddati tugadi | Eski narxda buyurtma qilinmaydi | Yangi taklif kerak |
| BL-045 | Taklif tasdiqlanadi | Menejer (limit ichida) yoki ega; pilotda har taklif | Tasdiqsiz yuborib bo'lmaydi |

## Buyurtmalar

| ID | Qachon | Qoida | Aks holda |
|---|---|---|---|
| BL-046 | Buyurtma yaratiladi | Bir xil so'rov ikki buyurtma yaratmaydi | Takror so'rovga birinchi buyurtma qaytariladi |
| BL-047 | Buyurtma tasdiqlanadi | Odam tasdiqlaydi; qoldiq va narx qayta tekshiriladi | Farq bo'lsa xaridordan qayta rozilik |
| BL-048 | Buyurtma holati o'zgaradi | Faqat ruxsat etilgan o'tishlar (`05`), rol va sabab bilan | Noto'g'ri o'tish rad etiladi |
| BL-049 | Buyurtma bekor qilinadi | Faqat menejer yoki ega, sabab bilan; band qilingan mahsulot bir marta bo'shatiladi | — |
| BL-111 | Har qanday buyurtma (chat yoki saytdan) | Avtomatik tasdiqlanmaydi, odam tasdiqlaydi | Stage 2 da shop xohlasa avtomatik tasdiqni yoqishi mumkin |

## To'lov va yetkazish ⏸

Stage 1 da to'lov va yetkazish tizimdan tashqarida (DEC-100, DEC-113). Quyidagi qoidalar ular qo'shilganda ishlaydi.

| ID | Qachon | Qoida |
|---|---|---|
| BL-050 ⏸ | Xaridor chek rasmini yubordi | Chek "to'landi" degani emas; moliya xodimi haqiqiy tushumni tekshiradi |
| BL-051 ⏸ | To'lov provayderidan xabar keldi | Haqiqiyligi, summa, valyuta va hisob raqami tekshiriladi |
| BL-052 ⏸ | To'lov yoki qaytarish takror keldi | Bir marta hisoblanadi |
| BL-053 ⏸ | Pul qaytariladi | Sabab, tasdiq va aniq summa bilan; provayder tasdiqlamaguncha "qaytarildi" emas |
| BL-054 ⏸ | Yetkazish rejalashtiriladi | Manzil va kontakt tasdiqlangan bo'lishi kerak (hozir buyurtmada faqat manzil saqlanadi) |
| BL-055 ⏸ | Yetkazish holati o'zgaradi | Faqat tayinlangan kuryer yoki menejer; topshirilgani dalil bilan |
| BL-056 ⏸ | Yetkazib bo'lmadi | Sabab va qayta rejalashtirish yoziladi, xaridorga xabar beriladi |

## Kafolat va qaytarish

| ID | Qachon | Qoida | Aks holda |
|---|---|---|---|
| BL-057 | Mahsulot kafolat bilan sotildi | Kafolat shartlari sotuv paytidagidek saqlanadi | Keyingi o'zgarishlar eski sotuvga ta'sir qilmaydi |
| BL-058 | Qaytarish so'raldi | Ruxsatni odam beradi | — |
| BL-059 | Mahsulot qaytdi | Tekshirilmaguncha sotuvga chiqmaydi | Shikastlangan mahsulot ombor tarixida alohida belgilanadi |

## Xabarnomalar

| ID | Qachon | Qoida | Aks holda |
|---|---|---|---|
| BL-060 | Xabar yaratiladi | Qaysi hodisa, qaysi shablon va kimga ekani yoziladi | Bir hodisa uchun ikkinchi xabar yuborilmaydi |
| BL-061 | Xaridor xabarlardan voz kechgan | Reklama yuborilmaydi; faqat buyurtma bilan bog'liq xabarlar | — |
| BL-062 | Xabar yuborilmadi | Cheklangan marta qayta uriniladi | Keyin xodimga vazifa; xato yo'qolib ketmaydi |

## Hisobotlar

| ID | Qachon | Qoida | Aks holda |
|---|---|---|---|
| BL-063 | Raqam so'raladi | Har ko'rsatkichning aniq formulasi bor (`engineering/19-reporting-metrics.md`); "to'landi" — tekshirilmagan belgi | Formulasi yo'q raqam aytilmaydi |
| BL-064 | Ovozli savolda summa bor | Matn ko'rsatiladi va tasdiqlash so'raladi | Noaniq bo'lsa qayta so'raladi |
| BL-065 | Hisobot ko'rsatiladi | Har kim faqat ruxsat etilgan raqamlarni ko'radi; tannarx operatorga ko'rinmaydi | — |
| BL-066 | Javob beriladi | Davr, vaqt zonasi va ma'lumot qachon yangilangani ko'rsatiladi | Eskirgan ma'lumot belgilanadi |

## Tarif, AI va audit

| ID | Qachon | Qoida | Aks holda |
|---|---|---|---|
| BL-067 | Ishlatish hisoblanadi | Shop bo'yicha va aniq davrlar bo'yicha | Limit oshsa, egaga tushuntiriladi va qo'shimcha funksiyalar cheklanadi |
| BL-068 | Obuna to'lovi kechikdi | Imtiyozli muddat beriladi | Mavjud buyurtmalar ochiq qoladi |
| BL-069 | AI o'chirilgan | Katalog, inbox va buyurtmalar AI'siz ishlaydi | — |
| BL-070 | Shop yopiladi | Ma'lumot eksporti beriladi, kirish to'xtaydi, ma'lumot muddati bo'yicha o'chiriladi | Ommaviy takliflar qolmaydi |
| BL-071 | Muhim o'zgarish | Kim, qachon, nima o'zgargani (oldin va keyin) tarixga yoziladi | Tarixga yozib bo'lmasa, stok va pul bilan bog'liq o'zgarish bajarilmaydi |
| BL-072 | Tarix yoziladi | Parol, karta raqami va keraksiz shaxsiy ma'lumot yozilmaydi | — |

---

# Stage 2 va Stage 3 qoidalari (keyinroq)

| ID | Qachon | Qoida |
|---|---|---|
| BL-073 | Tashqi tizim (POS, ERP) ulanadi | Har maydon uchun (narx, qoldiq) qaysi tizim asosiy ekanligi aniq yoziladi; nizo bo'lsa odam ko'radi |
| BL-074 | Sinxronizatsiya ishlaydi | Takrorlarga chidamli, tezlik limitiga amal qiladi, holati ko'rinadi |
| BL-075 | Moslashda nizo | Avval sinov; noaniq yozuv ustiga yozilmaydi |
| BL-076 | Turli shoplardagi mahsulot bog'lanadi | Part number, brend, model va variant dalili bo'lishi kerak; shubhada avtomatik birlashtirilmaydi |
| BL-077 | Variantlar farq qiladi | Xotira hajmi, rang, holat, revision hech qachon jim birlashtirilmaydi |
| BL-078 | Noto'g'ri bog'lash | Bekor qilish mumkin; tarix saqlanadi |
| BL-079 | Shop mahsulotini global qidiruvga chiqaradi | Shop qaysi ma'lumot ochiq bo'lishini o'zi tanlaydi; standart holatda yopiq |
| BL-080 | Ommaviy taklif o'zgaradi yoki qaytarib olinadi | Qaytarib olish darhol kuchga kiradi, qidiruv indeksi kechiksa ham |
| BL-081 | Ommaviy taklif mazmuni | Faqat ruxsat etilgan narx, shartlar, filial; tannarx va xaridorlar hech qachon |
| BL-082 | Filiallar orasida ko'chirish | Jo'natilganda bir filialdan kamayadi, qabul qilinganda boshqasiga qo'shiladi; yo'lda kuzatiladi |
| BL-083 | Tarif o'zgaradi | Sana va hisob aniq; kutilmagan to'lov olinmaydi |
| BL-084 | AI bilimlari yangilanadi | Tasdiqlanmaguncha AI ishlatmaydi |
| BL-085 | Qidiruv indeksi yangilanadi | Eski yangilanish yangisini bosib o'tmaydi |
| BL-086 | Taklif eskirdi | Yashiriladi yoki belgilanadi; xaridda qayta tekshiriladi |
| BL-087 | "Tasdiqlangan shop" belgisi | Faqat dalil bilan va muddatli |
| BL-088 | Shikoyat yoki qoidabuzarlik | Ko'rib chiqish, e'tiroz va sabab bilan olib tashlash |
| BL-089 | Hamkor API kaliti | Ruxsatlari cheklangan, tezlik limitli, bekor qilinadigan; sizib chiqsa darhol o'chiriladi |
| BL-090 | Global qidiruv | Faqat ochiq takliflar; yopiq mahsulotlar ko'rinmaydi |
| BL-091 | Qidiruv natijasi | Variant va holat farqlari hisobga olinadi; solishtirib bo'lmaydiganlar alohida |
| BL-092 | Narx solishtirish | Narx, ma'lum bo'lsa yetkazish, valyuta, kafolat va yangilangan vaqt ko'rsatiladi |
| BL-093 | Saralash | "Jami narx" faqat hammasi ma'lum va solishtirsa bo'ladigan bo'lsa |
| BL-094 | Xaridor noto'g'ri taklif haqida xabar berdi | Shop ko'rib chiqadi; jiddiy xato bo'lsa taklif yashiriladi |
| BL-095 | Joylashuv | Aniq joy faqat rozilik bilan; aks holda shahar bo'yicha |
| BL-096 | Masofa | To'g'ri chiziqmi yoki yo'l bo'yichami — aniq yoziladi; vaqt o'ylab topilmaydi |
| BL-097 | Global AI tavsiya beradi | Qaysi ma'lumotga asoslanganini aytadi; dalil yo'q bo'lsa noaniqligini aytadi |
| BL-098 | Global AI ma'lumot oladi | Faqat ochiq indeksdan; shoplarning ichki ma'lumotidan hech qachon |
| BL-099 | Saralash va reklama | Reklama oddiy natijalarga ta'sir qilmaydi va aniq belgilanadi |
| BL-100 | Xaridor shopga yo'naltiriladi | Xaridor roziligi bilan va qayerga yo'naltirilishini ko'rib |
| BL-101 | Shopga xaridor ma'lumoti beriladi | Faqat kerakli ma'lumot, rozilikdan keyin |
| BL-102 | Saqlangan qidiruv yoki ogohlantirish | Faqat xaridor yoqsa; bir bosishda bekor qilinadi |
| BL-103 | Narx ogohlantirishi | Faqat yangi tekshirilgan narx bo'yicha va tez-tez emas |
| BL-104 | Reklama o'rni | Aniq belgilanadi; "AI tavsiya qiladi" deb ko'rsatilmaydi |
| BL-105 | Saralash sifati | Moslik, yangilik va ochiq mezonlar bo'yicha; shikoyat bo'lsa ko'rib chiqiladi |
| BL-106 | SEO sahifalar | Faqat amaldagi takliflar uchun |
| BL-107 | Takroriy sahifalar | Bitta asosiy manzil, takrorlar indeksga kirmaydi |
| BL-108 | Global Telegram bot | Shop botlaridan alohida; ma'lumot aralashmaydi |

---

# Murakkab holatlar: bir nechta qoida birga ishlaydi

Har biri sinov ssenariysi sifatida ham ishlatiladi (`10`).

**BR-X01 — Oxirgi mahsulot uchun poyga.** Omborda 1 ta mahsulot. Ikki operator bir vaqtda ikki buyurtmani tasdiqlaydi. Faqat bittasi o'tadi, ikkinchisi "mahsulot qolmagan" xabarini oladi. (BL-019, 020, 023, 046, 047)

**BR-X02 — Kech kelgan to'lov ⏸.** To'lov moduli qo'shilgandan keyin dolzarb: rezerv bekor qilingandan keyin to'lov keladi. To'lov yozib qo'yiladi, buyurtma avtomatik davom etmaydi, menejer qaror qiladi. (BL-021, 049, 051, 052)

**BR-X03 — Narx o'zgardi.** AI 4,5 mln so'mlik taklif yubordi, keyin shop narxni 4,8 mln qildi. Yuborilgan taklif o'zgarmaydi. Buyurtma tasdiqlanayotganda tizim farqni ko'rsatadi va xaridordan qayta rozilik so'raladi. (BL-015, 016, 044, 047)

**BR-X04 — Xabar takror keldi.** Telegram bitta xabarni ikki marta yubordi. Inbox'da bitta xabar, AI bitta javob beradi, xaridorga bitta xabarnoma. (BL-032, 035, 060)

**BR-X05 — Operator va AI bir vaqtda.** Operator suhbatni oldi, AI esa javob tayyorlab turgan edi. Yuborishdan oldin tizim "hozir kim javob beradi?" deb tekshiradi va AI javobini tashlab yuboradi. (BL-034, 037)

**BR-X06 — Boshqa shop ma'lumoti so'raldi.** A shop xodimi hisobot yordamchisidan B shopning savdosini so'raydi. Hech qanday raqam berilmaydi, urinish yozib qo'yiladi. (BL-002, 005, 008, 065, 098)

**BR-X07 — Shop ommaviy taklifni qaytarib oldi (Stage 2).** Qidiruv indeksi hali yangilanmagan bo'lsa ham, taklif xaridorlarga darhol ko'rinmay qoladi. (BL-079, 080, 081, 085, 090)

**BR-X08 — Noto'g'ri moslash (Stage 2).** "RTX 5060 8GB" ni "RTX 5060 Ti" bilan birlashtirish taqiqlanadi; shubha bo'lsa odam ko'rib chiqadi. (BL-076, 077, 078, 091)

**BR-X09 — Soxta chek ⏸.** To'lov moduli qo'shilgandan keyin dolzarb: xaridor chek rasmini yuboradi, to'lov "kutilmoqda" holatida qoladi, moliya xodimi bankdan tekshiradi. Stage 1 da: AI "to'lov shop bilan kelishiladi" deb operatorga uzatadi. (BL-050, 051)

**BR-X10 — Noto'g'ri "eng arzon" (Stage 3).** Bir shopda yetkazish narxi noma'lum, ikkinchisida 50 ming. AI "eng arzon" demaydi; mahsulot narxini va yetkazish noma'lumligini alohida ko'rsatadi. (BL-092, 093, 097)

**BR-X11 — Shikastlangan mahsulot qaytdi.** Qaytgan mahsulot tekshirilmaguncha sotuvga chiqmaydi. (BL-057, 059, 019)

**BR-X12 — POS va dashboard bir vaqtda (Stage 2).** Shopning kassa dasturi va dashboard bir mahsulot qoldig'ini bir vaqtda o'zgartirdi. Oxirgi yozuv g'olib bo'lmaydi: qaysi tizim asosiy ekanligiga qarab hal qilinadi yoki odam ko'radi. (BL-073, 075, 019)

**BR-X13 — Online buyurtma va do'kondagi sotuv.** Omborda 1 ta RTX 4060. Online buyurtma tasdiq kutayotganda xodim shu mahsulotni do'konda "tez sotuv" bilan sotdi. Operator tasdiqlamoqchi bo'lganda tizim "mahsulot qolmagan" deydi; operator xaridorga muqobil taklif qiladi. (BL-047, 109, 111)

**BR-X14 — AI "tasdiqlandi" demoqchi.** Xaridor "olaman" dedi, AI buyurtma qoralamasini yaratdi. AI faqat "buyurtmangiz qabul qilindi, operator bog'lanadi" deydi. "Tasdiqlandi" yoki "band qilindi" deyish taqiqlangan. (BL-038, 041, 110)
