# AI Commerce OS — Engineering hujjatlari v2

> **Holat:** v2 (2026-10-22) — `bismuth_platform_v2/docs/v2` standartiga moslab qayta yozilmoqda (DEC-125). Kod hali yo'q.
> **Maqsad:** pilotdan (1–5 shop) yuzlab shopgacha bitta modular monolith'da ishlaydigan, kerak bo'lsa **og'riqsiz alohida servislarga ajratiladigan** backend.
> **Asosiy qarorlar:** papkalar — bismuth v2 uslubi (DEC-004 C), domenlar aloqasi — event + Query Port, `commerce` bitta domen (DEC-126), navbat — outbox + arq (DEC-003 D), monitoring — Grafana Cloud + Sentry (DEC-012).

## Eng muhim 6 ta qaror (TL;DR)

1. **Uch qatlam:** `app/shared` ← `app/platform` ← `app/domains`. Domenlar bir-birini import qilmaydi — CI tekshiradi.
2. **Domenlar orasida yozish faqat event (outbox), o'qish faqat Query Port.** Pul va qoldiq invarianti (tasdiqlash + band qilish) bitta `commerce` domeni ichida, bitta tranzaksiyada.
3. **Har domen — o'z PostgreSQL schemasi;** har shop jadvalida `shop_id NOT NULL`, sezgir jadvallarda RLS.
4. **Slim USE:** holat o'tishini tekshirish + jurnal + idempotency. Boshqa side-effect'lar — event orqali.
5. **Fon ishlari:** outbox (PostgreSQL) → arq (Redis); rejali ishlar — APScheduler + advisory lock.
6. **AI hech qachon haqiqat manbai emas:** faqat Query Port orqali o'qiydi va event orqali qoralama so'raydi.

## Hujjatlar

| № | Hujjat | Mavzu | Kim o'qiydi |
|---|---|---|---|
| 00 | [00-vision-and-principles.md](00-vision-and-principles.md) | Vision, 15 ta buzilmas qoida, texnologiyalar, murosalar | Hamma |
| 01 | [01-architecture-overview.md](01-architecture-overview.md) | Qatlamlar, domenlar, aloqa, asosiy oqimlar, API surface'lar | Hamma |
| 02 | [02-folder-skeleton.md](02-folder-skeleton.md) | To'liq papka tuzilmasi, import-linter | Hamma dasturchi |
| 03 | [03-module-requirements.md](03-module-requirements.md) | Har modul uchun majburiy checklist | Modul egasi |
| 04 | [04-state-machines-and-use.md](04-state-machines-and-use.md) | Holatlar, slim USE, o'tishlar jurnali | Backend |
| 05 | [05-events-and-outbox.md](05-events-and-outbox.md) | Event envelope, katalog, outbox, subscriber, dead-letter | Backend |
| 06 | [06-background-jobs.md](06-background-jobs.md) | arq, scheduler, advisory lock, rejali ishlar ro'yxati | Backend, infra |
| 07 | [07-data-layer.md](07-data-layer.md) | Schemalar, jadvallar, pul, indekslar, migratsiyalar | Backend |
| 08 | [08-cache-and-realtime.md](08-cache-and-realtime.md) | Redis kesh, rate limit, WebSocket inbox | Backend |
| 09 | [09-observability.md](09-observability.md) | structlog, OTel, metrikalar, alertlar, Sentry | Backend, ops |
| 10 | [10-security-tenancy-rbac.md](10-security-tenancy-rbac.md) | Shop izolyatsiyasi, RLS, auth, ruxsatlar, dedicated rejim | Backend |
| 11 | [11-api-conventions-errors-i18n.md](11-api-conventions-errors-i18n.md) | API qoidalari, xato kodlari, exception'lar, tarjimalar | Backend, frontend |
| 12 | [12-concurrency-and-transactions.md](12-concurrency-and-transactions.md) | Tranzaksiyalar, lock'lar, ikki marta sotishdan himoya | Backend |
| 13 | [13-integrations-and-channels.md](13-integrations-and-channels.md) | Telegram, Instagram, sayt chati, webhook'lar | Backend |
| 14 | [14-ai-sales-agent-and-tools.md](14-ai-sales-agent-and-tools.md) | AI sotuvchi, tool kontraktlari, redaction, handoff | Backend, AI |
| 15 | [15-voice-assistant.md](15-voice-assistant.md) | Ovozli hisobot (beta) | AI |
| 16 | [16-ai-data-and-evaluation.md](16-ai-data-and-evaluation.md) | Golden set, bake-off, AI sifatini o'lchash | AI |
| 17 | [17-pc-compatibility-engine.md](17-pc-compatibility-engine.md) | Texnik ma'lumotlar kutubxonasi, moslik qoidalari | Backend |
| 18 | [18-catalog-import.md](18-catalog-import.md) | CSV/XLSX import | Backend |
| 19 | [19-reporting-metrics.md](19-reporting-metrics.md) | Metrika registri, hisobot yordamchisi | Backend |
| 20 | [20-notifications.md](20-notifications.md) | Xabar shablonlari va triggerlar | Backend |
| 21 | [21-frontend.md](21-frontend.md) | Frontend arxitekturasi, sahifa kontraktlari | Frontend |
| 22 | [22-infrastructure-and-deployment.md](22-infrastructure-and-deployment.md) | Muhitlar, Docker, CI/CD, backup | Infra |
| 23 | [23-dev-setup-and-workflow.md](23-dev-setup-and-workflow.md) | Lokal muhit, git, PR, AI yordamchi bilan ishlash | Hamma dasturchi |
| 24 | [24-testing-and-release.md](24-testing-and-release.md) | Test strategiyasi, reliz bosqichlari | Hamma |
| 25 | [25-operations-runbooks.md](25-operations-runbooks.md) | Muhimlik darajalari, kill switch'lar, runbook'lar | Ops |
| 26 | [26-privacy-and-retention.md](26-privacy-and-retention.md) | Shaxsiy ma'lumot, saqlash muddati (qoralama) | Hamma |
| 27 | [27-roadmap-and-tasks.md](27-roadmap-and-tasks.md) | S0–S5 vazifalari | Founder, dasturchi |
| 28 | [28-network-and-global-search.md](28-network-and-global-search.md) | Stage 2–3: shoplar tarmog'i, global qidiruv | Arxitektor |
| 29 | [29-traceability.md](29-traceability.md) | Modul → domen → qoida → holat → sinov | Hamma |
| ADR | [ADR/](ADR/) | Arxitektura qarorlari (har biri alohida fayl) | Backend |
| Modullar | [../modules/](../modules/) | Har domen uchun README | Modul egasi |

