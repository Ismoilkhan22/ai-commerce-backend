# ADR-009: Ikki repo: backend (ichida infra) va frontend

**Sana:** 2026-10-21 (v2 formatiga ko'chirildi 2026-10-22)
**Holat:** Accepted (2026-10-21)
**Qaror qabul qiluvchi:** Founder
**Bog'liq:** DEC-014, BD-11

## Kontekst

Bitta founder; ko'p repo koordinatsiyasi qimmat.

## Qaror

1. `ai-commerce-backend` — kod, migratsiyalar, `deploy/` (Docker, nginx, backup), hujjatlar.
2. `ai-commerce-frontend` — pnpm workspace, Next.js ilovalari.

## Ko'rib chiqilgan variantlar

### 3+ repo (alohida infra)
- ❌ Rad etildi: koordinatsiya xarajati

## Oqibatlar

### Ijobiy
Kam koordinatsiya.

### Salbiy
Backend repo kattaroq.

### Neytral
Papkalar: ADR-031.

## Tekshiruv

—

## Qayta ko'rish sharti

Alohida DevOps egasi paydo bo'lsa.

## Havolalar

- Manba: eski `05_ARCHITECTURE_DECISIONS_ADR.md` (v1)
- [../../decisions/DECISION_REGISTER.md](../../decisions/DECISION_REGISTER.md)
