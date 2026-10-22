# 06 — Ekranlar va foydalanuvchi oqimlari

**Versiya:** v2 (2026-10-22, oddiy tilda qayta yozildi). Dizayn (ranglar, aniq joylashuv) keyinroq; bu yerda qaysi ekranlar borligi, ularda nima qilinishi va foydalanuvchi qanday ketma-ketlikda ishlashi yozilgan.

## Bu hujjat nima uchun

Dizayner va frontend dasturchi shu hujjatga qarab ekranlarni chizadi. Ega va operator esa tizimda qanday ishlashini oldindan ko'radi.

Tizimda ikki xil ilova bor:
1. **Shop paneli** — xodimlar ishlaydigan joy (inbox, buyurtmalar, katalog, hisobotlar).
2. **Shop sayti** — xaridor ko'radigan sayt (katalog, buyurtma berish, chat).

---

## 1. Shop paneli sahifalari (Stage 1)

Manzil: `app.<platforma>.uz/{shop}/...`

| Sahifa | Manzil | Nima uchun | Kim ishlatadi | Modul |
|---|---|---|---|---|
| Bosh sahifa | `/overview` | Bugungi raqamlar, tasdiq kutayotgan buyurtmalar, ogohlantirishlar | ega, menejer | M18 |
| Ishga tushirish | `/setup` | Yangi shopni sozlash bosqichlari | ega | M01, M03, M07, M09 |
| Inbox | `/inbox` | Barcha suhbatlar, AI'dan suhbatni olish | operator, menejer | M10, M11 |
| Buyurtmalar | `/orders` | Buyurtmalar ro'yxati va kartochkasi, tasdiqlash | operator, menejer, omborchi | M13 |
| Leadlar va takliflar | `/leads` | Qiziqqan xaridorlar, PC takliflari | operator, menejer | M12 |
| PC yig'ish | `/pc-builder` | Qismlarni tanlash va moslikni tekshirish | operator, menejer | M08 |
| Katalog | `/catalog` | Mahsulotlar, fayldan yuklash | katalog xodimi, menejer | M04 |
| Narxlar | `/prices` | Narxlar, kurslar, chegirma tasdiqlari | ega, menejer | M05 |
| Ombor | `/inventory` | Qoldiq, band qilinganlar, tuzatishlar, **"tez sotuv"** | omborchi, menejer, operator | M06 |
| Kafolat | `/support` | Kafolat va qaytarish murojaatlari | operator, menejer | M16 |
| Hisobotlar | `/reports` | Raqamlar, savol-javob, eksport | ega, menejer | M18 |
| Shop sayti sozlamalari | `/storefront` | Logotip, ranglar, manzil, saytni chiqarish | ega | M07 |
| Kanallar | `/channels` | Telegram, Instagram, web chat ulanishi | ega | M09 |
| Xodimlar | `/team` | Xodimlar, rollar, filiallar | ega | M02 |
| Filiallar | `/branches` | Manzil, ish vaqti | ega, menejer | M03 |
| Xabarnomalar | `/notifications` | Bildirishnomalar, xabar matnlari | hamma (ega — matnlar) | M17 |
| AI sozlamalari | `/settings/ai` | AI rejimi, shop ma'lumotlari, sinov oynasi | ega | M19 |
| Tarif va limitlar | `/settings/billing` | Ishlatish, limitlar, tarif | ega | M19 |
| Tarix | `/audit` | Kim nima o'zgartirgani | ega | M20 |

**Hozir yo'q:** to'lovlar sahifasi (DEC-100) va yetkazish sahifasi (DEC-113). Yetkazish holati buyurtma kartochkasida ko'rinadi.

**Telefonda:** inbox, buyurtmalar, "tez sotuv" va hisobotlar telefonda qulay ishlashi shart. Qolgan sahifalar asosan kompyuterda ishlatiladi.

## 2. Shop sayti sahifalari

