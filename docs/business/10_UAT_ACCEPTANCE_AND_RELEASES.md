# 10 — ACCEPTANCE/UAT MATRIX + STAGED RELEASE GATES

**Version:** v1.0 | **Goal:** Har bir modulning asosiy business success va failure holati testing orqali tasdiqlansin. Bu real test natijalari emas — implementatsiya uchun test kontrakti.

## Acceptance definition: har bir biznes modul uchun

- Happy path: actor valid, old state valid, data complete, expected new state and visible UI.
- Negative path: kamida bir concrete business failure, prohibited mutation absent.
- Authorization path: wrong merchant/branch/role denied, no sensitive data.
- Retry path: repeated same request/idempotency key does not double change stock, payment, order or notification.
- Observability proof: actor/correlation, event id, operation result and human-readable error state are available without PII leak.

## P0 / P1 release versus entire stages

**Stage 1 contains full target 20 modules; the first production release does NOT need every optional/advanced feature.** A module may be `MUST` for Stage 1 as a business capability but only a smaller **vertical slice** is required in v0.1. Release scope and stage completeness are distinct.

| Vertical slice | Modules | Customer demo ready when | Hard blockers |
|---|---|---|---|
| `R1` Identity + merchant foundation | M01 M02 M03 M20 | owner can create tenant, branch, invite member, audit all writes | cross-tenant leak, last owner deleted |
| `R2` Catalog + stock + storefront | M04 M05 M06 M07 | real SKU input → exact price/stock → own branded site | false price, oversell, wrong tenant |
| `R3` Channels + AI inbox | M09 M10 M11 M17 | Telegram/web customer message → AI grounded response → takeover | unapproved channel, prompt injection, duplicate send |
| `R4` PC quote → order | M08 M12 M13 | PC requirements → compatible quote → manager approve → confirmed order and reservation | incompatible approved build, double order/reservation |
| `R5` Proof + fulfillment + baseline report | M14 M15 M18 | verified merchant settlement → delivery state → accurate dashboard | screenshot auto-paid, phantom report |
| `R6` Operational hardening | M16 M19 M20 + cross-cutting | support/returns, billing safe limits, reconciliation and rollback | unresolved critical refund/payment bug |
| `R7` Voice Copilot beta | M18 + M11 eval services | authorized UZ/RU/EN voice metric correct, transcript correction | unauthorized cross-tenant output, hallucinated money |

**Channel detail:** Meta production credentials are a separately gated rollout, not a blocker for Telegram/web v0.1. Voice can enter beta when golden tests meet agreed criteria; merchant sales product remains usable without it.

## Module-by-module acceptance contracts

### UAT-M01 — Merchant tashkiloti va onboarding

- **Happy path:** authorized `Platform Admin, Owner` performs: *Email/telefon verifikatsiyasi va egani aniqlash*; expected data/status `draft→pending_verification→active→suspended→closed`, appropriate UI `Onboarding wizard` visible; event/audit recorded.
- **Additional functional coverage:** verify *merchant profili: nom, faoliyat, valuta, manzil; onboarding checklist va katalog sifat ko‘rsatkichi; trial/active/suspended/offboarded lifecycle* with concrete seeded test data and actual observable output.
- **Negative path:** simulate *takrorlangan tashkilot* and *egalik bahsi*; unauthorized write does not commit, user gets next step.
- **Rules checked:** `BL-001`, `BL-002`, `BL-003`, `BL-004`.
- **Integration check:** affected collaborator(s) `M02`, `M03`, `M07` reflect the new state without exposing private fields.
- **Metric:** measure aktivlashgunga qadar vaqt, onboarding completion on known fixture; zero silent mismatches.

### UAT-M02 — Xodimlar, rollar va filial ruxsatlari

- **Happy path:** authorized `Owner, Manager, Admin` performs: *Invite va accept*; expected data/status `invited→active→disabled; approval: pending→approved/rejected`, appropriate UI `Team list` visible; event/audit recorded.
- **Additional functional coverage:** verify *role assignment/disable; filialga scope; sezgir operatsiya uchun approval* with concrete seeded test data and actual observable output.
- **Negative path:** simulate *o‘zini oxirgi ownerlikdan o‘chirish* and *ketgan xodim tokeni*; unauthorized write does not commit, user gets next step.
- **Rules checked:** `BL-005`, `BL-006`, `BL-007`, `BL-008`.
- **Integration check:** affected collaborator(s) `M01`, `M17`, `M18` reflect the new state without exposing private fields.
- **Metric:** measure permission denied va approval kechikishi on known fixture; zero silent mismatches.

### UAT-M03 — Filiallar va xizmat hududi

- **Happy path:** authorized `Owner, Manager` performs: *filial yaratish/archivlash*; expected data/status `draft→active→temporarily_closed→archived`, appropriate UI `Branch list/map` visible; event/audit recorded.
- **Additional functional coverage:** verify *manzil va koordinatani tasdiqlash; ish vaqti va pickup opsiyasi; filial kesimida ishchi guruh* with concrete seeded test data and actual observable output.
- **Negative path:** simulate *noto‘g‘ri geolokatsiya* and *do‘kon yopiq*; unauthorized write does not commit, user gets next step.
- **Rules checked:** `BL-009`, `BL-010`.
- **Integration check:** affected collaborator(s) `M01`, `M02`, `M06` reflect the new state without exposing private fields.
- **Metric:** measure filial bo‘yicha pickup so‘rovlar on known fixture; zero silent mismatches.

