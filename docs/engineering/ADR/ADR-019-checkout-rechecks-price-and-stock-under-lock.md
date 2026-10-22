# ADR-019: Buyurtma tasdiqlashda narx va qoldiq lock ostida qayta tekshiriladi

**Sana:** 2026-10-21 (v2 formatiga ko'chirildi 2026-10-22)
**Holat:** Accepted (2026-10-21)
**Qaror qabul qiluvchi:** Founder
**Bog'liq:** ADR-032, TC-002, TC-027, TC-031

## Kontekst

Qidiruv, kesh va taklif ichidagi narx/qoldiq eskirgan bo'lishi mumkin; ularga ishonish ortiqcha sotish va noto'g'ri narxga olib keladi.

## Qaror

1. Tasdiqlashda narx va qoldiq DB'dan, `FOR UPDATE` lock ostida qayta o'qiladi (`commerce` ichida, ADR-032).
2. Narx o'zgargan bo'lsa — `409 PRICE_CHANGED`, xaridordan qayta rozilik (TC-031).
3. Kesh va Query Port natijalari hech qachon tasdiqlash uchun manba emas.

## Ko'rib chiqilgan variantlar

### Qidiruv yoki kesh natijasiga ishonish
- ❌ Rad etildi: eskirgan taklif, ortiqcha sotish

## Oqibatlar

### Ijobiy
Ikki marta sotish va noto'g'ri narx yo'q.

### Salbiy
Tasdiqlash biroz sekinroq.

### Neytral
Lock tartibi `12`.

## Tekshiruv

TC-002, TC-027, TC-031.

## Qayta ko'rish sharti

Hech qachon yumshatilmaydi.

## Havolalar

- Manba: eski `05_ARCHITECTURE_DECISIONS_ADR.md` (v1)
- [../../decisions/DECISION_REGISTER.md](../../decisions/DECISION_REGISTER.md)
