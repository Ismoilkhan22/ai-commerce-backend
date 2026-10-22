# ADR-022: Repo skeleti `src/commerce_os/modules/<context>/...`

**Sana:** 2026-10-21 (v2 formatiga ko'chirildi 2026-10-22)
**Holat:** Superseded by ADR-031 (2026-10-22)
**Qaror qabul qiluvchi:** Founder
**Bog'liq:** DEC-004 (A → C), ADR-031

## Kontekst

Backend kodi uchun papka tuzilmasi va import qoidalari kerak edi.

## Qaror

(Tarixiy) `src/commerce_os/` + `modules/<context>/{domain,application,infrastructure,presentation}` + `workflows/` + `workers/` + `api/v1/` + `bootstrap/`.

**2026-10-22:** almashtirildi — bismuth v2: `app/shared` ← `app/platform` ← `app/domains` (ADR-031).

## Ko'rib chiqilgan variantlar

### `app/contexts` + `entrypoints/`
- ❌ Rad etildi: kontekstlararo jarayonlar uchun joy yo'q

## Oqibatlar

### Ijobiy
src-layout standarti.

### Salbiy
Bismuth'dan farq qiladi.

### Neytral
—

## Tekshiruv

—

## Qayta ko'rish sharti

—

## Havolalar

- Manba: eski `05_ARCHITECTURE_DECISIONS_ADR.md` (v1)
- [../../decisions/DECISION_REGISTER.md](../../decisions/DECISION_REGISTER.md)
