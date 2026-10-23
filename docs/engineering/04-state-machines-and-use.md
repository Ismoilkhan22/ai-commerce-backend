# 04 — Holatlar (state machine) va slim USE

> **Versiya:** v2 (2026-10-22). ADR-034, K-02, K-03. Holatlar manbai — [../business/05](../business/05_STATE_MACHINES_AND_EXCEPTIONS.md).
> **Kim o'qiydi:** backend dasturchilar.

## 1. Muammo

Tizimda 10 dan ortiq narsa holatdan holatga o'tadi: shop, mahsulot, kanal, suhbat, lead, taklif, band qilish, buyurtma, kafolat murojaati, xabar. Agar har service holatni o'zicha o'zgartirsa:
- noto'g'ri o'tish (masalan, `COMPLETED → CONFIRMED`) jim o'tib ketadi;
- "kim, qachon, nega o'zgartirdi" tarixi tarqoq yoki yo'q;
- `business/05` dagi strelkalar va kod bir-biridan uzoqlashadi.

Boshqa tomondan, bismuth v1 tajribasi: markaziy "USE" hamma side-effect'ni o'ziga olib, 1500 qatorli god-orchestrator bo'lib ketgan.

## 2. Yechim — slim USE

`app/platform/use` **faqat 3 ish** qiladi (ADR-034):

| Funksiya | Nima qiladi | Qachon |
|---|---|---|
| `validate_transition(entity_type, from_status, to_status, command, actor)` | Qoida bormi va `actor.actor_type` qoidaning `actors` ro'yxatidami? Yo'q bo'lsa `InvalidTransitionError` → `409 INVALID_STATE_TRANSITION` (AI xodim buyrug'ini bajara olmaydi — TC-028) | Holat o'zgarishidan oldin, tranzaksiya ichida |
| `log_transition(entity_type, entity_id, rule, actor, reason, db)` | `platform.transition_log` ga yozadi | O'sha tranzaksiyada |
| `force_transition(...)` | Qoidadan tashqari o'tish — faqat platforma admini, majburiy sabab, audit | Runbook'lar (`25`) |

