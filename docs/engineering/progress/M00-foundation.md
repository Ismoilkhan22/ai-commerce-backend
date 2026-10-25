# Texnik asos (S0-01, S0-02, S0-03, S0-07)

> **Holat:** ✅ bitdi — 2026-10-23
> **Branch:** `feat/s0-foundation` · **Commit'lar:** `a7c9011`, `8523bad`, `1623669`, `365800d`, `48893de`, `2fa45fe`
> **Reja:** [27](../27-roadmap-and-tasks.md) §0, "Texnik asos" qatori va §3 (S0 vazifalari)

---

## 1. Nima bitdi — qisqacha

Hamma modullar turadigan poydevor tayyor:

- ilova ishga tushadi va modullarni o'zi topadi;
- xatolar bitta formatda va uch tilda qaytadi;
- baza har domen uchun alohida schemaga bo'lingan, migratsiyalar har schema uchun alohida;
- holat o'tishlari jurnalga yoziladi;
- takroriy so'rov ikki marta bajarilmaydi;
- har muhim o'zgarish auditga tushadi.

Biznes funksiyasi bu yerda yo'q. U 1-moduldan boshlanadi ([M01](M01-auth-shops-staff.md)).

## 2. Rejadagi bandlar

- [x] **S0-01** — Python 3.12 + uv, ruff, mypy strict, pytest, import-linter (qatlamlar va domenlar mustaqilligi), arxitektura testlari
- [x] **S0-02** — `main.py`, sozlamalar, DomainManifest orqali router'larni avtomatik ulash, xato formati (K-07), uch tilli xabarlar, `/health/live`, `/health/ready`
- [x] **S0-03** — async ulanishlar, `get_db` / `get_read_db`, mixin'lar, schemalar va DB rollari, har schema uchun alohida Alembic
- [x] **S0-07** — slim USE (tekshirish, jurnal, majburlash), idempotency, audit (faqat qo'shiladi, oyma-oy bo'lingan)
- [x] Code review (BLOCK) topilmalari tuzatildi: COMMIT javobdan oldin, parallel takror so'rov → 409, majburlash qat'iy va auditli, partition'lar 2028-12 gacha

Keyinga qoldirilgan (reja bo'yicha):

- **S0-06** — fon ishlari (outbox, arq, scheduler) — 5-modulda, birinchi haqiqiy ehtiyoj bilan.
- **S0-05** — monitoring va **S0-10** — deploy — pilotdan oldin.
- **S0-08** — fayllar (MinIO) — 2-modulda.

---

## 3. Fayllar xaritasi

```
app/
├── main.py                       # ilovani yig'adi: middleware, manifest'lar, health
├── dependencies.py               # composition root: Query Port'lar (hozircha bo'sh)
├── config/
│   ├── settings.py               # muhit sozlamalari (pydantic-settings)
│   └── logging.py                # structlog JSON
├── db/
│   ├── schemas.py  schemas.sql   # 9 ta schema, app_migrator / app_runtime rollari va huquqlar
│   ├── bootstrap.py              # bazani birinchi marta tayyorlash
│   ├── checks.py                 # schemalar orasida FK yo'qligini tekshirish
│   ├── models.py                 # qaysi schemada qaysi ORM modellari
│   └── migrations/
│       ├── env_common.py         # hamma schema uchun umumiy Alembic logikasi
│       └── <schema>/versions/    # har schema o'z migratsiyalari bilan
├── shared/
│   ├── db/        base.py  ids.py  mixins.py  partitions.py  session.py
│   ├── errors/    base.py  catalog.py  handlers.py
│   ├── i18n/      locale.py  translator.py  middleware.py  locales/{uz,ru,en}.yml
│   ├── idempotency/  store.py  dependency.py  models.py
│   ├── tracing/   context.py  middleware.py
│   ├── observability/health.py
│   ├── types/     actor.py  manifest.py  state.py
│   └── serialization.py
├── platform/
│   ├── use/       services/use_service.py  infrastructure/rules_loader.py  models/orm.py
│   └── audit/     services/audit_service.py  models/orm.py
├── domains/                      # bo'sh — domenlar modul-modul qo'shiladi
└── workers/                      # bo'sh — S0-06 da
deploy/docker-compose.yml         # lokal PostgreSQL 16, Redis 7, MinIO
tests/
├── architecture/                 # qatlam chegaralari
├── unit/                         # ilova, xatolar, DB yordamchilari
└── integration/                  # haqiqiy PostgreSQL (testcontainers)
```

---

## 4. Qaysi faylda nima bor

### 4.1 Ilova va sozlamalar

- **`app/main.py`**
  - `create_app(settings)` — FastAPI ilovasini yig'adi. Middleware tartibi: request-id va trace (eng tashqi) → til → endpoint.
  - `discover_manifests()` — `app/platform/*` va `app/domains/*` dagi manifest'larni topadi.
  - `mount_manifests()` — router'larni surface prefiksi bilan ulaydi (`/api/v1/shop`, `/platform`, `/storefront`, ...). Ikki modul bir xil yo'lni e'lon qilsa, ilova ishga tushmaydi (`RouteConflictError`).
- **`app/config/settings.py`** — `Settings`. Production/staging'da xavfli standart qiymatlar bilan ishga tushmaydi (DB URL'lar va boshqalar).
- **`app/config/logging.py`** — structlog, JSON format.

