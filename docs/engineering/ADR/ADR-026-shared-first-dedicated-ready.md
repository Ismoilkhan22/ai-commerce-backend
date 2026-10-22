# ADR-026: Shared-first, dedicated-ready deployment

**Sana:** 2026-10-21 (v2 formatiga ko'chirildi 2026-10-22)
**Holat:** Accepted (2026-10-21)
**Qaror qabul qiluvchi:** Founder
**Bog'liq:** DEC-001 C, DEC-002 B, ADR-002, ADR-003, ADR-035

## Kontekst

Ko'pchilik shoplar umumiy tizimda ishlaydi; katta mijoz alohida o'rnatish so'rashi mumkin. Keyin kodni qayta yozmaslik kerak.

## Qaror

1. Standart — umumiy (shared) o'rnatish: app-layer shop doirasi + composite FK; RLS S0 spike'dan keyin sezgir jadvallarga.
2. Dedicated rejim — butun stack nusxasi konfiguratsiya orqali (alohida DB va secret'lar); kodda shop soniga bog'liq global holat taqiqlangan.
3. Batafsil `10-security-tenancy-rbac.md`.

## Ko'rib chiqilgan variantlar

### DB-per-tenant
- ❌ Rad etildi: N ta deploy bitta odamga og'ir

### Darhol to'liq RLS
- ❌ Rad etildi: sinovsiz

## Oqibatlar

### Ijobiy
Hozir arzon va oddiy, keyin qayta yozish yo'q.

### Salbiy
Konfiguratsiya intizomi kerak.

### Neytral
Enterprise tarif bilan bog'liq.

## Tekshiruv

TC-ISO; dedicated rejimda smoke test.

## Qayta ko'rish sharti

RLS spike yiqilsa yoki Enterprise talab paydo bo'lsa.

## Havolalar

- Manba: eski `05_ARCHITECTURE_DECISIONS_ADR.md` (v1)
- [../../decisions/DECISION_REGISTER.md](../../decisions/DECISION_REGISTER.md)
