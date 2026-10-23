# 03 — Har modulga qo'yiladigan majburiy talablar

> **Versiya:** v2 (2026-10-22). Bismuth v2 `03-module-requirements` asosida + shu loyihaga xos talablar (shop izolyatsiyasi, AI, i18n).
> Bu — **checklist**. Yangi domen yoki sub-modul qo'shganda har punkt tekshiriladi. **Bittasi buzilsa — review'da reject.**

---

## 1. Har domenga talablar

### 1.1 Tuzilma
- [ ] Domen `app/domains/<name>/` da
- [ ] `domain_manifest.py` da `DOMAIN_MANIFEST` to'liq (name, schema, routers, rules, subscribers, jobs, permissions, role_grants, privacy_handlers); `__init__.py` bo'sh
- [ ] Shaxsiy ma'lumot saqlasa — `privacy_handlers` (eksport, o'chirish, saqlash muddati tozalash) — `26-privacy-and-retention.md`
- [ ] Har sub-modul: `api/`, `services/`, `repository/`, `models/`, `state_machine.py` (holati bo'lsa), `tests/`
- [ ] `events.py` — chiqaradigan va tinglaydigan event'lar ro'yxati
- [ ] `permissions.py` — barcha ruxsat kodlari (`<domain>.<entity>.<action>`), `../business/04` jadvaliga mos
- [ ] `subscribers.py` — event handler'lar (`@subscribe`), bo'sh bo'lsa ham
- [ ] Boshqa domen o'qishi kerak bo'lsa — `query_port.py` (interfeys `app/shared/contracts/<name>.py` da)

### 1.2 Ma'lumotlar bazasi
- [ ] O'z PostgreSQL schemasi (`<name>`), o'z Alembic env'i (`app/db/migrations/<name>/`)
- [ ] Boshqa domen ORM'ini import qilmaydi (import-linter)
- [ ] Boshqa schema bilan FK va JOIN yo'q; boshqa domen obyekti — faqat `UUID`
- [ ] **Shop jadvallarida `shop_id UUID NOT NULL`** (`ShopScopedMixin`), birinchi ustun sifatida indekslarda
- [ ] Istisno — platforma yuritadigan umumiy ma'lumotnomalar (`catalog.reference_hardware_specs`, `catalog.pc_rulesets`, `catalog.build_profiles`, `catalog.currencies`): `shop_id` yo'q, shop xodimlari faqat o'qiydi, yozish — faqat platforma jamoasi. Har yangi istisno `07-data-layer.md` ro'yxatiga qo'shiladi
- [ ] Unikal cheklovlar shop doirasida: `UNIQUE (shop_id, sku_code)`
- [ ] Shop ichidagi bog'lanishlar composite FK bilan: `(shop_id, product_id) → products(shop_id, id)` — boshqa shop obyektiga bog'lab bo'lmaydi
- [ ] Sezgir jadvallarda RLS yoqilgan (`10-security-tenancy-rbac.md` ro'yxati)
- [ ] Pul — `*_minor BIGINT` + `currency CHAR(3)` (ADR-025)
- [ ] Enum qiymatlari `UPPER_SNAKE` (K-02)

### 1.3 Holat boshqaruvi
- [ ] Holati bor har entity uchun lokal `state_machine.py`; qoidalar `../business/05` dagi strelkalarga 1:1 mos
- [ ] Holat faqat service ichida o'zgaradi: `use.validate_transition()` → yangilash → `use.log_transition()`
- [ ] **Repository `status='X'` to'g'ridan-to'g'ri yozmaydi**
- [ ] Bir vaqtdagi o'zgarishlar uchun `version` ustuni (optimistic) yoki `FOR UPDATE` (pul/qoldiq) — `12-concurrency-and-transactions.md`

### 1.4 Idempotency
- [ ] Har yozish endpoint'i `Idempotency-Key` qabul qiladi (K-06)
- [ ] Service'da `idempotency.check_or_record(shop_id, operation, key)`
- [ ] Fon vazifalari va subscriber'lar deterministik kalit ishlatadi (`order_reminder:{order_id}:24h`, `on_event:{consumer}:{event_id}`)

### 1.5 Event'lar (outbox)
- [ ] Holat o'zgarishi → `outbox_events` ga ham yoziladi (bitta TX)
- [ ] Nomi: `<domain>.<entity>.<action>` o'tgan zamonda (`commerce.order.confirmed`)
- [ ] Payload — Pydantic model, `schema_version` bilan; boshqa domen tinglaydigan payload'lar `app/shared/contracts/events/<domain>.py` da
- [ ] Payload'da shaxsiy ma'lumot, chat matni, token yo'q — faqat ID va minimal fakt
- [ ] **Domenlararo yozish faqat event orqali**

### 1.6 Testlar
- [ ] Service unit testlari (har asosiy use case)
- [ ] Repository integratsiya testi (haqiqiy PostgreSQL, testcontainers)
- [ ] State machine testi — har ruxsat etilgan va taqiqlangan o'tish
- [ ] **Izolyatsiya testi** — A shop xodimi B shop obyektini ko'ra/o'zgartira olmaydi (TC-ISO)
- [ ] Ruxsat testi — rol jadvali (`../business/04`) bo'yicha
- [ ] Arxitektura testi (import-linter) o'tadi
- [ ] Coverage > 70% (domen service'larida > 85%)

### 1.7 Hujjat
- [ ] `docs/modules/<name>/README.md` — shablon: [../modules/README.md](../modules/README.md)
- [ ] Holatlar (strelkalar, `../business/05` ga havola)
- [ ] Event'lar ro'yxati (chiqaradi / tinglaydi)
- [ ] API endpoint'lar qisqacha
- [ ] Qaysi `BL-xxx` qoidalarni amalga oshiradi

### 1.8 Kuzatuv (observability)
- [ ] Log: `structlog.get_logger().bind(domain="commerce")`; `trace_id`, `shop_id` contextvars'dan avtomatik
- [ ] Muhim amal → counter: `cos_<domain>_<entity>_<action>_total` (platform modullari uchun `cos_<module>_...`, masalan `cos_llm_requests_total`; to'liq ro'yxat — `09-observability.md`) (masalan `cos_commerce_order_confirmed_total`)
- [ ] Davomiylik → histogram: `cos_<domain>_<operation>_duration_seconds`
- [ ] Asosiy operatsiyalarda OpenTelemetry span
- [ ] Logga PII yozilmaydi (`shared/logging/filters.py`)

### 1.9 Xatolar va tarjima
- [ ] Domen xatolari `DomainError` dan meros (`NotFoundError`, `ConflictError`, ...), kodlari error katalogida (`11-api-conventions-errors-i18n.md`)
- [ ] Har xato kodi uchun `uz`, `ru`, `en` tarjimasi `locales/` da
- [ ] Topilmagan va boshqa shopniki — bir xil javob: `404 NOT_FOUND` (TC-001)

---

## 2. Service talablari

### 2.1 Stateless konstruktor
```python
# ✅ TO'G'RI
class OrderService:
    def __init__(self, repo: OrderRepository, inventory: InventoryService, use: UseService, audit: AuditService):
        self.repo = repo
        self.inventory = inventory          # domen ichida — to'g'ridan-to'g'ri
        self.use = use
        self.audit = audit
```
```python
# ❌ NOTO'G'RI
class OrderService:
    cache: dict = {}                       # global holat
    def __init__(self, db: AsyncSession):
        self.db = db                       # session class field'da
```

### 2.2 Session va actor — method argumenti
```python
async def confirm(self, order_id: UUID, actor: ActorContext, idem_key: str, db: AsyncSession) -> OrderOut: ...
```
`shop_id` alohida parametr emas — `actor.shop_id` dan olinadi.

### 2.3 Tranzaksiya chegarasi aniq
```python
async def confirm(self, order_id, actor, idem_key, db):
    async with db.begin():
        await self.idempotency.check_or_record(actor.shop_id, "order.confirm", idem_key, db)
        order = await self.repo.get_for_update(actor.shop_id, order_id, db)
        rule = await self.use.validate_transition("commerce.order", order.status, "CONFIRMED", "CONFIRM")
        await self.inventory.reserve(actor.shop_id, order.lines, order.id, db)   # FOR UPDATE, deterministik tartib
        order.status = "CONFIRMED"
        await self.use.log_transition("commerce.order", order.id, rule, actor, db)
        await self.audit.record("commerce.order.confirmed", order.id, actor, db)
        await write_outbox(db, OrderConfirmedV1.from_order(order))
    # COMMIT shu yerda
```

### 2.4 Bloklovchi I/O yo'q
`requests`, `time.sleep` — TAQIQ. `httpx.AsyncClient`, `asyncio.sleep`.

### 2.5 So'rov ichida uzoq ish yo'q
LLM, Telegram, Meta, fayl qayta ishlash — outbox → arq. So'rov < 500 ms qaytadi.

---

## 3. Repository talablari

- [ ] Faqat DB so'rovlari, biznes qoida yo'q
- [ ] **Har so'rovda `shop_id` filtri** — repository metodlari birinchi argument sifatida `shop_id` oladi (RLS — ikkinchi qavat)
- [ ] Ro'yxatlar `selectinload`/`joinedload` bilan (N+1 yo'q)
- [ ] Har ro'yxat — limit bilan (cursor pagination, `11-…`); limitsiz ro'yxat TAQIQ
- [ ] `SELECT *` yo'q — kerakli ustunlar

```python
async def get(self, shop_id: UUID, order_id: UUID, db: AsyncSession) -> OrderORM | None:
    return (await db.execute(
        select(OrderORM).where(OrderORM.shop_id == shop_id, OrderORM.id == order_id)
    )).scalar_one_or_none()
```

---

## 4. API talablari

- [ ] Bitta resurs — bitta router; manzil surface prefiksi bilan (`/api/v1/shop/orders`)
- [ ] Pydantic input/output; ORM hech qachon `response_model` emas
- [ ] Har endpoint `require_permission("<domain>.<entity>.<action>")` bilan (`shop` surface)
- [ ] Yozish endpoint'lari `Idempotency-Key` talab qiladi
- [ ] Holat kodlari aniq: 201, 204, 404, 409, 422
- [ ] Xatolar — K-07 envelope
- [ ] OpenAPI'da har endpoint uchun misol (frontend client shundan generatsiya qilinadi)

```python
@router.post("/orders/{order_id}/confirm", response_model=OrderOut)
async def confirm_order(
    order_id: UUID,
    actor: ActorContext = Depends(require_permission("commerce.order.confirm")),
    idem_key: str = Depends(get_idempotency_key),
    db: DbSession,                      # Annotated[AsyncSession, Depends(get_db, scope="function")]
    service: OrderService = Depends(get_order_service),
):
    return await service.confirm(order_id, actor, idem_key, db)
```
- [ ] Sessiya **faqat `DbSession` / `ReadDbSession`** orqali (`app/shared/db/session.py`). `Depends(get_db)` to'g'ridan-to'g'ri — TAQIQ: standart `scope="request"` da COMMIT javob yuborilgandan keyin bo'ladi va COMMIT xatosi (`VERSION_CONFLICT`, unikal cheklov) klientga yetmaydi — u 200 oladi, hech narsa saqlanmaydi (kod tekshiruvi, 2026-10-23)

---

## 5. Fon vazifasi talablari

- [ ] Idempotent (deterministik kalit)
- [ ] Rejali ish advisory lock bilan (`job:<name>`)
- [ ] Og'ir ish — arq'da, scheduler faqat tekshiradi va navbatga qo'yadi
- [ ] Maksimal davomiylik 5 daqiqa; kattasi bo'laklarga (batch 100)
- [ ] Vazifa payload'ida `shop_id` bor, lekin worker ruxsat va holatni DB'dan qayta o'qiydi
- [ ] Trace davomiyligi: `traceparent` outbox → arq → task

Batafsil: [06-background-jobs.md](06-background-jobs.md).

## 6. Subscriber talablari

```python
@subscribe("sales_ai.order_draft.requested")
async def on_order_draft_requested(envelope: EventEnvelope, db: AsyncSession) -> None:
    payload = OrderDraftRequestedV1.model_validate(envelope.payload)   # app/shared/contracts/events/sales_ai.py
    await order_service.create_draft_from_ai(
        payload, shop_id=envelope.shop_id,
        idem_key=f"commerce_on_order_draft:{envelope.event_id}", db=db,
    )
```
- [ ] At-least-once: bir event 2–3 marta kelishi mumkin — idempotent
- [ ] Payload versiyalangan (`schema_version`); eski versiyani ham o'qiy oladi yoki aniq rad etadi
- [ ] Xato bo'lsa — qayta urinish, keyin dead-letter (`05-events-and-outbox.md`)

## 7. Kesh talablari

- [ ] Faqat ro'yxat va ommaviy sahifalar keshlanadi (storefront katalogi, sayt sozlamalari)
- [ ] Kalitda shop prefiksi majburiy: `cos:v1:shop:{shop_id}:storefront:products:page=1`
- [ ] Invalidatsiya event bo'yicha (`catalog.product.published`, `commerce.stock.changed`)
- [ ] Narx va qoldiq **buyurtma tasdiqlashda** hech qachon keshdan olinmaydi (ADR-019)

Batafsil: [08-cache-and-realtime.md](08-cache-and-realtime.md).

## 8. AI bilan bog'liq talablar (`sales_ai` va unga ma'lumot beruvchilar)

- [ ] AI tool'lari faqat Query Port yoki event orqali ishlaydi; to'g'ridan-to'g'ri SQL yo'q
- [ ] Har tool `ActorContext` (AI agent, shop doirasida) bilan chaqiriladi va ruxsat tekshiriladi
- [ ] Tool javobida narx/qoldiqning yangilangan vaqti bor
- [ ] LLM'ga yuboriladigan matn redaction'dan o'tadi (DEC-016)

Batafsil: [14-ai-sales-agent-and-tools.md](14-ai-sales-agent-and-tools.md).

---

## 9. Yangi domen — mini checklist

```
Domen: __________   Egasi: __________   Slice: S_

[Papka va fayllar]
[ ] app/domains/<name>/ + __init__.py + domain_manifest.py
[ ] permissions.py, events.py, subscribers.py
[ ] .importlinter ga qo'shildi

[Ma'lumotlar bazasi]
[ ] CREATE SCHEMA — schemas.sql
[ ] Alembic env + birinchi migratsiya
[ ] shop_id NOT NULL, composite FK, RLS (kerak bo'lsa)

[Holat]
[ ] state_machine.py ← business/05
[ ] rules_loader boot'da tanidi (logda ko'rinadi)
[ ] use.log_transition() chaqirilyapti

[Kod sifati]
[ ] Type hint'lar, mypy
[ ] print() yo'q, faqat structlog
[ ] requests yo'q, faqat httpx
[ ] Global holat yo'q

[Testlar]
[ ] Unit, integratsiya, state machine
[ ] TC-ISO izolyatsiya va ruxsat testlari
[ ] Coverage > 70%

[Kuzatuv]
[ ] structlog.bind(domain=...)
[ ] Metrikalar (cos_<domain>_...)
[ ] Sentry'ga xato

[Hujjat]
[ ] docs/modules/<name>/README.md
[ ] Holatlar, event'lar, API, BL qoidalar

[CI]
[ ] import-linter, ruff, mypy, pytest — hammasi o'tadi
```

## 10. Keyingi qadam

→ [04-state-machines-and-use.md](04-state-machines-and-use.md)
