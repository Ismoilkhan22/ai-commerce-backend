# ADR-006: Redis — kesh, rate limit, vaqtinchalik holat; haqiqat manbai emas

**Sana:** 2026-10-21 (v2 formatiga ko'chirildi 2026-10-22)
**Holat:** Accepted (2026-10-21) — ADR-033 bilan o'zgartirildi (Redis arq navbatini ham ushlaydi)
**Qaror qabul qiluvchi:** Founder
**Bog'liq:** ADR-033, DEC-003

## Kontekst

Narx, qoldiq va navbat ma'lumoti yo'qolsa, pul va ishonchga zarar. Redis xotirada ishlaydi va qayta ishga tushganda ma'lumot yo'qolishi mumkin.

## Qaror

1. Redis: kesh, token bucket rate limit, WebSocket pub/sub, qisqa muddatli holat.
2. Rate limit Redis ishlamasa — **fail closed** (xavfsiz tomonga).
3. Narx, qoldiq, buyurtma — faqat PostgreSQL.
4. **2026-10-22 (ADR-033):** Redis arq vazifa navbatini ham ushlaydi (AOF bilan), lekin manba — outbox: vazifa faqat outbox orqali navbatga tushadi, Redis yo'qolsa outbox qayta yuboradi.

## Ko'rib chiqilgan variantlar

### Redis'da qoldiq yoki navbat manbai
- ❌ Rad etildi: yo'qolish xavfi

## Oqibatlar

### Ijobiy
PostgreSQL haqiqat manbai bo'lib qoladi.

### Salbiy
Redis endi majburiy servis (navbat uchun).

### Neytral
Kesh kalitlarida shop prefiksi majburiy.

## Tekshiruv

Redis o'chirilgan holda smoke test: rate limit yopiq, navbat outbox'dan tiklanadi.

## Qayta ko'rish sharti

Doimiy yuklama alohida broker talab qilsa.

## Havolalar

- Manba: eski `05_ARCHITECTURE_DECISIONS_ADR.md` (v1)
- [../../decisions/DECISION_REGISTER.md](../../decisions/DECISION_REGISTER.md)
