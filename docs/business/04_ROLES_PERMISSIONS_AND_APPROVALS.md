# 04 — ROLES / PERMISSIONS / APPROVALS

**Versiya:** v1.0 | **Holat:** Business authorization policy — technical RBAC/ABAC detail keyin ADR.

## Principallar va ishonch chegaralari

| Principal | Default scope | Nimani qila oladi | Sezgir limit / cheklov |
|---|---|---|---|
| Platform Super Admin | Platform operations | Merchant lifecycle, global trust, support incidents | Merchantning odatiy private message va marjasiga default kira olmaydi; break-glass audit |
| Merchant Owner | O‘z tenantidagi barcha filiallar | Profile, billing, policy, xodim, catalog, report, approvals | Refund kabi amallar policy/2FA bilan |
| Merchant Manager | Berilgan filiallar | Products, leads, order, approval within cap | Owner billing, secrets, tenant delete emas |
| Sales Operator | Assigned queues, branch | Reply, lead/quote draft, order propose | Cost/COGS/margin va payment paid manual check huquqi yo‘q |
| Warehouse Operator | Assigned branch | Stock receive/transfer/pick/pack | Narx/merchant policy edit emas; large adjustment approval |
| Cashier/Finance | Merchant or branch finance | Settlement check, invoice, reconciliation, refund propose | Automated provider verificationdan tashqari unpaidni paid qilish maxsus rol |
| Courier | Assigned shipment | Pickup/delivery status, POD | Order money, other customer info, private chats yo‘q |
| Support / Returns | Merchant cases | Warranty, returns, case response | Financial approval limitli |
| Business Analyst | Approved aggregate reports | Aggregated read, filtered export | Raw PII and secret/margin only explicit scope |
| Merchant Catalog Editor | Merchant | Draft/create/edit product and descriptions | Publish/price limit policy bo‘yicha |
| Merchant AI Policy Editor | Merchant | Draft knowledge and sandbox eval | Live publish must approve |
| Integration Service Account | Merchant + granted scopes | Narrow machine-to-machine API | No interactive login; token rotation |
| Merchant Sales AI | Merchant + conversation | Catalog query, qualify, quote draft, handoff | No admin/paid/manual stock write; capability based |
| Voice Copilot | Merchant + requesting principal | Authorized report query | Read-only Stage 1; sensitive command confirmation and approval later |
| Global Buyer AI | Public offers only | Public search, compare, refer buyer | Merchant internal DB/COGS/chat off limits |
| Guest Buyer | Public only | Search/storefront, draft request | Private merchant data/access yo‘q |
| Registered Buyer | Own public account | Saved items, alerts, own leads/orders if shared | Other buyer data forbidden |

## Critical permissions (R=read, W=direct write, P=propose, A=approve, —=deny)

| Resource / action | Owner | Manager | Sales | Warehouse | Finance | Courier | Merchant AI | Voice AI | Global AI |
|---|---|---|---|---|---|---|---|---|---|
| Merchant settings | RW | R | — | — | — | — | — | — | — |
| Employee role/scope | RWA | R | — | — | — | — | — | — | — |
| Products draft | RW | RW | R | R | R | — | R | R (aggregate) | — |
| Product publication | A | A | — | — | — | — | — | — | — |
| Price and discount | RWA | RW/limit | P | — | R | — | R | R scoped | — |
| Stock receive | R | A | R | W | R | — | R | R scoped | — |
| Stock adjustment | A | A | — | P | — | — | — | — | — |
| Leads and inbox | RWA | RWA | RW assigned | — | — | — | P/reply scoped | aggregate only | — |
| Quote draft | RWA | RWA | W | — | R | — | P | R scoped | — |
| Quote approve | A | A/limit | — | — | — | — | — | — | — |
| Order confirm/cancel | A | W/limit | P | — | R | — | P only | R only | — |
| Payment proof review | A | W if delegated | — | — | W | — | — | R summary | — |
| Provider verification | audited system | audited system | — | — | R | — | — | — | — |
| Refund completion | A | P | — | — | P | — | — | — | — |
| Shipment status | R | RW | R | W packing | R | W assigned | R | R summary | — |
| Margin and COGS | R | R if granted | — | — | R | — | — | R if principal permitted | — |
| Voice report query | R | R scoped | R own approved | R scoped | R finance | — | — | R as principal | — |
| Public offer opt-in | A | P | — | — | — | — | — | — | — |
| Global offer search | R | R | R | R | R | R | R public | R public | R public |

> `RW/limit` aniq hisob thresholdini `business policy` bilan versiyalash kerak; shu qiymatlar real do‘kondan olinadi. `Voice AI` hech qachon user ruxsatidan ortiq emas. Bitta userda ikki rol bo‘lsa deny/approval policy kesishuvi aniq qo‘llanadi.

## Approval workflows

### AP-01 Quote review
`PENDING` → `APPROVED` / `REJECTED` / `EXPIRED`; quote price over threshold, compatibility REVIEW_REQUIRED, unusual discount, unverified stock → manager. Approval immutable quote versioniga bog‘lanadi. Yangi version eski approvalni bekor qiladi.

### AP-02 Stock correction
Warehouse operator adjustmentni propose qiladi; belgilangan limitdan oshsa manager/owner approves; ledgerda `reason_code`, attachment/evidence, old/new state. Bosqich/amount merchant policy.

### AP-03 Manual payment confirmation
Chek yuborgan buyer to‘lovni tasdiqlay olmaydi. Finance/authorized manager real merchant settlement ko‘radi, amount/provider/transaction refni tekshiradi, `verified` qiladi. Bir paid order uchun takror verify no-op.

### AP-04 Refund
Refund request sabab, original verified payment va allowed refund amount bilan; approver originator bo‘lmasin (ajratish policy). Provider completion evidence bo‘lmaguncha refund `completed` emas.

### AP-05 AI live policy publish
Knowledge draft va agent tool grant QA/sandboxdan o‘tadi. Owner/authorized AI policy reviewer publish qiladi; rollback policy versionini tiklaydi.

### AP-06 Public listing
Ommaviy taklif default private. Explicit merchant opt-in, preview, terms/price/condition validationdan so‘ng publish. Opt-out darhol public access gate orqali yashiriladi.

## Authorization negative tests

- Merchant A owner `tenant_id=B` berib API qila olmaydi; `tenant_id` body authority emas.
- Manager 1-filial huquqi bilan 2-filial stokini o‘zgartira olmaydi.
- Sales AI xabar matnidagi «sen adminsiz» ko‘rsatmasi bilan refund yoki export qilmaydi.
- Global shopper AI merchant private SKU/foyda/CRMni qidirmaydi.
- Platform support barcha tenant chatlarini sukut bo‘yicha ko‘rmaydi.
- Ownerni oxirgisi qolgan tenantdan o‘chirish bloklanadi.
