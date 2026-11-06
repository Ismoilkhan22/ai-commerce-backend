# M08 — Serverga chiqarish (deploy va monitoring)

> **Holat:** tayyorlandi (2026-10-27), hali hech qaysi serverga o'rnatilmagan. Commit qilinmagan — founder ko'rib chiqishi kutilmoqda.
> **Reja:** [27-roadmap-and-tasks.md](../27-roadmap-and-tasks.md) — S0-05 (kuzatuv: loglar, Sentry), S0-10 (deploy, backup), TD-03 (S3 fayl ombori).
> **Texnik tafsilot:** [22-infrastructure-and-deployment.md](../22-infrastructure-and-deployment.md) §3.1–3.2, tiklash — [25](../25-operations-runbooks.md) RB-08.
> **Kim o'qiydi:** founder (serverni o'zi ko'taradi) va dasturchilar.

---

## 1. Nima bitdi — qisqacha

Tizimni bitta ijaraga olingan serverda (VPS) ishga tushirish uchun hamma narsa tayyor: dastur "qutilari" (Docker image), ularni birga ko'taradigan bitta fayl, HTTPS, har kuni avtomatik backup va xatolarni kuzatish.

```
Xaridor / xodim ──HTTPS──▶ nginx (qulf: TLS sertifikati) ──▶ panel.   → shop paneli
                                                         ├─▶ admin.   → platforma paneli
                                                         ├─▶ {shop}.  → shop sayti
                                                         └─▶ api.     → backend ──▶ PostgreSQL, Redis
                                                                         ↑
                                     fon ishlari: outbox-worker · task-worker · scheduler
Har kuni 03:00 ──▶ backup ──▶ /var/backups/commerce-os (14 kun) ──▶ (siz sozlaysiz) boshqa joyga nusxa
Xato bo'lsa ──▶ Sentry (shaxsiy ma'lumotsiz) ──▶ sizga email
```

---

## 2. Rejadagi bandlar

- [x] **Backend image** — bitta image, buyruqlar: `api`, `outbox-worker`, `task-worker`, `scheduler`, `migrate` (Makefile bilan bir xil). Root emas, faqat o'qiladigan disk.
- [x] **Frontend image** — bitta Dockerfile, uchta app (`APP` build arg), Next.js standalone, root emas.
- [x] **`deploy/docker-compose.prod.yml`** — PostgreSQL, Redis, backup, migrate (bir martalik), API, 3 ta fon jarayoni, 3 ta frontend, nginx, certbot.
- [x] **nginx** — domenlar bo'yicha yo'naltirish, HTTPS, logda query string yo'q, XFF to'g'ri, yuklash chegaralari, WebSocket, xavfsizlik sarlavhalari.
- [x] **S3 fayl ombori** — `app/platform/storage/s3.py` (TD-03 yopildi; 2-bandga qarang — `main.py` ulanishi qoldi).
- [x] **Kuzatuv** — JSON loglar (`service`, `env`, `version` maydonlari bilan), Sentry backend va frontend'da (faqat DSN berilsa), `/health/live`, `/health/ready`.
- [x] **Backup** — har kuni `pg_dump`, 14 kun, tiklash qadamlari 25 RB-08 da (lokalda sinab ko'rildi).
- [x] **CI** — backend: `make check` + image + compose/nginx tekshiruvi; frontend: `pnpm check` + 3 ta build + image.

**Ataylab keyinga qoldirilgan:**
- Prometheus `/metrics` va Grafana Cloud — hozircha health endpoint'lar + loglar + Sentry yetadi (09 bo'yicha OTel keyin).
- WAL/PITR (soatlik tiklash nuqtasi) — hozir kunlik backup, ya'ni eng yomon holatda bir kunlik ma'lumot yo'qoladi. Haqiqiy savdo boshlanganda qo'shiladi.
- Image registry (GHCR) va staging — hozir image'lar serverning o'zida build qilinadi.

