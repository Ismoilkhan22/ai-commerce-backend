# 22 — Infratuzilma va deployment

> **Versiya:** v2 (2026-10-22). Eski `19_INFRASTRUCTURE_AND_DEPLOYMENT` va `04_SYSTEM_ARCHITECTURE_C4` §9 o'rnini bosadi.
> **Qarorlar:** DEC-001 C (shared-first, dedicated-ready), DEC-003 D (outbox + arq), DEC-012 B (Grafana Cloud + Sentry), DEC-013 A (PII O'zbekistonda), ADR-020, ADR-030, ADR-033, ADR-035.
> **Holat:** S0-10 (2026-10-27) — bitta VPS uchun deploy tayyor: image'lar, `deploy/docker-compose.prod.yml`, nginx, backup, CI. Hali hech qayerga o'rnatilmagan. Haqiqiy shaxsiy ma'lumot huquqshunos xulosasidan keyin (DEC-013). Founder uchun qadamlar: [progress/M08-deploy.md](progress/M08-deploy.md).

## 1. Muammo va yechim

**Muammo:** bitta odam (founder) ishlatadigan tizim: Kubernetes, ko'p servisli monitoring stack yoki murakkab CI — vaqtni yeydi. Lekin backup, tiklash va maxfiy kalitlar bo'yicha xato — kechirib bo'lmaydi.

**Yechim:**
- **Bitta Docker image**, to'rt xil buyruq: `api`, `outbox-worker`, `task-worker`, `scheduler`.
- **Docker Compose** O'zbekistondagi VM'da (pilot). Kubernetes — yo'q.
- Monitoring — Grafana Cloud + Sentry (o'z serverimizda monitoring stack yo'q).
- Backup — har kuni + PITR, **oyiga bir marta tiklash mashqi**.

---

## 2. Jarayonlar (bitta image)

```
deploy/docker/Dockerfile  →  image: cos-backend:<git-sha>

ENTRYPOINT deploy/docker/entrypoint.sh (`cos <buyruq>`), Makefile maqsadlari bilan bir xil:
  api            uvicorn app.main:app --workers $WEB_CONCURRENCY --no-access-log --no-proxy-headers   # stateless, ×1–N
  outbox-worker  python -m app.workers.outbox_worker      # ×1–2 (SKIP LOCKED tufayli parallel xavfsiz)
  task-worker    arq app.workers.task_worker.WorkerSettings   # ×2–3
  scheduler      python -m app.workers.scheduler          # ×1–2 (advisory lock: faqat bitta leader)
  migrate        bootstrap (DATABASE_ADMIN_URL bo'lsa, idempotent) + har schema `alembic -n <s> upgrade head`

Image: builder — `ghcr.io/astral-sh/uv` (uv sync --locked --no-dev), runtime — `python:3.12-slim`, foydalanuvchi
`app` (uid 10001), kod `/app` (PYTHONPATH), compose'da read-only root FS + `/tmp` tmpfs.
```

| Jarayon | Masshtab signali | Nima qilinadi | Nima qilinmaydi |
|---|---|---|---|
| `api` | p95, CPU, DB pool to'lishi | Avval so'rov va pool sozlanadi, keyin nusxa qo'shiladi | DB yuklangan paytda faqat API'ni ko'paytirish |
| `outbox-worker` | `cos_outbox_oldest_age_seconds` | 2-nusxa; batch hajmi | Event'ni o'tkazib yuborish |
| `task-worker` | `cos_arq_oldest_job_age_seconds`, LLM rate limit | Nusxa qo'shish; provider bo'yicha concurrency chegarasi | Cheksiz parallel LLM chaqiruvi |
| `scheduler` | — | 2-nusxa faqat zaxira uchun (leader bitta) | Og'ir ishni scheduler ichida bajarish |

Batafsil: [06-background-jobs.md](06-background-jobs.md).

---

## 3. Pilot topologiyasi

```
Internet (xaridorlar, xodimlar, Telegram, Meta)
        │ HTTPS
        ▼
┌───────────────────────────── UZ data center, VM (private network) ───────────────────────────────┐
│  nginx (TLS, Let's Encrypt, rate limit: api., panel., admin., *.<platforma>.uz)  + certbot        │
│     ├──▶ frontend (Next.js standalone: shop-dashboard, platform-admin, shop-storefront)           │
│     └──▶ api ×N                                                                                   │
│                                                                                                    │
│  postgres:16  (schemalar: platform, audit, catalog, commerce, messaging, sales_ai, storefront,     │
│                support, reporting; WAL arxivi → backup storage)                                     │
│  redis:7      (AOF everysec; db0 kesh/rate limit, db1 arq navbati, db2 pub/sub)                    │
│  backup       (busybox cron: har kuni pg_dump → /var/backups/commerce-os, 14 kun)                  │
│  outbox-worker · task-worker ×2 · scheduler                                                        │
│  otel-collector (ixtiyoriy: redaction processor, batching)                                         │
└───────────────────────────────────────────────────────┬───────────────────────────────────────────┘
                                                        │ faqat chiquvchi
          ┌──────────────────────┬──────────────────────┼────────────────────────┐
          ▼                      ▼                      ▼                        ▼
   Telegram / Meta API     LLM provayder          Grafana Cloud + Sentry    Backup joyi
   (task-worker)           (redaction'dan keyin,  (PII'siz telemetriya)     (boshqa UZ DC yoki
                            DEC-016)                                         boshqa disk/VM)
```

- Tashqariga faqat nginx ochiq (80/443). PostgreSQL, Redis, MinIO konsoli, worker'lar — faqat ichki tarmoqda.
- nginx kirish logi yo'lni **query string'siz** yozadi (`log_format` da `$uri`, `$request_uri` emas): qidiruvda xaridor telefoni bo'lishi mumkin (09 §4.2).
- Bitta VM — bitta nosozlik nuqtasi. Pilot uchun ongli qaror; 99.5% maqsad (`00` §4), 99.9% va'da qilinmaydi.
- Fayllar va DB — O'zbekistonda (DEC-013, ADR-030). Fayllar VM ichidagi MinIO'da emas (obrazi Docker Hub'dan endi
  yuklanmaydi, TD-03), **tashqi S3-mos UZ xizmatida** (`STORAGE_BACKEND=s3`); zaxira yo'l — `storage` volume (`local`).
  LLM'ga faqat redaction'dan o'tgan matn.

### 3.1 Haqiqiy o'rnatma (S0-10)

```
deploy/
├── docker/Dockerfile, entrypoint.sh     # backend image, `cos api|outbox-worker|task-worker|scheduler|migrate`
├── docker-compose.prod.yml              # bitta VPS: postgres, redis, backup, migrate, api, 3 worker, 3 frontend, nginx, certbot
├── .env.prod.example                    # compose o'zgaruvchilari: domen, image tag'lari, postgres paroli
├── app.env.example                      # ilova sozlamalari (api/worker'lar o'qiydi) — superuser paroli bu yerda yo'q
├── nginx/nginx.conf                     # rasmiy nginx.conf o'rniga (unda query'li `main` logi bor edi)
├── nginx/templates/default.conf.template  # server'lar, ${PLATFORM_DOMAIN} envsubst bilan
├── nginx/snippets/                      # proxy.conf (XFF), security-headers.conf, tls.conf, admin-allowlist.conf
├── backup/pg_backup.sh, entrypoint.sh   # kunlik pg_dump + retention + sha256
└── secrets/cloudflare.ini.example       # certbot DNS-01 tokeni
ai-commerce-frontend/Dockerfile          # bitta Dockerfile, APP build arg (standalone, foydalanuvchi node)
```

Qarorlar:
- **TLS — nginx + certbot (DNS-01, Cloudflare DNS API)**, Caddy emas. Sabab: shop saytlari `*.platforma.uz` —
  wildcard sertifikat faqat DNS-01 bilan beriladi; bitta sertifikat `platforma.uz` + `*.platforma.uz` hamma
  server'ni qoplaydi. nginx 22-hujjatda allaqachon tanlangan proksi; Caddy'ga o'tish ikkinchi proksi yoki
  on-demand TLS (har shop uchun alohida sertifikat, `ask` endpoint) talab qilardi. Cloudflare faqat DNS sifatida
  ("DNS only", kulrang bulut) — trafik va ma'lumot Cloudflare orqali o'tmaydi, XFF zanjiri o'zgarmaydi.
- **IP'lar qat'iy:** `cos` tarmog'i 172.30.0.0/24; nginx 172.30.0.10, shop sayti serveri 172.30.0.20 →
  `TRUSTED_PROXIES=["172.30.0.10","172.30.0.20"]`; sayt `STOREFRONT_TRUSTED_PROXY_HOPS=1`, SSR API'ni ichkaridan
  (`API_INTERNAL_URL=http://api:8000`) chaqiradi.
- **nginx yuklash chegaralari:** umumiy 2 MB (ilova JSON chegarasi 1 MB); `POST /api/v1/shop/files` — 11 MB
  (import 10 MB + multipart zaxirasi; rasm 5 MB, logotip 2 MB — aniq chegara ilovada, `file_service.PURPOSES`),
  `proxy_request_buffering off`.
- **WebSocket** `/api/v1/ws`: Upgrade/Connection map orqali, `proxy_read_timeout 1h` (heartbeat 25 s).
- **Kirish logi** JSON (`cos_json`): `path` = `$uri` (query'siz), uzun token-ko'rinishli bo'laklar `{seg}`,
  Referer yozilmaydi.
- **Image'lar VPS'ning o'zida build qilinadi** (`up -d --build`, tag = git SHA). Registry (GHCR) — staging
  paydo bo'lganda.
- **Prometheus `/metrics` hali yo'q** — Stage 1 kuzatuvi: `/health/live`, `/health/ready` (tashqi uptime monitor
  `https://api.<domen>/health/ready` ni tekshiradi) + JSON loglar + Sentry. OTel → Grafana Cloud — 09 bo'yicha keyin.

### 3.2 Loglarni ko'rish

Hamma konteyner stdout'ga JSON yozadi; Docker `json-file` (20 MB × 5 fayl, servis bo'yicha) saqlaydi.

