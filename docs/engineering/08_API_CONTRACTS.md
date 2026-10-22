# TECH-08 — REST / WebSocket API contract design

**Status:** Baseline contracts (2026-10-22: ADR-023/024/025, K-01/K-02/K-06/K-07); FastAPI router specs for Stage 1. **Authority:** TECH-03 DDD context owners, TECH-06 schema, TECH-07 safety, BL rules. **Next artifact from code:** committed OpenAPI `openapi-v1.json` generated in CI; TypeScript SDK regeneration is mandatory.

## General transport rules
- Base `/api/v1` + surface prefix (ADR-024); JSON UTF-8; snake_case fields; enum qiymatlari `UPPER_SNAKE` (K-02); ISO-8601 timezone-aware UTC instants; currency as `{amount_minor, currency}` never float (ADR-025: UZS exponent 2).
- Staff: access JWT `Authorization: Bearer` (10–15 daq) + refresh token httpOnly cookie, `/auth/refresh` (ADR-023); scoped signed capability token for public quote/order tracking; webhook signature auth for provider.
- `traceparent` accepted for correlation only when valid; generated `X-Request-ID` echo; `Idempotency-Key` (K-06) required on all externally retryable POST mutations.
- PATCH with `If-Match` revision on price, stock adjustments, conversation claim, policy; stale state yields `409 VERSION_CONFLICT`.
- Cursor pagination and stable sort; no unsafe offset for messages/events; API never trusts client-provided `merchant_id` as authority.
- Nonstandard long operations → `202 Accepted {job_id,status_url}`; cancellation defined per job; no LLM call in webhook ACK path.

## Endpoint inventory (indicative; freeze via OpenAPI)

**Surface prefikslari (ADR-024, DEC-006):** har surface o'z auth middleware'i va rate limit'iga ega.

| Surface | Prefix | Auth |
|---|---|---|
| Staff (dashboard) | `/api/v1/merchant/*` | access JWT + membership + permission (ADR-023) |
| Do'kon sayti (public) | `/api/v1/storefront/{slug}/*` | public + rate limit; buyurtma kuzatuvi — scoped signed token |
| Provayder webhook'lari | `/api/v1/webhooks/{provider}/{account_ref}` | provider signature, durable ACK |
| Platforma jamoasi | `/api/v1/platform/*` | platform role + MFA, reason-coded audit |
| Auth | `/api/v1/auth/*` | login/refresh/logout |
| Stage 3 global | `/api/v1/public/*` | public, faqat public offers |

