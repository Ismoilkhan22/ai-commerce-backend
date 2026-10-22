# 03 — BIZNES QOIDALAR REYESTRI (`BL-001..BL-108`)

**Versiya:** v1.0 | **Status:** Review-ready rules. Raqamlar qatʼiy ID, tartib muhim emas.  
**Normativ:** MUST bo‘lgan qoidani buzgan action commit bo‘lmasligi yoki compensating exception bilan kuzatilishi shart.

## Tamoyil

- `BL` talabi modulga tegishli, lekin platformadagi boshqalar ham shu qoidaga amal qiladi.
- Biznes policy `IF condition THEN effect ELSE reject/approval/retry` sifatida implementatsiya qilinadi; technical concurrency batafsil ADRlarda yoziladi.
- Noaniq parametrlar (reserve TTL, discount cap, freshness TTL) `merchant_policy` orqali versioned configurable; default qiymatni go-live oldidan pilotda tasdiqlash shart. **Hozircha o‘zboshimcha min/soat o‘ylab topilmagan.**
- Callback bilan yozilgan paid holati source reconciliationga zid bo‘lsa exception queuega tushadi; qayta hisoblash imkoni saqlanadi.

| ID | Trigger / Shart | Majburiy qoida | Rad etish/istisno |
|---|---|---|---|
| `BL-001` | Merchant ro‘yxatdan o‘tadi | Bitta tasdiqlangan owner va mustaqil merchant identity yaratiladi | Egalik tekshiruvisiz aktivlashmaydi |
| `BL-002` | Tenant resursga murojaat qiladi | Har qanday read/write merchant scope bilan filtrlanadi | Cross-tenant ma’lumot 404/deny, audit alert |
| `BL-003` | Onboarding yakunlanadi | Minimal identifikatsiya, aloqa va public terms tasdiq bo‘lmaguncha live emas | Draft va checklist |
| `BL-004` | Merchant suspended/offboarded | Yangi sotuv va publikatsiya to‘xtaydi, tarixiy buyurtmalar boshqariladi | Mavjud majburiyatlar uchun controlled access |
| `BL-005` | Foydalanuvchi amal qiladi | RBAC + scope (merchant, branch, ownership) tekshiriladi | 403 + audit, sukut bo‘yicha deny |
| `BL-006` | Sezgir chegirma/refund/stock adjustment | Rol va limitdan oshsa second approval talab | Pending approval, write yo‘q |
| `BL-007` | Owner o‘zini o‘chiradi | Oxirgi ownerni o‘chirish taqiqlanadi | Yangi owner tayinlash talab |
| `BL-008` | AI tool buyruq beradi | AI ham aynan actor permissionlari bilan cheklanadi | Tool denied, operatorga eskalatsiya |
| `BL-009` | Filial joylashuvi e’lon qilinadi | Manzil/koordinata merchant tomonidan tasdiqlanadi | Unverified pin public emas |
| `BL-010` | Filial yopiqligi/ish vaqti o‘zgaradi | Pickup va delivery promise filial holatidan kelib chiqadi | Unavailable flag ko‘rsatiladi |
| `BL-011` | SKU yaratiladi | Merchant ichida unique SKU, variant va condition mustaqil saqlanadi | Duplicate validation error |
| `BL-012` | Mahsulot publish qilinadi | Majburiy atribut, narx va public kontent tekshiriladi | Missing fields = draft |
| `BL-013` | Import qilinadi | Preview/dry-run va row error; tanlangan yozuvlargina commit | Partial success summary, rollback policy |
| `BL-014` | Mahsulot archived | Yangi orderga kirmaydi, eski order snapshots saqlanadi | References delete qilinmaydi |
| `BL-015` | Narx belgilanadi | Currency+minor units, version, source va valid_until bo‘ladi | Invalid price reject |
| `BL-016` | Narx o‘zgardi | Yuborilgan quote immutable snapshot; qayta tasdiqda fresh pricing | Re-quote kerak |
| `BL-017` | Chegirma beriladi | Max discount rule/approver check; margin confidential | Out-of-limit approval |
| `BL-018` | Exchange price ishlatiladi | Kurs manbasi/vaqti snapshot; eskirsa final quote block | Manual price confirmation |
| `BL-019` | Stock ko‘rsatiladi | available = on_hand - reserved - allocated, >= 0 | Negative available block + reconcile |
| `BL-020` | Reservation yaratildi | Atomik check+increment, expiry; unique order/item reference | Insufficient stock = no reserve |
| `BL-021` | Reservation expiry/cancel | Faqat faol rezerv bo‘shatiladi; qayta release no-op | Idempotency required |
| `BL-022` | Stock adjustment | Ledger sababi, actor, timestamp va approval bilan | Unsourced adjustment reject |
| `BL-023` | Ikki buyurtma bitta SKUga | Row lock/CAS va DB constraint bilan oversell oldi olinadi | Bittasi conflict/retry |
| `BL-024` | Storefront publish | Faqat shu merchantning visible mahsulotlari chiqadi | Data scope violation block |
| `BL-025` | Storefront domain | Unique slug; domain verification; tls; revocation | Domain verified bo‘lmasa default subdomain |
| `BL-026` | Storefront stale stock | Display label va checkoutda fresh check | Stale claim bilan order confirm block |
| `BL-027` | PC komponent tanlandi | CPU/board/RAM/PSU/case bo‘yicha deterministik rules | BLOCK bo‘lsa quote yuborilmaydi |
| `BL-028` | Critical PC atribut noma’lum | Unknown != compatible; REVIEW_REQUIRED | Human assessment |
| `BL-029` | PC maslahati beriladi | Narx va stock filtrdan so‘ng tavsiya | Unavailable SKU exclude |
| `BL-030` | Rule set o‘zgargan | Quote rule_version va evidence snapshot saqlanadi | Revalidate if materially changed |
| `BL-031` | Channel connect | Rasmiy scope, account owner authorization va token vault | Permission yo‘q bo‘lsa connected deb ko‘rsatma |
| `BL-032` | Inbound webhook | Auth/signature, provider event uniqueness, durable persistence before ACK | Replay duplicate no-op |
| `BL-033` | Outbound channel | Provider window/recipient consent/rate-policy amal qilinadi | Blocked = manual fallback |
| `BL-034` | Conversation ownership | Bitta vaqtda AI yoki human send authority, har ikkisi emas | Atomic mode switch |
| `BL-035` | Incoming message order | Provider timestamp/event id bilan reorder/dedupe; unsafe gap = wait/reconcile | No double reply |
| `BL-036` | Consent handling | Xabarlardan kontakt/marketingga ruxsat farqlanadi | Marketing opt-in bo‘lmasa follow-up no-send |
| `BL-037` | Escalation | AI uncertain/complaint/payment/warranty = operator handoff | Human queue + SLA |
| `BL-038` | AI mahsulot aytadi | Faqat merchant allowlisted catalog tool natijasidagi SKU, narx, stock | Unsupported detail taqiqlanadi |
| `BL-039` | AI text/tool | Prompt injection va PII egress limit; tool-call schema validation | Unsafe instruction ignored/escalated |
| `BL-040` | AI bilan suhbat | Configurable quota/timeout/fallback; foydalanuvchiga inson mavjud | Quota exhaustion manual mode |
| `BL-041` | AI taklif yaratadi | Narx/delivery/discountni backend policy computes | LLM state mutation directly forbidden |
| `BL-042` | Lead yoziladi | Consent va minimal contact; duplicate logic scoped per merchant | Cross-merchant identities merged emas |
| `BL-043` | Quote yaratildi | Immutable SKU, price, taxes/fee if any, condition, warranty snapshot | No incomplete quote send |
| `BL-044` | Quote tugaydi | Expiry/stock/price qayta check; old quote paid order qilinmaydi | Re-quote requested |
| `BL-045` | Quote approval | Threshold/compatibility REVIEW uchun authorized approver | Approval bypass reject |
| `BL-046` | Order yaratiladi | Quote/order idempotency key, tenant and source uniqueness | Duplicate = same result |
| `BL-047` | Order confirm | Current stock or valid reservation, price and terms checked | Conflict -> customer re-confirm |
| `BL-048` | Order transition | Only allowed FSM transition with role and reason | Invalid transition = 409 |
| `BL-049` | Order cancelled | Reservation release and payment reconciliation orchestrated; no silent paid loss | Paid after cancel -> exception queue |
| `BL-050` | Manual payment proof | Proof != verified; authorized reviewer matches actual receipt | Remain pending until evidence |
| `BL-051` | Payment callback | Authenticity, amount, currency, merchant account and provider ref checked | Mismatch quarantine |
| `BL-052` | Payment/reversal | Idempotent processing and ledger reconciliation | Duplicate webhook no double paid/refund |
| `BL-053` | Refund | Merchant policy, evidence, approval, exact amount limits | Provider failed: refund pending, not completed |
| `BL-054` | Delivery booked | Address, contact permission, branch and shipment method verified | Missing address -> no dispatch |
| `BL-055` | Shipment status | Courier/manager scoped; POD where applicable | Delivered requires evidence policy |
| `BL-056` | Delivery failure | Retry/reschedule/return recorded, customer informed | No silent status skip |
| `BL-057` | Warranty sold | Terms snapshot order line at time of sale | Future policy edit does not change old sale |
| `BL-058` | Return request | Eligibility and product condition reviewed by human | Refund only approved case |
| `BL-059` | Return-to-stock | Inspect return; damaged not saleable | Ledger records disposition |
| `BL-060` | Notification created | Event/template/version/recipient and dedup key recorded | Duplicate deliver suppressed |
| `BL-061` | Recipient opt-out/quiet | Respect legal and channel transactional exceptions | Suppress marketing push |
| `BL-062` | Provider delivery error | Retry bounded; DLQ and visible merchant task | Never lose error silently |
| `BL-063` | Financial report | Metric registry defines paid turnover vs profit vs revenue | No undefined metric |
| `BL-064` | Voice report | Speech-to-text transcript confirmation for sensitive sums | Low-confidence ask to repeat |
| `BL-065` | Reporting permissions | Branch/role; sensitive costs hidden from sales users | Aggregates filtered at DB access |
| `BL-066` | Reporting freshness | Every generated answer displays period/timezone/data_as_of | Stale report explicitly flagged |
| `BL-067` | Subscription quota | Usage measured by merchant and stable billing windows | Exceeded: explain and limit noncritical functions |
| `BL-068` | Billing failure | Grace and downgrade policies; existing paid orders remain accessible | No orphaned pending orders |
| `BL-069` | AI switch off | Human sale/catalog/order operate independent of AI model | Manual fallback |
| `BL-070` | Merchant offboarding | Export available according to policy, access revoke, retention purge | No public offers remain |
| `BL-071` | Critical write | Actor, trace, entity, before/after safe diff audit in same logical operation | Fail closed for stock/payment if audit unavailable |
| `BL-072` | Audit visibility | Secrets, card data and unnecessary PII not logged | Redaction and access controls |
| `BL-073` | External source connected | Source-of-truth priority per field (stock, price, metadata) declared | Conflict -> review, no blind overwrite |
| `BL-074` | Sync job | Provider-specific cursor, idempotency and rate limits | Retry/backoff + visible health |
| `BL-075` | Mapping conflict | Test import dry-run and log unresolved SKU | Ambiguous overwrite prevented |
| `BL-076` | Canonical match | GTIN/MPN/brand+model+variant evidence required | Low-confidence auto-merge forbidden |
| `BL-077` | Variant difference | Capacity, color, condition, revision/material specs never silently merged | Split/review |
| `BL-078` | Canonical merge rollback | Keep provenance and reversible links | Wrong merge can be undone |
| `BL-079` | Public offer opt-in | Merchant explicitly selects offered public fields | Default private |
| `BL-080` | Offer publish/update/revoke | Index is eventually consistent but withdrawal prioritized; fail closed after revoke | Stale offer hidden until reverify |
| `BL-081` | Public offer content | Only approved public price, terms, branch location; never COGS/leads | Reject sensitive fields |
| `BL-082` | Inter-branch transfer | Atomic decrement origin at dispatched, receive destination after confirmation; in-transit tracked | Reconcile discrepancy |
| `BL-083` | Tenant plan change | Effective dates/usage and rights calculated deterministically | No retroactive unexpected charge |
| `BL-084` | Merchant knowledge revision | Policies reviewed and versioned before AI answers | Draft knowledge not active |
| `BL-085` | Index processing | Event ordering/aggregate_version and replay semantics | Older update cannot overwrite newest |
| `BL-086` | Index freshness | Merchant-defined TTL; stale prices hidden/warned | Checkout live reconfirmation |
| `BL-087` | Merchant verification | Badges require verified evidence and expiry | No unverifiable trusted label |
| `BL-088` | Fraud/moderation | Complaint, appeal, removal policy; unbiased written reasons | Abusive offer removed with audit |
| `BL-089` | Partner API | Scoped key, throttle, revoke, service audit | Compromised key disabled |
| `BL-090` | Global search | Search only published canonical and opt-in offers | Private items absent |
| `BL-091` | Product result | Condition/variant discriminators respected | Incomparable SKUs separate |
| `BL-092` | Price comparison | Show base price, delivery cost if known, currency, warranty, updated_at | Unknown total cannot claim cheapest |
| `BL-093` | Comparison sort | Total cost used only when comparable and valid | Otherwise base-price label |
| `BL-094` | User reports wrong offer | Evidence and merchant review, suppress severe false claim | Correction feedback tracked |
| `BL-095` | Location | Request explicit consent for device precise geo; city query without it | Denied -> manual area search |
| `BL-096` | Distance claims | Straight-line vs provider travel distance clearly labeled | No invented travel times |
| `BL-097` | Global AI recommendation | Explain input constraints and evidence source; no invented product quality | If no evidence, state uncertainty |
| `BL-098` | Global AI tool | Public index only, no merchant internal data | Cross boundary denied |
| `BL-099` | Ranked recommendations | Organic unaffected by paid ads; sponsored clearly separated | Disclosure mandatory |
| `BL-100` | Lead routed to merchant | Buyer consent and visible destination; tracked referral id | No unauthorized bulk solicitation |
| `BL-101` | Lead attribution | Merchant receives only necessary lead data after opt-in | No platform-wide identity leakage |
| `BL-102` | Saved alerts | Explicit opt-in with one-click unsubscribe | Default off |
| `BL-103` | Price watch | Alerts only on fresh verified offer and throttled per user | Stale offer no alert |
| `BL-104` | Sponsored slots | Clearly marked and approved; not presented as AI-best | Disclose paid placement |
| `BL-105` | Ranking quality | Match quality, offer freshness and disclosed scoring criteria | Complaints trigger review |
| `BL-106` | SEO public pages | Structured data only for currently valid public offers | Invalid markup removed |
| `BL-107` | Duplicate global/product pages | Canonical URL and noindex for thin duplicate states | No low-quality doorway pages |
| `BL-108` | Global Telegram bot | Separate bot identity and principal from merchant bot | No implicit cross-store context sharing |

