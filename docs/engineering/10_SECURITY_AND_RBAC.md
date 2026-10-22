# TECH-10 — Security, tenancy, RBAC, audit and privacy

**Status:** Baseline (2026-10-22), mandatory security test gate. **References:** Business roles matrix (04 — canonical, DEC-015), TECH-05 ADR-002/003/007/023/026, TECH-06 data, TECH-08 API, TECH-23 tenant isolation. **Caution:** not legal compliance certification.

## Identity/authorization model
- User principal ≠ merchant; `membership` links user→merchant with role, status, optional branch scopes and explicit permissions. Switching current merchant revalidates membership; JWT merchant hint cannot grant access alone.
- Roles (`business/04` bilan bir xil): owner, manager, sales, warehouse, finance, analyst, catalog_editor, support, ai_policy_editor, integration_service_account, platform_support, customer; courier — `DEFERRED` (DEC-113). Role permissions are least-privilege and action-based (quyidagi katalog).
- Attribute guards: merchant scope, branch, record ownership, channel, plan capability, resource status, MFA/step-up recency, approval limit. API, background job and AI tool share same policy service.
- Platform support uses time-limited, reason-coded support grant, audited; default no access to raw merchant chats/audio. Billing staff can't inspect customer messages without scoped grant.

## Permission catalog (DEC-015: `business/04` canonical, bu yerda kodlar)

Rollar va kim nima qila olishi — `../business/04_ROLES_PERMISSIONS_AND_APPROVALS.md` (yagona manba). Bu bo'lim faqat kodda ishlatiladigan permission kodlarini beradi. Rol → permission bog'lanishi seed ma'lumotida, merchant o'zgartira olmaydi (Stage 1).

| Permission kodi | Owner | Manager | Sales | Warehouse | Finance | Analyst | Catalog Ed. | Support | AI (Sales agent) |
|---|---|---|---|---|---|---|---|---|---|
| `merchant.settings.write`, `merchant.policy.write` | ✓ | — | — | — | — | — | — | — | — |
| `members.manage` | ✓ | — | — | — | — | — | — | — | — |
| `catalog.read` | ✓ | ✓ | ✓ | ✓ | ✓ | aggregate | ✓ | ✓ | ✓ (tool) |
| `catalog.write` / `catalog.publish` | ✓/✓ | ✓/✓ | — | — | — | — | ✓/— | — | — |
| `pricing.write` | ✓ | ✓ (policy) | — | — | — | — | — | — | — |
| `discount.apply` | ✓ (cheksiz) | ✓ (≤ policy, default 5%) | so'rov (0%) | — | — | — | — | — | — |
| `stock.receive` / `stock.adjust` | ✓/✓ | ✓/approve | — | ✓/propose | — | — | — | — | — |
| `stock.quick_sale` (DEC-123) | ✓ | ✓ | ✓ | ✓ | — | — | — | — | — |
| `inbox.read` / `inbox.reply` / `inbox.takeover` | ✓ | ✓ | assigned | — | — | — | — | assigned | reply (speaker lease) |
| `leads.write` | ✓ | ✓ | assigned | — | — | — | — | — | draft |
| `quotes.create` | ✓ | ✓ | ✓ | — | — | — | — | — | draft (`quotes.prepare_draft`) |
| `quotes.approve` (DEC-109) | ✓ | ✓ (limit) | — | — | — | — | — | — | — |
| `orders.create_draft` | ✓ | ✓ | ✓ | — | — | — | — | — | ✓ (DEC-100c) |
| `orders.confirm` (DEC-108) | ✓ | ✓ | assigned | — | — | — | — | — | — |
| `orders.process` / `orders.complete` | ✓ | ✓ | assigned | ✓ (process) | — | — | — | — | — |
| `orders.cancel` | ✓ | ✓ | — | — | — | — | — | — | — |
| `orders.paid_mark` (DEC-100a) | ✓ | ✓ | assigned | — | ✓ | — | — | — | — |
| `support.cases.write` (DEC-114) | ✓ | ✓ | — | — | — | — | — | ✓ | — |
| `reports.read` / `reports.margin.read` | ✓/✓ | ✓/policy | own/— | scoped/— | ✓/policy | aggregate/approved | — | — | — |
| `agent.pause`, `agent.policy.publish` | ✓ | ✓ / — | — | — | — | — | — | — | — |
| `payments.*` — `DEFERRED` (DEC-100) | | | | | | | | | never |
| `shipments.*` — `DEFERRED` (DEC-113) | | | | | | | | | never |

