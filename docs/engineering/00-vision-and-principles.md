# 00 — Vision va buzilmas prinsiplar

> **Versiya:** v2 (2026-10-22). Standart: `bismuth_platform_v2/docs/v2` (DEC-125).
> **Kim o'qiydi:** hamma dasturchi, AI yordamchi bilan ishlaganda ham.

## 1. Vision (3 jumlada)

> AI Commerce OS — **bitta backend, ko'p shop**. Har bir shop (tenant) ma'lumotlari boshqasidan qat'iy ajratilgan, har biznes yo'nalishi (katalog, savdo, suhbatlar, AI, hisobot) o'z domenida mustaqil ishlaydi, lekin bitta auth, bitta audit, bitta deployment ostida. **Yangi domen qo'shish — 1–2 kun**, kerak bo'lsa **alohida servisga ajratish — kod buzmasdan**.

Biznes tomoni — `../business/01`. Bu hujjat — kod qanday yozilishi haqida.

---

## 2. 15 ta buzilmas prinsip

Bu qoidalar **CI'da avtomatik tekshiriladi** (import-linter, arxitektura testlari, TC-ISO). Buzilsa — build fail. 1–12 bismuth v2 dan, 13–15 shu loyihaga xos.

### Qatlam qoidalari

**1.** `app/shared/` — hamma import qila oladi, lekin u **hech kimni import qilmaydi**.
*Sabab:* circular dependency ildizini kesish.

**2.** `app/platform/` — `shared` va boshqa `platform` modullarini import qiladi, **`domains` ni import qilmaydi**.
*Sabab:* platform domenlardan mustaqil.

**3.** `app/domains/<X>/` — `shared` va `platform` ni import qiladi, **boshqa `domains/<Y>` ni import qilmaydi**.
*Sabab:* domenlar bir-birini bilmaydi → alohida servisga ajratish oson.

### Aloqa qoidalari

**4.** **Domen ↔ domen yozish faqat event orqali** (outbox). O'qish — faqat read-only **Query Port** orqali (`app/shared/contracts/`). To'g'ridan-to'g'ri funksiya chaqirish, ORM import, ichki HTTP — TAQIQ (DEC-126, ADR-032).
*Sabab:* loose coupling.

**5.** **Cross-schema JOIN va FK — TAQIQ.** Boshqa domendagi obyekt faqat `UUID` sifatida saqlanadi.
*Sabab:* schema izolyatsiyasi (ADR-035).

**6.** **State change har doim outbox bilan.** Holat o'zgarishi + `outbox_events` yozuvi — bitta DB tranzaksiyada.
*Sabab:* event yo'qolmasin.

### Domen ichidagi qoidalar

**7.** **Status faqat service ichidagi state machine orqali o'zgaradi** (`platform/use.validate_transition` + `log_transition`). Repository `status='X'` yozmaydi.
*Sabab:* transition log, audit, event bir joyda. Holatlar manbai — `../business/05`.

**8.** **Repository — faqat DB so'rovlari.** Biznes qoida repository'ga tushmaydi.

**9.** **Service — stateless.** Konstruktorda faqat dependency'lar; session method argumenti; class field'da holat yo'q.
*Sabab:* 1 → N worker.

### Ishonchlilik qoidalari

**10.** **Har yozish amali `Idempotency-Key` bilan.** Bir xil buyruq 2 marta kelsa — bir marta bajariladi (K-06).

**11.** **Har so'rov `trace_id` ko'taradi.** HTTP → service → DB → outbox → worker → Telegram — hammasida bitta ID.

**12.** **Fon vazifasi — distributed lock bilan.** 4 worker bo'lsa ham bitta rejali ish 1 marta ishlaydi (ADR-033).

### Shu loyihaga xos qoidalar

**13.** **`shop_id` hech qachon klientdan olinmaydi.** U faqat server tomonida, autentifikatsiya va a'zolikdan aniqlanadi (`ActorContext`). Har shop jadvalida `shop_id NOT NULL`; sezgir jadvallarda RLS (DEC-002, `10-security-tenancy-rbac.md`).
*Sabab:* bir shop ma'lumoti boshqasiga ko'rinmasin (TC-001, TC-ISO).

**14.** **AI hech qachon haqiqat manbai emas.** Narx, qoldiq, moslik, buyurtma holati — faqat domen service'laridan. AI faqat Query Port orqali o'qiydi va faqat event orqali **qoralama** so'raydi (DEC-100c).
*Sabab:* AI xatosi qimmatga tushadi (BD-06).

**15.** **Pul — butun son, minor units.** `amount_minor BIGINT` + valyuta; float TAQIQ (ADR-025).

---

## 3. Anti-prinsiplar (nima qilinmaydi)

| ❌ Anti-pattern | Nega TAQIQ |
|---|---|
| God service (1000+ qator) | Test va o'zgartirish qiyin |
| Domenlar orasida sync HTTP | Bitta domen yiqilsa, hammasi to'xtaydi |
| Global mutable state (dict, class field) | Race condition, scaling yo'q |
| ORM modelni API javobi sifatida qaytarish | Ichki maydon chiqib ketadi, N+1 |
| Yashirin side-effect (signal, decorator zanjiri) | Oqim ko'rinmaydi |
| Tranzaksiya ichida tashqi chaqiruv (LLM, Telegram, HTTP) | Lock uzoq ushlanadi, deadlock |
| Logga katta JSON yoki shaxsiy ma'lumot yozish | Disk to'ladi, PII sizib chiqadi |
| `SELECT *`, limitsiz ro'yxat | Bandwidth, index ishlamaydi |
| Klientdan kelgan `shop_id`, `role`, `branch_id` ga ishonish | Tenant izolyatsiyasi buziladi |
| LLM'ga erkin SQL yozdirish | Ruxsat va aniqlik nazoratsiz |

