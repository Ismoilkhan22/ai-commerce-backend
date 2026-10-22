# 25 — Operatsion runbook'lar va hodisalarni boshqarish

> **Versiya:** v2 (2026-10-22). Eski `33_OPERATIONS_RUNBOOKS` va `19_INFRASTRUCTURE_AND_DEPLOYMENT` §7 o'rnini bosadi; outbox + arq + Redis (DEC-003 D, ADR-033) ga moslandi.
> **Kim uchun:** navbatchi (pilotda — founder), support, keyinroq ops jamoasi.
> **Qoida:** pilotdan oldin har runbook staging'da kamida bir marta mashq qilinadi (§6).

## 1. Muammo va yechim

**Muammo:** tunda Telegram'ga "outbox to'xtadi" alerti keldi. Nima qilish kerak — o'ylab o'tirishga vaqt yo'q, noto'g'ri qadam (masalan, qoldiqni qo'lda `UPDATE` qilish) vaziyatni yomonlashtiradi.

**Yechim:** har ehtimoliy hodisa uchun oldindan yozilgan qadamlar, kill switch'lar va postmortem. Alertlar (`09` §7) to'g'ridan-to'g'ri shu runbook'larga havola qiladi.

**Asosiy qoidalar:**
1. Avval **zararni cheklash** (kill switch), keyin sababni izlash.
2. Pul, qoldiq va holat — hech qachon to'g'ridan-to'g'ri SQL `UPDATE` bilan tuzatilmaydi. Faqat domen service'i, `ADJUSTMENT` ledger yozuvi yoki `use.force_transition` (sabab va audit bilan).
3. Har SEV-1/2 dan keyin postmortem (§5).

---

## 2. Muhimlik darajalari

| Daraja | Misollar | Javob (maqsad) | Kim xabardor |
|---|---|---|---|
| **SEV-1** | Bir shop ma'lumoti boshqasiga ko'rindi (RLS buzilishi); AI noto'g'ri narx yoki "buyurtma tasdiqlandi" deb yozdi; qoldiq minus; production butunlay ishlamayapti; ma'lumot yo'qolishi | 15 daqiqa | Founder (telefon + Telegram), ta'sirlangan shop egasi |
| **SEV-2** | Bitta kanal ishlamayapti; LLM ishlamayapti; outbox yoki arq 10+ daqiqa to'xtagan; Redis yo'q; scheduler leader yo'q; backup o'tkazib yuborildi | 1 soat | Founder |
| **SEV-3** | Bitta funksiyada xato, aylanib o'tish yo'li bor; hisobot kechikmoqda; dead-letter'da oddiy xabarnoma | 1 ish kuni | Tiket |

---

## 3. Kill switch'lar va boshqaruv tugmalari