**Kartadan farqlar va ochiq qolganlar:**
- **`app/main.py` hali lokal diskni ishlatadi.** S3 adapter tayyor, sozlamalar tayyor, lekin `main.py` va seed skriptlari boshqa ish ketayotgan fayllar — men tegmadim. Bitta qator o'zgarishi kerak: `storage=LocalDiskStorage(Path(settings.storage_local_dir))` → `storage=build_file_storage(settings.storage_config())` (import: `from app.platform.storage.config import build_file_storage`). Shu qilinmaguncha fayllar `storage` volume'da (diskda) saqlanadi — bu ham ishlaydi, backup'ga esa kirmaydi.
- **Band slug'lar yo'q:** shop slug'i `api`, `panel`, `admin` yoki `www` bo'lsa, uning sayti ochilmaydi (bu nomlar panellarga band). Backend'da shunday slug'larni rad etish kerak.

---

## 3. Fayllar xaritasi

```
ai-commerce-backend/
├── deploy/
│   ├── docker/Dockerfile                 # backend image (uv, python:3.12-slim, foydalanuvchi app)
│   ├── docker/entrypoint.sh              # `cos api | outbox-worker | task-worker | scheduler | migrate`
│   ├── docker-compose.prod.yml           # butun tizim bitta serverda
│   ├── .env.prod.example                 # domen, versiya (tag), postgres paroli
│   ├── app.env.example                   # backend sozlamalari: kalitlar, S3, Gemini, Sentry
│   ├── nginx/nginx.conf                  # asosiy nginx sozlamasi (query'li standart log o'chirilgan)
│   ├── nginx/templates/default.conf.template  # domenlar, HTTPS, chegaralar
│   ├── nginx/snippets/                   # proxy (XFF), xavfsizlik sarlavhalari, TLS, admin IP ro'yxati
│   ├── nginx/40-reload-loop.sh           # 6 soatda nginx yangi sertifikatni oladi
│   ├── backup/pg_backup.sh               # kunlik backup + eskisini o'chirish + tekshiruv
│   ├── backup/entrypoint.sh              # backup jadvali (cron, 03:00)
│   └── secrets/cloudflare.ini.example    # sertifikat uchun Cloudflare tokeni
├── app/platform/storage/s3.py            # S3-mos fayl ombori
├── app/platform/storage/config.py        # qaysi ombor (local / s3) — sozlamadan
├── app/config/observability.py           # Sentry: faqat DSN bo'lsa, shaxsiy ma'lumot tozalanadi
├── app/config/logging.py                 # JSON logga service/env/version + Sentry ishga tushishi
├── app/config/settings.py                # yangi sozlamalar: S3_*, SENTRY_*, SERVICE_NAME, APP_VERSION
├── tests/unit/test_s3_storage.py         # S3 adapter (moto bilan)
├── tests/unit/test_observability_sentry.py  # Sentry tozalash, log maydonlari
└── .github/workflows/ci.yml              # backend CI
ai-commerce-frontend/
├── Dockerfile, .dockerignore             # uchala app uchun bitta
├── apps/*/next.config.ts                 # output: "standalone"
├── apps/*/src/instrumentation.ts         # server Sentry (faqat DSN bo'lsa)
├── apps/*/src/instrumentation-client.ts  # brauzer Sentry (faqat DSN bo'lsa)
├── packages/app-kit/src/sentry.ts        # Sentry uchun shaxsiy ma'lumot tozalash
└── .github/workflows/ci.yml              # frontend CI
```

---

## 4. Serverga chiqarish — founder uchun qo'llanma

### 4.1 Nima kerak (sizdan)

