# 29 — Bog'lanish indeksi (traceability)

> **Versiya:** v2 (2026-10-22). Eski `36_TRACEABILITY_INDEX` o'rnini bosadi; domenlar ADR-031/032 bo'yicha.
> **Maqsad:** har biznes modul (`Mxx`) qaysi kod joyida yashashi, qaysi qoidalar, holatlar, sahifalar va sinovlar bilan bog'liqligini bitta jadvalda ko'rish.

**Manbalar:** modullar — `../business/02`, qoidalar — `../business/03`, rollar — `../business/04`, holatlar — `../business/05`, sahifalar — `../business/06`, sinovlar — `../business/10` (UAT va TC), domenlar — [01-architecture-overview.md](01-architecture-overview.md) §2.

**Qanday ishlatiladi:** biror qoida yoki modul o'zgarsa, shu qatordagi hamma ustunni tekshiring: kod joyi, holatlar, sahifa, sinov.

---

## 1. Stage 1 — shop uchun savdo tizimi

| Modul | Kod joyi (qatlam/modul/sub-modul) | Qoidalar | Holatlar | Sahifalar (`06`) | Sinovlar |
|---|---|---|---|---|---|
| M01 Shop akkaunti | `platform/shops` | BL-001…004 | FSM-01 | `/setup` | UAT-M01, TC-001, TC-023, TC-ISO-01…10 |
| M02 Xodimlar, rollar | `platform/staff`, `platform/auth` | BL-005…008 | Xodim (a'zolik) | `/team` | UAT-M02, TC-025, TC-029 |
| M03 Filiallar | `platform/shops` | BL-009, BL-010 | — | `/branches` | UAT-M03 |
| M04 Katalog | `domains/catalog/products`, `catalog/imports` | BL-011…014 | FSM-02 | `/catalog` | UAT-M04 |
| M05 Narx, valyuta, chegirma | `domains/catalog/pricing` | BL-015…018 | — | `/prices` | UAT-M05, TC-031 |
| M06 Ombor va band qilish | `domains/commerce/inventory` | BL-019…023, BL-109 | FSM-07 | `/inventory` | UAT-M06, TC-002, TC-027, TC-030 |
| M07 Shop sayti | `domains/storefront/sites`, `storefront/public_catalog`; buyurtma so'rovi — `commerce/orders` (surface `storefront`) | BL-024…026 | — | `/storefront`; sayt: `/p/{mahsulot}`, `/cart`, `/quote/{kod}`, `/orders/{kod}` | UAT-M07, TC-001 |
| M08 PC yig'ish va moslik | `domains/catalog/pc_specs`, `catalog/compatibility` | BL-027…030 | — | `/pc-builder` | UAT-M08, TC-008 |
| M09 Kanallarni ulash | `domains/messaging/channels` | BL-031…033 | FSM-03 | `/channels` | UAT-M09, TC-011 |
| M10 Inbox va operatorga uzatish | `domains/messaging/conversations`, `platform/realtime` | BL-034…037 | FSM-04 | `/inbox` | UAT-M10, TC-009, TC-010 |
| M11 AI sotuvchi | `domains/sales_ai/agent` (+ `platform/llm`) | BL-038…041, BL-110 | — | `/inbox`, `/settings/ai` | UAT-M11, TC-007, TC-028 |
| M12 Leadlar va PC takliflari | `domains/commerce/leads`, `commerce/quotes` | BL-042…045 | FSM-05, FSM-06 | `/leads`; sayt: `/quote/{kod}` | UAT-M12, TC-031 |
| M13 Buyurtmalar | `domains/commerce/orders` | BL-046…049, BL-111 | FSM-08 | `/orders`; sayt: `/orders/{kod}` | UAT-M13, TC-002, TC-003, TC-027, TC-028, TC-029, TC-030 |
| M14 To'lov — ⏸ DEFERRED (DEC-100) | keyin: `domains/payments` | BL-050…053 ⏸ | FSM-09 ⏸ | — | TC-004, TC-005, TC-006, TC-021 ⏸ |
| M15 Yetkazish — ⏸ DEFERRED (DEC-113) | keyin: `domains/fulfillment` | BL-054…056 ⏸ | FSM-10 ⏸ | — | — |
| M16 Kafolat va qaytarish | `domains/support/cases` | BL-057…059 | FSM-11 | `/support` | UAT-M16, TC-020 |
| M17 Xabarnomalar va vazifalar | `platform/notifications` | BL-060…062 | FSM-12 | `/notifications` | UAT-M17, TC-032 |
| M18 Hisobotlar va hisobot yordamchisi | `domains/reporting/metrics`, `reporting/read_models`, `reporting/assistant` | BL-063…066 | — | `/overview`, `/reports` | UAT-M18, TC-012, TC-013, TC-014 |
| M19 AI sozlamalari, tarif, limitlar | `platform/billing` (tarif, limitlar); `domains/sales_ai/knowledge` (AI rejimi, FAQ, agent profili) | BL-067…070 | — | `/settings/ai`, `/settings/billing` | UAT-M19 |
| M20 O'zgarishlar tarixi | `platform/audit` (+ `platform/use` — o'tishlar jurnali) | BL-071, BL-072 | — | `/audit` | UAT-M20 |

**Butun tizim uchun:** TC-022 (worker to'xtab qolishi) — `workers/` + outbox (ADR-033); TC-033 (backup'dan tiklash) — `deploy/backup` (`22`, `25`); TC-ISO — `app/tests/isolation/` (`10`).

---

## 2. Stage 2 — shoplar tarmog'i