### UAT-M04 — Katalog, variant va SKU

- **Happy path:** authorized `Owner, Catalog Manager` performs: *mahsulot+variant/SKU*; expected data/status `draft→in_review→published→hidden→archived`, appropriate UI `Products table` visible; event/audit recorded.
- **Additional functional coverage:** verify *brand/model/spec/serial policy; rasm va tavsif; kategoriya atribut template* with concrete seeded test data and actual observable output.
- **Negative path:** simulate *dublikat SKU* and *import qator xatosi*; unauthorized write does not commit, user gets next step.
- **Rules checked:** `BL-011`, `BL-012`, `BL-013`, `BL-014`.
- **Integration check:** affected collaborator(s) `M05`, `M06`, `M08` reflect the new state without exposing private fields.
- **Metric:** measure publishable SKU%, import rejection% on known fixture; zero silent mismatches.

### UAT-M05 — Narx, valuta va chegirmalar

- **Happy path:** authorized `Owner, Manager, Sales limited` performs: *bazaviy narx va price-list*; expected data/status `draft→active→expired/superseded`, appropriate UI `Pricing table` visible; event/audit recorded.
- **Additional functional coverage:** verify *narx tarixi va effective time; discount policy/limit; manual quote price approval* with concrete seeded test data and actual observable output.
- **Negative path:** simulate *narx almashgan paytdagi eski quote* and *manfiy narx*; unauthorized write does not commit, user gets next step.
- **Rules checked:** `BL-015`, `BL-016`, `BL-017`, `BL-018`.
- **Integration check:** affected collaborator(s) `M04`, `M08`, `M10` reflect the new state without exposing private fields.
- **Metric:** measure false price incidence, quote acceptance on known fixture; zero silent mismatches.

### UAT-M06 — Ombor, kirim-chiqim va rezerv

- **Happy path:** authorized `Warehouse, Manager, Owner` performs: *filial-SKU fizik qoldiq*; expected data/status `available / reserved / allocated / sold / returned-damaged`, appropriate UI `Stock list` visible; event/audit recorded.
- **Additional functional coverage:** verify *kirim/chiqim ledger; stock adjustment sababi; qisqa muddatli reservation* with concrete seeded test data and actual observable output.
- **Negative path:** simulate *ikki parallel rezerv* and *nol stok*; unauthorized write does not commit, user gets next step.
- **Rules checked:** `BL-019`, `BL-020`, `BL-021`, `BL-022`, `BL-023`.
- **Integration check:** affected collaborator(s) `M03`, `M04`, `M12` reflect the new state without exposing private fields.
- **Metric:** measure oversell=0, inventory discrepancies on known fixture; zero silent mismatches.

### UAT-M07 — Brendlangan mini-sayt va storefront

- **Happy path:** authorized `Owner, Customer` performs: *subdomain va brand theme*; expected data/status `preview→published→maintenance→disabled`, appropriate UI `Storefront builder` visible; event/audit recorded.
- **Additional functional coverage:** verify *responsive katalog/qidiruv/filtr; mahsulot detail va availability; savatcha yoki quote request* with concrete seeded test data and actual observable output.
- **Negative path:** simulate *subdomain conflict* and *unpublished product havolasi*; unauthorized write does not commit, user gets next step.
- **Rules checked:** `BL-024`, `BL-025`, `BL-026`.
- **Integration check:** affected collaborator(s) `M01`, `M04`, `M05` reflect the new state without exposing private fields.
- **Metric:** measure storefront qualified leads, conversions on known fixture; zero silent mismatches.

### UAT-M08 — PC configurator va compatibility

- **Happy path:** authorized `Buyer, Sales, AI, Manager` performs: *ready PC builds*; expected data/status `draft→compatible / review_required / incompatible→quote_ready`, appropriate UI `PC Builder` visible; event/audit recorded.
- **Additional functional coverage:** verify *CPU socket, board chipset/BIOS review; RAM DDR/form factor; GPU length/case clearance* with concrete seeded test data and actual observable output.
- **Negative path:** simulate *unknown BIOS* and *aniq o‘lcham yo‘q*; unauthorized write does not commit, user gets next step.
- **Rules checked:** `BL-027`, `BL-028`, `BL-029`, `BL-030`.
- **Integration check:** affected collaborator(s) `M04`, `M05`, `M06` reflect the new state without exposing private fields.
- **Metric:** measure incompatible quote=0, review_required% on known fixture; zero silent mismatches.

### UAT-M09 — Kanallar va kanal hisoblarini ulash