Atamalar — [../GLOSSARY.md](../GLOSSARY.md). Qarorlar — [../decisions/DECISION_REGISTER.md](../decisions/DECISION_REGISTER.md). Biznes talablari — [../business/](../business/00_README_AND_SCOPE.md).

## Eski hujjatlardan ko'chirish xaritasi

| Eski (v1) | Yangi (v2) |
|---|---|
| `00_ENGINEERING_README` | `README.md`, `00` |
| `03_DDD_DOMAIN_ARCHITECTURE`, `04_SYSTEM_ARCHITECTURE_C4` | `01` |
| `05_ARCHITECTURE_DECISIONS_ADR` | `ADR/` |
| `06_DATABASE_ERD_AND_SCHEMA`, `34_DOMAIN_ENTITIES_AND_DATA_BOUNDARIES` | `07` |
| `07_DOMAIN_TRANSACTIONS_CONCURRENCY` | `12`, `04` |
| `08_API_CONTRACTS`, `24_API_CONVENTIONS_ERRORS_I18N` | `11` |
| `09_EVENTS_OUTBOX_AND_JOBS`, `35_MODULE_INTERACTIONS_AND_EVENTS` | `05`, `06` |
| `10_SECURITY_AND_RBAC`, `23_TENANT_ISOLATION_AND_DEPLOYMENT_MODES` | `10` |
| `11_ASYNC_RUNTIME_ARCHITECTURE` | `06`, `08` |
| `12_OBSERVABILITY_AND_TRACING` | `09` |
| `13_INTEGRATION_ARCHITECTURE`, `30_CHANNELS_TELEGRAM_INSTAGRAM_WEBCHAT` | `13` |
| `14_GLOBAL_CATALOG_SEARCH_ARCHITECTURE` | `28` |
| `15_AI_AGENTS_ARCHITECTURE`, `26_AI_TOOL_CONTRACTS` | `14` |
| `16_VOICE_AI_ARCHITECTURE` | `15` |
| `17_DATASET_MODEL_TRAINING_EVALUATION` | `16` |
| `18_FRONTEND_ARCHITECTURE_AND_UI` | `21` |
| `19_INFRASTRUCTURE_AND_DEPLOYMENT` | `22` |
| `20_TESTING_AND_RELEASE_PLAN` | `24` |
| `21_FINAL_ARCHITECTURE_REVIEW` | olib tashlandi (natijalari registr va `00` da) |
| `22_DEVELOPMENT_TASKS_AND_REPO_STRUCTURE` | `02`, `27` |
| `25_PC_COMPATIBILITY_ENGINE` | `17` |
| `27_DEVELOPMENT_SETUP_AND_WORKFLOW` | `23` |
| `28_CATALOG_IMPORT_SPEC` | `18` |
| `29_REPORTING_METRICS_REGISTRY` | `19` |
| `31_NOTIFICATIONS_MESSAGE_CATALOG` | `20` |
| `32_DATA_PRIVACY_AND_RETENTION` | `26` |
| `33_OPERATIONS_RUNBOOKS` | `25` |
| `36_TRACEABILITY_INDEX` | `29` |

## Bu hujjatlar qachon yetarli

- [ ] Yangi domen qo'shish 1 sahifada yozilgan (`03`)
- [ ] Buyurtma tasdiqlashda ikki marta sotish qanday oldi olinishi aniq (`12`)
- [ ] A shop B shop ma'lumotini hech qaysi yo'l bilan ko'ra olmasligi isbotlanadigan (`10`, TC-ISO)
- [ ] Fon vazifasi 3 worker'da ham 1 marta ishlashi aniq (`06`)
- [ ] AI qaysi ma'lumotni qayerdan oladi va nimani qila olmaydi — aniq (`14`)
- [ ] Domenlar orasida qachon event, qachon Query Port — aniq (`01`, `05`)
- [ ] Backup va tiklash sinovi tartibi aniq (`22`, `25`)

## Versiya tarixi

| Versiya | Sana | O'zgarish |
|---|---|---|
| v1.0 | 2026-10-21 | Dastlabki engineering paketi (TECH-03…36) |
| v2 | 2026-10-22 | Bismuth v2 standarti: qatlamlar, domenlar, event + Query Port, arq, `shop` |