`assigned` = faqat o'ziga biriktirilgan suhbat/buyurtma. `✓` is capability subject to tenant scopes and policy, not unconditional privilege. Bitta xodimda bir nechta rol bo'lsa permission'lar birlashadi; "kichik do'kon" shabloni egasiga barcha rollarni beradi (DEC-100f). AI agent hech qachon `orders.confirm`, `orders.cancel`, `pricing.write`, `discount.apply`, `stock.*` olmaydi. Persist approvals as actor+timestamp+policy revision.

## Authentication and tokens
- Password Argon2id where password auth used; SSO later, password reset limited/expiring; refresh token rotation, revocation, device/session records and credential stuffing protections.
- **ADR-023 (DEC-008):** access JWT 10–15 daqiqa, frontend xotirasida (`Authorization: Bearer`), issuer/audience/kid/signature checked; refresh token — rotating, DB'da hash, `httpOnly Secure SameSite=Strict` cookie (`/api/v1/auth/refresh` path'iga cheklangan); refresh reuse aniqlansa butun session oilasi bekor qilinadi. Dashboard va API bitta site ostida (`app.` / `api.`). Tokenlar localStorage'da saqlanmaydi. WS uchun qisqa muddatli bir martalik ticket.
- Public quote/tracking links token scope=one resource, expiry, revocation, optional contact factor; no merchant ID inference as permission.
- HMAC webhook signature with secret rotation; replay timestamp windows/provider event ID, content raw bytes validation; outbound API scopes limited. Private provider callback URL must remain secret-independent (path secrecy insufficient).

## Threat model
| Threat | Mitigation | Negative verification |
|---|---|---|
| Cross-tenant IDOR | principal merchant-scoped UoW, composite FKs, optional proven RLS | A ID asks B SKU/order |
| AI prompt injection | treat customer/catalog text untrusted; tool allowlist, fixed policy, approval | prompt claiming 'admin' cannot call stock mutation |
| SSRF from product import/link preview | egress allowlist, private address deny, redirect rules | metadata endpoint denial |
| Fraudulent check upload | Stage 1: to'lov tizimda tasdiqlanmaydi (DEC-100); "to'landi" — tekshirilmagan merchant belgisi | screenshot never `PAID` |
| XSS in storefront/product | sanitize HTML, CSP, escaped render | malicious title harmless |
| CSRF/session theft | SameSite, CSRF token, MFA, session revocation | unauthorized cookie mutation blocked |
| Bot webhook forgery | signature, dedup, replay age | spoofed/duplicate webhook denied |
| Tenant leak through logs/embeddings | redact PII, tenant namespace, permission-aware retrieval | B embeddings never fetched by A |
| Image upload malware | MIME detect, AV, scanning, size quotas, private bucket | polyglot file quarantined |
| Cross-tenant background worker | hydrate tenant context before DB read and tool | foreign tenant payload denied |

## Audit policy and sensitive data
Every privileged state change produces append-only audit record: actor id/type, merchant, action, entity id/version, from→to, reason, decision, trace id, timestamp, sanitized diff. Hash-chain/tamper protection optional ADR with ops costs; never log passwords, raw payment tokens, voice audio or sensitive chat contents in audit. Employee accesses to private chats auditable.

## Privacy/lifecycle
Merchant owns customer relationship; platform processes to deliver service under contract. Explicit consent/notice for audio collection, training opt-in independent of service, transcript correction; default do NOT train shared model on merchant chats. Retention table by data class (to be legally reviewed), support export/delete requests; deletions consider accounting legal holds and backups. Stage 3 only publish opted-in storefront information, never phone/customer data. Verify Uzbek data residency and cross-border LLM processing rules with qualified counsel before live merchant PII.

## Security acceptance gates
`TC-SEC-01`: tenant A/B (API/WS/worker/AI/reports/search) — batafsil `TC-ISO-01…10` (TECH-23 §7), S0 gate; `02`: MFA for critical actions; `03`: signed webhook replay; `04`: same-origin/CSRF; `05`: injection and SSRF; `06`: S3 signed URL expiry; `07`: revoke staff mid job; `08`: audit log no secret; `09`: zero customer data in public offer; `10`: key rotation and active session revoke.

## Production controls
TLS, minimum security headers, secret manager, backup encryption, dependency and image CVE scanning, automated critical alert, vulnerability reporting/contact, least-privileged database role, no `postgres` superuser in API processes. Every auth failure logs safe reason without PII.
