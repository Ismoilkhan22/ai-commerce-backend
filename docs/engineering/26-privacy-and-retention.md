# 26 — Shaxsiy ma'lumotlar, saqlash muddatlari, rozilik va o'chirish

> **Versiya:** v2 (2026-10-22). Eski `32_DATA_PRIVACY_AND_RETENTION` o'rnini bosadi.
> **Holat:** `DRAFT — HUQUQSHUNOS XULOSASI KERAK`. Bu yuridik maslahat emas: texnik dizayn va huquqshunosga savollar bir joyda. Saqlash muddatlari — **taklif**; huquqshunos tasdiqlaguncha haqiqiy xaridor ma'lumoti production'ga yuklanmaydi (DEC-013).
> **Bog'liq:** DEC-013 (UZ hosting), DEC-016 (LLM'ga PII yo'q), DEC-117 (audio), DEC-118 (AI o'qitilmaydi), ADR-035 (schema per domain), BL-070…072.

## 1. Muammo

Xaridor ma'lumoti (ism, telefon, manzil, suhbatlar) bir nechta domen schemasida yotadi: `messaging`, `commerce`, `support`, `platform`. "Shu xaridorni o'chiring" yoki "shop ketdi — hammasini eksport qilib o'chiring" so'rovi har bir schemaga yetib borishi kerak. Lekin `platform` domenlarni import qila olmaydi va bir domen boshqasining jadvaliga tegmaydi (00 §2).

## 2. Yechim

