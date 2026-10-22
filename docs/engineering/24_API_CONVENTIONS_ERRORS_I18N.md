# TECH-24 — API konvensiyalari, xatolar va i18n

**Status:** Baseline (2026-10-22). K-01/K-02/K-06/K-07, ADR-023/024/025 asosida. "Taklif" deb belgilangan bandlar founder tasdig'isiz ham kod uchun default, lekin o'zgartirilishi mumkin.
**Bog'liq:** `08_API_CONTRACTS.md` (endpointlar), `12_OBSERVABILITY_AND_TRACING.md` §5a (middleware tartibi), `10_SECURITY_AND_RBAC.md` (ruxsatlar), `../decisions/DECISION_REGISTER.md`.

Bu hujjat backend va frontend dasturchilari uchun: API qanday javob qaytaradi, xatolar qanday tuziladi va ko'rsatiladi, matnlar qaysi tilda va kim tomonidan tarjima qilinadi.

---

## 1. Umumiy qoidalar

| Mavzu | Qoida |
|---|---|
| Yo'llar | `/api/v1/<surface>/...` (ADR-024): `merchant`, `storefront/{slug}`, `webhooks`, `platform`, `auth`, `public` |
| Format | JSON, UTF-8; maydon nomlari `snake_case` |
| Enum'lar | `UPPER_SNAKE` (K-02), qiymatlar manbai — `business/05`. Frontend noma'lum enum qiymatini `UNKNOWN` deb ko'rsatadi, xato bermaydi |
| ID'lar | UUIDv7 (vaqt bo'yicha tartiblangan), string sifatida. Ichki ID public token sifatida ishlatilmaydi |
| Vaqt | ISO-8601, UTC, `Z` bilan (`2026-10-22T09:15:00Z`). Hisobot sanalari merchant timezone'ida (`Asia/Tashkent` default) va javobda `timezone` maydoni bilan |
| Pul | `{"amount_minor": 1250000000, "currency": "UZS"}` — butun son, ISO exponent (ADR-025: UZS = 2). Float taqiqlangan. Ko'rsatish (formatlash) — frontend vazifasi |
| Tenant | `merchant_id` hech qachon so'rov tanasi yoki query'dan avtoritet sifatida olinmaydi (K-01) |
| Null va yo'q maydon | Ma'lum, lekin bo'sh qiymat — `null`. Javob sxemasidagi maydonlar har doim qaytariladi (yo'qolib qolmaydi) |

## 2. Muvaffaqiyatli javoblar (taklif)

Muvaffaqiyatli javob **envelope'siz** qaytadi: resursning o'zi yoki ro'yxat obyekti. Xato javobi esa doim `error` envelope'ida (§3). Shu farq tufayli frontend javob turini HTTP status va `error` kalitining bor-yo'qligidan aniqlaydi.

| Holat | HTTP | Tana |
|---|---|---|
| Bitta resurs (GET, PATCH, state transition) | 200 | resurs obyekti, `version` maydoni bilan |
| Yaratildi | 201 | resurs obyekti + `Location` header |
| Ro'yxat | 200 | `{"items": [...], "next_cursor": "opaque" \| null, "has_more": bool}` |
| Uzoq ish | 202 | `{"job_id", "status": "QUEUED", "status_url"}` |
| Tanasiz muvaffaqiyat | 204 | — |

```json
{
  "items": [
    {"id": "0192b6f0-…", "status": "PENDING_CONFIRMATION", "total": {"amount_minor": 450000000, "currency": "UZS"}, "version": 2}
  ],
  "next_cursor": "eyJjIjoiMjAyNi0xMC0yMlQwOToxNTowMFoiLCJpZCI6Ii4uLiJ9",
  "has_more": true
}
```

**Ro'yxat parametrlari:** `?limit=` (default 25, maks 100), `?cursor=`, filtrlar maydon nomi bilan (`?status=CONFIRMED&created_from=2026-10-01T00:00:00Z`), saralash `?sort=-created_at` (minus — kamayish bo'yicha). Offset pagination ishlatilmaydi.

