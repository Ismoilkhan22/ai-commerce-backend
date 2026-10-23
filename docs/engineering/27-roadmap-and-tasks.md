# 27 — Yo'l xaritasi va vazifalar (S0–S5, N1, G1)

> **Versiya:** v2 (2026-10-22). Eski `22_DEVELOPMENT_TASKS_AND_REPO_STRUCTURE` o'rnini bosadi (papka tuzilmasi — [02-folder-skeleton.md](02-folder-skeleton.md)).
> **Bajaruvchi:** founder + AI kodlash yordamchisi. **Stage 2/3 ni oldindan qurmaymiz.**
> **Asos:** DEC-005 (slice'lar), DEC-004 C / ADR-031 (papkalar), DEC-003 D / ADR-033 (outbox + arq), DEC-126 / ADR-032 (`commerce` domeni), [../business/10](../business/10_UAT_ACCEPTANCE_AND_RELEASES.md) §1.

## 0. Amaldagi tartib va holat (2026-10-23, founder)

Ish **modul-modul, har modul to'liq** qilinadi (baza loyihasi → founder tasdig'i → kod → testlar). Har modul bazasi avval `db/<domain>.dbml` da loyihalanadi va tasdiqlanadi. Quyidagi S-vazifalar shu modullarga taqsimlangan; fon ishlari (S0-06) birinchi haqiqiy ehtiyoj bilan — 5-modulda quriladi.

| № | Modul | Ichidagi vazifalar | Holat |
|---|---|---|---|
| — | Texnik asos | S0-01, S0-02, S0-03, S0-07 | ✅ tayyor (testlar: unit + PostgreSQL) |
| 1 | Auth, shop va xodimlar (to'liq auth) | S0-04 (+ CORS, rate limit; `get_db` actor dependency'ga aniq bog'lanadi — shop konteksti va RLS'siz tranzaksiya ochilmasligi uchun) | ✅ kod va testlar (2026-10-23): 33 endpoint, RLS (`memberships`, `sessions`), oxirgi ega trigger'i. Ataylab keyinga: xodim o'zi parol tiklashi (SMS), `switch-shop`, `ws-ticket` ([11](11-api-conventions-errors-i18n.md) §9.1) |
| 2 | Katalog | S1-01…S1-05, S0-08 (fayllar) | Baza loyihasi kutilmoqda |
| 3 | Savdo (commerce) | S1 ombor, S3 lead/taklif, S4 buyurtmalar | — |
| 4 | Shop sayti | S1 storefront | — |
| 5 | Kanallar va inbox | S2, **S0-06** (outbox, arq, scheduler) | — |
| 6 | AI sotuvchi | S3 | — |
| 7 | Xabarnomalar, kafolat, hisobotlar | S2/S5 | — |
| — | Frontend | S0-09, keyin har modul bilan | 1-moduldan keyin |
| — | Monitoring, deploy | S0-05, S0-10 | Pilotdan oldin |

**Muddati bor texnik qarzlar** (fon ishlari bilan birga qilinadi):

| ID | Vazifa | Muddat | Nega |
|---|---|---|---|
| TD-01 | `transition_log` va `audit_entries` uchun har oy kamida 12 oy oldinga partition yaratadigan rejali ish. Mexanizm hal qilinishi kerak: `app_scheduler` da DDL huquqi yo'q — `app_migrator` egaligidagi `SECURITY DEFINER` funksiya yoki deploy migratsiyasi | **2027-12-01 gacha** (migratsiyalar 2028-12 gacha yaratgan; `test_partitions_cover_next_months…` 12 oydan kam qolsa yiqiladi) | Aks holda yozuvlar DEFAULT partition'ga tushadi va keyingi partition yaratilmaydi |
| TD-02 | Eskirgan `idempotency_keys` ni tozalash (soatlik) | 1-pilotdan oldin | Jadval cheksiz o'smasin |

## 1. Qoidalar

