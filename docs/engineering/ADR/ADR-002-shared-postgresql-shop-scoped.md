# ADR-002: Umumiy PostgreSQL, har qatorda `shop_id`

**Sana:** 2026-10-21 (v2 formatiga ko'chirildi 2026-10-22)
**Holat:** Accepted (2026-10-21) — ADR-035 (schema per domain) bilan to'ldirildi
**Qaror qabul qiluvchi:** Founder
**Bog'liq:** DEC-001, DEC-002, ADR-003, ADR-026, ADR-035, K-01

## Kontekst

Barcha shoplar bitta tizimda ishlaydi (shared-first, DEC-001 C). Har shopga alohida DB pilot bosqichida qimmat va migratsiyalarni murakkablashtiradi.

## Qaror

1. Bitta PostgreSQL klasteri; har shop jadvalida `shop_id UUID NOT NULL` (ilgari `merchant_id`, DEC-124).
2. `shop_id` hech qachon klient so'rovidan olinmaydi — autentifikatsiya va a'zolikdan (`ActorContext`).
3. Unikal cheklovlar shop doirasida: `UNIQUE (shop_id, sku_code)`; shop ichidagi bog'lanishlar composite FK bilan.
4. **2026-10-22:** jadvallar domen bo'yicha alohida schemalarda (ADR-035); `shop_id` hamma schemalarda, cross-schema FK yo'q.

## Ko'rib chiqilgan variantlar

### Har shopga alohida DB
- ❌ Rad etildi: N ta migratsiya, backup, monitoring; tranzaksiyalar murakkab

### Har shopga alohida schema
- ❌ Rad etildi: ADR-035 bilan aralashadi, shop soni oshganda boshqarib bo'lmaydi

## Oqibatlar

### Ijobiy
Oddiy migratsiya va tranzaksiyalar, arzon.

### Salbiy
Bitta xato filtr — ma'lumot sizishi xavfi; shuning uchun RLS (ADR-003) va TC-ISO testlari.

### Neytral
Dedicated rejim — butun stack nusxasi (ADR-026), alohida DB emas.

## Tekshiruv

TC-ISO-01…10: A/B shop matritsasi har endpoint, worker va AI tool uchun.

## Qayta ko'rish sharti

Muvofiqlik (compliance) yoki yirik mijoz izolyatsiya shartnomasi talab qilsa — dedicated rejim.

## Havolalar

- Manba: eski `05_ARCHITECTURE_DECISIONS_ADR.md` (v1)
- [../../decisions/DECISION_REGISTER.md](../../decisions/DECISION_REGISTER.md)
