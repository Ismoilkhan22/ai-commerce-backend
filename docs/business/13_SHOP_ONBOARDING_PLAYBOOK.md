# 13 — Pilot shopni ulash qo'llanmasi

**Versiya:** v2 (2026-10-22, oddiy tilda qayta yozildi). Qoralama.
**Kim uchun:** founder va shopni ulaydigan jamoa.
**Bog'liq qarorlar:** DEC-122 (shopni platforma jamoasi qo'lda faollashtiradi), DEC-119 (30 kunlik pilot), DEC-116 (kanallar), DEC-011/120 (texnik ma'lumotlar kutubxonasi).

## Bu hujjat nima uchun

Pilot shopni birinchi kundan "AI javob beryapti, buyurtmalar kelyapti" holatigacha olib chiqish uchun qadam-baqadam yo'l.

**Maqsad:** shop 5–7 ish kunida ishga tushsin va birinchi haftada haqiqiy buyurtma olsin.

**Umumiy yo'l:**

```
Kelishuv ──▶ Akkaunt va jamoa (1-kun) ──▶ Katalog (1–3-kun) ──▶ Kanallar (2–4-kun)
   ──▶ AI sozlash (3–5-kun) ──▶ Jamoani o'qitish (4–5-kun) ──▶ Ishga tushirish (5–7-kun) ──▶ 30 kunlik pilot
```

---

## 0-qadam: Kelishuv (ishga tushirishdan oldin)

| # | Ish | Natija |
|---|---|---|
| 0.1 | Shop bilan suhbat va saralash bali (`discovery/A01` §8) — 60 va undan yuqori | Pilotga nomzod |
| 0.2 | Pilot shartlari va kelishuv imzolanadi (`14`) | Imzolangan hujjat |
| 0.3 | Shop tomonidan mas'ullar: ega (asosiy qaror qabul qiluvchi) va kunlik aloqa uchun odam (odatda operator) | Ism, telefon |
| 0.4 | **Boshlang'ich o'lchov:** oxirgi 7–14 kunda javob vaqti, so'rovlar soni, PC taklif tayyorlash vaqti (`A01` §7). Pilot oxirida shular bilan solishtiriladi | O'lchov jadvali |

## 1-qadam: Akkaunt va jamoa (1-kun)

| # | Ish | Kim | Tekshiruv |
|---|---|---|---|
| 1.1 | Platforma panelida shop yaratiladi ("qoralama" holatida) | Platforma | — |
| 1.2 | Ega taklif qilinadi, tizimga kiradi va parol o'rnatadi | Shop egasi | Ega kirdi |
| 1.3 | Filiallar: manzil, ish vaqti, telefon | Ega + platforma | Saytda to'g'ri ko'rinadi |
| 1.4 | Xodimlar va rollar. Kichik shop bo'lsa — "kichik shop" shabloni (DEC-100f) | Ega | Har xodim kirdi |
| 1.5 | Shop sozlamalari: taklif amal qilish muddati (24 soat), chegirma limitlari (operator 0%, menejer 5%), eslatmalar (24 va 72 soat). Kerak bo'lsa o'zgartiriladi | Ega | Saqlandi |
| 1.6 | Narxlar dollarda bo'lsa — kurs qayerdan olinadi (ega o'zi kiritadi yoki Markaziy bank kursi) | Ega | Kurs bor |

## 2-qadam: Katalog (1–3-kun) — eng muhim qism

