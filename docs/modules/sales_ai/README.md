# sales_ai

**Qatlam:** domain · **Schema:** `sales_ai` · **Slice:** S3 · **Egasi:** ___
**Biznes modullar:** M11, M19 (AI sozlamalari qismi) · **Qoidalar:** BL-038…041, BL-067, BL-069, BL-110 · **Holatlar:** o'z FSM'i yo'q; suhbat holati — FSM-04 (`messaging`)

## 1. Nima qiladi

Shop xaridorlariga Telegram, Instagram va sayt chatida javob beradigan AI sotuvchi. Faktlarni (narx, qoldiq, moslik, buyurtma holati) faqat Query Port orqali o'qiydi. Lead, taklif va buyurtma **qoralamasini** faqat event orqali so'raydi (DEC-100c, ADR-032).

Bu domen qilmaydi:
- narx, qoldiq va buyurtmani o'zgartirish yoki tasdiqlash;
- xabarni kanalga to'g'ridan-to'g'ri yuborish (yuborish va `speaker_version` tekshiruvi — `messaging`).

Hisobot yordamchisi bu domenda emas, `reporting/assistant` da.

Batafsil: [14-ai-sales-agent-and-tools.md](../../engineering/14-ai-sales-agent-and-tools.md).

## 2. Sub-modullar

