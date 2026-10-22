# ADR-004: SQLAlchemy 2 async + Alembic

**Sana:** 2026-10-21 (v2 formatiga ko'chirildi 2026-10-22)
**Holat:** Accepted (2026-10-21)
**Qaror qabul qiluvchi:** Founder
**Bog'liq:** ADR-035

## Kontekst

So'rovlar ko'p tashqi I/O kutadi (DB, Redis); sinxron DB kirishi event loop'ni bloklaydi.

## Qaror

1. SQLAlchemy 2.0 async + asyncpg; tranzaksiya chegarasi aniq (`async with db.begin()`).
2. Session — method argumenti, class field emas.
3. Alembic migratsiyalari; har schema uchun alohida env (ADR-035).

## Ko'rib chiqilgan variantlar

### Sinxron DB kirishi
- ❌ Rad etildi: event loop bloklanadi

## Oqibatlar

### Ijobiy
Non-blocking I/O, aniq tranzaksiyalar.

### Salbiy
Async lazy-load xatolari — eager loading majburiy.

### Neytral
Drayver muammosi bo'lsa psycopg3 async ko'rib chiqiladi.

## Tekshiruv

Pool va rollback testlari (S0-03).

## Qayta ko'rish sharti

Drayver ishlash muammolari o'lchansa.

## Havolalar

- Manba: eski `05_ARCHITECTURE_DECISIONS_ADR.md` (v1)
- [../../decisions/DECISION_REGISTER.md](../../decisions/DECISION_REGISTER.md)
