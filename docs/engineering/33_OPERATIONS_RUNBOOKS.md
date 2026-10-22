# TECH-33 — Operatsion runbook'lar va hodisalarni boshqarish

**Status:** Baseline (2026-10-22). TECH-12 (alertlar), TECH-19 §7 (playbook jadvali), TECH-23 (izolyatsiya), TECH-32 §7 (breach). Pilotdan oldin har runbook staging'da kamida bir marta mashq qilinadi.
**Kim uchun:** navbatchi (pilotda — founder), support, keyinchalik ops jamoasi.

---

## 1. Muhimlik darajalari

| Daraja | Misol | Javob vaqti (maqsad) | Kim xabardor qilinadi |
|---|---|---|---|
| **SEV-1** | Tenant ma'lumoti boshqasiga ko'rindi; AI noto'g'ri narx yoki "tasdiqlandi" deb yozdi; stok minusga tushdi; production ishlamayapti | 15 daqiqa | founder (telefon + Telegram), ta'sirlangan do'kon egasi |
| **SEV-2** | Bitta kanal ishlamayapti; AI provayder ishlamayapti; outbox 10+ daqiqa to'xtagan | 1 soat | founder |
| **SEV-3** | Bitta funksiyada xato, aylanib o'tish yo'li bor; hisobot kechikmoqda | 1 ish kuni | tiket |

Alertlar Grafana alerting → founder Telegram'i (TECH-12, DEC-012). Har SEV-1/2 dan keyin postmortem (§4).

## 2. Kill switch va boshqaruv tugmalari

| Tugma | Qayerda | Ta'siri |
|---|---|---|
| AI rejimi (merchant) | dashboard / platform admin | `AUTO → SUGGEST → OFF` (TECH-26 §2) |
| Global AI kill switch | platform admin, feature flag | barcha do'konlarda AI `OFF`, xabarlar operatorga |
| Kanal outbound to'xtatish | platform admin (kanal akkaunti bo'yicha) | shu akkauntdan chiquvchi xabarlar navbatda to'xtaydi |
| SKU sotuvini bloklash | dashboard (Manager) | SKU `available` ga qaramay confirm/quick-sale rad etiladi |
| Ruleset rollback | platform admin | oldingi `pc_rulesets` versiyasi aktiv (TECH-25 §8) |
| Prompt version rollback | platform admin | oldingi `prompt_versions` aktiv |
| Maintenance rejimi | infra | yozish so'rovlari 503 `SERVICE_UNAVAILABLE`, o'qish ishlaydi |

## 3. Runbook'lar

