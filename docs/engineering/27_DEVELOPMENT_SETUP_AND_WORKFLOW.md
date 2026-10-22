# TECH-27 — Development setup, ish tartibi va sifat qoidalari

**Status:** Baseline (2026-10-22). ADR-022 (repo skeleti), ADR-010 (frontend), ADR-029 (observability), TECH-22 (vazifalar), TECH-20 (testlar) asosida.
**Kim uchun:** founder, kelajakdagi dasturchilar va AI kodlash yordamchilari.

---

## 1. Vositalar

### Backend (`ai-commerce-backend`)

| Vosita | Versiya / qoida | Vazifasi |
|---|---|---|
| Python | 3.12 | runtime |
| uv | oxirgi barqaror | paketlar, virtual muhit, `uv.lock` |
| FastAPI, Pydantic v2, SQLAlchemy 2 (async), asyncpg, Alembic | `pyproject.toml` da pin qilingan | ilova |
| ruff | lint + format | kod uslubi (black o'rniga) |
| mypy | `strict = true` (`src/`), testlarda yumshoqroq | turlar |
| pytest, pytest-asyncio, hypothesis | — | unit, integration, property testlar |
| import-linter | `pyproject.toml` da kontraktlar | context chegaralari (ADR-001, ADR-021) |
| pre-commit | ruff, mypy (o'zgargan fayllar), secret scan | commit oldidan tekshiruv |
| Docker, Docker Compose | — | lokal PostgreSQL 16, Redis 7 |

### Frontend (`ai-commerce-frontend`)

| Vosita | Qoida |
|---|---|
| Node.js LTS, pnpm | workspace (`apps/*`, `packages/*`) |
| Next.js, TypeScript `strict` | ikki app: `merchant-dashboard`, `merchant-storefront` |
| ESLint, Prettier | lint/format |
| Vitest, Playwright | unit va E2E |
| `packages/api-client` | backend OpenAPI'dan generatsiya; qo'lda yozilmaydi |

## 2. Lokal muhit

```bash
# backend
git clone git@github.com:Ismoilkhan22/ai-commerce-backend.git && cd ai-commerce-backend
cp .env.example .env                 # faqat lokal qiymatlar, haqiqiy kalitlar yo'q
docker compose up -d postgres redis
uv sync
uv run alembic upgrade head
uv run python -m commerce_os.scripts.seed_dev   # 2 ta test do'kon (A va B), rollar, katalog
uv run uvicorn commerce_os.bootstrap.app_factory:create_app --factory --reload
uv run python -m commerce_os.workers.main        # worker (alohida terminal)

# frontend
cd ../ai-commerce-frontend && pnpm install
pnpm --filter api-client generate     # backend ishlab turgan bo'lsa, OpenAPI'dan
pnpm --filter merchant-dashboard dev
```

**Seed ma'lumot:** har doim ikkita do'kon (A va B) — tenant izolyatsiyasini lokalda ham ko'rish uchun (TECH-23 §7). Faqat sintetik ma'lumot; haqiqiy xaridor ma'lumoti lokal yoki staging'ga hech qachon yuklanmaydi.

**Muhit o'zgaruvchilari:** `.env.example` da barcha kalitlar ro'yxati (izoh bilan). Ilova ishga tushganda Pydantic `Settings` bilan validatsiya; majburiy qiymat yo'q bo'lsa — ishga tushmaydi. Production kalitlari — secret manager'da, repoda emas.

## 3. Git ish tartibi

| Mavzu | Qoida |
|---|---|
| Asosiy branch | `main` — doim deploy qilinadigan holatda; to'g'ridan-to'g'ri push yo'q |
| Branch nomi | `<tur>/<qisqa-nom>`: `feat/s0-auth`, `fix/order-confirm-race`, `docs/…`, `chore/…` |
| Commit | Conventional Commits: `feat(orders): add confirm workflow`, `fix(inventory): …`, `docs: …`. Bitta commit — bitta mantiqiy o'zgarish |
| PR | Kichik (≤ ~400 qator o'zgarish, migratsiya va generatsiya qilingan fayllardan tashqari); bitta TECH-22 vazifasi (masalan, `S0-04`) |
| Merge | Squash merge; PR sarlavhasi Conventional Commit formatida |
| Teglar | Reliz: `v0.<slice>.<patch>` (masalan, `v0.1.0` — S1) |

### PR shabloni (`.github/pull_request_template.md`)

```text
## Vazifa
TECH-22 ID: S_-__ · Business: M__ / BL-___ · DEC: ___ · Test ID: TC-___

## Nima o'zgardi

## Tekshiruv ro'yxati
- [ ] Tenant: merchant_id faqat ActorContext'dan; A/B testi qo'shildi yoki mavjud
- [ ] DB migratsiya: expand/contract, rollback yo'li yozilgan
- [ ] Tranzaksiya/lock/idempotency (yozish amallari uchun)
- [ ] Xatolar K-07 kodlari bilan; yangi kod bo'lsa TECH-24 va i18n kalitlari
- [ ] Audit yozuvi (sezgir amallar)
- [ ] Log/trace: PII yo'q; kerakli span/metrika
- [ ] UI holatlari: loading / empty / error / conflict / permission
- [ ] Testlar: unit + integration (PostgreSQL) + kerak bo'lsa concurrency
- [ ] Hujjat yangilandi (agar kontrakt yoki qaror o'zgarsa)

## Xavf va rollback
```

## 4. CI (GitHub Actions)

Har PR'da (TECH-19 §3 bilan bir xil tartib):

1. `ruff check`, `ruff format --check`, `mypy`
2. `lint-imports` (context chegaralari)
3. Unit testlar
4. PostgreSQL + Redis service bilan integration va concurrency testlari (`TC-ISO-*`, `TC-002`, `TC-027`…)
5. Alembic: `upgrade head` → `downgrade -1` → `upgrade head` (bo'sh DB'da)
6. OpenAPI generatsiya → oldingi versiya bilan farq; breaking o'zgarish bo'lsa `breaking-change` label talab qilinadi
7. i18n tekshiruvi: xato kodlari uchun kalitlar (TECH-24 §5.5) — frontend repoda
8. Secret scan, dependency audit
9. (S3 dan) AI eval'ning tezkor qismi — o'zgargan prompt yoki tool bo'lsa

`main` ga merge → staging'ga avtomatik deploy (S0-08 dan). Production — qo'lda tasdiq bilan.

## 5. Kod qoidalari (qisqa)

- **Qatlamlar:** `presentation → application → domain`; domain FastAPI, SQLAlchemy, httpx import qilmaydi. Boshqa context'ning `infrastructure` yoki modellarini import qilish taqiqlangan — faqat `public.py` orqali (import-linter tekshiradi).
- **Kontekstlararo yozuv** faqat `workflows/` da (ADR-021).
- **Tranzaksiya ichida** tashqi so'rov (LLM, Telegram, HTTP) yo'q (TECH-07 §7).
- **Pul** faqat `Money` value object orqali; `float` taqiqlangan (ruff qoidasi + review).
- **Vaqt** `Clock` port orqali (testda boshqariladi); `datetime.now()` to'g'ridan-to'g'ri ishlatilmaydi.
- **Xatolar** `DomainError` vorislari (TECH-24 §4.1); `HTTPException` faqat presentation'da va faqat istisno holatda.
- **Log** — strukturali, `logger.info("order.confirmed", order_id=…)`; f-string ichida PII yo'q.
- **Test nomi:** `test_<nima>_<qachon>_<natija>`; concurrency testlari barrier bilan, `sleep` bilan emas.

## 6. AI kodlash yordamchisi bilan ishlash

TECH-22 §10 dagi kontrakt asosida:

1. Bitta vazifa — bitta PR. AI'ga vazifa ID'si, tegishli hujjat bo'limlari (BL, FSM, TECH) va qabul testlari beriladi.
2. AI yozgan kod ham xuddi shu CI va review'dan o'tadi; "generatsiya qilingan" degani "tekshirilgan" degani emas.
3. Kontrakt (API sxemasi, DB jadvali, FSM) o'zgarsa — avval hujjat, keyin kod; qaror bo'lsa — `decisions/DECISION_REGISTER.md`.
4. Pul, stok, tenant izolyatsiyasi va AI tool'lariga tegadigan PR'lar uchun inson review majburiy (founder yoki tayinlangan reviewer).
5. Maxfiy kalitlar, haqiqiy xaridor ma'lumoti va production log'lari AI yordamchiga berilmaydi.

## 7. Definition of Done

TECH-20 §7 bilan bir xil; qisqacha: biznes qoidasi + ruxsat + typed DTO + migratsiya + idempotency/concurrency + audit + log/trace + UI holatlari + testlar (unit, integration, kerak bo'lsa e2e) + hujjat + feature flag (kerak bo'lsa) + staging demo. Faqat endpoint yozilgani — "tayyor" emas.

## 8. Muhitlar

| Muhit | Ma'lumot | Tashqi servislar | Deploy |
|---|---|---|---|
| local | sintetik seed (A/B do'konlar) | mock / sandbox | qo'lda |
| CI | fixture'lar | yo'q (fake adapterlar) | — |
| staging | sintetik yoki anonimlashtirilgan | Telegram test bot, Meta sandbox, LLM sandbox kalit | `main` merge'da avtomatik |
| production | real (huquqshunos xulosasidan keyin, DEC-013) | tasdiqlangan akkauntlar | qo'lda tasdiq, canary |
