# ADR-032: `commerce` domeni va domenlararo aloqa (event + Query Port)

**Sana:** 2026-10-22
**Holat:** Accepted — ADR-021 ni almashtiradi (Superseded: ADR-021)
**Qaror qabul qiluvchi:** Founder
**Bog'liq:** DEC-126, DEC-100, DEC-105, DEC-108, TC-002, TC-027, TC-028, TC-030

## Kontekst

Bismuth v2 qoidasi: domenlar orasida yozish faqat event orqali. Lekin buyurtmani tasdiqlash va mahsulotni band qilish **bitta tranzaksiyada** bo'lishi shart: oxirgi mahsulotga ikki operator bir vaqtda tasdiq bossa, faqat bittasi o'tishi kerak (TC-002), online buyurtma va do'kondagi "tez sotuv" to'qnashsa ham (TC-027).

Eski ADR-021 buni `workflows/` papkasi orqali hal qilgan edi: ikki modulni bitta UoW'da boshqaradigan istisno. Bu bismuth qoidasiga zid va istisnolar ko'payib ketishi mumkin.

## Qaror

1. **`commerce` domeni** quyidagilarni o'z ichiga oladi: `inventory` (qoldiq, ledger, band qilish, tez sotuv), `leads`, `quotes` (PC taklif), `orders`. Tasdiqlash, band qilish, topshirish (qoldiq kamayishi) — domen ichida, bitta tranzaksiyada.
2. **Domenlar orasida yozish — faqat event (outbox).** Misollar:
   - `sales_ai.order_draft.requested` → `commerce` `DRAFT` buyurtma yaratadi (qoldiq o'zgarmaydi, DEC-100c).
   - `sales_ai.quote_draft.requested` → `commerce` taklif qoralamasi.
   - `sales_ai.reply.ready` → `messaging` (speaker_version tekshirib) yuboradi.
3. **Domenlar orasida o'qish — faqat read-only Query Port.** Interfeys va DTO `app/shared/contracts/<domain>.py` da, implementatsiya egasi domenda, ulanish `app/dependencies.py` da.
   - `CatalogQueryPort`: `search`, `get_product`, `get_active_price`, `check_compatibility`, ...
   - `CommerceQueryPort`: `get_availability`, `get_order_status`, `get_order_for_support`, ...
   - `MessagingQueryPort`: `get_conversation_context`, ...
   - `SalesAiQueryPort`: `get_reply`, `resolve_contact_ref`.
   - To'liq ro'yxat — `05-events-and-outbox.md` §8.9.
4. **Ko'p va tez o'qish** (hisobotlar) — local read model: `reporting` event'lardan proyeksiya quradi.
5. **Platform xizmatlari** (audit, notifications, use, billing) — domen ularni to'g'ridan-to'g'ri chaqiradi (qatlam qoidasi ruxsat beradi).
6. Buyurtma tasdiqlashda **qoldiq** — `commerce` ning o'z jadvalidan, `FOR UPDATE` bilan; **narx** — `CatalogQueryPort.get_active_price()` orqali sinxron, keshsiz o'qiladi va buyurtma qatoridagi snapshot bilan solishtiriladi (farq bo'lsa `409 PRICE_CHANGED`). Hech qachon keshdan emas (ADR-019). Founder qarori, 2026-10-22; batafsil `12` §5.1.
7. Storefront'dan buyurtma so'rovi — `commerce` domenining `storefront` surface router'i (`POST /api/v1/storefront/{slug}/order-requests`), sinxron; event shart emas.

## Ko'rib chiqilgan variantlar

### Variant B — ombor va buyurtma alohida, `workflows/` istisnosi bilan
- ❌ Rad etildi: bismuth 4-qoidasiga istisno; CI'da maxsus ruxsat; keyin boshqa "istisno"lar qo'shilishi xavfi.

### Variant C — faqat event (saga)
- ❌ Rad etildi: operator "tasdiqlandi" ko'radi, keyin kompensatsiya bilan "mahsulot yo'q" bo'ladi — TC-002/TC-027 talabini buzadi.

## Oqibatlar

### Ijobiy
- Ikki marta sotish xavfi yo'q, saga va kompensatsiya kerak emas.
- Bismuth qoidalari istisnosiz saqlanadi.
- AI va boshqa domenlar `commerce` ichiga kira olmaydi — faqat so'raydi.

### Salbiy
- `commerce` eng katta domen bo'ladi — sub-modullar intizomi kerak.
- AI yaratgan qoralama 100–500 ms kechikib paydo bo'ladi (UI "yaratilmoqda").

### Neytral
- Stage 2 da `payments` va `fulfillment` qaytganda: to'lov tasdiqlanishi buyurtma holatini atomik o'zgartirishi kerak bo'lsa — `payments` ni ham `commerce` ichida sub-modul qilish yoki event + idempotent qabul — alohida ADR.

## Tekshiruv

- TC-002, TC-027, TC-030 (`tests/concurrency/`).
- TC-028: AI "olaman" → faqat `DRAFT`, qoldiq o'zgarmaydi.
- import-linter: `sales_ai` `commerce` ni import qilmaydi.

## Qayta ko'rish sharti

`commerce` kodi boshqa domenlar yig'indisidan katta bo'lsa yoki `leads`/`quotes` mustaqil o'zgarish tezligiga ega bo'lsa — ularni alohida domenga chiqarish (ular invariantda qatnashmaydi).

## Havolalar

- [01-architecture-overview.md](../01-architecture-overview.md) §2–3, [05-events-and-outbox.md](../05-events-and-outbox.md), [12-concurrency-and-transactions.md](../12-concurrency-and-transactions.md)
- `bismuth_platform_v2/docs/v2/11-data-sharing-strategy.md`
