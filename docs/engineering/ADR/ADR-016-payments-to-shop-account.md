# ADR-016: To'lov shop hisobiga, tasdiqlangan callback yoki vakolatli moliya tasdig'i

**Sana:** 2026-10-21 (v2 formatiga ko'chirildi 2026-10-22)
**Holat:** Accepted (2026-10-21), Stage 1 da DEFERRED (DEC-100)
**Qaror qabul qiluvchi:** Founder
**Bog'liq:** DEC-100, DEC-111, TC-004, TC-005, TC-006, TC-021

## Kontekst

Platforma pulni o'zida saqlasa — litsenziya va regulyatsiya. Chek rasmi soxta bo'lishi mumkin.

## Qaror

**Stage 1:** to'lov tizimdan tashqarida, shop o'zi oladi; faqat ixtiyoriy tekshirilmagan "to'landi" belgisi (DEC-100a).

**To'lov moduli qaytganda:**
1. Shop — merchant-of-record; soliq/fiskal majburiyatlar ishga tushirishdan oldin tekshiriladi.
2. Tizim faqat to'lov niyatini yaratadi va tasdiqlangan hisob-kitobni aks ettiradi; karta raqamlari platformaga kelmaydi.
3. Chek rasmidan avtomatik tasdiq yo'q.
4. Provayder callback imzosi + server-to-server tekshiruv; `UNIQUE (shop_id, provider, external_transaction_id)`.

## Ko'rib chiqilgan variantlar

### Platforma pulni saqlashi (custody)
- ❌ Rad etildi: regulyatsiya

## Oqibatlar

### Ijobiy
Pul oqimi regulyatsiyasi kam.

### Salbiy
Stage 1 da to'lov holati tizimda ishonchli emas.

### Neytral
`payments` domeni keyinroq; atomiklik masalasi ADR-032 neytral bandida.

## Tekshiruv

TC-004/005/006/021 — to'lov moduli bilan.

## Qayta ko'rish sharti

Marketplace bo'linadigan to'lovlar kerak bo'lsa.

## Havolalar

- Manba: eski `05_ARCHITECTURE_DECISIONS_ADR.md` (v1)
- [../../decisions/DECISION_REGISTER.md](../../decisions/DECISION_REGISTER.md)