## 3. Xato javoblari (K-07)

### 3.1 Envelope

Barcha surface'lar, barcha HTTP xatolar (4xx, 5xx) va FastAPI/Starlette'ning o'z xatolari ham shu formatda qaytadi:

```json
{
  "error": {
    "code": "VALIDATION_FAILED",
    "message": "Request validation failed",
    "details": {
      "fields": [
        {"field": "lines[0].quantity", "code": "min_value", "params": {"min": 1}},
        {"field": "contact.phone", "code": "required", "params": {}}
      ]
    },
    "trace_id": "4bf92f3577b34da6a3ce929d0e0e4736"
  }
}
```

| Maydon | Qoida |
|---|---|
| `code` | Barqaror, `UPPER_SNAKE`. Frontend logikasi va tarjimasi **faqat shunga** tayanadi |
| `message` | Inglizcha, dasturchi uchun. Foydalanuvchiga to'g'ridan-to'g'ri ko'rsatilmaydi (§5.4) |
| `details` | Kodga xos tuzilma (§3.3). Ichki tafsilot (SQL, stack trace, boshqa tenant ma'lumoti) hech qachon yo'q |
| `trace_id` | OpenTelemetry trace ID — support'ga murojaat va log qidiruvi uchun |

### 3.2 Xato kodlari katalogi

`08_API_CONTRACTS.md` dagi katalogning to'liq versiyasi. Yangi kod qo'shish — shu jadvalni va frontend tarjimalarini birga yangilash.

| Code | HTTP | Qachon | Retry? |
|---|---|---|---|
| `VALIDATION_FAILED` | 422 | Pydantic / maydon validatsiyasi | yo'q |
| `INVALID_REQUEST` | 400 | noto'g'ri JSON, kerakli header yo'q (`Idempotency-Key`, `If-Match`) | yo'q |
| `UNAUTHENTICATED` | 401 | token yo'q, eskirgan yoki yaroqsiz | refresh'dan keyin |
| `FORBIDDEN` | 403 | o'z tenantida ruxsat yo'q | yo'q |
| `NOT_FOUND` | 404 | resurs yo'q **yoki boshqa tenantniki** (cross-tenant uchun doim 404, hech qachon 403) | yo'q |
| `METHOD_NOT_ALLOWED` | 405 | yo'l bor, metod yo'q | yo'q |
| `VERSION_CONFLICT` | 409 | `If-Match`/`expected_version` mos emas | yangi versiyani o'qib, foydalanuvchi qaror qiladi |
| `IDEMPOTENCY_KEY_REUSED` | 409 | bir xil key, boshqa payload | yo'q |
| `INSUFFICIENT_AVAILABLE_STOCK` | 409 | confirm / quick-sale paytida stok yetmadi | yo'q |
| `PRICE_CHANGED` | 409 | narx snapshot'dan farq qiladi — xaridordan qayta rozilik kerak | yo'q |
| `QUOTE_EXPIRED` | 409 | quote muddati o'tgan | yo'q |
| `INVALID_STATE_TRANSITION` | 409 | FSM'da ruxsat etilmagan o'tish | yo'q |
| `PAYLOAD_TOO_LARGE` | 413 | fayl/audio limiti | yo'q |
| `UNSUPPORTED_MEDIA_TYPE` | 415 | ruxsat etilmagan fayl turi | yo'q |
| `RULE_BLOCK` | 422 | PC compatibility `BLOCK` yoki biznes qoida | yo'q |
| `DISCOUNT_LIMIT_EXCEEDED` | 422 | rol limitidan katta chegirma (DEC-110) | yo'q |
| `RATE_LIMITED` | 429 | limit oshdi; `Retry-After` header bilan | ha, `Retry-After` dan keyin |
| `INTERNAL_ERROR` | 500 | kutilmagan xato | ha, bir marta (idempotent so'rovlar) |
| `FEATURE_NOT_AVAILABLE` | 501 | `DEFERRED` modul yoki o'chirilgan feature flag | yo'q |
| `PROVIDER_UNAVAILABLE` | 503 | LLM / Telegram / Meta ishlamayapti | ha, backoff bilan |
| `SERVICE_UNAVAILABLE` | 503 | DB pool to'lgan, maintenance; `Retry-After` bilan | ha |

### 3.3 `details` tuzilmalari

| Code | `details` |
|---|---|
| `VALIDATION_FAILED` | `{"fields": [{"field", "code", "params"}]}` — `field` JSON yo'li (`lines[0].quantity`), `code` kichik harfda: `required`, `min_value`, `max_value`, `min_length`, `max_length`, `invalid_format`, `invalid_choice`, `not_unique` |
| `VERSION_CONFLICT` | `{"current_version": 5, "your_version": 4}` |
| `INSUFFICIENT_AVAILABLE_STOCK` | `{"lines": [{"sku_id", "branch_id", "requested": 1, "available": 0}]}` |
| `PRICE_CHANGED` | `{"lines": [{"sku_id", "old": {money}, "new": {money}}]}` |
| `INVALID_STATE_TRANSITION` | `{"entity": "order", "from": "DRAFT", "action": "complete"}` |
| `RULE_BLOCK` | `{"rule_set_version", "findings": [{"rule_id", "severity"}]}` |
| `DISCOUNT_LIMIT_EXCEEDED` | `{"requested_percent": 8, "allowed_percent": 5, "approver_role": "OWNER"}` |
| `RATE_LIMITED` | `{"retry_after_seconds": 30}` |
| boshqalar | `{}` |

## 4. Backend implementatsiyasi

### 4.1 Exception ierarxiyasi

Domain va application qatlamlari HTTP haqida bilmaydi: ular faqat domain xatolarini tashlaydi. HTTP'ga o'girish faqat presentation qatlamidagi global handler'da.

```python
# src/commerce_os/shared/kernel/errors.py
class DomainError(Exception):
    code: str = "INTERNAL_ERROR"
    def __init__(self, message: str = "", **details: object) -> None:
        super().__init__(message or self.code)
        self.details = details

class NotFound(DomainError):              code = "NOT_FOUND"
class Forbidden(DomainError):             code = "FORBIDDEN"
class Conflict(DomainError):              code = "CONFLICT"            # abstrakt
class VersionConflict(Conflict):          code = "VERSION_CONFLICT"
class InsufficientStock(Conflict):        code = "INSUFFICIENT_AVAILABLE_STOCK"
class PriceChanged(Conflict):             code = "PRICE_CHANGED"
class QuoteExpired(Conflict):             code = "QUOTE_EXPIRED"
class InvalidStateTransition(Conflict):   code = "INVALID_STATE_TRANSITION"
class IdempotencyKeyReused(Conflict):     code = "IDEMPOTENCY_KEY_REUSED"
class BusinessRuleViolation(DomainError): code = "RULE_BLOCK"
class DiscountLimitExceeded(BusinessRuleViolation): code = "DISCOUNT_LIMIT_EXCEEDED"
class FeatureNotAvailable(DomainError):   code = "FEATURE_NOT_AVAILABLE"
class ProviderUnavailable(DomainError):   code = "PROVIDER_UNAVAILABLE"
class RateLimited(DomainError):           code = "RATE_LIMITED"
```

HTTP mapping bitta joyda (`shared/contracts/errors.py`): `code → status` lug'ati §3.2 jadvali bilan bir xil. Testda jadval va lug'at sinxronligi tekshiriladi.

### 4.2 Global handler'lar (barcha surface'lar)

| Ushlanadigan xato | Javob |
|---|---|
| `DomainError` va voris klasslar | `code`, mapping'dagi status, `details` |
| `fastapi.exceptions.RequestValidationError` | 422 `VALIDATION_FAILED`, Pydantic xatolari `details.fields[]` ga o'giriladi (Pydantic turi → §3.3 kodi) |
| `starlette.exceptions.HTTPException` 404 / 405 / 413 / 415 | `NOT_FOUND` / `METHOD_NOT_ALLOWED` / `PAYLOAD_TOO_LARGE` / `UNSUPPORTED_MEDIA_TYPE` — FastAPI'ning standart `{"detail": ...}` formati **hech qachon** chiqmaydi |
| Boshqa har qanday `Exception` | 500 `INTERNAL_ERROR`, umumiy `message`; to'liq xato Sentry'ga va `ERROR` logga (`trace_id` bilan) |

Har bir xato javobi `X-Request-ID` va `trace_id` ni o'z ichiga oladi. 4xx — `WARNING` log, 5xx — `ERROR` log + Sentry (TECH-12 §5b).

### 4.3 Surface'larga xos qoidalar

- **Webhook'lar** (`/webhooks/*`): imzo noto'g'ri — 401 (provayder qayta yubormaydi), DB'ga yozib bo'lmadi — 503 (provayder qayta yuboradi), takroriy event — 200 (yangi ish qilinmaydi). Biznes xatolari provayderga qaytarilmaydi: event saqlangach har doim 200, qayta ishlash worker'da.
- **Storefront** (public): `details` ichida ichki ID va stok soni faqat merchant siyosati ruxsat bersa (masalan, `available` o'rniga `"in_stock": false`).
- **WebSocket** (`/ws/v1/inbox`): xato frame'i `{"type": "error", "code", "message", "trace_id"}`; `UNAUTHENTICATED` bo'lsa ulanish yopiladi (close code 4401), klient ticket'ni yangilab qayta ulanadi.
- **Worker'lar:** xato HTTP'ga emas, job natijasiga yoziladi: `failure_code` (§3.2 kodlari) + `retryable` (bool). `ProviderUnavailable`, `RateLimited` — retry; `VALIDATION_FAILED`, `RULE_BLOCK`, `NOT_FOUND` — permanent, DLQ va operator vazifasi.

## 5. i18n — tillar va tarjima

### 5.1 Tillar

| Locale | Interfeys (dashboard, storefront) | AI va bot xabarlari | Izoh |
|---|---|---|---|
| `uz` (lotin) | ✅ default | ✅ | manba til |
| `ru` | ✅ | ✅ | |
| `en` | ✅ | ✅ | |
| `uz-Cyrl` | ❌ Stage 1 da interfeys yo'q (taklif) | ✅ xaridor kirillda yozsa, AI kirillda javob beradi | qidiruv lotin/kirill transliteratsiyasini tushunadi |

### 5.2 Tilni aniqlash tartibi

**Xodim (dashboard API):** 1) foydalanuvchi profilidagi til → 2) `Accept-Language` header → 3) merchant default tili → 4) `uz`. Middleware (TECH-12 §5a, 9-qadam) natijani `ActorContext.locale` ga yozadi.

