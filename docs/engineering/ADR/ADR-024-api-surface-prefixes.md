# ADR-024: API surface prefikslari

**Sana:** 2026-10-21 (v2 formatiga ko'chirildi 2026-10-22)
**Holat:** Accepted (2026-10-21) — `merchant` → `shop` (DEC-124, 2026-10-22)
**Qaror qabul qiluvchi:** Founder
**Bog'liq:** DEC-006, DEC-124, ADR-031

## Kontekst

Bitta tekis `/api/v1/*` da xodim, ommaviy sayt, webhook va platforma endpoint'lari aralashsa, xususiy endpoint tasodifan ommaviy guruhga tushishi mumkin.

## Qaror

| Prefiks | Kim | Auth |
|---|---|---|
| `/api/v1/shop/*` | Shop xodimlari | JWT + ruxsat |
| `/api/v1/storefront/{slug}/*` | Sayt xaridori | Anonim / signed sessiya |
| `/api/v1/webhooks/*` | Telegram, Meta | Imzo |
| `/api/v1/platform/*` | Platforma jamoasi | JWT + platform roli + audit |
| `/api/v1/public/*` | Stage 3 | — |

Har surface o'z auth va rate limit middleware'iga ega. URL'da domen nomi yo'q; domen `DomainManifest.routers` da qaysi surface'ga router berishini e'lon qiladi (ADR-031).

## Ko'rib chiqilgan variantlar

### Tekis `/api/v1/orders`
- ❌ Rad etildi: auth turi har endpoint'da alohida, aralash

## Oqibatlar

### Ijobiy
Har guruhga o'z himoyasi.

### Salbiy
Manzillar uzunroq.

### Neytral
Batafsil `11`.

## Tekshiruv

Har surface uchun auth testlari.

## Qayta ko'rish sharti

—

## Havolalar

- Manba: eski `05_ARCHITECTURE_DECISIONS_ADR.md` (v1)
- [../../decisions/DECISION_REGISTER.md](../../decisions/DECISION_REGISTER.md)
