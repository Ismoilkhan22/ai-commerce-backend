# TECH-18 — Frontend architecture, page contracts and UX states

**Status:** baseline (2026-10-22: DEC-014 / ADR-010 — ikki Next.js app tasdiqlangan; DEC-008 / ADR-023 — auth); implementation order after TECH-08 OpenAPI and business flow source. **Repo:** `ai-commerce-frontend`, one pnpm workspace, two Next.js apps (`merchant-dashboard`, `merchant-storefront`), shared UI/API client. Stage 3 public shopping app later.

## 1. Repo skeleton
```text
ai-commerce-frontend/
  apps/
    merchant-dashboard/          # authenticated merchant operations
      src/app/(auth)/login/
      src/app/(workspace)/overview/
      src/app/(workspace)/inbox/
      src/app/(workspace)/catalog/
      src/app/(workspace)/stock/
      src/app/(workspace)/pc-builder/
      src/app/(workspace)/quotes/
      src/app/(workspace)/orders/
      # payments/, fulfillment/ — DEFERRED (DEC-100, DEC-113)
      src/app/(workspace)/reports/
      src/app/(workspace)/voice/
      src/app/(workspace)/settings/
    merchant-storefront/         # public merchant site, SEO/mobile-first
      src/app/[merchantSlug]/
      src/app/[merchantSlug]/products/[slug]/
      src/app/[merchantSlug]/cart/
      src/app/[merchantSlug]/quote/[token]/
      src/app/[merchantSlug]/track/[token]/
  packages/
    ui/                           # tokens, accessible components
    api-client/                   # generated from backend OpenAPI, NEVER manual duplication
    domain-types/                 # derived API enums, render mappers
    auth/                         # session client, route permissions
    i18n/                         # uz/ru/en
    analytics/                    # typed event logger
  e2e/                            # Playwright
  tooling/                        # lint/typecheck/CI
```
These are workspace folders, **not separate repositories**. Storefront multi-tenant routing must derive merchant by validated hostname/slug lookup; never trust arbitrary Host header without proxy allowlist and domain verification.

## 2. Frontend technology and ownership
Next.js + TypeScript strict, Tailwind+accessible component library (implementation vendor flexible), TanStack Query for server state, small Zustand for local ephemeral UI only, React Hook Form+Zod, Recharts/ECharts reporting if data needs justify. Component permissions are UX optimization, not access control; API enforces role. Strong cache invalidation after mutations; financial data no unsafe offline optimistic updates.

## 3. Navigation/IA per role
| Page | Role(s) | Primary queries | Mutations | Error/empty critical states |
|---|---|---|---|---|
| Overview | owner/manager | KPIs, integration health | date filters | missing data, stale aggregates |
| Inbox | sales/manager | chat pages, sender, speaker lease | assign, handoff, send | disconnected WS, 409 takeover |
| Catalog | catalog staff | product/variants/photos | create/import/publish | invalid SKU, upload errors |
| Inventory | warehouse/owner/sales | branch balance/ledger | receipt/adjust, "tez sotuv" (DEC-123, mobil ham) | outdated version, insufficient qty |
| PC Builder | sales/customer | parts, ruleset, variants | evaluate/build draft | incompatible/unknown parts |
| Quotes | sales/manager | quote revision/provenance | create/approve/send | price expired, approval denied |
| Orders | owner/manager/sales | FSM-08 status, fulfillment method, manzil, kelishuv izohi, rezerv, "to'landi" belgisi | confirm (assigned Sales/Manager), start processing, complete, cancel (Manager/Owner), notes, paid-mark | duplicate/idempotent, stock conflict (409), narx o'zgargan |
| Finance — DEFERRED (DEC-100) | finance/owner | proof, transactions | manual verify | fake proof, settlement unknown |
| Fulfillment — DEFERRED (DEC-113) | courier/manager | shipment state | dispatch/mark delivered | invalid status, missing proof |
| Voice | owner/approved roles | transcript, metric results | read query jobs | low confidence, TTS unavailable |
| Settings | owner | merchant, branch, members, plans, integration auth | config | provider revoked, missing consent |

