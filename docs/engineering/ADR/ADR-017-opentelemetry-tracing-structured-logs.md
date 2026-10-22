# ADR-017: OpenTelemetry (W3C traceparent), request ID, strukturali loglar

**Sana:** 2026-10-21 (v2 formatiga ko'chirildi 2026-10-22)
**Holat:** Accepted (2026-10-21) — vositalar ADR-029 da
**Qaror qabul qiluvchi:** Founder
**Bog'liq:** ADR-029, DEC-012

## Kontekst

Async zanjir (HTTP → outbox → worker → Telegram) bog'lanmagan loglar bilan debug qilib bo'lmaydi.

## Qaror

1. W3C `traceparent`, `X-Request-ID`; structlog JSON (contextvars: `trace_id`, `shop_id`, `actor_id`).
2. Trace outbox → arq → task orqali davom etadi.
3. Metrikalar va alertlar; xatolar Sentry'ga (ADR-029).

## Ko'rib chiqilgan variantlar

### Bog'lanmagan print/loglar
- ❌ Rad etildi: incident'larni tahlil qilib bo'lmaydi

## Oqibatlar

### Ijobiy
Async zanjirni kuzatish mumkin.

### Salbiy
Telemetriya xarajati.

### Neytral
PII telemetriyaga yozilmaydi.

## Tekshiruv

API → job trace korrelyatsiyasi testi (S0-05).

## Qayta ko'rish sharti

Tracing saqlash xarajati byudjetdan oshsa.

## Havolalar

- Manba: eski `05_ARCHITECTURE_DECISIONS_ADR.md` (v1)
- [../../decisions/DECISION_REGISTER.md](../../decisions/DECISION_REGISTER.md)