- **Happy path:** authorized `Owner, Manager` performs: *Telegram bot / Business bog‘lash*; expected data/status `pending→connected→degraded→disconnected/revoked`, appropriate UI `Channel connect wizard` visible; event/audit recorded.
- **Additional functional coverage:** verify *web widget joylashtirish; Meta professional account ruxsatiga tayyor adapter; OAuth/token rotate/revoke* with concrete seeded test data and actual observable output.
- **Negative path:** simulate *provider ruxsat bermaydi* and *token muddati tugaydi*; unauthorized write does not commit, user gets next step.
- **Rules checked:** `BL-031`, `BL-032`, `BL-033`.
- **Integration check:** affected collaborator(s) `M01`, `M02`, `M10` reflect the new state without exposing private fields.
- **Metric:** measure connected channels, delivery failure rate on known fixture; zero silent mismatches.

### UAT-M10 — Unified Inbox, conversation va human handoff

- **Happy path:** authorized `Sales, Manager, AI` performs: *inbound normalization/dedup*; expected data/status `new→ai_active→waiting_customer→human_needed→human_active→resolved→reopened`, appropriate UI `Unified inbox` visible; event/audit recorded.
- **Additional functional coverage:** verify *thread va customer identity linking; AI/on hold/manual mode; assign/escalate/transfer* with concrete seeded test data and actual observable output.
- **Negative path:** simulate *takrorlangan xabar* and *out-of-order kelgan xabar*; unauthorized write does not commit, user gets next step.
- **Rules checked:** `BL-034`, `BL-035`, `BL-036`, `BL-037`.
- **Integration check:** affected collaborator(s) `M02`, `M09`, `M11` reflect the new state without exposing private fields.
- **Metric:** measure first response, open backlog, takeover rate on known fixture; zero silent mismatches.

### UAT-M11 — AI Sales Agent va product discovery

- **Happy path:** authorized `Customer, AI, Sales` performs: *uz/ru/en niyat va tilni aniqlash*; expected data/status `idle→qualifying→recommending→quote_requested / handed_off / stopped`, appropriate UI `AI agent config` visible; event/audit recorded.
- **Additional functional coverage:** verify *budget/attributes/need clarify; catalog-only search tools; photo, variant, stock va price explain* with concrete seeded test data and actual observable output.
- **Negative path:** simulate *LLM hallucinated SKU* and *provider outage*; unauthorized write does not commit, user gets next step.
- **Rules checked:** `BL-038`, `BL-039`, `BL-040`, `BL-041`.
- **Integration check:** affected collaborator(s) `M04`, `M05`, `M06` reflect the new state without exposing private fields.
- **Metric:** measure grounded-answer rate, escalation rate, cost/lead on known fixture; zero silent mismatches.

### UAT-M12 — Lead, CRM va quotation

- **Happy path:** authorized `Sales, Manager, AI limited` performs: *lead dedup va source attribution*; expected data/status `lead: new→qualified→quoted→won/lost; quote: draft→review→approved→sent→accepted/expired/rejected`, appropriate UI `Lead pipeline` visible; event/audit recorded.
- **Additional functional coverage:** verify *qualification (budget, spec, phone consent); priority/owner/follow-up; PC quotation snapshot* with concrete seeded test data and actual observable output.
- **Negative path:** simulate *operator forgot lead* and *quote price changed*; unauthorized write does not commit, user gets next step.
- **Rules checked:** `BL-042`, `BL-043`, `BL-044`, `BL-045`.
- **Integration check:** affected collaborator(s) `M05`, `M08`, `M10` reflect the new state without exposing private fields.
- **Metric:** measure qualified lead rate, quote-to-order on known fixture; zero silent mismatches.

### UAT-M13 — Buyurtma va order lifecycle

- **Happy path:** authorized `Customer, Sales, Manager` performs: *cart/quote to order*; expected data/status `draft→pending_confirmation→confirmed→processing→completed/cancelled`, appropriate UI `Order list` visible; event/audit recorded.
- **Additional functional coverage:** verify *merchant order number; customer contact+pickup/shipping; reserve / confirm* with concrete seeded test data and actual observable output.
- **Negative path:** simulate *parallel confirm* and *buyurtma bekor bo‘lganidan keyin payment*; unauthorized write does not commit, user gets next step.
- **Rules checked:** `BL-046`, `BL-047`, `BL-048`, `BL-049`.
- **Integration check:** affected collaborator(s) `M06`, `M12`, `M14` reflect the new state without exposing private fields.
- **Metric:** measure order accuracy, cancellations on known fixture; zero silent mismatches.

### UAT-M14 — To‘lov va chekni tekshirish

- **Happy path:** authorized `Customer, Cashier, Manager` performs: *pay link yoki merchant rekvizitlari*; expected data/status `initiated→awaiting_confirmation→verified/failed/cancelled; refund pending→approved→completed/failed`, appropriate UI `Payments list` visible; event/audit recorded.
- **Additional functional coverage:** verify *manual proof upload; admin verifies settlement; provider callback adapter* with concrete seeded test data and actual observable output.
- **Negative path:** simulate *screenshot forged* and *webhook replay*; unauthorized write does not commit, user gets next step.
- **Rules checked:** `BL-050`, `BL-051`, `BL-052`, `BL-053`.
- **Integration check:** affected collaborator(s) `M02`, `M06`, `M13` reflect the new state without exposing private fields.
- **Metric:** measure payment mismatch, false paid=0 on known fixture; zero silent mismatches.