### 4.2 Baza

- **`app/db/schemas.sql`** — schemalar: `platform`, `audit`, `catalog`, `commerce`, `messaging`, `sales_ai`, `storefront`, `support`, `reporting`. Rollar:
  - `app_migrator` — jadvallar egasi, migratsiyalarni bajaradi;
  - `app_runtime` — ilova shu rol bilan ishlaydi: superuser emas, RLS'ni chetlab o'ta olmaydi.
- **`app/db/bootstrap.py`** — rollar, schemalar va huquqlarni bir marta yaratadi (`make bootstrap`).
- **`app/db/migrations/env_common.py`**
  - Har schema o'z `alembic_version` jadvaliga ega.
  - Autogenerate partition'larni "ortiqcha jadval" deb o'chirib yubormaydi.
  - Runtime roli `alembic_version` ni o'zgartira olmaydi.
- **`app/db/checks.py`** — `cross_schema_foreign_keys()`: domenlar orasida FK bo'lmasligi kerak (TC-DB-05).
- **`app/shared/db/session.py`**
  - `Database.transaction(shop_id)` — bitta tranzaksiya va RLS uchun `set_config('app.shop_id', ..., true)`. Qiymat faqat shu tranzaksiyada amal qiladi.
  - `get_db` / `get_read_db` — `scope="function"`, ya'ni COMMIT javob yuborilishidan **oldin** bo'ladi.
- **`app/shared/db/mixins.py`** — `IdMixin` (UUIDv7), `TimestampMixin`, `ShopScopedMixin` (`shop_id NOT NULL`), `VersionMixin`.
- **`app/shared/db/ids.py`** — `uuid7()`: vaqt bo'yicha tartiblangan ID (Python 3.12 da tayyori yo'q).
- **`app/shared/db/partitions.py`** — oyma-oy partition yaratish SQL'i (jurnal va audit uchun).

### 4.3 Xatolar va tillar

- **`app/shared/errors/base.py`** — `DomainError` va undan tarqalgan 30+ xato: `NotFoundError`, `ForbiddenError`, `VersionConflictError`, `InvalidTransitionError`, ... Service qatlami HTTP'ni bilmaydi, faqat shu xatolarni ko'taradi.
- **`app/shared/errors/catalog.py`** — xato kodlari katalogi (33 ta): kod → HTTP status → tarjima kaliti. Yagona manba.
- **`app/shared/errors/handlers.py`** — hamma xato bitta ko'rinishda qaytadi:

  ```json
  {"error": {"code": "VERSION_CONFLICT", "message": "...", "details": {...}, "trace_id": "..."}}
  ```

  Pydantic validatsiya xatolari `VALIDATION_FAILED` + `fields[]` ga aylantiriladi.
