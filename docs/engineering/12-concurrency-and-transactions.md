# 12 — Tranzaksiyalar va bir vaqtdagi o'zgarishlar

> **Versiya:** v2 (2026-10-22). ADR-032 (DEC-126), ADR-019, DEC-104, DEC-105, DEC-108, DEC-123, K-04, K-05, K-06, K-07. Eski `07_DOMAIN_TRANSACTIONS_CONCURRENCY` o'rnini bosadi.
> **Kim o'qiydi:** backend dasturchilar. Bu hujjat — pul va qoldiq xavfsizligi bo'yicha eng muhim hujjat.

## 1. Muammo

Omborda 1 ta RTX 4060 qoldi. Bir vaqtda:
- operator A shu mahsulotga buyurtmani tasdiqlayapti,
- operator B boshqa buyurtmani tasdiqlayapti,
- do'konda sotuvchi xuddi shu mahsulotni "tez sotuv" bilan sotyapti (BR-X13).

Hech qanday himoya bo'lmasa — uchalasi ham "bor" deb o'qiydi va uchalasi ham o'tadi: qoldiq −2, ikki xaridor aldangan. Tarmoq uzilsa operator tugmani yana bosadi — mahsulot ikki marta band qilinadi. AI javob yozayotganda operator suhbatni oldi — xaridor ikki xil javob oladi.

## 2. Asosiy qoidalar

1. **Pul va qoldiqqa tegadigan har o'zgarish — bitta domen ichida, bitta tranzaksiyada** (`commerce`, ADR-032). Event'ga yoki keyingi vazifaga qoldirilmaydi.
2. **Tranzaksiya qisqa.** Ichida LLM, Telegram, HTTP, fayl o'qish — yo'q. O'qish TX → tashqi chaqiruv → yozish TX.
3. **Qoldiq qatorlari pessimistik lock bilan** (`SELECT … FOR UPDATE`), **hamma joyda bir xil tartibda**: `(shop_id, branch_id, sku_id)` o'sish tartibida.
4. **Boshqa obyektlar optimistik** (`version` ustuni): narx, sozlamalar, suhbat egasi, taklif.
5. **Har yozish amali idempotent** (`Idempotency-Key`, K-06).
6. **Narx va qoldiq tasdiqlashda keshdan yoki Query Port'dan emas, lock ostida DB'dan** (ADR-019).
7. **Qisman natija yo'q:** bir qator yetmasa — butun buyurtma tasdiqlanmaydi, hech narsa band qilinmaydi.

---

## 3. Izolyatsiya darajasi va qayta urinish

- Standart: PostgreSQL `READ COMMITTED` + aniq row lock'lar. `SERIALIZABLE` global yoqilmaydi.
- `lock_timeout = 3s`, `statement_timeout = 10s` (API), `idle_in_transaction_session_timeout = 15s`.
- Deadlock (`40P01`) yoki serialization (`40001`) — **butun tranzaksiya** qayta boshlanadi: maks 3 urinish, 20–200 ms jitter. Tranzaksiya ichida tashqi effekt yo'qligi tufayli xavfsiz.
- `lock_timeout` tugasa → `409 VERSION_CONFLICT` ("ma'lumot o'zgarmoqda, qayta urinib ko'ring"), 503 emas.
- DB pool to'lsa → side-effect'dan oldin `503 SERVICE_UNAVAILABLE` + `Retry-After` (`06` §7).
- `asyncpg` session vazifalar (task) yoki thread'lar orasida ulashilmaydi.

## 4. Optimistik va pessimistik — qachon qaysi