## 4. Seven vital UI workflows
```mermaid
flowchart LR
 A[Merchant sign in] --> B[Onboarding + branch]
 B --> C[Import/approve catalog]
 C --> D[Storefront preview/publish]
 D --> E[Connect Telegram / Instagram / web chat]
 E --> F[Customer request → AI/Human inbox]
 F --> G[Quote → approval → Order]
 G --> H[AI DRAFT → operator → confirm + rezerv → topshirish (to'lovsiz)]
 H --> I[Reporting / Voice]
```
1. **Onboard**: choose trial/merchant, verified membership, create first branch, add catalog sample, preview public site, channel setup.
2. **Catalog import**: upload → parsed preview → validation mapping → draft list → user approve → publish; show row error report; job progress polling.
3. **Chat**: message arrival, AI typing/proposal, operator claim, handoff reason, channel health, no double-send on stale speaker version.
4. **Quote**: buyer budget, PC build compatibility PASS/REVIEW/BLOCK, quote revision, approval, send channel/link, expiry state.
5. **Order** (DEC-100): AI yoki saytdan `DRAFT` → operator kelishadi (chat/telefon, izoh) → `CONFIRMED` (stok qulf bilan tekshiriladi, rezerv) → `PROCESSING` → `COMPLETED`; narx o'zgargan bo'lsa xaridordan qayta rozilik; to'lov va yetkazish tizimdan tashqarida, ixtiyoriy "to'landi" belgisi.
6. **Stock**: branch selected, available/physical/reserved/allocated visibly distinct, adjustment requires reason and permission, ledger audit link.
7. **Voice**: press-to-talk → visible language/transcript correction → query processing → KPI+units/data_as_of → optional localized TTS.

## 5. Example inbox wireframe (text)
```text
┌──── Merchant / Branch ─────────── Search | Profile ──────────┐
│ NAV  Overview Inbox Catalog Stock Quotes Orders Reports       │
├───────────────┬────────────────────────┬──────────────────────┤
│ Conversations │ Customer thread        │ Lead / Offer / State │
│ filters/status│ Bot/human speaker badge│ budget, source       │
│ unseen count  │ AI draft + provenance  │ price_version        │
│ retry badges  │ timeline & attachments │ assigned user        │
│               │ reply / claim / handoff│ quote / order links  │
├───────────────┴────────────────────────┴──────────────────────┤
│ disconnected WS? → REST sync; permission/409 via visible toast│
└───────────────────────────────────────────────────────────────┘
```

## 6. Universal screen state model
For every page/field: `initial_loading`, `empty`, `ready`, `pending_mutation`, `success`, `validation_error`, `not_authorized`, `version_conflict`, `provider_unavailable`, `offline/reconnect`, `stale_read_model`. UI must show actionable remedy: refresh, ask manager, retry safe job, handoff, reconnect. **Never silently retry a charge, stock adjustment or confirmation under new idempotency key.**

## 7. Frontend security, analytics and accessibility
Auth — ADR-023 (access token xotirada, refresh httpOnly cookie, localStorage'da token yo'q), CSP, sanitized user-uploaded text, signed media proxy, no provider secret or AI key in browser; `merchant_id` always from server membership. Analytics events privacy-safe with `feature_id`, role tier, funnel stage, no phone/raw chat text. Mobile responsive merchant dashboard, keyboard accessible dialogs, reduced motion, UI copy uz/ru/en, RTL not a baseline requirement. Owner voice supports explicit microphone permission and visible recording indicator.

## 8. Component contract & test expectations
UI stories for stock conflict, wrong price, active handoff, payment unverified, refunded, TTS failed, disconnected provider, public offer revoked. Frontend contract mocks autogenerated from TECH-08; any OpenAPI change regenerates types in CI. Playwright scenario E2E targets Stage1 merchant→catalog→chat→quote→order, plus negative permission tests and keyboard navigation.

## 9. Stage 2/3 extension
Stage2 self-service billing and public-offer opt-in wizard. Stage3 separate `shopping-web` app (search, compare, map, merchant offer, referral) sharing UI/client but **never** sharing merchant privileged auth context. SEO crawlable public pages, truthful price last verified. Do not build this app in initial MVP unless Stage2 data is available.
