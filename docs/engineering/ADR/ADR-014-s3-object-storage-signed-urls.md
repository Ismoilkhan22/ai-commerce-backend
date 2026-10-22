# ADR-014: Media uchun S3-compatible storage, signed URL

**Sana:** 2026-10-21 (v2 formatiga ko'chirildi 2026-10-22)
**Holat:** Accepted (2026-10-21)
**Qaror qabul qiluvchi:** Founder
**Bog'liq:** ADR-030, DEC-013

## Kontekst

Rasm, import fayli va audio DB'da saqlansa baza tez o'sadi va backup og'irlashadi.

## Qaror

1. S3-compatible storage (MinIO, O'zbekistondagi serverda — DEC-013).
2. O'qish — qisqa muddatli signed URL; yozish — server tekshiruvidan keyin.
3. Kalitlarda shop prefiksi.

## Ko'rib chiqilgan variantlar

### DB blob
- ❌ Rad etildi: baza o'sishi

## Oqibatlar

### Ijobiy
DB kichik qoladi.

### Salbiy
Yana bitta servis.

### Neytral
Saqlash muddatlari `26`.

## Tekshiruv

Boshqa shop fayliga signed URL olib bo'lmasligi (TC-ISO).

## Qayta ko'rish sharti

Sezgir kontent saqlash talablari o'zgarsa.

## Havolalar

- Manba: eski `05_ARCHITECTURE_DECISIONS_ADR.md` (v1)
- [../../decisions/DECISION_REGISTER.md](../../decisions/DECISION_REGISTER.md)
