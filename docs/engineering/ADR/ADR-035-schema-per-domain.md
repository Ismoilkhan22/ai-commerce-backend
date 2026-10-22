# ADR-035: Har domen — alohida PostgreSQL schemasi

**Sana:** 2026-10-22
**Holat:** Accepted — ADR-002 ni to'ldiradi
**Qaror qabul qiluvchi:** Founder
**Bog'liq:** DEC-004 C, DEC-001, DEC-002, ADR-026

## Kontekst

ADR-002: hamma shoplar bitta PostgreSQL'da, har qatorda `shop_id` (shared-first). Lekin domenlar orasidagi chegara faqat kod darajasida edi — bir domen boshqa domen jadvaliga JOIN yoki FK qilib qo'yishi mumkin edi. Bismuth v2 da har domen o'z schemasida (ADR-003).

## Qaror

1. Schemalar: `platform`, `audit`, `catalog`, `commerce`, `messaging`, `sales_ai`, `storefront`, `support`, `reporting`. Keyin: `payments`, `fulfillment`, `network`, `marketplace`.
2. **Cross-schema FK va JOIN — TAQIQ** (production kodda). Boshqa domen obyekti — `UUID` ustuni, FK'siz.
3. `shop_id` hamma schemalarda bor, lekin `platform.shops` ga FK faqat `platform` schemasi ichida. Boshqa schemalarda `shop_id` FK'siz, butunligi `ActorContext` va RLS bilan ta'minlanadi.
4. Har schema uchun alohida Alembic env (`app/db/migrations/<schema>/`).
5. DB rollari: `app_migrator` (DDL), `app_runtime` (`NOBYPASSRLS`, faqat DML). Keyinroq har schema uchun alohida runtime rol — kerak bo'lsa.
6. RLS (DEC-002) schema'dan qat'i nazar sezgir jadvallarda: `USING (shop_id = current_setting('app.shop_id')::uuid)`.
7. Shop bo'yicha eksport yoki o'chirish (pilot tugasa, `26`) — har schemada `WHERE shop_id = ...`; skript schemalar ro'yxatini `schemas.sql` dan oladi.

## Ko'rib chiqilgan variantlar

### Bitta schema, prefikslar bilan
- ❌ Rad etildi: chegara faqat kelishuvga tayanadi.

### Har shop uchun alohida DB yoki schema
- ❌ Rad etildi (hozircha): DEC-001 C — shared-first; dedicated rejim — butun stack nusxasi (`10`), schema emas.

## Oqibatlar

### Ijobiy
- Domen chegarasi DB darajasida ham ko'rinadi.
- `pg_dump --schema=commerce` — domen bo'yicha backup va ajratish.
- Alohida servisga chiqarish ishi deyarli tayyor.

### Salbiy
- Hisobotlar uchun cross-schema JOIN yo'q — `reporting` read model'lari kerak.
- Har domen uchun Alembic env takrorlanadi.

### Neytral
- Bitta tranzaksiya bir nechta schemaga yozishi texnik mumkin, lekin qoida bo'yicha faqat o'z domeni + `platform`/`audit` (transition log, audit, idempotency).

## Tekshiruv

- Migratsiya CI testi: cross-schema FK yo'qligini tekshiradi (`information_schema`).
- TC-ISO: RLS har sezgir jadvalda yoqilgan.

## Havolalar

- [07-data-layer.md](../07-data-layer.md), [10-security-tenancy-rbac.md](../10-security-tenancy-rbac.md)
- `bismuth_platform_v2/docs/v2/ADR/ADR-003-domain-isolation.md`
