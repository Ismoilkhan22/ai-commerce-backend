# 02 — Papka tuzilmasi (to'liq)

> **Versiya:** v2 (2026-10-22). DEC-004 C, ADR-031, ADR-035.
> Bu — `app/` papkasining chizmasi. Har faylning maqsadi yozilgan. Papkalar **slice bo'yicha** yaratiladi (`27-roadmap-and-tasks.md`), hammasi birdan emas.

## 1. Backend repo

```
ai-commerce-backend/
│
├── app/
│   ├── main.py                              # FastAPI lifespan, middleware, DomainManifest'lardan router mount
│   ├── dependencies.py                      # Composition root: Query Port implementatsiyalari, DI provider'lar
│   │                                        # (domenlarni import qila oladigan YAGONA joy, workers bilan birga)
│   ├── config/
│   │   ├── settings.py                      # Pydantic BaseSettings (.env)
│   │   └── logging.py                       # structlog JSON
│   │
│   ├── shared/                              # ✅ Poydevor — hech kimni import qilmaydi
│   │   ├── db/
│   │   │   ├── base.py                      # Declarative base, naming convention
│   │   │   ├── session.py                   # get_db() / get_read_db(); tranzaksiyada set_config('app.shop_id')
│   │   │   ├── mixins.py                    # IdMixin (UUIDv7), TimestampMixin, ShopScopedMixin (shop_id NOT NULL)
│   │   │   └── advisory_lock.py             # PostgreSQL advisory lock helper
│   │   ├── events/
│   │   │   ├── envelope.py                  # EventEnvelope (K-08)
│   │   │   ├── outbox.py                    # OutboxEvent ORM (har schemada) + write_outbox(db, event)
│   │   │   └── registry.py                  # @subscribe("commerce.order.confirmed") registry
│   │   ├── contracts/                       # ⭐ Domenlararo kontraktlar (faqat interfeys va DTO)
│   │   │   ├── catalog.py                   # CatalogQueryPort + DTO'lar
│   │   │   ├── commerce.py                  # CommerceQueryPort + DTO'lar
│   │   │   ├── messaging.py                 # MessagingQueryPort + DTO'lar
│   │   │   └── events/                      # Boshqa domen tinglaydigan event payload'lari
│   │   │       ├── catalog.py               # ProductPublishedV1, PriceChangedV1, ...
│   │   │       ├── commerce.py              # OrderDraftedV1, OrderConfirmedV1, StockChangedV1, ...
│   │   │       ├── messaging.py             # MessageReceivedV1, ConversationHandedOffV1, ...
│   │   │       └── sales_ai.py              # ReplyReadyV1, OrderDraftRequestedV1, ...
│   │   ├── errors/
│   │   │   ├── base.py                      # DomainError ierarxiyasi, ErrorCode
│   │   │   └── handlers.py                  # Global exception handler → K-07 envelope
│   │   ├── i18n/
│   │   │   ├── middleware.py                # Accept-Language → uz/ru/en
│   │   │   ├── translator.py                # t("error.ORDER_NOT_FOUND", lang, **params)
│   │   │   └── locales/{uz,ru,en}.yml
│   │   ├── tracing/
│   │   │   ├── middleware.py                # RequestContextMiddleware (request_id, traceparent)
│   │   │   ├── context.py                   # contextvars: trace_id, shop_id, actor_id → structlog
│   │   │   └── otel.py                      # OpenTelemetry → Grafana Cloud
│   │   ├── logging/filters.py               # PII va secret maskalash
│   │   ├── observability/
│   │   │   ├── metrics.py                   # OTel metrikalar (counter, histogram)
│   │   │   └── health.py                    # /health/live, /health/ready
│   │   ├── cache/
│   │   │   ├── redis_client.py              # Redis pool
│   │   │   ├── keys.py                      # cos:v1:shop:{shop_id}:... (shop prefiksi majburiy)
│   │   │   └── stampede.py                  # single-flight
│   │   ├── idempotency/
│   │   │   ├── store.py                     # (shop_id, operation, key) — PostgreSQL
│   │   │   └── dependency.py                # Depends(get_idempotency_key)
│   │   ├── money.py                         # Money(amount_minor, currency), exponent (ADR-025)
│   │   └── types/
│   │       ├── actor.py                     # ActorContext(principal_id, shop_id, roles, branch_ids, surface)
│   │       ├── manifest.py                  # DomainManifest
│   │       └── state.py                     # StateMachineRule
│   │
│   ├── platform/                            # ✅ Domenlararo xizmatlar — domains'ni import qilmaydi
│   │   ├── auth/                            # login, refresh rotation (ADR-023), sessiyalar, WS ticket
│   │   │   ├── api/  services/  repository/  models/  tests/
│   │   ├── shops/                           # Shop (FSM-01), filiallar, subdomen, shop sozlamalari (shop_policy)
│   │   ├── staff/                           # principal, membership, rollar, ruxsat katalogi, guard.py
│   │   │   └── infrastructure/guard.py      # require_permission("commerce.order.confirm")
│   │   ├── use/                             # ⚡ Slim USE: validate_transition + log_transition + idempotency
│   │   │   ├── services/use_service.py
│   │   │   ├── infrastructure/rules_loader.py   # DomainManifest'lardan state rule'larni yig'adi
│   │   │   └── models/orm.py                # schema=platform: TransitionLog
│   │   ├── audit/                           # schema=audit: append-only, oyma-oy partition
│   │   ├── notifications/                   # shablonlar (19-…), xaridor/xodimga yuborish, xodim vazifalari
│   │   ├── storage/                         # S3 adapter (MinIO), signed URL
│   │   ├── realtime/                        # /ws, ConnectionManager, Redis pub/sub relay
│   │   ├── llm/                             # LLMPort, provayder adapterlari, redaction, xarajat hisobi
│   │   └── billing/                         # tarif, AI limitlari, ishlatilish (DEC-119)
│   │
│   ├── domains/                             # ❌ Domen → domen import TAQIQ
│   │   ├── catalog/
│   │   │   ├── __init__.py                  # DOMAIN_MANIFEST
│   │   │   ├── domain_manifest.py
│   │   │   ├── permissions.py               # catalog.product.edit, catalog.price.change, ...
│   │   │   ├── events.py                    # chiqaradigan va tinglaydigan event'lar ro'yxati
│   │   │   ├── subscribers.py
│   │   │   ├── query_port.py                # CatalogQueryPort implementatsiyasi (shared/contracts/catalog.py)
│   │   │   ├── products/
│   │   │   │   ├── api/routers.py           # surface=shop: /products ; surface=storefront: yo'q (storefront domeni)
│   │   │   │   ├── services/product_service.py
│   │   │   │   ├── repository/product_repo.py
│   │   │   │   ├── models/{orm.py,schemas.py}   # schema=catalog
│   │   │   │   ├── state_machine.py         # FSM-02: DRAFT → PUBLISHED → HIDDEN → ARCHIVED
│   │   │   │   └── tests/
│   │   │   ├── pricing/                     # narx versiyalari, kurs, chegirma qoidalari
│   │   │   ├── pc_specs/                    # reference_hardware_spec, SKU bog'lash
│   │   │   ├── compatibility/               # PC moslik engine (17-…), qoidalar versiyasi
│   │   │   └── imports/                     # katalog importi (18-…), jobs/
│   │   │
│   │   ├── commerce/
│   │   │   ├── __init__.py  domain_manifest.py  permissions.py  events.py  subscribers.py  query_port.py
│   │   │   ├── inventory/                   # stock_balance, stock_ledger, reservation (FSM-07), tez sotuv
│   │   │   ├── leads/                       # FSM-05
│   │   │   ├── quotes/                      # FSM-06, narx va moslik snapshot'i
│   │   │   └── orders/                      # FSM-08; services/ ichida confirm (inventory bilan bitta TX)
│   │   │       └── services/jobs/           # eslatmalar (24/72 soat), muddati o'tgan band qilishlar
│   │   │
│   │   ├── messaging/
│   │   │   ├── channels/                    # FSM-03; adapters/{telegram,instagram,webchat}.py
│   │   │   └── conversations/               # FSM-04, xabarlar, speaker_mode/speaker_version, handoff
│   │   │
│   │   ├── sales_ai/
│   │   │   ├── agent/                       # orkestrator, tool broker, javob tekshiruvi (14-…)
│   │   │   │   └── tools/                   # catalog.search, catalog.get_price_stock, commerce.create_order_draft, ...
│   │   │   └── knowledge/                   # agent profili, FAQ, siyosatlar (versiyalangan)
│   │   │
│   │   ├── storefront/
│   │   │   ├── sites/                       # sayt sozlamalari, sahifalar
│   │   │   └── public_catalog/              # surface=storefront: mahsulotlar ro'yxati (CatalogQueryPort + kesh)
│   │   │
│   │   ├── support/
│   │   │   └── cases/                       # FSM-11
│   │   │
│   │   └── reporting/
│   │       ├── metrics/                     # metrika registri (19-…)
│   │       ├── read_models/                 # event'lardan proyeksiyalar (projections/)
│   │       └── assistant/                   # hisobot yordamchisi (matn; ovoz — beta)
│   │
│   ├── workers/                             # Alohida jarayonlar (bitta image, boshqa buyruq)
│   │   ├── outbox_worker.py                 # outbox → subscriber'lar va arq navbati
│   │   ├── task_worker.py                   # arq WorkerSettings
│   │   ├── scheduler_worker.py              # APScheduler + advisory lock leader
│   │   └── tasks/                           # arq task'lari (domen service'larini chaqiradi)
│   │       ├── channel_send.py              # Telegram/Instagram/web chat'ga yuborish
│   │       ├── ai_reply.py
│   │       ├── catalog_import.py
│   │       └── notifications.py
│   │
│   ├── db/
│   │   ├── schemas.sql                      # CREATE SCHEMA ...; rollar app_runtime (NOBYPASSRLS), app_migrator
│   │   ├── migrations/                      # Alembic — har schema uchun env
│   │   │   ├── platform/  audit/  catalog/  commerce/  messaging/
│   │   │   ├── sales_ai/  storefront/  support/  reporting/
│   │   └── seed/
│   │       ├── platform_seed.py             # rollar, ruxsatlar, platforma admini
│   │       └── dev_seed.py                  # sintetik shop, katalog (haqiqiy PII yo'q)
│   │
│   └── tests/
│       ├── architecture/                    # import-linter, chegara testlari
│       ├── isolation/                       # TC-ISO-01…10 (A shop / B shop matritsasi)
│       ├── concurrency/                     # TC-002, TC-027, TC-030
│       ├── integration/
│       ├── ai_eval/                         # golden set (16-…)
│       └── e2e/
│
├── deploy/
│   ├── docker/Dockerfile                    # bitta image: api | outbox-worker | task-worker | scheduler
│   ├── docker-compose.yml                   # lokal: PostgreSQL 16, Redis 7, MinIO
│   ├── docker-compose.prod.yml
│   ├── nginx/default.conf                   # *.platforma.uz, TLS, rate limit
│   └── backup/                              # pg_dump/PITR skriptlari, tiklash mashqi
│
├── scripts/
│   ├── check_architecture.py                # import-linter wrapper
│   ├── create_audit_partitions.py
│   └── seed_dev.py
│
├── pyproject.toml                           # uv, ruff, mypy, pytest, import-linter
├── .importlinter                            # qatlam va domen kontraktlari
├── alembic.ini                              # multi-env
├── .env.example
└── docs/                                    # business, discovery, engineering, decisions, modules
```

