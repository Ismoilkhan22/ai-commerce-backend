# 14 — Pilot shartnomasi (MOU) qoralamasi va narxlash gipotezalari

**Status:** `DRAFT — FOUNDER VA HUQUQSHUNOS TO'LDIRADI`. Bu shablon yuridik hujjat emas: imzolashdan oldin huquqshunos ko'rib chiqadi. Narxlar — **gipoteza**, discovery intervyulari (A01) va pilot xarajatlari bilan tasdiqlanadi.
**Bog'liq:** DEC-119 (30 kun bepul, limitlar, keyin pullik), DEC-100 (to'lov tizimdan tashqarida), DEC-118 (AI o'qitish yo'q), TECH-32 (shaxsiy ma'lumotlar), business/13 (onboarding), discovery/A01 §7–9.

---

## 1-qism. Pilot kelishuvi (MOU) tuzilmasi

### 1.1 Tomonlar va maqsad
- Platforma: `[kompaniya nomi, STIR, manzil]`.
- Do'kon: `[nomi, STIR, manzil, mas'ul shaxs]`.
- Maqsad: AI Commerce OS ni do'konning haqiqiy savdosida 30 kun sinash va natijani raqamlar bilan baholash.

### 1.2 Muddat
- Pilot: `[boshlanish sanasi]` dan 30 kalendar kun.
- Onboarding (business/13) pilot muddatiga kirmaydi yoki `[kelishiladi]`.

### 1.3 Platforma nima beradi
- Telegram bot, Instagram Direct va web chat orqali AI yordamchi (Instagram — Meta ruxsati mavjud bo'lsa).
- Do'kon sayti (storefront), katalog va stok boshqaruvi, buyurtmalar, PC moslik tekshiruvi va takliflar, hisobotlar.
- Onboarding: katalog importi, sozlash, xodimlarni o'qitish.
- Support: ish vaqtida `[soat]`, javob maqsadi — `[2 soat]`; muhim nosozliklarda `[15 daqiqa]` (TECH-33 SEV-1).

### 1.4 Pilot limitlari (taklif, DEC-119)

| Ko'rsatkich | Limit (taklif) |
|---|---|
| AI javob beradigan suhbatlar | 1 000 / oy |
| AI xabarlari | 5 000 / oy |
| Xodimlar | 5 |
| SKU | 5 000 |
| Filiallar | 2 |

Limitga yaqinlashganda ogohlantirish; oshsa AI `OFF`, savdo funksiyalari ishlashda davom etadi (BL-067, BL-069).

### 1.5 Do'kon majburiyatlari
- Katalog, narx va qoldiq ma'lumotlarini berish va **to'g'riligi uchun javobgarlik** (narxlar do'kon tomonidan belgilanadi).
- Kunlik kontakt shaxs; tasdiq kutayotgan buyurtmalarni ish vaqtida ko'rib chiqish.
- Do'kondagi sotuvlarni "tez sotuv" bilan kiritish (stok to'g'ri bo'lishi uchun).
- Haftalik 30 daqiqalik uchrashuv.
- Xaridorlardan shaxsiy ma'lumot olish uchun zarur xabardor qilish (TECH-32 §4).

### 1.6 Muhim chegaralar
- **To'lov:** platforma xaridor to'lovlarini qabul qilmaydi va tekshirmaydi; to'lovni do'kon o'zi oladi (DEC-100).
- **Yetkazish:** do'kon o'zi tashkil qiladi (DEC-113).
- **AI:** AI yordamchi xato qilishi mumkin; narx, stok va moslik ma'lumotlari tizimdan olinadi, AI buyurtmani tasdiqlamaydi va chegirma bermaydi. Buyurtmani har doim do'kon xodimi tasdiqlaydi.
- **Kafolat yo'q:** platforma savdo hajmi oshishini kafolatlamaydi (A01 §9).

### 1.7 Ma'lumotlar
- Do'kon ma'lumotlari va xaridorlar ma'lumotlari do'konga tegishli; platforma ularni faqat xizmat ko'rsatish uchun qayta ishlaydi.
- Ma'lumotlar AI modelini o'qitish uchun ishlatilmaydi, do'konning alohida yozma roziligisiz (DEC-118).
- Sub-processor'lar ro'yxati (hosting, LLM provayderi, monitoring) ilovada.
- Saqlash va o'chirish: TECH-32 §3 (huquqshunos tasdiqlagan versiya).
- Pilot to'xtasa: 30 kun ichida eksport, keyin o'chirish.

### 1.8 Muvaffaqiyat mezonlari (pilot oxirida o'lchanadi)

| KPI (A01 §7) | Baseline | Pilot natijasi | Maqsad (kelishiladi) |
|---|---|---|---|
| Birinchi javob vaqti p50 / p90 | `[ ]` | `[ ]` | `[masalan, p90 < 5 daqiqa ish vaqtida]` |
| Javobsiz qolgan so'rovlar | `[ ]` | `[ ]` | `[ ]` |
| PC taklif tayyorlash vaqti | `[ ]` | `[ ]` | `[ ]` |
| Tizim orqali kelgan buyurtmalar (COMPLETED) | — | `[ ]` | `[ ]` |
| Noto'g'ri narx / stok da'volari | — | `[ ]` | 0 |
| Operator vaqti (do'kon baholashi) | `[ ]` | `[ ]` | `[ ]` |

### 1.9 Pilotdan keyin
- 30-kunda yakuniy uchrashuv.
- Mezonlar bajarilsa: do'kon `[tarif]` bo'yicha pullik davom etadi, birinchi `[2–3]` oy `[X]%` chegirma bilan (A01 §9 taklifi).
- Do'kon davom etmasa — hech qanday to'lov yo'q; ma'lumotlar eksport va o'chirish.
- Case study / ism ishlatish — faqat do'konning alohida roziligi bilan.

### 1.10 Imzolar
`[Platforma]` ________  `[Do'kon]` ________  Sana: ________

---

## 2-qism. Narxlash gipotezalari

> Hamma raqamlar — sinov uchun gipoteza. Intervyuda "agar pilot X natija ko'rsatsa, oyiga Y to'laysizmi?" savoliga javoblar (A01 savol 21) va pilotdagi haqiqiy xarajat bilan tasdiqlanadi.

### 2.1 Tarif paketlari (gipoteza)

| Tarif | Kim uchun | Nimalar kiradi | Oylik narx (UZS, gipoteza) |
|---|---|---|---|
| **Start** | 1 filial, kichik jamoa | 1 kanal (Telegram), katalog ≤ 1 000 SKU, AI ≤ 500 suhbat/oy, 3 xodim, storefront | `[ ]` |
| **PC Pro** | PC yig'uvchi do'konlar | Telegram + Instagram + web chat, PC builder va takliflar, katalog ≤ 5 000 SKU, AI ≤ 2 000 suhbat/oy, 10 xodim, hisobot-chat | `[ ]` |
| **Business** | ko'p filial | 3+ filial, yuqori limitlar, ustuvor support, ovozli hisobot (beta tayyor bo'lganda) | `[ ]` |
| Onboarding (bir martalik) | katalog tozalash va ulash | — | `[ ]` yoki pilotda bepul |
| Qo'shimcha AI paketi | limitdan oshganda | +1 000 suhbat | `[ ]` |

