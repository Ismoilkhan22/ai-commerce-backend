# 14 — Pilot kelishuvi qoralamasi va narx gipotezalari

**Versiya:** v2 (2026-10-22). **Holat:** qoralama — founder va huquqshunos to'ldiradi. Bu shablon yuridik hujjat emas: imzolashdan oldin huquqshunos ko'rib chiqadi. Narxlar — **gipoteza**, shoplar bilan suhbatlar (`discovery/A01`) va pilot xarajatlari bilan tasdiqlanadi.
**Bog'liq:** DEC-119 (30 kun bepul, limitlar, keyin pullik), DEC-100 (to'lov tizimdan tashqarida), DEC-118 (ma'lumotlar bilan AI o'qitilmaydi), `engineering/26-privacy-and-retention.md` (shaxsiy ma'lumotlar), `13` (shopni ulash), `discovery/A01` §7–9.

---

## 1-qism. Pilot kelishuvi tuzilmasi

### 1.1 Tomonlar va maqsad
- Platforma: `[kompaniya nomi, STIR, manzil]`.
- Shop: `[nomi, STIR, manzil, mas'ul shaxs]`.
- Maqsad: AI Commerce OS ni shopning haqiqiy savdosida 30 kun sinash va natijani raqamlar bilan baholash.

### 1.2 Muddat
- Pilot: `[boshlanish sanasi]` dan 30 kalendar kun.
- Shopni ulash (`13`) pilot muddatiga kirmaydi yoki `[kelishiladi]`.

### 1.3 Platforma nima beradi
- Telegram bot, Instagram Direct va saytdagi chat orqali AI yordamchi (Instagram — Meta ruxsati mavjud bo'lsa).
- Shop sayti, katalog va ombor boshqaruvi, buyurtmalar, PC moslik tekshiruvi va takliflar, hisobotlar.
- Shopni ulash: katalogni yuklash, sozlash, xodimlarni o'qitish.
- Yordam: ish vaqtida `[soat]`, javob maqsadi — `[2 soat]`; jiddiy nosozliklarda `[15 daqiqa]` (`engineering/25-operations-runbooks.md`).

### 1.4 Pilot limitlari (taklif, DEC-119)

| Ko'rsatkich | Limit (taklif) |
|---|---|
| AI javob beradigan suhbatlar | 1 000 / oy |
| AI xabarlari | 5 000 / oy |
| Xodimlar | 5 |
| Mahsulotlar | 5 000 |
| Filiallar | 2 |

Limitga yaqinlashganda ogohlantirish beriladi; limit tugasa AI o'chadi, lekin savdoning boshqa qismlari ishlashda davom etadi (BL-067, BL-069).

### 1.5 Shop majburiyatlari
- Katalog, narx va qoldiq ma'lumotlarini berish va **to'g'riligi uchun javobgarlik** (narxlarni shop belgilaydi).
- Kunlik kontakt shaxs; tasdiq kutayotgan buyurtmalarni ish vaqtida ko'rib chiqish.
- Do'kondagi sotuvlarni "tez sotuv" bilan kiritish (qoldiq to'g'ri bo'lishi uchun).
- Haftalik 30 daqiqalik uchrashuv.
- Xaridorlarni shaxsiy ma'lumot olinishi haqida xabardor qilish (`engineering/26-privacy-and-retention.md` §4).

### 1.6 Muhim chegaralar
- **To'lov:** platforma xaridor to'lovlarini qabul qilmaydi va tekshirmaydi; to'lovni shop o'zi oladi (DEC-100).
- **Yetkazish:** shop o'zi tashkil qiladi (DEC-113).
- **AI:** AI yordamchi xato qilishi mumkin; narx, qoldiq va moslik ma'lumotlari tizimdan olinadi, AI buyurtmani tasdiqlamaydi va chegirma bermaydi. Buyurtmani har doim shop xodimi tasdiqlaydi.
- **Kafolat yo'q:** platforma savdo hajmi oshishini kafolatlamaydi (A01 §9).

### 1.7 Ma'lumotlar
- Shop ma'lumotlari va xaridorlar ma'lumotlari shopga tegishli; platforma ularni faqat xizmat ko'rsatish uchun qayta ishlaydi.
- Shopning alohida yozma roziligisiz ma'lumotlar AI modelini o'qitish uchun ishlatilmaydi (DEC-118).
- Ma'lumotlarni qayta ishlaydigan tashqi xizmatlar ro'yxati (server, AI provayderi, monitoring) ilovada.
- Saqlash va o'chirish: `engineering/26-privacy-and-retention.md` §3 (huquqshunos tasdiqlagan versiya).
- Pilot to'xtasa: 30 kun ichida ma'lumotlar shopga beriladi, keyin o'chiriladi.

### 1.8 Muvaffaqiyat mezonlari (pilot oxirida o'lchanadi)

| Ko'rsatkich (`A01` §7) | Pilotdan oldin | Pilot natijasi | Maqsad (kelishiladi) |
|---|---|---|---|
| Birinchi javob vaqti (o'rtacha / eng sekin 10%) | `[ ]` | `[ ]` | `[masalan, ish vaqtida 90% javoblar 5 daqiqadan tez]` |
| Javobsiz qolgan so'rovlar | `[ ]` | `[ ]` | `[ ]` |
| PC taklif tayyorlash vaqti | `[ ]` | `[ ]` | `[ ]` |
| Tizim orqali kelgan va topshirilgan buyurtmalar | — | `[ ]` | `[ ]` |
| Noto'g'ri narx yoki qoldiq holatlari | — | `[ ]` | 0 |
| Operator vaqti (shop baholashi) | `[ ]` | `[ ]` | `[ ]` |

### 1.9 Pilotdan keyin
- 30-kunda yakuniy uchrashuv.
- Mezonlar bajarilsa: shop `[tarif]` bo'yicha pullik davom etadi, birinchi `[2–3]` oy `[X]%` chegirma bilan (`A01` §9).
- Shop davom etmasa — hech qanday to'lov yo'q; ma'lumotlar shopga beriladi va o'chiriladi.
- Shop nomini misol sifatida (reklama, taqdimot) ishlatish — faqat shopning alohida roziligi bilan.

### 1.10 Imzolar
`[Platforma]` ________  `[Shop]` ________  Sana: ________

---

## 2-qism. Narx gipotezalari

> Hamma raqamlar — sinov uchun gipoteza. Shoplar bilan suhbatda "agar pilot X natija ko'rsatsa, oyiga Y to'laysizmi?" savoliga javoblar (`A01` 21-savol) va pilotdagi haqiqiy xarajat bilan tasdiqlanadi.

### 2.1 Tarif paketlari (gipoteza)

| Tarif | Kim uchun | Nimalar kiradi | Oylik narx (UZS, gipoteza) |
|---|---|---|---|
| **Start** | 1 filial, kichik jamoa | 1 kanal (Telegram), 1 000 tagacha mahsulot, oyiga 500 tagacha AI suhbat, 3 xodim, sayt | `[ ]` |
| **PC Pro** | PC yig'adigan shoplar | Telegram + Instagram + saytdagi chat, PC yig'ish va takliflar, 5 000 tagacha mahsulot, oyiga 2 000 tagacha AI suhbat, 10 xodim, hisobot yordamchisi | `[ ]` |
| **Business** | Ko'p filialli shoplar | 3+ filial, yuqori limitlar, birinchi navbatdagi yordam, ovozli hisobot (beta tayyor bo'lganda) | `[ ]` |
| Ulash (bir martalik) | Katalogni tozalash va ulash | — | `[ ]` yoki pilotda bepul |
| Qo'shimcha AI paketi | Limit tugaganda | +1 000 suhbat | `[ ]` |

### 2.2 Bitta shopdan foyda — qanday hisoblanadi

| Ko'rsatkich | Formula | Manba |
|---|---|---|
| Bitta shopga oylik xarajatimiz | AI xarajati (`engineering/19-reporting-metrics.md`) + server ulushi + monitoring ulushi + yordamga ketgan vaqt | Pilot o'lchovi |
| Bitta AI suhbat narxi | Oylik AI xarajati / AI suhbatlar soni | Pilot o'lchovi |
| Yalpi foyda ulushi | (tarif − shopga xarajat) / tarif | — |
| Xarajat necha oyda qoplanadi | Bitta shopni jalb qilish xarajati / oylik foyda | Sotuv statistikasi |
| Shop uchun foyda | (tejalgan operator soatlari × soat narxi) + (qo'shimcha buyurtmalar × o'rtacha foyda) | Pilot ko'rsatkichlari va shop ma'lumoti |

**Qoida:** tarif bitta AI suhbat narxining kamida `[N]` baravaridan yuqori bo'lishi kerak — `[N]` pilot xarajatlari o'lchangach belgilanadi. Cheksiz AI limiti taklif qilinmaydi.

### 2.3 Shoplar bilan suhbatda beriladigan savollar
1. Hozir chat va savdo uchun qanday dasturlarga qancha to'laysiz?
2. Operator oyiga qancha turadi va qancha vaqtini takroriy savollarga sarflaydi?
3. Qaysi natija oylik to'lovni oqlaydi: tezroq javob, ko'proq buyurtma, kamroq xodim vaqti?
4. Oylik to'lov yoki har buyurtma uchun to'lov — qaysi biri qulayroq?
5. Narxlar dollarda yuritiladimi (DEC-121)?