### UAT-M15 — Yetkazish va pickup

- **Happy path:** authorized `Manager, Courier, Customer` performs: *pickup vs local delivery*; expected data/status `pending→ready→assigned→in_transit→delivered; exception→rescheduled/returned`, appropriate UI `Fulfillment board` visible; event/audit recorded.
- **Additional functional coverage:** verify *courier assignment; address confirmation; ETA only verified estimates* with concrete seeded test data and actual observable output.
- **Negative path:** simulate *noto‘g‘ri address* and *courier not assigned*; unauthorized write does not commit, user gets next step.
- **Rules checked:** `BL-054`, `BL-055`, `BL-056`.
- **Integration check:** affected collaborator(s) `M03`, `M13`, `M17` reflect the new state without exposing private fields.
- **Metric:** measure delivered %, exception age on known fixture; zero silent mismatches.

### UAT-M16 — Sotuvdan keyingi xizmat va kafolat

- **Happy path:** authorized `Customer, Support, Manager` performs: *warranty terms snapshot*; expected data/status `new→review→approved/rejected→in_service→resolved/closed`, appropriate UI `Support inbox` visible; event/audit recorded.
- **Additional functional coverage:** verify *RMA/support ticket; return eligibility review; exchange/repair/refund request* with concrete seeded test data and actual observable output.
- **Negative path:** simulate *warranty ambiguous* and *used product sold as new*; unauthorized write does not commit, user gets next step.
- **Rules checked:** `BL-057`, `BL-058`, `BL-059`.
- **Integration check:** affected collaborator(s) `M13`, `M14`, `M15` reflect the new state without exposing private fields.
- **Metric:** measure resolution time, repeat complaints on known fixture; zero silent mismatches.

### UAT-M17 — Notifications, automation va merchant tasks

- **Happy path:** authorized `Owner, Sales, Courier, Customer` performs: *notification template va locale*; expected data/status `pending→scheduled→sent/failed/suppressed`, appropriate UI `Notification center` visible; event/audit recorded.
- **Additional functional coverage:** verify *order/payment/escalation triggers; in-app/Telegram/email adapter; reminder due dates* with concrete seeded test data and actual observable output.
- **Negative path:** simulate *takror notification* and *provider unavailable*; unauthorized write does not commit, user gets next step.
- **Rules checked:** `BL-060`, `BL-061`, `BL-062`.
- **Integration check:** affected collaborator(s) `M09`, `M10`, `M12` reflect the new state without exposing private fields.
- **Metric:** measure missed SLA tasks, delivery success on known fixture; zero silent mismatches.

### UAT-M18 — Dashboard, hisobot va Voice Business Copilot

- **Happy path:** authorized `Owner, Manager, Analyst` performs: *KPI: orders/paid turnover/margin only if COGS exists*; expected data/status `requested→running→completed/partial/failed`, appropriate UI `Overview dashboard` visible; event/audit recorded.
- **Additional functional coverage:** verify *period/branch/channel comparisons; saved reports+export; uz/ru/en voice STT→intent→typed metric query→TTS* with concrete seeded test data and actual observable output.
- **Negative path:** simulate *ASR currency mistake* and *missing COGS*; unauthorized write does not commit, user gets next step.
- **Rules checked:** `BL-063`, `BL-064`, `BL-065`, `BL-066`.
- **Integration check:** affected collaborator(s) `M02`, `M10`, `M12` reflect the new state without exposing private fields.
- **Metric:** measure metric reconciliation, answer groundedness on known fixture; zero silent mismatches.

### UAT-M19 — Merchant AI controls, billing va platform operations

- **Happy path:** authorized `Owner, Platform Admin` performs: *AI enable/disable/policy*; expected data/status `trial→active→past_due→restricted→cancelled`, appropriate UI `Plan/usage` visible; event/audit recorded.
- **Additional functional coverage:** verify *usage limits and soft stop; subscription lifecycle; seat/channel/SKU quotas* with concrete seeded test data and actual observable output.
- **Negative path:** simulate *over-quota conversation* and *downgrade active order*; unauthorized write does not commit, user gets next step.
- **Rules checked:** `BL-067`, `BL-068`, `BL-069`, `BL-070`.
- **Integration check:** affected collaborator(s) `M01`, `M02`, `M09` reflect the new state without exposing private fields.
- **Metric:** measure gross margin/tenant, active merchants on known fixture; zero silent mismatches.

### UAT-M20 — Activity log va biznes audit

- **Happy path:** authorized `Owner, Auditor, Platform Support limited` performs: *who/when/why/change trace*; expected data/status `recorded→retained→expired by policy`, appropriate UI `Audit search` visible; event/audit recorded.
- **Additional functional coverage:** verify *before-after safe diffs; read views by role; tamper-evident append only* with concrete seeded test data and actual observable output.
- **Negative path:** simulate *logga PII tushishi* and *audit yozilmasdan state mutatsiya*; unauthorized write does not commit, user gets next step.
- **Rules checked:** `BL-071`, `BL-072`.
- **Integration check:** affected collaborator(s) `M01`, `M02`, `M05` reflect the new state without exposing private fields.
- **Metric:** measure unaudited critical mutations=0 on known fixture; zero silent mismatches.

