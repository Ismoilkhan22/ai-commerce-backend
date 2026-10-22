# 12 — CROSS-DOCUMENT TRACEABILITY INDEX

**Version:** v1.0. Every module `Mxx` maps to business rules and UAT section. UX uses `06`, FSM `05`, data `07`, AI `08`, events `09`.

| Module | Phase | Rules | UX surfaces | UAT test | Adjacent modules |
|---|---|---|---|---|---|
| `M01` — Merchant tashkiloti va onboarding | 1 | `BL-001` `BL-002` `BL-003` `BL-004` | Onboarding wizard, Merchant profile | `UAT-M01` | M02, M03, M07, M18 |
| `M02` — Xodimlar, rollar va filial ruxsatlari | 1 | `BL-005` `BL-006` `BL-007` `BL-008` | Team list, Invite panel | `UAT-M02` | M01, M17, M18 |
| `M03` — Filiallar va xizmat hududi | 1 | `BL-009` `BL-010` | Branch list/map, Schedule editor | `UAT-M03` | M01, M02, M06, M16 |
| `M04` — Katalog, variant va SKU | 1 | `BL-011` `BL-012` `BL-013` `BL-014` | Products table, Product editor | `UAT-M04` | M05, M06, M08, M10, M11 |
| `M05` — Narx, valuta va chegirmalar | 1 | `BL-015` `BL-016` `BL-017` `BL-018` | Pricing table, Change price dialog | `UAT-M05` | M04, M08, M10, M12, M13 |
| `M06` — Ombor, kirim-chiqim va rezerv | 1 | `BL-019` `BL-020` `BL-021` `BL-022` `BL-023` | Stock list, SKU stock ledger | `UAT-M06` | M03, M04, M12, M13, M14 |
| `M07` — Brendlangan mini-sayt va storefront | 1 | `BL-024` `BL-025` `BL-026` | Storefront builder, Website preview | `UAT-M07` | M01, M04, M05, M06, M12 |
| `M08` — PC configurator va compatibility | 1 | `BL-027` `BL-028` `BL-029` `BL-030` | PC Builder, Compatibility findings | `UAT-M08` | M04, M05, M06, M10, M11 |
| `M09` — Kanallar va kanal hisoblarini ulash | 1 | `BL-031` `BL-032` `BL-033` | Channel connect wizard, Permission status | `UAT-M09` | M01, M02, M10, M11, M17 |
| `M10` — Unified Inbox, conversation va human handoff | 1 | `BL-034` `BL-035` `BL-036` `BL-037` | Unified inbox, Conversation detail | `UAT-M10` | M02, M09, M11, M12, M17 |
| `M11` — AI Sales Agent va product discovery | 1 | `BL-038` `BL-039` `BL-040` `BL-041` | AI agent config, Tool permissions | `UAT-M11` | M04, M05, M06, M08, M10 |
| `M12` — Lead, CRM va quotation | 1 | `BL-042` `BL-043` `BL-044` `BL-045` | Lead pipeline, Lead detail | `UAT-M12` | M05, M08, M10, M11, M13 |
| `M13` — Buyurtma va order lifecycle | 1 | `BL-046` `BL-047` `BL-048` `BL-049` | Order list, Order detail | `UAT-M13` | M06, M12, M14, M15, M16 |
| `M14` — To‘lov va chekni tekshirish | 1 | `BL-050` `BL-051` `BL-052` `BL-053` | Payments list, Review receipt | `UAT-M14` | M02, M06, M13, M17, M18 |
| `M15` — Yetkazish va pickup | 1 | `BL-054` `BL-055` `BL-056` | Fulfillment board, Shipment timeline | `UAT-M15` | M03, M13, M17 |
| `M16` — Sotuvdan keyingi xizmat va kafolat | 1 | `BL-057` `BL-058` `BL-059` | Support inbox, RMA case | `UAT-M16` | M13, M14, M15, M17 |
| `M17` — Notifications, automation va merchant tasks | 1 | `BL-060` `BL-061` `BL-062` | Notification center, Template editor | `UAT-M17` | M09, M10, M12, M13, M14 |
| `M18` — Dashboard, hisobot va Voice Business Copilot | 1 | `BL-063` `BL-064` `BL-065` `BL-066` | Overview dashboard, Report builder | `UAT-M18` | M02, M10, M12, M13, M14 |
| `M19` — Merchant AI controls, billing va platform operations | 1 | `BL-067` `BL-068` `BL-069` `BL-070` | Plan/usage, Settings | `UAT-M19` | M01, M02, M09, M11, M17 |
| `M20` — Activity log va biznes audit | 1 | `BL-071` `BL-072` | Audit search, Object activity timeline | `UAT-M20` | M01, M02, M05, M06, M13 |
| `M21` — Self-service merchant provisioning | 2 | `BL-001` `BL-003` `BL-067` | Public signup, Provision checklist | `UAT-M21` | M01, M07, M19, M22 |
| `M22` — Integration hub / POS / ERP / marketplaces | 2 | `BL-073` `BL-074` `BL-075` | Integration catalog, Mapping wizard | `UAT-M22` | M04, M05, M06, M09, M21 |
| `M23` — Global canonical product registry | 2 | `BL-076` `BL-077` `BL-078` | Global product review, Merge diff | `UAT-M23` | M04, M22, M24, M28 |
| `M24` — Merchant public offers va opt-in | 2 | `BL-079` `BL-080` `BL-081` | Public listings settings, Offer publish preview | `UAT-M24` | M05, M06, M23, M28, M29 |
| `M25` — Multi-branch inventory and fulfillment intelligence | 2 | `BL-019` `BL-021` `BL-082` | Branch stock matrix, Transfer order | `UAT-M25` | M03, M06, M15, M22 |
| `M26` — Merchant tenancy at scale va subscription automation | 2 | `BL-067` `BL-068` `BL-083` | Billing console, Tenant fleet | `UAT-M26` | M19, M21, M22 |
| `M27` — Merchant-facing AI policy/knowledge center | 2 | `BL-038` `BL-039` `BL-084` | Knowledge hub, Agent sandbox | `UAT-M27` | M10, M11, M16, M18 |
| `M28` — Search index publishing and catalog data quality | 2 | `BL-080` `BL-085` `BL-086` | Index health, Publish queue | `UAT-M28` | M23, M24, M29 |
| `M29` — Merchant quality, verification and trust data | 2 | `BL-087` `BL-088` | Trust center, Verification queue | `UAT-M29` | M01, M03, M16, M24 |
| `M30` — Partner API va merchant developer access | 2 | `BL-005` `BL-074` `BL-089` | Developer settings, API usage | `UAT-M30` | M02, M22, M26 |
| `M31` — Global search and filters | 3 | `BL-090` `BL-091` | Global home/search, Results | `UAT-M31` | M23, M24, M28, M32, M33 |
| `M32` — Cross-store price comparison | 3 | `BL-092` `BL-093` `BL-094` | Compare table, Merchant offer card | `UAT-M32` | M23, M24, M28, M33, M34 |
| `M33` — Geo search, near-me va maps | 3 | `BL-095` `BL-096` | Map + list, Nearby merchants | `UAT-M33` | M03, M24, M31, M32 |
| `M34` — Global AI Shopping Advisor | 3 | `BL-097` `BL-098` `BL-099` | AI search chat, Evidence drawer | `UAT-M34` | M23, M24, M31, M32, M33 |
| `M35` — Merchant discovery and referral tracking | 3 | `BL-100` `BL-101` | Merchant page, Contact CTA | `UAT-M35` | M10, M12, M24, M31, M34 |
| `M36` — Buyer account, saved products and alerts | 3 | `BL-102` `BL-103` | Saved items, Alert preferences | `UAT-M36` | M17, M31, M32 |
| `M37` — Organic vs sponsored ranking and transparency | 3 | `BL-104` `BL-105` | Search placements, Sponsor disclosure | `UAT-M37` | M24, M29, M31, M32, M34 |
| `M38` — Global content, SEO and shareable landing pages | 3 | `BL-106` `BL-107` | Product landing, Merchant landing | `UAT-M38` | M23, M24, M28, M31 |
| `M39` — Global Telegram bot and discovery API | 3 | `BL-098` `BL-100` `BL-108` | Global bot, Results cards | `UAT-M39` | M09, M24, M31, M34, M35 |