1. **Vertikal bo'laklar:** har slice oxirida ishlaydigan, ko'rsatsa bo'ladigan yo'l bor: `shop → katalog → sayt → xabar → AI/taklif → buyurtma → hisobot`. Ajralgan "abstrakt modul" emas.
2. **Papkalar slice bo'yicha yaratiladi.** S0 da faqat `app/shared`, platform modullari va bo'sh `app/domains/`.
3. **import-linter S0 dan majburiy** — birinchi domen paydo bo'lishidan oldin.
4. Tayyor bo'lmagan integratsiya — feature flag ortida (`24` §7).
5. S0–S5 — **Stage 1 ichidagi** ishlab chiqish bo'laklari, alohida tijoriy bosqich emas.
6. Har vazifa — bitta PR, [03-module-requirements.md](03-module-requirements.md) checklisti bilan.

## 2. Umumiy ko'rinish

```
S0 Poydevor ──▶ S1 Katalog va sayt ──▶ S2 Kanallar va inbox ──▶ S3 AI, PC, taklif
   ──▶ S4 Buyurtmalar (to'lovsiz) ──▶ S5 Hisobot va pilotga tayyorlik ──▶ (S5+ ovoz beta)
Parallel: S0-00 Meta arizasi (S2 dagi Instagram uchun)
```

| Slice | Yaratiladigan domen / modul |
|---|---|
| S0 | `shared/*`; `platform/{auth,shops,staff,use,audit,storage}`; workers (outbox, task, scheduler) |
| S1 | `domains/catalog` (products, pricing, pc_specs, imports), `domains/commerce/inventory`, `domains/storefront` |
| S2 | `domains/messaging`, `platform/{notifications,realtime}` |
| S3 | `platform/llm`, `domains/sales_ai`, `catalog/compatibility`, `commerce/{leads,quotes}` |
| S4 | `commerce/orders` |
| S5 | `domains/reporting`, `domains/support`, `platform/billing` |

---

## 3. S0 — Poydevor

