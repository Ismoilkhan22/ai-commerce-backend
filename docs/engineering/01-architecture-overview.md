# 01 — Arxitektura umumiy ko'rinishi

> **Versiya:** v2 (2026-10-22). Eski `03_DDD_DOMAIN_ARCHITECTURE` va `04_SYSTEM_ARCHITECTURE_C4` o'rnini bosadi.
> **Kim o'qiydi:** hamma dasturchi.

## 1. Uchta qatlam (qat'iy)

```
┌────────────────────────────────────────────────────────────────────┐
│ domains/   (biznes)                                                │
│  catalog · commerce · messaging · sales_ai · storefront · support  │
│  · reporting           [keyin: payments · fulfillment · network ·  │
│                         marketplace]                               │
│                    ↓ import qila oladi                             │
│  ┌──────────────────────────────────────────────────────────────┐  │
│  │ platform/   (domenlararo xizmatlar)                          │  │
│  │  auth · shops · staff · use · audit · notifications ·        │  │
│  │  storage · realtime · llm · billing                          │  │
│  └──────────────────────────────────────────────────────────────┘  │
│                    ↓ import qila oladi                             │
│  ┌──────────────────────────────────────────────────────────────┐  │
│  │ shared/   (poydevor)                                         │  │
│  │  db · events · contracts · errors · i18n · tracing · cache · │  │
│  │  idempotency · money · types                                 │  │
│  └──────────────────────────────────────────────────────────────┘  │
└────────────────────────────────────────────────────────────────────┘

shared      → hech kimni import qilmaydi
platform    → shared, boshqa platform modullari
domains/X   → shared, platform; domains/Y — TAQIQ
Domenlar orasida: yozish = event (outbox), o'qish = Query Port
```

---

## 2. Domenlar va biznes modullar

Har domen — bitta bounded context, o'z PostgreSQL schemasi bilan (ADR-035). Ichida sub-modullar (bismuth'dagi `requests/`, `offers/` kabi) bir-biriga to'g'ridan-to'g'ri murojaat qila oladi.

### Platform (Stage 1)

| Modul | Biznes modullar | Nima qiladi | Schema |
|---|---|---|---|
| `auth` | M02 | Login, access/refresh token (ADR-023), sessiyalar, WS ticket | `platform` |
| `shops` | M01, M03 | Shop (tenant) va uning holati (FSM-01), filiallar, ish vaqti, subdomen | `platform` |
| `staff` | M02 | Xodimlar (principal), a'zolik, rollar, ruxsatlar, filial doirasi (`../business/04`) | `platform` |
| `use` | — | Holat o'tishini tekshirish, o'tishlar jurnali, idempotency (slim USE, ADR-034) | `platform` |
| `audit` | M20 | Append-only o'zgarishlar tarixi | `audit` |
| `notifications` | M17 | Xabar shablonlari, xaridor va xodimga yuborish, xodim vazifalari | `platform` |
| `storage` | — | Fayllar (rasm, import fayli), signed URL | `platform` |
| `realtime` | — | WebSocket (inbox), Redis pub/sub orqali ko'p worker | — |
| `llm` | — | `LLMPort` adapter, PII redaction, AI xarajati hisobi (ADR-027) | `platform` |
| `billing` | M19 | Tarif, AI limitlari va ishlatilishi (DEC-119) | `platform` |

### Domenlar (Stage 1)

