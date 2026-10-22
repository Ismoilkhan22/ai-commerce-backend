# ADR-013: Stage 1 qidiruvi — PostgreSQL FTS va trigram

**Sana:** 2026-10-21 (v2 formatiga ko'chirildi 2026-10-22)
**Holat:** Accepted (2026-10-21)
**Qaror qabul qiluvchi:** Founder
**Bog'liq:** ADR-028

## Kontekst

Bitta shop katalogi kichik (≤ 5 000 SKU); SKU/model kodi bo'yicha aniq qidiruv muhim.

## Qaror

PostgreSQL full-text search + `pg_trgm`; alohida qidiruv infratuzilmasi (Elasticsearch va h.k.) keyinga qoldiriladi. Qidiruv `CatalogQueryPort.search` orqasida — keyin almashtirish mumkin.

## Ko'rib chiqilgan variantlar

### Elasticsearch hozir
- ❌ Rad etildi: qo'shimcha servis, kichik katalog uchun ortiqcha

## Oqibatlar

### Ijobiy
Qo'shimcha servis yo'q.

### Salbiy
Semantik qidiruv cheklangan.

### Neytral
Stage 3 global qidiruv alohida (`28`).

## Tekshiruv

Qidiruv p95 va aniqlik o'lchovi.

## Qayta ko'rish sharti

p95 yoki katalog hajmi chegarasi tajribada oshsa.

## Havolalar

- Manba: eski `05_ARCHITECTURE_DECISIONS_ADR.md` (v1)
- [../../decisions/DECISION_REGISTER.md](../../decisions/DECISION_REGISTER.md)
