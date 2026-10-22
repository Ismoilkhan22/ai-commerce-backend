# 11 — BUSINESS DECISIONS, ASSUMPTIONS, RISK AND FUTURE EXTENSIONS

**Version:** v1.0 | **Goal:** Klonlash yoki implementatsiya paytida qabul qilingan defaultlarni tekshirilgan fakt bilan chalkashtirmaslik.

## A. Qabul qilingan dizayn prinsiplari (biznes baseline)

| ID | Decision | Why | Revision trigger |
|---|---|---|---|
| `BD-01` | **Exactly 3 core stages** Merchant OS → Network → Global AI Shopping | ROI first, later network effect | Genuine demand makes extensions separate product |
| `BD-02` | Start PC/electronics, generic commerce core + PC addon | Deep consultative selling pain | Pilot shows other vertical cheaper to serve |
| `BD-03` | Merchant owns customer relation and storefront | Independent merchants more willing to adopt | Negotiated platform checkout model |
| `BD-04` | Global offer listing opt-in by default private | Protect merchant confidence and data | Explicit policy, not forced by subscription |
| `BD-05` | Merchant AI vs Global buyer AI separate | Conflicting incentives and privacy scopes | Never merge private/public boundaries |
| `BD-06` | Price/stock/compatibility/payment deterministic | Costly mistakes from hallucination | Never relax invariant |
| `BD-07` | Voice Copilot read-only first | Speech misrecognition is risky | Full command approval workflow tested |
| `BD-08` | Payment routed to merchant. **Stage 1: to'lov tizimdan tashqarida, do'kon o'zi oladi** (DEC-100, 2026-10-22) | Simpler settlement and legal scope | Formal licensed gateway integration ready |
| `BD-09` | **Telegram + Instagram + web chat birga Stage 1 da** (DEC-116); Meta arizasi S0 bilan; no unofficial scraping | Instagram-first do'konlarga mos | Meta ruxsati pilot sanasiga kelmasa (DEC-116a) |
| `BD-10` | Sell SaaS value before global search has traffic | Avoid two-sided marketplace cold start | Verified global traffic can support referral pricing |
| `BD-11` | Separate backend/frontend repos, infra within backend for solo founder | Simplicity; deployment remains reproducible | Independent infra lifecycle/DevOps emerges |
| `BD-12` | DDD-inspired modular monolith candidate | Complexity bounded; clear ownership | ADR review with capacity facts |

**Bu BDlar biznes qarorlari.** Framework / RabbitMQ vs Redis / PostgreSQL isolation / C4 / transaction propagation uchun formal technical ADR keyin ishlab chiqiladi.

## B. Open items — code start oldidan qiymat belgilanadigan parametrlar

> **2026-10-22:** quyidagi savollar `../decisions/DECISION_REGISTER.md` ga ko'chirildi va founder tomonidan baseline sifatida hal qilindi (xaritasi — registr §4). Bu jadval tarix uchun saqlanadi; amaldagi qiymatlar registrda.

| Ref | Unconfirmed decision | Safe temporary policy | Who validates |
|---|---|---|---|
| `O-01` | PC merchantda eng ko‘p qiynaladigan sales step | AI inbox + quote demo, no conversion guarantee | Founder + merchant |
| `O-02` | Reserve TTL, cancellation windows | Merchant policy required; no guessed default | Owner + founder |
| `O-03` | Price validity / discount cap | Human approval when uncertain | Merchant owner |
| `O-04` | Stock source of truth POS vs dashboard | Explicit priority per field; conflict manual | Integration owner |
| `O-05` | Manual payment review proof | External settlement matched by finance | Merchant finance |
| `O-06` | Fulfillment rules and delivery partners | Merchant-controlled pickup/delivery statuses | Merchant owner |
| `O-07` | Return/warranty and fiscal obligations | Captured per merchant; no automatic rule invention | Merchant/legal reviewer |
| `O-08` | Voice ASR quality by language/accent | Read-only beta with transcript correction | ML eval & real users |
| `O-09` | Official Instagram/Meta / WhatsApp permissions | Feature flag off until verified | Platform integration owner |
| `O-10` | Public offer freshness policy | Hide/warn stale; merchant config | Merchant + network owner |
| `O-11` | Consent, privacy, retention local law | Minimize data and get compliance review | Legal reviewer |
| `O-12` | Sponsored/referral revenue scheme | Disabled until buyer traffic proven | Founder |
| `O-13` | Shopper ranking weights and warranty quality evidence | Evidence only, transparent neutral organic ranking | Product owner |
| `O-14` | Cross-channel identity merge | Per merchant only, explicit consent | Merchant/buyer |
| `O-15` | Unit economics of model calls, support, server and payments | Daily cost/tenant tracking from first pilot | Founder |

## C. High-impact risks and controls

| Risk | Likelihood initially | Impact | Minimum control |
|---|---|---|---|
| Incorrect PC compatibility | Medium | Critical | Deterministic rules, REVIEW when unknown, human approval |
| Oversold SKU | Medium | Critical | Atomic reservation/version, ledger and concurrency UAT |
| Fake payment receipt | High | Critical | Never screenshot auto-paid; provider/settlement verify |
| Wrong price AI answers | Medium | Critical | Catalog-only tool; last price version, review expired |
| Meta access withheld | Medium | Medium | Launch web/Telegram first, permission gate |
| Tenant privacy leak | Low tolerance | Critical | Default-deny scope, negative tests and audit |
| High LLM cost/merchant | Medium | High | Quotas, cost per lead/order, fallback, disable switch |
| False global match | High without review | High | Variant evidence, precision-focused review and rollback |
| Stale offer public | High at scale | High | Opt-out read-time block, freshness, index reconciliation |
| No merchant traction | Unknown | Critical business | Paid pilot value measurements, start single niche |
| External provider outage | Medium | High | Durable outbox, retries, operator fallback |
| Voice number transcription error | High risk UZ code mix | High | Transcript confirmation, metric revalidation, no write |

## D. Explicit OUT OF CURRENT THREE STAGES (extension candidates)

- Agro/Farmers: produce grades, kg/ton, perishability, cold chain, seasonal pricing, farmer verification, wholesale procurement.
- Global payment custody, split settlement, platform-wide buyer protection, complete disputes resolution and shipping insurance.
- Cross-border marketplace, localized tax/fiscal integration per country, currency settlements.
- Full AI marketing video/content generation and sentiment listening as separate opt-in merchant upsells.
- Supplier wholesale procurement, marketplace financing, multi-warehouse 3PL, highly sophisticated demand forecasting.

**Extension policy:** new domain may reuse Merchant, Offer, Catalog and Pricing identifiers, but specialized quantity/status/legal rules require an independent business annex. Never generalize PC physical-stock invariants to perishable goods without design review.

## E. Founder approval record

- `Scope baseline`: BUSINESS DRAFT REVIEW PENDING.
- `Pricing/monetization`: candidate only, no confirmed customer willingness-to-pay claim.
- `Regulatory/integration`: external verification required before live activation.
- `Engineering`: no claim of production-ready code, end-to-end integration, load-test or provider approval.