| Sub-modul | Vazifasi | Asosiy jadvallar |
|---|---|---|
| `agent` | Navbat orkestratori, tool broker, javob tekshiruvi (validator), sessiya slot'lari | `ai_sessions`, `ai_turns` (javob matni, `reply_id`), `ai_tool_executions`, `conversation_summaries` (`07` §4.6, `14` §6, §13). PII token xaritasi — `platform.llm_pii_refs` |
| `knowledge` | Agent profili (ohang, rejim), prompt versiyalari, FAQ va siyosatlar (versiyalangan, ega tasdig'i bilan) | `agent_profiles`, `prompt_versions`, `knowledge_items` ([07](../../engineering/07-data-layer.md) §4.6) |

## 3. Holatlar

Domen o'z FSM'iga ega emas.
- **Bilim yozuvlari va prompt versiyalari:** `DRAFT → APPROVED → ACTIVE → RETIRED` ([07](../../engineering/07-data-layer.md) §4.6). Ega tasdiqlaydi (`../../business/04` §3).
- **Sessiya bosqichi `ai_stage`** — ruxsat uchun emas, faqat ko'rsatish uchun ([14](../../engineering/14-ai-sales-agent-and-tools.md) §10):

```
IDLE ──▶ QUALIFYING ──▶ RECOMMENDING ──▶ QUOTE_PENDING ──▶ ORDER_DRAFTED ──▶ HANDED_OFF   (yoki STOPPED)
```

**AI rejimi:** `OFF` / `SUGGEST` (pilotning 1-haftasi) / `AUTO`.

## 4. Event'lar

### Chiqaradi ([05](../../engineering/05-events-and-outbox.md) §8.4)

| Event | Qachon | Kim tinglaydi |
|---|---|---|
| `sales_ai.reply.ready` | Javob tayyor va tekshiruvdan o'tdi | messaging |
| `sales_ai.reply.validation_failed` | Javob tekshiruvdan o'tmadi (TC-007) | messaging, reporting |
| `sales_ai.handoff.requested` | AI operator chaqirdi | messaging |
| `sales_ai.order_draft.requested` | Xaridor "olaman" (BL-110) | commerce |
| `sales_ai.quote_draft.requested` | AI PC yig'ma tuzdi | commerce |
| `sales_ai.quote_approval.requested` | Taklifni menejer tasdig'iga yuborish | commerce |
| `sales_ai.lead_capture.requested` | AI ehtiyojni aniqladi | commerce |

### Tinglaydi

| Event | Kimdan | Nima qiladi |
|---|---|---|
| `messaging.message.received` | messaging | `speaker_mode=AI` va rejim `OFF` emas → limitni tekshiradi → arq `ai_reply` |
| `messaging.conversation.handed_off` / `returned_to_ai` | messaging | Kutilayotgan navbatni bekor qiladi / operator xulosasini oladi |
| `messaging.channel.connected` / `disconnected` | messaging | Agent qaysi kanallar faolligini biladi |
| `commerce.order.drafted`, `commerce.quote.drafted`, `commerce.quote.expired` | commerce | `ai_sessions.last_order_ref` / `last_quote_ref` yangilanadi |
| `catalog.pc_ruleset.activated`, `catalog.hardware_spec.updated` | catalog | Keshlangan moslik natijalari bekor qilinadi |
| `platform.shop.activated` / `suspended` | platform | Agent yoqiladi / o'chadi |
| `platform.ai_quota.exhausted` | platform/billing | Rejim amalda `OFF`, xabarlar operatorga (BL-067, BL-069) |
| `platform.privacy.export_requested` / `erasure_requested` | platform/privacy | O'z qismini tayyorlaydi yoki o'chiradi ([26](../../engineering/26-privacy-and-retention.md)) |

## 5. Query Port

**Beradi** (`SalesAiQueryPort`, `app/shared/contracts/sales_ai.py`):

| Metod | Qaytaradi | Kim ishlatadi |
|---|---|---|
| `get_reply` | AI javob matni (event'da matn yo'q) | messaging |
| `resolve_contact_ref` | `contact_ref_id` bo'yicha haqiqiy kontakt (bir martalik) | commerce |

**Ishlatadi:**
- `CatalogQueryPort`: `search`, `get_active_price`, `check_compatibility`, `suggest_builds`;
- `CommerceQueryPort`: `get_availability`, `get_order_status`;
- `MessagingQueryPort`: `get_conversation_context`.

## 6. API (`shop` surface)

| Metod va yo'l | Ruxsat | Idempotency |
|---|---|---|
| `GET` / `PATCH /shop/ai/settings` (rejim) | `sales_ai.settings.view` / `sales_ai.settings.edit` | — / If-Match |
| `GET` / `POST` / `PATCH /shop/ai/knowledge…` | `sales_ai.settings.view` / `sales_ai.knowledge.edit` | Idem / If-Match |
| `POST /shop/ai/knowledge/{id}/publish`, `…/rollback` | `sales_ai.knowledge.publish` | Idem |
| `POST /shop/ai/sandbox/messages` | `sales_ai.knowledge.test` | Idem |

Manba: [11](../../engineering/11-api-conventions-errors-i18n.md) §9.6.

**AI tool'lari** (K-10, [14](../../engineering/14-ai-sales-agent-and-tools.md) §4):
- `catalog.search`, `catalog.get_price_stock`, `catalog.check_compatibility`, `catalog.suggest_builds`;
- `commerce.lookup_order_status`, `commerce.capture_lead`, `commerce.prepare_quote_draft`, `commerce.request_quote_approval`, `commerce.create_order_draft`;
- `messaging.request_handoff`.

## 7. Ruxsatlar

| Kod | Kimda bor ([10](../../engineering/10-security-tenancy-rbac.md)) |
|---|---|
| `sales_ai.settings.view` | Ega, menejer, AI sozlamalari muharriri |
| `sales_ai.settings.edit` | Faqat ega |
| `sales_ai.knowledge.edit`, `sales_ai.knowledge.test` | Ega, AI sozlamalari muharriri |
| `sales_ai.knowledge.publish` | Faqat ega |

AI agent principal'i hech qachon quyidagilarni olmaydi: `commerce.order.confirm`, `commerce.order.cancel`, `catalog.price.change`, `commerce.discount.*`, `commerce.stock.*` (yozish), `reporting.*` — CI testi bilan tekshiriladi.

## 8. Fon va rejali ishlar

| Ish | Qachon | Idempotency kaliti |
|---|---|---|
| `ai_reply` (arq, `default`) | `messaging.message.received` dan keyin | `ai_reply:{conversation_id}:{message_id}` |

Qo'shimcha qoidalar:
- 2 marta qayta urinish, timeout 45 s; muvaffaqiyatsiz bo'lsa — handoff (`AI_UNAVAILABLE`).
- Xabar 10 daqiqadan eski bo'lsa — vazifa tashlanadi ([06](../../engineering/06-background-jobs.md)).

## 9. Metrikalar

- `cos_sales_ai_first_reply_duration_seconds`, `cos_sales_ai_turns_total`, `cos_sales_ai_turn_duration_seconds`, `cos_sales_ai_tool_calls_total`, `cos_sales_ai_reply_rejected_total`, `cos_sales_ai_handoff_total`, `cos_sales_ai_order_draft_requested_total` ([09](../../engineering/09-observability.md))
- AI xarajati: `cos_llm_cost_minor_total` (`platform/llm`).

## 10. Testlar

- TC-007, TC-008, TC-009, TC-028, UAT-M11, UAT-M19
- TC-AI-01…03 ([14](../../engineering/14-ai-sales-agent-and-tools.md) §16)
- Golden set va red-team: [16](../../engineering/16-ai-data-and-evaluation.md)
- Izolyatsiya: TC-ISO (boshqa shop xotirasi kontekstga tushmaydi)

## 11. Ochiq savollar

Hozircha yo'q.