### 2.2 Unit economics — hisoblash usuli

| Ko'rsatkich | Formula | Manba |
|---|---|---|
| Do'kon uchun oylik xarajat | LLM xarajati (`ai_cost_amount`, TECH-29) + hosting ulushi + monitoring ulushi + support vaqti | pilot o'lchovi |
| Bitta AI suhbat narxi | oylik LLM xarajati / AI suhbatlar soni | `ai_cost_amount / conversations` |
| Gross margin | (tarif − do'kon xarajati) / tarif | — |
| Payback | mijoz jalb qilish xarajati / oylik foyda | sotuv statistikasi |
| Do'kon uchun qiymat | (tejalgan operator soatlari × soat narxi) + (qo'shimcha buyurtmalar × o'rtacha foyda) | pilot KPI va do'kon ma'lumoti |

**Qoida:** tarif bitta AI suhbat narxining kamida `[N]` baravaridan yuqori bo'lishi kerak — `[N]` pilot xarajatlari o'lchangach belgilanadi. Cheksiz AI limiti taklif qilinmaydi.

### 2.3 Intervyuda tekshiriladigan savollar
1. Hozir chat va savdo uchun qanday dasturlarga qancha to'laysiz?
2. Operator oyiga qancha turadi va qancha vaqtini takroriy savollarga sarflaydi?
3. Qaysi natija oylik to'lovni oqlaydi: tezroq javob, ko'proq buyurtma, kamroq xodim vaqti?
4. Oylik to'lov yoki har buyurtma uchun to'lov — qaysi biri qulayroq?
5. Narxlar dollarda yuritiladimi (DEC-121)?
