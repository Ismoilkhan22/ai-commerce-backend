# DECISION REGISTER — ochiq qarorlar va variantlar

**Sana:** 2026-10-21 · **Egasi:** Founder · **Holat qiymatlari:** `PROPOSED` → `APPROVED (sana)` / `CHANGED` / `DEFERRED` / `REJECTED`

Bu fayl hujjatlarda tarqalgan barcha ochiq savollarning **yagona ro'yxati**. Har bir qaror uchun 2–3 variant berilgan, ⭐ belgisi tavsiya qilingan variantni bildiradi. Founder tasdiqlagach, qaror shu yerda `APPROVED` deb belgilanadi va 4-bo'limda ko'rsatilgan hujjatlarga kiritiladi.

**Muhim (founder, 2026-10-22):** `APPROVED` qarorlar — **ishchi baseline**. Ular bo'yicha hujjatlar va kod ishlab chiqiladi, lekin pilot, intervyu yoki texnik spike natijasiga qarab o'zgartirilishi mumkin. O'zgartirish tartibi: registrda yangi variant va sabab yoziladi (`CHANGED (sana): eski → yangi`), so'ng 4-bo'limdagi ta'sirlangan hujjatlar yangilanadi.

**Hujjatlarga kiritish holati:** ✅ 2026-10-22 — barcha `APPROVED` qarorlar `business/` va `engineering/` hujjatlariga kiritildi. 2026-10-22 kechqurun engineering hujjatlari v2 (bismuth standarti) bo'yicha qayta yozildi va qayta raqamlandi; quyidagi "Qayerda" qatorlaridagi havolalar yangi fayllarga ko'chirilgan, § raqamlari olib tashlangan (eski → yangi xaritasi: `engineering/README.md`). Keyingi ish: S0 skeleti.

---

## 1. Arxitektura qarorlari (DEC-001…016, DEC-126)

### DEC-001 — Deployment va tenant modeli — `APPROVED (2026-10-21, founder): C`
**Nima:** barcha do'konlar bitta tizimdami yoki har biriga alohida o'rnatishmi.
**Qayerda:** `engineering/10-security-tenancy-rbac.md` (to'liq tahlil), `engineering/ADR/README.md` ADR-002.
**Ta'sir:** infra/deploy, Enterprise tarif, Stage 2 publication; kod qoidalari `engineering/10-security-tenancy-rbac.md` §3.

| Variant | Mazmuni | Afzallik | Kamchilik |
|---|---|---|---|
| A | Faqat shared | Eng arzon va oddiy | Katta mijozga alohida o'rnatish javobi yo'q |
| B | Har do'konga dedicated | Eng kuchli izolyatsiya | N ta deploy/backup/monitoring — bitta odamga og'ir |
| C ✅ | Shared-first, dedicated-ready | Hozir oddiy; keyin kod qayta yozilmaydi | Config-driven intizom, global holat taqiqlanadi |

### DEC-002 — PostgreSQL RLS — `APPROVED (2026-10-21, founder): B`
**Nima:** tenant izolyatsiyasini faqat kod tekshiradimi yoki DB ham qo'shimcha himoya qiladimi.
**Qayerda:** `engineering/ADR/README.md` ADR-003, `engineering/07-data-layer.md` §6, C4-O09, `engineering/10-security-tenancy-rbac.md` §6.
**Ta'sir:** `shared/infra/db` (`set_config('app.merchant_id', …, true)` har tranzaksiyada), DB rollari (`app_runtime` NOBYPASSRLS, `app_migrator`), TC-ISO testlari, S0-04 ga RLS spike.

| Variant | Mazmuni | Afzallik | Kamchilik |
|---|---|---|---|
| A | Faqat app-layer | Oddiy, tez | Bitta xato = leak |
| B ✅ | S0: app-layer + composite FK; RLS spike; o'tsa, sezgir jadvallarga (orders, conversations, messages, leads, stock) S0 oxirida | Ikki qavat himoya, pool bilan avval sinab ko'riladi | S0 ga 1–2 kun qo'shiladi |
| C | Darhol barcha jadvallarga | Maksimal | Sinovsiz; S0 sekinlashadi |

### DEC-003 — Job queue / broker — `CHANGED (2026-10-22, founder): A → D` (bismuth v2 standarti)
**Yangi qaror (D):** outbox PostgreSQL'da qoladi (asosiy manba). Outbox worker vazifani **arq** (Redis) navbatiga qo'yadi, task worker'lar bajaradi. Rejali ishlar — **APScheduler + PostgreSQL advisory lock** (bir nechta worker bo'lsa ham bitta ish bir marta). Qoida: vazifa faqat outbox orqali navbatga tushadi — server o'chsa ham yo'qolmaydi; Redis AOF bilan ishlaydi. Batafsil: `engineering/ADR/ADR-033`, `engineering/06-background-jobs.md`.
**Nega o'zgardi:** retry, kechiktirish, timeout tayyor kutubxonada bor — o'zimiz yozmaymiz; bismuth_platform_v2 bilan bir xil; Redis baribir bor (kesh, rate limit). Narxi: Redis majburiy servis bo'ladi.

**Eski matn (tarix uchun):**
**Nima:** HTTP so'rovdan tashqaridagi ishlar (Telegram javobi, AI javobi, eslatmalar, import, notification) qanday saqlanadi va qayta uriniladi.
**Qayerda:** `engineering/ADR/README.md` ADR-005, `engineering/01-architecture-overview.md` §2 (4-izoh, "TBD" edi), `engineering/05-events-and-outbox.md`, `engineering/06-background-jobs.md`, `engineering/05-events-and-outbox.md`.
**Ta'sir:** `shared/infra/outbox`, `shared/infra/jobs`, `workers/`; infra'da RabbitMQ yo'q.

| Variant | Mazmuni | Afzallik | Kamchilik |
|---|---|---|---|
| A ✅ | PostgreSQL outbox + PG leased jobs (`FOR UPDATE SKIP LOCKED`) | Qo'shimcha server yo'q; vazifa biznes ma'lumoti bilan atomik; backup bitta joyda | Lease/retry/DLQ'ni o'zimiz yozamiz (yoki tayyor PG-queue kutubxonasi baholanadi); katta yuklamada DB'ga og'irlik |
| B | Celery + RabbitMQ | Yetuk ekotizim, monitoring UI | Qo'shimcha server; Celery async FastAPI'ga yomon mos |
| C | Redis queue (arq / Taskiq) | Yengil, async | Redis ma'lumot yo'qotishi mumkin (ADR-006 ga zid) |
| D ✅ (2026-10-22) | PG outbox + arq (Redis) + APScheduler/advisory lock; navbatga faqat outbox orqali | Tayyor kutubxona; bismuth bilan bir xil; outbox tufayli yo'qolmaydi | Redis majburiy; ADR-006 o'zgaradi (Redis endi navbatni ham ushlaydi, lekin manba — outbox) |

**Qayta ko'rish sharti:** queue lag SLO buzilsa yoki throughput yetmasa, B ga o'tiladi; event schema va outbox o'zgarmaydi.