| Modul | Kod joyi | Qoidalar | Holatlar | Sinovlar |
|---|---|---|---|---|
| M21 Shop o'zi ro'yxatdan o'tadi | `platform/shops` + `domains/network` (provisioning) | BL-001, BL-003, BL-067 | FSM-01 | UAT-M21 |
| M22 Integratsiyalar (kassa, ERP) | `domains/network/integrations` | BL-073…075 | FSM-13 | UAT-M22, TC-019 |
| M23 Umumiy mahsulot registri | `domains/network/registry` | BL-076…078 | FSM-15 | UAT-M23, TC-016 |
| M24 Ommaviy taklif (rozilik) | `domains/network/public_offers` (ADR-018) | BL-079…081 | FSM-14 | UAT-M24, TC-015 |
| M25 Ko'p filialli ombor | `domains/commerce/inventory` | BL-019, BL-021, BL-082 | FSM-07 | UAT-M25 |
| M26 Ko'p shop, obunalar | `platform/shops`, `platform/billing` | BL-067, BL-068, BL-083 | — | UAT-M26 |
| M27 AI bilim markazi | `domains/sales_ai/knowledge` | BL-038, BL-039, BL-084 | — | UAT-M27 |
| M28 Qidiruv indeksi va katalog sifati | `domains/network/publishing` | BL-080, BL-085, BL-086 | — | UAT-M28 |
| M29 Shopni tasdiqlash, ishonch | `domains/network/trust` | BL-087, BL-088 | FSM-16 | UAT-M29 |
| M30 Partner API | `domains/network/integrations` (API kalitlari), `platform/auth` | BL-005, BL-074, BL-089 | — | UAT-M30 |

Sahifalar — `../business/06` Stage 2 bo'limi. UAT-M21…M30 Stage 2 boshlanganda yoziladi (`../business/10` §2). Batafsil: [28-network-and-global-search.md](28-network-and-global-search.md).

---

## 3. Stage 3 — global AI qidiruv

| Modul | Kod joyi | Qoidalar | Holatlar | Sinovlar |
|---|---|---|---|---|
| M31 Global qidiruv va filtrlar | `domains/marketplace/search` | BL-090, BL-091 | — | UAT-M31 |
| M32 Narxlarni solishtirish | `domains/marketplace/compare` | BL-092…094 | — | UAT-M32, TC-017 |
| M33 Xarita, yaqin atrofda | `domains/marketplace/geo` | BL-095, BL-096 | — | UAT-M33, TC-026 |
| M34 Global AI maslahatchi | `domains/marketplace/advisor` (`sales_ai` dan alohida) | BL-097…099 | — | UAT-M34, TC-018 |
| M35 Shopga yo'naltirish | `domains/marketplace/referrals` → event → `commerce/leads` | BL-100, BL-101 | FSM-17 | UAT-M35 |
| M36 Xaridor akkaunti, saqlanganlar, ogohlantirishlar | `domains/marketplace/buyers` | BL-102, BL-103 | FSM-18 | UAT-M36 |
| M37 Organik va reklama tartiblash | `domains/marketplace/ranking` | BL-104, BL-105 | — | UAT-M37, TC-024 |
| M38 Kontent va SEO sahifalar | `domains/marketplace/content` + `domains/storefront` | BL-106, BL-107 | — | UAT-M38 |
| M39 Global Telegram bot va API | `domains/marketplace` + `messaging/channels` adapteri | BL-098, BL-100, BL-108 | — | UAT-M39 |

`marketplace` faqat `network` ning ommaviy proyeksiyasini o'qiydi; shopning xususiy jadvallariga yo'l yo'q (`01` §9).

---

## 4. Teskari ko'rinish: domen → modullar

| Kod joyi | Modullar |
|---|---|
| `platform/auth` | M02, M30 |
| `platform/shops` | M01, M03, M21, M26 |
| `platform/staff` | M02 |
| `platform/use` | M20 (o'tishlar jurnali), barcha FSM'lar |
| `platform/audit` | M20 |
| `platform/notifications` | M17 |
| `platform/realtime` | M10 |
| `platform/llm` | M11, M18 (yordamchi), M34 |
| `platform/billing` | M19, M26 |
| `domains/catalog` | M04, M05, M08 |
| `domains/commerce` | M06, M12, M13, M25 |
| `domains/messaging` | M09, M10, M39 (adapter) |
| `domains/sales_ai` | M11, M19 (AI sozlamalari), M27 |
| `domains/storefront` | M07, M38 |
| `domains/support` | M16 |
| `domains/reporting` | M18 |
| `domains/payments` ⏸ | M14 |
| `domains/fulfillment` ⏸ | M15 |
| `domains/network` (Stage 2) | M21–M24, M28–M30 |
| `domains/marketplace` (Stage 3) | M31–M39 |

---

## 5. Engineering'ga o'tishdan oldin tekshiruv

1. Har `M01…M39` `../business/02`, rollar, holatlar va sinovlarda bor.
2. `BL-001…BL-111` bir marta e'lon qilingan, osilib qolgan havola yo'q.
3. Har sezgir amalning ruxsat va tasdiqlash yo'li bor (`../business/04`).
4. Stage 1 savdosi keyingi bosqich moduliga bog'liq emas.
5. Har AI tool'i haqiqiy manbaga (Query Port) ishora qiladi; erkin SQL yo'q.
6. Takror va parallel amallarning aniq natijasi yozilgan (TC-002, TC-003, TC-010, TC-027, TC-030).
7. Bir xil mahsulot — aynan bir xil variant va holat; shop taklifi umumiy mahsulotga aralashmaydi.
8. Ommaviy taklifni qaytarib olish qidiruv indeksidan mustaqil himoyalangan.
9. Barcha UAT oldindan ma'lum sintetik ma'lumot bilan, reklama raqamlari bilan emas.
10. Tasdiqlanmagan ADR, provayder ruxsati yoki huquqiy talqin "tayyor" deb e'lon qilinmaydi.