| Area/context | Endpoint (prefiksdan keyin) | Action | Permission / guarantee |
|---|---|---|---|
| Auth/C01 | `POST /auth/login`, `/auth/refresh`, `/auth/logout` | session lifecycle | refresh rotation, revocation, throttling |
| Merchant/C02 | `GET/PATCH /merchant/profile`, `GET/POST /merchant/branches` | settings, branches | `merchant.settings.*` |
| Staff/C01 | `GET /merchant/members`, `POST /merchant/members/invites`, `PATCH /merchant/members/{id}` | rollar (bitta xodimga bir nechta) | `members.manage` |
| Policy/C16 | `GET/PATCH /merchant/policies` | quote TTL, discount limits, reminder hours, quote approval mode | `merchant.policy.write` (Owner) |
| Catalog/C03 | `GET/POST /merchant/products`, `POST /merchant/products/import-jobs` | products/import | `catalog.write`; 202 import |
| Pricing/C04 | `GET/PUT /merchant/skus/{id}/price`, `GET/POST /merchant/exchange-rates` | approved revision (UZS/USD), kurs | If-Match; audit |
| Stock/C05 | `GET /merchant/stock`, `POST /merchant/stock/receipts`, `POST /merchant/stock/adjustments`, `POST /merchant/stock/quick-sales` | ledger movement; "tez sotuv" (DEC-123) | `stock.*`, `stock.quick_sale`; idempotent |
| PC/C07 | `POST /merchant/pc-builds/evaluate`, `POST /merchant/pc-builds/quotes`, `GET /merchant/hardware-specs?query=` | validate/build; reference spec qidiruvi | no quote on `BLOCK` |
| Specs/C07 | `POST /platform/hardware-specs`, `PATCH /platform/hardware-specs/{id}`; `POST /merchant/hardware-spec-requests` | spec kutubxonasi (DEC-120) | platform role; merchant so'rovi |
| Channels/C08 | `GET /merchant/channels`, `POST /merchant/channels/{provider}/connect` | Telegram, Instagram (DEC-116) | Owner; OAuth flow |
| Webhooks/C08 | `POST /webhooks/{provider}/{account_ref}` | ingress | signature, event dedup, durable ACK |
| Inbox/C08 | `GET /merchant/conversations`, `GET /merchant/conversations/{id}/messages` | transcript | authorized staff |
| Inbox/C08 | `POST /merchant/conversations/{id}/takeover`, `/resume-ai`, `/assign`, `/reply` | speaker claim | `speaker_version` CAS |
| Leads/C10 | `GET/POST /merchant/leads`, `PATCH /merchant/leads/{id}` | pipeline | sales |
| Quotes/C10 | `POST /merchant/quotes`, `POST /merchant/quotes/{id}/submit`, `/approve`, `/send` | faqat PC (DEC-100e) | `quotes.approve` — Manager/Owner (DEC-109) |
| Orders/C11 | `GET/POST /merchant/orders` (DRAFT), `POST /merchant/orders/{id}/submit`, `/confirm`, `/start-processing`, `/complete`, `/cancel`, `/notes`, `/paid-mark` | FSM-08 (DEC-100) | `orders.confirm` (Sales — o'ziga biriktirilgan / Manager), `orders.cancel` (Manager/Owner), workflow UoW (ADR-021) |
| Storefront/C06 | `GET /storefront/{slug}/products`, `GET /storefront/{slug}/products/{product_slug}`, `POST /storefront/{slug}/order-requests`, `GET /storefront/{slug}/quotes/{token}`, `GET /storefront/{slug}/orders/{tracking_token}` | katalog, buyurtma so'rovi (to'lovsiz, DEC-115), PC taklif, kuzatuv | public + rate limit; no private joins |
| Support/C13 | `GET/POST /merchant/support-cases`, `PATCH /merchant/support-cases/{id}` | kafolat murojaati (DEC-114, S5) | support/manager |
| Reports/C15 | `GET /merchant/reports/summary`, `POST /merchant/reports/queries`, `POST /merchant/reports/export-jobs` | approved metrics; matnli hisobot-chat (DEC-112) | role + 202 export |
| Voice/C15 (beta) | `POST /merchant/voice/transcriptions` → tahrirlanadigan transcript; `POST /merchant/voice/queries` (tasdiqlangan transcript) | 2 bosqich: avval matnni tasdiqlash, keyin so'rov | feature flag; audio transkripsiyadan keyin o'chiriladi (DEC-117) |
| Payments/C12 | `POST /merchant/orders/{id}/payment-proof`, `POST /merchant/payments/{id}/review` | — | **`DEFERRED` (DEC-100)** — `FEATURE_NOT_AVAILABLE` |
| Shipment/C13 | `GET /merchant/shipments`, `POST /merchant/shipments/{id}/transition` | — | **`DEFERRED` (DEC-113)** |
| Stage2/C18 | `PUT /merchant/public-offers/{sku_id}`, `DELETE /merchant/public-offers/{id}` | opt-in/out | public deny immediately |
| Stage3/C19 | `GET /public/search`, `GET /public/compare/{canonical_id}` | public | freshness + disclosures |

