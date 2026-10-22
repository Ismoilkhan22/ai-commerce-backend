# 13 — Merchant onboarding playbook (pilot do'konni ulash)

**Status:** Draft (2026-10-22). DEC-122 (platforma jamoasi qo'lda faollashtiradi), DEC-119 (30 kunlik pilot), DEC-116 (kanallar), DEC-011/120 (spec kutubxonasi), FSM-01.
**Kim uchun:** founder va onboarding jamoasi — pilot do'konni birinchi kundan "AI javob beryapti, buyurtma kelyapti" holatigacha olib chiqish.

Maqsad: do'kon 5–7 ish kunida ishga tushsin va birinchi haftada haqiqiy buyurtma olsin.

---

## 0-bosqich: Kelishuv (ishga tushirishdan oldin)

| # | Ish | Natija |
|---|---|---|
| 0.1 | Discovery intervyusi va saralash bali (A01 §8) — 60+ | pilot nomzodi |
| 0.2 | Pilot shartlari va MOU imzolanadi (business/14) | imzolangan hujjat |
| 0.3 | Mas'ul shaxslar: do'kon tomonidan sponsor (egasi) va kunlik kontakt (operator) | ism, telefon |
| 0.4 | Baseline o'lchovi boshlanadi: oxirgi 7–14 kun javob vaqti, so'rovlar soni, quote vaqti (A01 §7) | baseline jadvali |

## 1-bosqich: Akkaunt va jamoa (1-kun)

| # | Ish | Kim | Tekshiruv |
|---|---|---|---|
| 1.1 | Platform admin'da merchant yaratiladi (`DRAFT`) | platforma | — |
| 1.2 | Owner taklif qilinadi, login va parol/MFA | do'kon egasi | owner tizimga kirdi |
| 1.3 | Filiallar: manzil, ish vaqti, telefon | owner + platforma | storefront'da to'g'ri ko'rinadi |
| 1.4 | Xodimlar va rollar; kichik do'kon bo'lsa "kichik do'kon" shabloni (DEC-100f) | owner | har xodim kirdi |
| 1.5 | Merchant siyosatlari: quote muddati (24 s), chegirma limitlari (Sales 0%, Manager 5%), eslatma vaqtlari (24/72 s) — kerak bo'lsa o'zgartiriladi | owner | sozlamalar saqlandi |
| 1.6 | Valyuta: narxlar USD da bo'lsa — kurs manbai (o'zi kiritadi yoki Markaziy bank) | owner | kurs bor |

## 2-bosqich: Katalog (1–3-kun) — eng muhim qism