**Xaridor (chat, storefront):** 1) xaridor tanlagan til (storefront'dagi til tanlagich) → 2) suhbatning oxirgi xabaridan aniqlangan til → 3) merchant default tili.

### 5.3 Nima qayerda tarjima qilinadi

| Matn turi | Kim tarjima qiladi | Qayerda saqlanadi |
|---|---|---|
| Dashboard va storefront interfeysi (tugmalar, sarlavhalar, holat nomlari) | **Frontend** | `ai-commerce-frontend/packages/i18n/locales/{uz,ru,en}.json` |
| API xato xabarlari | **Frontend**, `error.code` va `details` bo'yicha | o'sha fayllar, `errors.*` va `validation.*` kalitlari |
| Status nomlari (`PENDING_CONFIRMATION` → "Tasdiq kutilmoqda") | **Frontend** | `status.order.*`, `status.quote.*` |
| Xaridorga bot / AI javoblari | **Backend** (LLM xaridor tilida yozadi; tizim iboralari — shablon) | `message_templates` jadvali |
| Xaridorga notification'lar (buyurtma tasdiqlandi va h.k.) | **Backend** | `message_templates` (platforma default + merchant override) |
| PC compatibility tushuntirishlari | **Backend** (qoida shablonlari, uz/ru/en) | rule ta'riflari (TECH-25 §5) |
| Mahsulot nomi va tavsifi | **Merchant** kiritadi; ixtiyoriy til bo'yicha maydonlar | `product_translations` (taklif); bo'lmasa asosiy til |
| Hisobot va export sarlavhalari | **Backend** (CSV/XLSX — foydalanuvchi tilida) | backend locale fayllari |

**Qoida:** backend xodimga ko'rinadigan interfeys matni yubormaydi (faqat kod va ma'lumot). Xaridorga boradigan matnni esa backend yaratadi, chunki u Telegram/Instagram orqali frontend'siz yetkaziladi.

