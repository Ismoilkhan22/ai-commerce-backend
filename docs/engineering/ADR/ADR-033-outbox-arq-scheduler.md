# ADR-033: Outbox + arq navbati + APScheduler (advisory lock)

**Sana:** 2026-10-22
**Holat:** Accepted — ADR-005 ni almashtiradi (Superseded: ADR-005); ADR-006 ni o'zgartiradi
**Qaror qabul qiluvchi:** Founder
**Bog'liq:** DEC-003 D, TC-005, TC-010, TC-022, TC-032

## Kontekst

HTTP so'rovdan tashqaridagi ishlar ko'p: AI javobi, Telegram/Instagram'ga yuborish, eslatmalar (24/72 soat), katalog importi, xabarnomalar, muddati o'tgan takliflar. DEC-003 A da hammasi PostgreSQL ichida edi (PG leased jobs) — lease, retry, dead-letter va rejali ishlarni o'zimiz yozishimiz kerak edi (1–2 hafta). Bismuth v2 da outbox + arq + APScheduler ishlatiladi va sinalgan.

## Qaror

1. **Outbox — asosiy manba.** Holat o'zgarishi bilan bitta tranzaksiyada `<schema>.outbox_events` ga yoziladi (har domen schemasida o'z jadvali).
2. **`outbox_worker`** (1–2 nusxa): `FOR UPDATE SKIP LOCKED` bilan yozuvlarni oladi →
   - domen subscriber'larini chaqiradi (qisqa, DB ichidagi ishlar), yoki
   - arq'ga vazifa qo'yadi (`job_id = event_id` — arq bir xil job_id ni ikki marta qo'ymaydi),
   - so'ng `published_at` belgilaydi. Xato bo'lsa — `attempts++`, `next_attempt_at` (eksponensial), 10 urinishdan keyin `DEAD`.
3. **Navbatga faqat outbox orqali.** Service to'g'ridan-to'g'ri `arq.enqueue()` qilmaydi — server COMMIT va enqueue o'rtasida o'chsa vazifa yo'qolmasligi uchun.
4. **`task_worker`** (arq, 2–3 nusxa): tashqi chaqiruvlar va og'ir ishlar. Har task idempotent; tashqi xizmatga idempotency kaliti beriladi (imkon bo'lsa).
5. **`scheduler_worker`**: APScheduler; ishga tushganda `pg_try_advisory_lock(hash('scheduler_leader'))` — faqat bitta leader. Har rejali ish ham `job:<name>` lock bilan. Og'ir ish — arq'ga.
6. **Redis** AOF (`appendfsync everysec`) bilan; navbat DB'si keshdan alohida (`db=1`). Redis yo'qolsa — outbox'dagi `published_at IS NULL` yozuvlar qayta yuboriladi; arq'da bajarilmagan vazifalar uchun "rekonsilyatsiya" ishi (`06` §6).
7. ADR-006 o'zgaradi: Redis endi navbatni ham ushlaydi, lekin **haqiqat manbai emas** — manba outbox va domen jadvallari.

## Ko'rib chiqilgan variantlar

### Variant A — PG leased jobs (eski DEC-003 A)
- ❌ Rad etildi: retry, lease, dead-letter, cron'ni o'zimiz yozamiz; bismuth'dan farq.

### Variant B — Celery + RabbitMQ
- ❌ Rad etildi: qo'shimcha server; Celery async FastAPI'ga yomon mos.

### Variant C — arq to'g'ridan-to'g'ri (outbox'siz)
- ❌ Rad etildi: COMMIT va enqueue o'rtasida vazifa yo'qolishi mumkin.

## Oqibatlar

### Ijobiy
- Tayyor kutubxona: retry, kechiktirish, timeout, cron.
- Bismuth bilan bir xil — bilim va kod qayta ishlatiladi.
- Outbox tufayli hech narsa yo'qolmaydi.

### Salbiy
- Redis majburiy servis; uni kuzatish va backup kerak (AOF).
- Ikki joyda holat (outbox va arq) — rekonsilyatsiya ishi kerak.

### Neytral
- At-least-once: har consumer idempotent bo'lishi shart (`03` §6).

## Tekshiruv

- TC-022: worker vazifa o'rtasida o'chirildi → qayta ishga tushganda ish takrorlanmaydi.
- TC-010: bir xil webhook 3 marta → bitta xabar, bitta AI javobi.
- TC-032: Telegram 429 → cheklangan qayta urinish, takror xabar yo'q.
- Scheduler 3 nusxada ishga tushiriladi → har rejali ish 1 marta.

## Qayta ko'rish sharti

Navbat kechikishi p99 > 30 s doimiy bo'lsa yoki Redis xotirasi yetmasa — RabbitMQ yoki Redis Streams; event sxemasi va outbox o'zgarmaydi.

## Havolalar

- [05-events-and-outbox.md](../05-events-and-outbox.md), [06-background-jobs.md](../06-background-jobs.md)
- `bismuth_platform_v2/docs/v2/ADR/ADR-004-task-queue-arq.md`, `ADR-005-outbox-pattern.md`, `ADR-006-distributed-scheduler.md`
