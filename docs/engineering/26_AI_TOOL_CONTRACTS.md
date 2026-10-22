# TECH-26 — AI Sales Agent: tool kontraktlari, prompt, xotira va xavfsizlik qatlamlari

**Status:** Baseline (2026-10-22). DEC-009, DEC-016, DEC-100c, K-10, BL-038…041, BL-110 asosida. Raqamli chegaralar (token, qadam soni, vaqt) LLM bake-off'dan (S3-00) keyin yangilanadi. "Taklif" belgilangan bandlar default, o'zgartirilishi mumkin.
**Bog'liq:** `15_AI_AGENTS_ARCHITECTURE.md` (umumiy arxitektura), `23_TENANT_ISOLATION_AND_DEPLOYMENT_MODES.md` (izolyatsiya), `25_PC_COMPATIBILITY_ENGINE.md`, `24_API_CONVENTIONS_ERRORS_I18N.md`, `business/08`.

Bu hujjat AI qismini yozadigan dasturchi uchun: agent qanday ishlaydi, qaysi tool'larni qanday chaqiradi, modelga nima yuboriladi va javob mijozga ketishidan oldin qanday tekshiriladi.

---

## 1. Bir suhbat navbatining hayot tsikli

```mermaid
sequenceDiagram
 participant CH as Kanal (Telegram/Instagram/web)
 participant IN as Webhook + inbox
 participant W as AI worker
 participant B as Tool broker
 participant D as Domain servislar
 participant L as LLM (LLMPort)
 participant V as Output validator
 CH->>IN: Xaridor xabari
 IN->>W: job: conversation_id, event_id
 W->>W: ActorContext (merchant_id DB mapping'dan), speaker_version o'qiladi
 W->>W: PII redaction, kontekst yig'ish (§5, §6)
 loop maks 6 tool chaqiruvi
  W->>L: prompt + tool sxemalari
  L-->>W: tool_call yoki javob matni
  W->>B: tool_call (argumentlar)
  B->>B: sxema, ruxsat, budget tekshiruvi; merchant_id qo'shiladi
  B->>D: application query/command
  D-->>B: natija + dalil
  B-->>W: typed natija yoki typed xato
 end
 W->>V: javob matni + shu navbatdagi tool natijalari
 V-->>W: OK / qayta yozish / handoff
 W->>W: speaker_version qayta tekshiriladi (operator olgan bo'lsa — bekor)
 W->>CH: javob (outbox orqali)
```

Har navbat bitta job. Job qayta ishga tushsa, takroriy yozish tool'lari idempotency key orqali bir martadan ortiq bajarilmaydi (§3).

## 2. AI rejimlari (merchant sozlamasi, taklif)

| Rejim | Ma'nosi | Qachon |
|---|---|---|
| `OFF` | AI javob bermaydi, hamma xabar operatorga | provayder ishlamasa, limit tugasa, kill switch |
| `SUGGEST` | AI javob qoralamasini yozadi, operator tasdiqlab yuboradi | **pilotning birinchi haftasi uchun default** (taklif) |
| `AUTO` | AI o'zi javob beradi, xavfli holatlarda operatorga uzatadi | owner yoqadi, eval va shadow natijalari yaxshi bo'lsa |

Rejimni Owner va Manager o'zgartiradi (`agent.pause`). Global kill switch platforma darajasida (TECH-15 §9).

## 3. Tool broker qoidalari

