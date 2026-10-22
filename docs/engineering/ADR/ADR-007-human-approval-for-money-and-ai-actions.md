# ADR-007: Pul va noaniq AI amallari uchun odam tasdig'i

**Sana:** 2026-10-21 (v2 formatiga ko'chirildi 2026-10-22)
**Holat:** Accepted (2026-10-21)
**Qaror qabul qiluvchi:** Founder
**Bog'liq:** DEC-100c, DEC-100d, DEC-102, DEC-108, DEC-110

## Kontekst

AI va avtomatika xato qilishi mumkin; buyurtma, chegirma, taklif va (keyin) to'lovdagi xato pul va obro'ga zarar.

## Qaror

1. AI faqat qoralama yaratadi (buyurtma `DRAFT`, taklif qoralamasi); tasdiqlash — xodim (DEC-100c, 100d).
2. Buyurtmani operator (o'ziniki) yoki menejer tasdiqlaydi (DEC-108); bekor qilish — menejer/ega.
3. PC taklifi pilotda har doim menejer tasdig'idan o'tadi (DEC-102); chegirma limitlari (DEC-110).
4. To'lov moduli qaytganda moliyaviy tasdiqlar ham shu tamoyil bilan.

## Ko'rib chiqilgan variantlar

### AI avtonom buyurtma/to'lov amallari
- ❌ Rad etildi: moliyaviy va obro' xavfi

## Oqibatlar

### Ijobiy
Xatolar odam filtridan o'tadi.

### Salbiy
Operator yuklamasi; javob tezligi biroz past.

### Neytral
Tasdiqlash qoidalari `business/04` da.

## Tekshiruv

TC-028, TC-029; UAT-M12, UAT-M13.

## Qayta ko'rish sharti

Ko'p bosqichli tasdiqlash jarayoni sinalib, xatolar o'lchab past bo'lsa.

## Havolalar

- Manba: eski `05_ARCHITECTURE_DECISIONS_ADR.md` (v1)
- [../../decisions/DECISION_REGISTER.md](../../decisions/DECISION_REGISTER.md)