| Obyekt | Usul | Nega |
|---|---|---|
| `commerce.stock_balances` | `FOR UPDATE` (pessimistik) | To'qnashuv ehtimoli yuqori (oxirgi dona), xato qimmat |
| `commerce.orders` (tasdiqlash, bekor qilish, topshirish) | `FOR UPDATE` + `version` | Qoldiq bilan birga o'zgaradi |
| `commerce.reservations` | `FOR UPDATE` (buyurtma bilan birga) | Bir marta bo'shatish/ishlatish |
| Narx (`catalog.prices`) | Yangi versiya qatori (INSERT), joriy ko'rsatkich CAS | Eski versiya hech qachon o'zgarmaydi |
| Taklif (`commerce.quotes`) | `version` (CAS); yuborilgani o'zgarmaydi — yangi revision | Tasdiqlash va narx o'zgarishi to'qnashuvi |
| Suhbat egasi (`messaging.conversations.speaker_version`) | Atomik `UPDATE … SET speaker_version = speaker_version + 1 … RETURNING` | Fencing (§8) |
| Shop sozlamalari, profil | `version` + `If-Match` | Kam to'qnashuv |

**`version` qanday oshadi:** faqat avtomatik — modelda `VersionMixin` (SQLAlchemy `version_id_col`). Har UPDATE `... SET version = version + 1 WHERE id = :id AND version = :o'qilgan` ko'rinishida ketadi; qator boshqa tranzaksiyada o'zgargan bo'lsa, 0 qator yangilanadi va `VERSION_CONFLICT` bo'ladi. Kodda `version` ni qo'lda oshirish — TAQIQ (ikki marta oshib ketadi). `If-Match` dagi versiya o'qilgan obyekt versiyasi bilan solishtiriladi.

`If-Match` sarlavhasi dashboard tahrir formalarida majburiy; eskirgan versiya → `409 VERSION_CONFLICT` va UI "sahifani yangilang" (`business/05` umumiy qoida 3).

---

## 5. Buyurtmani tasdiqlash — algoritm

```
POST /api/v1/shop/orders/{order_id}/confirm
Headers: Idempotency-Key, If-Match: <order.version>
Ruxsat: commerce.order.confirm (operator — faqat o'ziga biriktirilgan; menejer/ega — filiali doirasida)
```

```
BEGIN                                                      -- READ COMMITTED
 1. set_config('app.shop_id', actor.shop_id, true)          -- RLS (10)
 2. idempotency: INSERT (shop_id, 'order.confirm', key, request_hash) ON CONFLICT
      ├─ bor, hash bir xil, yakunlangan → saqlangan javobni qaytarish (ROLLBACK, 200)
      ├─ bor, hash boshqa → 409 IDEMPOTENCY_KEY_REUSED
      └─ yangi → davom
 3. order := SELECT … FROM commerce.orders WHERE shop_id=? AND id=? FOR UPDATE
      yo'q → 404 NOT_FOUND (boshqa shopniki ham shunday, TC-001)
      order.version ≠ If-Match → 409 VERSION_CONFLICT
      operator va order.assigned_to ≠ actor → 403 FORBIDDEN (TC-029)
 4. use.validate_transition('commerce.order', order.status, 'CONFIRMED', 'CONFIRM')
      → aks holda 409 INVALID_STATE_TRANSITION
 5. lines := buyurtma qatorlari, (branch_id, sku_id) bo'yicha saralangan
 6. balances := SELECT … FROM commerce.stock_balances
                 WHERE shop_id=? AND (branch_id, sku_id) IN (...)
                 ORDER BY branch_id, sku_id FOR UPDATE
 7. har qator uchun:
      available = on_hand − reserved − allocated
      available < qty → 409 INSUFFICIENT_AVAILABLE_STOCK {sku_id, available} — butun TX ROLLBACK
 8. narx tekshiruvi:
      joriy_narx := CatalogQueryPort.get_active_price(sku_ids)   -- sinxron, keshsiz (5.1)
                    va buyurtma qatoridagi price_version / unit_price snapshot bilan solishtiriladi
      PC taklif bo'lsa: quote.status='ACCEPTED', quote.expires_at tekshirilmaydi (qabul qilingan),
                        lekin quote revision qatorlari bilan solishtiriladi
      farq bor → 409 PRICE_CHANGED {old, new} — xaridordan qayta rozilik (TC-031)
 9. reserved += qty (har balans), stock_ledger ga RESERVE yozuvlari   -- balans version'i avtomatik oshadi (§4)
10. reservation := INSERT ACTIVE (order_id, lines)
11. order.status = 'CONFIRMED', confirmed_by, confirmed_at   -- version avtomatik oshadi (§4)
12. use.log_transition(...); audit.record(...)
13. outbox: commerce.order.confirmed, commerce.reservation.created, commerce.stock.changed (har SKU)
14. notifications.request('order.confirmed', customer)    -- platform outbox
15. idempotency yozuviga javobni saqlash
COMMIT  → 200 {order, version}
```

