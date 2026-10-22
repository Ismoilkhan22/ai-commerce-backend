# TECH-06 — Database ERD, schema and lifecycle

**Status:** v1 design draft, NOT deployed DDL. **Primary:** PostgreSQL; SQLAlchemy2 async + Alembic. **Contexts:** C01–C19. **Phase:** normalized Stage 1 tables; Stage 2/3 future-schema *non-migrated* appendix. **Decision refs:** ADR-002/003/004/018.

## 1. Data ownership and invariants
Every merchant-owned record has `merchant_id`, `created_at timestamptz`, and usually `version bigint`; FK should be composite `(merchant_id, parent_id)` where supported to prevent cross-merchant associations. Never reuse row IDs as public tokens. Never expose cost, supplier price, PII or margin in Stage 3.

| Domain | Aggregate / important tables | Owner | Critical invariant |
|---|---|---|---|
| Identity C01 | users, merchant_memberships, role_assignments, sessions | access | active membership for merchant context |
| Merchant C02 | merchants, branches, delivery_regions, policies | merchant | branch in merchant |
| Catalog C03 | merchant_products, sku_variants, product_media, sku_attributes | catalog | unique `(merchant_id,sku_code)` |
| Pricing C04 | price_lists, sku_prices, price_revisions, discount_rules | pricing | amount nonnegative; approved revision |
| Inventory C05 | stock_balances, stock_ledger, reservations, stock_receipts | inventory | physical-reserved-allocated >=0 when sellable |
| Storefront C06 | storefront_settings, pages, published_sku_snapshots | storefront | only approved public merchant listing |
| PC C07 | pc_builds, pc_build_items, pc_rulesets, validations | pc builder | critical rule BLOCK prevents quote |
| Messaging C08 | channel_accounts, provider_events, conversations, messages, handoff_tasks | messaging | unique provider event + speaker lease |
| AI C09 | agent_profiles, prompt_versions, tool_call_logs, ai_usage | ai | no direct money/stock write |
| CRM C10 | leads, quotes, quote_revisions, quote_lines | crm | sent revision immutable |
| Orders C11 | orders, order_lines, order_status_history | orders | committed snapshots; unique order token |
| Payments C12 | payment_intents, payment_attempts, payment_evidence, verified_transactions | payments | proof != verification |
| Fulfillment C13 | shipments, pickup_requests, returns, warranty_cases | fulfill | shipment != order payment |
| Engagement C14 | notification_intents, notifications, templates | notifications | idempotent intent |
| Reporting C15 | metric_definitions, daily_aggregates, report_jobs | reporting | approved definitions, source watermarks |
| Platform C16 | subscriptions, usage_ledgers, audit_entries, outbox_messages, jobs, consumed_events | platform/infra | append-only audit, durable delivery |
| Integrations C17 | connections, external_id_maps, sync_runs, sync_conflicts | integration | source precedence |
| Registry C18 (S2) | canonical_products, product_matches, public_offers, publish_versions | registry | opt-in and reversible matches |
| Discovery C19 (S3) | search_documents, referrals, saved_searches, ad_placements | discovery | public allowlist only |

## 2. Concept ERD (Stage 1)
```mermaid
erDiagram
 MERCHANTS ||--o{ BRANCHES : owns
 MERCHANTS ||--o{ MERCHANT_MEMBERSHIPS : grants
 USERS ||--o{ MERCHANT_MEMBERSHIPS : holds
 MERCHANTS ||--o{ SKU_VARIANTS : catalogs
 SKU_VARIANTS ||--o{ SKU_PRICES : priced
 SKU_VARIANTS ||--o{ STOCK_BALANCES : stocked
 BRANCHES ||--o{ STOCK_BALANCES : located
 STOCK_BALANCES ||--o{ STOCK_RESERVATIONS : reserved
 MERCHANTS ||--o{ CONVERSATIONS : routes
 CONVERSATIONS ||--o{ MESSAGES : contains
 CONVERSATIONS ||--o{ LEADS : qualifies
 LEADS ||--o{ QUOTES : requests
 QUOTES ||--o{ QUOTE_REVISIONS : snapshots
 QUOTE_REVISIONS ||--o{ QUOTE_LINES : contains
 MERCHANTS ||--o{ ORDERS : receives
 ORDERS ||--o{ ORDER_LINES : contains
 ORDERS ||--o{ PAYMENT_ATTEMPTS : settles
 ORDERS ||--o{ SHIPMENTS : fulfills
 MERCHANTS ||--o{ OUTBOX_MESSAGES : publishes
```

## 3. Implementable DDL examples — Stage 1 subset
Schemas below illustrate **minimum** invariants, NOT complete migration. All production tables get audited Alembic migrations and proper tenant FKs.