## Eng muhim kombinatsiyalangan edge-case ssenariylari

**Case BR-X01: last SKU race.** 1 dona bor, ikkita order har biri 1 dona reserve qiladi. Faqat bittasi muvaffaqiyatli; ikkinchisi stock conflict oladi. `BL-019/020/023/046/047`.

**Case BR-X02: late payment.** Rezerv muddati tugadi, keyin `payment.verified` keldi. Paid yozuvi ledgerda saqlanadi, order avtomatik `fulfilled` bo‘lmaydi; operator refund/rebook qarorini beradi. `BL-021/049/051/052`.

**Case BR-X03: price drift.** AI 4,5 mln so‘mlik quote berdi, merchant narxni 4,8 mln qildi. Old quote snapshot o‘zgarmaydi; expiry/business policyga ko‘ra order confirmdan avval qayta rozilik talab. `BL-015/016/044/047`.

**Case BR-X04: channel duplicates.** Telegram/Meta xabari ikki marta keldi. Inboxda bitta logical message, AI bitta response, notification bitta transaction intent. `BL-032/035/060`.

**Case BR-X05: AI takeover race.** Operator suhbatni oldi; AI parallel javob generate qildi. Mode generation/cas check javob yuborishdan oldin to‘xtatadi. `BL-034/037`.

