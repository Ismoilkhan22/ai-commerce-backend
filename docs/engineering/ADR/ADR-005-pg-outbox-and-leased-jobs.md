# ADR-005: PostgreSQL outbox + PG leased job navbati

**Sana:** 2026-10-21 (v2 formatiga ko'chirildi 2026-10-22)
**Holat:** Superseded by ADR-033 (2026-10-22)
**Qaror qabul qiluvchi:** Founder
**Bog'liq:** DEC-003 (A → D), ADR-033

## Kontekst

Fon ishlari (AI javobi, xabar yuborish, eslatmalar, import) ishonchli saqlanishi va qayta urinilishi kerak edi; pilot hajmida qo'shimcha broker kerak emas deb hisoblangan.

## Qaror

(Tarixiy) PG `outbox_messages` va `jobs` jadvallari `FOR UPDATE SKIP LOCKED` bilan; lease, heartbeat, urinishlar, dead holat, operator replay. `LISTEN/NOTIFY` faqat uyg'otish uchun.

**2026-10-22:** almashtirildi — outbox PostgreSQL'da qoladi, vazifalar arq (Redis) navbatida, rejali ishlar APScheduler + advisory lock (ADR-033). Sabab: retry/lease/cron'ni o'zimiz yozmaslik, bismuth v2 bilan bir xillik.

## Ko'rib chiqilgan variantlar

### Kafka
- ❌ Rad etildi: pilot uchun ortiqcha

### RabbitMQ + Celery
- ❌ Rad etildi: qo'shimcha server, Celery async'ga yomon mos

## Oqibatlar

### Ijobiy
Bitta saqlash joyi, vazifa biznes ma'lumoti bilan atomik.

### Salbiy
Lease/retry/DLQ o'zimiz yozishimiz kerak edi; DB'ga yuk.

### Neytral
Outbox g'oyasi ADR-033 da saqlangan.

## Tekshiruv

—

## Qayta ko'rish sharti

—

## Havolalar

- Manba: eski `05_ARCHITECTURE_DECISIONS_ADR.md` (v1)
- [../../decisions/DECISION_REGISTER.md](../../decisions/DECISION_REGISTER.md)
