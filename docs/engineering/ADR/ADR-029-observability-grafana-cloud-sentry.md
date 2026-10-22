# ADR-029: Observability: OpenTelemetry + JSON loglar → Grafana Cloud; xatolar → Sentry

**Sana:** 2026-10-21 (v2 formatiga ko'chirildi 2026-10-22)
**Holat:** Accepted (2026-10-22, bismuth v2 bilan solishtirilib qayta tasdiqlandi)
**Qaror qabul qiluvchi:** Founder
**Bog'liq:** DEC-012 B, ADR-017

## Kontekst

Bitta odam self-hosted Prometheus/Grafana/Tempo/Loki stack'ini yuritishi og'ir. Bismuth v2 self-hosted ishlatadi, lekin kod darajasidagi qoidalar bir xil (OTel, structlog).

## Qaror

1. Kodda: OpenTelemetry SDK, structlog JSON, metrika nomlari `cos_<domain>_<entity>_<action>_total` (bismuth uslubi).
2. Eksport: Grafana Cloud (trace, metrika, log); xatolar — Sentry.
3. PII telemetriyaga yozilmaydi (redaction filtrlari majburiy).
4. `deploy/` da self-hosted monitoring yo'q.

## Ko'rib chiqilgan variantlar

### Self-hosted (bismuth): OTel Collector + Prometheus + Grafana + Tempo + Loki
- ❌ Rad etildi: 4–5 servisni yuritish

### Faqat Sentry + loglar
- ❌ Rad etildi: async zanjir, metrika, alert yo'q

## Oqibatlar

### Ijobiy
Boshqarish kerak emas, kichik hajmda arzon.

### Salbiy
Telemetriya xorijda (PII'siz); hajm oshsa narx oshadi.

### Neytral
OTel tufayli kodni o'zgartirmasdan self-hosted'ga o'tish mumkin.

## Tekshiruv

Log va trace'da PII yo'qligini tekshiruvchi test; alert sinovi.

## Qayta ko'rish sharti

Narx yoki data residency talabi o'zgarsa — self-hosted.

## Havolalar

- Manba: eski `05_ARCHITECTURE_DECISIONS_ADR.md` (v1)
- [../../decisions/DECISION_REGISTER.md](../../decisions/DECISION_REGISTER.md)
