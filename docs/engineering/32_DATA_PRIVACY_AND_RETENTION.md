# TECH-32 — Shaxsiy ma'lumotlar, saqlash muddatlari, rozilik va o'chirish

**Status:** `DRAFT — HUQUQSHUNOS XULOSASI KERAK`. Bu hujjat yuridik maslahat emas. U texnik dizaynni va huquqshunosga beriladigan savollarni bir joyga yig'adi. Saqlash muddatlari — **takliflar**, huquqshunos tasdiqlaguncha real merchant ma'lumoti production'ga yuklanmaydi (DEC-013).
**Bog'liq:** DEC-013 (UZ hosting), DEC-016 (LLM'ga PII yo'q), DEC-117 (audio), DEC-118 (AI o'qitish), `engineering/10` Privacy, `business/07` (ma'lumot egaligi), TECH-26 §7 (redaction).

---

## 1. Rollar

| Tomon | Rol (taklif, huquqshunos tasdiqlaydi) |
|---|---|
| Do'kon (merchant) | Xaridorlar ma'lumotining egasi; ularni qayta ishlash maqsadini belgilaydi |
| Platforma (biz) | Do'kon nomidan ma'lumotni qayta ishlovchi; o'z maqsadlarimiz uchun ishlatmaymiz (DEC-118) |
| LLM provayderi, hosting, Grafana Cloud, Sentry | Sub-processor'lar; ro'yxati shartnomaga ilova qilinadi |

O'zbekiston "Shaxsga doir ma'lumotlar to'g'risida"gi qonuni (https://lex.uz/docs/4831939) va lokalizatsiya talablari qo'llanilishi huquqshunos bilan aniqlanadi.

## 2. Ma'lumot turlari

| Turi | Misollar | Qayerda | Shifrlash | Kim ko'radi |
|---|---|---|---|---|
| Xaridor kontakti | ism, telefon, Telegram/IG ID | `contacts`, `orders` | ustun darajasida (telefon, manzil) | biriktirilgan operator, menejer, owner |
| Yetkazish manzili | manzil matni | `orders.delivery_address` | ✅ | o'sha buyurtma bilan ishlovchilar |
| Suhbat matni | xabarlar | `messages` | at rest (DB/disk) | operatorlar (o'z do'koni) |
| Ovozli xabarlar | audio | private storage | ✅ | — (transkripsiyadan keyin o'chiriladi, DEC-117) |
| Rasm va fayllar | xaridor yuborgan rasm | private storage | ✅, signed URL | operatorlar |
| PII token jadvali | `[PHONE_1]` → raqam | `conversation_pii_refs` | ✅ | faqat tizim (TECH-26 §7) |
| Xodim ma'lumoti | ism, email, telefon, login tarixi | `users`, `sessions` | parol — Argon2id | owner, xodimning o'zi |
| Biznes ma'lumoti | katalog, narx, stok | tegishli jadvallar | at rest | do'kon xodimlari |
| Audit | kim, nima, qachon | `audit_entries` | at rest; PII'siz safe diff | owner, platforma (break-glass) |
| Telemetriya | trace, metrika, log | Grafana Cloud, Sentry | — | platforma; **PII yo'q** (TECH-12 §5b) |

## 3. Saqlash muddatlari (takliflar)

| Turi | Taklif | Muddat tugagach | Huquqshunosga savol |
|---|---|---|---|
| Suhbat matni | oxirgi faollikdan 12 oy | xabarlar o'chiriladi, statistik hisoblagichlar qoladi | Etarlimi? Qisqaroq kerakmi? |
| Ovozli xabar | transkripsiyadan keyin darhol (DEC-117) | audio o'chiriladi, redact qilingan transcript suhbat muddati bilan | — |
| Xaridor rasm/fayllari | suhbat muddati bilan | o'chiriladi | — |
| Buyurtmalar | buyurtma tafsilotlari ko'p yil kerak bo'lishi mumkin (kafolat, hisob) | xaridor PII'si anonimlashtiriladi, buyurtma qatorlari qoladi | Buxgalteriya/soliq hujjatlari uchun majburiy muddat qancha? |
| PII token jadvali | suhbat muddati bilan | o'chiriladi | — |
| Audit yozuvlari | 3 yil | arxiv, keyin o'chirish | Muddat to'g'rimi? |
| Xodim sessiyalari | 90 kun | o'chiriladi | — |
| Telemetriya log'lari | 30 kun (Grafana Cloud tarifiga bog'liq) | provayder o'chiradi | — |
| Backup'lar | 30 kun (taklif) | aylanma o'chirish; o'chirilgan ma'lumot backup'dan ham shu muddatda yo'qoladi | O'chirish so'rovi bilan backup muddati muvofiqmi? |
| Do'kon shartnomasi tugagach | eksport uchun 30 kun, keyin o'chirish (BL-070) | buyurtma yozuvlari — qonuniy muddat bo'yicha | Muddat? |

Texnik amalga oshirish: kunlik `retention_purge` job (merchant va ma'lumot turi bo'yicha), har o'chirish audit'da (nechta yozuv, qaysi tur — mazmunsiz).

## 4. Rozilik va xabardor qilish

| Qayerda | Nima | Matn (uz, qoralama) |
|---|---|---|
| Birinchi AI javobi (`customer.ai_greeting`) | AI ekanligi, operator mavjudligi | TECH-31 §2 |
| Telefon so'ralganda | maqsad | "Raqamingiz faqat buyurtma bo'yicha bog'lanish uchun ishlatiladi." |
| Storefront buyurtma formasi | maqsad + maxfiylik siyosati havolasi, checkbox | "Buyurtma bo'yicha bog'lanish uchun ma'lumotlarim ishlatilishiga roziman. [Maxfiylik siyosati]" |
| Storefront footer | maxfiylik siyosati, do'kon rekvizitlari | do'kon + platforma shabloni |
| Xodim taklifnomasi | xodim ma'lumotlari va login tarixi | foydalanish shartlari |
| Do'kon shartnomasi | platforma roli, sub-processor'lar, AI o'qitish yo'qligi (DEC-118), saqlash muddatlari | business/14 |

Marketing roziligi Stage 1 da yig'ilmaydi (marketing xabarlari yo'q).

