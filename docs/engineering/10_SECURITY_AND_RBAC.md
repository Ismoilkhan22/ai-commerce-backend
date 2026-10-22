# TECH-10 — Security, tenancy, RBAC, audit and privacy

**Status:** Design candidate, mandatory security test gate. **References:** Business roles matrix (04), TECH-05 ADR-002/003/007, TECH-06 data, TECH-08 API. **Caution:** not legal compliance certification.

## Identity/authorization model
- User principal ≠ merchant; `membership` links user→merchant with role, status, optional branch scopes and explicit permissions. Switching current merchant revalidates membership; JWT merchant hint cannot grant access alone.
- Roles: owner, manager, sales, warehouse, finance, analyst, courier, platform_support, customer. Role permissions are least-privilege and action-based (`orders.confirm`, `payments.verify_manual`, `stock.adjust`, `reports.margin.read`, `agent.pause`).
- Attribute guards: merchant scope, branch, record ownership, channel, plan capability, resource status, MFA/step-up recency, approval limit. API, background job and AI tool share same policy service.
- Platform support uses time-limited, reason-coded support grant, audited; default no access to raw merchant chats/audio. Billing staff can't inspect customer messages without scoped grant.

## Permission matrix (subset)
| Action | Owner | Manager | Sales | Stock | Finance | Courier | Analyst | AI |
|---|---|---|---|---|---|---|---|---|
| Catalog read | ✓ | ✓ | ✓ | ✓ | limited | — | aggregate | public only |
| Price change | ✓ | policy | — | — | — | — | — | never |
| Stock adjustment | ✓ | approval | — | scoped | — | — | — | never |
| Quote create | ✓ | ✓ | ✓ | — | — | — | — | suggested draft |
| Quote approve | ✓ | cap | cap policy | — | — | — | — | never |
| Manual payment verify | ✓+step-up | — | — | — | ✓+evidence | — | — | never |
| Delivery update | ✓ | ✓ | scoped | — | — | assigned only | — | never |
| Gross margin report | ✓ | policy | — | — | policy | — | approved | tool read-only if delegated |
| Public offer opt-in S2 | ✓ | delegated | — | — | — | — | — | never |

`✓` is capability subject to tenant scopes and policy, not unconditional privilege. Persist approvals as actor+timestamp+policy revision.

## Authentication and tokens
- Password Argon2id where password auth used; SSO later, password reset limited/expiring; refresh token rotation, revocation, device/session records and credential stuffing protections.
- Access JWT short lived, issuer/audience/kid/signature checked; refresh stored hashed, optional httpOnly Secure SameSite cookie for browser flows; CSRF on cookie-based unsafe calls. Do not put secret tokens in localStorage where avoidable.
- Public quote/tracking links token scope=one resource, expiry, revocation, optional contact factor; no merchant ID inference as permission.
- HMAC webhook signature with secret rotation; replay timestamp windows/provider event ID, content raw bytes validation; outbound API scopes limited. Private provider callback URL must remain secret-independent (path secrecy insufficient).

## Threat model
| Threat | Mitigation | Negative verification |
|---|---|---|
| Cross-tenant IDOR | principal merchant-scoped UoW, composite FKs, optional proven RLS | A ID asks B SKU/order |
| AI prompt injection | treat customer/catalog text untrusted; tool allowlist, fixed policy, approval | prompt claiming 'admin' cannot call stock mutation |
| SSRF from product import/link preview | egress allowlist, private address deny, redirect rules | metadata endpoint denial |
| Fraudulent check upload | verify actual funds via provider/finance | screenshot never `PAID` |
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
`TC-SEC-01`: tenant A/B (API/WS/worker/AI/reports/search); `02`: MFA for critical actions; `03`: signed webhook replay; `04`: same-origin/CSRF; `05`: injection and SSRF; `06`: S3 signed URL expiry; `07`: revoke staff mid job; `08`: audit log no secret; `09`: zero customer data in public offer; `10`: key rotation and active session revoke.

## Production controls
TLS, minimum security headers, secret manager, backup encryption, dependency and image CVE scanning, automated critical alert, vulnerability reporting/contact, least-privileged database role, no `postgres` superuser in API processes. Every auth failure logs safe reason without PII.
