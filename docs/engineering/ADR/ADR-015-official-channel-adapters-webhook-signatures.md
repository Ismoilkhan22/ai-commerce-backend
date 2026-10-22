# ADR-015: Rasmiy kanal adapterlari, webhook imzosi, kanal imkoniyatlari registri

**Sana:** 2026-10-21 (v2 formatiga ko'chirildi 2026-10-22)
**Holat:** Accepted (2026-10-21)
**Qaror qabul qiluvchi:** Founder
**Bog'liq:** DEC-116, BD-09

## Kontekst

Norasmiy brauzer botlari platforma qoidalarini buzadi va ishonchsiz.

## Qaror

1. Faqat rasmiy API: Telegram Bot API, Meta (Instagram Messaging), o'z sayt chati.
2. Har webhook imzosi va yangiligi tekshiriladi; `(provider, channel_account_id, event_id)` bo'yicha takror tekshiruvi.
3. Kanal imkoniyatlari registri (qaysi xabar turlari, cheklovlar) — `13-integrations-and-channels.md`.

## Ko'rib chiqilgan variantlar

### Norasmiy brauzer botlari
- ❌ Rad etildi: qoidabuzarlik, bloklanish

## Oqibatlar

### Ijobiy
Barqarorlik, qonuniylik.

### Salbiy
Meta ruxsati kutilishi (DEC-116a).

### Neytral
Kanal tokenlari secret store'da.

## Tekshiruv

TC-010, TC-011.

## Qayta ko'rish sharti

Provayder qoidalari o'zgarsa.

## Havolalar

- Manba: eski `05_ARCHITECTURE_DECISIONS_ADR.md` (v1)
- [../../decisions/DECISION_REGISTER.md](../../decisions/DECISION_REGISTER.md)
