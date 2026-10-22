# TECH-22 — Development implementation roadmap, repo skeleton, task breakdown

**Status:** executable work plan, not finished code. **Execution:** founder + AI coding assistant. **Do not develop all Stage2/3 up front.** Specs anchored TECH-03–TECH-21.

## 1. Repos and source layout
```text
ai-commerce-backend/
  pyproject.toml
  alembic/
  app/
    main.py
    bootstrap.py              # DI composition root
    shared/
      kernel/                  # IDs, money, result/errors, Clock, UoW protocol
      security/                # principal/context/policies
      db/                      # async engine, session,UoW, migrations
      tracing/                 # OTel middleware, log correlation
      jobs/                    # outbox, worker leases, scheduler
    contexts/
      identity/{domain,application,infrastructure,presentation}/
      merchant/{domain,application,infrastructure,presentation}/
      catalog/{domain,application,infrastructure,presentation}/
      pricing/{domain,application,infrastructure,presentation}/
      inventory/{domain,application,infrastructure,presentation}/
      storefront/{domain,application,infrastructure,presentation}/
      pc_builder/{domain,application,infrastructure,presentation}/
      messaging/{domain,application,infrastructure,presentation}/
      ai_sales/{domain,application,infrastructure,presentation}/
      crm_quotes/{domain,application,infrastructure,presentation}/
      orders/{domain,application,infrastructure,presentation}/
      payments/{domain,application,infrastructure,presentation}/
      fulfillment/{domain,application,infrastructure,presentation}/
      notifications/{domain,application,infrastructure,presentation}/
      reporting/{domain,application,infrastructure,presentation}/
      platform/{domain,application,infrastructure,presentation}/
      integrations/{domain,application,infrastructure,presentation}/ # S2
      registry/{domain,application,infrastructure,presentation}/     # S2
      discovery/{domain,application,infrastructure,presentation}/    # S3
    entrypoints/{api,worker,scheduler}/
  tests/{unit,integration,contract,e2e,concurrency,security,ai_eval}/
  infra/{docker,nginx,monitoring,backup,scripts}/
  docs/{architecture,adr,runbooks,openapi}/

ai-commerce-frontend/
  apps/{merchant-dashboard,merchant-storefront}/
  packages/{ui,api-client,domain-types,i18n,auth,analytics}/
  e2e/
```
Folders for S2/S3 are planning-only; don't scaffold dozens of empty contexts initially. `shared/kernel` MUST NOT grow into business god module. One application use-case can coordinate C11+C05 synchronously through owned ports+UoW; actual import boundary architecture test mandatory.

## 2. S0 — foundation tasks
| ID | Task | Dependency | Acceptance |
|---|---|---|---|
| S0-01 | Python/uv/poetry project, typed lint/test, CI | approved ADRs | reproducible setup and precommit |
| S0-02 | FastAPI bootstrap/config/dependency graph | S0-01 | health, readiness, typed errors |
| S0-03 | Postgres async UoW, Alembic | S0-02 | rollback, pool tests |
| S0-04 | Identity, merchant membership, branch RBAC | S0-03 | cross tenant tests |
| S0-05 | request/trace middleware, JSON logs, OTel | S0-02 | API→job trace correlation |
| S0-06 | PG jobs+outbox lease/worker/dedup | S0-03 | restart/crash replay test |
| S0-07 | frontend two Next apps, auth shell, generated client | S0-02 OpenAPI | role-aware 401/403 UX |
| S0-08 | infra Docker, staging secrets, backup restore | S0-03 | smoke + restore rehearsal |

## 3. S1 — Merchant catalog/site
| ID | Task | Acceptance |
|---|---|---|
| S1-01 | Merchant/branch setup UI and policies | owner can create store and branch, validation |
| S1-02 | SKU/variant attributes, media upload, prices/version | atomic edits, uniqueness, audit |
| S1-03 | Branch stock ledger/receipt/adjustment | available vs physical reserved; concurrency tests |
| S1-04 | CSV/XLSX import validation as resumable job | dry-run, row errors, no memory blowup |
| S1-05 | Branded subdomain, catalog & product public pages | no unpublished SKU, SEO, cache freshness |

