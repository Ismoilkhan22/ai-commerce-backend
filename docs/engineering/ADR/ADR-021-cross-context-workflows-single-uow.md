# ADR-021: Kontekstlararo sinxron yozuv `workflows/` orqali bitta UoW'da

**Sana:** 2026-10-21 (v2 formatiga ko'chirildi 2026-10-22)
**Holat:** Superseded by ADR-032 (2026-10-22)
**Qaror qabul qiluvchi:** Founder
**Bog'liq:** DEC-126, ADR-032

## Kontekst

Buyurtma tasdiqlash (`orders`) va qoldiqni band qilish (`inventory`) alohida kontekstlarda edi, lekin atomik bo'lishi kerak edi.

## Qaror

(Tarixiy) Kontekstlararo sinxron yozuvlar faqat `workflows/` dagi nomlangan use case orqali, bitta UoW ichida.

**2026-10-22:** almashtirildi — ombor, buyurtma, lead va taklif bitta `commerce` domenida; domenlar orasida faqat event va Query Port (ADR-032). Sabab: bismuth v2 qoidasiga istisno qilmaslik.

## Ko'rib chiqilgan variantlar

### Context A ning context B jadvaliga to'g'ridan-to'g'ri yozishi
- ❌ Rad etildi: egalik buziladi

### Event zanjiri (saga)
- ❌ Rad etildi: TC-002/027 buziladi

## Oqibatlar

### Ijobiy
Atomik invariant.

### Salbiy
Bismuth qoidasiga istisno, istisnolar ko'payishi xavfi.

### Neytral
—

## Tekshiruv

—

## Qayta ko'rish sharti

—

## Havolalar

- Manba: eski `05_ARCHITECTURE_DECISIONS_ADR.md` (v1)
- [../../decisions/DECISION_REGISTER.md](../../decisions/DECISION_REGISTER.md)