### UAT-M21 — Self-service merchant provisioning

- **Happy path:** authorized `Prospective Owner, Platform Admin` performs: *public signup and anti-fraud*; expected data/status `registered→verified→provisioned→ready/blocked`, appropriate UI `Public signup` visible; event/audit recorded.
- **Additional functional coverage:** verify *automated workspace/subdomain; self-serve plan purchase; guided catalog import* with concrete seeded test data and actual observable output.
- **Negative path:** simulate *fraud signup* and *subdomain conflict*; unauthorized write does not commit, user gets next step.
- **Rules checked:** `BL-001`, `BL-003`, `BL-067`.
- **Integration check:** affected collaborator(s) `M01`, `M07`, `M19` reflect the new state without exposing private fields.
- **Metric:** measure time to live merchant on known fixture; zero silent mismatches.

### UAT-M22 — Integration hub / POS / ERP / marketplaces

- **Happy path:** authorized `Owner, Integrator` performs: *connector registry and credentials*; expected data/status `draft→authorized→syncing→healthy/degraded→revoked`, appropriate UI `Integration catalog` visible; event/audit recorded.
- **Additional functional coverage:** verify *field mapping & dry run; incremental sync; source priority and conflict policy* with concrete seeded test data and actual observable output.
- **Negative path:** simulate *API credentials revoked* and *data overwrite*; unauthorized write does not commit, user gets next step.
- **Rules checked:** `BL-073`, `BL-074`, `BL-075`.
- **Integration check:** affected collaborator(s) `M04`, `M05`, `M06` reflect the new state without exposing private fields.
- **Metric:** measure sync freshness, data conflicts on known fixture; zero silent mismatches.

### UAT-M23 — Global canonical product registry

- **Happy path:** authorized `Catalog Operator, Merchant, AI assist` performs: *brand/model/MPN/GTIN normalize*; expected data/status `unmatched→candidate→reviewed→matched/rejected`, appropriate UI `Global product review` visible; event/audit recorded.
- **Additional functional coverage:** verify *variant and condition differentiation; matching confidence and evidence; review queue* with concrete seeded test data and actual observable output.
- **Negative path:** simulate *false merge* and *GTIN collision*; unauthorized write does not commit, user gets next step.
- **Rules checked:** `BL-076`, `BL-077`, `BL-078`.
- **Integration check:** affected collaborator(s) `M04`, `M22`, `M24` reflect the new state without exposing private fields.
- **Metric:** measure precision, false merge rate on known fixture; zero silent mismatches.

### UAT-M24 — Merchant public offers va opt-in

- **Happy path:** authorized `Owner, Manager` performs: *per-SKU public opt-in/out*; expected data/status `private→pending_validation→published→stale/hidden/withdrawn`, appropriate UI `Public listings settings` visible; event/audit recorded.
- **Additional functional coverage:** verify *public price/availability/warranty terms; offer version+freshness; branch visibility settings* with concrete seeded test data and actual observable output.
- **Negative path:** simulate *merchant revokes permission* and *missing warranty*; unauthorized write does not commit, user gets next step.
- **Rules checked:** `BL-079`, `BL-080`, `BL-081`.
- **Integration check:** affected collaborator(s) `M05`, `M06`, `M23` reflect the new state without exposing private fields.
- **Metric:** measure valid public offers, takedown lag on known fixture; zero silent mismatches.

### UAT-M25 — Multi-branch inventory and fulfillment intelligence

- **Happy path:** authorized `Owner, Warehouse, Manager` performs: *branch stock splits*; expected data/status `transfer: draft→approved→in_transit→received/cancelled`, appropriate UI `Branch stock matrix` visible; event/audit recorded.
- **Additional functional coverage:** verify *transfer requisitions; warehouse→branch movement; replenishment suggestions* with concrete seeded test data and actual observable output.
- **Negative path:** simulate *transfer and reservation collide* and *in transit vanished*; unauthorized write does not commit, user gets next step.
- **Rules checked:** `BL-019`, `BL-021`, `BL-082`.
- **Integration check:** affected collaborator(s) `M03`, `M06`, `M15` reflect the new state without exposing private fields.
- **Metric:** measure transfer delay, pick success on known fixture; zero silent mismatches.

### UAT-M26 — Merchant tenancy at scale va subscription automation

- **Happy path:** authorized `Platform Admin, Owner` performs: *plan self-service changes*; expected data/status `active→grace_period→limited→restored/terminated`, appropriate UI `Billing console` visible; event/audit recorded.
- **Additional functional coverage:** verify *quota calculation; usage invoice; merchant health scoring* with concrete seeded test data and actual observable output.
- **Negative path:** simulate *billing webhook replay* and *quota race*; unauthorized write does not commit, user gets next step.
- **Rules checked:** `BL-067`, `BL-068`, `BL-083`.
- **Integration check:** affected collaborator(s) `M19`, `M21`, `M22` reflect the new state without exposing private fields.
- **Metric:** measure merchant retention, unit cost on known fixture; zero silent mismatches.

### UAT-M27 — Merchant-facing AI policy/knowledge center

