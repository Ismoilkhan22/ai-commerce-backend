# ADR-023: Dashboard auth: access JWT xotirada + rotating refresh cookie; WS — qisqa ticket

**Sana:** 2026-10-21 (v2 formatiga ko'chirildi 2026-10-22)
**Holat:** Accepted (2026-10-21)
**Qaror qabul qiluvchi:** Founder
**Bog'liq:** DEC-008

## Kontekst

Xodim tokenini brauzerda qayerda saqlash: localStorage XSS'ga ochiq; cookie-session CSRF va BFF talab qiladi.

## Qaror

1. Access JWT (10–15 daqiqa) — faqat JS xotirasida.
2. Refresh token — rotating, `httpOnly; Secure; SameSite=Strict` cookie; har ishlatilganda almashtiriladi, qayta ishlatilsa butun sessiya bekor.
3. WebSocket — qisqa muddatli bir martalik ticket.
4. Dashboard va API bitta site ostida (`app.<domen>`, `api.<domen>`).

## Ko'rib chiqilgan variantlar

### Cookie-session + BFF CSRF
- ❌ Rad etildi: har yozishga CSRF, Next server auth yo'lida

### localStorage bearer
- ❌ Rad etildi: XSS orqali o'g'irlanadi

## Oqibatlar

### Ijobiy
Uzoq token XSS'dan himoyalangan; API stateless.

### Salbiy
Sahifa yangilanganda silent refresh.

### Neytral
Batafsil `10`.

## Tekshiruv

Refresh rotation va reuse detection testlari (S0-04).

## Qayta ko'rish sharti

Dashboard va API turli site'da bo'lishi kerak bo'lsa.

## Havolalar

- Manba: eski `05_ARCHITECTURE_DECISIONS_ADR.md` (v1)
- [../../decisions/DECISION_REGISTER.md](../../decisions/DECISION_REGISTER.md)