## 5. Xaridor huquqlari bo'yicha so'rovlar

| So'rov | Qanday bajariladi | Muddat (taklif) |
|---|---|---|
| Ma'lumotlarimni ko'rsating | Do'kon (owner) dashboard'dan xaridor bo'yicha eksport (JSON/CSV) | 10 ish kuni |
| O'chiring | Owner "xaridorni anonimlashtirish" amali: kontakt, suhbat, fayllar o'chiriladi; buyurtmalar anonim holda qoladi (qonuniy saqlash talabi bo'lsa) | 10 ish kuni |
| Tuzating | Owner/operator kontaktni tahrirlaydi, audit bilan | darhol |
| Meta talabi (Instagram foydalanuvchisi o'chirish callback'i) | avtomatik anonimlashtirish job'i + tasdiq kodi | Meta talabiga ko'ra |

Platformaga to'g'ridan-to'g'ri kelgan so'rov tegishli do'konga yo'naltiriladi (biz processor'miz).

## 6. Texnik himoya choralari (xulosa)

- Tenant izolyatsiyasi: TECH-23 (app scoping, composite FK, RLS, TC-ISO testlari).
- Shifrlash: TLS hamma joyda; DB va storage at rest; telefon, manzil, PII token jadvali — ustun darajasida (kalit secret manager'da, rotatsiya bilan).
- LLM: faqat redact qilingan matn, zero-retention / no-training sharti (DEC-016).
- Telemetriya va audit'da PII yo'q (CI'da log snapshot skaneri, TECH-12 §7).
- Platforma support: odatiy holatda xaridor suhbatlarini ko'rmaydi; break-glass — sabab, muddat, audit (TECH-10).
- Fayllar: private bucket, qisqa muddatli signed URL, MIME tekshiruvi.

## 7. Sizib chiqish (breach) holatida

TECH-33 runbook RB-05: kirishni to'xtatish → ko'lamini aniqlash (qaysi do'kon, qaysi ma'lumot, qancha) → do'konlarga xabar → qonun talab qilsa vakolatli organga xabar (muddat va tartib — huquqshunos) → tuzatish va regression test.

## 8. Huquqshunosga savollar ro'yxati

1. Xaridor ma'lumotlarini O'zbekistondagi serverda saqlash majburiyati bizning holatga qanday qo'llaniladi (DEC-013)?
2. Redact qilingan matnni xorijiy LLM provayderiga yuborish transchegaraviy uzatish hisoblanadimi? Qanday shartlar kerak?
3. Grafana Cloud va Sentry'ga PII'siz telemetriya yuborish ruxsat etilganmi?
4. Platforma va do'kon o'rtasidagi rollar (egasi / qayta ishlovchi) va shartnomada nima bo'lishi kerak?
5. §3 dagi saqlash muddatlari, ayniqsa buyurtma va hisob hujjatlari uchun majburiy muddatlar.
6. Xaridor roziligi matni (§4) yetarlimi; alohida yozma rozilik kerakmi?
7. Shaxsga doir ma'lumotlar bazasini ro'yxatdan o'tkazish talabi bormi?
8. Sizib chiqish holatida xabar berish muddati va tartibi.
