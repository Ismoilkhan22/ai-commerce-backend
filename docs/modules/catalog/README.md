# catalog

**Qatlam:** domain · **Schema:** `catalog` · **Slice:** S1 (mahsulot, narx, import), S3 (PC moslik) · **Egasi:** ___
**Biznes modullar:** M04, M05, M08 · **Qoidalar:** BL-011…014 (katalog), BL-015…018 (narx, kurs), BL-027…030 (PC yig'ish) · **Holatlar:** FSM-02 (`../../business/05`)

## 1. Nima qiladi

Shop katalogi: mahsulotlar va SKU'lar, rasmlar, saytga chiqarish, narx versiyalari, dollar kursi, chegirma qoidalari, fayldan import, PC qismlari texnik ma'lumotlar kutubxonasi va moslik engine'i (K-09: `PASS` / `REVIEW_REQUIRED` / `BLOCK`).

Nima qilmaydi: qoldiqni yuritmaydi — import qoldig'i ham `commerce` ga event orqali beriladi. Moslik natijasini saqlamaydi — taklif snapshot'i `commerce` da (`quote_compatibility_snapshots`).

## 2. Sub-modullar

| Sub-modul | Vazifasi | Asosiy jadvallar |
|---|---|---|
| `products` | Mahsulot, SKU, rasm, FSM-02 | `products`, `skus`, `product_media` |
| `pricing` | Narx versiyalari, joriy narx, kurs, chegirma qoidalari | `price_versions`, `current_prices`, `exchange_rates`, `discount_rules`, `currencies` |
| `pc_specs` | Texnik ma'lumotlar kutubxonasi, SKU bog'lash | `reference_hardware_specs`, `sku_spec_links` |
| `compatibility` | Moslik engine, qoidalar versiyalari, yig'ma profillari | `pc_rulesets`, `build_profiles` |
| `imports` | CSV/XLSX import, xatolar, qoldiq staging | `catalog_imports`, `catalog_import_rows`, `import_stock_rows` |

`reference_hardware_specs`, `pc_rulesets`, `build_profiles`, `currencies` — platforma egaligida, `shop_id` yo'q (shoplar faqat o'qiydi). Batafsil — [07](../../engineering/07-data-layer.md) §4.3.

## 3. Holatlar

```
Mahsulot (FSM-02):
DRAFT ──(katalog xodimi tekshiruvga yubordi)──▶ IN_REVIEW        [majburiy maydonlar, narx bormi]
IN_REVIEW ──(menejer tasdiqladi)──▶ PUBLISHED                   [sayt va AI ko'radi]
PUBLISHED ──(menejer yashirdi)──▶ HIDDEN ──(qayta chiqarildi)──▶ PUBLISHED
PUBLISHED ──(ega arxivladi)──▶ ARCHIVED
```
Aniq strelkalar — `../../business/05` (FSM-02), kod nomlari — [04](../../engineering/04-state-machines-and-use.md) §4. Narx holatsiz: har o'zgarish yangi `price_versions` qatori (immutable).

## 4. Event'lar

### Chiqaradi
| Event | Qachon | Kim tinglaydi |
|---|---|---|
| `catalog.product.published` / `hidden` / `archived` | FSM-02 | storefront, reporting |
| `catalog.price.changed` | yangi narx versiyasi | storefront, reporting |
| `catalog.exchange_rate.updated` | kurs yangilandi | storefront, reporting |
| `catalog.import.completed` | import tugadi (`has_stock_rows`) | commerce, storefront, reporting |
| `catalog.pc_ruleset.activated` | yangi qoidalar versiyasi | sales_ai, commerce |
| `catalog.hardware_spec.updated` | kutubxona yoki bog'lanish o'zgardi | sales_ai, storefront, reporting |

### Tinglaydi
| Event | Kimdan | Nima qiladi |
|---|---|---|
| `commerce.import_stock.applied` | commerce | Import holatini yakunlaydi |
| `platform.privacy.*` | platform | `privacy_handlers` |

Payload'lar — [05](../../engineering/05-events-and-outbox.md) §8.1.

## 5. Query Port (`CatalogQueryPort`)

| Metod | Kim ishlatadi |
|---|---|
| `search`, `get_product` | sales_ai (tool `catalog.search`), storefront |
| `get_active_price` | sales_ai (`catalog.get_price_stock`), commerce |
| `check_compatibility`, `suggest_builds` | sales_ai (`catalog.check_compatibility`, `catalog.suggest_builds`), commerce (taklif) |
| `get_import_stock_rows` | commerce |
| `get_public_projection` | storefront |
| `list_reference_specs` | storefront, sales_ai |

Interfeys — `app/shared/contracts/catalog.py`.

## 6. API (`shop` surface)

`/shop/products` (+ `/submit-review`, `/publish`, `/hide`, `/archive`, `/skus`), `/shop/skus/{id}` (+ `/price`, `/price-history`, `/spec-link`), `/shop/exchange-rates`, `/shop/catalog/imports` (+ `PUT /mapping`, `/dry-run`, `/commit` — `catalog.import.commit`, `/errors.csv`), `/shop/hardware-specs`, `/shop/hardware-spec-requests`, `POST /shop/pc-builds/check`.
`platform` surface: `/platform/hardware-specs` (`platform.spec.edit`).

To'liq ro'yxat — [11](../../engineering/11-api-conventions-errors-i18n.md) §9.3. Import — [18](../../engineering/18-catalog-import.md), moslik — [17](../../engineering/17-pc-compatibility-engine.md).

Asosiy xatolar: `EXCHANGE_RATE_STALE`, `IMPORT_FILE_INVALID`, `VERSION_CONFLICT`, `INVALID_STATE_TRANSITION`.

## 7. Ruxsatlar

`catalog.product.view|edit|publish`, `catalog.import.run|commit`, `catalog.price.view|change`, `catalog.exchange_rate.edit`, `catalog.spec.link`, `catalog.compatibility.check` — [10](../../engineering/10-security-tenancy-rbac.md) §6.2. Katalog xodimi narx o'zgartira olmaydi (UAT-M04); saytga chiqarish — menejer yoki ega.

## 8. Fon va rejali ishlar

| Ish | Qachon | Idempotency kaliti |
|---|---|---|
| `catalog_import` (arq, `low`) | import commit | `import_id` + qator raqami |
| `media_process` (arq, `low`) | rasm yuklandi | `file_id` |
| `exchange_rate_staleness` | har soat; kurs 3 kundan eski | `fx_stale:{shop_id}:{date}` |
| `exchange_rate_fetch` | har kuni 09:30 (MB kursi) | `fx_fetch:{date}` |

Batafsil — [06](../../engineering/06-background-jobs.md).

## 9. Metrikalar

`cos_catalog_compatibility_checked_total`, `cos_catalog_import_rows_total`, `cos_catalog_exchange_rate_age_seconds` — [09](../../engineering/09-observability.md).

## 10. Testlar

- UAT-M04, UAT-M05, UAT-M08 (`../../business/10`); TC-008 (BIOS noma'lum → `REVIEW_REQUIRED`).
- TC-IMP-01…10 ([18](../../engineering/18-catalog-import.md)); moslik qoidalari golden set ([17](../../engineering/17-pc-compatibility-engine.md)).
- TC-ISO: B shop mahsuloti A shop so'rovlarida yo'q.

## 11. Ochiq savollar

1. Spec kutubxonasi Stage 2 da `catalog` da qoladimi yoki `network` ga ko'chadimi (`28`).