### 5.1 Narx qayerdan tekshiriladi

**Founder qarori (2026-10-22):** tasdiqlash paytida joriy narx `catalog` dan **sinxron, Query Port orqali** o'qiladi — `CatalogQueryPort.get_active_price()` (ADR-032 §6). Qo'shimcha jadval yoki nusxa yo'q.

- Buyurtma `DRAFT` yaratilganda har qatorga `unit_price` (Money), `price_version_id` va (USD bo'lsa) `exchange_rate_id` **snapshot** qilinadi.
- Tasdiqlashda (8-qadam) `get_active_price()` joriy `price_version_id` va narxni qaytaradi; snapshot bilan farq qilsa — `409 PRICE_CHANGED {old, new}` (TC-031), xaridordan qayta rozilik.
- Bu faqat o'qish: `commerce` `catalog` jadvaliga JOIN yoki FK qilmaydi (ADR-035), Query Port implementatsiyasi `catalog` ichida. Keshdan o'qilmaydi (ADR-019).
- Narx lock ostida emas — tasdiqlash va narx o'zgarishi bir necha millisekund farq bilan kelsa, tasdiqlangan buyurtma snapshot narxida qoladi (kelishilgan narx); bu qabul qilingan va audit'da ko'rinadi.
- Qoldiq esa `commerce` ning o'z jadvali — har doim `FOR UPDATE` bilan (6-qadam).

### 5.2 Xato kodlari

| Kod | HTTP | Qachon | UI nima qiladi |
|---|---|---|---|
| `INSUFFICIENT_AVAILABLE_STOCK` | 409 | §5 7-qadam | "Mahsulot qolmagan", muqobil taklif vazifasi |
| `PRICE_CHANGED` | 409 | 8-qadam | Eski/yangi narx, "xaridordan rozilik olindi" tugmasi → narxni yangilab qayta tasdiqlash |
| `QUOTE_EXPIRED` | 409 | taklif asosidagi qoralama, taklif `EXPIRED` | Yangi taklif versiyasi |
| `VERSION_CONFLICT` | 409 | `If-Match` mos emas, `lock_timeout` | "Sahifani yangilang" |
| `INVALID_STATE_TRANSITION` | 409 | holat ruxsat bermaydi (allaqachon tasdiqlangan, bekor qilingan) | Joriy holatni ko'rsatish |
| `IDEMPOTENCY_KEY_REUSED` | 409 | bir kalit, boshqa so'rov tanasi | Dasturiy xato — Sentry |
| `FORBIDDEN` | 403 | boshqa operatorning buyurtmasi | — |
| `NOT_FOUND` | 404 | yo'q yoki boshqa shopniki | — |

To'liq katalog va tarjimalar — `11`.

---

## 6. Qolgan qoldiq operatsiyalari

Hammasi `stock_balances` ni **bir xil tartibda** (`branch_id, sku_id`) lock qiladi — deadlock bo'lmasligi uchun.

| Amal | TX ichida | Lock | Idempotency | Qoida |
|---|---|---|---|---|
| `start_processing` | order → `PROCESSING`; reservation `ACTIVE → ALLOCATED`; `reserved −qty`, `allocated +qty` | order, reservation, balances | `Idempotency-Key` + holat | — |
| `complete_order` | order → `COMPLETED`; reservation → `CONSUMED`; `allocated −qty`, `on_hand −qty`; ledger `SALE` | order, reservation, balances | `Idempotency-Key` + holat (`COMPLETED` dan qayta o'tib bo'lmaydi) | Qoldiq **bir marta** kamayadi (TC-030) |
| `cancel_order` | order → `CANCELLED`; reservation `ACTIVE/ALLOCATED → RELEASED`; `reserved`/`allocated −qty`; ledger `RELEASE` | order, reservation, balances | holat + `RELEASED` dan qayta bo'shatilmaydi | Faqat menejer/ega, sabab (BL-049); bir marta bo'shatish (BL-021) |
| `expire_reservation` | reservation `ACTIVE → EXPIRED` + bo'shatish; order holati menejer qaroriga ko'ra | reservation, order, balances | holat | Faqat menejer, 72 soatlik vazifadan (DEC-104) |
| `quick_sale` (tez sotuv) | `on_hand −qty`, faqat `available` dan; ledger `QUICK_SALE`; audit | balances | `Idempotency-Key` | `available < qty` → `409 INSUFFICIENT_AVAILABLE_STOCK`; band mahsulotni sotib bo'lmaydi (DEC-123, BL-109) |
| `receive_stock` (kirim) | `on_hand +qty`; ledger `RECEIPT` | balances | `Idempotency-Key` | — |
| `adjust_stock` (tuzatish) | `on_hand ±qty`; ledger `ADJUSTMENT` + sabab; limitdan katta bo'lsa — tasdiq so'rovi | balances | `Idempotency-Key` | `on_hand` < `reserved + allocated` bo'lib qolmaydi — aks holda rad |
| `support` dan "tekshiruvda" (ledger `RETURN_QUARANTINE`) | `quarantine_qty +1` (`on_hand` ga kirmaydi, sotilmaydi) | balances | `case_id` | BR-X11 |

### 6.1 DB invariantlari

```sql
CREATE TABLE commerce.stock_balances (
    shop_id      UUID NOT NULL,
    branch_id    UUID NOT NULL,
    sku_id       UUID NOT NULL,
    on_hand      INT  NOT NULL DEFAULT 0,
    reserved     INT  NOT NULL DEFAULT 0,
    allocated    INT  NOT NULL DEFAULT 0,
    inspection   INT  NOT NULL DEFAULT 0,
    stock_version BIGINT NOT NULL DEFAULT 0,
    PRIMARY KEY (shop_id, branch_id, sku_id),
    CHECK (on_hand >= 0 AND reserved >= 0 AND allocated >= 0 AND inspection >= 0),
    CHECK (reserved + allocated <= on_hand)                -- available >= 0 (BL-019)
);
```
CHECK — oxirgi himoya qatlami; asosiy himoya — lock + tekshiruv. Ledger (`commerce.stock_ledger`, append-only) yig'indisi balans bilan har kecha solishtiriladi (rekonsilyatsiya, farq → alert).

---

## 7. Tez sotuv va online buyurtma to'qnashuvi (TC-027)

```
T0  on_hand=1, reserved=0
T1  Operator: confirm  → BEGIN; balances FOR UPDATE (lock oldi)
T2  Sotuvchi: quick_sale → BEGIN; balances FOR UPDATE (kutadi)
T3  Operator: available=1 ≥ 1 → reserved=1 → COMMIT (lock bo'shadi)
T4  Sotuvchi: available = 1 − 1 = 0 < 1 → 409 INSUFFICIENT_AVAILABLE_STOCK
    UI: "Bu mahsulot online buyurtma uchun band qilingan"
```
Teskari tartibda (tez sotuv birinchi) — operator `409` oladi va muqobil taklif vazifasi yaratiladi (BR-X13). Har ikki holatda `available` manfiy bo'lmaydi.

## 8. AI va operator — fencing (TC-009)

`messaging.conversations`: `speaker_mode` (`AI` | `HUMAN` | `PAUSED`), `speaker_version BIGINT`.

```
Operator "Suhbatni olish":
  UPDATE messaging.conversations
     SET speaker_mode='HUMAN', speaker_version = speaker_version + 1, assigned_to=:op, status='HUMAN_ACTIVE'
   WHERE shop_id=:s AND id=:c
   RETURNING speaker_version;                      -- atomik
  + outbox messaging.conversation.handed_off

AI (sales_ai) javob tayyorlashdan oldin:  v0 := speaker_version (event'dan), speaker_mode='AI' ekanini tekshiradi
AI javob tayyor:  outbox sales_ai.reply.ready {speaker_version: v0}

messaging subscriber, yuborishdan oldin (bitta TX):
  SELECT speaker_mode, speaker_version FROM messaging.conversations WHERE … FOR UPDATE
  speaker_mode ≠ 'AI' yoki speaker_version ≠ v0  → javob DISCARDED (log, metrika), yuborilmaydi
  aks holda → outbound_messages INSERT (keyin channel_send)
```
- Bir suhbatda bir vaqtda bitta chiquvchi AI xabari: `outbound_messages` da `(conversation_id, speaker_version, origin='AI', status='PENDING')` bo'yicha qisman unikal indeks.
- Cheklov: xabar provayderga allaqachon ketgan bo'lsa, qaytarib bo'lmaydi — operator transkriptda ko'radi. Fencing provayderga yuborishdan **oldin**gi oxirgi nuqtada tekshiriladi.

## 9. Idempotency siyosati

| Amal | Kalit doirasi | Saqlanadi | Takror kelsa |
|---|---|---|---|
| API yozish (`POST`/`PATCH`) | `(shop_id, operation, Idempotency-Key)` | so'rov hash, status, javob | Hash bir xil → saqlangan javob; boshqa → `409 IDEMPOTENCY_KEY_REUSED`; birinchisi hali bajarilmoqda → `409 REQUEST_IN_PROGRESS` |
| Webhook | `(provider, channel_account_id, provider_event_id)` | normallashtirilgan xabar ID | 200, qayta ishlanmaydi (TC-010) |
| Event consumer | `(consumer, event_id)` | `consumer_receipts` | O'tkazib yuboriladi (`05` §6) |
| AI qoralama so'rovi | `sales_ai` `request_id` → `orders.source_request_id UNIQUE` | buyurtma | Mavjud qoralama qaytariladi (BL-046) |
| Rejali ish | `<job>:<entity_id>:<window>` | eslatma/vazifa | Takror eslatma yo'q (`06` §5) |
| Xabarnoma | `(shop_id, template_key, aggregate_id, aggregate_version, recipient)` | `platform.notifications` | Bitta hodisaga bitta xabar (FSM-12) |

Dublikat kutmaydi: `begin()` avval `pg_try_advisory_xact_lock(kalit)` oladi; band bo'lsa — darhol `409 REQUEST_IN_PROGRESS` (baza ulanishi band bo'lib turmaydi, founder 2026-10-23). Qulf COMMIT yoki ROLLBACK bilan o'zi ochiladi.