**Case BR-X06: cross-tenant voice data.** Merchant A xodimi Merchant B foydasini so‘radi; agent tool-level permission deny qaytaradi, hech qanday metric chiqmaydi. `BL-002/005/008/065/098`.

**Case BR-X07: public opt-out.** Merchant global searchdan taklifini olib tashladi. Public index eski bo‘lsa ham request authorization/visibility gate offerni chiqarishni taqiqlaydi. `BL-079/080/081/085/090`.

**Case BR-X08: wrong match.** RTX 5060 8GB ni RTX 5060 Ti yoki boshqa memory variant bilan merge qilish taqiqlanadi; yuqori confidence bo‘lmasa manual review. `BL-076/077/078/091`.

**Case BR-X09: payment proof forgery.** Mijoz skrinshot yubordi. Status pending qoladi, reviewer real tushum yoki trusted provider transaction bilan solishtiradi. `BL-050/051`.

**Case BR-X10: false cheapest claim.** Bitta merchantda delivery unknown, ikkinchisida 50k. AI «eng arzon yetkaziladigan» deya olmaydi; «asosiy narx» va unknown delivery ni alohida belgilaydi. `BL-092/093/097`.

**Case BR-X11: return of damaged SKU.** Returned hardware tekshirilmaguncha saleable stockga kirmaydi. `BL-057/059/019`.

**Case BR-X12: POS vs dashboard edit.** Bir paytning o‘zida POS va merchant qoldiqni o‘zgartirdi. Version/source priority va reconcile, blind last-write-wins taqiqlanadi. `BL-073/075/019`.
