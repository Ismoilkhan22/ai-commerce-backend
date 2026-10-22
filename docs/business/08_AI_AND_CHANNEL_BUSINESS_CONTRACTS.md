# 08 — AI AGENTS, VOICE, CHANNELS: BIZNES CAPABILITY CONTRACTS

**Version:** v1.0. Provider/model choice and prompts are **technical ADR / experiment**, this file defines permissions, business expectations, fallback and test boundaries.

## 1. Three explicitly separated AI identities

| AI agent | Scope | Allowed reads | Allowed write/propose | Strict no-go |
|---|---|---|---|---|
| `MerchantSalesAI` (Stage 1) | Single merchant and one conversation | Approved catalog, pricing, stock, FAQ, compatible PC parts | Lead draft, quote draft, operator handoff, approved permitted reply | Set paid, change stock, discount without approval, read other merchant |
| `MerchantVoiceCopilot` (Stage 1) | Requesting merchant principal and branch | Authorized semantic reporting metrics | Read-only Stage 1: report/query/export if role permits | Raw AI SQL unrestricted, write order, refund, transfer funds without approval |
| `GlobalShoppingAdvisor` (Stage 3) | Public index and consented buyer context | Canonical product, opted-in offer, public trust, location | Compare and create referral with buyer consent | Merchant private margin, sales stats, CRM, catalog unpublished items |

## 2. Merchant Sales Agent full business cycle

1. Channel ingress validates identity and message event, stores durable message.
2. Conversation manager resolves merchant, channel policy, AI/human mode.
3. AI determines language (`uz`, `ru`, `en`) and intent; asks only needed parameters: category, budget, specs, location, delivery preferences.
4. Product search tool responds with merchant-scoped SKU, versioned price, stock freshness, restrictions. AI never reconstructs nonexistent SKU.
5. For PC buyer, compatibility rules engine determines `PASS / REVIEW_REQUIRED / BLOCK`; LLM can summarize reasons but cannot override.
6. AI presents up to policy allowed recommendations with pros/cons, uncertainties, pricing validity.
7. If buyer ready: CRM tool records consented lead. PC yig'ma uchun quote builder immutable draft hisoblaydi (DEC-100e); pilotda har quote Manager/Owner tasdig'idan o'tadi (DEC-102). AI chegirma bermaydi (DEC-110).
8. Xaridor "olaman" desa: AI `orders.create_draft` bilan buyurtma qoralamasini (mahsulot, miqdor, kontakt, olib ketish/yetkazish, manzil) yaratadi va operatorni chaqiradi (DEC-100c). AI buyurtmani tasdiqlamaydi va "band qilindi/tasdiqlandi" demaydi — faqat "buyurtmangiz qabul qilindi, operator bog'lanadi" (BL-110, BR-X14). Stage 1 da to'lov tizimdan tashqarida (DEC-100).
9. Post-order status only from order state (FSM-08). AI cannot claim completed before `COMPLETED`.
10. Missing tools/provider down/angry customer/no consent → stop safely, store conversation and open human task.

### Sale AI tools (business typed contracts, implementation later) — nomlar K-10 formatida (`kontekst.amal`)

