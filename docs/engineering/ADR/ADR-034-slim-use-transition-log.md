# ADR-034: Slim USE — holat o'tishlari markazi

**Sana:** 2026-10-22
**Holat:** Accepted
**Qaror qabul qiluvchi:** Founder
**Bog'liq:** DEC-004 C, K-02, K-03, `../business/05`

## Kontekst

Loyihada ko'p holatlar ketma-ketligi bor: shop (FSM-01), mahsulot (FSM-02), kanal (FSM-03), suhbat (FSM-04), lead (FSM-05), taklif (FSM-06), band qilish (FSM-07), buyurtma (FSM-08), kafolat (FSM-11), xabar (FSM-12). Har domen holatni o'zicha o'zgartirsa: noto'g'ri o'tishlar, tarix yo'q, audit tarqoq. Bismuth v1 da esa markaziy USE "god-orchestrator" bo'lib ketgan (1500 qator side-effect).

## Qaror

`app/platform/use` — **faqat 3 ish**:
1. `validate_transition(entity_type, from_status, to_status, command)` — qoida bormi? Yo'q bo'lsa `InvalidTransitionError` (409 `INVALID_STATE_TRANSITION`).
2. `log_transition(...)` — `platform.transition_log` ga: entity, eski → yangi holat, buyruq, actor (xodim / AI / tizim), sabab, `trace_id`, vaqt. O'sha tranzaksiyada.
3. `force_transition(...)` — faqat platforma admini, majburiy sabab, audit bilan (runbook'lar uchun).

Qoidalar har domenning `state_machine.py` faylida (`StateMachineRule`), boot vaqtida `rules_loader` yig'adi. Qoidalar `../business/05` dagi strelkalarga 1:1 mos; mos kelmasa — test yiqiladi.

USE **qilmaydi:** notification, event yuborish (domen outbox'ga o'zi yozadi), ruxsat tekshirish (router'da), AI chaqirish, boshqa entity yaratish.

## Ko'rib chiqilgan variantlar

### USE'siz — har domen o'zi
- ❌ Rad etildi: o'tishlar jurnali va tekshiruv tarqoq bo'ladi.

### "Katta" USE (orkestrator)
- ❌ Rad etildi: bismuth v1 tajribasi — god class.

## Oqibatlar

### Ijobiy
- Har holat o'zgarishining tarixi bitta jadvalda (kim, qachon, nega).
- Yangi holat qo'shish — faqat `state_machine.py`.

### Salbiy
- Har o'tishda bitta qo'shimcha INSERT.

### Neytral
- `transition_log` tez o'sadi — oyma-oy partition (`07`).

## Tekshiruv

- Har domen `tests/` da: har ruxsat etilgan o'tish o'tadi, har taqiqlangan o'tish 409 qaytaradi.
- `business/05` ↔ `state_machine.py` muvofiqlik testi.

## Havolalar

- [04-state-machines-and-use.md](../04-state-machines-and-use.md)
- `bismuth_platform_v2/docs/v2/04-use-service-v2.md`, `ADR/ADR-001-slim-use.md`