```
C="docker compose -f deploy/docker-compose.prod.yml --env-file deploy/.env.prod"
$C logs -f --tail=100 api                     # bitta servis
$C logs -f api task-worker outbox-worker      # bir nechtasi
$C logs --since=1h api | grep '"level":"error"'
$C logs --no-log-prefix api | jq -c 'select(.request_id=="<id>")'   # bitta so'rov zanjiri
$C logs --no-log-prefix nginx | jq -c 'select(.status>=500)'
$C logs backup                                # backup.started / backup.finished
```

Har backend qatorida `service`, `env`, `version` (git SHA), `request_id`/`trace_id` bor (09 §4). Sentry —
faqat `SENTRY_DSN` (backend) / `FRONTEND_SENTRY_DSN` (build vaqtida) berilganda; PII tozalash
`app/config/observability.py` va `@cos/app-kit/sentry`.

---

## 4. Lokal muhit (`deploy/docker-compose.yml`)

```yaml
services:
  postgres:
    image: postgres:16
    environment: { POSTGRES_DB: cos, POSTGRES_USER: app_migrator, POSTGRES_PASSWORD: dev }
    volumes: [ "./deploy/postgres/init:/docker-entrypoint-initdb.d" ]   # schemas.sql, app_runtime roli
    ports: [ "5433:5432" ]   # dasturchining o'z PostgreSQL'i bilan to'qnashmasin
  redis:
    image: redis:7
    command: [ "redis-server", "--appendonly", "yes", "--appendfsync", "everysec" ]
    ports: [ "6380:6379" ]
  minio:
    image: minio/minio
    command: server /data --console-address ":9001"
    ports: [ "9000:9000", "9001:9001" ]
```
Ilova jarayonlari lokalda `uv run` bilan (tez qayta yuklash). Batafsil: [23-dev-setup-and-workflow.md](23-dev-setup-and-workflow.md).