### 5.4 Frontend: xatoni ko'rsatish

```ts
// packages/i18n — kalit topilmasa umumiy matn, xom message hech qachon ko'rsatilmaydi
function errorText(err: ApiError, t: TFunction): string {
  return t(`errors.${err.code}`, { ...err.details, defaultValue: t("errors.UNKNOWN") });
}
```

| `code` | Ko'rinish |
|---|---|
| `VALIDATION_FAILED` | har maydon ostida inline xato (`validation.<code>` kaliti, `params` bilan) |
| `VERSION_CONFLICT` | dialog: "Ma'lumot boshqa foydalanuvchi tomonidan o'zgartirildi" + "Yangilash" (eski holatni yozib yubormaydi) |
| `INSUFFICIENT_AVAILABLE_STOCK`, `PRICE_CHANGED` | buyurtma kartochkasida ogohlantirish bloki va keyingi qadam tugmalari |
| `UNAUTHENTICATED` | jimgina `/auth/refresh`; muvaffaqiyatsiz bo'lsa login sahifasi |
| `FORBIDDEN` | "Ruxsat yo'q" holati, maxfiy ma'lumot ko'rsatilmaydi |
| `RATE_LIMITED`, `PROVIDER_UNAVAILABLE`, `SERVICE_UNAVAILABLE` | toast + `Retry-After` bo'yicha avtomatik qayta urinish (faqat GET va idempotent so'rovlar) |
| `INTERNAL_ERROR` | toast + "Xato kodi: `trace_id`" (support uchun) |