- **Happy path:** authorized `Owner, Manager, AI Operator` performs: *FAQ/returns/warranty knowledge*; expected data/status `draft→review→approved→published→rolled_back`, appropriate UI `Knowledge hub` visible; event/audit recorded.
- **Additional functional coverage:** verify *source revision approval; tone/language setting; AI answer preview* with concrete seeded test data and actual observable output.
- **Negative path:** simulate *policy contradicts merchant terms* and *owner accidentally enables unsafe tool*; unauthorized write does not commit, user gets next step.
- **Rules checked:** `BL-038`, `BL-039`, `BL-084`.
- **Integration check:** affected collaborator(s) `M10`, `M11`, `M16` reflect the new state without exposing private fields.
- **Metric:** measure verified response coverage on known fixture; zero silent mismatches.

### UAT-M28 — Search index publishing and catalog data quality

- **Happy path:** authorized `Catalog Operator, Platform Admin` performs: *incremental index from public offers*; expected data/status `pending_index→indexed→stale→hidden/reindexed`, appropriate UI `Index health` visible; event/audit recorded.
- **Additional functional coverage:** verify *freshness SLA; denormalization without sensitive fields; stale suppression* with concrete seeded test data and actual observable output.
- **Negative path:** simulate *lost event* and *out-of-order price update*; unauthorized write does not commit, user gets next step.
- **Rules checked:** `BL-080`, `BL-085`, `BL-086`.
- **Integration check:** affected collaborator(s) `M23`, `M24`, `M29` reflect the new state without exposing private fields.
- **Metric:** measure index age, withdrawn visibility=0 on known fixture; zero silent mismatches.

### UAT-M29 — Merchant quality, verification and trust data

- **Happy path:** authorized `Platform Verification, Owner` performs: *merchant business verification*; expected data/status `unverified→in_review→verified/rejected/expired`, appropriate UI `Trust center` visible; event/audit recorded.
- **Additional functional coverage:** verify *branch ownership proof; trust attributes as evidence; complaint review* with concrete seeded test data and actual observable output.
- **Negative path:** simulate *fake business document* and *false negative complaint*; unauthorized write does not commit, user gets next step.
- **Rules checked:** `BL-087`, `BL-088`.
- **Integration check:** affected collaborator(s) `M01`, `M03`, `M16` reflect the new state without exposing private fields.
- **Metric:** measure verification coverage, fraud reports on known fixture; zero silent mismatches.

### UAT-M30 — Partner API va merchant developer access

- **Happy path:** authorized `Owner, Developer, Platform Admin` performs: *API key/service account with scopes*; expected data/status `requested→active→limited/revoked`, appropriate UI `Developer settings` visible; event/audit recorded.
- **Additional functional coverage:** verify *webhook subscriptions; idempotency contract; usage and rate dashboards* with concrete seeded test data and actual observable output.
- **Negative path:** simulate *leaked key* and *cross-tenant integration*; unauthorized write does not commit, user gets next step.
- **Rules checked:** `BL-005`, `BL-074`, `BL-089`.
- **Integration check:** affected collaborator(s) `M02`, `M22`, `M26` reflect the new state without exposing private fields.
- **Metric:** measure API errors, key rotation age on known fixture; zero silent mismatches.

### UAT-M31 — Global search and filters

- **Happy path:** authorized `Visitor, Buyer` performs: *query uz/ru/en/translit*; expected data/status `query→results/no_results/degraded`, appropriate UI `Global home/search` visible; event/audit recorded.
- **Additional functional coverage:** verify *category/brand/condition filters; canonical product result; public offer availability* with concrete seeded test data and actual observable output.
- **Negative path:** simulate *query ambiguity* and *incorrect product merge*; unauthorized write does not commit, user gets next step.
- **Rules checked:** `BL-090`, `BL-091`.
- **Integration check:** affected collaborator(s) `M23`, `M24`, `M28` reflect the new state without exposing private fields.
- **Metric:** measure search success, query latency on known fixture; zero silent mismatches.

### UAT-M32 — Cross-store price comparison

- **Happy path:** authorized `Buyer, Visitor` performs: *same variant normalization*; expected data/status `available→stale/excluded; report: new→verified→closed`, appropriate UI `Compare table` visible; event/audit recorded.
- **Additional functional coverage:** verify *item price+delivery total; warranty/condition/stock columns; last verified timestamp* with concrete seeded test data and actual observable output.
- **Negative path:** simulate *comparison variant mismatch* and *unavailable shipping quote*; unauthorized write does not commit, user gets next step.
- **Rules checked:** `BL-092`, `BL-093`, `BL-094`.
- **Integration check:** affected collaborator(s) `M23`, `M24`, `M28` reflect the new state without exposing private fields.
- **Metric:** measure valid comparisons, wrong-price reports on known fixture; zero silent mismatches.

### UAT-M33 — Geo search, near-me va maps

