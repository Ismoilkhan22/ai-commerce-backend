# ADR-025: Pul: `amount_minor BIGINT` + ISO 4217 exponent; USD narx + kurs snapshot

**Sana:** 2026-10-21 (v2 formatiga ko'chirildi 2026-10-22)
**Holat:** Accepted (2026-10-21)
**Qaror qabul qiluvchi:** Founder
**Bog'liq:** DEC-007, DEC-121, K-04

## Kontekst

Float bilan pul hisoblash yaxlitlash xatolariga olib keladi; shoplar narxni dollarda yuritadi, xaridor so'mda to'laydi.

## Qaror

1. Pul — `*_minor BIGINT` + `currency CHAR(3)`; exponent `currencies` jadvalidan (UZS = 2, 10 mln so'm = `1000000000`).
2. USD narx + kurs snapshot (manba, vaqt) — taklif va buyurtmada saqlanadi (DEC-121).
3. UI butun so'mga yaxlitlaydi; float TAQIQ.

## Ko'rib chiqilgan variantlar

### Butun so'm
- ❌ Rad etildi: USD/kurs uchun alohida mantiq

### Float
- ❌ Rad etildi: yaxlitlash xatolari

## Oqibatlar

### Ijobiy
Standart, aniq.

### Salbiy
Raqamlar 100x katta.

### Neytral
`shared/money.py`.

## Tekshiruv

Pul arifmetikasi unit testlari; kurs snapshot testi.

## Qayta ko'rish sharti

—

## Havolalar

- Manba: eski `05_ARCHITECTURE_DECISIONS_ADR.md` (v1)
- [../../decisions/DECISION_REGISTER.md](../../decisions/DECISION_REGISTER.md)