---

## 4. Muvaffaqiyat mezonlari (pilot uchun maqsad)

Raqamlar — maqsad, isbotlangan emas. Pilotda o'lchanadi (`09-observability.md`).

| Metrika | Maqsad | Qachon o'lchanadi |
|---|---|---|
| API p95 (o'qish) | < 300 ms | Doimiy |
| API p95 (yozish) | < 500 ms | Doimiy |
| Webhook ACK (Telegram/Meta) | < 1 s (AI'siz) | Doimiy |
| AI birinchi javob (p90) | < 15 s | Doimiy |
| Outbox → consumer kechikishi (p99) | < 2 s | Tracing |
| Rejali ish kechikishi | < 30 s | Scheduler metrikasi |
| Eng eski navbat vazifasi yoshi | < 120 s | Alert |
| Bir shop ma'lumoti boshqasiga ko'rinishi | 0 | TC-ISO, har reliz |
| Ikki marta sotish | 0 | TC-002, TC-027 |
| Uptime | 99.5% | Status sahifasi |
| Yangi domen qo'shish | 1–2 kun | Qo'lda |

---

## 5. Texnologiyalar (baseline)

Bu tanlovlar ADR'siz o'zgartirilmaydi.

| Qatlam | Tanlov | Sabab | ADR |
|---|---|---|---|
| Web framework | FastAPI | Async, OpenAPI | ADR-001 |
| Validatsiya | Pydantic v2 | FastAPI bilan native | — |
| ORM | SQLAlchemy 2.0 async + asyncpg | Yetuk, aniq tranzaksiyalar | ADR-004 |
| DB | PostgreSQL 16, schema per domain | JSONB, advisory lock, RLS | ADR-002, ADR-035 |
| Migratsiya | Alembic (har schema uchun env) | SQLAlchemy native | ADR-035 |
| Kesh, rate limit, navbat | Redis 7 (AOF) | Pub/Sub, TTL, arq | ADR-006, ADR-033 |
| Fon vazifalari | arq + outbox | Async-native, yengil | ADR-033 |
| Rejali ishlar | APScheduler + advisory lock | Bitta leader | ADR-033 |
| Fayllar | S3-compatible (MinIO, UZ serverda) | DB'ga blob yozilmaydi | ADR-014, ADR-030 |
| Loglar | structlog (JSON, contextvars) | `trace_id` har qatorda | ADR-029 |
| Tracing va metrika | OpenTelemetry → Grafana Cloud | Boshqarish kerak emas | ADR-029, DEC-012 |
| Xatolar | Sentry | — | ADR-029 |
| LLM | `LLMPort` adapter, default nomzod Claude Sonnet (bake-off) | Provayderdan mustaqil | ADR-027 |
| Import chegaralari | import-linter | CI'da tekshiruv | ADR-031 |
| Test | pytest + pytest-asyncio, testcontainers | Haqiqiy PostgreSQL | — |
| Frontend | Next.js, alohida repo | `21-frontend.md` | ADR-010 |

---

## 6. Ongli murosalar (trade-off'lar)

### 1. Domenlar orasida eventual consistency
**Tanlov:** AI "olaman" desa, buyurtma qoralamasi event orqali 100–500 ms da paydo bo'ladi.
**Foyda:** domen izolyatsiyasi. **Narx:** UI'da "yaratilmoqda" holati.
**Muhim:** pul va qoldiqqa tegadigan invariant (tasdiqlash + band qilish) **bitta domen ichida, bitta tranzaksiyada** (`commerce`, DEC-126). Eventual consistency faqat xavfsiz joylarda.

### 2. Boilerplate ko'p
**Tanlov:** har domen uchun `api/`, `services/`, `repository/`, `models/`, `state_machine.py`.
**Foyda:** mustaqillik. **Narx:** ko'proq fayl. Ko'p kod ≠ yomon kod, agar har biri o'z mas'uliyatida bo'lsa.

### 3. `commerce` domeni kattaroq
**Tanlov:** ombor, band qilish, buyurtma, tez sotuv, lead va PC taklif bitta domenda.
**Foyda:** ikki marta sotish xavfi yo'q, saga kerak emas. **Narx:** domen ichida intizom kerak (sub-modullar: `inventory/`, `orders/`, `quotes/`, `leads/`).

### 4. Redis — majburiy servis
**Tanlov:** navbat arq'da (Redis). **Narx:** Redis o'chsa navbat to'xtaydi. **Himoya:** vazifa faqat outbox orqali navbatga tushadi — Redis qaytganda outbox qayta yuboradi, hech narsa yo'qolmaydi.

### 5. Read replica va PgBouncer — hozir yo'q
Pilot hajmida bitta PostgreSQL yetadi. Kod `get_db()` / `get_read_db()` ajratilgan holda yoziladi — keyin replica qo'shish konfiguratsiya o'zgarishi bo'ladi (`07-data-layer.md`).

---

## 7. Hujjat yangilash tartibi

Bu hujjatlar tirik:
1. Arxitektura o'zgarishi — avval ADR (`ADR/ADR-XXX-title.md`, shablon `ADR/_template.md`).
2. Founder qarori — `../decisions/DECISION_REGISTER.md` da `CHANGED (sana): eski → yangi`.
3. Tegishli hujjat va `../modules/<domain>/README.md` yangilanadi.
4. PR'da `arch-change` belgisi.

## 8. Keyingi qadam

→ [01-architecture-overview.md](01-architecture-overview.md) — qatlamlar, domenlar, oqimlar
→ [02-folder-skeleton.md](02-folder-skeleton.md) — papka tuzilmasi