## Review checklist before transitioning to engineering

1. Every module ID `M01..M39` appears in `02`, UI/role/FSM references and UAT.
2. Rules `BL-001..BL-108` uniquely declared, with no dangling references.
3. All sensitive UI operations have permission and approval path.
4. A stage never depends on unimplemented next-stage module for merchant core sale; public offer projection is optional Stage 1.
5. Every AI tool scope refers to real source-of-truth; no free-form payment/stock SQL or anonymous merchant data.
6. Duplicate/retry and parallel actions have explicit business correctness outcomes.
7. The same product means same exact variant and condition; merchant offers not flattened into canonical metadata.
8. Merchant public opt-out is protected independently from eventually consistent search indexing.
9. All UAT use seeded known data, not marketing claims or hypothetical live store statistics.
10. No unapproved ADR, provider permission, legal interpretation declared production-ready.

## Existing prior package mapping

- Previous `AI_PC_Commerce_OS_Full_Spec_2026` remains a reference for backend and PC-specific feature ideas; not authoritative when it conflicts with this three-stage business baseline.
- Previous `AI_COMMERCE_MASTER_PLAN_V1/00_MASTER_IDEA...` had four named phases; this package uses exactly three, with old phase 4 moved to future extension scope.
- Technical architecture next should consume `02 + 03 + 04 + 05 + 07 + 08 + 09 + 10`, not reverse engineer from disconnected marketing text.
