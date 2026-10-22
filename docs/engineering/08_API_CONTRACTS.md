# TECH-08 — REST / WebSocket API contract design

**Status:** PROPOSED contracts; FastAPI router specs for Stage 1. **Authority:** TECH-03 DDD context owners, TECH-06 schema, TECH-07 safety, BL rules. **Next artifact from code:** committed OpenAPI `openapi-v1.json` generated in CI; TypeScript SDK regeneration is mandatory.

## General transport rules
- Base `/api/v1`; JSON UTF-8; snake_case fields; ISO-8601 timezone-aware UTC instants; currency as `{amount_minor, currency}` never float.
- Authorization JWT/session for staff; scoped signed capability token for public quote/order tracking; webhook signature auth for provider.
- `traceparent` accepted for correlation only when valid; generated `X-Request-ID` echo; `X-Idempotency-Key` required on all externally retryable POST mutations.
- PATCH with `If-Match` revision on price, stock adjustments, conversation claim, policy; stale state yields `409 VERSION_CONFLICT`.
- Cursor pagination and stable sort; no unsafe offset for messages/events; API never trusts client-provided `merchant_id` as authority.
- Nonstandard long operations → `202 Accepted {job_id,status_url}`; cancellation defined per job; no LLM call in webhook ACK path.

## Endpoint inventory (indicative; freeze via OpenAPI)
| Area/context | Endpoint | Action | Permission / guarantee |
|---|---|---|---|
| Auth/C01 | `POST /auth/login`, `/auth/refresh`, `/auth/logout` | session lifecycle | revocation, throttling |
| Merchant/C02 | `GET/PATCH /merchant`, `GET/POST /branches` | settings, branches | owner/manager |
| Staff/C01 | `GET /members`, `POST /members/invites`, `PATCH /members/{id}` | assignments | owner / least privilege |
| Catalog/C03 | `GET/POST /products`, `POST /products/import-jobs` | products/import | catalog role; 202 import |
| Pricing/C04 | `GET/PUT /skus/{id}/price` | approved revision | If-Match; audit |
| Stock/C05 | `GET /stock`, `POST /stock/receipts`, `POST /stock/adjustments` | ledger movement | scoped, idempotent |
| PC/C07 | `POST /pc-builds/evaluate`, `POST /pc-builds/quotes` | validate/build | no quote on BLOCK |
| Channels/C08 | `GET /channels`, `POST /channels/{provider}/connect` | connect | owner; OAuth flow |
| Webhooks/C08 | `POST /webhooks/{provider}/{account_ref}` | ingress | signature, event dedup, durable ACK |
| Inbox/C08 | `GET /conversations`, `GET /conversations/{id}/messages` | transcript | authorized staff |
| Inbox/C08 | `POST /conversations/{id}/handoff`, `/assign`, `/reply` | speaker claim | version and consent |
| Leads/C10 | `GET/POST /leads`, `PATCH /leads/{id}` | pipeline | sales |
| Quotes/C10 | `POST /quotes`, `POST /quotes/{id}/approve`, `/send` | quote lifecycle | valid snapshot, approval |
| Orders/C11 | `GET/POST /orders`, `POST /orders/{id}/confirm`, `/cancel` | lifecycle | inventory UoW |
| Payments/C12 | `POST /orders/{id}/payment-proof`, `POST /payments/{id}/review` | evidence, review | finance + proof != paid |
| Shipment/C13 | `GET /shipments`, `POST /shipments/{id}/transition` | dispatch/deliver | scoped courier |
| Reports/C15 | `GET /reports/summary`, `POST /reports/export-jobs` | approved metrics | role + 202 export |
| Voice/C15 | `POST /voice/query-jobs`, `GET /voice/query-jobs/{id}` | read-only 3 language | rate limit + redaction |
| Merchant site/C06 | `GET /public/stores/{slug}/products`, `GET /public/quotes/{token}` | published data | no private joins |
| Stage2/C18 | `PUT /public-offers/{sku_id}`, `DELETE /public-offers/{id}` | opt-in/out | public deny immediately |
| Stage3/C19 | `GET /search`, `GET /compare/{canonical_id}` | public | freshness + disclosures |

## Key payloads and error contracts
```json
{
  "request": {"sku_id":"uuid", "branch_id":"uuid", "quantity":1,"quote_revision_id":"uuid"},
  "response": {"order_id":"uuid","status":"AWAITING_PAYMENT","stock_reserved":true,"version":2,"expires_at":"2026-10-21T14:00:00Z"}
}
```
```json
{
  "error": {
    "code":"INSUFFICIENT_AVAILABLE_STOCK",
    "message":"Insufficient available stock",
    "trace_id":"32-char-hex-trace",
    "details":{"sku_id":"uuid","requested":1,"available":0,"retryable":false}
  }
}
```
Error catalog `INVALID_REQUEST` 400, `UNAUTHENTICATED` 401, `FORBIDDEN` 403, `NOT_FOUND` 404 (prefer for cross-tenant), `VERSION_CONFLICT` 409, `INSUFFICIENT_AVAILABLE_STOCK` 409, `QUOTE_EXPIRED` 409, `RULE_BLOCK` 422, `RATE_LIMITED` 429, `PROVIDER_UNAVAILABLE` 503, `PAYMENT_RECONCILIATION_REQUIRED` 409; client never infers business state from HTTP code alone.

## WebSocket messages
`/ws/v1/inbox?ticket=short_lived`, validate membership at connect and on rebinding; event payload `{type, merchant_conversation_id, last_sequence, payload, trace_id}`. Client fetches gaps from REST after reconnect (not WS as sole truth). Broadcast tenant+branch authorization, not raw merchant-wide pub/sub with missing scope.

## OpenAPI governance
- Contract-first interfaces: backend generator is authoritative. Pin schema artifact with commit SHA in frontend; incompatible diff CI fails until frontend regenerated and e2e tests pass.
- Breaking field removal requires `/v2` or deprecation window; enums include unknown fallback in UI, no silent reinterpretation.
- Standard `X-Request-ID`, `traceparent`, `X-Idempotency-Key` appear as reusable components. Rate limit/permission metadata and example 409 for each write.
- Public API production docs must not expose privileged internal operations, tokens or merchant private identifiers.

## Contract cases
`TC-API-01`: unauthorized cross-tenant ID returns safe 404 without data; `02` replay same idem request returns same result; `03` same key+different payload returns conflict; `04` expired quote, `05` concurrent price change, `06` WS gap recovery, `07` 202 worker + status polling, `08` role matrix; generate mock server for frontend before implementation.

## Out-of-scope until provider approval
No promise of Instagram bulk auto-DM, payments capture or external POS write. Endpoint may exist behind flags but must return explicit `FEATURE_NOT_AVAILABLE` if unconfigured.
