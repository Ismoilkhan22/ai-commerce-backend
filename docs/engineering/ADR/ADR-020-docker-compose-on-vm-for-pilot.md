# ADR-020: Pilot uchun VM'da Docker Compose

**Sana:** 2026-10-21 (v2 formatiga ko'chirildi 2026-10-22)
**Holat:** Accepted (2026-10-21)
**Qaror qabul qiluvchi:** Founder
**Bog'liq:** ADR-030, DEC-013

## Kontekst

Kubernetes bitta odam uchun operatsion yuk; pilot hajmi kichik.

## Qaror

1. O'zbekistondagi VM'da Docker Compose: api, outbox-worker, task-worker, scheduler, PostgreSQL, Redis, MinIO, nginx.
2. Production secret'lar va backup'lar alohida; staging — sintetik ma'lumot.

## Ko'rib chiqilgan variantlar

### Kubernetes birinchi kundan
- ❌ Rad etildi: operatsion murakkablik

## Oqibatlar

### Ijobiy
Oddiy operatsiya.

### Salbiy
Yuqori mavjudlik cheklangan.

### Neytral
Batafsil `22`.

## Tekshiruv

Backup'dan tiklash mashqi (TC-033).

## Qayta ko'rish sharti

HA yoki masshtab maqsadlari orkestratsiyani talab qilsa.

## Havolalar

- Manba: eski `05_ARCHITECTURE_DECISIONS_ADR.md` (v1)
- [../../decisions/DECISION_REGISTER.md](../../decisions/DECISION_REGISTER.md)
