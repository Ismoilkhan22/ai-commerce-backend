# ADR-008: Versiyalangan REST `/api/v1`, tipli OpenAPI klient; WebSocket faqat inbox uchun

**Sana:** 2026-10-21 (v2 formatiga ko'chirildi 2026-10-22)
**Holat:** Accepted (2026-10-21)
**Qaror qabul qiluvchi:** Founder
**Bog'liq:** ADR-024, K-06, K-07

## Kontekst

Frontend va backend alohida repo'larda; kontrakt ikki joyda qo'lda yozilsa tez buziladi.

## Qaror

1. HTTPS REST, `/api/v1` prefiksi, surface bo'yicha guruhlar (ADR-024).
2. OpenAPI'dan frontend `api-client` generatsiya qilinadi, qo'lda yozilmaydi.
3. WebSocket — faqat inbox va jonli bildirishnomalar uchun (qisqa ticket bilan, ADR-023).

## Ko'rib chiqilgan variantlar

### GraphQL birinchi
- ❌ Rad etildi: testlash va keshlash murakkab, ruxsat nazorati qiyin

## Oqibatlar

### Ijobiy
Testlanadigan kontrakt, oddiy kesh.

### Salbiy
Murakkab o'qish sahifalari uchun bir nechta so'rov (BFF yoki `?expand=` bilan hal qilinadi).

### Neytral
Xato formati K-07.

## Tekshiruv

Kontrakt testlari; generatsiya qilingan klient CI'da build bo'ladi.

## Qayta ko'rish sharti

Ko'p murakkab klientlararo o'qish naqshlari paydo bo'lsa.

## Havolalar

- Manba: eski `05_ARCHITECTURE_DECISIONS_ADR.md` (v1)
- [../../decisions/DECISION_REGISTER.md](../../decisions/DECISION_REGISTER.md)