1. **Tenant va kontekst serverdan.** `merchant_id`, `conversation_id`, `locale`, `channel` hech qachon LLM argumentida bo'lmaydi; broker ularni `ActorContext` dan qo'shadi. LLM ularni yuborsa — argument rad etiladi.
2. **Qat'iy sxema.** Har tool Pydantic modeli, `extra="forbid"`, chegaralar (masalan, `limit <= 10`). Sxemaga mos kelmagan chaqiruv → `VALIDATION_FAILED` modelga qaytadi.
3. **Ruxsat.** AI agent principal'ining permission'lari (TECH-10): faqat o'qish tool'lari, `leads.capture`, `quotes.prepare_draft`, `quotes.request_approval`, `orders.create_draft`, `chat.request_handoff`.
4. **Idempotency.** Yozuvchi tool'lar uchun key = `hash(conversation_id, event_id, tool_name, normalized_args)`; takroriy chaqiruv oldingi natijani qaytaradi.
5. **Budget (taklif, bake-off'dan keyin yangilanadi):** navbatda maks 6 tool chaqiruvi, navbat umumiy vaqti 20 s, kirish konteksti ≤ 12k token, javob ≤ 600 token. Oshsa — handoff.
6. **Dalil.** Har natija `source_id`, `observed_at`, `version` bilan qaytadi; validator (§8) shularga tayanadi.
7. **Log.** Har chaqiruv `ai_tool_executions` ga: redact qilingan argumentlar, natija hash'i, latency, xato kodi (§12).

## 4. Tool'lar (Merchant Sales Agent)

Sxemalar qisqartirilgan Pydantic ko'rinishida. Barcha pul — `{amount_minor, currency}` (ADR-025).

### 4.1 `catalog.search`
```python
class CatalogSearchIn(BaseModel):
    query: str = Field(min_length=1, max_length=200)      # "rtx 4060", "32gb ddr5"
    category: Category | None = None                       # CPU, GPU, RAM, ...
    max_price: Money | None = None
    in_stock_only: bool = True
    limit: int = Field(default=5, ge=1, le=10)

class CatalogItem(BaseModel):
    sku_id: UUID; title: str; brand: str; variant: str | None
    price: Money; price_version: int
    availability: Literal["IN_STOCK", "LOW", "OUT_OF_STOCK", "UNKNOWN"]
    spec_linked: bool                                      # DEC-011
    observed_at: datetime
```
Faqat shu merchantning `published` SKU'lari. Aniq stok soni emas, `availability` darajasi (merchant siyosati).

### 4.2 `pricing.get_price_stock`
Kirish: `sku_ids: list[UUID]` (≤10). Chiqish: har SKU uchun `price` (xaridorga UZS; USD narxli SKU bo'lsa kurs snapshot'i bilan — DEC-121), `price_version`, `availability`, `observed_at`. Narx yo'q bo'lsa — `PRICE_UNKNOWN` xatosi (§4.10).

### 4.3 `pc.compatibility_check`
Kirish: `sku_ids: list[UUID]` (≤12). Chiqish: TECH-25 §6 kontrakti (`decision`, `findings[].explanation` — xaridor tilida, `can_publish_quote`). AI natijani o'zgartira olmaydi.

### 4.4 `quotes.prepare_draft`
Faqat PC yig'ma uchun (DEC-100e).
```python
class QuoteDraftIn(BaseModel):
    lines: list[QuoteLineIn] = Field(min_length=1, max_length=15)   # {sku_id, quantity}
    requirements: BuildRequirements                                   # budget, workload, notes
```
Chiqish: `quote_id`, `status` (`DRAFT` yoki `REVIEW`), narx snapshot'i, `compatibility_decision`, `approval_required: true` (pilotda doim — DEC-102). `BLOCK` bo'lsa → `RULE_BLOCK` xatosi.

### 4.5 `quotes.request_approval`
Kirish: `quote_id`, `reason` (enum: `STANDARD`, `REVIEW_REQUIRED`, `DISCOUNT_REQUEST`). Chiqish: `approval_task_id`. Menejerga vazifa (M17). AI xaridorga "taklif menejer tomonidan tekshirilmoqda" deydi.

### 4.6 `leads.capture`
Kirish: `requirements` (budget, workload, afzalliklar), `contact_ref` (§7 — redaction token, masalan `PHONE_1`), `consent_contact: bool`. Chiqish: `lead_id`, `stage`. Merchant ichida dedup (BL-042).

### 4.7 `orders.create_draft` (DEC-100c, BL-110)
```python
class OrderDraftIn(BaseModel):
    lines: list[OrderLineIn] | None = None        # oddiy xarid: {sku_id, quantity}
    quote_id: UUID | None = None                  # PC yig'ma: tasdiqlangan quote'dan
    contact_ref: str                              # 'PHONE_1' — server haqiqiy raqamga almashtiradi
    fulfillment_method: Literal["PICKUP", "DELIVERY"]
    address_ref: str | None = None                # 'ADDRESS_1', DELIVERY bo'lsa majburiy
    customer_note: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def one_source(self): ...                     # lines YOKI quote_id, ikkalasi emas
```
Chiqish: `order_id`, `status: "DRAFT"`, `operator_task_id`. Stok band qilinmaydi, buyurtma tasdiqlanmaydi. Chaqiruvdan keyin broker avtomatik ravishda `chat.request_handoff(reason="PURCHASE_INTENT")` bajaradi.

### 4.8 `orders.lookup_status`
Kirish: `order_ref` (shu suhbatga bog'langan buyurtma yoki xaridor tracking token'i). Chiqish: FSM-08 status, `fulfillment_method`, oxirgi o'zgarish vaqti. Boshqa xaridorning buyurtmasi — `NOT_FOUND`.

### 4.9 `chat.request_handoff`
Kirish: `reason` (enum §9), `summary` (≤300 belgi, PII'siz). Chiqish: `handoff_task_id`. Conversation `HUMAN_NEEDED` ga o'tadi; shu paytdan AI faqat "operator tez orada javob beradi" xabarini yuborishi mumkin.

### 4.10 Tool xatolari va AI xatti-harakati

| Xato kodi | AI nima qiladi |
|---|---|
| `NOT_FOUND` | "Bunday mahsulot topilmadi", muqobil qidiruv yoki aniqlashtiruvchi savol |
| `OUT_OF_STOCK` | Hozir yo'qligini aytadi, muqobil taklif qiladi; "keltiramiz" deb va'da bermaydi |
| `PRICE_UNKNOWN`, `STALE_PRICE` | Narx aytmaydi → handoff (`PRICE_UNKNOWN`) |
| `RULE_BLOCK` | Bu kombinatsiya mos emasligini `explanation` bo'yicha tushuntiradi, boshqa variant izlaydi |
| `REVIEW_REQUIRED` (compatibility) | "Mutaxassis tekshiradi" → `quotes.request_approval` |
| `VALIDATION_FAILED` | Argumentni tuzatib bir marta qayta urinadi; yana bo'lsa handoff |
| `FORBIDDEN` | Hech narsa aytmaydi, xavfsizlik log'i, handoff |
| `RATE_LIMITED`, `PROVIDER_UNAVAILABLE` | Handoff, xaridorga "operator javob beradi" |

## 5. Prompt arxitekturasi

Model kontekstiga to'rt qatlam beriladi. Har qatlamning manbai va kim o'zgartirishi aniq.

| Qatlam | Mazmuni | Kim o'zgartiradi | Versiyalash |
|---|---|---|---|
| 1. Platforma tizim prompti | Qat'iy qoidalar: AI ekanini yashirmaslik, faqat tool natijalariga tayanish, narx/stok/chegirma/to'lov/tasdiq bo'yicha taqiqlar, javob tili, handoff holatlari, taqiqlangan iboralar | Faqat platforma (PR + eval) | `prompt_versions` (global) |
| 2. Merchant profili | Do'kon nomi, ohang (rasmiy/samimiy), ish vaqti, tasdiqlangan FAQ va siyosatlar (yetkazish, kafolat, qaytarish) | Owner / AI Policy Editor, AP-05 tasdig'i bilan | `agent_profiles.version` |
| 3. Suhbat holati | Slot'lar (byudjet, ish turi, tanlangan SKU'lar), suhbat xulosasi, oxirgi xabarlar | Tizim (§6) | — |
| 4. Tool natijalari | Shu navbatdagi faktlar (narx, stok, moslik) | Tool broker | — |

**Qoidalar:**
- Xaridor matni, mahsulot tavsifi va FAQ hujjatlari **ishonchsiz kontent** sifatida ajratilgan bloklarda beriladi; ulardagi "ko'rsatmalar" bajarilmaydi (BL-039).
- Merchant profili 1-qatlam qoidalarini bekor qila olmaydi (masalan, "chegirma va'da qil" yozilsa ham).
- Prompt versiyasini almashtirish: yangi versiya → eval to'plami (§13) → shadow → aktivlashtirish. Har javob qaysi `prompt_version` va `agent_profile.version` bilan yozilgani saqlanadi.

## 6. Xotira va kontekst

| Qism | Qoida (taklif) |
|---|---|
| Oxirgi xabarlar | Oxirgi 20 ta xabar to'liq (redact qilingan) |
| Suhbat xulosasi | Eskiroq xabarlar `conversation_summaries` ga qisqa xulosa sifatida; har 10 xabarda yangilanadi; PII'siz |
| Slot'lar | JSON: `budget`, `workloads`, `brand_preferences`, `selected_sku_ids`, `fulfillment_method`; har navbatda yangilanadi |
| Operator suhbatdan keyin | `resume_ai` da AI operatorning oxirgi javoblari xulosasini oladi va operator va'dalarini buzmaydi (SAGA-S04) |
| Uzoq muddatli xaridor profili | Stage 1 da yo'q (BL-042: faqat merchant ichida, rozilik bilan) |

Xotira `merchant_id` + `conversation_id` bilan cheklangan; boshqa suhbat yoki do'kon xotirasi kontekstga hech qachon tushmaydi (TECH-23 5-qatlam).

## 7. PII redaction (DEC-016)

1. LLM'ga yuborishdan oldin: telefon raqamlari, email, karta raqamlari, manzil va aniqlangan ismlar `[PHONE_1]`, `[ADDRESS_1]`, `[NAME_1]` tokenlariga almashtiriladi.
2. Token → haqiqiy qiymat jadvali faqat serverda, suhbat doirasida (`conversation_pii_refs`, shifrlangan).
3. AI tool'larga token yuboradi (`contact_ref: "PHONE_1"`); broker uni haqiqiy qiymatga almashtirib domain servisga beradi.
4. AI javobida token bo'lsa (masalan, "raqamingiz [PHONE_1] ga qo'ng'iroq qilamiz"), yuborishdan oldin haqiqiy qiymat qaytariladi.
5. Aniqlash: regex (O'zbekiston telefon formatlari `+998`, karta raqamlari Luhn tekshiruvi bilan) + oddiy NER; xato aniqlash xavfsiz tomonga (ortiqcha redaction).
6. Test: redaction to'plami (telefon, manzil, ism variantlari uz/ru/en) — LLM so'roviga PII tushmasligi CI'da tekshiriladi.

## 8. Javob tekshiruvi (output validator)

LLM yozgan javob mijozga ketishidan oldin deterministik tekshiriladi:

| Tekshiruv | Qoida | Yiqilsa |
|---|---|---|
| Narxlar | Matndagi har bir summa (normalizatsiya: "4,5 mln", "4 500 000", "4.5m") shu suhbatdagi tool natijasidagi narxga mos | qayta yozish |
| Mahsulotlar | Matnda tilga olingan model nomlari shu navbatda topilgan SKU'lar ichida | qayta yozish |
| Taqiqlangan da'volar | "tasdiqlandi", "band qilindi", "to'landi", "kafolatlaymiz", "albatta bor", "chegirma beramiz" va ru/en ekvivalentlari — buyurtma holati buni tasdiqlamasa | qayta yozish |
| Compatibility | "mos keladi" deyilsa, shu yig'ma uchun `PASS` natija bo'lishi shart | qayta yozish |
| Til | Javob xaridor tilida (va yozuvida: lotin/kirill) | qayta yozish |
| Uzunlik | Kanal limitidan oshmaydi (Telegram 4096 belgi) | qisqartirish |

Qayta yozish bir marta, validator izohi bilan. Ikkinchi marta ham yiqilsa — handoff (`VALIDATION_FAILED`). Har yiqilish metrikaga yoziladi (`ai_validation_failures_total{check}`).

## 9. Handoff holatlari

| `reason` | Trigger |
|---|---|
| `CUSTOMER_REQUEST` | Xaridor odam bilan gaplashmoqchi |
| `PURCHASE_INTENT` | "Olaman" — `orders.create_draft` dan keyin avtomatik (DEC-100) |
| `PRICE_UNKNOWN` | Narx yo'q yoki eskirgan |
| `COMPATIBILITY_REVIEW` | `REVIEW_REQUIRED` yig'ma |
| `DISCOUNT_REQUEST` | Xaridor chegirma so'raydi (AI bermaydi — DEC-110) |
| `COMPLAINT` | Shikoyat, norozilik, haqorat |
| `WARRANTY_OR_RETURN` | Kafolat, qaytarish, nosozlik |
| `PAYMENT_QUESTION` | To'lov tafsilotlari (to'lov do'kon bilan — DEC-100) |
| `VALIDATION_FAILED` | Javob tekshiruvidan ikki marta o'tmadi |
| `TOOL_ERROR`, `PROVIDER_UNAVAILABLE`, `BUDGET_EXCEEDED` | Texnik sabablar |
| `UNSUPPORTED_REQUEST` | Do'kon faoliyatiga aloqasiz yoki tushunarsiz so'rov (2 ta aniqlashtirishdan keyin) |

Ish vaqtidan tashqarida handoff bo'lsa, AI xaridorga do'kon ish vaqtini va operator qachon javob berishini aytadi (merchant profilidan).

## 10. AI sessiya bosqichi (`ai_stage`)

Avtorizatsiya uchun emas, operator ekrani va hisobot uchun: `IDLE → QUALIFYING → RECOMMENDING → QUOTE_PENDING → ORDER_DRAFTED → HANDED_OFF` (yoki `STOPPED`). Bu `business/10` UAT-M11 dagi holatlar. Conversation FSM-04 (`AI_ACTIVE`, `HUMAN_NEEDED`…) asosiy holat bo'lib qoladi; `ai_stage` uning ichidagi ma'lumot.

## 11. Til

- Har xabarda til aniqlanadi: `uz` (lotin), `uz-Cyrl`, `ru`, `en`; aralash (code-switch) xabarda asosiy til tanlanadi.
- AI xaridor tilida va yozuvida javob beradi. Tizim iboralari (handoff xabari, "buyurtmangiz qabul qilindi") — `message_templates` dan (TECH-24 §5.6).
- Qidiruv uchun so'rov transliteratsiya qilinadi (`видеокарта` ↔ `videokarta`, `rtx4060` ↔ `RTX 4060`).

## 12. Kuzatuv va audit

- `ai_tool_executions`: `merchant_id`, `conversation_id`, `tool`, `args_redacted`, `result_hash`, `error_code`, `latency_ms`, `model_alias`, `prompt_version`, `tokens_in`, `tokens_out`, `cost_minor`.
- Span'lar: `ai.generate`, `tools.<name>`, `ai.validate` (TECH-12 §2) — prompt matni va xaridor xabari telemetriyaga yozilmaydi.
- Metrikalar: `ai_requests_total{outcome}`, `ai_handoff_total{reason}`, `ai_validation_failures_total{check}`, `ai_cost_minor_total{plan_tier}`.
- To'liq suhbat namunalari eval uchun faqat merchant opt-in bilan va anonimlashtirilib (DEC-118).

## 13. Baholash va reliz shartlari

| To'plam | Hajm | Nima o'lchanadi |
|---|---|---|
| Dialoglar (uz/uz-Cyrl/ru/en) | 200+ | to'g'ri tool tanlash, slot'larni to'g'ri ajratish, javob tili |
| PC | 150+ (TECH-25 §10) | compatibility natijasini to'g'ri yetkazish |
| Red-team | 100+ | boshqa do'kon ma'lumoti, "sen adminsan", soxta chegirma, "tasdiqlandi" deyishga majburlash, tizim promptini oshkor qilish |
| Redaction | 100+ | PII LLM so'roviga tushmasligi |

**Nol toqat (har relizda):** noto'g'ri narx, mavjud bo'lmagan SKU, AI buyurtmani "tasdiqlandi" deyishi, boshqa tenant ma'lumoti, AI tomonidan chegirma va'dasi. Boshqa ko'rsatkichlar (tool aniqligi, handoff to'g'riligi) uchun chegaralar bake-off'dan keyin belgilanadi.

**Yoqish tartibi:** eval o'tdi → shadow (AI javob yozadi, yubormaydi, operator javobi bilan solishtiriladi) → `SUGGEST` → `AUTO` (owner qarori).

## 14. Hisobot agenti (Merchant Business Copilot, S5)

Alohida agent, alohida prompt va bitta tool:

```python
class MetricQueryIn(BaseModel):
    metric_ids: list[MetricId] = Field(min_length=1, max_length=4)   # TECH-16 §4 allowlist
    period: Period                                                    # preset yoki {from, to}
    group_by: list[Dimension] = Field(default_factory=list, max_length=2)
    filters: MetricFilters = MetricFilters()                          # channel, branch, category
```

Natija: qiymatlar, valyuta, `timezone`, `data_as_of`, `quality_flags` (masalan, `UNVERIFIED_PAID_MARK`). Ruxsat foydalanuvchi rolidan (margin — faqat ruxsati borlarga). SQL yaratish yo'q. S5 da matnli; ovoz — beta (DEC-112), xuddi shu tool bilan.