- **`app/shared/i18n/`** — til `Accept-Language` dan aniqlanadi (uz, ru, en). Xato matnlari `locales/*.yml` da. `missing_keys()` test orqali tarjima tushib qolmaganini tekshiradi.

### 4.4 Holatlar, takroriy so'rov, audit

- **`app/shared/types/state.py`** — `StateMachineRule`: bitta strelka (`entity_type`, `command`, `from`, `to`, kim bajaradi, sabab kerakmi).
- **`app/platform/use/infrastructure/rules_loader.py`** — `RulesRegistry`: manifest'lardagi qoidalarni yig'adi. Bir xil qoida ikki marta bo'lsa, xato beradi.
- **`app/platform/use/services/use_service.py`** — `UseService`, uchta ish:
  - `validate_transition` — bunday strelka bormi, bu actor bajara oladimi, sabab berilganmi;
  - `log_transition` — `platform.transition_log` ga yozadi (o'zgartirib va o'chirib bo'lmaydi);
  - `force_transition` — faqat platforma admini (`platform.state.force`), kamida 20 belgili sabab va audit bilan. Pul va qoldiq holatlarini majburlab bo'lmaydi.
- **`app/shared/idempotency/store.py`** — `IdempotencyStore`:
  - bir xil kalit va bir xil tana → saqlangan javob qaytadi;
  - bir xil kalit, boshqa tana → `409 IDEMPOTENCY_KEY_REUSED`;
  - birinchi so'rov hali tugamagan bo'lsa → `409 REQUEST_IN_PROGRESS` (advisory lock).
- **`app/shared/idempotency/dependency.py`** — `Idempotency-Key` header'i majburiy.
- **`app/platform/audit/services/audit_service.py`** — `AuditService.record(...)`: biznes o'zgarishi bilan bitta tranzaksiyada yoziladi. Diff'da parol, token kabi kalitlar bo'lsa, xato beradi (PII auditga tushmasin). Jadvalga faqat qo'shish mumkin: `UPDATE` va `DELETE` huquqi olib tashlangan.

### 4.5 So'rovni kuzatish

- **`app/shared/tracing/`** — har so'rovga `X-Request-ID` va `trace_id` (W3C `traceparent`) beriladi. Ular log va xato javobiga qo'shiladi.
- **`app/shared/observability/health.py`** — `/health/live` (jarayon tirikmi) va `/health/ready` (PostgreSQL, keyin Redis ham).

---

## 5. Testlar

Texnik asos yakunida: **123 passed** (hozir 1-modul bilan birga 168).

- [x] `tests/architecture/test_boundaries.py` — `shared` → `platform` → `domains` qatlamlari buzilmagan, domenlar bir-birini import qilmaydi
- [x] `tests/unit/test_app.py` — manifest'larni ulash, yo'l to'qnashuvi, health
- [x] `tests/unit/test_errors.py` — har xato kodi to'g'ri status va uch tilda xabar bilan
- [x] `tests/integration/test_database.py` — har schema `upgrade` / `downgrade`, modellar migratsiyalar bilan bir xil, schemalar orasida FK yo'q, runtime roli RLS'ni chetlab o'ta olmaydi va DDL bajara olmaydi, xatoda ROLLBACK, shop konteksti keyingi tranzaksiyaga o'tmaydi, faqat o'qish tranzaksiyasi yozmaydi
- [x] `tests/integration/test_http_transactions.py` — COMMIT paytidagi konflikt mijozga 409 bo'lib yetadi, idempotent endpoint HTTP orqali
- [x] `tests/integration/test_use_idempotency_audit.py` — o'tishlar jurnali, takror so'rov, parallel takror so'rov → 409, majburlash qoidalari, audit, partition'lar kamida 12 oy oldinga bor
- [x] `tests/integration/test_versioning.py` — optimistic lock (`version`)

## 6. Muddati bor texnik qarzlar

- **TD-01** — partition'larni har oy oldinga yaratadigan rejali ish. Muddat: **2027-12-01** (S0-06 bilan).
- **TD-02** — eskirgan `idempotency_keys` ni tozalash. Muddat: 1-pilotdan oldin.