Idempotency yozuvi biznes o'zgarishi bilan **bitta tranzaksiyada** (2-qadam) — COMMIT bo'lmasa, kalit ham yo'q. HTTP javob COMMIT'dan keyin yo'qolsa, klient shu kalit bilan qayta yuboradi va saqlangan javobni oladi.

## 10. Taklif, narx va vaqt

- Taklif yaratilganda: moslik tekshiruvi (`catalog` `CompatibilityQueryPort` orqali) + joriy narx versiyalari — `DRAFT`.
- `APPROVE`: jami, kurs, chegirma, qoidalar versiyasi, `expires_at`, tasdiqlagan, revision hash — **muzlatiladi**. Taklifni tuzgan odam tasdiqlay olmaydi (DEC-109).
- `APPROVE` va narx o'zgarishi bir vaqtda: taklif `version` CAS; narx read model'i tasdiqlash paytida tekshiriladi — farq bo'lsa `PRICE_CHANGED`, menejer qayta ko'radi.
- `ACCEPT` (xaridor): `expires_at` va qoldiq qayta tekshiriladi; narx o'zgargan bo'lsa — yangi revision, xaridordan qayta rozilik. Yuborilgan taklif hech qachon jim o'zgarmaydi.

## 11. Bir vaqtdagi o'zgarishlar testlari