Manzil: `{shop}.<platforma>.uz/...` (yoki shopning o'z domeni)

| Sahifa | Manzil | Nima uchun |
|---|---|---|
| Bosh sahifa va katalog | `/` | Mahsulotlar, qidiruv, kategoriyalar |
| Mahsulot sahifasi | `/p/{mahsulot}` | Rasm, tavsif, narx, mavjudligi, "savatga" tugmasi |
| Savatcha va buyurtma | `/cart` | Kontakt, olib ketish yoki yetkazish, manzil → buyurtma so'rovi (to'lovsiz, DEC-115) |
| PC taklifi | `/quote/{kod}` | Operator yoki AI yuborgan PC taklifini ko'rish va qabul qilish |
| Buyurtma holati | `/orders/{kod}` | Xaridor o'z buyurtmasi qayerdaligini ko'radi |
| Chat | barcha sahifalarda | AI sotuvchi bilan yozishish |

---

## 3. Asosiy oqimlar

Belgilar `05` dagi kabi: `──(kim nima qiladi)──▶`, `[tizim nima qiladi]`.

### Oqim 1 — Shopni ishga tushirish

```
Platforma jamoasi shop yaratadi ──▶ Ega tizimga kiradi
  ──▶ Filiallar va xodimlar qo'shiladi
  ──▶ Katalog fayldan yuklanadi   [xato qatorlar ko'rsatiladi, tuzatiladi]
  ──▶ PC qismlari texnik kutubxonaga bog'lanadi
  ──▶ 20 ta mahsulot narxi va qoldig'i ega bilan birga tekshiriladi
  ──▶ Telegram bot, Instagram va sayt ulanadi
  ──▶ AI sozlanadi va sinov oynasida sinaladi
  ──▶ Jamoa o'qitiladi
  ──▶ Platforma jamoasi shopni faollashtiradi   [AI xaridorlarga javob bera boshlaydi]
```

Batafsil reja va tekshiruv ro'yxati: `13`.

### Oqim 2 — Savdo: xabardan topshirishgacha (asosiy oqim, DEC-100)

**Chat orqali (Telegram, Instagram, saytdagi chat):**

```
Xaridor yozadi ──▶ AI javob beradi   [tilini aniqlaydi, ehtiyojni so'raydi]
  ──▶ AI shu shop katalogidan mos mahsulot topadi   [narx va mavjudlik tizimdan]
  ──(PC yig'ma bo'lsa)──▶ AI yig'ma tuzadi   [moslik tekshiriladi]
        ──▶ Menejer taklifni tasdiqlaydi ──▶ Xaridorga taklif havolasi ketadi (24 soat amal qiladi)
  ──(xaridor "olaman" dedi)──▶ AI buyurtma qoralamasini yaratadi va operatorni chaqiradi
                                [xaridorga: "buyurtmangiz qabul qilindi, operator bog'lanadi"]
```

**Sayt orqali:**

```
Xaridor savatga soladi ──▶ Kontakt va manzilni kiritadi ──▶ "Buyurtma berish"
  [buyurtma "tasdiq kutilmoqda" holatida, operatorga vazifa]
```

**Keyin ikkala yo'l bir xil davom etadi:**

```
Operator suhbatni oladi   [AI endi yozmaydi]
  ──▶ Operator xaridor bilan kelishadi: narx, olib ketish yoki yetkazish, vaqt (chat yoki telefon)
  ──▶ Operator (yoki menejer) "Tasdiqlash"ni bosadi
        [tizim mahsulot borligini tekshiradi]
        ├─ bor ──▶ Tasdiqlandi   [mahsulot band qilinadi, xaridorga xabar]
        └─ yo'q ──▶ "Mahsulot qolmagan" ──▶ operator muqobil taklif qiladi yoki menejer bekor qiladi
  ──▶ Tayyorlanmoqda   [xaridorga xabar; olib ketish bo'lsa "tayyor" xabari]
  ──▶ Xaridor mahsulotni oladi ──▶ Topshirildi   [mahsulot ombordan chiqadi]
  ──▶ Pulni shop o'zi oladi   [xohlasa "to'landi" deb belgilaydi]
```

**Kutib qolsa:** buyurtma 24 soat tasdiqlanmasa — operator va menejerga eslatma. Mahsulot 72 soat band turib, xaridor kelmasa — menejerga "bekor qilinsinmi?" vazifasi (DEC-104).