### RB-01 — LLM provayderi ishlamayapti (SEV-2)
**Belgilar:** `ai_requests_total{outcome="provider_error"}` keskin oshgan, `PROVIDER_UNAVAILABLE` handoff'lar.
1. Provayder status sahifasini tekshirish; zaxira provayder sozlangan bo'lsa — routing'ni almashtirish (ADR-027; DEC-016 shartlariga mos bo'lsa).
2. Zaxira yo'q bo'lsa — ta'sirlangan do'konlarda AI `OFF`; xaridorlarga `customer.handoff_notice` avtomatik.
3. Do'kon egalariga xabar: "AI vaqtincha o'chirildi, xabarlar operatorga tushmoqda".
4. Tiklangach: navbatdagi AI job'lari qayta ishga tushmaydi (eski xabarlarga kech javob bermaslik uchun) — operator ko'rib chiqqan suhbatlarda AI `resume_ai` bilan qaytadi.
5. Postmortem (SEV-2).

### RB-02 — AI noto'g'ri narx, mavjud bo'lmagan mahsulot yoki "tasdiqlandi" deb yozdi (SEV-1)
1. Ta'sirlangan do'konda AI `SUGGEST` yoki `OFF`.
2. `ai_tool_executions` va javob log'idan: qaysi suhbat, qaysi `prompt_version`, qaysi tool natijasi, validator nega o'tkazib yubordi.
3. Xaridorga operator orqali tuzatish xabari (do'kon bilan kelishib).
4. Sabab bo'yicha: validator qoidasini kuchaytirish (TECH-26 §8) / prompt rollback / tool xatosini tuzatish.
5. Holatni red-team to'plamiga qo'shish; eval o'tgach AI qayta yoqiladi.

### RB-03 — Stok minus yoki ledger mos kelmaydi (SEV-1)
**Belgilar:** `stock_reconciliation_discrepancy_total > 0`, DB CHECK xatosi, do'kon "tizimda bor, omborda yo'q" deydi.
1. Ta'sirlangan SKU'ni bloklash (§2).
2. `stock_balances`, `stock_ledger`, `stock_reservations` va oxirgi buyurtma/quick-sale yozuvlarini solishtirish (TECH-07 §2).
3. Do'kondan jismoniy sanoq; qo'lda tuzatish faqat `ADJUSTMENT` ledger yozuvi va sabab bilan (BL-022), to'g'ridan-to'g'ri UPDATE yo'q.
4. Ta'sirlangan buyurtmalar: operator xaridor bilan bog'lanadi (muqobil yoki bekor qilish).
5. Concurrency testiga reproducer qo'shish; SKU blokdan chiqariladi.

### RB-04 — Telegram yoki Instagram ulanishi uzildi (SEV-2)
**Belgilar:** kanal `DEGRADED`/`DISCONNECTED`, `outbound_failures_total` oshgan, webhook jim.
1. Sabab: token bekor qilingan / muddati tugagan / ruxsat olib tashlangan / provayder nosozligi.
2. Do'kon egasiga qayta ulash ko'rsatmasi (`staff.channel_degraded`).
3. Telegram: `getWebhookInfo` bilan oxirgi xato; kerak bo'lsa `setWebhook` qayta. Instagram: token yangilash yoki qayta OAuth.
4. Uzilish paytidagi xabarlar: provayder qayta yuborsa dedup ishlaydi; yo'qolgan bo'lsa — operator xaridorlar ro'yxatini qo'lda tekshiradi.

### RB-05 — Ma'lumot sizib chiqishi ehtimoli: boshqa do'kon ma'lumoti ko'rindi (SEV-1)
1. **Darhol:** ta'sirlangan endpoint/feature'ni o'chirish (feature flag yoki maintenance), kerak bo'lsa global AI kill switch.
2. Dalillarni saqlash: log'lar, audit, so'rov ID'lari (yangi PII tarqatmasdan).
3. Ko'lam: qaysi do'konlar, qaysi ma'lumot turi, qancha yozuv, qancha vaqt.
4. Founder + huquqshunos: do'konlarga va (qonun talab qilsa) vakolatli organga xabar (TECH-32 §7, §8 savol 8).
5. Tuzatish, TC-ISO regression testi, xavfsizlik review'idan keyingina qayta yoqish.

### RB-06 — Outbox / job'lar to'xtab qoldi (SEV-2)
**Belgilar:** `oldest_job_age_seconds` > 600, xabarnomalar ketmayapti.
1. Worker process'lari ishlayaptimi, DB ulanishlari yetarlimi.
2. Bitta "zaharli" job barcha navbatni to'sayotgan bo'lsa — uni `DEAD` holatiga o'tkazish (sabab bilan, audit).
3. Worker'larni qayta ishga tushirish; lease muddati o'tgan job'lar avtomatik qaytadi (TECH-09).
4. DLQ'dagi job'larni ko'rib chiqish va kerak bo'lsa replay (audit bilan); xaridorga kech ketgan xabarlar mazmuni hali dolzarbligini tekshirish.

### RB-07 — Production DB ishlamayapti (SEV-1)
1. Ilova yozishni to'xtatadi (webhook'lar 503 — provayderlar keyin qayta yuboradi).
2. DB holati: disk, ulanishlar, replikatsiya; tiklab bo'lmasa — RB-08.
3. Tiklangach: outbox backlog avtomatik ishlaydi; stok reconciliation (RB-03 2-qadam) bajariladi.

### RB-08 — Backup'dan tiklash (SEV-1, mashq — oyiga bir marta staging'da)
1. Oxirgi to'liq backup + WAL bilan kerakli vaqt nuqtasiga tiklash (TECH-19 §6).
2. Integrity: FK, ledger yig'indisi = balans, outbox holati.
3. Tiklash nuqtasidan keyingi ma'lumot yo'qolgan bo'lsa: kanal provayderlaridan qayta yuborilgan event'lar dedup bilan qabul qilinadi; do'konlarga yo'qolgan davr haqida xabar.
4. Natija va vaqt (RTO) qayd qilinadi.

### RB-09 — Noto'g'ri PC moslik natijasi (SEV-1 agar xaridorga yuborilgan bo'lsa)
1. Ruleset yoki spec xatosimi — `compatibility_results` dan aniqlash.
2. Ruleset rollback yoki spec tuzatish (ikki ko'z bilan, TECH-25 §9).
3. Shu qoida/spec ta'sir qilgan ochiq quote va buyurtmalarni topish va qayta tekshirish; yuborilgan quote'lar bo'yicha operator xaridor bilan bog'lanadi.
4. Golden set'ga regression qo'shish.

### RB-10 — Platforma support do'kon ma'lumotiga kirishi kerak (break-glass)
1. Do'kon egasining yozma so'rovi yoki tiket.
2. Platform admin'da vaqtinchalik grant: sabab, muddat (≤ 4 soat), faqat kerakli resurs.
3. Barcha harakatlar audit'da; muddat tugagach avtomatik bekor.
4. Do'kon egasiga kim, qachon, nima uchun kirgani haqida xabar.

## 4. Postmortem shabloni

```text
Hodisa ID / sana / daraja:
Ta'sir: qaysi do'konlar, nechta xaridor, qanday ma'lumot yoki noto'g'ri xabar:
Vaqt chizig'i: aniqlandi → cheklandi → tuzatildi:
Asosiy sabab:
Nega oldinroq aniqlanmadi:
Tuzatish (darhol / uzoq muddatli):
Qo'shilgan test yoki alert:
Do'konlarga va xaridorlarga xabar:
Mas'ul va muddat:
```

Postmortem ayblash uchun emas: maqsad — xuddi shu hodisa takrorlanmasligi uchun test yoki alert qo'shish.

## 5. Pilotdan oldin tekshiruv ro'yxati

- [ ] Alertlar founder Telegram'iga keladi (staging'da sinov alerti yuborilgan)
- [ ] Global AI kill switch va kanal outbound to'xtatish staging'da sinalgan
- [ ] RB-03, RB-06, RB-08 staging'da mashq qilingan, natija yozilgan
- [ ] Do'kon egalari uchun "AI o'chirildi" va "kanal uzildi" xabarlari tayyor
- [ ] Break-glass jarayoni va audit ishlaydi
- [ ] Huquqshunos bilan breach xabar berish tartibi kelishilgan (TECH-32 §8)