### DEC-004 — Backend repo skeleti — `CHANGED (2026-10-22, founder): A → C` (bismuth v2 standarti)
**Yangi qaror (C):** `app/shared` → `app/platform` → `app/domains` uch qatlami (bismuth v2). `shared` hech kimni import qilmaydi; `platform` `domains` ni import qilmaydi; domenlar bir-birini import qilmaydi (CI'da import-linter). Har domen: `api/`, `services/`, `repository/`, `models/`, `state_machine.py`, `events.py`, `permissions.py`, `subscribers.py`, `tests/`; har domenga o'z PostgreSQL schemasi. Batafsil: `engineering/02-folder-skeleton.md`, `engineering/ADR/ADR-031`, `ADR-035`.
- `platform/`: `auth`, `shops` (shop, filiallar), `staff` (xodimlar, rollar, ruxsatlar), `use` (holat o'tishlari jurnali + idempotency), `audit`, `notifications`, `storage`, `realtime` (WebSocket), `llm` (provayder adapteri, redaction), `billing` (tarif, AI limitlari), `privacy` (eksport/o'chirish so'rovlari).
- `domains/` (Stage 1): `catalog`, `commerce`, `messaging`, `sales_ai`, `storefront`, `support`, `reporting`. Keyin: `payments`, `fulfillment` (DEFERRED), `network` (Stage 2), `marketplace` (Stage 3).
**Nega o'zgardi:** ikki loyihada bitta uslub; qoidalar CI'da avtomatik tekshiriladi.

**Eski matn (tarix uchun):**
**Nima:** backend kodi qaysi papkalarda turadi, import qoidalari qanday.
**Qayerda:** `engineering/01-architecture-overview.md` §6 (A), `engineering/01-architecture-overview.md` §2.2 (A), `engineering/27-roadmap-and-tasks.md` §1 (B) — 22 A ga moslab tuzatiladi.
**Ta'sir:** barcha backend kodi, CI import-linter qoidalari, AI-assisted PR shabloni.

| Variant | Mazmuni | Afzallik | Kamchilik |
|---|---|---|---|
| A ✅ | `src/commerce_os/` + `modules/<context>/{domain,application,infrastructure,presentation}` + `workflows/` + `workers/` + `api/v1/` + `bootstrap/` | Python src-layout standarti; kontekstlararo use case'lar uchun `workflows/`; ikki hujjat mos | Papkalar chuqurroq; `transport/` va `presentation/` chegarasi aniq yozilishi kerak |
| B | `app/contexts/...` + `entrypoints/{api,worker,scheduler}` | Entry point'lar aniq | Kontekstlararo jarayon uchun joy yo'q; src-layout emas |
| C ✅ (2026-10-22) | Bismuth v2: `app/{shared,platform,domains}` + `workers/` | Sinalgan uslub, CI tekshiruvi, schema per domain | DEC-004 A dagi hujjatlar qayta yoziladi |

Kontekst nomlari: `identity`, `merchants`, `catalog`, `pricing`, `inventory`, `storefronts`, `pc_builder`, `messaging`, `merchant_ai`, `sales`, `orders`, `payments` (Stage 1 da yo'q, DEC-100), `fulfillment`, `engagement`, `reporting`, `platform`. S0 da faqat `identity`, `merchants`, `platform` yaratiladi.

### DEC-005 — Reliz slice nomlari — `APPROVED (2026-10-21, founder): A`
**Nima:** ish qaysi bo'laklarda va qaysi tartibda chiqariladi.
**Qayerda:** `business/10` (R1–R7), `engineering/24-testing-and-release.md` §4 va `engineering/27-roadmap-and-tasks.md` (S0–S5), `engineering/01-architecture-overview.md` §14, `engineering/01-architecture-overview.md` §13.
**Ta'sir:** roadmap, vazifalar, test gate'lari, PR shabloni. `business/10` dagi R jadvali S ga moslab qayta yoziladi.

| Variant | Mazmuni | Afzallik | Kamchilik |
|---|---|---|---|
| A ✅ | S0–S5 asosiy; Stage 2/3 — `N1`/`G1` | TECH-22 vazifalari tayyor; poydevor (S0) alohida | business/10 jadvali qayta yoziladi |
| B | R1–R7 asosiy | Biznes tili | TECH-20/22 qayta yoziladi; poydevor alohida emas |

DEC-100 bilan S slice'lar: S0 poydevor (auth, tenant, DB, outbox, audit, tracing) · S1 katalog, narx, stok, storefront · S2 kanallar + inbox + handoff · S3 AI + PC compatibility + quote · S4 buyurtma, rezerv, operator/sotuvchi tasdig'i, yetkazish (to'lovsiz) · S5 hisobot, kafolat, billing limitlari, pilot.
R → S: R1→S0, R2→S1, R3→S2+S3, R4→S3+S4, R5→S4+S5 (to'lov qismi chiqarildi), R6→S5, R7→S5 (voice, DEC-112).

### DEC-006 — API yo'l tuzilmasi — `APPROVED (2026-10-21, founder): A`
**Nima:** API manzillari qanday guruhlanadi.
**Qayerda:** `engineering/01-architecture-overview.md` §6.1 (A), `engineering/11-api-conventions-errors-i18n.md` (B) — 08 A ga moslanadi.
**Ta'sir:** `api/v1/` router tuzilmasi, har surface uchun alohida auth middleware va rate limit, frontend API client.

| Variant | Mazmuni | Afzallik | Kamchilik |
|---|---|---|---|
| A ✅ | `/api/v1/merchant/*` (staff), `/api/v1/storefront/{slug}/*` (public do'kon), `/api/v1/webhooks/*` (imzo), `/api/v1/platform/*` (support), `/api/v1/public/*` (Stage 3) | Har guruhga o'z himoyasi; private endpoint public guruhga tasodifan tushmaydi | Manzillar uzunroq |
| B | Tekis `/api/v1/orders` | Qisqa | Auth turi har endpoint'da alohida; aralash |

### DEC-007 — Pul birligi (UZS minor units) — `APPROVED (2026-10-21, founder): A`
**Nima:** pul bazada qaysi birlikda butun son sifatida saqlanadi.
**Qayerda:** `engineering/07-data-layer.md` §4, `engineering/16-ai-data-and-evaluation.md` §6, barcha API/JSON misollar.
**Ta'sir:** `shared/kernel/money`, `currencies` jadvali (exponent), barcha `*_minor` ustunlar, UI formatlash.

| Variant | Mazmuni | Afzallik | Kamchilik |
|---|---|---|---|
| A ✅ | ISO 4217: UZS exponent 2 (10 mln so'm = `1000000000`); `currencies` jadvalida exponent | Standart; USD bilan bir xil; kurs hisobida aniqlik; misollarga mos | Raqamlar 100x katta; UI butun so'mga yaxlitlaydi |
| B | Butun so'm | Qisqa | USD/kurs uchun alohida mantiq; misollar noto'g'ri bo'lib qoladi |

### DEC-008 — Dashboard autentifikatsiya tokenlari — `APPROVED (2026-10-21, founder): A`
**Nima:** xodim login qilgandan keyin brauzer uni qanday eslab qoladi va API'ga qanday murojaat qiladi.
**Qayerda:** `engineering/10-security-tenancy-rbac.md` "Authentication and tokens" (ochiq qoldirilgan edi), `engineering/21-frontend.md` §7 ("CSRF/session strategy ADR"), C4-O08.
**Ta'sir:** `modules/identity` (sessions, refresh token rotation), `api/v1/middlewares/auth`, frontend `packages/auth`, WS ticket; domenlar: `app.<domen>` va `api.<domen>` bitta site ostida.

| Variant | Mazmuni | Afzallik | Kamchilik |
|---|---|---|---|
| A ✅ | Access JWT (10–15 daq) xotirada + rotating refresh token `httpOnly Secure SameSite=Strict` cookie'da; WS uchun qisqa ticket | Uzoq tokenni XSS o'g'irlay olmaydi; OpenAPI client va WS bilan oddiy; API stateless | Sahifa yangilanganda silent refresh kerak; dashboard va API bitta site ostida bo'lishi shart |
| B | Cookie-session + CSRF, Next.js BFF orqali | Token JS'ga umuman ko'rinmaydi | Har yozish so'roviga CSRF; Next server auth yo'liga qo'shiladi |
| C | localStorage bearer | Oson | XSS orqali o'g'irlanadi — rad etildi |

### DEC-009 — LLM provayder strategiyasi — `APPROVED (2026-10-21, founder): A`
**Nima:** AI sotuvchi qaysi LLM orqali ishlaydi va u qanday tanlanadi.
**Qayerda:** `engineering/ADR/README.md` ADR-011, `engineering/14-ai-sales-agent-and-tools.md` §7, `engineering/16-ai-data-and-evaluation.md` §4.
**Ta'sir:** `modules/merchant_ai` provider adapter (`LLMPort`), S3 dan oldin bake-off vazifasi, suhbat narxi, DEC-016 shartlari.

| Variant | Mazmuni | Afzallik | Kamchilik |
|---|---|---|---|
| A ✅ | Provayderdan mustaqil adapter + 1 haftalik bake-off (uz/ru/en 200 dialog: tool-calling aniqligi, narx, latency). Default nomzod Claude Sonnet (eng so'nggi) | Dalilga asoslangan; almashtirish oson | Test to'plami va 1 hafta kerak |
| B | Darhol multi-provider routing | Zaxira | Murakkab, har birini testlash |
| C | Self-hosted open model | Ma'lumot chiqmaydi | GPU qimmat, o'zbekcha sifat past |

### DEC-010 — STT / TTS (ovoz) — `APPROVED (2026-10-21, founder): A — DEC-112 B ga bog'liq`
**Nima:** ovozni matnga va matnni ovozga aylantirish provayderi.
**Qayerda:** `engineering/15-voice-assistant.md` §7, `engineering/16-ai-data-and-evaluation.md` §4, `engineering/ADR/README.md` A-05.
**Ta'sir:** voice beta'dan oldin bake-off; `SpeechToTextPort`/`TextToSpeechPort` adapterlari; har doim text fallback.

| Variant | Mazmuni | Afzallik | Kamchilik |
|---|---|---|---|
| A ✅ | 2–3 hosted provayder o'zbekcha golden set (300 yozuv + 100 raqam/sana) bilan solishtiriladi | Dalilga asoslangan, tez | Golden set yig'ish kerak (rozilik bilan) |
| B | Self-hosted Whisper + fine-tune | Nazorat to'liq | GPU, ML ish hajmi katta |
| C | Ovozni keyinga qoldirish | Ish kam | DEC-112 bilan hal qilindi |

### DEC-011 — PC komponent spetsifikatsiyalari manbai — `APPROVED (2026-10-21, founder): B`
**Nima:** compatibility engine uchun socket, RAM turi, GPU uzunligi, PSU quvvati/konnektorlari kabi ma'lumotlar qayerdan keladi. Merchant Excel'ida bular odatda yo'q.
**Qayerda:** `business/02` M08, `engineering/07-data-layer.md` (faqat `pc_rulesets` nomi), `engineering/28-network-and-global-search.md` (global katalog — Stage 2). Manba ilgari yozilmagan edi.
**Ta'sir:** `modules/pc_builder` (reference spec library + SKU mapping), katalog importi (MPN/model bo'yicha avtomatik bog'lash), yangi hujjat `PC_COMPATIBILITY_ENGINE`.

| Variant | Mazmuni | Afzallik | Kamchilik |
|---|---|---|---|
| A | Merchant har SKU uchun spec kiritadi | Bizga ish yo'q | Merchant kiritmaydi yoki xato kiritadi → PC builder ishlamaydi |
| B ✅ | Platforma yuritadigan reference hardware spec library (CPU, MB, GPU, PSU, case, cooler, RAM — eng ko'p sotiladigan bir necha yuz model, manba va versiya bilan); merchant SKU unga bog'lanadi; bog'lanmasa `REVIEW_REQUIRED` | Merchantga ish deyarli yo'q; ishonchli; Stage 2 canonical katalogiga tabiiy o'tish | Kutubxonani yuritish kerak (DEC-120) |
| C | To'liq global katalog Stage 1 da | To'liq | Stage 1 juda kattalashadi |

### DEC-012 — Observability stack — `APPROVED (2026-10-22, founder): B` — 2026-10-22 bismuth v2 bilan solishtirilib qayta tasdiqlandi: kod qoidalari (structlog, metrika nomlari) bismuth'dan olinadi, ma'lumot Grafana Cloud + Sentry'ga
**Nima:** xatolar, sekinlashish, queue holati va AI xarajati qayerda ko'rinadi va ogohlantirish qayerdan keladi.
**Qayerda:** `engineering/ADR/README.md` ADR-017 (OpenTelemetry), `engineering/09-observability.md` (span, metrika, alert), `engineering/01-architecture-overview.md` §10 — vosita tanlanmagan edi.
**Ta'sir:** S0 — OpenTelemetry SDK + JSON loglar (`trace_id`, `request_id`), eksport Grafana Cloud'ga (trace, metrika, log), xatolar Sentry'ga; `engineering/09-observability.md` redaction qoidalari majburiy (PII telemetriyaga yozilmaydi); `infra/` da self-hosted monitoring yo'q.

| Variant | Mazmuni | Afzallik | Kamchilik |
|---|---|---|---|
| A | Self-hosted: OTel Collector + Prometheus + Grafana + Tempo + Loki + Sentry | To'liq nazorat | 5 ta servisni yuritish |
| B ✅ | Managed: Grafana Cloud + Sentry; faqat redact qilingan telemetriya | Tez, boshqarish kerak emas, kichik hajmda arzon; hammasi bitta joyda | Telemetriya xorijda (PII'siz); hajm oshsa narx oshadi |
| C | Faqat Sentry + loglar | Oddiy | Async zanjir, metrika, alert yo'q |

**Qayta ko'rish sharti:** narx yoki data residency talabi o'zgarsa A ga o'tiladi — OpenTelemetry tufayli kod o'zgarmaydi.

### DEC-013 — Hosting va data residency — `APPROVED (2026-10-21, founder): A — huquqshunos tasdig'i sharti bilan`
**Nima:** xaridor shaxsiy ma'lumotlari qaysi davlatdagi serverda saqlanadi.
**Qayerda:** `engineering/22-infrastructure-and-deployment.md`, `engineering/01-architecture-overview.md` C4-O01, `engineering/10-security-tenancy-rbac.md` Privacy, `engineering/ADR/README.md` A-04.
**Ta'sir:** production hosting provayderi, backup joyi, `infra/`. Dev/staging — sintetik ma'lumot bilan istalgan joyda.

| Variant | Mazmuni | Afzallik | Kamchilik |
|---|---|---|---|
| A ✅ | PII DB va storage O'zbekistonda (Docker Compose, VM); LLM'ga faqat tozalangan matn (DEC-016) | Lokalizatsiyaga eng mos; lokal kechikish past | Managed servis kam; backup'ni o'zimiz sozlaymiz |
| B | Xorijiy cloud | Arzon, qulay | Lokalizatsiya talabini buzishi mumkin |
| C | Gibrid | Ma'lumot lokal | Ikki joy, kechikish |

**Shart:** huquqshunos xulosasigacha production'ga real merchant PII yuklanmaydi.

### DEC-014 — Frontend tuzilmasi — `APPROVED (2026-10-21, founder): A`
**Nima:** xodimlar dashboard'i va xaridor ko'radigan do'kon sayti bitta ilovami yoki ikkita.
**Qayerda:** `engineering/ADR/README.md` ADR-010, `engineering/21-frontend.md` §1, `engineering/01-architecture-overview.md` §2 (6-izoh), C4-O08.
**Ta'sir:** `ai-commerce-frontend` repo tuzilmasi (pnpm workspace), deploy (ikki alohida app), cookie domenlari.

| Variant | Mazmuni | Afzallik | Kamchilik |
|---|---|---|---|
| A ✅ | Bitta repo: `apps/merchant-dashboard`, `apps/merchant-storefront` + `packages/{ui,api-client,i18n,auth}` | Alohida deploy; public/private chegarasi aniq; storefront SEO va keshi mustaqil | Monorepo sozlash, ikkita build |
| B | Bitta Next.js app | Boshlash oson | Public va private kod bitta deploy'da; subdomen routing murakkab; cookie aralashish xavfi |

### DEC-015 — Rollar va ruxsatlar matritsasining manbai — `APPROVED (2026-10-21, founder): A`
**Nima:** kim nima qila oladi; `business/04` va `engineering/10-security-tenancy-rbac.md` zid edi (Sales quote tasdiqlashi, Sales yetkazish statusi, 4 ta yetishmayotgan rol).
**Qayerda:** `business/04` (canonical), `engineering/10-security-tenancy-rbac.md` (moslanadi).
**Ta'sir:** `modules/identity` permission katalogi, endpoint guard'lari, AI tool ruxsatlari, UI menyular.

| Variant | Mazmuni | Afzallik | Kamchilik |
|---|---|---|---|
| A ✅ | `business/04` canonical; TECH-10 ga `resource.action` permission kodlari katalogi va yetishmayotgan rollar (Catalog Editor, Support, AI Policy Editor, Service Account) qo'shiladi | To'liq, BL-045 bilan mos | R/W/P/A ni kodlarga tarjima qilish kerak |
| B | TECH-10 canonical | Kodlar tayyor | Rollar yetishmaydi, biznes qoidasiga zid kataklar |

Aniq kataklar `DEC-108` (buyurtmani kim tasdiqlaydi) va `DEC-109` da hal qilinadi.

### DEC-016 — LLM provayderga yuboriladigan ma'lumot siyosati — `APPROVED (2026-10-21, founder): A`
**Nima:** AI javobi uchun tashqi provayderga qanday ma'lumot ketadi.
**Qayerda:** `engineering/10-security-tenancy-rbac.md` Privacy, `engineering/14-ai-sales-agent-and-tools.md` §7, `engineering/10-security-tenancy-rbac.md` 8-qatlam, `engineering/07-data-layer.md`.
**Ta'sir:** AI worker'da PII redaction qadami; provayder tanlovi (DEC-009) faqat zero-retention / no-training shartini beradiganlar bilan.

| Variant | Mazmuni | Afzallik | Kamchilik |
|---|---|---|---|
| A ✅ | PII redaction (telefon, manzil, ism, karta) + zero-retention / no-training sharti | Huquqiy xavf kam; sifat deyarli pasaymaydi (narx/stok tool'dan) | Redaction yozish va testlash kerak |
| B | To'liq kontekst | Oddiy | Huquqiy xavf, provayder saqlashi mumkin |
| C | Faqat on-prem | Ma'lumot chiqmaydi | Qimmat, o'zbekcha sifat past |

---

### DEC-126 — Domenlar o'zaro aloqasi — `APPROVED (2026-10-22, founder): A`
**Nima:** domenlar bir-biri bilan qanday gaplashadi va buyurtma tasdiqlanganda mahsulot qanday atomik band qilinadi (TC-002, TC-027).
**Qayerda:** `engineering/01-architecture-overview.md`, `engineering/05-events-and-outbox.md`, `engineering/ADR/ADR-032`. ADR-021 (`workflows/`) bekor qilinadi.

| Variant | Mazmuni | Afzallik | Kamchilik |
|---|---|---|---|
| A ✅ | Ombor, band qilish, buyurtma, tez sotuv, lead va PC taklif — bitta `commerce` domeni; tasdiqlash + band qilish domen ichida, bitta tranzaksiyada. Domenlar orasida yozish faqat event orqali, o'qish — faqat Query Port | Bismuth qoidalari to'liq; ikki marta sotish xavfi yo'q | `commerce` kattaroq; AI qoralamasi event orqali biroz kechikib paydo bo'ladi |
| B | Ombor va buyurtma alohida, `workflows/` istisnosi bilan | Domenlar kichik | Bismuth 4-qoidasiga istisno, istisnolar ko'payishi mumkin |
| C | Faqat event (saga) | To'liq mustaqillik | "Tasdiqlandi" dan keyin "mahsulot yo'q" — TC-002/027 buziladi |

### DEC-127 — Buyurtma tasdiqlashda narx qayerdan tekshiriladi — `APPROVED (2026-10-22, founder): A`
**Nima:** operator buyurtmani tasdiqlaganda tizim narx o'zgarmaganini tekshiradi (TC-031). Narx `catalog` da, buyurtma `commerce` da.
**Qayerda:** `engineering/12-concurrency-and-transactions.md`, `engineering/ADR/ADR-032-commerce-domain-and-event-communication.md`.

| Variant | Mazmuni | Afzallik | Kamchilik |
|---|---|---|---|
| A ✅ | Tasdiqlashda `CatalogQueryPort.get_active_price()` sinxron o'qiladi va buyurtma qatoridagi narx bilan solishtiriladi | Har doim eng yangi narx, qo'shimcha jadval yo'q | `commerce` tasdiqlashda catalog interfeysiga bog'liq |
| B | `commerce` ichida narx nusxasi (event orqali yangilanadi) | Domenlar to'liq mustaqil | Qo'shimcha jadval; ~2 s kechikish oynasi |

## 2. Konvensiyalar — K-01…K-10 — `APPROVED (2026-10-21, founder): hammasi ⭐ bo'yicha`

Hujjatlarda bitta narsa turli nom bilan yozilgan; quyidagi standartlar barcha hujjat va kodda majburiy. Ta'sir: DB ustunlari, enum'lar, API, event'lar, AI tool'lar — hujjatlarni birlashtirish bosqichida (5-bo'lim, 2-band) kiritiladi.

| ID | Konvensiya ⭐ | Hozirgi ziddiyat |
|---|---|---|
| K-01 | Tenant identifikatori hamma joyda `shop_id` — `CHANGED (2026-10-22): merchant_id → shop_id` (DEC-124) | DDD/event: `tenant_id`; TECH-06/09: `merchant_id` |
| K-02 | Enum qiymatlari API va DB'da `UPPER_SNAKE` (`PENDING_CONFIRMATION`) | FSM lowercase, DDL/API uppercase |
| K-03 | Status nomlari manbai — `business/05` FSM'lar. Order, Payment, Shipment statuslari alohida: API `order.status` faqat FSM-08 qiymatini qaytaradi, to'lov holati `payment.status` da | TECH-08 `AWAITING_PAYMENT`, DDD `pending_payment` |
| K-04 | Stock maydonlari: `on_hand`, `reserved`, `allocated`; `available = on_hand − reserved − allocated` | DDL `physical_qty` |
| K-05 | Reservation FSM: `ACTIVE → ALLOCATED → CONSUMED`, `ACTIVE → RELEASED`, `ACTIVE → EXPIRED` (FSM-07 va DDL birlashtiriladi) | FSM-07 `EXPIRED` yo'q, DDL `ALLOCATED` yo'q |
| K-06 | Header: `Idempotency-Key` (IETF draft), `X-Request-ID`, `traceparent` | `X-Idempotency-Key` va `Idempotency-Key` aralash |
| K-07 | Error envelope: `{"error":{"code","message","details","trace_id"}}`; yagona error kod katalogi (TECH-08 asos + `INTERNAL_ERROR` 500, `VALIDATION_FAILED` 422/400, `PRICE_CHANGED`, `FEATURE_NOT_AVAILABLE`) | DDD `OUT_OF_STOCK`, TECH-08 `INSUFFICIENT_AVAILABLE_STOCK` |
| K-08 | Event envelope (TECH-09 asos + DDD qo'shimchalari): `event_id, event_type, schema_version, shop_id, aggregate_type, aggregate_id, aggregate_version, occurred_at, actor, traceparent, correlation_id, causation_id, payload`. `event_type` nomi — `<domain>.<entity>.<action>` o'tgan zamonda (`commerce.order.confirmed`), bismuth v2 (2026-10-22) | 3 xil variant |
| K-09 | PC compatibility natijasi: `PASS` / `REVIEW_REQUIRED` / `BLOCK` (hamma joyda) | M08/UAT: `compatible / incompatible` |
| K-10 | AI tool nomlari `domain.verb` formatida (TECH-15 asos; 2026-10-22 dan domen nomlari DEC-004 C bo'yicha): `catalog.search`, `catalog.get_price_stock`, `commerce.request_quote_approval`, `commerce.lookup_order_status`, `commerce.create_order_draft` (DEC-100c; event orqali, DEC-126) | business/08 va TECH-15 nomlari farqli |

---

## 3. Biznes qarorlari (DEC-100…122)

### DEC-100 — Stage 1 savdo oqimi: buyurtma bor, to'lov tizimdan tashqarida — `APPROVED (2026-10-21, founder)`

**Qaror:** Stage 1 da xaridor buyurtma beradi, to'lovni har bir do'kon o'zi oladi (naqd, karta, o'tkazma — tizimdan tashqarida). Sotuv gaplashib yakunlanadi.

```
Xaridor (Telegram / web) → AI maslahat, mos mahsulot / PC yig'ma
  → xaridor buyurtma beradi (AI faqat buyurtma so'rovini yaratadi, tasdiqlamaydi)
  → xaridor "aniq olaman" desa → operator ulanadi (human handoff)
  → operator gaplashadi, shartlarni kelishadi
  → sotuvchi mahsulot borligini tasdiqlaydi → order CONFIRMED, stok rezerv qilinadi
  → yetkazib berish yoki olib ketish
  → to'lovni do'kon o'zi oladi (tizimdan tashqarida)
  → topshirildi → order COMPLETED, stok kamayadi
```

**Oqibatlari:**
- M14 (to'lov va chek tekshirish) Stage 1 dan chiqadi → `DEFERRED` (Stage 2 yoki keyinroq). DEC-106, DEC-108, DEC-111 yopiladi.
- AI buyurtmani hech qachon tasdiqlamaydi: sotuvni operator va sotuvchi yakunlaydi (BL-041, BL-047 bilan mos).
- Buyurtma statuslari (FSM-08): `DRAFT` (so'rov) → `PENDING_CONFIRMATION` (operator ulangan) → `CONFIRMED` (sotuvchi tasdiqladi, rezerv) → `PROCESSING` (yig'ish / yetkazish) → `COMPLETED` (topshirildi) / `CANCELLED`.
- Hisobot va Voice: "to'langan tushum" (`sales_paid_gross_minor`) Stage 1 da yo'q. O'rniga `orders_completed_count` va `orders_completed_amount_minor` (merchant topshirgan buyurtmalar) ishlatiladi.
- Release gate'lardan TC-004/005/006 (chek, callback, kech to'lov) Stage 1 dan chiqariladi.

**Oqim bo'yicha kichik qarorlar (DEC-100a…h):**

| ID | Savol | Variantlar | Holat |
|---|---|---|---|
| DEC-100a | Merchant buyurtmani "to'landi" deb belgilay oladimi? | A: yo'q, faqat COMPLETED · B: ixtiyoriy belgi "to'landi (merchant belgiladi, tekshirilmagan)" — kim, qachon, usul (naqd/karta/o'tkazma), audit bilan | `APPROVED (2026-10-21): B`. Afzallik: qarzdorlik va to'lov usuli statistikasi; kamchilik: xodim xato belgilashi mumkin — hisobotda "tekshirilmagan" yorlig'i |
| DEC-100b | Stok qachon rezerv qilinadi? | A: xaridor buyurtma berganda · B: sotuvchi tasdiqlaganda | `APPROVED (2026-10-21): B` — DEC-105 bilan birga |
| DEC-100c | AI buyurtma qoralamasini yarata oladimi? | A: AI `DRAFT` buyurtma (mahsulot, miqdor, kontakt, manzil) yaratadi + operatorni chaqiradi; qoralama stok band qilmaydi va hech narsani tasdiqlamaydi · B: faqat operatorni chaqiradi | `APPROVED (2026-10-21): A` — tool `orders.create_draft` (K-10). Afzallik: operator vaqti tejaladi; kamchilik: AI xatosini operator tekshiradi |
| DEC-100d | Saytdan kelgan buyurtma ham operator tasdig'idan o'tadimi? | A: ha, har buyurtma · B: stok bo'lsa avtomatik | `APPROVED (2026-10-21): A` — Stage 2 da merchant avto-tasdiqni ixtiyoriy yoqishi mumkin. Afzallik: narx/yetkazish/manzil aniq, feyk buyurtma kam; kamchilik: operatorga yuk |
| DEC-100e | Online sotuvda oddiy mahsulot (PC emas) uchun quote kerakmi? | A: yo'q — online oddiy xarid to'g'ridan-to'g'ri buyurtma qoralamasiga (narx buyurtma qatorida muzlatiladi); quote faqat PC yig'ma va maxsus narx uchun · B: har doim quote | `APPROVED (2026-10-21): A`. Offline (do'kondagi) sotuv bu savolga kirmaydi — DEC-123 |
| DEC-100f | Operator va sotuvchi bitta odammi? | A: tizimda alohida ruxsatlar (Sales, Warehouse/Manager), bitta odamga bir nechta rol berilishi mumkin; onboarding'da "kichik do'kon" shabloni — egasiga barcha rollar · B: bitta "sotuvchi" roli | `CHANGED (2026-10-23): A → DEC-131` — alohida rollar qoladi, lekin har xodimga bitta rol; shablon kerak emas (ega hammasini qiladi) |
| DEC-100g | Operator xaridor bilan qanday bog'lanadi? | A: chat yoki telefon; telefon natijasi buyurtmaga izoh sifatida kiritiladi · B: faqat chat | `APPROVED (2026-10-21): A`. Ta'sir: buyurtma kartochkasida "qo'ng'iroq natijasi / kelishuv" izohi (audit bilan) |
| DEC-100h | Yetkazish narxi qanday qo'shiladi? | A: alohida "yetkazish" qatori (operator yoki tarifdan) · B: tizimda yuritilmaydi | `DEFERRED (2026-10-21, founder)`: Stage 1 da tizim yetkazish narxini hisoblamaydi — operator xaridor bilan sotish paytida kelishadi. Oqibat: hisobotdagi buyurtma summasi yetkazishsiz. Qayta ko'rish: pilot intervyulari va M15 dizaynida |

### DEC-123 — Do'kondagi offline sotuv stokka qanday tushadi — `APPROVED (2026-10-21, founder): A`
**Nima:** do'konga kelgan xaridor peshtaxtadan olgan mahsulot tizimdagi stokdan kamayishi kerak, aks holda AI online xaridorga noto'g'ri "bor" deydi. Ilgari hujjatlarda yozilmagan bo'shliq.
**Qayerda bog'liq:** `business/02` M06, BL-019/022, DEC-107 (dashboard — stok master), M22 (POS — Stage 2).
**Ta'sir:** `modules/inventory` — "tez sotuv" amali (ledger reason `OFFLINE_SALE`, actor, audit), dashboard va mobil ekran tugmasi, hisobotda offline sotuvlar alohida.

| Variant | Mazmuni | Afzallik | Kamchilik |
|---|---|---|---|
| A ✅ | "Tez sotuv" tugmasi: mahsulot + miqdor → stok darhol kamayadi; mijoz ma'lumoti kerak emas | Stok real vaqtda to'g'ri; offline sotuv hisobotda | Xodim har sotuvda bosishi kerak |
| B | Kun oxirida qo'lda stok tuzatish | Hech narsa qurilmaydi | Kun davomida stok noto'g'ri |
| C | POS integratsiyasi | Avtomatik | Stage 2 ishi |

### DEC-101 — Pilotdagi "hero feature" (O-01, HYP-001/002) — `APPROVED (2026-10-21, founder): A` (intervyulardan keyin yakuniy tasdiq)
**Nima:** do'konga birinchi navbatda nima sotiladi va demoda nima ko'rsatiladi.
**Qayerda:** `discovery/A01` §11, `business/11` O-01.
**Ta'sir:** S0–S4 tartibi, demo ssenariysi (A01 §9). Agar intervyuda do'konlar ishonchli narx/stok bera olmasa — C ga o'tish (A01 qaror daraxti).

| Variant | Mazmuni | Afzallik | Kamchilik |
|---|---|---|---|
| A ✅ | AI chat + PC taklif + buyurtma | To'liq qiymat, raqobatchilardan farq | Eng ko'p ish (S0–S4) |
| B | Avval operator uchun PC taklif quruvchi | Tez, AI xavfi yo'q | "AI sotuvchi" ko'rinmaydi |
| C | Avval AI lead + operatorga uzatish | Eng tez qiymat | PC farqi keyin |

### DEC-102 — Quote tasdiqlash siyosati (FSM-06 ↔ AP-01 ziddiyati) — `APPROVED (2026-10-21, founder): A`
**Nima:** PC taklifi xaridorga yuborilishidan oldin menejer tekshiradimi (quote faqat online PC yig'ma uchun — DEC-100e).
**Qayerda:** `business/05` FSM-06 (har doim review), `business/04` AP-01 (faqat threshold/REVIEW/chegirma) — zid edi.
**Ta'sir:** merchant policy `quote_approval_mode` (`ALWAYS` default / `RISK_ONLY`); FSM-06 ga `DRAFT → APPROVED` (policy `RISK_ONLY` va xavf yo'q bo'lsa) yo'li qo'shiladi.

| Variant | Mazmuni | Afzallik | Kamchilik |
|---|---|---|---|
| A ✅ | Pilotda default — har quote menejerdan; keyin owner `RISK_ONLY` rejimiga o'tkaza oladi | Pilotda AI xatosi mijozga yetmaydi; keyin tezlashtirish mumkin | Boshida menejer yuklanadi |
| B | Har doim menejer | Maksimal nazorat | Doim sekin |
| C | Faqat xavfli holatlarda | Tez | Pilotda AI xatosi mijozga yetishi mumkin |

### DEC-103 — Quote amal qilish muddati (O-03) — `APPROVED (2026-10-21, founder): B`
**Nima:** PC taklifidagi narx qancha vaqt kafolatlanadi.
**Qayerda:** `business/03` BL-016/044, `business/05` timer jadvali.
**Ta'sir:** merchant policy `quote_ttl_hours` (default 24), quote expiry job, xaridorga "amal qiladi: …" matni; qabul qilishda narx va stok qayta tekshiriladi.

| Variant | Mazmuni | Afzallik | Kamchilik |
|---|---|---|---|
| A | 2 soat | Narx xavfi kam | Xaridor o'ylab ulgurmaydi |
| B ✅ | Merchant sozlaydi, default 24 soat | O'ylash uchun vaqt; do'kon o'zgartira oladi | Kurs keskin o'zgarsa, qayta taklif |
| C | 72 soat | Qulay | Narx eskiradi |

### DEC-104 — Rezerv va buyurtma muddatlari (O-02) — `APPROVED (2026-10-21, founder): B`
**Nima:** to'lov kutilmagani uchun (DEC-100) tasdiqlanmagan so'rov va tasdiqlangan, lekin olib ketilmagan buyurtma bilan nima qilinadi.
**Qayerda:** `business/03` BL-021, `business/05` timer jadvali, `business/11` O-02.
**Ta'sir:** merchant policy `order_confirm_reminder_hours` (default 24), `reservation_review_hours` (default 72); scheduler job → menejer vazifasi (M17); FSM-07 da `EXPIRED` faqat menejer qarori bilan.

| Variant | Mazmuni | Afzallik | Kamchilik |
|---|---|---|---|
| A | Muddat yo'q | Oddiy | Unutilgan buyurtmalar stokni band qiladi |
| B ✅ | Eslatma 24 soat, "bekor qilinsinmi?" vazifasi 72 soat; avtomatik bekor yo'q; do'kon sozlaydi | Hech narsa unutilmaydi, qarorni odam qiladi | Menejer vazifalarni ko'rib chiqishi kerak |
| C | Avtomatik bekor | Stok o'zi tozalanadi | Kelishilgan buyurtma kutilmaganda bekor |

### DEC-105 — Stok qachon band qilinadi va kamayadi (DDD-O02, C4-O03) — `APPROVED (2026-10-21, founder): A`
**Nima:** bitta qolgan mahsulotni ikki xaridorga va'da qilmaslik uchun stok qaysi paytda band bo'ladi va qachon ombordan chiqadi.
**Qayerda:** `business/03` BL-019…023, `business/05` FSM-07, `engineering/01-architecture-overview.md` §7.1 ("qaror qilinmagan" edi), `engineering/12-concurrency-and-transactions.md`.
**Ta'sir:** `modules/inventory`, `workflows/order_confirmation`, FSM-07/08, oversell testlari (TC-002, TC-CON).

| Variant | Mazmuni | Afzallik | Kamchilik |
|---|---|---|---|
| A ✅ | `CONFIRMED` → reserved; `PROCESSING` → allocated; `COMPLETED` → on_hand kamayadi (consumed); bekor → rezerv bo'shaydi | Javobsiz so'rovlar stokni egallamaydi; ombor jismoniy holatiga mos | So'rov va tasdiq orasida mahsulot tugashi mumkin — tasdiqda qulf bilan qayta tekshiriladi |
| B | So'rov kelishi bilan band | Kafolat yuqori | Unutilgan so'rovlar stokni bloklaydi |
| C | Tasdiqda darhol on_hand kamayadi | Oddiy | Jismoniy holatga zid; bekor qilishda qaytarish |

### DEC-106 — Rezerv tugagandan keyin kelgan to'lov (D-04) — `CLOSED` (DEC-100: Stage 1 da tizim orqali to'lov yo'q). To'lov moduli qaytganda qayta ochiladi.

### DEC-107 — Stage 1 da stok manbai (O-04) — `APPROVED (2026-10-21, founder): A`
**Nima:** qoldiqning "haqiqiy" manbai — bizning dashboard yoki do'konning tashqi dasturi.
**Qayerda:** `business/03` BL-073, `business/11` O-04, `engineering/01-architecture-overview.md` DDD-O04, C4-O03.
**Ta'sir:** `modules/inventory` (ledger, import, "tez sotuv" DEC-123), AI "bor/yo'q" javobi. POS sinxron — Stage 2 (M22). Pilot intervyusida do'konning hozirgi tizimi aniqlanadi.

| Variant | Mazmuni | Afzallik | Kamchilik |
|---|---|---|---|
| A ✅ | Dashboard yagona master: qo'lda, CSV/XLSX import, tez sotuv; har o'zgarish ledger'da | Bitta haqiqat, tarix, ishonchli rezerv | Do'kon eski dasturini ham yuritsa — ikki marta ish |
| B | Tashqi Excel/POS master | Odat o'zgarmaydi | Stok eskiradi, rezerv tashqarida ko'rinmaydi |

### DEC-108 — Buyurtmani kim tasdiqlaydi — `APPROVED (2026-10-21, founder): A`
(Avvalgi savol "qo'lda to'lovni kim tasdiqlaydi" — DEC-100 bilan `DEFERRED`.)
**Nima:** mahsulot borligini va buyurtmani `CONFIRMED` ga kim o'tkazadi.
**Qayerda:** `business/04` matritsasi ("Order confirm/cancel": Sales P edi), `business/05` FSM-08.
**Ta'sir:** permission katalogi (`orders.confirm` — Sales o'ziga biriktirilgan buyurtma uchun; `orders.cancel` — Manager/Owner), `business/04` jadvali yangilanadi.

| Variant | Mazmuni | Afzallik | Kamchilik |
|---|---|---|---|
| A ✅ | Sales o'ziga biriktirilgan buyurtmani yoki Manager tasdiqlaydi (stok tizimda qayta tekshiriladi); bekor qilish — Manager/Owner | Tez; kichik do'konda menejer kutilmaydi | Matritsa o'zgaradi (Sales: P → W o'z buyurtmasi) |
| B | Faqat Manager/Owner | Nazorat kuchli | Menejer band bo'lsa buyurtma kutadi |

### DEC-109 — Sales operator quote tasdiqlay oladimi — `APPROVED (2026-10-21, founder): A`
**Nima:** operator o'zi tuzgan PC taklifini o'zi tasdiqlay oladimi.
**Qayerda:** `business/04` ("Quote approve: Sales —"), `engineering/10-security-tenancy-rbac.md` ("cap policy") — zid edi; BL-045.
**Ta'sir:** permission `quotes.approve` — faqat Manager (limit ichida) va Owner; `engineering/10-security-tenancy-rbac.md` matritsasi tuzatiladi.

| Variant | Mazmuni | Afzallik | Kamchilik |
|---|---|---|---|
| A ✅ | Yo'q: Sales draft yaratadi; Manager — limit ichida; Owner — cheksiz | "Yaratgan o'zi tasdiqlamaydi"; xato/kelishuvdan himoya | Menejer bo'lmasa kutiladi (kichik do'konda egasi Manager rolida) |
| B | Sales kichik limitgacha | Tezroq | Nazorat zaif |

### DEC-110 — Chegirma limitlari (O-03) — `APPROVED (2026-10-21, founder): A`
**Nima:** savdolashishda kim qancha chegirma bera oladi.
**Qayerda:** `business/03` BL-017, `business/04` (Sales P, Manager RW/limit), BL-041 (AI chegirma bermaydi).
**Ta'sir:** merchant policy `discount_limits` (rol → %), quote/buyurtma tasdig'ida limit tekshiruvi, chegirma so'rovi oqimi (Sales → Manager).

| Variant | Mazmuni | Afzallik | Kamchilik |
|---|---|---|---|
| A ✅ | Merchant sozlaydi. Default: Sales 0% (faqat so'raydi), Manager 5% gacha, undan yuqori Owner | Har do'kon o'z siyosati; foiz narxga moslashadi | Sozlama ekrani kerak |
| B | Faqat Owner | Qattiq nazorat | Owner band |
| C | So'mda limit | Aniq | Qimmat/arzon mahsulotga noqulay |

### DEC-111 — Stage 1 da to'lov usuli — `APPROVED (2026-10-21)`: **C** — to'lov tizimdan tashqarida, har do'kon o'zi oladi (DEC-100). Ixtiyoriy "to'landi" belgisi — DEC-100a.

### DEC-112 — Voice Copilot Stage 1 da (O-08, HYP-007) — `APPROVED (2026-10-21, founder): B`
**Nima:** do'kon egasi ovoz bilan uz/ru/en tilida hisobot so'rashi.
**Qayerda:** `business/02` M18, `business/08` §3, `engineering/15-voice-assistant.md`, `business/10` R7.
**Ta'sir:** S5 — matnli hisobot-chat (metric registry, ruxsatlar); voice beta — DEC-010 bake-off va golden set'dan keyin feature flag bilan.

| Variant | Mazmuni | Afzallik | Kamchilik |
|---|---|---|---|
| A | S5 da 3 tilda voice beta | Kuchli demo | O'zbek ASR xatosi → noto'g'ri raqam, ishonch yo'qoladi |
| B ✅ | S5 da avval matnli hisobot-chat; voice beta golden set testidan o'tgach | Mantiq bir xil, ovoz faqat kirish usuli; noto'g'ri raqam xavfi yo'q | Demoda ovoz kechroq |
| C | Voice Stage 2 ga | Stage 1 kichik | Farqlovchi xususiyat yo'qoladi |

### DEC-113 — Yetkazish (O-06) — `DEFERRED (2026-10-21, founder)`: Stage 1 da yetkazish moduli yo'q
**Founder qarori:** hozircha kerak emas — yetkazish servislari bilan shartnoma va integratsiya yo'q. Yetkazishni do'kon o'zi tizimdan tashqarida tashkil qiladi.
**Qayerda:** `business/02` M15, `business/05` FSM-10, `business/11` O-06.
**Ta'sir:**
- M15 (yetkazish va pickup), FSM-10 (Shipment), kuryer roli va ekrani Stage 1 dan chiqadi.
- Buyurtmada faqat xaridor tanlovi qoladi: `fulfillment_method` (`PICKUP` / `DELIVERY`) va manzil (DELIVERY bo'lsa).
- Buyurtma oqimi: `CONFIRMED` → `PROCESSING` (tayyorlanmoqda / yo'lda) → `COMPLETED` (xaridorga topshirildi) — statusni xodim o'zgartiradi, xaridorga status xabari boradi (M17).
- Qayta ko'rish: yetkazish hamkori bilan shartnoma yoki pilotda kuryer ekraniga talab paydo bo'lganda (variant B — kuryer PWA, C — servis integratsiyasi).

### DEC-114 — Qaytarish / kafolat (M16) — `APPROVED (2026-10-21, founder): A`
**Nima:** "mahsulot ishlamayapti" murojaatlari tizimda qanday yuritiladi.
**Qayerda:** `business/02` M16, `business/03` BL-057…059, `business/05` FSM-11.
**Ta'sir:** `modules/fulfillment` ichida `support_cases` (S5); buyurtma qatorida kafolat shartlari snapshot'i **S4 dan boshlab** saqlanadi; qaytgan mahsulot ledger'da `RETURNED_QUARANTINE`, tekshiruvgacha sotuvga chiqmaydi. Pul qaytarish tizimdan tashqarida (DEC-100).

| Variant | Mazmuni | Afzallik | Kamchilik |
|---|---|---|---|
| A ✅ | Buyurtmaga bog'langan murojaat: muammo, kafolat shartlari, holat (yangi → ko'rib chiqilmoqda → hal qilindi), qaror | PC do'konida tez-tez kerak; hech narsa unutilmaydi | S5 ga ish qo'shiladi |
| B | Stage 2 ga | Stage 1 kichik | Kafolat daftarda qoladi |
| C | To'liq RMA | To'liq | Juda katta |

### DEC-115 — Storefront (M07) Stage 1 hajmi — `APPROVED (2026-10-21, founder): A`
**Nima:** avtomatik yaratiladigan do'kon sayti Stage 1 da nima qila oladi.
**Qayerda:** `business/02` M07, `business/06` storefront route'lari, DEC-100d.
**Ta'sir:** `apps/merchant-storefront` (katalog, mahsulot sahifasi, savatcha, buyurtma formasi, web chat), `/api/v1/storefront/{slug}/*`, S1 hajmi.

| Variant | Mazmuni | Afzallik | Kamchilik |
|---|---|---|---|
| A ✅ | Katalog + mahsulot sahifasi + savatcha → buyurtma so'rovi (kontakt, manzil / olib ketish), to'lovsiz; + web chat; operator tasdiqlaydi | Xaridor o'zi buyurtma beradi; oddiy | Savatcha va forma ekranlari kerak |
| B | Faqat "narx so'rash" + chat | Tez quriladi | Har xarid chat orqali |
| C | Sayt yo'q | Ish kam | "Websaytsiz online savdo" va'dasi bajarilmaydi |

### DEC-116 — Stage 1 kanallari (O-09) — `APPROVED (2026-10-21, founder): C` — Telegram + Instagram birga (+ web chat, DEC-115)
**Nima:** xaridor do'kon bilan qaysi kanallarda yozisha oladi.
**Qayerda:** `business/08` §5, `engineering/13-integrations-and-channels.md` §2, `business/11` BD-09/O-09.
**Ta'sir:** S2 ga Telegram bot va Instagram adapterlari ikkalasi kiradi; `business/11` BD-09 ("Meta permission gated") qayta ko'riladi.
**Muhim bog'liqlik:** Instagram Direct uchun Meta'ning rasmiy app review jarayoni (business verification, privacy policy, ruxsatlar) talab qilinadi va uning muddati bizga bog'liq emas. Ariza S0 bilan bir vaqtda topshirilishi kerak. Meta ruxsati kechiksa nima qilinishi — DEC-116a.

| Variant | Mazmuni | Afzallik | Kamchilik |
|---|---|---|---|
| A | Telegram + web; Instagram ruxsat kelgach | Reliz Meta'ga bog'liq emas | Instagram-first do'konlar kutadi |
| B | Faqat web chat | Oddiy | Xaridorlar Telegram'da |
| C ✅ | Telegram + Instagram birga | Instagram-first do'konlarga birinchi kundan mos | Reliz Meta ruxsatiga bog'liq bo'lib qoladi |

**DEC-116a — Meta ruxsati kechiksa — `FOUNDER ASSUMPTION (2026-10-21)`:** founder Meta ruxsati kechikmaydi deb hisoblaydi; Instagram S2 da Telegram bilan birga quriladi. Majburiy chora: Meta arizasi S0 bilan bir vaqtda topshiriladi. Risk registrda qoladi (`business/11` §C "Meta access withheld"); agar pilot sanasiga qadar ruxsat kelmasa, qaror qayta ko'riladi (variant: Telegram bilan boshlash, Instagram ruxsat kelgach yoqiladi).

### DEC-117 — Audio saqlash muddati (O-11) — `APPROVED (2026-10-21, founder): A`
**Nima:** xaridor va do'kon egasining ovozli xabarlari qancha saqlanadi.
**Qayerda:** `business/11` O-11, `engineering/15-voice-assistant.md` §5, `engineering/10-security-tenancy-rbac.md` Privacy, `engineering/01-architecture-overview.md` §6.3.
**Ta'sir:** audio transkripsiyadan keyin o'chiriladi (o'chirish job'i + audit), faqat redact qilingan transcript qoladi; ASR golden set alohida, yozma rozilik bilan yig'iladi. Boshqa ma'lumot turlari uchun retention huquqshunos bilan belgilanadi.

| Variant | Mazmuni | Afzallik | Kamchilik |
|---|---|---|---|
| A ✅ | Transkripsiyadan keyin o'chiriladi | Huquqiy xavf kam, xarajat yo'q | Asl ovozni qayta eshitib bo'lmaydi |
| B | 30 kun | Qayta tekshirish mumkin | 30 kun PII saqlanadi |
| C | Do'kon sozlaydi | Moslashuvchan | Javobgarlik noaniq |

### DEC-118 — Merchant ma'lumotida AI o'qitish (O-14, D-07) — `APPROVED (2026-10-21, founder): A`
**Nima:** suhbatlar va buyurtmalar AI modelini o'qitishda ishlatiladimi.
**Qayerda:** `business/11` O-14, `engineering/10-security-tenancy-rbac.md` Privacy, `engineering/16-ai-data-and-evaluation.md` §2, `business/08` §7.
**Ta'sir:** merchant sozlamasida `ai_training_opt_in` (default `false`); dataset pipeline faqat opt-in + anonimlashtirilgan ma'lumot; eval uchun sintetik ma'lumot; merchant shartnomasiga band.

| Variant | Mazmuni | Afzallik | Kamchilik |
|---|---|---|---|
| A ✅ | Default yo'q; opt-in bo'lsa anonim va faqat o'sha do'kon uchun | Ishonch, huquqiy xavf kam | Ma'lumot sekin yig'iladi |
| B | Anonim umumiy, opt-out | Tez yaxshilanish | Ishonch pasayadi |
| C | Hech qachon | Eng xavfsiz | Yaxshilash imkoni yo'q |

### DEC-119 — Pilot va monetizatsiya (O-12, O-15) — `APPROVED (2026-10-21, founder): A`
**Nima:** birinchi do'konlar bilan qanday shartlarda ishlanadi.
**Qayerda:** `discovery/A01` §9, `business/11` O-12/O-15.
**Ta'sir:** M19 — usage limitlari (xabar, AI so'rovlari), merchant uchun limit ogohlantirishlari; pilot MOU shabloni (yozilishi kerak).

| Variant | Mazmuni | Afzallik | Kamchilik |
|---|---|---|---|
| A ✅ | 30 kun bepul, xabar/AI limitlari bilan, pullik davom sharti oldindan yozma (MOU) | Do'kon xavf qilmaydi; AI xarajati cheklangan; pullikka o'tish oldindan kelishilgan | 30 kun o'lchash uchun qisqa bo'lishi mumkin |
| B | Darhol chegirmali pullik | To'lash niyati darhol tekshiriladi | Kirish to'sig'i |
| C | 3 oy bepul | Jozibali | Xarajat katta, signal zaif |

### DEC-120 — Reference spec library'ni kim yuritadi — `APPROVED (2026-10-21, founder): A`
**Nima:** DEC-011 kutubxonasini kim to'ldiradi va yangilaydi.
**Qayerda:** yangi; `engineering/28-network-and-global-search.md` (Stage 2 matching) bilan bog'liq.
**Ta'sir:** platforma admin UI (spec kiritish, manba), merchant "yangi model so'rovi", S1/S3 dan oldin ~1–2 haftalik boshlang'ich to'ldirish ishi.

| Variant | Mazmuni | Afzallik | Kamchilik |
|---|---|---|---|
| A ✅ | Platforma jamoasi (founder + PC mutaxassis) ishlab chiqaruvchi hujjatlari asosida; merchant so'rov yuboradi | Sifat nazorati, manba har qiymatda | Boshlang'ich 1–2 hafta + haftalik yangilash |
| B | Merchantlar kiritadi, biz tekshiramiz | Ish kam | Sifat notekis |
| C | Tashqi bazani litsenziyalash | Tez | Narx; mahalliy modellar qamralmasligi |

### DEC-121 — Valyuta (BL-018) — `APPROVED (2026-10-21, founder): B`
**Nima:** do'kon narxni dollarda yurita oladimi.
**Qayerda:** `business/03` BL-018, `business/02` M05, DEC-007.
**Ta'sir:** `modules/pricing` — `exchange_rates` (merchant kiritadi yoki Markaziy bank kursi; manba, vaqt), "kurs eskirdi" ogohlantirishi; buyurtma va quote qatorida kurs snapshot'i; xaridorga har doim UZS. Intervyuda tasdiqlanadi.

| Variant | Mazmuni | Afzallik | Kamchilik |
|---|---|---|---|
| A | Faqat UZS | Oddiy | Dollardagi do'kon narxlarni har kuni qo'lda o'zgartiradi |
| B ✅ | SKU narxi UZS yoki USD; xaridorga do'kon kursi bo'yicha UZS; kurs snapshot | Bozor amaliyotiga mos | Kurs jadvali va ogohlantirish kerak |
| C | To'liq multi-currency | Moslashuvchan | Ortiqcha |

### DEC-122 — Merchant aktivatsiyasi (DDD-O01, BL-003) — `APPROVED (2026-10-21, founder): A`
**Nima:** ro'yxatdan o'tgan do'kon qachon haqiqiy sotuvni boshlay oladi.
**Qayerda:** `business/03` BL-001/003, `business/05` FSM-01, `engineering/01-architecture-overview.md` DDD-O01.
**Ta'sir:** FSM-01 `PENDING_VERIFICATION → ACTIVE` faqat platforma admini tomonidan; platforma admin ekrani (S0/S1); self-service — Stage 2 (M21).

| Variant | Mazmuni | Afzallik | Kamchilik |
|---|---|---|---|
| A ✅ | Platforma jamoasi qo'lda faollashtiradi, katalogni tekshiradi | Pilotda sifat nazorati | Ko'p do'konga masshtablanmaydi |
| B | Avtomatik hujjat tekshiruvi | Masshtab | Stage 1 uchun og'ir |
| C | Faqat telefon/email | Tez | Soxta do'kon xavfi |

---

### DEC-124 — Tenant (do'kon) nomi — `APPROVED (2026-10-22, founder): shop`
**Nima:** platformadan foydalanuvchi do'kon hujjatlarda va kodda qanday ataladi. "Merchant" founder uchun tushunarsiz edi.
**Ta'sir:** K-01 o'zgaradi: `merchant_id` → `shop_id`. Biznes hujjatlari qayta yozilayotganda "shop" (izohda "do'kon") ishlatiladi; engineering hujjatlari va kod — engineering bosqichida (bismuth v2 standartlari bilan) birga yangilanadi. Boshqa nomlar (masalan, xodim rollari) kerak bo'lsa alohida savollar bilan hal qilinadi.

| Variant | Afzallik | Kamchilik |
|---|---|---|
| `shop` ✅ | Eng oddiy, "do'kon" ma'nosini to'g'ridan-to'g'ri beradi | — |
| `store` | Keng tarqalgan | `storefront`, `storage` bilan chalkashadi |
| `seller` | Sotuvchi ma'nosi | `SALES` xodim roli bilan chalkashadi |
| `business` | Kelajakda boshqa sohalarga mos | Juda keng ma'noli |

### DEC-125 — Hujjatlar tuzilmasi va uslubi — `APPROVED (2026-10-22, founder)`
- `business/` da faqat odam o'qiydigan hujjatlar qoladi; dasturchilar uchun yozilgan `07` (entity'lar), `09` (event'lar), `12` (bog'lanish indeksi) `engineering/07-data-layer.md`, `35`, `36` ga ko'chirildi.
- Biznes hujjatlari oddiy o'zbek tilida, boshqa odamlar ham tushunadigan qilib qayta yoziladi; holatlar strelka ketma-ketligi bilan tushuntiriladi.
- Engineering hujjatlari `bismuth_platform_v2/docs/v2` standartlariga moslab qayta ko'rib chiqiladi (biznes hujjatlaridan keyin).

### DEC-128 — Saytda qoldiq qanday ko'rsatiladi — `APPROVED (2026-10-22, founder): A`
**Nima:** shop saytida va AI javoblarida mahsulot qoldig'i aniq son bilanmi yoki faqat holat bilanmi.
**Qayerda:** `business/02` M07, `engineering/08-cache-and-realtime.md`, `modules/storefront`.

| Variant | Mazmuni | Afzallik | Kamchilik |
|---|---|---|---|
| A ✅ | Shop sozlamasi: `EXACT` (aniq son) yoki `STATUS_ONLY` ("bor / kam qoldi / yo'q") | Qoldig'ini yashirmoqchi bo'lgan shoplarga qulay | Bitta qo'shimcha sozlama |
| B | Har doim aniq son | Oddiy | Ba'zi shoplar istamaydi |
| C | Har doim faqat holat | Oddiy, xavfsiz | Xaridor nechta qolganini bilmaydi |

### DEC-129 — Xodimlarga xabar kanali — `APPROVED (2026-10-22, founder): A`
**Nima:** yangi buyurtma, uzatilgan suhbat, eslatmalar haqida xodim qayerdan biladi.
**Qayerda:** `business/02` M17, `engineering/20-notifications.md`, `engineering/22-infrastructure-and-deployment.md`.

| Variant | Mazmuni | Afzallik | Kamchilik |
|---|---|---|---|
| A ✅ | Panel (real vaqt) + platformaning Telegram tizim boti; xodim botga bir marta ulanadi | Panel yopiq bo'lsa ham xodim biladi | Yana bitta bot; ulash qadami |
| B | Faqat panel | Oddiy | Panel yopiq bo'lsa javob kechikadi |

### DEC-130 — Kafolat murojaatini kim ochadi — `APPROVED (2026-10-22, founder): A`
**Nima:** `business/04` (operator faqat ko'radi) va `business/05` FSM-11 (operator ko'rib chiqishni boshlaydi) o'rtasidagi ziddiyat.
**Qayerda:** `business/04`, `business/02` M16, `engineering/10-security-tenancy-rbac.md`, `modules/support`.

| Variant | Mazmuni | Afzallik | Kamchilik |
|---|---|---|---|
| A ✅ | Operator ochadi va ma'lumot yig'adi; qabul/rad qarorini menejer yoki ega qiladi | Xaridor bilan gaplashayotgan odam darhol ro'yxatga oladi | — |
| B | Faqat menejer ochadi | Nazorat kuchli | Sekinroq |

### DEC-131 — Xodimlar, rollar va ruxsatlar (1-funksiya bazasi) — `APPROVED (2026-10-23, founder)`
**Nima:** `platform` diagrammasini ko'rib chiqishda qabul qilingan qarorlar.
**Qayerda:** `engineering/db/platform.dbml`, `engineering/db/platform.md`, `business/04`, `business/02` M02.

| Savol | Qaror | Nega |
|---|---|---|
| Bir odam nechta shopda ishlaydi? | Hozircha **bitta** (`memberships.principal_id` unikal) | Pilot uchun yetarli; jadvallar ajratilgani uchun keyin cheklovni olib tashlash oson |
| Bitta xodimga nechta rol? | **Bitta** (`memberships.role`) | Sodda; kichik shopda ega baribir hammasini qila oladi. DEC-100f dagi "bir nechta rol / kichik do'kon shabloni" o'rniga |
| Stage 1 rollari | **4 ta:** Ega, Menejer, Operator, Omborchi | Pilot shoplarda 1–5 kishi. Moliya, katalog xodimi, tahlilchi, AI muharriri — keyinroq |
| Rol → ruxsatlar qayerda? | **Kodda** (`app/platform/staff/permissions.py`), bazada jadval yo'q | Rollar hamma shop uchun bir xil; bitta manba, testlar tekshiradi. Shop o'z rolini yaratsa (Stage 2) — jadval |
| Xodim taklifi | **Ega havolani o'zi yuboradi** (`invitations.channel = LINK`) | Bepul, SMS provayder kerak emas; SMS keyin |
| STIR | **Majburiy va unikal** | Pilot kelishuvi, bitta korxona ikki marta ro'yxatdan o'tmasin |
| Login | Telefon (majburiy) + parol; parolni terib topishdan himoya (5 xato → 15 daqiqa blok) | SMS kod (OTP) keyinroq |

### DEC-133 — Katalog bazasi (2-modul) — `APPROVED (2026-10-25, founder)`
**Nima:** `catalog` diagrammasini ko'rib chiqishda qabul qilingan qarorlar.
**Qayerda:** `engineering/db/catalog.dbml`, `engineering/db/catalog.md`, `business/05` (FSM-02), `business/02` M04/M05.

| Savol | Qaror | Nega |
|---|---|---|
| Saytga chiqarish | Ega yoki menejer qoralamani **to'g'ridan** chiqaradi; "Tekshiruvda" — keyin katalog xodimi qo'shilganda | Stage 1 da katalog xodimi roli yo'q (DEC-131); ortiqcha bosqich foydasiz |
| Arxivlash | **Faqat ega**, qoralama / chiqarilgan / yashirilgan holatdan | `business/05` dagidek ega qaroridir |
| Toifalar | **Platforma ro'yxati** (3 tilda), shop faqat tanlaydi | AI qidiruv, texnik kutubxonaga bog'lash va Stage 2 umumiy qidiruv uchun tartib |
| So'm narxini yaxlitlash | **Yaxlitlanmaydi**, aniq so'mgacha | Founder tanlovi |
| Mahsulot rasmlari | **Ochiq** (taxmin qilib bo'lmaydigan manzil); import va eksport fayllari yopiq | Sayt tezligi, kesh, Telegram/Instagram'da ochilishi |
| "Aksiya" (`discount_rules`) | **Stage 1 da yo'q** | Chegirma limitlari `shop_policies` da, aniq chegirma taklif va buyurtmada (3-modul) |

### DEC-134 — Ombor va buyurtmalar bazasi (3-modul) — `APPROVED (2026-10-25, founder)`
**Nima:** `commerce` diagrammasini ko'rib chiqishda qabul qilingan qarorlar.
**Qayerda:** `engineering/db/commerce.dbml`, `engineering/db/commerce.md`, `business/05` (FSM-07, FSM-08).

| Savol | Qaror | Nega |
|---|---|---|
| 72 soatlik "bekor qilinsinmi?" | **Band va ajratilgan** bandlarga; tayyorlanayotgan buyurtma ham shu vazifadan bekor qilinishi mumkin | Xaridor kelmagan tayyor buyurtma unutilmaydi, mahsulot bekorga turmaydi |
| Filial | **Bir buyurtma — bitta filial** | Xaridor bitta joydan oladi; qoldiq va band sodda |
| Tasdiqlangandan keyin o'zgartirish | **Yo'q** — bekor qilib yangisi ochiladi | Band, daftar va narx tarixi toza |
| Stok tuzatish tasdig'i | Omborchiniki **har doim** tasdiq bilan; ega/menejer to'g'ridan | Sozlama yo'q, kamomadni jim yashirib bo'lmaydi |
| Kurs o'zgarsa | Tasdiqlashda **so'm narxi qayta hisoblanadi**; farq bo'lsa "narx o'zgardi" va xaridor roziligi | Xaridor ko'rgan summa jim o'zgarmaydi (BL-047), farqni shop ham ko'tarmaydi |

### DEC-135 — Shop sayti bazasi (4-modul) — `APPROVED (2026-10-25, founder)`
**Nima:** `storefront` diagrammasini ko'rib chiqishda qabul qilingan qarorlar.
**Qayerda:** `engineering/db/storefront.dbml`, `engineering/db/storefront.md`.

| Savol | Qaror | Nega |
|---|---|---|
| Sayt ma'lumotni qayerdan o'qiydi | Katalog va ombordan **to'g'ridan**, faqat ochiq maydonlar, 60 s kesh; nusxa jadvali keyin | Fon ishlari 5-modulda; 4-modul hozir quriladi |
| O'z domeni | Stage 1 da **yo'q**, faqat `slug.platforma.uz` | Bitta SSL, DNS tekshiruvi yo'q; pilotdan keyin |
| Filial bo'yicha mavjudlik | **Mahsulot sahifasida** (2+ olib ketish joyi bo'lsa); ro'yxatda umumiy holat | Xaridor to'g'ri filialni tanlaydi, qo'ng'iroq kamayadi |
| Ma'lumot sahifalari | **3 ta tayyor sahifa** | Sozlash sodda, har shopda kerakli javoblar bor |
| Shop matnlari tili | **Bitta tilda**; sayt tugmalari doim 3 tilda | Mahsulot tavsifi bilan bir xil qoida |

### DEC-136 — Kirim tasdig'i va faollashtirilmagan shopda savdo — `APPROVED (2026-10-26, founder)`
**Nima:** 3-modul QA tekshiruvida chiqqan ikki hujjat ziddiyati bo'yicha qaror.
**Qayerda:** `business/04` (rollar jadvali), `business/05` (FSM-01), `engineering/db/commerce.md` §3.

| Savol | Qaror | Nega |
|---|---|---|
| Stok kirimi menejer tasdig'idan o'tadimi | **Yo'q** — omborchi, menejer va ega kiritgan kirim darhol qoldiqqa qo'shiladi | Kirim qoldiqni oshiradi, xavf kam; xato kirim tuzatish bilan to'g'rilanadi. `business/04` dagi "Tasdiqlaydi" olib tashlandi |
| Faollashtirilmagan shop (qoralama, tekshiruvda) savdo qila oladimi | **Ha** — yangi savdo faqat to'xtatilgan (SUSPENDED) va yopilgan (CLOSED) shopda bloklanadi | FSM-01 qoidasi so'zma-so'z; shop tizimni faollashtirishgacha o'rganadi. Sayt faqat faol shopda ochiladi |

## 4. Eski ID'lar xaritasi

| Eski ID | Yangi |
|---|---|
| D-01 (3 bosqich, PC vertikal) | BD-01/BD-02 — allaqachon biznes baseline |
| D-02, A-01, C4-O09 | DEC-002 |
| D-03, C4-O02 | DEC-003 |
| D-04 | DEC-104, DEC-106 |
| D-05, O-04, DDD-O04 | DEC-107 |
| D-06, O-05, DDD-O05, C4-O05, A-03 | DEC-108, DEC-111 |
| D-07, O-14 | DEC-118, DEC-016 |
| D-08, O-09, DDD-O07, C4-O06 | DEC-116 |
| D-09, A-07, C4-O10 | DEC-013 (+ RPO/RTO restore test bilan) |
| D-10, O-11, A-04, DDD-O09, C4-O01 | DEC-013, DEC-016, DEC-117 + huquqshunos |
| O-01 | DEC-101 |
| O-02, DDD-O02, C4-O03 | DEC-104, DEC-105 |
| O-03, DDD-O03, C4-O04 | DEC-103, DEC-110, DEC-121 |
| O-06, DDD-O06 | DEC-113 |
| O-07 | Merchant policy + huquqshunos (ochiq) |
| O-08, A-05, DDD-O08, C4-O07 | DEC-010, DEC-112 |
| O-10, O-13, DDD-O10, DDD-O11, C4-O11, C4-O12 | Stage 2/3 — `DEFERRED` |
| O-12, O-15 | DEC-119 |
| A-02 | DEC-003 (load test bilan) |
| A-06 | Storefront subdomain — S1 da platforma subdomeni, custom domain keyin |
| C4-O08 | DEC-014, DEC-008 |
| DDD-O01 | DEC-122 |
| DDD-O12 | Metric registry (S5) — `DEFERRED` |

## 5. Tasdiqlangandan keyin bajariladigan ishlar

1. Har bir `APPROVED` qaror ta'sir qiladigan hujjatlarga kiritiladi (ADR, FSM, rollar, API, DB).
2. K-01…K-10 konvensiyalari bo'yicha barcha hujjatlarda nomlar birlashtiriladi.
3. Eski `O-xx`/`D-xx` jadvallari o'rniga shu registrga havola qo'yiladi.
4. ✅ Yangi hujjatlar yozildi (2026-10-22): `engineering/11-api-conventions-errors-i18n.md`, `engineering/17-pc-compatibility-engine.md`, `engineering/14-ai-sales-agent-and-tools.md`.