| Domen | Biznes modullar | Sub-modullar | Schema |
|---|---|---|---|
| `catalog` | M04, M05, M08 | `products` (mahsulot, SKU, rasm, saytga chiqarish), `pricing` (narx versiyalari, kurs, chegirma qoidalari), `pc_specs` (texnik ma'lumotlar kutubxonasi, SKU bog'lash), `compatibility` (PC moslik engine) | `catalog` |
| `commerce` | M06, M12, M13 | `inventory` (qoldiq, band qilish, tez sotuv, ledger), `leads`, `quotes` (PC taklif), `orders` | `commerce` |
| `messaging` | M09, M10 | `channels` (Telegram, Instagram, sayt chati), `conversations` (inbox, xabarlar, kim javob beradi, handoff) | `messaging` |
| `sales_ai` | M11, M19 (AI sozlamalari) | `agent` (AI sotuvchi, tool broker), `knowledge` (FAQ, siyosatlar, agent profili) | `sales_ai` |
| `storefront` | M07 | `sites` (sayt sozlamalari, sahifalar), `public_catalog` (saytda ko'rinadigan katalog proyeksiyasi) | `storefront` |
| `support` | M16 | `cases` (kafolat va qaytarish murojaatlari) | `support` |
| `reporting` | M18 | `metrics` (metrika registri), `read_models` (event'lardan proyeksiyalar), `assistant` (hisobot yordamchisi, ovoz — beta) | `reporting` |

**Keyinroq:** `payments` (M14, DEFERRED, DEC-100), `fulfillment` (M15, DEFERRED, DEC-113), `network` (M21–M30, Stage 2), `marketplace` (M31–M39, Stage 3). M25 (ko'p filialli ombor) — `commerce`, M27 (AI bilim markazi) — `sales_ai`. To'liq jadval — [29-traceability.md](29-traceability.md).

### Nega `commerce` bitta domen (DEC-126)

Buyurtmani tasdiqlash va mahsulotni band qilish **bitta tranzaksiyada** bo'lishi shart: oxirgi mahsulotga ikki operator bir vaqtda tasdiq bossa, faqat bittasi o'tadi (TC-002, TC-027). Agar ombor va buyurtma alohida domen bo'lsa, buni faqat event (saga) bilan qilish mumkin — operator "tasdiqlandi" ko'rib, keyin "mahsulot yo'q" bo'lib qoladi. Shuning uchun ular bitta domenda, `quotes` va `leads` ham (taklif → buyurtma o'tishi ichkarida).

---

## 3. Domenlar orasidagi aloqa

| Kerak | Usul | Misol |
|---|---|---|
| Domen ichida o'qish/yozish | To'g'ridan-to'g'ri (repository, service) | `orders` service `inventory` repository'ni chaqiradi |
| Boshqa domendan **o'qish** (kam) | **Query Port** — interfeys `shared/contracts/<domain>.py`, implementatsiya egasi domenda | `sales_ai` → `CatalogQueryPort.search()`, `CommerceQueryPort.get_availability()` |
| Boshqa domendan **o'qish** (ko'p, tez) | **Local read model** — event'lardan proyeksiya | `reporting` buyurtmalar proyeksiyasi |
| Boshqa domenda **yozish** | **Event** (outbox) → u domendagi subscriber | `sales_ai.order_draft.requested` → `commerce` qoralama yaratadi |
| Platform xizmatini ishlatish | To'g'ridan-to'g'ri (domen platform'ni import qila oladi) | `commerce` → `platform.audit.record(...)`, `platform.notifications.request(...)` |

Batafsil: [05-events-and-outbox.md](05-events-and-outbox.md), ADR-032.

### Asosiy oqimlar orasidagi event'lar (Stage 1)

```
messaging ──messaging.message.received──▶ sales_ai      (AI javob tayyorlaydi)
sales_ai  ──sales_ai.reply.ready────────▶ messaging     (speaker_version tekshirib yuboradi)
sales_ai  ──sales_ai.handoff.requested──▶ messaging     (suhbat operatorga)
sales_ai  ──sales_ai.order_draft.requested─▶ commerce   (DRAFT buyurtma)
sales_ai  ──sales_ai.quote_draft.requested─▶ commerce   (taklif qoralamasi)
commerce  ──commerce.order.*────────────▶ messaging, reporting, support
catalog   ──catalog.product.published / catalog.price.changed──▶ storefront, reporting
commerce  ──commerce.stock.changed──────▶ storefront    (kesh yangilanadi)
messaging ──messaging.conversation.*────▶ reporting
```

Notification va audit — event emas: domen o'z service'ida platform xizmatini chaqiradi (audit — o'sha tranzaksiyada; notification — `platform.notifications.request()` outbox orqali).

---

## 4. Komponentlar (deployment ko'rinishi)

```
             Xaridor (Telegram, Instagram, sayt)        Shop xodimi (dashboard)
                        │                                       │
                        ▼                                       ▼
┌──────────────────────────────────────────────────────────────────────────┐
│ Nginx — TLS, rate limit, *.platforma.uz subdomenlar                      │
└───────────────┬──────────────────────────────────────────┬───────────────┘
                ▼                                          ▼
┌──────────────────────────────┐            ┌──────────────────────────────┐
│ API (uvicorn ×N, stateless)  │            │ Frontend (Next.js) — alohida │
│ /api/v1/shop, /storefront,   │            │ repo: dashboard + storefront │
│ /webhooks, /platform, /ws    │            └──────────────────────────────┘
└──────┬───────────────┬───────┘
       │               │
       ▼               ▼
┌──────────────┐  ┌──────────────────────────────┐
│ PostgreSQL   │  │ Redis (AOF)                  │
│ schemas:     │  │ kesh · rate limit · arq      │
│ platform     │  │ navbat · pub/sub (WS)        │
│ audit        │  └──────────────┬───────────────┘
│ catalog      │                 │
│ commerce     │◀───────┐        │
│ messaging    │        │        │
│ sales_ai     │  ┌─────┴────────▼──────────┐   ┌─────────────────────────┐
│ storefront   │  │ outbox_worker           │──▶│ task_worker (arq ×2–3)  │
│ support      │  │ outbox → subscriber'lar │   │ AI javob, Telegram/Meta │
│ reporting    │  │ va arq navbati          │   │ yuborish, import,       │
└──────────────┘  └─────────────────────────┘   │ xabarnoma               │
                  ┌─────────────────────────┐   └───────────┬─────────────┘
                  │ scheduler_worker        │               │
                  │ APScheduler + advisory  │               ▼
                  │ lock: eslatmalar, taklif│   ┌─────────────────────────┐
                  │ muddati, tozalash       │   │ Tashqi: Telegram, Meta, │
                  └─────────────────────────┘   │ LLM, MinIO (S3)         │
                                                └─────────────────────────┘
Telemetriya: OpenTelemetry + structlog → Grafana Cloud; xatolar → Sentry (PII'siz)
```

Hammasi bitta repo'dan, bitta Docker image'dan, turli buyruq bilan ishga tushadi (`api`, `outbox-worker`, `task-worker`, `scheduler`). Batafsil: [22-infrastructure-and-deployment.md](22-infrastructure-and-deployment.md).

---

## 5. HTTP so'rov hayot sikli

```
1. Klient → Nginx (TLS, rate limit)
2. Nginx → API
3. Middleware (tartib bilan):
   ├── RequestContextMiddleware   — request_id, traceparent, structlog contextvars
   ├── I18nMiddleware             — Accept-Language → uz/ru/en
   ├── ExceptionHandlingMiddleware— DomainError → K-07 envelope (11-…)
   └── SurfaceAuthMiddleware      — surface bo'yicha: shop (JWT), storefront (anonim/sessiya),
                                    webhooks (imzo), platform (ichki)
4. Router dependency'lari:
   ├── get_actor_context()        — principal + shop_id + rollar (serverda, DB'dan)
   ├── require_permission("commerce.order.confirm")
   ├── get_idempotency_key()      — yozish amallarida majburiy
   └── get_db()                   — tranzaksiya ichida set_config('app.shop_id', …, true)
5. Service:
   async with db.begin():
       use.validate_transition(...)
       repo.update(...)
       use.log_transition(...)
       audit.record(...)
       outbox.write(event)
   # COMMIT
6. Javob (Pydantic DTO, hech qachon ORM emas)
```

Tashqi chaqiruv (LLM, Telegram) **hech qachon** 5-qadam ichida emas — outbox → worker orqali.

---

## 6. Muhim oqimlar

### 6.1 Xaridor xabari → AI javobi

```
Telegram webhook ──▶ messaging: imzo tekshiriladi, (provider, event_id) bo'yicha takror tekshiriladi,
                     xabar saqlanadi + outbox [messaging.message.received] ──▶ 200 OK (AI kutilmaydi)
outbox_worker ──▶ sales_ai subscriber ──▶ arq: ai_reply(conversation_id, speaker_version)
task_worker: AI ──▶ CatalogQueryPort / CommerceQueryPort (narx, qoldiq, moslik) ──▶ LLM
          ──▶ javob tekshiriladi (narx/qoldiq katalogdagi bilan mosmi) ──▶ outbox [sales_ai.reply.ready]
messaging subscriber: speaker hali ham AI va speaker_version o'zgarmaganmi?
          ├─ Ha  ──▶ arq: channel_send ──▶ Telegram
          └─ Yo'q (operator olgan) ──▶ javob tashlanadi (TC-009)
```

### 6.2 "Olaman" → qoralama → tasdiq

```
AI tool commerce.create_order_draft ──▶ outbox [sales_ai.order_draft.requested]
commerce subscriber ──▶ Order(DRAFT) + outbox [commerce.order.drafted]   (qoldiq o'zgarmaydi, TC-028)
messaging/notifications ──▶ operatorga vazifa, suhbat operatorga uzatiladi
Operator "Tasdiqlash" (Idempotency-Key) ──▶ commerce, BITTA tranzaksiya:
     qoldiq qatorlari FOR UPDATE (shop_id, branch_id, sku_id tartibida)
     available yetarlimi? ── yo'q ──▶ 409 INSUFFICIENT_AVAILABLE_STOCK
     narx o'zgarganmi?   ── ha  ──▶ 409 PRICE_CHANGED (TC-031)
     reservation ACTIVE + order PENDING_CONFIRMATION → CONFIRMED + transition log + audit + outbox
──▶ COMMIT ──▶ xaridorga xabar (notifications)
```

Batafsil: [12-concurrency-and-transactions.md](12-concurrency-and-transactions.md).

### 6.3 AI va operator bir vaqtda (fencing)

Operator "suhbatni olish" bosganda `conversation.speaker_version` atomik oshadi. Eski versiya bilan tayyorlangan AI javobi yuborilmaydi. Batafsil: `13-integrations-and-channels.md`, `14-ai-sales-agent-and-tools.md`.

---

## 7. API surface'lar (ADR-024, DEC-124)

| Prefiks | Kim | Auth | Misol |
|---|---|---|---|
| `/api/v1/shop/*` | Shop xodimlari (dashboard) | JWT + ruxsat | `POST /api/v1/shop/orders/{id}/confirm` |
| `/api/v1/storefront/{slug}/*` | Sayt xaridori | Anonim, signed sessiya | `POST /api/v1/storefront/{slug}/order-requests` |
| `/api/v1/webhooks/*` | Telegram, Meta | Imzo | `POST /api/v1/webhooks/telegram/{bot_id}` |
| `/api/v1/platform/*` | Platforma jamoasi | JWT + platform roli + audit | `POST /api/v1/platform/shops/{id}/activate` |
| `/api/v1/public/*` | Stage 3 | — | — |

URL'da domen nomi yo'q — domen ichki tushuncha. Har domen o'z `DomainManifest`'ida qaysi surface'ga qaysi router berishini e'lon qiladi (`02-folder-skeleton.md`). Batafsil: [11-api-conventions-errors-i18n.md](11-api-conventions-errors-i18n.md).

---

## 8. Ma'lumot egaligi qoidalari

1. Har jadvalning **bitta egasi** bor — bitta domen.
2. Boshqa domen u jadvalga yozmaydi, ORM modelini import qilmaydi, JOIN qilmaydi.
3. Tashqi integratsiya ma'lumoti normallashtirilmaguncha va tekshirilmaguncha haqiqat emas.
4. AI va qidiruv — **o'quvchi**, narx, qoldiq va buyurtmaning egasi emas.
5. Event payload'da minimal fakt va ID'lar; chat matni, shaxsiy ma'lumot, token — yo'q.

---

## 9. Stage 2 va 3 qanday qo'shiladi

- **Stage 2 (`network`):** yangi domen, o'z schemasi. Shop takliflarini `catalog`/`commerce` event'laridan proyeksiya qiladi (faqat shop roziligi bilan). Integratsiyalar (kassa, ERP) — anti-corruption adapterlar. `catalog`/`commerce` o'zgarmaydi.
- **Stage 3 (`marketplace`):** global qidiruv faqat `network` ning ommaviy proyeksiyasini o'qiydi; shopning xususiy jadvallariga yo'l yo'q. Xaridorning global AI'si `sales_ai` dan alohida.

Batafsil: [28-network-and-global-search.md](28-network-and-global-search.md).

## 10. Keyingi qadam

→ [02-folder-skeleton.md](02-folder-skeleton.md)
→ [03-module-requirements.md](03-module-requirements.md)
