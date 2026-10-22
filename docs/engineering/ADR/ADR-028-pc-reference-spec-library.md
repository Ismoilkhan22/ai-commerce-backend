# ADR-028: PC moslik ma'lumoti — platforma yuritadigan texnik ma'lumotlar kutubxonasi

**Sana:** 2026-10-21 (v2 formatiga ko'chirildi 2026-10-22)
**Holat:** Accepted (2026-10-21)
**Qaror qabul qiluvchi:** Founder
**Bog'liq:** DEC-011 B, DEC-120, K-09

## Kontekst

Moslik engine uchun socket, RAM turi, GPU uzunligi, quvvat kabi ma'lumot kerak; shop Excel'ida odatda yo'q.

## Qaror

1. Platforma `reference_hardware_spec` kutubxonasini yuritadi (CPU, MB, GPU, PSU, korpus, sovutgich, RAM — eng ko'p sotiladigan bir necha yuz model, manba va versiya bilan).
2. Shop SKU'si kutubxonaga bog'lanadi (MPN/model bo'yicha avtomatik, keyin tasdiqlash).
3. Bog'lanmagan qism → `REVIEW_REQUIRED`, hech qachon `PASS` emas.
4. `catalog` domeni: `pc_specs`, `compatibility` sub-modullari (`17`).

## Ko'rib chiqilgan variantlar

### Shop har SKU uchun kiritadi
- ❌ Rad etildi: kiritmaydi yoki xato kiritadi

### To'liq global katalog Stage 1 da
- ❌ Rad etildi: Stage 1 juda kattalashadi

## Oqibatlar

### Ijobiy
Ishonchli spec, shopga ish kam; Stage 2 umumiy katalogga tabiiy o'tish.

### Salbiy
Kutubxonani yuritish xarajati (DEC-120).

### Neytral
Qoidalar versiyalangan.

## Tekshiruv

TC-008; moslik golden set.

## Qayta ko'rish sharti

Kutubxonani yuritish xarajati juda katta bo'lsa.

## Havolalar

- Manba: eski `05_ARCHITECTURE_DECISIONS_ADR.md` (v1)
- [../../decisions/DECISION_REGISTER.md](../../decisions/DECISION_REGISTER.md)
