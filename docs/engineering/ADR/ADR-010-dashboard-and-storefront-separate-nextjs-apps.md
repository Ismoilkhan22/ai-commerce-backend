# ADR-010: Dashboard va shop sayti — bitta workspace'da alohida Next.js ilovalari

**Sana:** 2026-10-21 (v2 formatiga ko'chirildi 2026-10-22)
**Holat:** Accepted (2026-10-21)
**Qaror qabul qiluvchi:** Founder
**Bog'liq:** DEC-014, DEC-115

## Kontekst

Shop sayti ommaviy va SEO talab qiladi; dashboard yopiq va auth talab qiladi. Bitta katta ilova ikkalasini aralashtiradi.

## Qaror

1. `apps/shop-dashboard` (`app.<platforma>.uz`) va `apps/shop-storefront` (`<shop>.<platforma>.uz`) — alohida deploy.
2. Umumiy `packages/{ui, i18n, auth, api-client}`.

## Ko'rib chiqilgan variantlar

### Bitta katta Next.js
- ❌ Rad etildi: SEO va xususiy auth aralashadi

## Oqibatlar

### Ijobiy
Mustaqil domenlar, xavfsizlik chegarasi aniq.

### Salbiy
Umumiy UI takrorlanishi.

### Neytral
Frontend tafsilotlari `21-frontend.md`.

## Tekshiruv

—

## Qayta ko'rish sharti

Takrorlanish xarajati katta bo'lsa.

## Havolalar

- Manba: eski `05_ARCHITECTURE_DECISIONS_ADR.md` (v1)
- [../../decisions/DECISION_REGISTER.md](../../decisions/DECISION_REGISTER.md)