Production `deploy/docker-compose.prod.yml` (§3.1): postgres, redis, backup, migrate (bir martalik), `api`, `outbox-worker`, `task-worker`, `scheduler`, uchta frontend, `nginx`, `certbot`; har servisda `restart: unless-stopped`, healthcheck (api, frontend, nginx, ma'lumotlar), xotira chegarasi; image tag — git SHA (hech qachon `latest`). Loyiha nomi `cos-prod` — lokal `commerce-os` volume'lari bilan aralashmaydi.

---

## 5. Muhitlar

| Muhit | Ma'lumot | Tashqi xizmatlar | Joy | Maqsad |
|---|---|---|---|---|
| `local` | Sintetik (`dev_seed.py`) | Mock / sandbox | Dasturchi kompyuteri | Kod yozish |
| `ci` | Bir martalik fixture'lar | Yo'q (soxta provider payload'lari) | GitHub Actions | Testlar |
| `staging` | Sintetik yoki rozilik bilan olingan sinov ma'lumoti | Sinov bot'lari, Meta test akkaunti, LLM | Istalgan joy (PII yo'q) | Integratsiya, yuklama, tiklash mashqi |
| `production` | Haqiqiy shop va xaridor ma'lumoti | Tasdiqlangan akkauntlar | UZ data center | Ish |

`APP_ENV` sozlamasi; `production` da `debug`, `/docs` (OpenAPI UI) va `dev_seed` o'chiq.

### 5.1 Konfiguratsiya va maxfiy kalitlar
- Hammasi env/secret orqali (`app/config/settings.py`, Pydantic). Kodda manzil yoki kalit yo'q (dedicated-ready qoidasi).
- Ishga tushishda tekshiriladi: DB, Redis, MinIO, public URL'lar, ruxsat etilgan origin'lar, JWT kalitlari, OTel endpoint. Muhimi yetishmasa — jarayon ishga tushmaydi.
- Production secret'lari: VM'da faqat root o'qiy oladigan `.env.prod` (pilot) → keyinroq secret manager. Repo'da faqat `.env.example`.
- Shop kanal tokenlari (Telegram bot token, Meta token) — DB'da shifrlangan (`app/shared/crypto`, kalit env'da), logga hech qachon tushmaydi.
- Platformaning xodimlar uchun tizim Telegram boti (`20` §1): token `STAFF_TELEGRAM_BOT_TOKEN` env/secret'da, webhook `POST /api/v1/webhooks/telegram/staff-bot` (imzo — `secret_token`). Har muhit (dev/staging/prod) uchun alohida bot.
- Kalit almashtirish: ikki kalitli oyna (eski + yangi bir vaqtda qabul qilinadi), audit yozuvi bilan.

---

## 6. CI/CD

### 6.1 Har PR'da (GitHub Actions)

**Hozir bor (S0-10):** backend `.github/workflows/ci.yml` — `make check` (testcontainers: GitHub runner'da Docker bor,
alohida `services: postgres` kerak emas — lokal bilan bir xil yo'l), backend image build, prod compose va nginx
`nginx -t` tekshiruvi. Frontend `.github/workflows/ci.yml` — `pnpm check`, har app uchun `next build` va Docker image
build. Quyidagi ro'yxatning 5–9-bandlari — keyin.

1. `ruff check`, `ruff format --check`
2. `mypy app`
3. `lint-imports` — qatlam va domen kontraktlari (ADR-031)
4. `pytest` — unit + integratsiya (testcontainers: PostgreSQL 16, Redis 7)
5. `pytest tests/isolation tests/concurrency` — TC-ISO, TC-002, TC-027, TC-030
6. Migratsiya tekshiruvi: bo'sh DB'ga **har schema** bo'yicha `upgrade head` → `downgrade -1` → `upgrade head`; cross-schema FK yo'qligi (`information_schema`, ADR-035); RLS yoqilgan jadvallar ro'yxati kutilganiga mos
7. OpenAPI artefakti o'zgargan bo'lsa — frontend `api-client` generatsiyasi tekshiriladi
8. Secret skaneri (gitleaks), dependency audit (`pip-audit`)
9. Telemetriya testi: log/trace fixture'larida PII yo'q, `/metrics` da `shop_id` label yo'q (`09` §11)

### 6.2 `main` ga merge
Image build (`cos-backend:<git-sha>`) → registry → staging'ga avtomatik deploy → smoke testlar.

### 6.3 Production deploy (qo'lda tasdiq bilan)
```
1. Backup nuqtasi (pg_dump yoki PITR belgisi)       — buzuvchi migratsiya bo'lsa majburiy
2. migrate (expand)                                  — yangi ustun/jadval, eskisini o'chirmaydi
3. docker compose pull && up -d (rolling: api avval, keyin worker'lar)
4. /health/ready + smoke (login, katalog, webhook sinovi)
5. Backfill (kerak bo'lsa, arq vazifasi sifatida)
6. Keyingi relizda contract (eski ustunni olib tashlash)
Rollback: oldingi image tag'iga qaytish; migratsiya avtomatik orqaga qaytarilmaydi (expand/contract tufayli eski kod yangi schema bilan ishlaydi)
```

### 6.4 Migratsiyalar (har schema alohida)
- `app/db/migrations/<schema>/` — alohida Alembic env; tartib: `platform` → `audit` → qolganlari (cross-schema FK yo'q, shuning uchun tartib faqat `platform` uchun muhim).
- Buzuvchi migratsiya (ustun o'chirish, tip o'zgartirish) — faqat expand/contract bilan, ikki relizda.
- Ma'lumot tuzatish — migratsiya emas, audit bilan alohida skript.
- Shop ma'lumotiga bog'liq data-migration yo'q (har qanday DB'da ishlashi kerak — dedicated rejim uchun).

---

## 7. Backup va tiklash

### 7.1 Nima, qanchalik tez-tez

| Nima | Usul | Davriylik | Saqlash |
|---|---|---|---|
| PostgreSQL to'liq | `pg_basebackup` (yoki `pgBackRest`) | Har kuni | 14 kun |
| PostgreSQL WAL (PITR) | WAL arxivi | Doimiy | 7 kun |
| Schema bo'yicha mantiqiy dump | `pg_dump --schema=<s> --format=custom` | Har kuni | 7 kun; shop eksporti va bitta schema'ni tiklash uchun |
| Redis | AOF + kunlik RDB snapshot | Doimiy / kuniga | 3 kun (Redis haqiqat manbai emas — §7.3) |
| MinIO | Versioning + boshqa diskka/joyga replikatsiya | Doimiy / kuniga | 30 kun |
| Konfiguratsiya | `deploy/` repo'da; secret'lar shifrlangan nusxa | O'zgarishda | — |

- **Pilotda haqiqatda (S0-10):** faqat kunlik to'liq `pg_dump --format=custom` + `pg_dumpall --globals-only`, 14 kun,
  `sha256` va `pg_restore --list` tekshiruvi (`deploy/backup/pg_backup.sh`, `backup` konteyneri, 03:00 Toshkent).
  RPO ≤ 24 soat. WAL/PITR, schema bo'yicha dump va shifrlangan offsite — pilot shoplar haqiqiy savdo boshlaganda.
  Tiklash buyruqlari — `25` RB-08.
- Backup'lar shifrlangan; boshqa VM yoki boshqa UZ data center'da (DEC-013 — xorijga emas).
- Maqsad (taxmin, isbotlanmagan): **RPO ≤ 1 soat, RTO ≤ 4 soat**. Haqiqiy raqam — tiklash mashqidan keyin yoziladi.

### 7.2 Tiklash mashqi (TC-033)
Oyiga bir marta, staging'da:
1. Oxirgi to'liq backup + WAL bilan belgilangan vaqtga tiklash.
2. Tekshiruv: har schemada jadvallar soni; `stock_ledger` yig'indisi = `stock_balance` (har SKU); FK butunligi; RLS siyosatlari joyida.
3. Outbox: `published_at IS NULL` yozuvlar `outbox-worker` tomonidan qayta yuboriladi; subscriber'lar idempotent — takror ta'sir yo'q.
4. arq navbati bo'sh bo'lishi mumkin — rekonsilyatsiya ishi (`06`) yo'qolgan vazifalarni outbox'dan tiklaydi.
5. MinIO havolalari (rasm, import fayllari) DB'dagi yozuvlarga mos.
6. Vaqt (RTO) va yo'qolgan davr (RPO) `25-operations-runbooks.md` RB-08 jurnaliga yoziladi.

### 7.3 Redis yo'qolsa
Redis — haqiqat manbai emas (ADR-006, ADR-033). Yo'qolganda: kesh qayta to'ladi; rate limit hisoblagichlari nolga tushadi; arq navbatidagi vazifalar outbox va rekonsilyatsiya orqali qayta yaratiladi; WebSocket ulanishlar qayta ulanadi. Pul va qoldiqqa ta'sir yo'q.

---

## 8. Tarmoq va xavfsizlik

- Faqat nginx tashqarida. DB, Redis, MinIO portlari ochiq emas; MinIO konsoli faqat SSH tunnel orqali.
- SSH: faqat kalit, parol o'chiq; root login yo'q; fail2ban.
- TLS: Let's Encrypt wildcard (certbot DNS-01, 12 soatda `renew`, nginx 6 soatda reload); HSTS `includeSubDomains`;
  noma'lum domen/IP bilan kirishda `ssl_reject_handshake`.
- DB rollari: `app_migrator` (DDL, faqat migratsiya), `app_runtime` (`NOBYPASSRLS`, faqat DML) — ilova faqat `app_runtime` bilan ishlaydi (ADR-035, `10`).
- Docker: non-root foydalanuvchi, read-only root filesystem (imkon bo'lsa), image skaneri.
- OS va image yangilanishlari — oyiga bir marta yoki kritik zaiflikda darhol.
- Webhook endpoint'lari faqat imzo bilan (`13`); storefront va webhook surface'larida rate limit.
- **Mijoz IP'si (rate limit).** uvicorn `--no-proxy-headers` bilan ishlaydi: `X-Forwarded-For` ni ilovaning o'zi
  o'qiydi (`app/shared/client_ip.py`) va faqat `TRUSTED_PROXIES` dagi manzildan kelganiga ishonadi; zanjirdan
  o'ngdan birinchi ishonchsiz manzil olinadi. Ro'yxatga **nginx** va **shop sayti serveri** (Next.js, SSR)
  ichki manzillari kiradi: sayt serveri API'ni bitta IP'dan chaqiradi va xaridor IP'sini XFF'da beradi — shunda
  120/daq chegarasi har xaridorga alohida. nginx sozlamasi:
  `proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;` (haqiqiy IP zanjir oxiriga qo'shiladi; xaridor
  chapga nima yozsa ham hisobga olinmaydi). Lokalda ro'yxat `127.0.0.1`, `::1` — XFF'ni soxtalash lokalda
  ataylab mumkin, prod'da emas. Bir nechta XFF qatori bitta zanjirga birlashtiriladi (QA M04 B1). Sayt
  serverining o'zi xaridor IP'sisiz chaqirsa — alohida `sf-ssr:{slug}` chelagi (`STOREFRONT_SSR_READ_LIMIT_PER_MINUTE`,
  `08` §5). Sayt ilovasida `STOREFRONT_TRUSTED_PROXY_HOPS=1` (nginx ortida) — **production'da majburiy**: aks holda hamma mehmon so'rovi sayt serveri IP'si bilan keladi va sayt chati/o'qish chegaralari (sessiya 10/soat, o'qish 120/daq) hamma mehmonga bitta bo'lib qoladi (QA 5b kuzatuv). Sayt CSP'sida `'unsafe-eval'` faqat dev rejimda (Next HMR); production build'da yo'q.
- **Shop sayti va sarlavhalar.** Absolyut havolalar `STOREFRONT_PUBLIC_URL` dan (backend) — nginx'ning `Host` va
  `X-Forwarded-Proto` qiymatiga tayanmaydi. CSP sayt ilovasining o'zida (`10` §11); CDN ishlatilsa — uning manzili
  `STOREFRONT_ASSET_ORIGINS` ga.
- Takroriy so'rov jadvalidagi barmoq izi — `IDEMPOTENCY_HASH_KEY` bilan HMAC (secret manager'da, kamida 32 belgi;
  lokal standart staging/production'da rad etiladi).

---

## 9. Dedicated rejim (DEC-001 C)

**Muammo:** katta mijoz (Enterprise) "ma'lumotim boshqa shoplar bilan bitta DB'da bo'lmasin" deyishi mumkin.

**Yechim:** dedicated = **butun stack'ning alohida nusxasi** (o'sha image, o'sha compose, alohida VM, alohida DB/Redis/MinIO), ichida bitta shop. Alohida kod yoki branch yo'q.

Qoidalar (kod hozirdan shunga amal qiladi):
1. Kod har doim multi-tenant; dedicated — DB'da bitta shop.
2. Hamma manzillar va kalitlar konfiguratsiyadan.
3. Global singleton holat yo'q.
4. Migratsiyalar har qanday DB'da mustaqil ishlaydi.
5. `DEPLOYMENT_MODE=shared|dedicated` faqat operatsion farqlarni boshqaradi (billing hisoboti, telemetriya `deployment` atributi). Xavfsizlik qoidalari o'chmaydi — RLS va `shop_id` tekshiruvlari dedicated'da ham ishlaydi.
6. Stage 2: dedicated shop ommaviy taklif chiqarmoqchi bo'lsa — markaziy `network` ga chiquvchi API orqali yuboradi (`28`).

Dedicated o'rnatish — Enterprise backlog; Stage 1 da faqat yuqoridagi qoidalarga rioya qilinadi.

---

## 10. O'sish yo'li

| Bosqich | Belgisi | Qadam |
|---|---|---|
| Pilot (1–5 shop) | — | Bitta VM, yuqoridagi compose |
| 10–30 shop | DB CPU > 60%, pool to'lishi | VM'ni kattalashtirish (vertikal); sekin so'rovlarni tuzatish |
| 30–100 shop | API va worker'lar DB bilan raqobatlashadi | DB alohida VM'ga; PgBouncer (transaction mode); `get_read_db()` → read replica (hisobotlar, storefront ro'yxatlari) |
| 100+ shop | Redis yoki arq chegarasi | Redis alohida VM; task-worker'lar alohida VM'larda |
| Mustaqil yuklama | Bitta domen boshqalardan ko'p resurs oladi | O'sha domenni alohida servisga (schema + event'lar tayyor, ADR-035) |

Kod hozirdan `get_db()` (yozish) va `get_read_db()` (o'qish) ajratilgan holda yoziladi — replica qo'shish faqat konfiguratsiya.

---

## 11. Production tekshiruv ro'yxati

- [ ] DNS, TLS, avtomatik yangilanish
- [ ] CORS faqat ruxsat etilgan domenlar; CSP (shop sayti — bor, QA M04 U7; panellar — keyin)
- [ ] Secret'lar repo'da yo'q; kanal tokenlari DB'da shifrlangan
- [ ] Backup ishlayapti va **tiklash mashqi o'tgan** (natija yozilgan)
- [ ] Alertlar Telegram'ga keladi (sinov alerti yuborilgan)
- [ ] TC-ISO va concurrency testlari o'tgan
- [ ] NTP / vaqt sinxroni
- [ ] Huquqshunos xulosasi (DEC-013) — haqiqiy PII'dan oldin
- [ ] Telegram va Meta rasmiy ruxsatlari

Ma'lumot yoki pulga xavf tug'diradigan band bajarilmagan bo'lsa — reliz to'xtatiladi.

## 12. Xarajat va sig'imni kuzatish

CPU/RAM, disk (ayniqsa WAL va audit o'sishi), DB pool, navbat yoshi, AI xarajati (bir suhbatga), MinIO hajmi va trafik. Pilot byudjeti o'lchangan trafik va LLM ishlatilishidan hisoblanadi (`../business/14` §2.2), taxmin bilan emas.

## Keyingi qadam

→ [23-dev-setup-and-workflow.md](23-dev-setup-and-workflow.md) — lokal muhit va ish tartibi
→ [25-operations-runbooks.md](25-operations-runbooks.md) — nosozlikda nima qilish kerak