### 5.5 Tarjima fayllari formati

- **ICU MessageFormat** (plural va jins qoidalari uchun; rus tilining ko'plik shakllari shu bilan to'g'ri ishlaydi):
  `"orders.list.count": "{count, plural, one {# ta buyurtma} other {# ta buyurtma}}"` (uz), `"{count, plural, one {# заказ} few {# заказа} many {# заказов} other {# заказа}}"` (ru).
- **Kalit nomlash:** `<soha>.<ekran>.<element>` — `orders.detail.confirm_button`; xatolar `errors.<CODE>`; maydon xatolari `validation.<code>`; statuslar `status.<entity>.<STATUS>`.
- **Fallback:** so'ralgan til → `uz` → kalit nomi (faqat dev'da ko'rinadi).
- **CI tekshiruvi:** `uz`, `ru`, `en` fayllarida kalitlar to'plami bir xil bo'lishi shart; backend §3.2 dagi har bir `code` uchun `errors.<CODE>` kaliti mavjudligi tekshiriladi. Yetishmasa build yiqiladi.
- **Manba til** — `uz`. Rus va ingliz tarjimalari founder yoki tarjimon tomonidan, PR orqali.

### 5.6 Backend xabar shablonlari

```sql
CREATE TABLE message_templates (
  id uuid PRIMARY KEY,
  merchant_id uuid,                 -- NULL = platforma default; qiymat = merchant override
  key text NOT NULL,                -- 'order.confirmed', 'order.ready_for_pickup', 'ai.handoff_notice'
  locale text NOT NULL CHECK (locale IN ('uz','uz-Cyrl','ru','en')),
  body text NOT NULL,               -- ICU MessageFormat, o'zgaruvchilar: {order_number}, {total}
  version integer NOT NULL DEFAULT 1,
  UNIQUE (merchant_id, key, locale, version)
);
```

Tanlash tartibi: merchant override (xaridor tili) → platforma default (xaridor tili) → platforma default (`uz`). Notification yozuvida ishlatilgan `template_key`, `locale` va `version` saqlanadi (BL-060).

### 5.7 Raqam, sana, pul formatlash

- Formatlash faqat ko'rsatish qatlamida: frontend (`Intl.NumberFormat`, `Intl.DateTimeFormat`), backend shablonlari (Babel yoki ekvivalent).
- UZS: butun so'm, mingliklar bo'sh joy bilan — `1 250 000 so'm` (uz), `1 250 000 сум` (ru), `UZS 1,250,000` (en).
- USD (DEC-121, faqat xodim ko'radi): `$1,250.00`.
- Sana va vaqt merchant timezone'ida (`Asia/Tashkent`): `22.10.2026 14:15`.
- O'zbek apostrofi: saqlashda `ʻ` (U+02BB) / `‘` (U+2018) / `'` normalizatsiya qilinadi, qidiruvda hammasi bir xil deb hisoblanadi; ko'rsatishda `o‘`, `g‘` (U+2018).

## 6. Header'lar va boshqa konvensiyalar

| Header | Yo'nalish | Qoida |
|---|---|---|
| `Authorization: Bearer <access>` | so'rov | merchant surface (ADR-023) |
| `X-Request-ID` | ikkala | klient yuborishi mumkin (UUID format), aks holda server yaratadi; javobda doim |
| `traceparent` | so'rov | W3C format bo'lsa qabul qilinadi |
| `Idempotency-Key` | so'rov | barcha qayta yuborilishi mumkin bo'lgan POST'larda majburiy (K-06). Natija 24 soat saqlanadi; scope `(merchant_id, actor, route, key)`; bir xil key + boshqa payload → `IDEMPOTENCY_KEY_REUSED` |
| `If-Match: "v4"` | so'rov | narx, stok tuzatish, buyurtma o'tishlari, policy o'zgarishi |
| `ETag: "v4"` | javob | resurs `version` maydoni bilan bir xil |
| `Accept-Language` | so'rov | locale aniqlash (§5.2) |
| `RateLimit-Limit`, `RateLimit-Remaining`, `RateLimit-Reset`, `Retry-After` | javob | IETF RateLimit header'lari |
| `Location` | javob | 201 da yangi resurs manzili |

## 7. Qabul testlari

| ID | Sinov | Kutilgan natija |
|---|---|---|
| TC-CONV-01 | Noto'g'ri tana bilan POST | 422, `VALIDATION_FAILED`, `details.fields[]`, FastAPI `detail` formati yo'q |
| TC-CONV-02 | Mavjud bo'lmagan yo'l va noto'g'ri metod | 404 `NOT_FOUND`, 405 `METHOD_NOT_ALLOWED`, ikkalasi envelope'da |
| TC-CONV-03 | Handler ichida kutilmagan exception | 500 `INTERNAL_ERROR`, javobda stack trace yo'q, Sentry'da hodisa, log'da `trace_id` |
| TC-CONV-04 | Har bir §3.2 kodi uchun `errors.<CODE>` kaliti `uz/ru/en` da | CI o'tadi; bittasi yo'q bo'lsa yiqiladi |
| TC-CONV-05 | `Accept-Language: ru`, profil tili yo'q | `ActorContext.locale = ru`; CSV export sarlavhalari ruscha |
| TC-CONV-06 | Xaridor kirillcha yozadi | AI va notification javoblari kirillcha; storefront interfeysi lotincha |
| TC-CONV-07 | Bir xil `Idempotency-Key` bilan 2 ta POST | Ikkinchisi birinchining natijasini qaytaradi; boshqa payload bilan — 409 |
| TC-CONV-08 | Webhook: imzo noto'g'ri / DB ishlamayapti / takroriy event | 401 / 503 / 200 |