## 4. S2 — channels + conversation
| ID | Task | Acceptance |
|---|---|---|
| S2-01 | Web widget inbound events and conversation model | durable inbox, mapped visitor |
| S2-02 | Telegram bot adapter, official webhook auth | signature/secret, duplicate retry test |
| S2-03 | Conversation inbox, status, assign/handoff | speaker CAS, WS reconnect |
| S2-04 | Outbound message intent, provider delivery tracking | retry/ambiguous send visible |
| S2-05 | Meta adapter P0 only after approved permissions | blocked flag until approved |

## 5. S3 — AI + PC + quote
| ID | Task | Acceptance |
|---|---|---|
| S3-01 | AI model provider abstraction, budgets and tool broker | forbidden mutation impossible |
| S3-02 | Catalog hybrid retrieval+merchant knowledge policies | exact SKU/price grounded |
| S3-03 | Deterministic PC rules with evidence and REVIEW | wrong socket blocked, unknown escalated |
| S3-04 | Lead capture, quote versions and approvals | immutable sent snapshot, expiry |
| S3-05 | 3-language agent evaluation and shadow tests | eval+cost pass/AI kill switch |

## 6. S4 — order/payment/delivery
| ID | Task | Acceptance |
|---|---|---|
| S4-01 | Atomic order+multi-SKU reserve and expiry | two final-unit buyers no oversell |
| S4-02 | Payment proof/manual finance workflow | proof never paid without settlement |
| S4-03 | Payment gateway adapter if provider approved | sandbox reconciliation and idempotency |
| S4-04 | Shipment/pickup FSM and tracking link | courier scope, proof of delivery |
| S4-05 | Order cancel/return/refund review | compensation no double refund/release |

## 7. S5 — reports/voice/billing/reliability
| ID | Task | Acceptance |
|---|---|---|
| S5-01 | Metric registry and merchant summary dashboard | reconciled paid/refund totals |
| S5-02 | Voice STT→metric tool→TTS read-only | 3 languages eval, transcript correction |
| S5-03 | Pilot usage metering/quotas/plan switch | AI cost bounded by merchant |
| S5-04 | alerts, runbooks, backup restore and load tests | SLO measurement and recovery proof |
| S5-05 | paid pilot readiness review | founder signoff all critical TC |

## 8. Stage 2 follow-up (N1…)
Self-service merchant provisioning; POS/ERP connectors and source precedence; canonical product schema; match review tool; public-offer opt-in/withdraw; async index and billing/support scale. Gate by merchant adoption. **Avoid integrating all ERP systems before one authorized partner.**

## 9. Stage 3 follow-up (G1…)
Public buyer search app/SEO; geosearch, canonical comparison, AI advisor public tools, referral attribution, trust quality, organic vs sponsored differentiation. Gate by public coverage, freshness and ability to maintain truthful comparisons.

## 10. AI-assisted development handoff contract
One task per PR: include source M-ID/BL-ID, SPEC doc, exact API DTOs, affected entity/port, error conditions, concurrency/idempotency, tests, telemetry, rollback. Claude can implement, ChatGPT reviews architecture, founder runs tests/approves; do not accept code merely because generated. Required PR template:
```text
Ticket / stage:
Business rule IDs / test IDs:
Interface and schema changes:
DB migration and tenant guard:
Transactions, locks, async/outbox:
AI tool boundary/provider error:
UI: loading/empty/error/conflict:
Observability and privacy:
Unit/integration/e2e evidence:
Rollback and risk:
```

## 11. Release sequencing principle
Vertical increments produce usable paths, not detached abstract modules: `merchant→catalog→storefront→message→AI/quote→order→payment→delivery→report`. Feature flags disable unready integrations. S0–S5 labels are development slices **within Stage1**, not separate commercial stages.