- **VPS** — O'zbekistondagi data center'da (shaxsiy ma'lumot qonuni, DEC-013). Pilot uchun: **4 vCPU, 8 GB RAM, 160 GB SSD (NVMe)**, Ubuntu 24.04. Bu 1–5 shop uchun yetadi; PostgreSQL ~2 GB, qolgan jarayonlar ~4 GB oladi.
- **Domen** — masalan `platforma.uz` (quyida shu nom; o'zingiznikiga almashtiring).
- **Cloudflare hisobi (bepul)** — faqat DNS uchun. Sabab: har shop sayti `noutbukuz.platforma.uz` kabi alohida manzil; bitta "hammasi uchun" (wildcard) sertifikatni faqat DNS orqali olish mumkin, certbot buni Cloudflare orqali avtomatik qiladi. Trafik Cloudflare orqali **o'tmaydi** (kulrang bulut, "DNS only").
- **S3-mos fayl ombori** O'zbekistonda (rasm, import fayllari): endpoint manzili, access key, secret key, bitta yopiq bucket (masalan `cos-private`).
- **Gemini API kaliti** — pullik tarif (bepul kalit production'da rad etiladi). Yoki hozircha `LLM_PROVIDER=fake` (AI o'chiq).
- **Sentry hisobi** (ixtiyoriy, bepul tarif yetadi) — ikkita loyiha: backend va frontend, har biridan DSN.
- **Backup uchun ikkinchi joy** — boshqa UZ server yoki S3 bucket (VPS diski o'lsa backup ham yo'qolmasin).

### 4.2 DNS yozuvlari (Cloudflare'da, hammasi "DNS only" — kulrang bulut)

```
A   platforma.uz          → <VPS IP>
A   api.platforma.uz      → <VPS IP>
A   panel.platforma.uz    → <VPS IP>
A   admin.platforma.uz    → <VPS IP>
A   *.platforma.uz        → <VPS IP>     # hamma shop saytlari
```

Domen registratorida (`.uz` sotgan joy) nameserver'larni Cloudflare bergan ikkita manzilga almashtiring. Cloudflare'da API token yarating: faqat "Zone → DNS → Edit", faqat `platforma.uz` zonasi.

**Muhim:** bulutni sariq (proxied) qilmang — unda mijoz IP'si o'zgaradi va har mehmonning so'rov chegarasi buziladi.

### 4.3 .env qiymatlari

Ikki fayl, ikkalasi ham serverda, hech qachon git'ga kirmaydi:

- `deploy/.env.prod` — domen, versiya, postgres paroli.
- `deploy/app.env` — backend sozlamalari.

Tasodifiy kalit yaratish: `openssl rand -base64 48`. Har kalit — alohida.

**`deploy/.env.prod`:**
- `PLATFORM_DOMAIN=platforma.uz`
- `BACKEND_TAG`, `FRONTEND_TAG` — har repo'da `git rev-parse --short HEAD` natijasi (versiya; qaysi kod ishlayotganini ko'rsatadi).
- `POSTGRES_PASSWORD` — uzun tasodifiy parol (faqat sozlash va backup uchun; ilova uni ko'rmaydi).
- `FRONTEND_SENTRY_DSN` — Sentry frontend loyihasi DSN'i (bo'sh — o'chiq).
- `BACKUP_HEARTBEAT_URL` — ixtiyoriy: healthchecks.io manzili; backup o'tmasa sizga xabar keladi.

**`deploy/app.env`** (namunadagi `platforma.uz` larni o'z domeningizga almashtiring):
- `DATABASE_URL`, `DATABASE_MIGRATOR_URL` — faqat `CHANGE_ME_..._pw` qismini almashtiring, har biriga 12+ belgili alohida parol.
- `JWT_SECRET`, `IDEMPOTENCY_HASH_KEY` — har biri `openssl rand -base64 48`.
- `PII_ENCRYPTION_KEYS=p1:<openssl rand -base64 32>`, `PII_HMAC_KEY=<openssl rand -base64 32>` — xaridor telefoni va manzilini shifrlaydi. **Bu kalitlarni yo'qotsangiz — shifrlangan ma'lumot qaytmaydi.** Parol menejerida ham saqlang.
- `TRUSTED_PROXIES=["172.30.0.10","172.30.0.20"]` — o'zgartirmang. Bu nginx va shop sayti serverining ichki manzillari: backend faqat ular aytgan mijoz IP'siga ishonadi.
- `STOREFRONT_TRUSTED_PROXY_HOPS=1` — `docker-compose.prod.yml` ichida allaqachon yozilgan (shop sayti nginx ortida). Olib tashlamang: aks holda hamma mehmon bitta odamdek hisoblanib, chat va sahifa chegaralari hammaga bitta bo'lib qoladi.
- `STORAGE_BACKEND=s3`, `S3_ENDPOINT_URL`, `S3_ACCESS_KEY_ID`, `S3_SECRET_ACCESS_KEY`, `S3_PRIVATE_BUCKET` (va ixtiyoriy `S3_PUBLIC_BUCKET`) — fayl ombori. Diqqat: 2-bo'limdagi `main.py` ulanishi qilinmaguncha fayllar baribir diskda.
- `LLM_PROVIDER=gemini`, `GEMINI_API_KEY=...`, `GEMINI_TIER=paid`.
- `SENTRY_DSN` — Sentry backend loyihasi DSN'i (bo'sh — o'chiq).
- `PLATFORM_TELEGRAM_BOT_TOKEN`, `PLATFORM_TELEGRAM_BOT_USERNAME`, `PLATFORM_TELEGRAM_WEBHOOK_SECRET` — xodimlarga xabar yuboradigan bot (ixtiyoriy). Production uchun alohida bot yarating.

### 4.4 Birinchi deploy — qadamlar

```
1. Server:     ssh orqali kiring → Docker o'rnating (docs.docker.com/engine/install/ubuntu)
               → SSH parolini o'chiring (faqat kalit), ufw: faqat 22, 80, 443 ochiq
2. Kod:        mkdir -p /opt/cos && cd /opt/cos
               git clone <backend repo> ai-commerce-backend
               git clone <frontend repo> ai-commerce-frontend
               cd ai-commerce-backend
3. Sozlamalar: cp deploy/.env.prod.example deploy/.env.prod
               cp deploy/app.env.example deploy/app.env
               cp deploy/secrets/cloudflare.ini.example deploy/secrets/cloudflare.ini
               chmod 600 deploy/.env.prod deploy/app.env deploy/secrets/cloudflare.ini
               → uchalasini 4.3 bo'yicha to'ldiring
4. Sertifikat (bir marta; keyin certbot o'zi yangilaydi):
               C="docker compose -f deploy/docker-compose.prod.yml --env-file deploy/.env.prod"
               $C run --rm --entrypoint certbot certbot certonly \
                  --dns-cloudflare --dns-cloudflare-credentials /run/secrets/cloudflare.ini \
                  -d platforma.uz -d '*.platforma.uz' --agree-tos -m <email> --non-interactive
5. Ishga tushirish:
               $C up -d --build          # birinchi build 10–15 daqiqa
               $C ps                     # migrate "Exited (0)", qolganlari "Up" / "healthy"
6. Tekshiruv:  curl https://api.platforma.uz/health/ready      → {"status":"ready",...}
               brauzerda https://panel.platforma.uz va https://admin.platforma.uz
7. Platforma admini (bir marta):
               $C run --rm -e PLATFORM_ADMIN_PASSWORD='<kuchli parol>' api \
                  python -m app.platform.staff.cli create-platform-admin --phone "+998..." --name "..."
8. Uptime:     UptimeRobot (bepul) → https://api.platforma.uz/health/ready har 5 daqiqada → Telegram/email
```

**Yangi versiya chiqarish:**

```
cd /opt/cos/ai-commerce-backend && git pull && cd ../ai-commerce-frontend && git pull && cd ../ai-commerce-backend
→ deploy/.env.prod'da BACKEND_TAG va FRONTEND_TAG ni yangi git SHA'ga almashtiring
$C exec backup /backup/pg_backup.sh      # migratsiyadan oldin qo'shimcha backup
$C up -d --build                         # migrate o'zi birinchi ishlaydi, keyin api va worker'lar
```

Orqaga qaytish: `.env.prod`'da eski tag'larni qo'yib `$C up -d`. Migratsiyalar orqaga qaytmaydi — eski kod yangi bazada ishlaydi (22 §6.3).

**Loglarni ko'rish:** `$C logs -f api`, `$C logs -f task-worker`, `$C logs nginx`. Batafsil — 22 §3.2.

### 4.5 Backup

- Har kuni soat 03:00 (Toshkent) `backup` konteyneri butun bazani `/var/backups/commerce-os/daily/` ga yozadi. 14 kundan eskisi o'chadi. Har faylning butunligi tekshiriladi (`.sha256`).
- Qo'lda backup: `$C exec backup /backup/pg_backup.sh`.
- Ishlayotganini ko'rish: `$C logs backup` → `backup.finished` qatori.
- **Boshqa joyga nusxa (majburiy):** server o'lsa, backup ham shu diskda. `rclone` o'rnating (`apt install rclone`), `rclone config` bilan ikkinchi joyni (UZ S3 bucket yoki boshqa server) ulang, keyin `crontab -e`:

```
30 3 * * * rclone sync /var/backups/commerce-os/daily remote:cos-backups/daily --max-age 15d
```

- **Tiklash:** [25 RB-08](../25-operations-runbooks.md) "pilot buyruqlari" — qadamma-qadam. Oyiga bir marta mashq qiling (production'ga tegmaydi), vaqtini shu yerga yozing.
- Shifrlash kalitlari (`PII_*`, `JWT_SECRET`) backup'da yo'q — ularni parol menejerida alohida saqlang. Kalitsiz backup'dagi telefon va manzillar o'qilmaydi.

---

## 5. Qaysi faylda nima bor

### Backend image va jarayonlar
- `deploy/docker/Dockerfile` — ikki bosqich: `uv sync --locked --no-dev` (faqat kerakli kutubxonalar), keyin toza `python:3.12-slim`. Kod `/app` da, foydalanuvchi `app` (uid 10001). `APP_VERSION` build arg → logdagi `version`.
- `deploy/docker/entrypoint.sh` — `migrate`: `DATABASE_ADMIN_URL` bo'lsa avval `app.db.bootstrap` (rollar, schemalar; takror ishlatish xavfsiz), keyin har schema `alembic -n <s> upgrade head` (Makefile bilan bir xil tartib). `api`: uvicorn `--no-access-log --no-proxy-headers`, ishchilar soni `WEB_CONCURRENCY` (compose'da `API_WORKERS`, standart 2).

### Compose
- `deploy/docker-compose.prod.yml` — loyiha nomi `cos-prod`. `migrate` muvaffaqiyatli tugamaguncha api va worker'lar ishga tushmaydi. Backend konteynerlari faqat o'qiladigan diskda (`/tmp` dan tashqari). Har servisga xotira chegarasi. Ichki tarmoq 172.30.0.0/24: qat'iy IP'lar (.10 nginx, .20 sayt) dinamik IP'lar bilan to'qnashmasligi uchun dinamik oraliq .128–.254.

### nginx
- `templates/default.conf.template` — kirish logi JSON, `path` = `$uri` (query'siz) va 20+ belgili token ko'rinishidagi yo'l bo'laklari `{seg}` (buyurtma holati havolasi, taklifnoma tokeni). Umumiy tana chegarasi 2 MB; `/api/v1/shop/files` — 11 MB (import 10 MB, rasm 5 MB — aniq chegara ilovada). `/api/v1/ws` — WebSocket, 1 soat. IP bo'yicha qo'pol chegara (API 20 so'rov/s). Noma'lum domen — TLS rad etiladi.
- `snippets/proxy.conf` — `X-Forwarded-For $proxy_add_x_forwarded_for`: haqiqiy IP zanjir oxiriga; `X-Request-ID` — nginx va backend logida bir xil `request_id`.
- `snippets/security-headers.conf` — HSTS, nosniff, X-Frame-Options, Referrer-Policy, Permissions-Policy (panellar va API). Shop sayti o'z sarlavhalari va CSP'sini beradi, nginx unga faqat HSTS qo'shadi.

### Fayl ombori (TD-03)
- `app/platform/storage/s3.py` — `S3FileStorage`: `put/get/delete` (port bilan bir xil), boto3 chaqiruvlari `asyncio.to_thread` da. Ochiq fayllar (mahsulot rasmi, logotip) `S3_PUBLIC_BUCKET` berilsa o'sha bucket'ga, qolgani yopiq bucket'ga. Havolalar o'zgarmadi: yopiq fayl — API orqali imzoli havola (`UrlSigner`, 5 daqiqa), ochiq fayl — `PUBLIC_FILES_URL`; bucket ommaga ochilishi shart emas. Kalit tekshiruvi lokal adapter bilan bir xil.
- `app/platform/storage/config.py` — `StorageConfig`, `build_file_storage()`; `Settings.storage_config()` yaratadi. `STORAGE_BACKEND=s3` bo'lsa bucket majburiy, kalitlar juft.

### Kuzatuv
- `app/config/observability.py` — `init_sentry()`: DSN yo'q — hech narsa. `before_send`: request'dan faqat metod va query'siz URL, `user` faqat `id`, matnda telefon/email/token niqoblanadi, kutilgan `DomainError` yuborilmaydi; HTTP breadcrumb'lar tashlanadi (Telegram manzilida bot token bor).
- `app/config/logging.py` — `configure_logging` (api va har worker chaqiradi) endi JSON qatorga `service`, `env`, `version` qo'shadi va Sentry'ni yoqadi. `main.py` va worker'larga tegilmadi.
- Frontend: `instrumentation.ts` / `instrumentation-client.ts` — `@sentry/nextjs`, faqat DSN bo'lsa; `@cos/app-kit/sentry` — URL'dan query va token bo'laklarini olib tashlaydi, header/cookie yubormaydi. Shop sayti CSP'siga Sentry manzili faqat DSN bo'lsa qo'shiladi.

---

## 6. Testlar

- `tests/unit/test_s3_storage.py` (moto, tarmoqsiz) — yozish/o'qish/o'chirish; ochiq purpose ochiq bucket'ga; ochiq bucket bo'lmasa hammasi yopiqda; yo'q kalit va ikki marta o'chirish xato emas; `..`, `/`, `\` kalitlar rad etiladi; boshqa S3 xatolari yashirilmaydi; sozlamadan adapter tanlash; to'liq bo'lmagan S3 sozlamasi ishga tushmaydi.
- `tests/unit/test_observability_sentry.py` — telefon, email, bot token, Bearer, query niqoblanadi (sana emas); request va user tozalanadi; `DomainError` yuborilmaydi; HTTP breadcrumb tashlanadi; DSN'siz Sentry o'chiq; JSON logda `service`/`version`.
- **Lokal to'liq sinov (Docker, `cos.test` domeni, o'z-o'zidan imzolangan sertifikat):** hamma 12 servis ko'tarildi, migrate `Exited (0)`; `/health/ready` → postgres ok, redis ok; panel va admin `/login` 200; noma'lum shop 404; asosiy domen → panel; 12 MB fayl → 413, 3 MB JSON → 413; WebSocket → 101; HTTP → HTTPS 301; noma'lum domen — TLS rad; nginx logida `?q=+998…` va WS ticket yo'q; nginx va API logida bir xil `request_id`; har worker logida `service`. Backup → `pg_restore` bilan bo'sh bazaga tiklandi: 159 jadval, 55 RLS siyosati, egalari (`app_migrator`) saqlangan.

---

## 7. Jarayonda topilgan muammolar

- **nginx'ning standart `nginx.conf` i query bilan log yozardi** (`access_log ... main`, `$request`). O'zimizning log qo'shilsa ham u qolardi → `deploy/nginx/nginx.conf` bilan almashtirildi.
- **`command:` bilan nginx'ni ishga tushirish shablonlarni o'chirib qo'yardi** (rasmiy entrypoint faqat `nginx` buyrug'ida `envsubst` qiladi) → reload sikli `/docker-entrypoint.d/40-reload-loop.sh` ga ko'chirildi.
- **Qat'iy IP band bo'lib qoldi** — Docker 172.30.0.10 ni boshqa konteynerga bergan edi → dinamik IP oralig'i .128–.254 bilan cheklandi.
- **`pg_dump --no-owner`** tiklangan jadvallarni `postgres` ga berib qo'yardi (migrator keyin DDL qila olmasdi) → egalik saqlanadi, rollar `globals-*.sql` dan.
- **Lokal compose bilan nom to'qnashuvi** — ikkalasi `commerce-os` bo'lsa, volume'lar (dev baza) aralashardi → prod loyiha nomi `cos-prod`.

---

## 8. Keyingi qadamga meros

- `app/main.py` (va seed'lar) `build_file_storage(settings.storage_config())` ga o'tkazilsin — shundan keyin `STORAGE_BACKEND=s3` haqiqatda ishlaydi.
- Band slug'lar (`api`, `panel`, `admin`, `www`) shop yaratishda rad etilsin.
- Yangi jarayon qo'shilsa: `entrypoint.sh` ga buyruq, compose'ga servis (`<<: *backend`, `SERVICE_NAME`), Makefile'ga maqsad — uchalasi bir xil nomda.
- Yangi sozlama qo'shilsa: `app.env.example` ga ham.
- Pilot shoplar haqiqiy savdo boshlaganda: WAL/PITR (RPO 1 soat), OTel → Grafana Cloud, alertlar (09 §7), image registry va staging.