**USE qilmaydi:** ruxsat tekshirish (router'da `require_permission`), event yuborish (domen outbox'ga o'zi yozadi), notification, AI chaqirish, boshqa entity yaratish yoki o'zgartirish.

**Qoida:** holat faqat domen service'i ichida o'zgaradi. Repository hech qachon `status = 'X'` yozmaydi (`00` 7-prinsip).

---

## 3. `StateMachineRule` formati

```python
# app/shared/types/state.py
class StateMachineRule(BaseModel):
    entity_type: str            # "commerce.order"
    command: str                # "CONFIRM"
    from_status: str            # "PENDING_CONFIRMATION"
    to_status: str              # "CONFIRMED"
    actors: frozenset[ActorType]  # ActorContext.actor_type: STAFF | AI_AGENT | CUSTOMER | SYSTEM | PLATFORM
    requires_reason: bool = False
    business_ref: str           # "FSM-08" — business/05 ga havola
```

```python
# app/domains/commerce/orders/state_machine.py
ORDER_RULES = [
    StateMachineRule(entity_type="commerce.order", command="SUBMIT",
                     from_status="DRAFT", to_status="PENDING_CONFIRMATION",
                     actors={STAFF, CUSTOMER}, business_ref="FSM-08"),
    StateMachineRule(entity_type="commerce.order", command="CONFIRM",
                     from_status="PENDING_CONFIRMATION", to_status="CONFIRMED",
                     actors={STAFF}, business_ref="FSM-08"),          # AI yo'q (BL-110)
    StateMachineRule(entity_type="commerce.order", command="CANCEL",
                     from_status="CONFIRMED", to_status="CANCELLED",
                     actors={STAFF}, requires_reason=True, business_ref="FSM-08"),
    ...
]
```

`actors` — kim **turi** (xodim, AI, tizim, xaridor). Aniq rol (operator o'ziga biriktirilganini tasdiqlaydi, bekor qilish faqat menejer/ega) — ruxsat qatlamida (`10`, `../business/04`).

Qoidalar `DomainManifest.state_machine_rules` orqali e'lon qilinadi; `platform/use/infrastructure/rules_loader.py` boot vaqtida yig'adi va xotirada saqlaydi. Boot logida: `use.rules_loaded entity_types=11 rules=…`.

---

## 4. Stage 1 holatlari — domen va `entity_type` bo'yicha

Holat nomlari `UPPER_SNAKE`, aynan `business/05` dagidek (K-02, K-03).

| FSM | `entity_type` | Egasi | Holatlar |
|---|---|---|---|
| FSM-01 | `platform.shop` | `platform/shops` | `DRAFT`, `PENDING_VERIFICATION`, `ACTIVE`, `SUSPENDED`, `CLOSED` |
| — | `platform.membership` | `platform/staff` | `INVITED`, `ACTIVE`, `DISABLED` |
| FSM-02 | `catalog.product` | `catalog/products` | `DRAFT`, `IN_REVIEW`, `PUBLISHED`, `HIDDEN`, `ARCHIVED` |
| FSM-03 | `messaging.channel` | `messaging/channels` | `PENDING`, `CONNECTED`, `DEGRADED`, `DISCONNECTED` |
| FSM-04 | `messaging.conversation` | `messaging/conversations` | `NEW`, `AI_ACTIVE`, `WAITING_CUSTOMER`, `HUMAN_NEEDED`, `HUMAN_ACTIVE`, `RESOLVED`, `REOPENED` |
| FSM-05 | `commerce.lead` | `commerce/leads` | `NEW`, `QUALIFIED`, `QUOTED`, `WON`, `LOST` |
| FSM-06 | `commerce.quote` | `commerce/quotes` | `DRAFT`, `REVIEW`, `APPROVED`, `SENT`, `ACCEPTED`, `EXPIRED`, `REJECTED` |
| FSM-07 | `commerce.reservation` | `commerce/inventory` | `ACTIVE`, `ALLOCATED`, `CONSUMED`, `RELEASED`, `EXPIRED` |
| FSM-08 | `commerce.order` | `commerce/orders` | `DRAFT`, `PENDING_CONFIRMATION`, `CONFIRMED`, `PROCESSING`, `COMPLETED`, `CANCELLED`, `EXCEPTION` |
| FSM-11 | `support.case` | `support/cases` | `NEW`, `IN_REVIEW`, `APPROVED`, `REJECTED`, `IN_SERVICE`, `RESOLVED`, `CLOSED` |
| FSM-12 | `platform.notification` | `platform/notifications` | `PENDING`, `SCHEDULED`, `SENT`, `FAILED`, `SUPPRESSED` |

Keyinga qoldirilgan: FSM-09 to'lov (`payments`, DEC-100), FSM-10 yetkazish (`fulfillment`, DEC-113). Stage 2–3: FSM-13…18 (`network`, `marketplace`).

### 4.1 O'tishlar va buyruqlar

Har strelka — bitta qoida. Buyruq nomlari kodda shunday:

**`commerce.order` (FSM-08)**
```
DRAFT ──SUBMIT (xodim | xaridor saytda)──▶ PENDING_CONFIRMATION
PENDING_CONFIRMATION ──CONFIRM (xodim)──▶ CONFIRMED          [reservation ACTIVE, 12-…]
CONFIRMED ──START_PROCESSING (xodim)──▶ PROCESSING           [reservation ALLOCATED]
PROCESSING ──COMPLETE (xodim)──▶ COMPLETED                   [reservation CONSUMED, on_hand −qty]
DRAFT ──CANCEL (xodim | xaridor)──▶ CANCELLED
PENDING_CONFIRMATION | CONFIRMED ──CANCEL (menejer/ega, sabab)──▶ CANCELLED   [reservation RELEASED]
PROCESSING ──RAISE_EXCEPTION (xodim, sabab)──▶ EXCEPTION
EXCEPTION ──RESOLVE_TO_PROCESSING (menejer)──▶ PROCESSING
EXCEPTION ──CANCEL (menejer/ega, sabab)──▶ CANCELLED         [reservation RELEASED]
```
Holat o'zgartirmaydigan amallar — USE'dan o'tmaydi, faqat audit + event:
- `MARK_READY` — `ready_at` qo'yiladi, holat `PROCESSING` qoladi, xaridorga xabar (`commerce.order.ready`).
- `MARK_PAID` — `paid_mark` (shop belgisi, tekshirilmagan, DEC-100a), `commerce.order.paid_marked`.
- AI yaratgan qoralama — `DRAFT` holatida **yaratiladi** (o'tish emas); AI hech qanday buyruqni bajara olmaydi (BL-110).

**`commerce.reservation` (FSM-07)**
```
(yaratiladi CONFIRM ichida) ──▶ ACTIVE
ACTIVE ──ALLOCATE (tizim, START_PROCESSING ichida)──▶ ALLOCATED
ALLOCATED ──CONSUME (tizim, COMPLETE ichida)──▶ CONSUMED
ACTIVE | ALLOCATED ──RELEASE (tizim, CANCEL ichida)──▶ RELEASED
ACTIVE ──EXPIRE (menejer, 72 soatlik vazifadan keyin)──▶ EXPIRED
```
Avtomatik muddati o'tish yo'q (DEC-104): rejali ish faqat vazifa yaratadi (`06`).

**`commerce.quote` (FSM-06)**
```
DRAFT ──SUBMIT_FOR_REVIEW (xodim | AI)──▶ REVIEW              [moslik tekshiruvi]
REVIEW ──APPROVE (menejer/ega; tuzgan odam emas)──▶ APPROVED  [narx snapshot, expires_at]
DRAFT ──AUTO_APPROVE (tizim, "faqat xavfli holatlarda" rejimi)──▶ APPROVED
APPROVED ──SEND (xodim | tizim)──▶ SENT
SENT ──ACCEPT (xaridor)──▶ ACCEPTED                           [buyurtma qoralamasi]
SENT ──EXPIRE (tizim, muddat)──▶ EXPIRED
SENT ──REJECT (xaridor)──▶ REJECTED
REJECTED ──REVISE (xodim)──▶ yangi versiya DRAFT da (eski qator o'zgarmaydi)
```

**`messaging.conversation` (FSM-04)** — har o'tishda `speaker_mode` va `speaker_version` ham o'zgaradi (`12` §6):
```
NEW ──FIRST_MESSAGE (tizim)──▶ AI_ACTIVE
AI_ACTIVE ──AWAIT_CUSTOMER (AI)──▶ WAITING_CUSTOMER
AI_ACTIVE ──REQUEST_HUMAN (AI | tizim)──▶ HUMAN_NEEDED
HUMAN_NEEDED ──TAKE_OVER (operator)──▶ HUMAN_ACTIVE          [speaker_version +1]
HUMAN_ACTIVE ──AWAIT_CUSTOMER (operator)──▶ WAITING_CUSTOMER
WAITING_CUSTOMER ──CUSTOMER_REPLIED (tizim)──▶ HUMAN_ACTIVE | AI_ACTIVE   [kim olgan bo'lsa]
HUMAN_ACTIVE ──RETURN_TO_AI (operator)──▶ AI_ACTIVE           [speaker_version +1]
HUMAN_ACTIVE ──RESOLVE (operator)──▶ RESOLVED
RESOLVED ──CUSTOMER_REPLIED (tizim)──▶ REOPENED
```
`WAITING_CUSTOMER → AI_ACTIVE` va `REOPENED` dan keyingi yo'l `business/05` da to'liq strelka bilan berilmagan — `REOPENED` ga qayta ochilgandan keyin `speaker_mode` oldingi qiymatida qoladi va keyingi o'tishlar `AI_ACTIVE`/`HUMAN_NEEDED` dagi kabi. Bu `business/05` ga qo'shimcha sifatida tasdiqlanishi kerak (11-bo'lim).

Qolgan FSM'lar (`platform.shop`, `catalog.product`, `messaging.channel`, `commerce.lead`, `support.case`, `platform.notification`) — `business/05` dagi strelkalar 1:1, buyruq nomi strelka ustidagi harakatdan olinadi (`ACTIVATE`, `SUSPEND`, `PUBLISH`, `HIDE`, `CONNECT`, `MARK_DEGRADED`, `QUALIFY`, `MARK_LOST`, `APPROVE`, `START_SERVICE` …). To'liq ro'yxat har domenning `state_machine.py` faylida va `../modules/<domain>/README.md` da.

---

## 5. Service'da ishlatish

```python
async def start_processing(self, order_id, actor, idem_key, db):
    async with db.begin():
        await self.idempotency.check_or_record(actor.shop_id, "order.start_processing", idem_key, db)
        order = await self.repo.get_for_update(actor.shop_id, order_id, db)
        rule = self.use.validate_transition("commerce.order", order.status, "PROCESSING", "START_PROCESSING", actor)
        await self.inventory.allocate(actor.shop_id, order.id, db)       # reservation ACTIVE → ALLOCATED
        order.status = rule.to_status
        order.version += 1
        await self.use.log_transition(db, entity_id=order.id, rule=rule, actor=actor)
        await self.audit.record("commerce.order.processing", order.id, actor, db)
        await write_outbox(db, OrderProcessingV1.from_order(order))
```

Tartib doim bir xil: **idempotency → lock/o'qish → validate → o'zgartirish → log → audit → outbox → COMMIT.**

Bir xil holatga takroriy o'tish (masalan, `COMPLETE` ikki marta): ikkinchi chaqiruv idempotency yozuvidan birinchi javobni qaytaradi; kalit boshqa bo'lsa — `409 INVALID_STATE_TRANSITION` (holat allaqachon `COMPLETED`), qoldiq qayta kamaymaydi (TC-030).

---

## 6. `transition_log` jadvali

```sql
CREATE TABLE platform.transition_log (
    id              UUID NOT NULL,                 -- UUIDv7; PK (id, occurred_at) — partition kaliti PK'da
    shop_id         UUID,                          -- platforma darajasidagi entity uchun NULL bo'lishi mumkin
    entity_type     TEXT NOT NULL,                 -- 'commerce.order'
    entity_id       UUID NOT NULL,
    command         TEXT NOT NULL,                 -- 'CONFIRM'
    from_status     TEXT NOT NULL,
    to_status       TEXT NOT NULL,
    actor_type      TEXT NOT NULL,                 -- STAFF | AI_AGENT | CUSTOMER | SYSTEM | PLATFORM (ActorContext)
    actor_id        UUID,
    reason          TEXT,
    forced          BOOLEAN NOT NULL DEFAULT false,
    trace_id        TEXT,
    occurred_at     TIMESTAMPTZ NOT NULL DEFAULT now()
) PARTITION BY RANGE (occurred_at);              -- oyma-oy, 07-…

CREATE INDEX ON platform.transition_log (shop_id, entity_type, entity_id, occurred_at);
```

- Append-only: `app_runtime` roliga faqat `INSERT` va `SELECT`.
- `reason` — erkin matn, lekin shaxsiy ma'lumot yozilmaydi (UI ogohlantiradi).
- Cross-schema: domen tranzaksiyasi `platform.transition_log` ga yozadi — ruxsat etilgan istisno (ADR-035 neytral bandi). FK yo'q.
- Dashboard'da "Tarix" bo'limi shu jadvaldan + `audit` dan o'qiladi.

Audit (`audit.events`) bilan farqi: transition_log — faqat holat o'tishlari, tez so'rovlar uchun; audit — barcha muhim o'zgarishlar (narx, ruxsat, sozlamalar), eski/yangi qiymatlar bilan (`10`).

---

## 7. `force_transition`

Faqat runbook holatlari uchun (masalan, xato tufayli `EXCEPTION` da qotib qolgan buyurtma):
- Ruxsat: `platform.state.force` (faqat platforma admini, shop xodimlarida yo'q).
- Majburiy: `reason` (≥ 20 belgi), shop egasi xabardor qilinadi (`25`).
- `forced = true`, audit'ga alohida yozuv, Sentry'ga `warning`.
- Pul va qoldiq bog'liq o'tishlar (`CONFIRMED`, `COMPLETED`) `force` bilan **qilinmaydi** — ularni faqat oddiy service yo'li bilan (qoldiq invarianti saqlanishi uchun).

---

## 8. `business/05` ↔ kod muvofiqligi

Holatlar ikki joyda yashaydi: odam o'qiydigan `business/05` va kod (`state_machine.py`). Ular uzoqlashmasligi uchun:

1. **Muvofiqlik fayli:** `app/tests/architecture/fsm_spec.yaml` — `business/05` dagi har strelka (`entity_type`, `from`, `to`, `command`). Yangi strelka avval `business/05` ga, keyin shu faylga, keyin kodga qo'shiladi.
2. **Test `test_fsm_parity.py`:** `rules_loader` yig'gan qoidalar to'plami `fsm_spec.yaml` bilan **aynan teng** bo'lishi kerak — ortiqcha ham, kam ham emas.
3. **Har domen testi:** har ruxsat etilgan o'tish o'tadi; har taqiqlangan juftlik (`from × to` dan qolganlari) `409 INVALID_STATE_TRANSITION` qaytaradi.
4. **Enum testi:** DB `CHECK (status IN (...))` qiymatlari `fsm_spec.yaml` dagi holatlar bilan bir xil.

---

## 9. Kuzatuv

- Metrika: `cos_use_transition_total{entity_type, command, result="ok|rejected"}`.
- `rejected` ko'payishi — UI eskirgan holatni ko'rsatayotgani yoki xato belgisi.
- Log: `use.transition entity_type=commerce.order command=CONFIRM from=… to=…` (`trace_id`, `shop_id` contextvars'dan).

## 10. Testlar

| Test | Nima tekshiradi |
|---|---|
| `test_fsm_parity` | `business/05` ↔ kod |
| Domen state testlari | har o'tish va taqiq |
| TC-028 | AI faqat `DRAFT` yaratadi, hech qanday buyruq bajara olmaydi |
| TC-029 | Operator boshqa operator buyurtmasini `CONFIRM`/`CANCEL` qila olmaydi (ruxsat qatlami) |
| TC-030 | `COMPLETE` takrorlansa qoldiq bir marta kamayadi |
| `force_transition` testi | `CONFIRMED`/`COMPLETED` ga majburlab o'tib bo'lmaydi |

## 11. Ochiq savollar

1. FSM-04: `WAITING_CUSTOMER → AI_ACTIVE` (AI javob berib turgan suhbatda xaridor yozsa) va `REOPENED` dan keyingi o'tishlar `business/05` da aniq strelka bilan yo'q — yuqoridagi talqinni founder tasdiqlashi kerak.
2. Xodim a'zoligi: `DISABLED → ACTIVE` (qayta yoqish) `business/05` da yo'q — hozircha taqiqlangan, yangi taklif kerak.

## Keyingi qadam

→ [05-events-and-outbox.md](05-events-and-outbox.md) — holat o'zgarishidan keyin event qanday tarqaladi
