# ADR-030: Hosting: production PII ma'lumotlari O'zbekistonda

**Sana:** 2026-10-21 (v2 formatiga ko'chirildi 2026-10-22)
**Holat:** Accepted (2026-10-21) — huquqshunos xulosasi sharti bilan
**Qaror qabul qiluvchi:** Founder
**Bog'liq:** DEC-013, DEC-016

## Kontekst

Shaxsiy ma'lumotlarni lokalizatsiya qilish talabi bo'lishi mumkin; xorijiy cloud arzon va qulay, lekin xavfli.

## Qaror

1. Production PII DB va storage — O'zbekistondagi serverda (VM, Docker Compose).
2. LLM'ga faqat tozalangan matn (DEC-016).
3. Haqiqiy PII — huquqshunos xulosasidan keyin; dev/staging — sintetik ma'lumot.

## Ko'rib chiqilgan variantlar

### Xorijiy cloud
- ❌ Rad etildi: lokalizatsiya talabini buzishi mumkin

### Gibrid
- ❌ Rad etildi: murakkab

## Oqibatlar

### Ijobiy
Lokalizatsiyaga mos, past kechikish.

### Salbiy
Managed servislar kam; backup'ni o'zimiz sozlaymiz.

### Neytral
Telemetriya PII'siz xorijda (ADR-029).

## Tekshiruv

Backup va tiklash mashqi; PII oqimi xaritasi (`26`).

## Qayta ko'rish sharti

Huquqiy xulosa boshqacha bo'lsa.

## Havolalar

- Manba: eski `05_ARCHITECTURE_DECISIONS_ADR.md` (v1)
- [../../decisions/DECISION_REGISTER.md](../../decisions/DECISION_REGISTER.md)