```sql
CREATE TABLE stock_balances (
  merchant_id uuid NOT NULL,
  branch_id uuid NOT NULL,
  sku_id uuid NOT NULL,
  physical_qty integer NOT NULL DEFAULT 0 CHECK (physical_qty >= 0),
  reserved_qty integer NOT NULL DEFAULT 0 CHECK (reserved_qty >= 0),
  allocated_qty integer NOT NULL DEFAULT 0 CHECK (allocated_qty >= 0),
  version bigint NOT NULL DEFAULT 1,
  PRIMARY KEY (merchant_id, branch_id, sku_id),
  CHECK (physical_qty >= reserved_qty + allocated_qty)
);
CREATE TABLE stock_reservations (
  id uuid PRIMARY KEY,
  merchant_id uuid NOT NULL,
  order_id uuid NOT NULL,
  branch_id uuid NOT NULL,
  sku_id uuid NOT NULL,
  qty integer NOT NULL CHECK(qty > 0),
  status text NOT NULL CHECK(status IN ('ACTIVE','CONSUMED','RELEASED','EXPIRED')),
  expires_at timestamptz NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (merchant_id, order_id, branch_id, sku_id)
);
CREATE TABLE outbox_messages (
  id uuid PRIMARY KEY,
  merchant_id uuid,
  event_type text NOT NULL,
  aggregate_type text NOT NULL,
  aggregate_id uuid NOT NULL,
  aggregate_version bigint NOT NULL,
  payload jsonb NOT NULL,
  traceparent text,
  created_at timestamptz NOT NULL DEFAULT now(),
  claimed_until timestamptz,
  published_at timestamptz,
  attempt_count integer NOT NULL DEFAULT 0
);
CREATE INDEX outbox_due_idx ON outbox_messages (created_at, id)
  WHERE published_at IS NULL;
CREATE TABLE consumer_receipts (
  consumer_name text NOT NULL,
  event_id uuid NOT NULL,
  applied_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (consumer_name,event_id)
);
```
**Gap requiring review:** `stock_balances` must reference tenant-scoped branch and SKU via composite FKs, and reservation references must be tenant-composite. Stock transfers require separate `stock_ledger` double-entry movement records rather than direct quantity edits.

## 4. Monetary model, pricing versioning
- `money_minor bigint`, `currency_code char(3)` and currency exponent metadata; all calculations in integer/Decimal, no float. UZS rounding policy explicit per merchant. Snapshot unit price, discount, currency, tax treatment, optional FX version at quote approval.
- `price_revisions` immutable; `sku_prices` pointer/current. `quote_revisions` immutable once sent. Quote acceptance revalidates same/version/expiry or returns `PRICE_CHANGED` and requires explicit reconfirmation.
- Dedup external payment by `(provider, provider_merchant_id, external_transaction_id) UNIQUE` and merchant-scoped verified transaction link. Ledger separate from attempts.

## 5. Indexes, retention and query patterns
| Query | Index recommendation | Guard |
|---|---|---|
| Inbox newest | `(merchant_id,updated_at DESC,id DESC)` | cursor pagination |
| Orders by state | `(merchant_id,status,created_at DESC)` | tenant authorization |
| Provider webhook dedup | `(provider,channel_account_id,provider_event_id) UNIQUE` | canonical normalized IDs |
| Find active reservation due | partial `(expires_at)` WHERE status='ACTIVE' | SKIP LOCKED batch |
| SKU local lookup | `(merchant_id, sku_code) UNIQUE` | normalized SKU code |
| Public offers (Stage 2) | `(canonical_product_id, published, last_verified_at)` | opt-in and revocation overlay |
| Event rebuild | `(aggregate_type,aggregate_id,aggregate_version)` | version/ordering |

- Sensitive conversations/audio: explicit retention policy and deletion/export flow; design GDPR-like minimization without claiming particular law applies. Backups have expiry and documented deletion limitations.
- Outbox/consumed receipts: partition/TTL after sufficient replay horizon and consumer offset reconciliation. Archive audit separately with tamper checks.
- Migrations: expand → dual-read/write where needed → backfill (idempotent batches) → contract; rollback plan for each incompatible change.

## 6. Tenant scoping and public projection
`merchant_id` is extracted from authenticated membership and set on UoW context. RLS optional only after tested isolation. Public catalog is **separate projection**: merchant can opt-in, restrict SKUs, revoke instantly in read path even when search index lags. Do not JOIN private stock ledger in anonymous API.

## 7. Stage 2/3 evolution — do not migrate on day one
```mermaid
erDiagram
 CANONICAL_PRODUCTS ||--o{ PRODUCT_MATCHES : mapped
 SKU_VARIANTS ||--o{ PRODUCT_MATCHES : matched
 MERCHANTS ||--o{ PUBLIC_OFFERS : publishes
 CANONICAL_PRODUCTS ||--o{ PUBLIC_OFFERS : compares
 PUBLIC_OFFERS ||--o{ REFERRALS : originates
```
- Canonical product identity includes model, exact variant, capacity, condition, manufacturer evidence and `match_confidence/status`; false merge undo must be supported.
- Publication keeps `merchant_id, sku_id, branch/location, revision, allowed_fields, status, revoked_at`; price/stock timestamp prominent; public ranking cannot override truth.

## 8. Verification / hard edge cases
`TC-DB-01`: cross-tenant FK insert rejected; `TC-DB-02`: 2 simultaneous final-SKU reservations → exactly one success; `TC-DB-03`: duplicate payment callback → one verified transaction; `TC-DB-04`: old price revision cannot overwrite newer; `TC-DB-05`: rollback emits no outbox; `TC-DB-06`: create merchant then teardown leaves no leaked public row; `TC-DB-07`: migration rollback/backfill tested on snapshot.

## 9. Open questions
Precise SKU dimensions per vertical, physical-vs-supplier stock, reservation TTL, booking policy, payment reconciliation source, retention periods, RLS proof. Track as decisions, never assume production approval.