- **Happy path:** authorized `Buyer, Visitor` performs: *city and neighborhood query*; expected data/status `unknown→location_allowed/denied; branch pickup: available/unavailable`, appropriate UI `Map + list` visible; event/audit recorded.
- **Additional functional coverage:** verify *voluntary precise location; distance from validated branches; pickup availability* with concrete seeded test data and actual observable output.
- **Negative path:** simulate *precise location denied* and *merchant coordinate invalid*; unauthorized write does not commit, user gets next step.
- **Rules checked:** `BL-095`, `BL-096`.
- **Integration check:** affected collaborator(s) `M03`, `M24`, `M31` reflect the new state without exposing private fields.
- **Metric:** measure map-to-store actions on known fixture; zero silent mismatches.

### UAT-M34 — Global AI Shopping Advisor

- **Happy path:** authorized `Buyer, Global AI` performs: *intent and budget clarifying*; expected data/status `understanding→searching→comparing→answered/clarify/handoff`, appropriate UI `AI search chat` visible; event/audit recorded.
- **Additional functional coverage:** verify *tool-based public search; criteria explainability; top candidates with provenance* with concrete seeded test data and actual observable output.
- **Negative path:** simulate *LLM recommends private SKU* and *no evidence for quality*; unauthorized write does not commit, user gets next step.
- **Rules checked:** `BL-097`, `BL-098`, `BL-099`.
- **Integration check:** affected collaborator(s) `M23`, `M24`, `M31` reflect the new state without exposing private fields.
- **Metric:** measure grounded ranking %, conversion assist on known fixture; zero silent mismatches.

### UAT-M35 — Merchant discovery and referral tracking

- **Happy path:** authorized `Buyer, Merchant, Platform` performs: *merchant profile and offers*; expected data/status `created→delivered→acknowledged→converted/lost/expired`, appropriate UI `Merchant page` visible; event/audit recorded.
- **Additional functional coverage:** verify *click-to-chat/storefront; lead handoff with consent; referral attribution token* with concrete seeded test data and actual observable output.
- **Negative path:** simulate *merchant ignores referral* and *spam repeated lead*; unauthorized write does not commit, user gets next step.
- **Rules checked:** `BL-100`, `BL-101`.
- **Integration check:** affected collaborator(s) `M10`, `M12`, `M24` reflect the new state without exposing private fields.
- **Metric:** measure referral-to-response / sale on known fixture; zero silent mismatches.

### UAT-M36 — Buyer account, saved products and alerts

- **Happy path:** authorized `Buyer` performs: *guest browsing*; expected data/status `watch: active→triggered/expired/cancelled`, appropriate UI `Saved items` visible; event/audit recorded.
- **Additional functional coverage:** verify *optional account; saved comparisons and offers; price-drop notification opt-in* with concrete seeded test data and actual observable output.
- **Negative path:** simulate *price changed but out of stock* and *notification repeated*; unauthorized write does not commit, user gets next step.
- **Rules checked:** `BL-102`, `BL-103`.
- **Integration check:** affected collaborator(s) `M17`, `M31`, `M32` reflect the new state without exposing private fields.
- **Metric:** measure saved-to-return, unsubscribe rate on known fixture; zero silent mismatches.

### UAT-M37 — Organic vs sponsored ranking and transparency

- **Happy path:** authorized `Platform Admin, Buyer, Merchant` performs: *organic ranking relevance rules*; expected data/status `eligible→ranked/filtered; ad approved/rejected`, appropriate UI `Search placements` visible; event/audit recorded.
- **Additional functional coverage:** verify *sponsored slots only with label; ad targeting boundaries; seller disclosure* with concrete seeded test data and actual observable output.
- **Negative path:** simulate *seller pays to fake quality* and *unverified sponsorship*; unauthorized write does not commit, user gets next step.
- **Rules checked:** `BL-104`, `BL-105`.
- **Integration check:** affected collaborator(s) `M24`, `M29`, `M31` reflect the new state without exposing private fields.
- **Metric:** measure buyer trust signals, complaint rate on known fixture; zero silent mismatches.

### UAT-M38 — Global content, SEO and shareable landing pages

- **Happy path:** authorized `Visitor, Platform Content` performs: *canonical product public pages*; expected data/status `draft→indexable→noindex/retired`, appropriate UI `Product landing` visible; event/audit recorded.
- **Additional functional coverage:** verify *structured product/offer markup when valid; public seller detail; indexation hygiene and canonical URLs* with concrete seeded test data and actual observable output.
- **Negative path:** simulate *thin duplicate pages* and *unverified price markup*; unauthorized write does not commit, user gets next step.
- **Rules checked:** `BL-106`, `BL-107`.
- **Integration check:** affected collaborator(s) `M23`, `M24`, `M28` reflect the new state without exposing private fields.
- **Metric:** measure organic qualified traffic on known fixture; zero silent mismatches.

### UAT-M39 — Global Telegram bot and discovery API

- **Happy path:** authorized `Buyer, Global Bot` performs: *global query in Telegram*; expected data/status `idle→searching→results→handoff`, appropriate UI `Global bot` visible; event/audit recorded.
- **Additional functional coverage:** verify *product results in cards; store price deep-links; saved search opt-in* with concrete seeded test data and actual observable output.
- **Negative path:** simulate *merchant AI leaks private data* and *user chat linked across sellers*; unauthorized write does not commit, user gets next step.
- **Rules checked:** `BL-098`, `BL-100`, `BL-108`.
- **Integration check:** affected collaborator(s) `M09`, `M24`, `M31` reflect the new state without exposing private fields.
- **Metric:** measure bot-to-merchant referrals on known fixture; zero silent mismatches.

