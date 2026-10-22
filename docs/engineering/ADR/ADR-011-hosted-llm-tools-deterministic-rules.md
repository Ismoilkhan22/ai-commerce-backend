# ADR-011: Hosted LLM provayder adapter orqali; narx/qoldiq/PC — aniq qoidalar

**Sana:** 2026-10-21 (v2 formatiga ko'chirildi 2026-10-22)
**Holat:** Accepted (2026-10-21)
**Qaror qabul qiluvchi:** Founder
**Bog'liq:** ADR-027, DEC-009, BD-06

## Kontekst

O'z modelini o'qitish qimmat va sekin; LLM esa narx yoki moslikni o'ylab topishi mumkin.

## Qaror

1. Hosted LLM, `LLMPort` adapter orqali (ADR-027).
2. Ma'lumot — tool'lar va RAG orqali; narx, qoldiq, PC moslik — deterministik kod (catalog/commerce domenlari).
3. Fine-tune faqat eval aniq ROI ko'rsatsa.

## Ko'rib chiqilgan variantlar

### O'z foundation modelini o'qitish
- ❌ Rad etildi: vaqt va xarajat

## Oqibatlar

### Ijobiy
Tez bozorga chiqish, xavfsizlik.

### Salbiy
Provayderga bog'liqlik, xarajat.

### Neytral
Provayder bake-off bilan tanlanadi.

## Tekshiruv

AI eval golden set (`16`).

## Qayta ko'rish sharti

Eval aniq fine-tune foydasini ko'rsatsa.

## Havolalar

- Manba: eski `05_ARCHITECTURE_DECISIONS_ADR.md` (v1)
- [../../decisions/DECISION_REGISTER.md](../../decisions/DECISION_REGISTER.md)
