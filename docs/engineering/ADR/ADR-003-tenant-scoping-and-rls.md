# ADR-003: Shop doirasini cheklash: middleware + UoW, sezgir jadvallarda RLS

**Sana:** 2026-10-21 (v2 formatiga ko'chirildi 2026-10-22)
**Holat:** Accepted (2026-10-21) — RLS S0 spike natijasiga bog'liq (DEC-002 B)
**Qaror qabul qiluvchi:** Founder
**Bog'liq:** DEC-002, ADR-002, ADR-026, TC-001, TC-ISO

## Kontekst

Async connection pool'da bir so'rovning shop konteksti boshqa so'rovga o'tib qolishi mumkin. Faqat kod filtriga tayanish — bitta xato bilan ma'lumot sizishi.

## Qaror

1. Har so'rovda server `ActorContext` (principal, `shop_id`, rollar, filiallar) yaratadi.
2. Har tranzaksiya boshida `set_config('app.shop_id', <id>, true)` (tranzaksiya oxirida o'zi tozalanadi).
3. Sezgir jadvallarda (orders, conversations, messages, leads, stock va h.k.) `ENABLE` + `FORCE ROW LEVEL SECURITY`, siyosat `shop_id = current_setting('app.shop_id')::uuid`.
4. Runtime DB roli `app_runtime` — `NOBYPASSRLS`; migratsiyalar `app_migrator` bilan.
5. RLS S0 da spike sifatida sinaladi; o'tsa — S0 oxirida yoqiladi. Tasdiqlanmaguncha shoplararo umumiy admin endpoint'lar taqiqlangan.

## Ko'rib chiqilgan variantlar

### Faqat klientdan kelgan `shop_id`
- ❌ Rad etildi: rad etildi — ishonchsiz

### Faqat app-layer filtr
- ❌ Rad etildi: bitta xato = sizish

### Darhol barcha jadvallarga RLS
- ❌ Rad etildi: sinovsiz, S0 ni sekinlashtiradi

## Oqibatlar

### Ijobiy
Ikki qavat himoya: kod filtri + DB siyosati.

### Salbiy
S0 ga 1–2 kun qo'shiladi; pool bilan to'g'ri ishlashi sinalishi shart.

### Neytral
Platforma admin endpoint'lari alohida rol va audit bilan.

## Tekshiruv

Connection reuse regression testi; TC-ISO; rollback'dan keyin kontekst tozaligi.

## Qayta ko'rish sharti

Spike yiqilsa yoki murakkablik o'lchab haddan oshsa — faqat app-layer + qo'shimcha testlar.

## Havolalar

- Manba: eski `05_ARCHITECTURE_DECISIONS_ADR.md` (v1)
- [../../decisions/DECISION_REGISTER.md](../../decisions/DECISION_REGISTER.md)