## High-severity end-to-end and adversarial checks

| Test ID | Given / trigger | Expected invariant / observed result |
|---|---|---|
| `TC-001` | Merchant A token reads merchant B catalog/orders | Denied, zero leaked fields incl error messages |
| `TC-002` | Two concurrent requests reserve last unit | Exactly one valid active reservation, available nonnegative |
| `TC-003` | Duplicate confirmed-order POST | One order id, no second stock hold |
| `TC-004` | Payment proof photo only | Not verified/paid; finance task |
| `TC-005` | Genuine payment callback 3x/out-of-order | Payment verified exactly once; no duplicate notification/fulfillment |
| `TC-006` | Cancelled order then late payment | Exception case + audit + refund/reorder decision, no silent paid/delivered |
| `TC-007` | AI quotes absent SKU or price | Refuses fabricated detail; operator handoff |
| `TC-008` | Unknown BIOS support in PC build | REVIEW_REQUIRED; cannot publish compatible quote |
| `TC-009` | Human takes over while AI composing | No AI outgoing after human took send authority |
| `TC-010` | Telegram/Meta webhook replay | One inbound event, one logical conversation update |
| `TC-011` | Provider/token revoked mid send | Channel degraded, job task, no false sent status |
| `TC-012` | Owner UZ speech 15 vs 50 million unclear | Correctable transcript, no numeric answer/command from uncertain input |
| `TC-013` | Sales user requests margin/COGS via voice | Denied, safe response, audited |
| `TC-014` | Owner asks paid turnover, no paid orders | Correct 0 and period, not fabricated result |
| `TC-015` | Merchant opts out public offer while index delayed | No public visibility at read gate; eventual index cleanup |
| `TC-016` | Product match RTX5060 8GB vs RTX5060 Ti | Candidate split / manual review, no false same-product comparison |
| `TC-017` | Compare one merchant missing delivery fee | Cannot label exact «cheapest delivered» |
| `TC-018` | Global buyer AI prompt injection asks other merchant CRM | Tool denied; only public result |
| `TC-019` | POS sends old inventory snapshot after newer manual change | No blind overwrite; conflict/reconcile |
| `TC-020` | Return damaged hardware | Quarantine, stock not saleable until inspection |
| `TC-021` | Refund request repeated after provider response timeout | No double refund; reconcile by provider transaction id |
| `TC-022` | Worker dies after event published before ack | Consumer dedup/replay, no duplicate side effect |
| `TC-023` | Merchant terminated while active customer orders | New leads disabled; old order resolution and privacy retention allowed |
| `TC-024` | Platform sponsored result appears as organic #1 | Label required; neutral AI recommendation unaffected |
| `TC-025` | Owner removes staff privileges mid-session | Old session/permission no longer authorizes protected action |
| `TC-026` | Global offer points to branch now closed | Hide pickup or show unavailable, no invented open-now |

## Stage exit / go-no-go

### Stage 1 acceptance
- At least one merchant can complete full catalog → AI/inbox → quote → reservation/order → settlement review → fulfillment → KPI flow on staging/production pilot with rollback procedure.
- All critical `TC-001..TC-014`, `TC-020..TC-023`, `TC-025` pass on release candidate; other phased tests follow their module readiness.
- Merchant and AI mode independent; no LLM outage can mutate incorrect business state.
- Production operators can reconcile payments, retry failed jobs, and disable unsafe AI/channel features.

### Stage 2 acceptance
- Three independent merchants can self-serve under isolation; same canonical product linked to distinct merchant offers; public opt-out is honored instantly at read boundary.
- Sync backlog, mapping errors, false merge review and tenant billing accuracy observable.
- All `TC-015`, `TC-016`, `TC-019`, `TC-022`, `TC-023` pass.

### Stage 3 acceptance
- Buyer searches multiple merchants, sees explicit last-verified time, condition, warranty and known total costs; cannot access private merchant data.
- Global AI recommendation cites public evidence and never infers unverified quality. Referral data only consented.
- All `TC-017`, `TC-018`, `TC-024`, `TC-026` pass; price comparison correctness monitored.

## Formal sign-off worksheet (not pre-checked)

| Gate | Reviewer | Requirement | Status |
|---|---|---|---|
| Business scope | Founder | 3 stages/first ICP/quotes/payment semantics approved | `PENDING` |
| Business FSM | Founder + implementer | Every critical state/abort/recover flow reviewed | `PENDING` |
| Privacy/legal | Qualified reviewer | Live chat, audio, payments, published offers lawful | `PENDING` |
| Integrations | Engineering | Provider approvals/sandbox tests verified | `PENDING` |
| Technical design | Engineering | DDD boundaries, ERD, OpenAPI, outbox and races designed | `PENDING` |
| UAT | Product/engineering | Critical TC cases passed with logs | `PENDING` |
| Pilot | Merchant + founder | Measured baseline and merchant acceptance | `PENDING` |