---

## 2. Muhim fayllar mas'uliyati

### `app/main.py`
- Lifespan (DB, Redis, OTel ishga tushadi va to'xtaydi)
- Middleware zanjiri (`01` §5)
- `app/domains/*/DOMAIN_MANIFEST` larni avtomatik topadi va router'larni surface prefiksi bilan ulaydi
- `/health/*`
- **Biznes logika yo'q**

### `app/dependencies.py` — composition root
Domenlararo Query Port'lar shu yerda ulanadi:
```python
def get_catalog_query() -> CatalogQueryPort:          # interfeys: app/shared/contracts/catalog.py
    from app.domains.catalog.query_port import CatalogQueryPortImpl
    return CatalogQueryPortImpl()
```
`sales_ai` faqat `CatalogQueryPort` interfeysini biladi, `catalog` kodini import qilmaydi. import-linter'da `app.dependencies` va `app.workers` — domenlarni import qilishga ruxsat berilgan yagona modullar.

### `app/shared/types/manifest.py`
```python
DOMAIN_MANIFEST = DomainManifest(
    name="commerce",
    schema_name="commerce",
    routers={                                   # surface → router (ADR-024)
        "shop": commerce_shop_router,           # /api/v1/shop/orders, /inventory, /quotes, /leads
        "storefront": commerce_storefront_router,  # /api/v1/storefront/{slug}/order-requests
    },
    state_machine_rules=[*ORDER_RULES, *RESERVATION_RULES, *QUOTE_RULES, *LEAD_RULES],
    event_subscribers=[on_order_draft_requested, on_quote_draft_requested],
    scheduled_jobs=[order_reminders_job, reservation_expiry_job, quote_expiry_job],
    permissions=COMMERCE_PERMISSIONS,
)
```

### `app/platform/use/services/use_service.py`
Faqat 3 ish (ADR-034):
```python
class UseService:
    async def validate_transition(entity_type, from_status, to_status, command) -> StateMachineRule
    async def log_transition(entity_type, entity_id, from_status, to_status, actor, reason, db) -> None
    async def force_transition(...)            # faqat platforma admini, sabab va audit bilan
```
Notification, AI, Telegram — boshqa joyda.

### `app/domains/<X>/<sub>/state_machine.py`
Lokal holat qoidalari (`../business/05` dagi strelkalar). USE ularni boot vaqtida yig'adi.

### `app/workers/*`
- `outbox_worker` — `outbox_events` ni `FOR UPDATE SKIP LOCKED` bilan oladi, subscriber'larni chaqiradi yoki arq'ga vazifa qo'yadi, keyin `published_at` belgilaydi.
- `task_worker` — arq: tashqi chaqiruvlar (LLM, Telegram, Meta), import, xabarnomalar.
- `scheduler_worker` — APScheduler; advisory lock bilan bitta leader. Og'ir ishni o'zi qilmaydi — arq'ga qo'yadi.

Batafsil: [06-background-jobs.md](06-background-jobs.md).

---

## 3. import-linter kontraktlari

```ini
[importlinter:contract:layers]
name = shared -> platform -> domains
type = layers
layers =
    app.domains
    app.platform
    app.shared

[importlinter:contract:domains-independent]
name = Domenlar bir-birini import qilmaydi
type = independence
modules =
    app.domains.catalog
    app.domains.commerce
    app.domains.messaging
    app.domains.sales_ai
    app.domains.storefront
    app.domains.support
    app.domains.reporting
```
`app.dependencies` va `app.workers` qatlamlardan tashqarida (composition root).

---

## 4. Yangi domen qo'shish (minimal)

```bash
DOMAIN=support
mkdir -p app/domains/$DOMAIN/cases/{api,services,repository,models,tests}
mkdir -p app/db/migrations/$DOMAIN
touch app/domains/$DOMAIN/{__init__,domain_manifest,permissions,events,subscribers}.py
echo "CREATE SCHEMA IF NOT EXISTS $DOMAIN;" >> app/db/schemas.sql
alembic -n $DOMAIN revision -m init
```
So'ng `.importlinter` dagi `domains-independent` ro'yxatiga qo'shiladi va [03-module-requirements.md](03-module-requirements.md) checklisti to'ldiriladi.

---

## 5. Frontend repo (qisqacha)

```
ai-commerce-frontend/
├── apps/
│   ├── shop-dashboard/          # app.<platforma>.uz — xodimlar paneli
│   └── shop-storefront/         # <shop>.<platforma>.uz — shop sayti
├── packages/
│   ├── ui/  i18n/  auth/
│   └── api-client/              # OpenAPI'dan generatsiya, qo'lda yozilmaydi
└── e2e/
```
Batafsil: [21-frontend.md](21-frontend.md).

## 6. Keyingi qadam

→ [03-module-requirements.md](03-module-requirements.md)
