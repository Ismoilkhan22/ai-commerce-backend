# ADR-031: Uch qatlamli papka tuzilmasi (bismuth v2)

**Sana:** 2026-10-22
**Holat:** Accepted — ADR-022 ni almashtiradi (Superseded: ADR-022)
**Qaror qabul qiluvchi:** Founder
**Bog'liq:** DEC-004 C, DEC-125, ADR-032, ADR-035

## Kontekst

DEC-004 A da `src/commerce_os/modules/<context>/{domain,application,infrastructure,presentation}` + `workflows/` tanlangan edi. Founder'ning boshqa loyihasi (`bismuth_platform_v2`) boshqa tuzilmada: `app/shared` → `app/platform` → `app/domains`, qoidalar CI'da import-linter bilan tekshiriladi. Ikki loyihada ikki xil uslub — kontekst almashtirishda xato va sekinlik; AI yordamchiga ikki xil qoida tushuntirish kerak.

## Qaror

1. Kod `app/` ostida uch qatlamda:
   - `app/shared/` — poydevor (db, events, contracts, errors, i18n, tracing, cache, idempotency, money, types). **Hech kimni import qilmaydi.**
   - `app/platform/` — domenlararo xizmatlar: `auth`, `shops`, `staff`, `use`, `audit`, `notifications`, `storage`, `realtime`, `llm`, `billing`, `privacy`. **`domains` ni import qilmaydi.**
   - `app/domains/` — biznes domenlari: `catalog`, `commerce`, `messaging`, `sales_ai`, `storefront`, `support`, `reporting`. **Bir-birini import qilmaydi.**
2. Har domen sub-modullarga bo'linadi; har sub-modul: `api/`, `services/`, `repository/`, `models/`, `state_machine.py`, `tests/`.
3. Har domen `DomainManifest` e'lon qiladi (schema, surface router'lari, state rule'lar, subscriber'lar, rejali ishlar, ruxsatlar); `main.py` ularni avtomatik ulaydi.
4. `app/dependencies.py` va `app/workers/` — composition root: domenlarni import qila oladigan yagona joylar.
5. Domenlararo kontraktlar (Query Port interfeyslari, event payload'lari) — `app/shared/contracts/`.
6. import-linter S0 dan boshlab CI'da majburiy.

## Ko'rib chiqilgan variantlar

### Variant A — `src/commerce_os/modules/...` + `workflows/` (DEC-004 A)
- ❌ Rad etildi: bismuth bilan mos emas; `workflows/` domenlar orasida sinxron yozishga yo'l ochadi (ADR-032 ga zid).

### Variant B — `app/contexts/...` + `entrypoints/`
- ❌ Rad etildi: kontekstlararo jarayonlar uchun aniq qoida yo'q.

## Oqibatlar

### Ijobiy
- Ikki loyihada bitta uslub; AI yordamchi uchun bitta qoidalar to'plami.
- Chegaralar CI'da avtomatik tekshiriladi.
- Domenni alohida servisga ajratish: schema + papka + event'lar tayyor.

### Salbiy
- Boilerplate ko'proq (har domen uchun manifest, events, permissions).
- Eski hujjatlar (03, 04, 22) qayta yoziladi — v2 da bajarildi.

### Neytral
- `shared/contracts/` o'sib ketmasligi kerak: faqat interfeys va DTO, logika yo'q.

## Tekshiruv

- `lint-imports` CI'da o'tadi.
- `tests/architecture/` — domenlar bir-birini import qilmasligini tekshiradi.

## Qayta ko'rish sharti

Bitta domen boshqalardan 3 baravar katta bo'lsa yoki alohida jamoa paydo bo'lsa — bo'lish yoki alohida servis haqida yangi ADR.

## Havolalar

- [02-folder-skeleton.md](../02-folder-skeleton.md), [03-module-requirements.md](../03-module-requirements.md)
- `bismuth_platform_v2/docs/v2/02-folder-skeleton.md`, `ADR-003-domain-isolation.md`