### Oqim 3 — Oxirgi mahsulot: online buyurtma va do'kondagi sotuv

```
Omborda 1 ta RTX 4060.
  Operator A online buyurtmani tasdiqlamoqchi ─┐
  Do'konda xodim "tez sotuv" qilmoqchi ────────┼──▶ Tizim bitta-bitta tekshiradi
  Operator B boshqa buyurtmani tasdiqlamoqchi ─┘
        ──▶ Birinchisi o'tadi
        ──▶ Qolganlariga "mahsulot qolmagan" ──▶ operatorlar muqobil taklif qiladi
```

### Oqim 4 — Ega hisobot so'raydi

```
Ega yozadi: "Oxirgi 7 kunda nechta buyurtma topshirildi?"
  ──▶ Tizim savolni ruxsat etilgan ko'rsatkichga aylantiradi
  ──▶ Ega bu raqamni ko'rishga ruxsati bormi?
        ├─ yo'q ──▶ "Ruxsat yo'q", raqam aytilmaydi
        └─ ha ──▶ Raqam + davr + "ma'lumot 14:30 holatiga" + grafik
```

Ovozli variant (keyinroq, DEC-112): ega gapiradi → matn ekranda ko'rsatiladi va tasdiqlanadi → shundan keyin xuddi yuqoridagidek.

### Oqim 5 — Ishlamay qolganda

```
AI ishlamayapti yoki limiti tugadi ──▶ Xabarlar operatorga   [xaridorga: "operator javob beradi"]
Telegram yoki Instagram uzildi ──▶ Egaga ogohlantirish, kanal sahifasida "qayta ulash"
Instagram'da 24 soat o'tdi ──▶ AI yozmaydi, operatorga "boshqa kanal orqali bog'laning"
```

### Keyingi bosqichlar oqimlari (qisqa)

- **Stage 2 — mahsulotni global qidiruvga chiqarish:** shop mahsulotni tanlaydi → qaysi ma'lumot ochiq bo'lishini ko'radi → tizim uni umumiy katalogdagi modelga bog'laydi (shubha bo'lsa odam ko'radi) → chiqariladi. Shop qaytarib olsa, darhol ko'rinmay qoladi.
- **Stage 3 — xaridor global qidiruvda:** "RTX 5060 yaqin atrofda" → aynan shu model va variant bo'yicha takliflar → narx, yetkazish, kafolat, oxirgi yangilanish → xaridor roziligi bilan shop chatiga o'tadi.

---

## 4. Har ekranda bo'lishi shart holatlar

| Holat | Ekranda nima ko'rinadi |
|---|---|
| Yuklanmoqda | Kulrang shablon yoki aylanuvchi belgi; uzoq ishda "bekor qilish" |
| Bo'sh | Nima qilish kerakligi: "Katalog bo'sh — fayl yuklang" kabi tugma bilan |
| Xato kiritildi | Har maydon ostida tushunarli xabar (foydalanuvchi tilida) |
| Ma'lumot eski | "14:30 holatiga" va "yangilash" tugmasi |
| Boshqa odam o'zgartirdi | "Bu ma'lumot o'zgardi" va yangi holatni ko'rsatish; eski ma'lumot bilan ustidan yozilmaydi |
| Tashqi servis ishlamayapti | Nima ishlamayotgani va keyingi qadam |
| Ruxsat yo'q | "Ruxsat yo'q" — maxfiy ma'lumot ko'rsatilmaydi |
| Tugma ikki marta bosildi | Bitta natija, ikkinchi buyurtma yoki band yaratilmaydi |
| Uzoq ish (fayl yuklash, eksport) | Jarayon holati; sahifa yangilansa ham davom etadi |

