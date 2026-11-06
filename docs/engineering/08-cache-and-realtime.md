# 08 — Kesh, rate limit va realtime (WebSocket)

> **Versiya:** v2 (2026-10-22). ADR-006 (ADR-033 bilan o'zgargan), ADR-019, ADR-023, ADR-024.
> **Kim o'qiydi:** backend dasturchilar.

## 1. Muammo

- Shop sayti ommaviy: bitta Instagram post'dan keyin yuzlab odam bir vaqtda katalogni ochadi. Har safar DB'dan o'qish — keraksiz yuk.
- Ommaviy endpoint'lar (sayt, webhook) suiiste'mol qilinishi mumkin — limit kerak.
- Operator inbox'ni yangilab o'tirmasligi kerak: yangi xabar darhol ko'rinishi kerak. API bir nechta nusxada ishlaydi — xabar qaysi nusxaga ulangan operatorga borishini bilmaymiz.

Lekin: kesh noto'g'ri narx yoki qoldiqni ko'rsatib, buyurtma shu asosida tasdiqlansa — pul yo'qotiladi.

## 2. Asosiy qoida

> **Redis — tezlashtirish va vaqtinchalik holat uchun. Haqiqat manbai — PostgreSQL.**
> Narx, qoldiq, buyurtma holati, ruxsatlar keshdan **hech qachon** tasdiqlash yoki yozish uchun olinmaydi (ADR-019).

Redis o'chsa — tizim sekinlashadi, lekin noto'g'ri ishlamaydi (`06` §6).

---

## 3. Redis tuzilishi

Bitta Redis 7 instansiya (pilot), AOF (`appendfsync everysec`), parol, faqat ichki tarmoqda.

| DB | Vazifa | Yo'qolsa |
|---|---|---|
| `0` | Kesh (storefront katalogi, sayt sozlamalari, ruxsat to'plamlari) + rate limit hisoblagichlari (`cos:v1:rl:*`) + kesh single-flight lock'lari | DB'dan qayta o'qiladi; rate limit — konservativ fallback (§5.3) |
| `1` | arq navbatlari `default` va `low` (`06`) | `app.workers.reconcile_tasks` outbox va niyat jadvallaridan tiklaydi |
| `2` | Pub/Sub (WebSocket relay) va WS ticket'lar | Dashboard REST poll'ga o'tadi |

Eslatma: Redis Pub/Sub kanallari DB raqamiga bog'liq emas (global); db2 — ticket kalitlari uchun, pub/sub ulanishi alohida client bilan ochiladi.

`maxmemory-policy`: pilotda bitta instansiya `noeviction` (navbat yo'qolmasligi uchun) va kesh kalitlari doim TTL bilan; yuklama oshsa kesh (db0) alohida `allkeys-lru` instansiyaga ko'chiriladi. Xotira 70% dan oshsa — alert (`09`).

---

## 4. Kesh

### 4.1 Kalit formati

```
cos:v1:shop:{shop_id}:<domain>:<resource>:<variant>
```
Misollar:
```
cos:v1:shop:0192a0b2…:storefront:products:list:cat=gpu:sort=price:page=1:lang=uz
cos:v1:shop:0192a0b2…:storefront:product:slug=rtx-4060-msi:lang=uz
cos:v1:shop:0192a0b2…:storefront:site:settings
cos:v1:shop:0192a0b2…:storefront:index_version              # invalidatsiya hisoblagichi
cos:v1:global:storefront:slug=techzone                      # slug → shop_id
```
- **`shop_id` prefiksi majburiy** (`shared/cache/keys.py` boshqacha kalit qurishga yo'l qo'ymaydi). Bir shop kaliti boshqasiga hech qachon to'g'ri kelmaydi.
- Kalitda foydalanuvchi kiritgan xom matn yo'q — normallashtirilgan va hash'langan parametrlar.
- `v1` — format o'zgarsa `v2`, eski kalitlar TTL bilan o'ladi.

**4-modulda qurilgani** (`app/shared/cache/`: `Cache` — Redis yoki xotira, `keys.py` — kalit quruvchi; storefront kalitlari — `app/domains/storefront/common.py`):
- `cos:v1:global:storefront:<hash(slug)>` → shop_id (600 s); shop holati esa har so'rovda bazadan;
- `cos:v1:shop:{id}:storefront:site`, `…:pages` (300 s) — sayt yoki sahifa saqlanganda darhol `DEL`;
- `…:storefront:products:list:<hash(v, cat, q, sort, limit, cursor)>`, `…:product:<hash(v, id)>`, `…:categories:<hash(v)>` (60 s + 0–10 s jitter); `v` — `…:storefront:index_version` (sayt saqlanganda `INCR`; katalog va ombor event'lari bilan — S0-06);
- mahsulot kaliti slug emas, **id** bo'yicha (storefront.md §5); mahsulot sahifasi keshdan berilsa ham holati har safar tekshiriladi;
- stampede himoyasi (§4.4) hali yo'q — pilot hajmida kerak emas, yuklama oshganda qo'shiladi;
- kesh ishlamasa (Redis uzildi) javob baribir DB'dan to'g'ri chiqadi — xato logga yoziladi, foydalanuvchiga chiqmaydi;
- **kesh faqat backend'da.** Sayt ilovasi (Next.js) API'ni `no-store` bilan o'qiydi: Next'ning "stale-while-revalidate" keshi kam tashrifli shopda ro'yxat va ma'lumot sahifalarini soatlab eskirtirardi (QA M04 U3, U5). Ega saqlagan narsa saytda darhol (backend keshi saqlanganda tozalanadi).

### 4.2 Nima keshlanadi

| Ma'lumot | Kim o'qiydi | TTL | Invalidatsiya event'i |
|---|---|---|---|
| Sayt katalog ro'yxati (sahifalangan) | xaridor (storefront) | 60 s + jitter 10 s | `catalog.product.published|hidden|archived`, `catalog.price.changed`, `catalog.exchange_rate.updated`, `commerce.stock.changed`, `catalog.import.completed` |
| Mahsulot sahifasi | xaridor | 60 s + jitter | o'sha mahsulot/SKU event'lari |
| Sayt sozlamalari (logo, kontaktlar, filiallar, ish vaqti) | xaridor | 300 s | `storefront.site.updated` (ichki), `platform.shop.suspended` |
| `slug → shop_id` | storefront router | 600 s | slug o'zgarsa (kam) |
| Xodimning ruxsat to'plami | `require_permission` | 60 s | `platform.staff.access_revoked`, rol o'zgarishi — kalit darhol o'chiriladi |
| Valyuta kursi (ko'rsatish uchun) | storefront | 300 s | `catalog.exchange_rate.updated` |

**Keshlanmaydi:**
- Dashboard (xodim) ro'yxatlari — buyurtmalar, inbox, qoldiq: DB'dan (indekslar bilan, `07`).
- Buyurtma tasdiqlash, tez sotuv, taklif tasdiqlash — har doim `FOR UPDATE` bilan DB'dan (`12`).
- AI tool'lari javoblari — `CatalogQueryPort`/`CommerceQueryPort` DB'dan o'qiydi va `as_of` vaqtini qaytaradi; AI eskirgan narxni aytmasligi uchun (`14`).
- Har qanday yozish (`POST`, `PATCH`).

### 4.3 Invalidatsiya

Ro'yxat kalitlari ko'p (filtr × sahifa × til) — har birini o'chirish o'rniga **versiya hisoblagichi**:
```
storefront subscriber (inline, 05 §5.1):
  on catalog.price.changed / commerce.stock.changed / ...:
      INCR cos:v1:shop:{shop_id}:storefront:index_version
ro'yxat kaliti = ...:products:list:v={index_version}:...
```
Eski versiyadagi kalitlar TTL bilan o'ladi. Bitta mahsulot sahifasi — to'g'ridan-to'g'ri `DEL`.

Mahsulot `HIDDEN`/`ARCHIVED` yoki shop `SUSPENDED` bo'lsa — kesh kechikishi bilan ham ko'rinmasligi uchun storefront API **o'qish paytida** ham holatni tekshiradi (sahifani keshdan bersa-da, buyurtma so'rovi `commerce` da DB'dan qayta tekshiriladi).

### 4.4 Stampede himoyasi

Kesh bir vaqtda tugasa, 300 so'rov birdaniga DB'ga ketmasligi uchun — single-flight (`shared/cache/stampede.py`):
```
miss → SET lock_key NX PX 3000
   ├─ lock olindi → DB'dan o'qish → SET value → DEL lock
   └─ lock yo'q → 50 ms kutib keshni qayta o'qish (maks 3 marta) → bo'lmasa DB'dan
```
Qo'shimcha: TTL jitter, va tugashiga 10% qolganda fonda yangilash (probabilistic early refresh) — faqat katalog ro'yxati uchun.

### 4.5 Narx va qoldiqni ko'rsatish

Saytda ko'rsatilgan qoldiq — "taxminiy" (60 s gacha eski). Xaridor buyurtma so'rovi yuborganda `commerce` uni DB'dan qayta tekshiradi; mos kelmasa — xaridorga "mahsulot qolmagan / narx o'zgardi" (`409 INSUFFICIENT_AVAILABLE_STOCK` / `PRICE_CHANGED`). Operator tasdiqlashda yana bir marta lock ostida tekshiriladi (`12`).

Qanday ko'rsatilishini shop tanlaydi (founder qarori, 2026-10-22) — `platform.shop_policies.stock_display`:
- `EXACT` — aniq son ("5 ta bor");
- `STATUS_ONLY` (default) — faqat "bor / kam qoldi / yo'q" (`low_stock_threshold` dan kam bo'lsa "kam qoldi").

Sozlama `storefront.public_products` proyeksiyasida (`available_qty` faqat `EXACT` da to'ldiriladi) va AI javoblarida (`14` §4) qo'llanadi. Sozlama o'zgarsa — `platform.shop.policy_changed` (`05` §8.6), storefront proyeksiyani qayta hisoblaydi va keshni tozalaydi.

---

## 5. Rate limit

### 5.1 Surface bo'yicha (ADR-024)

| Surface | Kalit | Limit (boshlang'ich) | Oshsa |
|---|---|---|---|
| `/api/v1/storefront/{slug}/*` (o'qish) | IP + shop | 120/daq | `429 RATE_LIMITED` + `Retry-After` |
| `/api/v1/storefront/{slug}/*` (o'qish, sayt serverining o'zi — ishonchli proksi, xaridor IP'sisiz) | shop (`sf-ssr:{slug}`) | `STOREFRONT_SSR_READ_LIMIT_PER_MINUTE` (3000) | Alohida chelak: SSR chaqiruvlari xaridorlar limitini, xaridorlar SSR'ni to'xtatmaydi (QA M04 U1) |
| `POST /storefront/{slug}/order-requests` | IP + shop, telefon hash | 5/10 daq | 429 |
| `/api/v1/storefront/{slug}/chat/*` (sayt chati) | sessiya + IP | 20 xabar/daq | 429; xabar saqlanmaydi |
| `/api/v1/webhooks/telegram/{bot_id}` | bot | 50/s (Telegram o'zi limitlaydi) | 429 emas — qabul qilinadi, lekin AI navbati throttle |
| `/api/v1/webhooks/meta` | sahifa | 50/s | xuddi shunday |
| `/api/v1/shop/*` | xodim | 300/daq | 429 |
| `POST /api/v1/auth/login` | IP + login | 5/15 daq, keyin eksponensial blok | 429, audit |
| `/api/v1/platform/*` | admin | 60/daq | 429 |

Nginx'da qo'shimcha IP limit va so'rov hajmi limiti (body ≤ 1 MB; import fayllari — alohida endpoint, ≤ 20 MB) — `22`.

### 5.2 Algoritm

Token bucket (Lua skript, atomik) Redis db0 da; kalit `cos:v1:rl:{surface}:{scope}:{id}`. Javob sarlavhalari: `X-RateLimit-Limit`, `X-RateLimit-Remaining`, `Retry-After`. Xato formati K-07: `{"error":{"code":"RATE_LIMITED","details":{"retry_after_seconds":30},...}}` (`11`).

### 5.3 Redis ishlamasa

- `auth/login` va `order-requests` — **fail closed** emas, balki jarayon ichidagi (in-memory, har nusxa) qattiqroq limit (yarmi); suiiste'mol xavfi past, xizmat to'xtamaydi.
- Webhook'lar — limitsiz qabul qilinadi (provayder o'zi limitlaydi), AI navbati `06` §7 bo'yicha.
- Hodisa log va alert'ga yoziladi.

### 5.4 Tashqi provayder limitlari (chiquvchi)

Telegram (bitta chatga ~1 xabar/s, bot bo'yicha ~30/s), Meta (sahifa bo'yicha) — `channel_send` ichida shop-kanal bo'yicha throttle (`13`). LLM — shop va global token/daqiqa limiti (`14`, DEC-119).

---

## 6. Realtime — WebSocket inbox

### 6.1 Nima uchun

Operator va menejer dashboard'da quyidagilarni darhol ko'rishi kerak: yangi xabar, suhbat operatorga uzatildi, yangi buyurtma qoralamasi, buyurtma holati o'zgardi, vazifa/eslatma. WebSocket — **faqat signal**: haqiqat REST'da.

### 6.2 Ulanish va auth (ADR-023)

```
1. Dashboard (JWT bilan):  POST /api/v1/shop/realtime/ticket  → {"ticket": "...", "expires_in": 30}
2. Brauzer:                 wss://api.<platforma>.uz/ws/v1/inbox?ticket=...
3. Server:                  ticket Redis db2 dan olinadi va o'chiriladi (bir martalik, 30 s);
                            principal, shop_id, rollar, filiallar DB'dan qayta tekshiriladi
4. Ulanish obunalari:       shop:{shop_id}:staff:{principal_id}
                            shop:{shop_id}:branch:{branch_id}   (ruxsat etilgan filiallar)
                            shop:{shop_id}:managers             (menejer/ega bo'lsa)
```
- JWT URL'da yuborilmaydi — faqat qisqa ticket.
- Access token yangilanganda yoki rol o'zgarganda (`platform.staff.access_revoked`) server ulanishni yopadi (`4401`), klient yangi ticket oladi.
- Har 30 s ping; javob bo'lmasa ulanish yopiladi.

### 6.3 Ko'p nusxada tarqatish (Redis pub/sub relay)

```
Domen service / subscriber ──(COMMIT'dan keyin)──▶ realtime.publish(channel, message)
        │
        ▼
Redis PUBLISH cos:v1:rt:shop:{shop_id}:staff:{id}
        │
        ▼
Har API nusxasidagi pubsub_relay ──▶ shu nusxadagi mos ulanishlarga yuboradi
```
- `realtime.publish` faqat COMMIT'dan keyin chaqiriladi (yoki outbox subscriber ichidan) — bekor qilingan tranzaksiya signal yubormaydi.
- Pub/sub yo'qotishi mumkin — shuning uchun har xabarda `sequence` bor va klient bo'shliqni REST'dan to'ldiradi.
- **Hech qachon** shop bo'yicha keng kanalga ruxsatsiz ma'lumot yuborilmaydi: operator faqat o'ziga biriktirilgan suhbat va buyurtmalar signalini oladi (`../business/04`: "O'ziniki").

### 6.4 Xabar formati

```json
{
  "type": "conversation.message_received",
  "shop_id": "0192a0b2-...",
  "resource": {"kind": "conversation", "id": "0192f3...", "version": 18},
  "sequence": 10452,
  "summary": {"channel": "TELEGRAM", "unread": 3},
  "trace_id": "4bf92f3577b34da6a3ce929d0e0e4736"
}
```
- Xabar matni va xaridor shaxsiy ma'lumoti WS orqali **yuborilmaydi** — klient `GET /api/v1/shop/conversations/{id}/messages?after=…` bilan oladi.
- Turlar: `conversation.message_received`, `conversation.assigned`, `conversation.handed_off`, `order.drafted`, `order.status_changed`, `task.created`, `channel.status_changed`, `ai.quota_warning`.

### 6.5 Qayta ulanish

Klient oxirgi `sequence` ni saqlaydi; qayta ulanganda `GET /api/v1/shop/realtime/changes?since_sequence=…` (yoki ro'yxatlarni qayta yuklaydi). WS yagona haqiqat manbai emas — signal yo'qolsa ham ma'lumot yo'qolmaydi.

### 6.6 Storefront chati (xaridor)

Sayt chati vidjeti uchun **SSE** (`GET /api/v1/storefront/{slug}/chat/sessions/{session_id}/events`) — anonim sessiya tokeni bilan, xabar yuborish oddiy `POST …/chat/messages`; SSE uzilsa `GET …/chat/messages?after=` polling. Nega SSE: anonim mehmon uchun ticket kerak emas, bir tomonlama oqim yetarli, nginx orqali oddiy; xabarlar `messaging` da boshqa kanallar kabi (`13`). Xaridor WS'i alohida, xodim kanallariga hech qanday aloqasi yo'q.

---

## 7. Kuzatuv

| Metrika | Alert |
|---|---|
| `cos_cache_requests_total{cache, result="hit|miss|stale"}` | storefront hit rate < 60% (yuklama bo'lsa) |
| `cos_cache_stampede_wait_total` | — |
| `cos_rate_limited_total{surface}` | to'satdan o'sish |
| `cos_redis_memory_used_ratio` | > 0.7 |
| `cos_ws_connections{instance}` | — |
| `cos_ws_messages_sent_total{type}` | — |
| `cos_ws_relay_lag_seconds` | p95 > 1 s |

## 8. Testlar

1. Kesh kaliti `shop_id` siz qurilsa — `keys.py` xato beradi (unit test).
2. A shop sayti keshida B shop mahsuloti hech qachon yo'q (TC-ISO, kesh kalit to'qnashuvi testi).
3. Narx o'zgargach 1 s ichida `index_version` oshadi; eski sahifa TTL ichida ko'rinishi mumkin, lekin buyurtma so'rovi yangi narx bilan tekshiriladi.
4. Mahsulot `HIDDEN` → storefront ro'yxatida yo'q, havola "mavjud emas" (UAT-M07).
5. 300 ta parallel miss → DB'ga 1 ta so'rov (stampede testi).
6. WS: operator A ga biriktirilgan suhbat signali operator B ga bormaydi.
7. WS ticket ikki marta ishlatilsa — rad etiladi.
8. Redis o'chirildi → login va order-request ishlaydi (fallback limit), dashboard poll'ga o'tadi.

## Keyingi qadam

→ [09-observability.md](09-observability.md) — loglar, metrikalar, alertlar
→ [12-concurrency-and-transactions.md](12-concurrency-and-transactions.md) — nega tasdiqlash keshdan o'qimaydi