| Tool | Inputs | Returns | Side effect? | AI rights |
|---|---|---|---|---|
| `catalog.search` | merchant context (server-side), query, filters | versioned SKU candidates, evidence | No | Read |
| `pricing.get_price_stock` | SKU+branch | amount, currency, available, freshness | No | Read |
| `pc.compatibility_check` | component SKU IDs + rules version | `PASS / REVIEW_REQUIRED / BLOCK` and explanations (K-09) | No | Read |
| `leads.capture` | consented contact, preferences | lead_id, state | Yes | Draft only |
| `quotes.prepare_draft` | item SKUs, quantities, branch (faqat PC yig'ma) | quote_id, immutable snapshot, approval policy | Yes | Draft only |
| `quotes.request_approval` | quote id, reason | approval task id | Yes | May request |
| `chat.request_handoff` | conversation id, reason | queue assignment | Yes | Always allowed |
| `orders.lookup_status` | scoped order auth | validated state | No | Read authenticated buyer only |
| `orders.create_draft` | SKU(lar), miqdor, kontakt, fulfillment method, manzil; conversation | order_id (`DRAFT`), operator vazifasi | Yes | Draft only — stok band qilmaydi, tasdiqlamaydi (DEC-100c) |
| `orders.confirm` | — | — | Yes | **Forbidden** (faqat odam, DEC-108) |
| `payments.confirm` | — | — | Yes | **Forbidden** (Stage 1 da to'lov moduli yo'q) |
| `inventory.write` | — | — | Yes | **Forbidden** |

## 3. Voice Business Copilot UZ/RU/EN

**User journey:** owner taps mic → STT yields transcript with language + confidence → UI displays editable transcription → intent parser produces typed `metric_id`, `period`, `timezone`, `branch`, `filters` → reporting permission enforced → approved semantic metric service computes numbers → answer displayed with period/freshness/evidence → TTS audio as requested. User can fallback to text.

**Stage 1 baseline (DEC-112):** S5 da avval **matnli** hisobot-chat; ovoz (STT/TTS) golden set testidan keyin beta. **Supported read-only intents Stage 1:** completed orders count va summasi (to'lov tizimdan tashqarida — "paid turnover" faqat merchant belgisi bo'yicha, tekshirilmagan deb, DEC-100a); top SKU/PC builds by quantity; leads by channel; response time; unpaid order count; stock low list; daily/weekly/monthly trend; export report if principal can export.

**Undefined or blocked:** net profit when COGS incomplete; unsupported metric; user role no margin permission; microphone transcription uncertain about `15 mln vs 50 mln`; seller asks to lower stock/issue refund by voice → requires separate future command+approval and current Stage 1 must deny write.

**Sample prompts:**
- UZ: «Oxirgi 7 kunda Toshkent filialidagi to‘langan buyurtmalar summasini ayt; oldingi hafta bilan solishtir».
- RU: «Покажи пять самых продаваемых видеокарт за этот месяц и остатки на складе».
- EN: «Give me the paid order count, revenue definition and last updated timestamp for today».

**ASR quality:** PC model names, mixed Latin/Cyrillic, currency/large numbers and accents need offline golden set; hosted STT/TTS plus prompt/eval first, train local model **only if benchmark demonstrates need**. No accuracy claims without a test report.

## 4. Global shopping AI

- Differentiate exact-match model vs similar alternatives; explain why recommendation exists.
- Gather public price, delivery, warranty, condition, latest verification and merchant trust facts; absent data shown unknown.
- With no location permission use city search/merchant-declared zones.
- With public matching uncertainty, ask disambiguation or provide separately labeled product families.
- Sponsored listings must be labeled and not influence objective recommendation without disclosure.
- Referral to merchant only after buyer sees destination and permits data share.

## 5. Channel integration matrix — business behavior vs external approval

| Channel | Stage | Capabilities | Dependencies and fallback |
|---|---|---|---|
| Merchant website chat widget | 1 | Inbound text, quote, lead, order request | Owned channel; works even if external social APIs down |
| Telegram merchant bot | 1 | Buyer-initiated bot chat, typed catalog, notifications | Bot account setup; channel-specific consent/rate rules |
| Telegram Business connection | 1/2 | Business chats within authorized capabilities | Merchant permission and Telegram supported connection; regular bot fallback |
| Instagram Direct | 1 (DEC-116) | Permitted professional account conversation replies | Meta rasmiy ruxsati talab qilinadi — ariza S0 bilan topshiriladi; founder ruxsat kechikmaydi deb hisoblaydi (DEC-116a) |
| Facebook Messenger | 1/2 (gated) | Permitted Page conversations | Platform permissions & window; manual transfer fallback |
| WhatsApp Business Platform | 2 (gated) | Template/session messages where allowed | WABA onboarding/provider approval/fees; no bulk unsolicited messaging |
| Global website AI | 3 | Public global catalog search/recommendation | Only public offers |
| Global Telegram bot | 3 | Public comparison + opted-in referrals | Never share merchant private bot credentials or context |

No channel is labeled «live working» until technical proof/permissions approved. No stealth scraping, password automation, hidden personal-account messaging.

## 6. AI refusal/escalation matrix

| Cause | User-facing behavior | Merchant-facing result |
|---|---|---|
| SKU not in catalogue | «Aniq mahsulot topilmadi» + alternatives | Catalog improvement suggestion |
| Price stale | «Narx tasdiqlanishi kerak» | Quote review task |
| Compatibility unknown | «Mosligini tekshirib beramiz» | Hardware review task |
| AI provider outage | «Hozir operatorga ulayapman» | Manual inbox queue |
| Customer angry/dispute | Apology, human handoff; no policy invention | Escalation record |
| Payment proof screenshot | Stage 1: «To'lov do'kon bilan kelishiladi, operator bog'lanadi» | Operatorga uzatiladi (to'lov tizimdan tashqarida, DEC-100) |
| Voice uncertain number | Show transcript + ask repeat | No report/value mutation |
| Scope violation | Authorized-data refusal | Security audit event |
| Global missing shipping price | Base price only; no cheapest delivered claim | Offer quality warning |

## 7. AI dataset, training and evaluation business requirements

- **Sources:** approved merchant catalog/specs, rule set, consented sanitized chat, FAQ, PC component authoritative sources licensed for use, voice utterances with consent, synthetic multi-turn dialogs labeled synthetic.
- **Label fields:** merchant/domain, language, intent, entities, SKU evidence, expected tool calls, permission, outcome, escalation, latency and dollar/UZS values represented without ambiguity.
- **Golden sets:** UZ/RU/EN catalog intent, misspellings/translit, wrong variant, no stock, stale price, PC compatibility, fake payment proof, cross-tenant injection, voice `15/50 mln` confusion.
- **Evals:** wrong-price critical errors 0 in acceptance set; other retrieval/recall, match precision, refusal, voice WER/numeric intent exact-match targets chosen from pilot baseline. Do not train without licensing/consent/retention policy.
- **Architecture constraint:** first deploy a hosted model behind adapter + deterministic tools, logs/eval, optional small model later. Training from scratch is not Stage 1 prerequisite.