Barcha matnlar uch tilda (o'zbek, rus, ingliz) — `engineering/24` §5.

---

## 5. Ekran eskizlari

### Inbox

```text
┌──── Shop paneli ──────────────────────────────────────────────────────────┐
│ Bosh sahifa  Inbox  Buyurtmalar  Katalog  Ombor  Hisobotlar              │
├───────────────┬─────────────────────────────┬────────────────────────────┤
│ Suhbatlar     │ Xaridor bilan yozishma      │ Xaridor va buyurtma        │
│ ● Yangi (12)  │ Kanal: Telegram · til: uz   │ Ehtiyoj: o'yin + montaj    │
│ Operator (4)  │ Hozir javob beradi: AI      │ Byudjet: 10 mln so'm       │
│ Kutilmoqda (7)│ AI tavsiyalari va narxlar   │ Buyurtma qoralamasi: bor   │
│ Xatolar (2)   │ [Suhbatni olish] [Javob]    │ [PC taklifi] [Buyurtmaga]  │
└───────────────┴─────────────────────────────┴────────────────────────────┘
```

### Buyurtma kartochkasi

```text
┌──── Buyurtma A-1042 ──────────────────────────────────────────────────────┐
│ Holat: Tasdiq kutilmoqda      Olib ketish: Chilonzor filiali              │
│ Mahsulotlar: RTX 4060 8GB × 1 — 4 500 000 so'm (narx muzlatilgan)         │
│ Kelishuv: "Ertaga 15:00 da olib ketadi" (operator Aziz, telefon)          │
│ Tarix: Qoralama (AI) → Tasdiq kutilmoqda                                  │
│ Ogohlantirish: [Narx o'zgargan] [Mahsulot qolmagan]                       │
│ [Tasdiqlash] [Tayyorlanmoqda] [Topshirildi] [Bekor qilish] [To'landi]     │
└───────────────────────────────────────────────────────────────────────────┘
```

Tugmalar faqat ruxsati bor odamga va faqat mumkin bo'lgan holatda ko'rinadi (masalan, "Bekor qilish" — faqat menejer va egaga).

### PC yig'ish

```text
┌──── PC yig'ish ───────────────────────────────────────────────────────────┐
│ Talablar           │ Qismlar                 │ Moslik va narx             │
│ Byudjet: 10 mln    │ Protsessor [tanlash ▼]  │ ✓ Soket mos                │
│ Maqsad: o'yin      │ Ona plata  [tanlash ▼]  │ ✓ Xotira turi mos          │
│ Monitor: kerak emas│ Xotira     [tanlash ▼]  │ ⚠ BIOS ma'lumoti yo'q      │
│                    │ Videokarta [tanlash ▼]  │ ✓ Korpusga sig'adi         │
│ [3 ta variant]     │ Blok pitaniya, korpus…  │ Jami: 9 850 000 so'm       │
│                    │                         │ [Tasdiqqa yuborish]        │
└───────────────────────────────────────────────────────────────────────────┘
```

Qism almashtirilsa, moslik darhol qayta tekshiriladi. "Mos emas" bo'lsa, yuborish tugmasi ishlamaydi.

### Bosh sahifa (ega)

```text
┌──── Bosh sahifa · 22.10.2026 · Toshkent vaqti ────────────────────────────┐
│ Topshirildi: 6 ta · 42 mln so'm   │ Tasdiq kutmoqda: 3 ta (1 tasi 24+ soat)│
│ Suhbatlar: 48 (Telegram 30, Instagram 12, sayt 6) │ Operator kutmoqda: 4   │
│ Kam qolgan mahsulotlar: 5         │ AI limiti: 62%                         │
│ [Savol bering: "Kecha nechta buyurtma bo'ldi?"]                           │
│ Ma'lumot 14:30 holatiga                                                    │
└───────────────────────────────────────────────────────────────────────────┘
```

---

## 6. Ekranda aytish taqiqlangan narsalar

- Ma'lumot eskirgan bo'lsa — "omborda bor".
- Yetkazish narxi noma'lum bo'lsa — "eng arzon".
- Chek rasmi asosida — "to'lov qabul qilindi".
- Muhim ma'lumot noma'lum bo'lsa — "PC mos keladi".
- Operator ishlayotgan suhbatda — "AI hammasini hal qildi".
- Buyurtma faqat qoralama bo'lsa — "buyurtma tasdiqlandi".