| ID | Vazifa | Bog'liq | Qabul mezoni |
|---|---|---|---|
| S0-00 | Meta (Instagram) app review arizasi va biznes verifikatsiyasi | — | Ariza topshirilgan (DEC-116) |
| S0-01 | Python 3.12 + uv, ruff, mypy, pytest, **import-linter** (`.importlinter`: layers + domains-independent), pre-commit, CI | ADR-031 | CI yashil; bo'sh `app/domains/x` boshqa domenni import qilsa CI yiqiladi |
| S0-02 | `app/main.py`, `config/`, `dependencies.py`; DomainManifest avto-ulash; surface router'lari (`shop`, `storefront`, `webhooks`, `platform`); `shared/errors` + global handler (K-07); `shared/i18n` | S0-01 | `/health/live`, `/health/ready`; barcha xatolar bitta formatda, uch tilda |
| S0-03 | `shared/db`: async session, `get_db`/`get_read_db`, mixin'lar (`ShopScopedMixin`), `schemas.sql` (schemalar, `app_migrator`, `app_runtime NOBYPASSRLS`), Alembic multi-env | S0-02 | Rollback va pool testlari; har schema `upgrade/downgrade` |
| S0-04 | `platform/auth` (ADR-023, refresh rotation; WS ticket — realtime bilan), `platform/shops` (FSM-01, filiallar), `platform/staff` (a'zolik, rollar, ruxsat katalogi, `require_permission`, filial doirasi); **RLS spike** (DEC-002): `set_config('app.shop_id', …, true)` async pool bilan | S0-03 | TC-ISO-01…10, TC-025; oxirgi egani o'chirib bo'lmaydi |
| S0-05 | `shared/tracing`, structlog JSON sxemasi, PII filtri, OTel → Grafana Cloud, Sentry (DEC-012) | S0-02 | Bitta `trace_id` API → outbox → arq task'gacha; logda PII yo'q |
| S0-06 | `shared/events` (envelope K-08, `write_outbox`, `@subscribe` registry), `outbox_events` har schemada; `workers/outbox_worker` (SKIP LOCKED, retry, `DEAD`), `workers/task_worker` (arq), `workers/scheduler_worker` (APScheduler + advisory lock) | S0-03 | TC-022 (failpoint), 3 nusxa scheduler → har ish 1 marta; Redis o'chib-yonsa vazifa yo'qolmaydi |
| S0-07 | `platform/use` (validate/log/force transition, rules_loader), `shared/idempotency`, `platform/audit` (append-only, oyma-oy partition) | S0-03 | FSM-01 o'tishlari jurnalda; takror `Idempotency-Key` → bir xil javob |
| S0-08 | `platform/storage` (MinIO, signed URL) | S0-03 | TC-ISO-05 |
| S0-09 | Frontend: pnpm workspace, `shop-dashboard` + `shop-storefront`, auth shell (ADR-023), generatsiya qilingan client, i18n | S0-02 OpenAPI | Rolga qarab 401/403 UX (`21`) |
| S0-10 | Deploy: Docker image (bitta, 4 buyruq), staging, secret'lar, backup va tiklash mashqi | S0-03 | Smoke + tiklash repetitsiyasi |

## 4. S1 — Katalog va sayt

| ID | Vazifa | Domen | Qabul mezoni |
|---|---|---|---|
| S1-01 | Shop va filial sozlash UI, shop sozlamalari (`shop_policy`: taklif muddati, chegirma limitlari, eslatmalar) | `platform/shops` | UAT-M01, UAT-M03 |
| S1-02 | Mahsulot, variant/SKU, atributlar, rasmlar; saytga chiqarish (FSM-02) | `catalog/products` | `UNIQUE (shop_id, sku_code)`, audit, UAT-M04 |
| S1-03 | Narx versiyalari (so'm/dollar), kurs (DEC-121), chegirma qoidalari | `catalog/pricing` | Versiyalar o'zgarmaydi; `catalog.price.changed`; UAT-M05 |
| S1-04 | Texnik ma'lumotlar kutubxonasi: platforma admini CRUD, SKU avto-bog'lash (MPN/model), so'rov (DEC-011, DEC-120) | `catalog/pc_specs` | Bog'lanmagan SKU → `REVIEW_REQUIRED` (`17`) |
| S1-05 | Ombor: `stock_balance`, `stock_ledger`, kirim, tuzatish (tasdiq bilan), **tez sotuv** (DEC-123) | `commerce/inventory` | `available = on_hand − reserved − allocated`; ledger; UAT-M06 |
| S1-06 | CSV/XLSX import — arq vazifasi, avval sinov (dry-run), qator xatolari (`18`) | `catalog/imports` | 5000 qator; xotira o'smaydi; qayta boshlash mumkin |
| S1-07 | Shop sayti: subdomen, katalog va mahsulot sahifalari (CatalogQueryPort + kesh), savatcha → buyurtma so'rovi (`commerce` storefront router, DEC-115) | `storefront`, `commerce` | Chiqarilmagan SKU ko'rinmaydi; kesh event bilan yangilanadi; UAT-M07 |

## 5. S2 — Kanallar va inbox

| ID | Vazifa | Domen | Qabul mezoni |
|---|---|---|---|
| S2-01 | Sayt chati: anonim sessiya, suhbat va xabar modeli (FSM-04) | `messaging/conversations` | Xabar saqlanadi, `messaging.message.received` |
| S2-02 | Telegram adapteri: webhook secret, `(provider, event_id)` dedup | `messaging/channels` | TC-010; UAT-M09 |
| S2-03 | Inbox: holat, biriktirish, operatorga uzatish, `speaker_mode`/`speaker_version` | `messaging/conversations` | Fencing testi (TC-009 qismi); UAT-M10 |
| S2-04 | Chiquvchi xabar: outbox → arq `channel_send`, yetkazish holati, 429/timeout | `messaging`, `workers/tasks` | TC-011, TC-032 |
| S2-05 | Instagram (Meta) adapteri; ruxsat kelguncha flag (DEC-116, DEC-116a) | `messaging/channels` | Meta sandbox sinovi |
| S2-06 | `platform/realtime`: WS ticket, Redis pub/sub relay; `platform/notifications`: xodim vazifalari va bildirishnomalar | platform | TC-ISO-06; WS qayta ulanish |

## 6. S3 — AI, PC moslik, taklif

| ID | Vazifa | Domen | Qabul mezoni |
|---|---|---|---|
| S3-00 | LLM bake-off: 200 dialog (uz/ru/en), 2–3 model (DEC-009, `16`) | — | Tanlangan model + hisobot |
| S3-01 | `platform/llm`: `LLMPort`, PII redaction (DEC-016), xarajat hisobi | platform | Redaction testlari; har chaqiruv xarajati yoziladi |
| S3-02 | `shared/contracts`: `CatalogQueryPort`, `CommerceQueryPort` + implementatsiyalar | `catalog`, `commerce` | `sales_ai` ularni faqat interfeys orqali oladi (import-linter) |
| S3-03 | PC moslik engine: qoidalar `pc-2026-10-v1`, dalil bilan natija (`17`) | `catalog/compatibility` | Noto'g'ri socket → `BLOCK`; noma'lum → `REVIEW_REQUIRED`; TC-008; UAT-M08 |
| S3-04 | AI sotuvchi: orkestrator, tool broker, javob tekshiruvi, handoff (`14`); event'lar `sales_ai.reply.ready`, `sales_ai.handoff.requested` | `sales_ai/agent` | TC-007, TC-009, TC-ISO-02/03; UAT-M11 |
| S3-05 | Leadlar (FSM-05), PC takliflari (FSM-06): versiyalar, menejer/ega tasdig'i (`ALWAYS`/`RISK_ONLY`), 24 soat muddat; subscriber `sales_ai.quote_draft.requested` | `commerce/leads`, `commerce/quotes` | Yuborilgan taklif o'zgarmaydi; muddat; UAT-M12 |
| S3-06 | AI buyurtma qoralamasi: tool `commerce.create_order_draft` → `sales_ai.order_draft.requested` → `commerce` `DRAFT` | `sales_ai`, `commerce/orders` | TC-028 |
| S3-07 | AI sozlamalari: agent profili, FAQ, rejimlar, sinov oynasi, kill switch | `sales_ai/knowledge` | UAT-M19 (AI qismi) |
| S3-08 | Uch tilda AI eval va "soya" rejimi (`16`) | `app/tests/ai_eval` | Eval + xarajat chegarasi o'tadi |

## 7. S4 — Buyurtmalar (to'lovsiz, DEC-100)

| ID | Vazifa | Domen | Qabul mezoni |
|---|---|---|---|
| S4-01 | Buyurtma FSM-08: tasdiqlash (o'ziga biriktirilgan operator / menejer) + ko'p SKU'ni atomik band qilish — **`commerce` ichida bitta tranzaksiya** (ADR-032) | `commerce/orders` + `inventory` | TC-002, TC-003, TC-027 |
| S4-02 | Tayyorlash va topshirish: `allocated → consumed`, `on_hand` kamayadi; bekor qilish (menejer/ega, sabab bilan) | `commerce` | TC-029, TC-030 |
| S4-03 | Izohlar (chat/telefon kelishuvi), `fulfillment_method` + manzil, ixtiyoriy "to'landi" belgisi | `commerce/orders` | Audit; belgi "tekshirilmagan" deb ko'rsatiladi |
| S4-04 | Narx o'zgarishi: tasdiqlashda DB'dan lock ostida qayta tekshirish | `commerce/orders` | TC-031 |
| S4-05 | Rejali ishlar: 24 soat tasdiqlanmagan, 72 soat band qilish ko'rib chiqish (DEC-104) | `commerce` scheduled_jobs | Vazifa yaratiladi, holat o'zgarmaydi |
| S4-06 | Xaridorga holat xabarlari (Telegram/Instagram/sayt) — `commerce` subscriber → `platform/notifications` | `commerce`, platform | Har o'tish uchun bitta xabar; UAT-M13, UAT-M17 |
| — | To'lov tekshiruvi, yetkazish/kuryer | — | `DEFERRED` (DEC-100, DEC-113) |

## 8. S5 — Hisobot, kafolat, pilotga tayyorlik

| ID | Vazifa | Domen | Qabul mezoni |
|---|---|---|---|
| S5-01 | Read model'lar (event proyeksiyalari), metrika registri, bosh sahifa; hisobot yordamchisi (matn, DEC-112) | `reporting` | Raqamlar DB bilan mos, `data_as_of`; TC-013, TC-014; UAT-M18 |
| S5-02 | Kafolat murojaatlari (FSM-11, DEC-114); qaytgan mahsulot karantinda | `support` | TC-020; UAT-M16 |
| S5-03 | Tarif, AI limitlari va ishlatilish (DEC-119); limit tugasa AI o'chadi, savdo ishlaydi | `platform/billing` | UAT-M19 |
| S5-04 | Alertlar, runbook'lar, backup'dan tiklash, yuklama sinovi | ops | TC-033; `25` |
| S5-05 | Shopni yopish oqimi | `platform/shops`, `commerce` | TC-023 |
| S5-06 | Pilotga tayyorlik ko'rigi | — | Founder tasdig'i: Stage 1 muhim sinovlari (`24` §6) |
| S5+-01 | Ovozli hisobot beta: STT/TTS bake-off (DEC-010), audio o'chirish (DEC-117) | `reporting/assistant` | Golden set o'tgach flag; TC-012 |

## 9. Stage 2 — N1…

Shopning o'zi ro'yxatdan o'tishi; kassa/ERP konnektorlari va manba ustuvorligi; `domains/network`: umumiy mahsulot sxemasi, moslashtirishni ko'rib chiqish vositasi, ommaviy taklifga rozilik va qaytarib olish; asinxron indeks; billing va qo'llab-quvvatlashni kengaytirish. Darvoza — shoplar qiziqishi. **Bitta tasdiqlangan hamkordan oldin barcha ERP'larni ulamaymiz.** Batafsil: `28`.

## 10. Stage 3 — G1…

`domains/marketplace`: ommaviy qidiruv ilovasi va SEO, joylashuv bo'yicha qidiruv, solishtirish, xaridorning global AI'si (alohida tool'lar), yo'naltirish, ishonch sifati, organik va reklama farqi. Darvoza — ommaviy takliflar soni va yangiligi. Batafsil: `28`.

---

## 11. AI yordamchiga vazifa topshirish kontrakti

Bitta vazifa — bitta PR. Vazifa matnida:

```text
Vazifa ID / slice:
Domen / sub-modul (yoki platform moduli):
Biznes: M-ID, BL-ID, FSM-ID, UAT/TC-ID:
Kontrakt o'zgarishlari: endpoint + DTO, jadval (schema), event (nomi, payload versiyasi), Query Port:
Migratsiya va shop himoyasi: shop_id, composite FK, RLS:
Tranzaksiya, lock, idempotency; outbox → arq (tashqi chaqiruvlar):
AI tool chegarasi / provayder xatolari:
UI holatlari: loading / empty / error / conflict / permission:
Kuzatuv va maxfiylik: log, metrika, PII yo'q:
Testlar (unit / integratsiya / izolyatsiya / concurrency / e2e) dalili:
Rollback va xavf:
```

Rollar: AI yordamchi kodni yozadi; boshqa model yoki inson arxitekturani ko'rib chiqadi; founder testlarni ishga tushiradi va tasdiqlaydi. Generatsiya qilingani uchun kod qabul qilinmaydi. Batafsil: [23-dev-setup-and-workflow.md](23-dev-setup-and-workflow.md) §8.

## Keyingi qadam

→ [28-network-and-global-search.md](28-network-and-global-search.md)
→ [29-traceability.md](29-traceability.md)