Haqiqiy PostgreSQL'da (testcontainers), `sleep` emas — **barrier** bilan (`asyncio.Barrier`), har test oxirida: qoldiq, ledger, buyurtma holati, outbox va audit yozuvlari soni tekshiriladi. Commit'dan oldin/keyin "failpoint"lar.

| ID | Ssenariy | Kutilgan natija |
|---|---|---|
| TC-CON-01 / TC-002 | Ikki operator oxirgi donani bir vaqtda tasdiqlaydi | Bittasi `CONFIRMED`, ikkinchisi 409; `available = 0` |
| TC-CON-02 / TC-027 | Online tasdiq va tez sotuv bir vaqtda | Bittasi o'tadi; `available ≥ 0` |
| TC-CON-03 / TC-003 | Bir `Idempotency-Key` bilan tasdiq 5 marta parallel | Bitta rezerv; birinchisi bajarilayotganda qolganlari darhol `409 REQUEST_IN_PROGRESS`, keyingi qayta so'rov — birinchisining saqlangan javobi |
| TC-CON-04 / TC-030 | `complete` ikki marta | `on_hand` bir marta kamayadi, bitta `SALE` ledger yozuvi |
| TC-CON-05 | Ikki bekor qilish + rezerv muddati vazifasi | Bitta `RELEASE` |
| TC-CON-06 / TC-009 | Ikki AI javobi + operator suhbatni oldi | Eski versiyadagi AI javobi yuborilmaydi |
| TC-CON-07 / TC-031 | Taklif tasdiqlash va narx o'zgarishi bir vaqtda | `PRICE_CHANGED` yoki `VERSION_CONFLICT`, jim o'zgarish yo'q |
| TC-CON-08 / TC-022 | Worker COMMIT'dan keyin o'ldi, qayta ishga tushdi | Bitta holat o'tishi, bitta outbox fakti |
| TC-CON-09 / TC-001 | A shop xodimi B shop SKU/filial ID'si bilan tasdiqlaydi | 404, hech qanday o'zgarish yo'q |
| TC-CON-10 | Ko'p SKU'li ikki buyurtma teskari tartibda (A,B) va (B,A) | Deadlock yo'q (tartiblangan lock) yoki avtomatik retry bilan ikkalasi to'g'ri yakunlanadi |
| TC-CON-11 | Bir xil `sales_ai.order_draft.requested` 3 marta | Bitta `DRAFT` |
| TC-CON-12 | `adjust_stock` `on_hand` ni `reserved` dan pastga tushirmoqchi | Rad etiladi |

## 12. Ochiq savollar

Hozircha yo'q. (Narx manbai — 2026-10-22 hal qilindi, §5.1; saytda qoldiqni ko'rsatish — `stock_display` sozlamasi, `08` §4.5.)

## Keyingi qadam

→ [13-integrations-and-channels.md](13-integrations-and-channels.md) — kanallar va webhook'lar
→ [24-testing-and-release.md](24-testing-and-release.md) — concurrency testlari reliz bosqichida