| Tugma | Qayerda | Ta'siri | Qaytarish |
|---|---|---|---|
| Shop AI rejimi | Shop paneli (ega) / platforma paneli | `AUTO → SUGGEST → OFF` (`14`); `OFF` da xabarlar operatorga | Ega yoki platforma |
| Global AI o'chirish | Platforma paneli, feature flag `ai.global_enabled` | Barcha shoplarda AI `OFF`, `sales_ai` subscriber'lari vazifa qo'ymaydi | Platforma, sabab bilan |
| Kanal chiquvchi xabarlarini to'xtatish | Platforma paneli (kanal akkaunti bo'yicha) | `channel_send` vazifalari shu akkaunt uchun kechiktiriladi (yo'qolmaydi) | Platforma |
| Outbox dispatch pauza | Feature flag `outbox.paused` (schema yoki event_type bo'yicha) | `outbox-worker` shu yozuvlarni olmaydi; ular DB'da kutadi | Platforma — pauza tugagach o'zi davom etadi |
| arq navbatini to'xtatish | `task-worker` ni to'xtatish (`docker compose stop task-worker`) | Vazifalar Redis'da kutadi | Qayta ishga tushirish |
| SKU sotuvini bloklash | Shop paneli (menejer) | Shu SKU uchun tasdiqlash va tez sotuv rad etiladi | Menejer |
| Moslik qoidalari rollback | Platforma paneli | Oldingi ruleset versiyasi faol (`17`) | Platforma |
| Prompt versiyasi rollback | Platforma paneli | Oldingi `prompt_version` faol (`14`) | Platforma |
| Maintenance rejimi | Feature flag / nginx | Yozish so'rovlari 503 `SERVICE_UNAVAILABLE`, o'qish ishlaydi; webhook'lar 503 (provayder keyin qayta yuboradi) | Infra |

Har tugma bosilishi `platform/audit` ga yoziladi (kim, qachon, sabab).

---

## 4. Runbook'lar

### RB-01 — LLM provayderi ishlamayapti yoki juda sekin (SEV-2)
**Belgilar:** `cos_llm_requests_total{outcome="provider_error"}` ulushi > 20%; `cos_sales_ai_first_reply_duration_seconds` p90 > 15 s; handoff'larda `PROVIDER_UNAVAILABLE` sababi.
1. Provayder status sahifasini tekshirish.
2. Zaxira provayder sozlangan va DEC-016 shartlariga mos bo'lsa — `platform/llm` routing'ini almashtirish (ADR-027).
3. Zaxira yo'q — global yoki ta'sirlangan shoplarda AI `OFF`; xaridorga avtomatik `customer.handoff_notice` (`20`).
4. Shop egalariga: "AI vaqtincha o'chirildi, xabarlar operatorga tushmoqda".
5. arq'da kutayotgan `ai_reply` vazifalari: tiklangach **eski xabarlarga javob berilmaydi** — task suhbat holatini qayta o'qiydi; 10 daqiqadan eski xabar bo'lsa yoki speaker o'zgargan bo'lsa — vazifa tashlanadi (`14`).
6. AI xarajati keskin oshgan bo'lsa (alert): `platform/billing` limitlarini tekshirish, sababchi shop yoki suhbatni topish (DB hisoboti), kerak bo'lsa shu shopda AI `OFF`.
7. Postmortem.

### RB-02 — AI noto'g'ri narx, mavjud bo'lmagan mahsulot yoki "tasdiqlandi" deb yozdi (SEV-1)
1. Ta'sirlangan shopda AI `SUGGEST` yoki `OFF`.
2. Suhbat bo'yicha (`conversation_id` → `trace_id`): qaysi `prompt_version`, qaysi tool natijasi, javob tekshiruvi (`ai.validate_reply`) nega o'tkazib yubordi.
3. Xaridorga operator orqali tuzatish xabari (shop bilan kelishib).
4. Sabab bo'yicha: javob tekshiruvi qoidasini kuchaytirish (`14`) / prompt rollback / tool xatosini tuzatish.
5. Holat red-team to'plamiga qo'shiladi (`16`); eval o'tgach AI qayta yoqiladi.

### RB-03 — Qoldiq minus yoki ledger mos kelmaydi (SEV-1)
**Belgilar:** `cos_commerce_stock_negative_total` yoki `..._ledger_mismatch_total` > 0; DB CHECK xatosi; shop "tizimda bor, omborda yo'q" deydi.
1. Ta'sirlangan SKU'ni bloklash (§3).
2. `commerce.stock_balances`, `commerce.stock_ledger`, `commerce.stock_reservations` va oxirgi buyurtma / tez sotuv yozuvlarini solishtirish (`12`).
3. Shopdan jismoniy sanoq. Tuzatish faqat `ADJUSTMENT` ledger yozuvi va sabab bilan (BL-022) — to'g'ridan-to'g'ri `UPDATE` yo'q.
4. Ta'sirlangan buyurtmalar: operator xaridor bilan bog'lanadi (muqobil yoki bekor qilish).
5. Concurrency testiga reproducer qo'shish (`tests/concurrency/`); SKU blokdan chiqariladi.

### RB-04 — Telegram yoki Instagram ulanishi uzildi (SEV-2)
**Belgilar:** `cos_messaging_channel_degraded` = 1; `cos_messaging_send_failed_total` oshgan; webhook jim; webhook ACK sekin.
1. Sabab: token bekor qilingan / muddati tugagan / ruxsat olib tashlangan / provayder nosozligi / 429 (rate limit).
2. Shop egasiga qayta ulash ko'rsatmasi (`staff.channel_degraded` xabari, `20`).
3. Telegram: `getWebhookInfo` — oxirgi xato; kerak bo'lsa `setWebhook` qayta. Instagram: token yangilash yoki qayta OAuth (`13`).
4. Uzilish paytidagi chiquvchi xabarlar: `channel_send` vazifalari retry qiladi; 10 urinishdan keyin dead-letter (RB-13) — mazmuni hali dolzarbmi, operator hal qiladi.
5. Kiruvchi xabarlar: provayder qayta yuborsa, `(provider, event_id)` dedup ishlaydi; yo'qolgan bo'lsa — operator xaridorlar ro'yxatini qo'lda tekshiradi.

### RB-05 — Boshqa shop ma'lumoti ko'rindi yoki RLS buzilishi alerti (SEV-1)
**Belgilar:** `cos_security_rls_violation_total` > 0; `cos_security_cross_shop_access_attempt_total` keskin oshgan; shop yoki xaridor shikoyati.
1. **Darhol:** ta'sirlangan endpoint yoki funksiyani o'chirish (feature flag yoki maintenance); AI bilan bog'liq bo'lsa — global AI o'chirish.
2. RLS alerti — ya'ni app-layer filtri ishlamagan, RLS ushlab qolgan: so'rov `trace_id` bo'yicha qaysi kod yo'lidan kelganini topish. Ma'lumot chiqmagan bo'lishi mumkin, lekin bu baribir SEV-1 (birinchi qavat buzilgan).
3. Dalillarni saqlash: loglar, audit, `trace_id`'lar (yangi PII tarqatmasdan).
4. Ko'lam: qaysi shoplar, qaysi ma'lumot turi, nechta yozuv, qancha vaqt.
5. Founder + huquqshunos: shoplarga va (qonun talab qilsa) vakolatli organga xabar (`26`).
6. Tuzatish, TC-ISO regression testi, xavfsizlik ko'rigi — shundan keyingina qayta yoqish.

### RB-06 — Outbox to'xtab qoldi (SEV-2)
**Belgilar:** `cos_outbox_oldest_age_seconds` > 120 s 10 daqiqa; xabarnomalar va AI javoblari ketmayapti.
1. `outbox-worker` jarayoni ishlayaptimi (`docker compose ps`, loglar)? DB ulanishlari yetarlimi?
2. `outbox.paused` flag'i yoqilib qolmaganmi?
3. Bitta "zaharli" yozuv navbatni to'sayotgan bo'lsa (bir xil `event_id` qayta-qayta xato): uni `DEAD` ga o'tkazish (sabab bilan, audit) — RB-13.
4. Redis ishlamayotgan bo'lsa — outbox arq'ga yoza olmaydi: RB-11.
5. Jarayonni qayta ishga tushirish. `FOR UPDATE SKIP LOCKED` tufayli ikki nusxa xavfsiz.
6. Tiklangach backlog o'zi ishlanadi; kech ketadigan xabarlar dolzarbligini tekshirish (masalan, 3 soat oldingi "AI javobi" — yuborilmaydi, RB-01 5-qadam).

### RB-07 — Production DB ishlamayapti (SEV-1)
1. Ilova yozishni to'xtatadi; webhook'lar 503 qaytaradi (yolg'on 200 emas) — provayderlar keyin qayta yuboradi.
2. DB holati: disk joyi (ayniqsa WAL), ulanishlar soni, xotira; loglar.
3. Disk to'lgan — eski WAL arxivini backup joyiga ko'chirish, audit partition'larini tekshirish.
4. Tiklab bo'lmasa — RB-08.
5. Tiklangach: outbox backlog avtomatik ishlaydi; qoldiq rekonsilyatsiyasi (RB-03, 2-qadam) bajariladi.

### RB-08 — Backup'dan tiklash (SEV-1; mashq — oyiga bir marta staging'da, TC-033)
1. Kerakli vaqt nuqtasi tanlanadi (hodisadan oldin).
2. Oxirgi to'liq backup + WAL bilan tiklash (`22` §7).
3. Tekshiruv: jadvallar soni har schemada; ledger yig'indisi = balans; RLS siyosatlari; FK butunligi.
4. Outbox: `published_at IS NULL` yozuvlar qayta yuboriladi (subscriber'lar idempotent).
5. arq navbati (Redis) bo'shatiladi yoki tiklangan DB bilan mos kelmasa — tozalanadi; rekonsilyatsiya ishi outbox'dan qayta yaratadi.
6. Tiklash nuqtasidan keyingi yo'qolgan davr: kanal provayderlari qayta yuborgan event'lar dedup bilan qabul qilinadi; shoplarga yo'qolgan davr haqida xabar (o'sha davrdagi buyurtmalarni qo'lda tekshirish).
7. Vaqt (RTO) va yo'qolgan davr (RPO) jurnalga yoziladi.

### RB-09 — Noto'g'ri PC moslik natijasi (SEV-1, agar xaridorga yuborilgan bo'lsa)
1. Qoidami yoki texnik ma'lumot xatosimi — `catalog` moslik natijalari jurnalidan (ruleset versiyasi, spec versiyasi).
2. Ruleset rollback yoki spec tuzatish (ikki kishi tekshiruvi, `17`).
3. Shu qoida yoki spec ta'sir qilgan ochiq takliflar va buyurtmalarni topish va qayta tekshirish; yuborilgan takliflar bo'yicha operator xaridor bilan bog'lanadi.
4. Golden set'ga regression qo'shish.

### RB-10 — Platforma jamoasi shop ma'lumotiga kirishi kerak (break-glass)
1. Shop egasining yozma so'rovi yoki tiket.
2. Platforma panelida vaqtinchalik ruxsat: sabab, muddat (≤ 4 soat), faqat kerakli resurs.
3. Barcha harakatlar audit'da; `cos_security_break_glass_active` = 1; muddat tugagach avtomatik bekor.
4. Shop egasiga kim, qachon, nima uchun kirgani haqida xabar.

### RB-11 — Redis ishlamayapti (SEV-2)
**Belgilar:** `/health/ready` Redis xatosi; arq va kesh xatolari; WebSocket ulanishlar uzilgan.
**Ta'sir:** kesh yo'q (sekinroq, lekin to'g'ri); rate limit — konservativ rejim (in-memory, har jarayonda kichik limit); arq vazifalari qo'yilmaydi va bajarilmaydi; inbox real-time yangilanmaydi. **Pul va qoldiqqa ta'sir yo'q** — haqiqat manbai PostgreSQL.
1. Redis jarayoni, xotira (`maxmemory`), disk (AOF) tekshiriladi.
2. Qayta ishga tushirish; AOF'dan tiklanadi.
3. AOF buzilgan bo'lsa — `redis-check-aof --fix` yoki oxirgi RDB; yo'qolgan arq vazifalari:
4. **Rekonsilyatsiya:** `python -m app.workers.reconcile_tasks` — outbox'da `published_at` belgilangan, lekin natijasi yo'q (masalan, `channel_send` uchun yuborilgan holati yo'q) yozuvlar uchun vazifani qayta qo'yadi (`06`).
5. Outbox Redis yo'qligida `published_at` belgilamaydi — o'zi qayta urinadi.

### RB-12 — arq navbati to'lib ketdi (SEV-2)
**Belgilar:** `cos_arq_oldest_job_age_seconds` > 120 s; `cos_arq_queue_depth` o'sib bormoqda.
1. Qaysi vazifa turi ko'p (`cos_arq_queue_depth`, `cos_arq_job_duration_seconds` job bo'yicha)?
2. Sekin tashqi xizmat (LLM, Telegram 429)? — provider concurrency chegarasini tekshirish; RB-01 yoki RB-04.
3. Katalog importi kabi ommaviy ish navbatni bosgan bo'lsa — import vazifalari past ustuvorlikdagi navbatda bo'lishi kerak (`06`); vaqtincha import'ni to'xtatish.
4. `task-worker` nusxasini qo'shish (`docker compose up -d --scale task-worker=4`) — LLM rate limit'ga e'tibor.
5. Eskirgan vazifalar (AI javobi 10 daqiqadan eski) o'zi tashlanadi (RB-01 5-qadam).

### RB-13 — Dead-letter'dagi yozuvlarni ko'rib chiqish va qayta yuborish (SEV-3, buyurtma event'i bo'lsa SEV-2)
**Belgilar:** `cos_outbox_dead_total` yoki `cos_arq_job_failed_total` o'sishi.
1. Platforma panelidagi dead-letter ro'yxati: event_type, sabab (oxirgi xato), urinishlar, shop, vaqt. Payload — redact qilingan ko'rinishda.
2. Sababni tuzatish (kod xatosi → reliz; tashqi xizmat → kutish; ma'lumot xatosi → tuzatish).
3. Qayta yuborish ("replay") — platforma admini, sabab bilan, audit'ga yoziladi. Subscriber idempotent — takror ta'sir yo'q.
4. Eskirgan xabarlar (masalan, 2 kun oldingi "buyurtmangiz tayyor") — qayta yuborilmaydi, `DISCARDED` deb belgilanadi (sabab bilan).

### RB-14 — Scheduler ishlamayapti yoki ikkita leader (SEV-2)
**Belgilar:** `sum(cos_scheduler_leader)` = 0 yoki > 1; `cos_scheduler_job_lag_seconds` > 30 s; eslatmalar ketmayapti.
1. `scheduler` jarayoni(lari) ishlayaptimi?
2. Leader yo'q: advisory lock "osilib" qolgan bo'lishi mumkin (o'lik ulanish). `pg_locks` / `pg_stat_activity` dan lock egasini topish; ulanish o'lik bo'lsa — `pg_terminate_backend(pid)`. Lock sessiya bilan birga ozod bo'ladi.
3. Ikki leader (bo'lmasligi kerak): darhol bitta nusxani to'xtatish; lock kalitlari kodda bir xilligini tekshirish. Har rejali ish o'zining `job:<name>` lock'i va idempotency kaliti bilan himoyalangan — takror bajarilish zarar keltirmaydi, lekin sabab topilishi shart.
4. O'tkazib yuborilgan rejali ishlar: scheduler qayta ishga tushganda `misfire_grace_time` ichidagilar bajariladi; qolganlari (masalan, 24 soatlik eslatmalar) keyingi ishga tushishda holatga qarab yuboriladi (`06`).

---

## 5. Postmortem shabloni

```text
Hodisa ID / sana / daraja:
Ta'sir: qaysi shoplar, nechta xaridor, qanday ma'lumot yoki noto'g'ri xabar:
Vaqt chizig'i: aniqlandi → cheklandi → tuzatildi:
Asosiy sabab:
Nega oldinroq aniqlanmadi (qaysi alert yoki test yo'q edi):
Tuzatish (darhol / uzoq muddatli):
Qo'shilgan test yoki alert:
Shoplarga va xaridorlarga xabar:
Mas'ul va muddat:
```
Postmortem ayblash uchun emas: maqsad — xuddi shu hodisa takrorlanmasligi uchun test yoki alert qo'shish.

---

## 6. Pilotdan oldin tekshiruv ro'yxati

- [ ] Alertlar founder Telegram'iga keladi (har SEV-1/2 alert uchun staging'da sinov signali yuborilgan, `09` §7)
- [ ] Global AI o'chirish, kanal chiquvchi xabarlarini to'xtatish va `outbox.paused` staging'da sinalgan
- [ ] RB-03, RB-06, RB-08, RB-11, RB-14 staging'da mashq qilingan, natija yozilgan
- [ ] Tiklash mashqi (TC-033) o'tgan, RPO/RTO yozilgan
- [ ] Dead-letter ro'yxati va replay (RB-13) platforma panelida ishlaydi
- [ ] Shop egalari uchun "AI o'chirildi" va "kanal uzildi" xabarlari tayyor (`20`)
- [ ] Break-glass jarayoni va audit ishlaydi
- [ ] Huquqshunos bilan ma'lumot sizib chiqqanda xabar berish tartibi kelishilgan (`26`)

## Keyingi qadam

→ [26-privacy-and-retention.md](26-privacy-and-retention.md) — shaxsiy ma'lumot va saqlash muddatlari
→ [09-observability.md](09-observability.md) — alertlar manbai
