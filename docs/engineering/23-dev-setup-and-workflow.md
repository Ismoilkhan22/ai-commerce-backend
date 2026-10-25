# 23 — Lokal muhit, ish tartibi va sifat qoidalari

> **Versiya:** v2 (2026-10-22). Eski `27_DEVELOPMENT_SETUP_AND_WORKFLOW` o'rnini bosadi. ADR-031 (papkalar), ADR-033 (outbox + arq), ADR-035 (schema per domain), ADR-029 (observability).
> **Kim o'qiydi:** founder, kelajakdagi dasturchilar va AI kodlash yordamchilari.

## 1. Muammo va yechim

**Muammo:** loyihani asosan bitta odam AI yordamchi bilan yozadi. Agar lokal muhit, CI va PR qoidalari aniq bo'lmasa, AI yozgan kod qatlam chegaralarini, shop izolyatsiyasini yoki idempotency'ni sezdirmasdan buzadi.

**Yechim:** bitta buyruq bilan ko'tariladigan lokal muhit, har PR'da bir xil CI tekshiruvlari, har vazifa uchun aniq checklist ([03-module-requirements.md](03-module-requirements.md)) va Definition of Done (§8).

---

## 2. Vositalar

### Backend (`ai-commerce-backend`)

| Vosita | Qoida | Vazifasi |
|---|---|---|
| Python 3.12 | — | runtime |
| uv | `uv.lock` commit qilinadi | paketlar, virtual muhit |
| FastAPI, Pydantic v2, SQLAlchemy 2 (async), asyncpg, Alembic | `pyproject.toml` da pin | ilova |
| arq, APScheduler | — | fon vazifalari va rejali ishlar (ADR-033) |
| structlog, OpenTelemetry SDK, sentry-sdk | — | log, trace, xato (ADR-029) |
| httpx | `requests` TAQIQ | tashqi chaqiruvlar |
| ruff | lint + format | kod uslubi |
| mypy | `strict = true` (`app/`) | turlar |
| import-linter | `.importlinter` (`02` §3) | qatlam va domen chegaralari |
| pytest, pytest-asyncio, hypothesis | — | testlar |
| testcontainers | PostgreSQL 16, Redis 7 | integratsiya testlari haqiqiy DB bilan |
| pre-commit | ruff, mypy (o'zgargan fayllar), secret scan, `lint-imports` | commit oldidan |
| Docker Compose | — | lokal PostgreSQL, Redis (fayllar — diskda, `var/storage`) |

### Frontend (`ai-commerce-frontend`)

| Vosita | Qoida |
|---|---|
| Node.js LTS, pnpm | workspace (`apps/*`, `packages/*`) |
| Next.js, TypeScript `strict` | `shop-dashboard`, `shop-storefront` |
| ESLint, Prettier, Vitest, Playwright | — |
| `packages/api-client` | backend OpenAPI'dan generatsiya; qo'lda yozilmaydi |

---

## 3. Lokal muhit

```bash
# 1. Backend
git clone git@github.com:Ismoilkhan22/ai-commerce-backend.git && cd ai-commerce-backend
cp .env.example .env                       # faqat lokal qiymatlar, haqiqiy kalitlar yo'q
make up                                    # PostgreSQL :5433, Redis :6380 (o'z PostgreSQL/Redis'ingiz bilan to'qnashmaydi)
uv sync
make bootstrap                             # rollar (app_migrator, app_runtime) + app/db/schemas.sql; .env'dan o'qiydi
make migrate                               # barcha schema env'lari (§4)
make seed                                  # demo: platforma jamoasi va 8 ta shop (ixtiyoriy)
PLATFORM_ADMIN_PASSWORD='...' uv run python -m app.platform.staff.cli create-platform-admin \
  --phone "+998900000001" --name "Platforma Admin"     # birinchi platforma admini

# 2. Jarayonlar
uv run uvicorn app.main:app --port 8000 --reload          # API; Swagger — http://localhost:8000/docs
# Fon ishlari (outbox_worker, arq, scheduler) — 5-modulda qo'shiladi

# 3. Frontend (ai-commerce-frontend/README.md)
cd ../ai-commerce-frontend && pnpm install
pnpm api:generate                          # backend ishlab turgan bo'lsa: /api/v1/openapi.json → turlar
pnpm dev                                   # shop paneli :3000, platforma paneli :3001
pnpm test:e2e                              # Playwright (backend va admin kerak)
```

**Demo ma'lumot:** `make seed` — platforma jamoasi (admin, yordam, taklif qilingan a'zo) va 8 ta shop turli holatda (tekshiruvda, faol pilot, to'xtatilgan, egasi kirmagan). Servislar orqali yaratiladi — audit va jurnal haqiqiydagidek; qayta ishga tushirish xavfsiz. Kirish ma'lumotlari skript oxirida chiqadi. **Fayllar:** lokal va testda diskda (`STORAGE_LOCAL_DIR`, standart `var/storage`, git'ga kirmaydi) — `FileStorage` portining disk adapteri (2-modul). MinIO ishlatilmaydi: obrazi Docker Hub'dan endi yuklanmaydi. Production uchun S3-mos adapter deploy bilan qo'shiladi (S0-10, TD-03).

**Seed ma'lumot:** har doim ikkita shop (A va B) — izolyatsiyani lokalda ham ko'rish uchun (TC-ISO). Faqat sintetik ma'lumot; haqiqiy xaridor ma'lumoti lokal yoki staging'ga hech qachon yuklanmaydi.

**Muhit o'zgaruvchilari:** `.env.example` da barcha kalitlar izoh bilan. `Settings` ishga tushishda validatsiya qiladi; majburiy qiymat yo'q bo'lsa — jarayon ishga tushmaydi. DB'ga ikki URL: `DATABASE_URL` (`app_runtime`, `NOBYPASSRLS`) va `DATABASE_MIGRATOR_URL` (`app_migrator`, faqat migratsiya). Production kalitlari — secret manager'da.

**Tashqi servislar lokalda:** Telegram, Meta va LLM uchun fake adapterlar (`LLM_PROVIDER=fake`, `CHANNEL_MODE=fake`). Haqiqiy sandbox — staging'da.

---

## 4. Alembic — har schema uchun env (ADR-035)

```bash
# Barcha schemalar (Makefile: make migrate)
for s in platform audit catalog commerce messaging sales_ai storefront support reporting; do
  uv run alembic -n $s upgrade head
done

# Bitta domen uchun yangi migratsiya
uv run alembic -n commerce revision --autogenerate -m "orders: add ready_at"

# Orqaga qaytarish tekshiruvi (CI ham qiladi)
uv run alembic -n commerce downgrade -1 && uv run alembic -n commerce upgrade head
```

Qoidalar:
- Migratsiya faqat o'z schemasiga tegadi; cross-schema FK — TAQIQ (CI tekshiradi).
- Expand → contract: avval yangi ustun/jadval qo'shiladi, kod o'tadi, keyingi relizda eskisi olib tashlanadi.
- Har shop jadvalida `shop_id NOT NULL`; sezgir jadvalda RLS policy shu migratsiyada (`10`).
- Katta jadvalga indeks — `CREATE INDEX CONCURRENTLY` (alohida migratsiya, tranzaksiyasiz).

---

## 5. Git ish tartibi

| Mavzu | Qoida |
|---|---|
| Asosiy branch | `main` — doim deploy qilinadigan; to'g'ridan-to'g'ri push yo'q |
| Branch nomi | `<tur>/<qisqa-nom>`: `feat/s0-auth`, `fix/order-confirm-race`, `docs/...`, `chore/...` |
| Commit | Conventional Commits, scope — domen yoki platform moduli: `feat(commerce): order confirm`, `fix(messaging): speaker fencing` |
| PR | Kichik (≤ ~400 qator, migratsiya va generatsiya qilingan fayllardan tashqari); bitta `27` vazifasi (`S0-04`) |
| Merge | Squash; PR sarlavhasi Conventional Commit formatida |
| Arxitektura o'zgarishi | `arch-change` belgisi + ADR (`ADR/`) |
| Teglar | `v0.<slice>.<patch>` (masalan `v0.1.0` — S1) |

### PR shabloni (`.github/pull_request_template.md`)

```text
## Vazifa
Roadmap ID: S_-__ · Biznes: M__ / BL-___ · DEC: ___ · Test: TC-___ / UAT-M__
Domen / platform moduli: ______

## Nima o'zgardi

## Checklist (03-module-requirements)
- [ ] Qatlamlar: domen boshqa domenni import qilmaydi; lint-imports o'tadi
- [ ] Domenlararo yozish faqat event (outbox), o'qish faqat Query Port (shared/contracts)
- [ ] shop_id faqat ActorContext'dan; A/B izolyatsiya testi qo'shildi yoki mavjud
- [ ] Migratsiya: o'z schemasi, expand/contract, downgrade ishlaydi, shop_id + RLS
- [ ] Holat o'zgarishi: use.validate_transition + log_transition; repository status yozmaydi
- [ ] Yozish amali: Idempotency-Key, tranzaksiya chegarasi aniq, tranzaksiya ichida tashqi chaqiruv yo'q
- [ ] Event: nomi <domain>.<entity>.<action>, payload versiyalangan, PII yo'q
- [ ] Xatolar K-07 kodlari bilan; yangi kod — katalog va uz/ru/en tarjima
- [ ] Audit yozuvi (sezgir amallar)
- [ ] Log/trace/metrika: PII yo'q, cos_<domain>_... metrikalar
- [ ] UI holatlari (agar frontend): loading / empty / error / conflict / permission
- [ ] Testlar: unit + integratsiya (PostgreSQL) + kerak bo'lsa concurrency
- [ ] docs/modules/<domain>/README.md yangilandi

## Xavf va rollback
```

---

## 6. CI (GitHub Actions)

Har PR'da:

1. `ruff check`, `ruff format --check`, `mypy`
2. `lint-imports` (qatlamlar va domenlar mustaqilligi)
3. Unit testlar
4. testcontainers (PostgreSQL + Redis) bilan integratsiya, izolyatsiya (`TC-ISO-*`) va concurrency (`TC-002`, `TC-027`, `TC-030`) testlari
5. Migratsiyalar: bo'sh DB'da har schema `upgrade head` → `downgrade -1` → `upgrade head`; cross-schema FK yo'qligi tekshiruvi
6. DB rollar tekshiruvi: `app_runtime` `BYPASSRLS` yoki superuser emas (TC-ISO-10)
7. State machine muvofiqligi: `state_machine.py` ↔ `../business/05` (ADR-034)
8. OpenAPI generatsiya → oldingi versiya bilan farq; breaking o'zgarish bo'lsa `breaking-change` belgisi talab qilinadi
9. i18n: har xato kodi uchun `uz`, `ru`, `en` kalitlari mavjud
10. Secret scan, dependency audit
11. (S3 dan) AI eval'ning tezkor qismi — prompt yoki tool o'zgargan bo'lsa (`16`)

`main` ga merge → staging'ga avtomatik deploy (S0-08 dan). Production — qo'lda tasdiq bilan (`24` §6).

---

## 7. Kod qoidalari (qisqa)

To'liq ro'yxat — [00-vision-and-principles.md](00-vision-and-principles.md) §2–3 va [03-module-requirements.md](03-module-requirements.md).

- **Qatlamlar:** `shared` ← `platform` ← `domains`; domenlar bir-birini import qilmaydi. Domenlararo kontraktlar — `app/shared/contracts/`.
- **Service** stateless; `db` va `actor` — method argumentlari.
- **Tranzaksiya ichida** tashqi so'rov (LLM, Telegram, HTTP) yo'q — outbox → arq.
- **Navbatga** faqat outbox orqali; service to'g'ridan-to'g'ri `arq.enqueue()` qilmaydi (ADR-033).
- **Pul** faqat `Money` orqali; `float` taqiqlangan.
- **Vaqt** `Clock` orqali (testda boshqariladi); `datetime.now()` to'g'ridan-to'g'ri ishlatilmaydi.
- **Xatolar** `DomainError` vorislari (`11`); `HTTPException` faqat istisno holatda.
- **Log** — strukturali: `log.info("order.confirmed", order_id=...)`; f-string ichida PII yo'q; `print()` yo'q.
- **Test nomi:** `test_<nima>_<qachon>_<natija>`; concurrency testlari barrier bilan, `sleep` bilan emas.

---

## 8. AI kodlash yordamchisi bilan ishlash

1. **Bitta vazifa — bitta PR.** AI'ga beriladi: vazifa ID'si (`27`), domen, tegishli `BL-xxx`, `FSM-xx`, engineering bo'limlari, qabul testlari (`TC-xxx`).
2. AI har doim shu fayllarni kontekst sifatida oladi: `00-vision-and-principles.md`, `02-folder-skeleton.md`, `03-module-requirements.md`, tegishli `../modules/<domain>/README.md`.
3. AI yozgan kod xuddi shu CI va review'dan o'tadi; "generatsiya qilingan" ≠ "tekshirilgan".
4. Kontrakt (API, jadval, holat, event) o'zgarsa — avval hujjat, keyin kod; qaror bo'lsa — `../decisions/DECISION_REGISTER.md`.
5. Pul, qoldiq, shop izolyatsiyasi va AI tool'lariga tegadigan PR — inson review majburiy.
6. Maxfiy kalitlar, haqiqiy xaridor ma'lumoti va production loglari AI yordamchiga berilmaydi.
7. AI yangi kutubxona qo'shmoqchi bo'lsa — PR tavsifida sababi; texnologiyalar ro'yxati (`00` §5) ADR'siz o'zgarmaydi.

### AI uchun vazifa shabloni

```text
Vazifa: S_-__ — <qisqa nom>
Domen / sub-modul: commerce/orders
Biznes: M13, BL-0xx, FSM-08 (business/05)
Kontrakt: endpoint, DTO, event, jadval o'zgarishi
Invariantlar: ...
Xato holatlari va kodlar: ...
Testlar: TC-0xx, izolyatsiya, concurrency
Qilinmaydi: ...
Checklist: 03-module-requirements.md
```

---

## 9. Definition of Done

Vazifa tayyor, agar:
- [ ] Biznes qoidasi va ruxsatlar (`../business/03`, `04`) amalga oshirilgan
- [ ] Tipli DTO'lar, OpenAPI misollari
- [ ] Migratsiya (o'z schemasi, `shop_id`, RLS kerak bo'lsa, indekslar)
- [ ] Idempotency va concurrency (yozish amallari)
- [ ] Holat o'zgarishlari USE orqali, transition log va audit
- [ ] Event'lar outbox orqali, payload kontrakti `shared/contracts/events/` da (boshqa domen tinglasa)
- [ ] Log, trace, metrikalar (PII'siz)
- [ ] UI holatlari (agar frontend qismi bo'lsa)
- [ ] Testlar: unit, integratsiya, izolyatsiya, kerak bo'lsa concurrency va e2e
- [ ] `docs/modules/<domain>/README.md` va kerakli engineering hujjati yangilangan
- [ ] Feature flag (tayyor bo'lmagan integratsiya uchun)
- [ ] Staging'da ko'rsatilgan

Faqat endpoint yozilgani — "tayyor" emas.

---

## 10. Muhitlar

| Muhit | Ma'lumot | Tashqi servislar | Deploy |
|---|---|---|---|
| local | sintetik seed (A/B shoplar) | fake adapterlar | qo'lda |
| CI | fixture'lar, testcontainers | yo'q (fake) | — |
| staging | sintetik yoki anonimlashtirilgan | Telegram test bot, Meta sandbox, LLM sandbox kalit | `main` merge'da avtomatik |
| production | haqiqiy (huquqshunos xulosasidan keyin, DEC-013) | tasdiqlangan akkauntlar | qo'lda tasdiq, bosqichma-bosqich |

Batafsil: [22-infrastructure-and-deployment.md](22-infrastructure-and-deployment.md).

## Keyingi qadam

→ [24-testing-and-release.md](24-testing-and-release.md)
→ [27-roadmap-and-tasks.md](27-roadmap-and-tasks.md)