## Key payloads and error contracts
```json
{
  "request": "POST /api/v1/merchant/orders/{id}/confirm  (Idempotency-Key, If-Match: 3)",
  "response": {"order_id":"uuid","status":"CONFIRMED","fulfillment_method":"PICKUP","reservation_status":"ACTIVE","version":4,"reservation_review_at":"2026-10-25T14:00:00Z","paid_mark":null}
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
**Error envelope (K-07):** `{"error":{"code","message","details","trace_id"}}` — barcha surface va barcha xatolar uchun (FastAPI validation va 404/405 ham shu formatga o'giriladi). To'liq konvensiya va i18n — `API_CONVENTIONS_ERRORS_I18N.md` (yoziladi).

| Code | HTTP | Qachon |
|---|---|---|
| `VALIDATION_FAILED` | 422 | Pydantic/field validation; `details.fields[] = {field, code, params}` |
| `INVALID_REQUEST` | 400 | noto'g'ri format, header yo'q (masalan `Idempotency-Key`) |
| `UNAUTHENTICATED` | 401 | token yo'q/eskirgan |
| `FORBIDDEN` | 403 | ruxsat yo'q (o'z tenantida) |
| `NOT_FOUND` | 404 | resurs yo'q yoki boshqa tenantniki (cross-tenant uchun doim 404) |
| `VERSION_CONFLICT` | 409 | `If-Match`/version mos emas |
| `IDEMPOTENCY_KEY_REUSED` | 409 | bir xil key, boshqa payload |
| `INSUFFICIENT_AVAILABLE_STOCK` | 409 | confirm / quick-sale paytida stok yetarli emas |
| `PRICE_CHANGED` | 409 | narx snapshot'dan farq qiladi — xaridordan qayta rozilik |
| `QUOTE_EXPIRED` | 409 | quote muddati o'tgan |
| `INVALID_STATE_TRANSITION` | 409 | FSM'da ruxsat etilmagan o'tish |
| `RULE_BLOCK` | 422 | PC compatibility `BLOCK` yoki biznes qoida |
| `DISCOUNT_LIMIT_EXCEEDED` | 422 | rol limitidan katta chegirma (DEC-110) |
| `RATE_LIMITED` | 429 | `Retry-After` bilan |
| `FEATURE_NOT_AVAILABLE` | 501 | `DEFERRED` modul yoki o'chirilgan feature flag |
| `PROVIDER_UNAVAILABLE` | 503 | LLM/Telegram/Meta ishlamayapti |
| `INTERNAL_ERROR` | 500 | kutilmagan xato; `trace_id` bilan, ichki tafsilot oshkor qilinmaydi |

Client never infers business state from HTTP code alone; `code` — barqaror, frontend uni tarjima kalitiga map qiladi.

## WebSocket messages
`/ws/v1/inbox?ticket=short_lived`, validate membership at connect and on rebinding; event payload `{type, merchant_conversation_id, last_sequence, payload, trace_id}`. Client fetches gaps from REST after reconnect (not WS as sole truth). Broadcast tenant+branch authorization, not raw merchant-wide pub/sub with missing scope.

## OpenAPI governance
- Contract-first interfaces: backend generator is authoritative. Pin schema artifact with commit SHA in frontend; incompatible diff CI fails until frontend regenerated and e2e tests pass.
- Breaking field removal requires `/v2` or deprecation window; enums include unknown fallback in UI, no silent reinterpretation.
- Standard `X-Request-ID`, `traceparent`, `Idempotency-Key` appear as reusable components. Rate limit/permission metadata and example 409 for each write.
- Public API production docs must not expose privileged internal operations, tokens or merchant private identifiers.

## Contract cases
`TC-API-01`: unauthorized cross-tenant ID returns safe 404 without data; `02` replay same idem request returns same result; `03` same key+different payload returns conflict; `04` expired quote, `05` concurrent price change, `06` WS gap recovery, `07` 202 worker + status polling, `08` role matrix; generate mock server for frontend before implementation.

## Out-of-scope until provider approval
No promise of Instagram bulk auto-DM, payments capture (Stage 1 — DEC-100) or external POS write. Instagram Direct — Stage 1 kanali (DEC-116), faqat Meta rasmiy ruxsati bilan. Endpoint may exist behind flags but must return explicit `FEATURE_NOT_AVAILABLE` if unconfigured.
