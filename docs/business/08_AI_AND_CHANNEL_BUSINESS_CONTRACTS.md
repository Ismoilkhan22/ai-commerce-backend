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
7. If buyer ready: CRM tool records consented lead; quote builder calculates immutable draft; discount or unusual hardware → human approval.
8. Order proposal requires explicit buyer confirmation and fresh stock/price; payment verification belongs independent payment module.
9. Post-order status only from verified order fulfillment state. AI cannot claim delivered before proof.
10. Missing tools/provider down/angry customer/no consent → stop safely, store conversation and open human task.

### Sale AI tools (business typed contracts, implementation later)

| Tool | Inputs | Returns | Side effect? | AI rights |
|---|---|---|---|---|
| `search_merchant_catalog` | merchant context, query, filters | versioned SKU candidates, evidence | No | Read |
| `get_sku_price_stock` | SKU+branch | amount, currency, available, freshness | No | Read |
| `check_pc_compatibility` | component SKU IDs + rules version | PASS/BLOCK/REVIEW and explanations | No | Read |
| `create_lead_draft` | consented contact, preferences | lead_id, state | Yes | Draft only |
| `build_quote_draft` | item SKUs, quantities, branch | quote_id, immutable snapshot, approval policy | Yes | Draft only |
| `request_manager_approval` | quote id, reason | approval task id | Yes | May request |
| `handoff_to_human` | conversation id, reason | queue assignment | Yes | Always allowed |
| `lookup_order_status` | scoped order auth | validated state | No | Read authenticated buyer only |
| `confirm_payment` | — | — | Yes | **Forbidden** |
| `write_stock` | — | — | Yes | **Forbidden** |

## 3. Voice Business Copilot UZ/RU/EN

**User journey:** owner taps mic → STT yields transcript with language + confidence → UI displays editable transcription → intent parser produces typed `metric_id`, `period`, `timezone`, `branch`, `filters` → reporting permission enforced → approved semantic metric service computes numbers → answer displayed with period/freshness/evidence → TTS audio as requested. User can fallback to text.

**Supported read-only intents Stage 1:** sales/orders count; paid turnover; top SKU/PC builds by quantity; leads by channel; response time; unpaid order count; stock low list; daily/weekly/monthly trend; export report if principal can export.

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
| Instagram Direct | 1 (gated) | Permitted professional account conversation replies | Meta approved permissions/webhook/policy; disabled/manual link fallback |
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
| Payment proof screenshot | «Tekshiruvda» | Finance review |
| Voice uncertain number | Show transcript + ask repeat | No report/value mutation |
| Scope violation | Authorized-data refusal | Security audit event |
| Global missing shipping price | Base price only; no cheapest delivered claim | Offer quality warning |

## 7. AI dataset, training and evaluation business requirements

- **Sources:** approved merchant catalog/specs, rule set, consented sanitized chat, FAQ, PC component authoritative sources licensed for use, voice utterances with consent, synthetic multi-turn dialogs labeled synthetic.
- **Label fields:** merchant/domain, language, intent, entities, SKU evidence, expected tool calls, permission, outcome, escalation, latency and dollar/UZS values represented without ambiguity.
- **Golden sets:** UZ/RU/EN catalog intent, misspellings/translit, wrong variant, no stock, stale price, PC compatibility, fake payment proof, cross-tenant injection, voice `15/50 mln` confusion.
- **Evals:** wrong-price critical errors 0 in acceptance set; other retrieval/recall, match precision, refusal, voice WER/numeric intent exact-match targets chosen from pilot baseline. Do not train without licensing/consent/retention policy.
- **Architecture constraint:** first deploy a hosted model behind adapter + deterministic tools, logs/eval, optional small model later. Training from scratch is not Stage 1 prerequisite.