- **Har domen o'z ma'lumotiga o'zi javob beradi.** Har domenda `privacy/` handler'lari: eksport, anonimlashtirish, shop bo'yicha o'chirish, muddat bo'yicha tozalash.
- **Muvofiqlashtirish — `platform/privacy` + event.** So'rov `platform.privacy_requests` jadvaliga yoziladi → event → har domen subscriber o'z qismini bajaradi va `privacy.mark_part_done(request_id, domain, summary)` ni chaqiradi → hamma qism tugaganda so'rov `COMPLETED`.
- Qaysi domenlar qatnashishi kerakligi `DomainManifest.privacy_handlers` dan boot'da yig'iladi (ro'yxat konfiguratsiya sifatida `platform` ga uzatiladi, import emas).

```
Ega "xaridorni anonimlashtirish" ──▶ platform/privacy: request (PENDING) + outbox [platform.privacy.erasure_requested]
   ──▶ messaging subscriber: kontakt, xabarlar, fayllar ──▶ mark_part_done(messaging)
   ──▶ commerce subscriber:  buyurtma/lead'dagi ism, telefon, manzil → anonim ──▶ mark_part_done(commerce)
   ──▶ support subscriber:   murojaat kontaktlari ──▶ mark_part_done(support)
   ──▶ platform/llm:         PII token xaritasi ──▶ mark_part_done(platform)
   ──▶ barcha qismlar tayyor ──▶ COMPLETED + audit (nechta yozuv, qaysi tur — mazmunsiz)
```

## 3. Rollar

| Tomon | Rol (taklif, huquqshunos tasdiqlaydi) |
|---|---|
| Shop | Xaridorlar ma'lumotining egasi; qayta ishlash maqsadini belgilaydi |
| Platforma (biz) | Shop nomidan qayta ishlovchi; o'z maqsadimizda ishlatmaymiz (DEC-118) |
| LLM provayderi, hosting, Grafana Cloud, Sentry | Sub-processor'lar; ro'yxat shartnomaga ilova (`../business/14` §1.7) |

O'zbekiston "Shaxsga doir ma'lumotlar to'g'risida"gi qonuni (https://lex.uz/docs/4831939) va lokalizatsiya talablari qo'llanilishi huquqshunos bilan aniqlanadi.

## 4. Ma'lumot turlari va joyi

| Turi | Misollar | Schema / jadval (egasi) | Shifrlash | Kim ko'radi |
|---|---|---|---|---|
| Xaridor kanal identifikatori | Telegram/IG ID, taxallus | `messaging.contacts` | at rest | Biriktirilgan operator, menejer, ega |
| Xaridor kontakti buyurtmada | ism, telefon | `commerce.orders`, `commerce.leads` | telefon — ustun darajasida | O'sha buyurtma bilan ishlovchilar |
| Yetkazish manzili | manzil matni | `commerce.orders.delivery_address` | ✅ ustun | O'sha buyurtma bilan ishlovchilar |
| Suhbat matni | xabarlar | `messaging.messages` | at rest | O'z shopi operatorlari |
| Ovozli xabarlar | audio | `platform/storage` private bucket | ✅ | — (transkripsiyadan keyin o'chiriladi, DEC-117) |
| Rasm va fayllar | xaridor yuborgan rasm | private bucket, havolasi `messaging.attachments` | ✅, signed URL | Operatorlar |
| PII token xaritasi | `[PHONE_1]` → raqam | `platform.llm_pii_refs` (`14`) | ✅ | Faqat tizim |
| Kafolat murojaati kontakti | ism, telefon | `support.cases` | telefon — ustun | Menejer, operator |
| Xodim ma'lumoti | ism, email, telefon, login tarixi | `platform.principals`, `platform.sessions` | parol — Argon2id | Ega, xodimning o'zi |
| Biznes ma'lumoti | katalog, narx, qoldiq | `catalog.*`, `commerce.*` | at rest | Shop xodimlari |
| Read model'lar | agregat raqamlar | `reporting.*` | at rest | Ruxsat bo'yicha — **PII yo'q** (`19` §3) |
| Audit | kim, nima, qachon | `audit.entries` | at rest; PII'siz diff | Ega, platforma (break-glass) |
| Telemetriya | trace, metrika, log | Grafana Cloud, Sentry | — | Platforma; **PII yo'q** (`09`) |
| Event payload'lar | ID va minimal fakt | `<schema>.outbox_events` | at rest | Tizim; **PII yo'q** (`03` §1.5) |

Ustun darajasida shifrlash kaliti — secret manager'da, rotatsiya bilan; `shared/db` dagi `EncryptedString` turi.

## 5. Saqlash muddatlari (takliflar)

| Turi | Taklif | Muddat tugagach | Kim tozalaydi | Huquqshunosga savol |
|---|---|---|---|---|
| Suhbat matni | Oxirgi faollikdan 12 oy | Xabarlar o'chiriladi, `reporting` raqamlari qoladi | `messaging` | Yetarlimi? |
| Ovozli xabar | Transkripsiyadan keyin darhol | Audio o'chiriladi; redact qilingan matn suhbat bilan | `messaging` | — |
| Xaridor fayllari | Suhbat muddati bilan | O'chiriladi | `messaging` | — |
| Buyurtmalar | Kafolat va hisob uchun uzoq | Xaridor PII'si anonimlashtiriladi, qatorlar qoladi | `commerce` | Buxgalteriya/soliq uchun majburiy muddat? |
| PII token xaritasi | Suhbat muddati bilan | O'chiriladi | `platform/llm` | — |
| Kafolat murojaatlari | Kafolat muddati + 12 oy | Kontakt anonimlashtiriladi | `support` | — |
| Import fayllari va staging | 30 kun | O'chiriladi | `catalog` (`18` §12) | — |
| Audit | 3 yil | Arxiv, keyin o'chirish (oylik partition `DROP`) | `platform/audit` | Muddat to'g'rimi? |
| Xodim sessiyalari | 90 kun | O'chiriladi | `platform/auth` | — |
| Outbox yozuvlari | `published_at` dan 14 kun | O'chiriladi | har domen | — |
| Telemetriya | 30 kun (tarifga bog'liq) | Provayder o'chiradi | — | — |
| Backup'lar | 30 kun | Aylanma; o'chirilgan ma'lumot backup'dan ham shu muddatda yo'qoladi | infra (`22`) | O'chirish so'rovi bilan muvofiqmi? |
| Shop shartnomasi tugagach | Eksport uchun 30 kun, keyin o'chirish (BL-070) | Buyurtma yozuvlari — qonuniy muddat bo'yicha | hamma domenlar (§7) | Muddat? |

**Texnik amalga oshirish:** har domen o'z rejali ishi `<domain>_retention_purge` (kunlik, advisory lock, 1000 tadan batch, `06`). Muddatlar `platform.retention_policies` da (platforma default + kerak bo'lsa shop bo'yicha). Domen ularni `platform.privacy.get_policy(shop_id, data_type)` orqali o'qiydi. Har tozalash audit'da: domen, tur, soni — mazmunsiz.

## 6. Xaridor so'rovlari

| So'rov | Qanday bajariladi | Muddat (taklif) |
|---|---|---|
| Ma'lumotlarimni ko'rsating | Ega dashboard'dan: `platform.privacy.export_requested` → har domen o'z qismini JSON'ga → `platform/storage` da arxiv, signed URL (24 soat) | 10 ish kuni |
| O'chiring | Ega "xaridorni anonimlashtirish": `platform.privacy.erasure_requested` (§2). Buyurtmalar anonim holda qoladi (qonuniy talab bo'lsa) | 10 ish kuni |
| Tuzating | Ega yoki operator kontaktni tahrirlaydi, audit bilan | Darhol |
| Meta talabi (Instagram foydalanuvchisini o'chirish callback'i) | `messaging` webhook → xuddi `erasure_requested` oqimi + tasdiq kodi | Meta talabi bo'yicha |

Xaridor qanday aniqlanadi: so'rov `customer_ref` bilan (`messaging.contacts.id`). Domenlar o'z jadvallarida shu ref yoki unga bog'langan `conversation_id`/`order_id` lar bo'yicha qidiradi; `commerce` va `support` buyurtma va murojaatlarda `contact_id` ni saqlaydi (FK'siz UUID, ADR-035).

Platformaga to'g'ridan-to'g'ri kelgan so'rov tegishli shopga yo'naltiriladi (biz qayta ishlovchimiz).

## 7. Shop bo'yicha eksport va o'chirish (ADR-035)

Shop pilotni to'xtatsa yoki yopilsa (`../business/13` §7, BL-070):

```
Platforma admini / ega "shopni yopish" ──▶ platform/shops: shop → CLOSING; kirish faqat eksport uchun
   ──▶ [platform.privacy.shop_export_requested] ──▶ har domen: WHERE shop_id = :id bo'yicha eksport
        ──▶ arxiv (JSON + CSV) platform/storage da ──▶ egaga havola (30 kun)
   ──▶ 30 kundan keyin: [platform.privacy.shop_purge_requested]
        ──▶ har domen o'z schemasida: DELETE ... WHERE shop_id = :id (1000 tadan batch)
        ──▶ commerce: qonuniy saqlash kerak bo'lgan buyurtmalar — anonim holda qoladi
        ──▶ har domen mark_part_done ──▶ platform: shop → CLOSED, audit
```

Qoidalar:
1. Har domen eksport/o'chirish handler'ini `DomainManifest.privacy_handlers` da e'lon qiladi; yangi domen qo'shilganda bu majburiy (`03` checklistiga qo'shiladi).
2. Schemalar ro'yxati `app/db/schemas.sql` dan; CI testi: shop jadvali bor har schemada privacy handler bor.
3. O'chirish idempotent: qayta ishga tushsa davom etadi.
4. Ommaviy takliflar (Stage 2) darhol olib tashlanadi (BL-070, `28`).
5. Dedicated rejimdagi shop (`10`) — butun stack nusxasi o'chiriladi, alohida runbook (`25`).

## 8. Rozilik va xabardor qilish

| Qayerda | Nima | Matn (uz, qoralama) |
|---|---|---|
| Birinchi AI javobi (`customer.ai_greeting`) | AI ekani, operator borligi | `20` §7 |
| Telefon so'ralganda | Maqsad | "Raqamingiz faqat buyurtma bo'yicha bog'lanish uchun ishlatiladi." |
| Sayt buyurtma formasi | Maqsad + maxfiylik siyosati havolasi, belgi | "Buyurtma bo'yicha bog'lanish uchun ma'lumotlarim ishlatilishiga roziman. [Maxfiylik siyosati]" |
| Sayt pastki qismi | Maxfiylik siyosati, shop rekvizitlari | Shop + platforma shabloni |
| Xodim taklifnomasi | Xodim ma'lumotlari va login tarixi | Foydalanish shartlari |
| Shop kelishuvi | Platforma roli, sub-processor'lar, AI o'qitilmasligi, muddatlar | `../business/14` |

Rozilik `commerce.orders.consent_version` va `messaging.contacts.notice_version` da saqlanadi. Marketing roziligi Stage 1 da yig'ilmaydi.

## 9. Texnik himoya (xulosa)

- Shop izolyatsiyasi: `10-security-tenancy-rbac.md` (`shop_id` serverdan, composite FK, RLS, TC-ISO).
- Shifrlash: TLS hamma joyda; DB va storage at rest; telefon, manzil, PII token xaritasi — ustun darajasida.
- LLM: faqat redact qilingan matn, zero-retention / no-training sharti (DEC-016, `14`).
- Telemetriya, audit, event payload'larda PII yo'q (CI'da log snapshot skaneri, `09`).
- Platforma jamoasi: odatiy holatda xaridor suhbatlarini ko'rmaydi; break-glass — sabab, muddat, audit (`10`, `25`).
- Fayllar: private bucket, qisqa muddatli signed URL, MIME tekshiruvi.

## 10. Sizib chiqish holatida

`25-operations-runbooks.md` RB-05: kirishni to'xtatish → ko'lamni aniqlash (qaysi shop, qaysi ma'lumot, qancha) → shoplarga xabar → qonun talab qilsa vakolatli organga (muddat va tartib — huquqshunos) → tuzatish va regression test.

## 11. Testlar

| ID | Sinov | Natija |
|---|---|---|
| TC-PRV-01 | Xaridorni anonimlashtirish | `messaging`, `commerce`, `support`, `platform` da PII yo'q; buyurtma qatorlari va hisobot raqamlari qoladi |
| TC-PRV-02 | `erasure_requested` 2 marta | Natija bir xil, xato yo'q |
| TC-PRV-03 | Shop purge | Barcha schemalarda `shop_id` bo'yicha 0 qator (qonuniy saqlanadiganlardan tashqari, anonim) |
| TC-PRV-04 | Yangi domen privacy handler'siz | CI yiqiladi |
| TC-PRV-05 | Log va outbox snapshot skaneri | Telefon, karta raqami, manzil topilmaydi |
| TC-PRV-06 | A shop eksporti | B shop ma'lumoti yo'q (TC-ISO) |

## 12. Huquqshunosga savollar

1. Xaridor ma'lumotlarini O'zbekistondagi serverda saqlash majburiyati bizga qanday qo'llaniladi (DEC-013)?
2. Redact qilingan matnni xorijiy LLM provayderiga yuborish transchegaraviy uzatish hisoblanadimi? Qanday shartlar kerak?
3. Grafana Cloud va Sentry'ga PII'siz telemetriya yuborish mumkinmi?
4. Platforma va shop o'rtasidagi rollar (egasi / qayta ishlovchi) va kelishuvda nima bo'lishi kerak?
5. §5 dagi muddatlar, ayniqsa buyurtma va hisob hujjatlari uchun majburiy muddatlar.
6. Rozilik matni (§8) yetarlimi; alohida yozma rozilik kerakmi?
7. Shaxsga doir ma'lumotlar bazasini ro'yxatdan o'tkazish talabi bormi?
8. Sizib chiqish holatida xabar berish muddati va tartibi.

## Keyingi qadam

→ [10-security-tenancy-rbac.md](10-security-tenancy-rbac.md) — shop izolyatsiyasi va ruxsatlar
→ [25-operations-runbooks.md](25-operations-runbooks.md) — RB-05 va break-glass
