# ADR-001: FastAPI va modular monolith

**Sana:** 2026-10-21 (v2 formatiga ko'chirildi 2026-10-22)
**Holat:** Accepted (2026-10-21) — ichki qatlamlar (`domain/application/adapters`) ADR-031 bilan almashtirildi
**Qaror qabul qiluvchi:** Founder
**Bog'liq:** DEC-004, ADR-031, ADR-032

## Kontekst

Loyihani bitta founder AI yordamchi bilan quradi. 39 ta biznes modul (M01–M39) bor, lekin ular alohida deploy qilinadigan servislar emas. Buyurtma tasdiqlash va qoldiqni band qilish kabi amallar lokal ACID tranzaksiyani talab qiladi.

## Qaror

1. Backend — bitta FastAPI ilovasi (modular monolith), bitta repo, bitta Docker image.
2. Modullar orasida ichki HTTP yo'q; worker'lar ham shu kod paketini ishlatadi.
3. **2026-10-22 o'zgarishi:** modul ichidagi `domain / application / adapters` qatlamlari va `workflows/` o'rniga bismuth v2 tuzilmasi qabul qilindi: `app/shared` ← `app/platform` ← `app/domains`, har domen `api/ services/ repository/ models/ state_machine.py` (ADR-031). Domenlararo aloqa — event + Query Port (ADR-032).

## Ko'rib chiqilgan variantlar

### Microservices
- ❌ Rad etildi: bitta odam uchun operatsion yuk katta, tranzaksiyalar taqsimlanadi

### Django'ga to'liq o'tish
- ❌ Rad etildi: async va mavjud bilim FastAPI'da

## Oqibatlar

### Ijobiy
Bitta deploy, lokal tranzaksiyalar, oddiy debug.

### Salbiy
Bitta jarayon yiqilsa hammasi ta'sirlanadi — worker'lar alohida jarayonda ishlaydi.

### Neytral
Chegaralar faqat CI tekshiruvi bilan saqlanadi (import-linter).

## Tekshiruv

import-linter va `tests/architecture/` CI'da; port integratsiya testlari.

## Qayta ko'rish sharti

Mustaqil masshtablash yoki reliz zaruriyati o'lchab tasdiqlansa — domenni alohida servisga chiqarish.

## Havolalar

- Manba: eski `05_ARCHITECTURE_DECISIONS_ADR.md` (v1)
- [../../decisions/DECISION_REGISTER.md](../../decisions/DECISION_REGISTER.md)
