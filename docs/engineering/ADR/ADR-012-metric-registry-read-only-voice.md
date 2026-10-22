# ADR-012: SQL asosidagi tasdiqlangan metrika registri; ovoz faqat o'qish

**Sana:** 2026-10-21 (v2 formatiga ko'chirildi 2026-10-22)
**Holat:** Accepted (2026-10-21)
**Qaror qabul qiluvchi:** Founder
**Bog'liq:** DEC-010, DEC-112

## Kontekst

Hisobot yordamchisi LLM'ga erkin SQL yozdirsa — ruxsat va aniqlik nazoratsiz; ovozda raqamlar noto'g'ri tushunilishi mumkin.

## Qaror

1. Hisobotlar faqat registrdagi metrikalardan (`19-reporting-metrics.md`); LLM faqat metrika va filtrni tanlaydi.
2. Ovoz: STT → niyat → metrika → javob (TTS ixtiyoriy); faqat o'qish, hech narsa yozilmaydi.
3. Javob foydalanuvchi ruxsati doirasida (operator tannarxni ko'rmaydi).

## Ko'rib chiqilgan variantlar

### LLM erkin SQL
- ❌ Rad etildi: ruxsat va aniqlik nazoratsiz

## Oqibatlar

### Ijobiy
Raqamlar bir xil va tekshiriladigan.

### Salbiy
Yangi savol turi uchun metrika qo'shish kerak.

### Neytral
Ovoz — beta (DEC-112).

## Tekshiruv

TC-012, TC-013, TC-014.

## Qayta ko'rish sharti

Ovoz eval yozish amallari uchun sinovdan o'tsa.

## Havolalar

- Manba: eski `05_ARCHITECTURE_DECISIONS_ADR.md` (v1)
- [../../decisions/DECISION_REGISTER.md](../../decisions/DECISION_REGISTER.md)