| # | Ish | Kim | Tekshiruv |
|---|---|---|---|
| 2.1 | Shopdan Excel yoki kassa dasturidan fayl olinadi | Shop | Fayl |
| 2.2 | Fayl tozalanadi: nomlar, kategoriyalar, model kodi, narx, soni (`engineering/28` §3) | Platforma + shop | — |
| 2.3 | Yuklash: avval sinov tariqasida tekshiriladi (hech narsa saqlanmaydi) → xatolar tuzatiladi → keyin haqiqiy yuklash | Platforma | Xatolar yo'q yoki ataylab o'tkazib yuborilgan |
| 2.4 | PC qismlari texnik ma'lumotlar kutubxonasiga bog'lanadi. Bog'lanmaganlar kutubxonaga qo'shiladi (DEC-120) | Platforma | Eng ko'p sotiladigan 100 ta qismning 90%+ bog'langan (maqsad) |
| 2.5 | Narx va qoldiq shop egasi bilan birga **tasodifiy 20 ta mahsulot** bo'yicha tekshiriladi | Shop egasi | 20 tadan 20 tasi to'g'ri |
| 2.6 | Rasmlar va qisqa tavsiflar (kamida eng ko'p sotiladiganlar uchun) | Shop / platforma | — |
| 2.7 | Sotuvga chiqariladigan mahsulotlar saytga chiqariladi | Ega | Saytda ko'rinadi |

**Qoida:** katalog tekshiruvidan (2.5) o'tmaguncha AI xaridorlarga javob bermaydi.

## 3-qadam: Kanallar (2–4-kun)

| # | Ish | Kim | Tekshiruv |
|---|---|---|---|
| 3.1 | Telegram bot: BotFather'da yaratiladi (yordam bilan), kaliti shop paneliga kiritiladi (`engineering/30` §2) | Shop egasi + platforma | `/start` ishlaydi |
| 3.2 | Instagram: professional akkaunt, Meta orqali ruxsat berish (`engineering/30` §3) | Shop egasi | Sinov xabari inbox'ga keldi |
| 3.3 | Sayt: manzil (subdomen), logotip, kontaktlar; saytdagi chat yoqiladi | Ega | Sahifa ochiladi, chat ishlaydi |
| 3.4 | Instagram profili va Telegram kanal tavsifiga bot va sayt havolasi qo'yiladi | Shop | — |

## 4-qadam: AI sozlash (3–5-kun)

| # | Ish | Kim | Tekshiruv |
|---|---|---|---|
| 4.1 | AI uchun ma'lumot: shop nomi, gapirish uslubi, ish vaqti, yetkazish va kafolat shartlari (matn), tez-tez beriladigan 10–20 savol | Ega + platforma | Ega tasdiqladi (`04` §3) |
| 4.2 | Sinov oynasida platforma va shop egasi 20 ta haqiqiy savolni sinab ko'radi (`A01` §5 va shopning o'z chatlaridan) | Ikkalasi | Xato javoblar tuzatildi |
| 4.3 | 5 ta PC yig'ma ssenariysi (byudjet + nima uchun kerak) | Ikkalasi | Moslik natijalari to'g'ri |
| 4.4 | Birinchi hafta AI faqat **javob taklif qiladi**, operator tasdiqlab yuboradi (`08`) | Ega | — |

## 5-qadam: Jamoani o'qitish (4–5-kun, 1–1,5 soat)

| Mavzu | Kim uchun |
|---|---|
| Inbox: suhbatni olish, javob berish, AI'ga qaytarish | Operatorlar |
| Buyurtma: qoralamani ko'rish → xaridor bilan kelishish → tasdiqlash → tayyor → topshirildi; bekor qilish | Operatorlar, menejer |
| "Tez sotuv" — do'kondagi har bir sotuvdan keyin (qoldiq to'g'ri bo'lishi uchun) | Sotuvchilar, omborchi |
| PC taklifini tasdiqlash | Menejer |
| Hisobot yordamchisi va bosh sahifa | Ega |
| Muammo bo'lsa kimga yozish | Hamma |

Bir sahifalik qisqa qo'llanma (o'zbek va rus tilida) va 3–5 daqiqalik video beriladi.

## 6-qadam: Ishga tushirish (5–7-kun)

| # | Ish | Tekshiruv |
|---|---|---|
| 6.1 | Platforma jamoasi shopni faollashtiradi: "tekshiruvda" → "faol" (`05`, DEC-122) | Holat "faol" |
| 6.2 | Birinchi kuni platforma jamoasi inbox'ni jonli kuzatib turadi | — |
| 6.3 | Birinchi hafta har kuni qisqa tekshiruv: AI xatolari, tasdiq kutayotgan buyurtmalar, qoldiq farqlari | Kunlik yozuv |
| 6.4 | 7-kuni shop egasi bilan qaror: AI o'zi javob bersinmi yoki taklif rejimida qolsinmi (xatolar soniga qarab) | Qaror yozildi |
| 6.5 | Haftalik uchrashuv: ko'rsatkichlar (`A01` §7), muammolar, takliflar | Uchrashuv qaydi |

## 7. Pilot davomida va oxirida

- **2–3-hafta:** haftalik hisobot — javob vaqti, buyurtmalar soni va qayerdan kelgani, operatorga uzatish sabablari, AI xatolari, qoldiq farqlari.
- **30-kun:** yakuniy uchrashuv — boshlang'ich o'lchov bilan solishtirish, pullik davom etish bo'yicha qaror (`14`).
- Pilot to'xtasa: ma'lumotlar shopga beriladi va o'chiriladi (`engineering/32` §3).

## 8. Shop kartochkasi — tekshiruv ro'yxati

```text
Shop: ______  Ega: ______  Kunlik aloqa: ______  Boshlanish: ____
[ ] Kelishuv imzolangan            [ ] Boshlang'ich o'lchov boshlangan
[ ] Ega va xodimlar kirgan         [ ] Filiallar va ish vaqti
[ ] Sozlamalar (taklif muddati, chegirma, eslatma, kurs)
[ ] Katalog: ___ mahsulot, xato 0  [ ] Kutubxonaga bog'langan: ___%  [ ] 20 mahsulot tekshiruvi 20/20
[ ] Telegram bot   [ ] Instagram   [ ] Sayt + chat
[ ] AI ma'lumotlari + savollar     [ ] Sinov: 20 savol   [ ] 5 PC ssenariy
[ ] Jamoa o'qitildi   [ ] Faol   [ ] 7-kun: AI rejimi bo'yicha qaror
```
