# ADR-018: Stage 2 ommaviy taklif — shop roziligi bilan alohida proyeksiya

**Sana:** 2026-10-21 (v2 formatiga ko'chirildi 2026-10-22)
**Holat:** Accepted (2026-10-21)
**Qaror qabul qiluvchi:** Founder
**Bog'liq:** BD-04, FSM-14, TC-015

## Kontekst

Shop xususiy SKU, narx va qoldig'ini global qidiruvga to'g'ridan-to'g'ri ochib qo'yish maxfiylikni buzadi va rozilikni qaytarib olishni qiyinlashtiradi.

## Qaror

1. Ommaviy taklif — `network` domenidagi alohida proyeksiya, faqat shop roziligi va maydonlar allowlist bilan.
2. Rozilik qaytarib olinsa — o'sha tranzaksiyada `denied`, o'qishda tekshiriladi (indeks kechikishi qayta ochib qo'ymaydi).
3. Tannarx, xaridorlar, ichki eslatmalar hech qachon proyeksiyaga tushmaydi.

## Ko'rib chiqilgan variantlar

### Shop DB'sini global qidiruvga ochish
- ❌ Rad etildi: maxfiylik, qaytarib olish imkonsiz

## Oqibatlar

### Ijobiy
Maxfiylik, darhol qaytarib olish.

### Salbiy
Proyeksiya va indeks sinxronizatsiyasi.

### Neytral
Batafsil `28`.

## Tekshiruv

TC-015.

## Qayta ko'rish sharti

Hech qachon yumshatilmaydi.

## Havolalar

- Manba: eski `05_ARCHITECTURE_DECISIONS_ADR.md` (v1)
- [../../decisions/DECISION_REGISTER.md](../../decisions/DECISION_REGISTER.md)