| # | Ish | Kim | Tekshiruv |
|---|---|---|---|
| 2.1 | Do'kondan Excel/POS eksporti olinadi | do'kon | fayl |
| 2.2 | Fayl tozalanadi: nomlar, kategoriyalar, MPN/model, narx, soni (TECH-28 §3) | platforma + do'kon | — |
| 2.3 | Import: dry-run → xatolar tuzatiladi → commit | platforma | xatolar 0 yoki ongli o'tkazib yuborilgan |
| 2.4 | PC komponentlari spec'ga bog'lanadi; bog'lanmaganlar ro'yxati → spec kutubxonasiga qo'shiladi (DEC-120) | platforma | top-100 sotiladigan komponentlarning 90%+ bog'langan (maqsad) |
| 2.5 | Narx va qoldiq do'kon bilan birga **20 ta tasodifiy SKU** bo'yicha tekshiriladi | do'kon egasi | 20/20 to'g'ri |
| 2.6 | Rasmlar va asosiy tavsiflar (kamida eng ko'p sotiladigan mahsulotlar uchun) | do'kon / platforma | — |
| 2.7 | Publish: sotuvga chiqariladigan SKU'lar | owner | storefront'da ko'rinadi |

**Qoida:** katalog tekshiruvidan (2.5) o'tmaguncha AI xaridorlarga javob bermaydi.

## 3-bosqich: Kanallar (2–4-kun)

| # | Ish | Kim | Tekshiruv |
|---|---|---|---|
| 3.1 | Telegram bot: BotFather'da yaratish (yordam bilan), token dashboard'ga (TECH-30 §2) | do'kon egasi + platforma | `/start` ishlaydi |
| 3.2 | Instagram: professional akkaunt, Meta OAuth (TECH-30 §3) | do'kon egasi | test xabari inbox'ga keldi |
| 3.3 | Storefront: subdomen, logotip, kontaktlar; web chat yoqilgan | owner | sahifa ochiladi, chat ishlaydi |
| 3.4 | Instagram bio va Telegram kanal tavsifiga bot / sayt havolasi | do'kon | — |

## 4-bosqich: AI sozlash (3–5-kun)

| # | Ish | Kim | Tekshiruv |
|---|---|---|---|
| 4.1 | Agent profili: do'kon nomi, ohang, ish vaqti, yetkazish va kafolat siyosati (matn), FAQ (10–20 savol) | owner + platforma | AP-05 tasdig'i |
| 4.2 | Sandbox: platforma va do'kon egasi 20 ta haqiqiy savolni sinaydi (A01 §5 savollaridan va do'konning o'z chatlaridan) | ikkalasi | xato javoblar tuzatildi |
| 4.3 | 5 ta PC yig'ma ssenariysi (byudjet + ish turi) | ikkalasi | moslik natijalari to'g'ri |
| 4.4 | AI rejimi: birinchi hafta `SUGGEST` (TECH-26 §2) | owner | — |

## 5-bosqich: Jamoani o'qitish (4–5-kun, 1–1.5 soat)

| Mavzu | Kim uchun |
|---|---|
| Inbox: suhbatni olish, javob, AI'ga qaytarish | operatorlar |
| Buyurtma: qoralamani ko'rish → xaridor bilan kelishish → tasdiqlash → tayyor → topshirildi; bekor qilish | operatorlar, menejer |
| "Tez sotuv" — do'kondagi har sotuvdan keyin | sotuvchilar, omborchi |
| PC taklifini tasdiqlash | menejer |
| Hisobot-chat va dashboard | ega |
| Muammo bo'lsa kimga yozish (support kanali) | hamma |

Qisqa qo'llanma (1 sahifa, uz/ru) va 3–5 daqiqalik video beriladi.

## 6-bosqich: Ishga tushirish (5–7-kun)

| # | Ish | Tekshiruv |
|---|---|---|
| 6.1 | Platform admin: merchant `PENDING_VERIFICATION → ACTIVE` (FSM-01, DEC-122) | holat `ACTIVE` |
| 6.2 | Birinchi kun: platforma inbox'ni real vaqtda kuzatadi | — |
| 6.3 | Kunlik qisqa tekshiruv (birinchi hafta): AI xatolari, tasdiq kutayotgan buyurtmalar, stok farqlari | kunlik yozuv |
| 6.4 | 7-kun: `SUGGEST → AUTO` qarori (do'kon egasi bilan, xatolar soniga qarab) | qaror yozildi |
| 6.5 | Haftalik uchrashuv: KPI (A01 §7), muammolar, takliflar | uchrashuv qaydi |

## 7. Pilot davomida va yakunida

- **2–3-hafta:** haftalik KPI hisoboti (javob vaqti, buyurtmalar soni va manbasi, handoff sabablari, AI xatolari, stok farqlari).
- **30-kun:** yakuniy uchrashuv — baseline bilan solishtirish, pullik davom etish qarori (business/14).
- Pilot to'xtasa: ma'lumot eksporti va o'chirish (TECH-32 §3).

## 8. Onboarding tekshiruv ro'yxati (do'kon kartochkasi)

```text
Do'kon: ______  Sponsor: ______  Kunlik kontakt: ______  Boshlanish: ____
[ ] MOU imzolangan            [ ] Baseline boshlangan
[ ] Owner va xodimlar kirgan  [ ] Filiallar va ish vaqti
[ ] Siyosatlar (quote, chegirma, eslatma, kurs)
[ ] Import: ___ SKU, xatolar 0   [ ] Spec bog'langan: ___%   [ ] 20 SKU tekshiruvi 20/20
[ ] Telegram bot   [ ] Instagram   [ ] Storefront + web chat
[ ] Agent profili + FAQ   [ ] Sandbox 20 savol   [ ] 5 PC ssenariy
[ ] Jamoa o'qitildi   [ ] ACTIVE   [ ] SUGGEST → AUTO qarori (7-kun)
```
