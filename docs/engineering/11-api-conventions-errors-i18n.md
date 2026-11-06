# 11 — API qoidalari, xatolar va tarjimalar (i18n)

> **Versiya:** v2 (2026-10-22). Eski `08_API_CONTRACTS` (WebSocket ichki qismi — [08-cache-and-realtime.md](08-cache-and-realtime.md) ga) va `24_API_CONVENTIONS_ERRORS_I18N` o'rnini bosadi.
> **Bog'liq:** ADR-008, ADR-023, ADR-024, ADR-025, ADR-031; DEC-006, DEC-124; K-02, K-06, K-07.
> **Kim o'qiydi:** backend va frontend dasturchi.

## 1. Muammo va yechim

**Muammo:** 7 domen, 5 surface, 3 til. Agar har endpoint o'zicha javob va xato qaytarsa, frontend har biriga alohida kod yozadi, foydalanuvchi esa "Internal Server Error" yoki inglizcha `{"detail": ...}` ko'radi.

**Yechim:**
- Bitta javob formati, bitta xato envelope'i (K-07), barqaror xato kodlari katalogi.
- Domen kodi HTTP'ni bilmaydi — faqat `DomainError` tashlaydi; HTTP'ga o'girish bitta global handler'da.
- Xodim interfeysi matnini **frontend** tarjima qiladi (xato kodi bo'yicha); xaridorga boradigan matnni **backend** shablonlardan yaratadi.
- OpenAPI — yagona kontrakt; frontend client undan generatsiya qilinadi.

---

## 2. Surface'lar va router'lar

| Surface | Prefiks | Kim | Auth ([10](10-security-tenancy-rbac.md) §5) |
|---|---|---|---|
| `shop` | `/api/v1/shop/*` | Shop xodimlari (dashboard) | Access JWT + a'zolik + ruxsat |
| `storefront` | `/api/v1/storefront/{slug}/*` | Sayt xaridori | Anonim + rate limit; signed token (bitta resurs) |
| `webhooks` | `/api/v1/webhooks/*` | Telegram, Meta | Provayder imzosi |
| `platform` | `/api/v1/platform/*` | Platforma jamoasi | Platforma roli + audit |
| `auth` | `/api/v1/auth/*` | Hamma | — |
| `public` | `/api/v1/public/*` | Stage 3 | — |
| WebSocket | `/ws` | Xodim (inbox), sayt chati | Ticket ([08](08-cache-and-realtime.md)) |

**Router'lar `DomainManifest` orqali ulanadi** ([02](02-folder-skeleton.md) §2): har domen `routers={"shop": ..., "storefront": ...}` beradi, `main.py` ularni surface prefiksi va surface middleware'i bilan ulaydi. URL'da domen nomi yo'q (`/api/v1/shop/orders`, `/api/v1/shop/commerce/orders` emas). Bitta resurs yo'li faqat bitta domenga tegishli — `main.py` boot'da ikki domen bir xil yo'lni e'lon qilsa xato beradi.

---

## 3. Umumiy qoidalar

| Mavzu | Qoida |
|---|---|
| Format | JSON, UTF-8; maydonlar `snake_case` |
| Resurs nomlari | Ko'plikda, kebab-case: `/orders`, `/catalog/imports`, `/quick-sales`, `/support-cases` |
| Holat o'tishlari | `POST /orders/{id}/confirm` — fe'l alohida yo'lda (FSM buyruqlari), `PATCH status` emas |
| Ichma-ich resurs | Faqat egalik aniq bo'lsa, 1 daraja: `/orders/{id}/notes`. `/orders/{id}/conversation` kabi boshqa domen resursi — TAQIQ; o'rniga `conversation_id` maydoni yoki `?expand=` |
| Enum | `UPPER_SNAKE` (K-02); manbai — `../business/05`. Frontend noma'lum qiymatni `UNKNOWN` deb ko'rsatadi, xato bermaydi |
| ID | UUIDv7, string. Ichki ID ommaviy token sifatida ishlatilmaydi (taklif/buyurtma kuzatuvi uchun alohida token) |
| Vaqt | ISO-8601 UTC, `Z` bilan: `2026-10-22T09:15:00Z`. Hisobot sanalari shop timezone'ida + javobda `timezone` |
| Pul | `{"amount_minor": 1250000000, "currency": "UZS"}` — butun son (ADR-025, UZS exponent 2). Float yo'q. Formatlash — ko'rsatish qatlamida |
| Kasr son (foiz, kurs) | **Matn**: `"8.50"` — aniqlik yo'qolmaydi. Javoblar, xato `details` va saqlangan idempotency javoblari bitta serializer'dan o'tadi (`app/shared/serialization.py`, Pydantic) |
| Shop | `shop_id` so'rovda **qabul qilinmaydi** — serverda aniqlanadi (K-01) |
| Null | Ma'lum, lekin bo'sh — `null`. Sxemadagi maydonlar har doim qaytadi |
| Versiya | O'zgaradigan resurslarda `version` maydoni; yozishda `If-Match: "v4"` |
| ORM | Hech qachon javob sifatida qaytarilmaydi — faqat Pydantic DTO |

---

## 4. Muvaffaqiyatli javoblar

Muvaffaqiyatli javob **envelope'siz**: resursning o'zi yoki ro'yxat obyekti. Xato — doim `error` envelope'ida (§6). Frontend javob turini HTTP status va `error` kaliti bo'yicha aniqlaydi.

| Holat | HTTP | Tana |
|---|---|---|
| Bitta resurs (GET, PATCH, holat o'tishi) | 200 | Resurs obyekti, `version` bilan |
| Yaratildi | 201 | Resurs obyekti + `Location` |
| Ro'yxat | 200 | `{"items": [...], "next_cursor": "opaque" \| null, "has_more": bool}` |
| Uzoq ish (import, eksport) | 202 | `{"job_id", "status": "QUEUED", "status_url"}` |
| Tanasiz | 204 | — |

```json
{
  "items": [
    {"id": "0192b6f0-…", "number": 1042, "status": "PENDING_CONFIRMATION",
     "total": {"amount_minor": 450000000, "currency": "UZS"}, "version": 2}
  ],
  "next_cursor": "eyJjIjoiMjAyNi0xMC0yMlQwOToxNTowMFoiLCJpZCI6Ii4uLiJ9",
  "has_more": true
}
```

### 4.1 Pagination, filtr, saralash

- **Cursor pagination:** `?limit=` (default 25, maks 100), `?cursor=`. Cursor — opaque (base64: saralash qiymati + `id`). Offset — ishlatilmaydi.
- **Filtr:** maydon nomi bilan: `?status=CONFIRMED&branch_id=…&created_from=2026-10-01T00:00:00Z&created_to=…`. Bir nechta qiymat: `?status=CONFIRMED,PROCESSING`. Matn qidiruvi: `?q=rtx 5060`.
- **Saralash:** `?sort=-created_at` (minus — kamayish). Har ro'yxat uchun ruxsat etilgan maydonlar ro'yxati router'da; boshqasi — `VALIDATION_FAILED`.
- **`?expand=`** — faqat shu domen ichidagi bog'liq resurslar (`?expand=lines,notes`).
- Limitsiz ro'yxat — TAQIQ ([03](03-module-requirements.md) §3).

### 4.2 Uzoq ishlar (202)

`POST /api/v1/shop/catalog/imports/{id}/dry-run` → `202 {"job_id", "status_url": "/api/v1/shop/jobs/{job_id}"}`. `GET /api/v1/shop/jobs/{job_id}` → `{"status": "QUEUED|RUNNING|SUCCEEDED|FAILED", "progress", "result_url", "failure_code"}`. Ish holati shop doirasida (boshqa shop ishi — 404).

---

## 5. Header'lar (K-06)

| Header | Yo'nalish | Qoida |
|---|---|---|
| `Authorization: Bearer <access>` | so'rov | `shop` va `platform` surface |
| `X-Request-ID` | ikkala | Klient yuborishi mumkin (UUID); aks holda server yaratadi; javobda doim |
| `traceparent` | so'rov | W3C format bo'lsa qabul qilinadi; aks holda yangi trace |
| `Idempotency-Key` | so'rov | **Barcha yozish POST'larida majburiy** (`shop`, `storefront`, `platform`). Yo'q bo'lsa — `INVALID_REQUEST`. Doira `(shop_id, operation, key)`, natija 24 soat saqlanadi ([07](07-data-layer.md) `idempotency_keys`). Tana barmoq izi — server kaliti bilan HMAC (`h1:…`, `IDEMPOTENCY_HASH_KEY`): bazadan tanani (masalan, telefonni) tanlab topib bo'lmaydi. Bir xil key + boshqa tana → `IDEMPOTENCY_KEY_REUSED` |
| `If-Match: "v4"` | so'rov | Narx, stok tuzatish, buyurtma o'tishlari, sozlamalar, profil. Mos kelmasa — `VERSION_CONFLICT` |
| `ETag: "v4"` | javob | Resurs `version` bilan bir xil |
| `Accept-Language` | so'rov | Til aniqlash (§8.2) |
| `RateLimit-Limit`, `RateLimit-Remaining`, `RateLimit-Reset`, `Retry-After` | javob | IETF RateLimit header'lari |
| `Location` | javob | 201 da |

---

## 6. Xatolar (K-07)

### 6.1 Envelope

Barcha surface'lar, barcha 4xx/5xx, FastAPI/Starlette'ning o'z xatolari ham shu formatda:

```json
{
  "error": {
    "code": "INSUFFICIENT_AVAILABLE_STOCK",
    "message": "Insufficient available stock",
    "details": {"lines": [{"sku_id": "0192…", "branch_id": "0192…", "requested": 1, "available": 0}]},
    "trace_id": "4bf92f3577b34da6a3ce929d0e0e4736"
  }
}
```

| Maydon | Qoida |
|---|---|
| `code` | Barqaror, `UPPER_SNAKE`. Frontend logikasi va tarjimasi **faqat shunga** tayanadi |
| `message` | Inglizcha, dasturchi uchun. Foydalanuvchiga ko'rsatilmaydi |
| `details` | Kodga xos tuzilma (§6.3). Ichki tafsilot (SQL, stack trace, boshqa shop ma'lumoti) — hech qachon |
| `trace_id` | OpenTelemetry trace ID — yordamga murojaat va log qidiruvi uchun |

### 6.2 Xato kodlari katalogi

Yangi kod qo'shish — shu jadval + `DomainError` klassi + `uz/ru/en` tarjimalari, bitta PR'da (CI tekshiradi, TC-CONV-04).

| Code | HTTP | Qachon | Qayta urinish |
|---|---|---|---|
| `VALIDATION_FAILED` | 422 | Pydantic / maydon validatsiyasi, noto'g'ri filtr yoki saralash | yo'q |
| `INVALID_REQUEST` | 400 | Noto'g'ri JSON, kerakli header yo'q (`Idempotency-Key`, `If-Match`) | yo'q |
| `UNAUTHENTICATED` | 401 | Token yo'q, eskirgan yoki yaroqsiz | refresh'dan keyin |
| `FORBIDDEN` | 403 | O'z shopida ruxsat yo'q (rol, "own", filial). Buyurtmada `details.reason`: `other_operator`, `not_confirmed` (omborchi — hali tasdiqlanmagan), `other_branch`, `not_assigned` | yo'q |
| `SELF_APPROVAL_NOT_ALLOWED` | 403 | O'zi tuzgan taklif/so'rovni o'zi tasdiqlamoqchi (DEC-109) | yo'q |
| `NOT_FOUND` | 404 | Resurs yo'q **yoki boshqa shopniki** — doim 404, hech qachon 403 (TC-001) | yo'q |
| `METHOD_NOT_ALLOWED` | 405 | Yo'l bor, metod yo'q | yo'q |
| `VERSION_CONFLICT` | 409 | `If-Match` / `version` mos emas | yangisini o'qib, foydalanuvchi qaror qiladi |
| `IDEMPOTENCY_KEY_REUSED` | 409 | Bir xil key, boshqa tana | yo'q |
| `REQUEST_IN_PROGRESS` | 409 | Shu `Idempotency-Key` bilan birinchi so'rov hali bajarilmoqda — dublikat kutmaydi (founder, 2026-10-23) | ha, 1–2 s dan keyin **xuddi shu kalit bilan**: saqlangan javob yoki (birinchisi yiqilgan bo'lsa) yangi bajarilish |
| `INVALID_STATE_TRANSITION` | 409 | FSM'da ruxsat etilmagan o'tish (ADR-034) | yo'q |
| `INSUFFICIENT_AVAILABLE_STOCK` | 409 | Tasdiqlash / tez sotuv paytida qoldiq yetmadi (TC-002, TC-027) | yo'q |
| `PRICE_CHANGED` | 409 | Narx snapshot'dan farq qiladi — xaridordan qayta rozilik (TC-031) | yo'q |
| `QUOTE_EXPIRED` | 409 | Taklif muddati o'tgan | yo'q |
| `APPROVAL_REQUIRED` | 409 | Tasdiqsiz yuborib bo'lmaydi: taklif `REVIEW`, moslik `REVIEW_REQUIRED` (TC-008), chegirma tasdiq kutyapti | yo'q |
| `EXCHANGE_RATE_STALE` | 409 | Dollar kursi eskirgan (UAT-M05) — yangi taklif berilmaydi | kurs yangilangach |
| `PRODUCT_NOT_AVAILABLE` | 409 | Mahsulot chiqarilmagan, yashirilgan yoki arxivda (UAT-M07) | yo'q |
| `BRANCH_CLOSED` | 409 | Yopiq filial tanlangan (UAT-M03, TC-026) | yo'q |
| `SHOP_NOT_ACTIVE` | 409 | Shop `SUSPENDED`/`CLOSED` — yangi buyurtma va tez sotuv qabul qilinmaydi, mavjudlari yakunlanadi (TC-023, DEC-136). `details.shop_status`: `CLOSED` — klient sessiyani tugatadi; `SUSPENDED` — faqat shu amal rad etiladi | yo'q |
| `LAST_OWNER_REQUIRED` | 409 | Oxirgi egani o'chirish yoki rolini olish (UAT-M02) | yo'q |
| `LAST_ADMIN_REQUIRED` | 409 | Oxirgi faol platforma adminini o'chirish yoki rolini olish (business/15 §5) | yo'q |
| `FILE_IN_USE` | 409 | Fayl allaqachon boshqa mahsulot rasmi — bitta fayl bitta mahsulotda (`details.product_id`) | yo'q (faylni qayta yuklash) |
| `ORDER_LINKED_ELSEWHERE` | 409 | Buyurtma boshqa suhbatga bog'langan — jim ko'chirilmaydi (`details.order_version`); ko'chirish `relink: true` + `expected_version` bilan (QA 5b M3) | yo'q (tasdiqlab qayta yuborish) |
| `SHOP_HAS_OPEN_ORDERS` | 409 | Shopni yopib bo'lmaydi: tasdiq kutayotgan, tasdiqlangan, tayyorlanayotgan yoki muammoli buyurtmalar bor — avval yakunlanadi yoki bekor qilinadi (FSM-01, TC-023) | yo'q |
| `SITE_NOT_AVAILABLE` | 409 | Shop sayti xaridorga hozir ochiq emas: "tez orada" (sayt qoralama yoki shop faollashtirilmagan) yoki "vaqtincha ishlamayapti" (sayt yoki shop to'xtatilgan). Bunday shop yo'q yoki yopilgan — `NOT_FOUND` (storefront.md §0) | yo'q |
| `SPEAKER_CONFLICT` | 409 | Suhbatni boshqa operator olgan yoki `speaker_version` eskirgan (TC-009) | yangilab qayta |
| `CHANNEL_UNAVAILABLE` | 409 | Kanal `DISCONNECTED`/`DEGRADED`, xabar yuborib bo'lmaydi (TC-011) | ulangach |
| `PAYLOAD_TOO_LARGE` | 413 | Fayl yoki audio limiti | yo'q |
| `UNSUPPORTED_MEDIA_TYPE` | 415 | Ruxsat etilmagan fayl turi | yo'q |
| `RULE_BLOCK` | 422 | PC moslik `BLOCK` yoki biznes qoida buzildi | yo'q |
| `DISCOUNT_LIMIT_EXCEEDED` | 422 | Rol limitidan katta chegirma (DEC-110) | yo'q (tasdiq so'raladi) |
| `IMPORT_FILE_INVALID` | 422 | Import fayli o'qilmadi (format, kodlash, ustunlar) — [18](18-catalog-import.md); `details.reason`: `EMPTY`, `NO_HEADER`, `NOT_TABLE`, `MACRO`, `ZIP_BOMB`, `TOO_MANY_ROWS`, `TOO_LARGE`, `UNSUPPORTED_ENCODING` (yuklashdagi arzon tekshiruv). Fonda o'qishda chiqqan sabab (`TIMEOUT` va shu ro'yxat) — 422 emas, import `FAILED`, `error_code` da (5c QA F1) | yo'q |
| `IMPORT_ALREADY_RUNNING` | 409 | Shopda boshqa faol import bor (sinov, yozish yoki qoldiq bosqichida) — tugashini kuting (18 §3) | yo'q |
| `IMPORT_BUSY` | 409 | Import fon bosqichi aynan shu daqiqada yozuvni yangilayapti — qulf kutilmaydi (`NOWAIT`), bir zumdan keyin qayta urinish (5c QA F5) | ha |
| `RATE_LIMITED` | 429 | Limit oshdi; `Retry-After` bilan | ha, `Retry-After` dan keyin |
| `AI_QUOTA_EXCEEDED` | 429 | Shop AI limiti tugadi (BL-067, BL-069) — AI o'chadi, savdo ishlaydi | keyingi davr / paket |
| `INTERNAL_ERROR` | 500 | Kutilmagan xato | ha, bir marta (idempotent so'rovlar) |
| `FEATURE_NOT_AVAILABLE` | 501 | `DEFERRED` modul (to'lov, yetkazish) yoki o'chirilgan feature flag | yo'q |
| `PROVIDER_UNAVAILABLE` | 503 | LLM / Telegram / Meta ishlamayapti | ha, backoff |
| `SERVICE_UNAVAILABLE` | 503 | DB pool to'lgan, texnik ishlar; `Retry-After` | ha |

### 6.3 `details` tuzilmalari

| Code | `details` |
|---|---|
| `VALIDATION_FAILED` | `{"fields": [{"field": "lines[0].quantity", "code": "min_value", "params": {"min": 1}}]}`; `code`: `required, min_value, max_value, min_length, max_length, invalid_format, invalid_choice, not_unique, too_weak, invalid, same_as_current, out_of_scope, invalid_range` (`invalid_range` — oraliq bo'sh, masalan ish vaqti `09:00–09:00`; `out_of_scope` — buyurtma filiali almashganda mas'ul xodim yangi filialda ishlamaydi, `params.membership_id`; `too_weak` — parol juda oddiy yoki telefon raqamini o'z ichiga oladi; `invalid` — qiymat tekshiruvdan o'tmadi, masalan joriy parol noto'g'ri; `same_as_current` — yangi parol joriysi bilan bir xil). Qat'iy chegara (`> 0`): butun sonda `min` — eng kichik **ruxsat etilgan** qiymat (`{"min": 1}`), kasrda — chegaraning o'zi va `"exclusive": true`. NUL belgisi (`\u0000`) yoki `NaN`/`Infinity` bor maydon — `invalid_format` (so'rov darajasida ushlanadi; yo'lda NUL — 404) |
| `VERSION_CONFLICT` | `{"current_version": 5, "your_version": 4}` |
| `INVALID_STATE_TRANSITION` | `{"entity": "commerce.order", "from": "DRAFT", "command": "COMPLETE"}` |
| `INSUFFICIENT_AVAILABLE_STOCK` | `{"lines": [{"sku_id", "branch_id", "requested", "available", "reserved"}]}` — `reserved > 0` bo'lsa mahsulot buyurtmaga band (BL-109: "online buyurtma uchun band qilingan") |
| `PRICE_CHANGED` | `{"lines": [{"line_id", "sku_id", "old": {money}, "new": {money}}]}` — so'mdagi narx (DEC-134) |
| `PRODUCT_NOT_AVAILABLE` | `{"lines": [{"sku_id", "product_status", "sku_status"}]}` (tasdiq va narx yangilashda + `line_id`; kirim va oshiruvchi tuzatishda arxivdagi SKU) yoki tez sotuvda narx yo'qligida `{"lines": [{"sku_id", "reason": "NO_PRICE" \| "NO_RATE"}]}`. Tez sotuv — faqat `PUBLISHED`/`HIDDEN` mahsulot va faol SKU |
| `SHOP_NOT_ACTIVE` | `{"shop_status": "SUSPENDED" \| "CLOSED"}` |
| `SHOP_HAS_OPEN_ORDERS` | `{"open_orders": {"CONFIRMED": 3, "PROCESSING": 2}, "total": 5}` — faqat noldan kattalari |
| `SITE_NOT_AVAILABLE` | `{"state": "COMING_SOON" \| "PAUSED", "preview": false}` |
| `QUOTE_EXPIRED` | `{"expired_at"}` |
| `APPROVAL_REQUIRED` | `{"reason": "COMPATIBILITY_REVIEW" \| "QUOTE_REVIEW" \| "DISCOUNT", "approver_roles": ["MANAGER", "OWNER"]}`; chegirmada + `line_ids` |
| `EXCHANGE_RATE_STALE` | `{"rate_effective_at", "max_age_hours"}` |
| `RULE_BLOCK` | `{"ruleset_version", "findings": [{"rule_id", "severity"}]}` |
| `DISCOUNT_LIMIT_EXCEEDED` | `{"requested_percent": 8, "allowed_percent": 5, "approver_role": "OWNER"}` |
| `SPEAKER_CONFLICT` | `{"speaker_mode": "HUMAN", "speaker_version": 7}` |
| `RATE_LIMITED`, `AI_QUOTA_EXCEEDED` | `{"retry_after_seconds"}` / `{"period_end"}` |
| boshqalar | `{}` |

**Storefront'da** `details` ichida ichki ID va aniq qoldiq yo'q: buyurtma so'rovida mavjud bo'lmagan mahsulot — `PRODUCT_NOT_AVAILABLE` va faqat `{"lines": [{"sku_id"}]}`; boshqa shop SKU'si yoki filiali — xuddi yo'qdek (`VALIDATION_FAILED`, `invalid`). Eskirgan rozilik — `consent_version` / `invalid_choice` (`params.expected`). Buyurtma so'rovi xatolarida `*_id` kalitlari olib tashlanadi: yopiq filial — `BRANCH_CLOSED` tafsilotsiz; qatorlarda faqat xaridor yuborgan `sku_id` (QA M04 F5). `qty` — faqat butun son (`"2"` yoki `true` — 422). Sozlamada och rang — `accent_color` / `low_contrast` (`params.min_ratio`, `params.ratio`); sahifa matnida HTML — `body_md` / `invalid_format`.

---

## 7. Backend implementatsiyasi

### 7.1 Exception ierarxiyasi — `app/shared/errors/base.py`

Domen va service qatlamlari HTTP haqida bilmaydi — faqat domen xatolarini tashlaydi.

```python
class DomainError(Exception):
    code: ClassVar[str] = "INTERNAL_ERROR"
    def __init__(self, message: str = "", **details: object) -> None:
        super().__init__(message or self.code)
        self.details = details

class ValidationError(DomainError):        code = "VALIDATION_FAILED"
class NotFoundError(DomainError):          code = "NOT_FOUND"
class ForbiddenError(DomainError):         code = "FORBIDDEN"
class SelfApprovalError(ForbiddenError):   code = "SELF_APPROVAL_NOT_ALLOWED"

class ConflictError(DomainError):          code = "CONFLICT"               # abstrakt, to'g'ridan-to'g'ri ishlatilmaydi
class VersionConflictError(ConflictError):        code = "VERSION_CONFLICT"
class IdempotencyKeyReusedError(ConflictError):   code = "IDEMPOTENCY_KEY_REUSED"
class InvalidTransitionError(ConflictError):      code = "INVALID_STATE_TRANSITION"
class InsufficientStockError(ConflictError):      code = "INSUFFICIENT_AVAILABLE_STOCK"
class PriceChangedError(ConflictError):           code = "PRICE_CHANGED"
class QuoteExpiredError(ConflictError):           code = "QUOTE_EXPIRED"
class ApprovalRequiredError(ConflictError):       code = "APPROVAL_REQUIRED"
class ExchangeRateStaleError(ConflictError):      code = "EXCHANGE_RATE_STALE"
class ProductNotAvailableError(ConflictError):    code = "PRODUCT_NOT_AVAILABLE"
class BranchClosedError(ConflictError):           code = "BRANCH_CLOSED"
class ShopNotActiveError(ConflictError):          code = "SHOP_NOT_ACTIVE"
class LastOwnerRequiredError(ConflictError):      code = "LAST_OWNER_REQUIRED"
class LastAdminRequiredError(ConflictError):      code = "LAST_ADMIN_REQUIRED"
class FileInUseError(ConflictError):              code = "FILE_IN_USE"
class ShopHasOpenOrdersError(ConflictError):      code = "SHOP_HAS_OPEN_ORDERS"
class SiteNotAvailableError(ConflictError):       code = "SITE_NOT_AVAILABLE"
class SpeakerConflictError(ConflictError):        code = "SPEAKER_CONFLICT"
class ChannelUnavailableError(ConflictError):     code = "CHANNEL_UNAVAILABLE"

class BusinessRuleError(DomainError):             code = "RULE_BLOCK"
class DiscountLimitExceededError(BusinessRuleError): code = "DISCOUNT_LIMIT_EXCEEDED"
class ImportFileInvalidError(BusinessRuleError):  code = "IMPORT_FILE_INVALID"

class RateLimitedError(DomainError):       code = "RATE_LIMITED"
class AIQuotaExceededError(RateLimitedError): code = "AI_QUOTA_EXCEEDED"
class FeatureNotAvailableError(DomainError):  code = "FEATURE_NOT_AVAILABLE"
class ProviderUnavailableError(DomainError):  code = "PROVIDER_UNAVAILABLE"
```

Katalogdagi qolgan kodlar uchun ham klass bor: `InvalidRequestError` (`INVALID_REQUEST`), `UnauthenticatedError`, `PayloadTooLargeError`, `UnsupportedMediaTypeError`, `ServiceUnavailableError`. Faqat `METHOD_NOT_ALLOWED` ni framework o'zi chiqaradi. Abstrakt klasslar (`ConflictError`) `abstract = True` bilan belgilanadi va to'g'ridan-to'g'ri tashlanmaydi.

`code → HTTP status` lug'ati bitta joyda (`app/shared/errors/catalog.py`, `ERROR_CATALOG`), §6.2 jadvali bilan bir xil. Test: jadval, lug'at va `locales/` sinxron.

### 7.2 Global handler'lar (barcha surface)

| Ushlanadigan xato | Javob |
|---|---|
| `DomainError` va vorislari | `code`, lug'atdagi status, `details` |
| `RequestValidationError` (FastAPI) | 422 `VALIDATION_FAILED`, Pydantic xatolari `details.fields[]` ga (§6.3 kodlari) |
| `HTTPException` 404 / 405 / 413 / 415 | `NOT_FOUND` / `METHOD_NOT_ALLOWED` / `PAYLOAD_TOO_LARGE` / `UNSUPPORTED_MEDIA_TYPE` — FastAPI'ning `{"detail": ...}` formati **hech qachon** chiqmaydi |
| `sqlalchemy.exc.IntegrityError` (unikal cheklov) | Repository'da domen xatosiga o'giriladi; o'girilmagani — 500 (bug) |
| `HTTPException` — katalogda yo'q status | 4xx — asl status saqlanadi, kod `INVALID_REQUEST`, `WARNING` log; 5xx — 500 `INTERNAL_ERROR`. Bizning kodda `HTTPException` ishlatilmaydi — faqat `DomainError` |
| `StaleDataError` (`VersionMixin`) | 409 `VERSION_CONFLICT` |
| Boshqa har qanday `Exception` | 500 `INTERNAL_ERROR`, umumiy `message`; to'liq xato Sentry'ga va `ERROR` logga (`trace_id` bilan) |

Har xato javobida `X-Request-ID` va `trace_id`. 4xx — `WARNING` log, 5xx — `ERROR` log + Sentry ([09-observability.md](09-observability.md)).

### 7.3 Surface'larga xos qoidalar

- **Webhook'lar:** imzo noto'g'ri — 401 (provayder qayta yubormaydi); DB'ga yozib bo'lmadi — 503 (qayta yuboradi); takror event — 200 (yangi ish yo'q). Biznes xatolari provayderga qaytarilmaydi: event saqlangach doim 200, qayta ishlash worker'da ([13](13-integrations-and-channels.md)).
- **Storefront:** ichki maydonlar yashiriladi (§6.3); `NOT_FOUND` va `PRODUCT_NOT_AVAILABLE` — xaridorga "mavjud emas".
- **WebSocket:** xato frame'i `{"type": "error", "code", "message", "trace_id"}`; `UNAUTHENTICATED` — ulanish yopiladi (4401) ([08](08-cache-and-realtime.md)).
- **Worker / subscriber:** xato HTTP'ga emas, vazifa natijasiga: `failure_code` (§6.2) + `retryable`. `PROVIDER_UNAVAILABLE`, `RATE_LIMITED` — qayta urinish; `VALIDATION_FAILED`, `RULE_BLOCK`, `NOT_FOUND` — doimiy, dead-letter va xodim vazifasi ([06](06-background-jobs.md)).

---

## 8. i18n — tillar va tarjima

### 8.1 Tillar

| Locale | Interfeys (dashboard, sayt) | AI va bot xabarlari | Izoh |
|---|---|---|---|
| `uz` (lotin) | ✅ default | ✅ | Manba til |
| `ru` | ✅ | ✅ | |
| `en` | ✅ | ✅ | |
| `uz-Cyrl` | ❌ Stage 1 da interfeys yo'q | ✅ xaridor kirillda yozsa, AI kirillda javob beradi | Qidiruv lotin/kirillni tushunadi |

### 8.2 Tilni aniqlash

**Xodim (`shop` surface):** 1) profil tili (`principals.locale`) → 2) `Accept-Language` → 3) shop default tili → 4) `uz`. `I18nMiddleware` natijani `ActorContext.locale` ga yozadi.

**Xaridor (chat, sayt):** 1) saytdagi til tanlagich → 2) suhbatning oxirgi xabaridan aniqlangan til (`conversations.locale`) → 3) shop default tili.

### 8.3 Nima qayerda tarjima qilinadi

| Matn turi | Kim tarjima qiladi | Qayerda |
|---|---|---|
| Dashboard va sayt interfeysi | **Frontend** | `ai-commerce-frontend/packages/i18n/locales/{uz,ru,en}.json` |
| API xato xabarlari | **Frontend**, `error.code` + `details` bo'yicha | `errors.*`, `validation.*` kalitlari |
| Holat nomlari (`PENDING_CONFIRMATION` → "Tasdiq kutilmoqda") | **Frontend** | `status.<entity>.<STATUS>` |
| Xaridorga bot/AI javoblari | **Backend** (LLM xaridor tilida; tizim iboralari — shablon) | `platform.message_templates` |
| Xaridorga xabarnomalar | **Backend** | `message_templates` (platforma default + shop override) — [20-notifications.md](20-notifications.md) |
| PC moslik tushuntirishlari | **Backend** (qoida shablonlari) | Qoidalar ta'rifi ([17](17-pc-compatibility-engine.md)) |
| Mahsulot nomi va tavsifi | **Shop** kiritadi | `catalog.products` (+ ixtiyoriy tarjimalar, keyin) |
| Hisobot va eksport sarlavhalari (CSV/XLSX) | **Backend**, foydalanuvchi tilida | `app/shared/i18n/locales/{uz,ru,en}.yml` |
| Backend xato matni (log, worker) | Tarjima qilinmaydi (inglizcha) | — |

**Qoida:** backend xodim interfeysi matnini yubormaydi — faqat kod va ma'lumot. Xaridorga boradigan matnni esa backend yaratadi, chunki u Telegram/Instagram orqali frontend'siz yetkaziladi.

### 8.4 Backend tarjima fayllari

```yaml
# app/shared/i18n/locales/uz.yml
export:
  orders:
    columns: {number: "Raqam", status: "Holat", total: "Jami", created_at: "Sana"}
status:
  order: {CONFIRMED: "Tasdiqlandi", COMPLETED: "Topshirildi"}
```
`t("export.orders.columns.number", locale)`; topilmasa → `uz` → kalit nomi (faqat dev'da).

### 8.5 Xabar shablonlari (`platform.message_templates`)

Tuzilma — [07](07-data-layer.md) §4.1. Tanlash tartibi: shop override (xaridor tili) → platforma default (xaridor tili) → platforma default (`uz`). Xabarnoma yozuvida ishlatilgan `template_key`, `locale`, `template_version` saqlanadi (BL-060). Matn — ICU MessageFormat, o'zgaruvchilar `{order_number}`, `{total}`.

### 8.6 Format qoidalari (frontend va backend uchun bir xil)

- **ICU MessageFormat** (ko'plik): `"{count, plural, one {# ta buyurtma} other {# ta buyurtma}}"` (uz), `"{count, plural, one {# заказ} few {# заказа} many {# заказов} other {# заказа}}"` (ru).
- **Kalit nomlash:** `<soha>.<ekran>.<element>` — `orders.detail.confirm_button`; xatolar `errors.<CODE>`; maydon xatolari `validation.<code>`; holatlar `status.<entity>.<STATUS>`.
- **CI:** `uz`, `ru`, `en` da kalitlar to'plami bir xil; §6.2 dagi har `code` uchun `errors.<CODE>` bor. Yetishmasa — build yiqiladi.
- **Manba til** — `uz`; rus va ingliz tarjimalari PR orqali.

### 8.7 Raqam, sana, pul

- Formatlash faqat ko'rsatishda: frontend `Intl.NumberFormat`/`Intl.DateTimeFormat`; backend shablonlarida Babel.
- UZS: butun so'mga yaxlitlanadi, mingliklar bo'sh joy bilan — `1 250 000 so'm` (uz), `1 250 000 сум` (ru), `UZS 1,250,000` (en).
- USD (DEC-121, faqat xodim ko'radi): `$1,250.00`.
- Sana va vaqt shop timezone'ida (`Asia/Tashkent`): `22.10.2026 14:15`.
- O'zbek apostrofi: saqlashda `ʻ` (U+02BB), `‘` (U+2018), `'` normalizatsiya qilinadi; qidiruvda hammasi bir xil; ko'rsatishda `o‘`, `g‘`.

### 8.8 Frontend: xatoni ko'rsatish

```ts
// packages/i18n — kalit topilmasa umumiy matn; xom `message` hech qachon ko'rsatilmaydi
function errorText(err: ApiError, t: TFunction): string {
  return t(`errors.${err.code}`, { ...err.details, defaultValue: t("errors.UNKNOWN") });
}
```

| `code` | Ko'rinish |
|---|---|
| `VALIDATION_FAILED` | Har maydon ostida (`validation.<code>`, `params` bilan) |
| `VERSION_CONFLICT` | Dialog: "Ma'lumot boshqa foydalanuvchi tomonidan o'zgartirildi" + "Yangilash" |
| `INSUFFICIENT_AVAILABLE_STOCK`, `PRICE_CHANGED`, `APPROVAL_REQUIRED` | Buyurtma/taklif kartochkasida ogohlantirish va keyingi qadam tugmalari |
| `SPEAKER_CONFLICT` | Inbox'da: "Suhbatni boshqa operator oldi" + yangilash |
| `UNAUTHENTICATED` | Jimgina `/auth/refresh`; muvaffaqiyatsiz — login |
| `FORBIDDEN`, `SELF_APPROVAL_NOT_ALLOWED` | "Ruxsat yo'q" holati |
| `RATE_LIMITED`, `PROVIDER_UNAVAILABLE`, `SERVICE_UNAVAILABLE` | Toast + `Retry-After` bo'yicha avtomatik qayta urinish (faqat GET va idempotent) |
| `INTERNAL_ERROR` | Toast + "Murojaat raqami: `trace_id`" (qo'llab-quvvatlash shu raqam bilan logdan topadi) |

---

## 9. Endpoint'lar ro'yxati (Stage 1)

Prefiks `/api/v1/<surface>`. **Idem** — `Idempotency-Key` majburiy. **IfM** — `If-Match` majburiy. Ruxsat kodlari — [10](10-security-tenancy-rbac.md) §6. Aniq sxemalar — OpenAPI'da.

### 9.1 `auth`

1-modulda qurilgan (2026-10-23). Login — telefon + parol; telefon istalgan ko'rinishda kelishi mumkin, `+998XXXXXXXXX` ga keltiriladi.

| Metod va yo'l | Nima | Izoh |
|---|---|---|
| `POST /auth/login` | Kirish → access token + refresh cookie. Tana: `phone`, `password`, `audience` (`shop` / `platform`) | Rate limit (IP + telefon); 5 xato → 15 daqiqa blok (`429 RATE_LIMITED`, `retry_after_seconds`). Bu panelga huquq yo'q — `401` (oddiy "noto'g'ri login") |
| `POST /auth/refresh` | Token yangilash (rotatsiya). Tana: `audience` | Cookie: `cos_refresh_shop` yoki `cos_refresh_platform`; eski token qayta kelsa — butun oila bekor |
| `POST /auth/logout`, `POST /auth/logout-all` | Joriy sessiyani yoki barcha sessiyalarni yopish | |
| `GET /auth/me` | Kim, qaysi shop, rol, ruxsatlar, filiallar | Frontend menyuni shundan quradi |
| `POST /auth/password/change` | Parolni o'zgartirish | Joriy parol so'raladi; boshqa sessiyalar bekor |
| `GET /auth/sessions`, `DELETE /auth/sessions/{id}` | Faol qurilmalar va bittasini yopish | |
| `POST /auth/invites/{token}/accept` | Taklifni qabul qilish: parol o'rnatiladi, darhol kiriladi | Token bir martalik — Idem kerak emas; `404` + `reason`: `invalid`, `used`, `revoked`, `expired` |
| `POST /auth/password-reset/confirm` | Tiklash havolasi bilan yangi parol | Barcha sessiyalar bekor; `404` + `reason` xuddi yuqoridagidek |
| `POST /auth/platform-invites/{token}/accept` | Platforma jamoasiga taklif: parol o'rnatiladi, platforma paneliga kiriladi (`audience: platform`, cookie `cos_refresh_platform`) | Havola `PLATFORM_APP_PUBLIC_URL/invite/...`; `404` + `reason` xuddi yuqoridagidek |
| `POST /auth/platform-password-reset/confirm` | Platforma jamoasi a'zosining yangi paroli | Barcha sessiyalar bekor; `404` + `reason` |
| `POST /auth/ws-ticket` | Shop paneli WebSocket'i uchun bir martalik ticket (30 s) → `{ticket, expires_in, path: "/api/v1/ws"}`; keyin `WS /api/v1/ws?ticket=…` ([08](08-cache-and-realtime.md) §6, 5a) | Bearer; `Cache-Control: no-store` |

Stage 1 da **yo'q**: `POST /auth/password-reset` (xodim o'zi so'rashi — SMS provayder kerak; hozir havolani ega yoki platforma admini beradi), `POST /auth/switch-shop` (bir odam — bitta shop, DEC-131).

### 9.2 `shop` surface — platform modullari

| Metod va yo'l | Ruxsat | Idem / IfM |
|---|---|---|
| `GET /shop/profile`, `PATCH /shop/profile` | `shops.settings.view` / `shops.settings.edit` | — / IfM |
| `POST /shop/profile/submit-for-verification` | `shops.settings.edit` | Idem |
| `GET /shop/policies`, `PATCH /shop/policies` | `shops.settings.view` / `shops.policy.edit` | — / IfM |
| `GET /shop/branches`, `POST /shop/branches`, `PATCH /shop/branches/{id}` | `shops.settings.view` / `shops.branch.edit` | — / Idem / IfM |
| `GET /shop/branches/options` — filial tanlash uchun: `id`, `name`, `status`, `is_pickup_point` (manzil va telefonsiz) | har shop xodimi (filial doirasi bilan) | — |
| `POST /shop/branches/{id}/close` | `shops.branch.edit` | Idem |
| `GET /shop/members` | `staff.member.view` | — |
| `POST /shop/members/invites` | `staff.member.invite` | Idem (takror so'rovda havola qayta beriladi — havola bazada saqlanmaydi) |
| `POST /shop/members/{id}/invites` | `staff.member.invite` — taklifni qayta yuborish | Idem; har chaqiruv yangi havola, eskisi bekor |
| `POST /shop/members/{id}/password-reset` | `staff.member.password_reset` | Idem; har chaqiruv yangi havola (24 soat) |
| `PUT /shop/members/{id}/roles` | `staff.member.edit_roles` | IfM |
| `POST /shop/members/{id}/disable` | `staff.member.disable` | Idem |
| `GET /shop/tasks?status=OPEN&type=&cursor=&limit=` — vazifalar (5a): ega va menejer filial doirasidagi hammasini, operator va omborchi o'ziniki va o'z roliniki; har qatorda `link {route, id}` | `staff.task.view` | — |
| `POST /shop/tasks/{id}/done`, `POST /shop/tasks/{id}/assign` (`{membership_id}`, faqat ega/menejer) | `staff.task.view` | Idem + IfM |
| `GET /shop/notifications?unread=&cursor=&limit=`, `GET /shop/notifications/unread-count`, `POST /shop/notifications/{id}/read`, `POST /shop/notifications/read-all` — xodimning o'z bildirishnomalari (5a) | har shop xodimi (faqat o'ziniki) | — (o'qish tabiatan idempotent) |
| `GET /shop/me/notification-settings`, `PUT /shop/me/notification-settings` — tinch soat, bot, o'chirilgan turlar | har shop xodimi (o'ziniki) | — / IfM (birinchi — `"v0"`) |
| `GET /shop/me/telegram-link`, `POST /shop/me/telegram-link` (201, bir martalik kod + `deep_link`), `DELETE /shop/me/telegram-link` — platforma botiga ulanish (DEC-129) | har shop xodimi (o'ziniki) | — |
| `GET /shop/audit-entries`, `POST /shop/audit-exports` (202) | `audit.entry.view` / `audit.entry.export` | — / Idem |
| `GET /shop/billing/usage` | `billing.plan.view` | — |
| `GET /shop/jobs/{job_id}` | Ishni boshlagan foydalanuvchi yoki ega | — |

### 9.3 `catalog`

Holat: 2-modul backend'i qurilgan (2026-10-25, [progress/M02](progress/M02-catalog.md)). Import va moslik tekshiruvi — 5 va 6-modullar.

| Metod va yo'l | Ruxsat | Idem / IfM |
|---|---|---|
| `GET /shop/categories` | `catalog.product.view` | — |
| `GET /shop/products` (`status=A,B` yoki takroriy `status`, `category`, `q`, `sort`, `limit`, `cursor`), `GET /shop/products/counts`, `GET /shop/products/{id}` | `catalog.product.view` | — |
| `POST /shop/products` (kartochka + ixtiyoriy variantlar va narxlar), `PATCH /shop/products/{id}` | `catalog.product.edit` | Idem / IfM |
| `POST /shop/products/{id}/submit-review` | `catalog.product.edit` | Idem — **keyin** (katalog xodimi roli bilan, DEC-133) |
| `POST /shop/products/{id}/publish` (qoralamadan va yashirilgandan), `/hide` | `catalog.product.publish` | Idem |
| `POST /shop/products/{id}/archive` | `catalog.product.archive` (faqat ega) | Idem |
| `POST /shop/products/{id}/skus`, `PATCH /shop/skus/{id}`, `POST /shop/skus/{id}/archive` | `catalog.product.edit` | Idem / IfM (SKU versiyasi; javob `ETag` — ham SKU versiyasi) / Idem |
| `POST /shop/products/{id}/media` (`file_id`), `DELETE …/media/{media_id}`, `PUT …/media/order` | `catalog.product.edit`. Bitta fayl — bitta mahsulot: boshqa mahsulotdagi faylni ulash — `FILE_IN_USE` | Idem / — / — |
| `PUT /shop/skus/{id}/price`, `GET /shop/skus/{id}/price-history` | `catalog.price.change` / `catalog.price.view` | Idem + IfM (birinchi narx — `"v0"`) / — |
| `GET /shop/exchange-rates`, `GET /shop/exchange-rates/{id}`, `POST /shop/exchange-rates` (`Location`) | `catalog.price.view` / `catalog.exchange_rate.edit` | — / Idem |
| `POST /shop/catalog/imports` (multipart), `GET /shop/catalog/imports/{id}`, `PUT …/{id}/mapping`, `POST …/{id}/dry-run` (202), `GET …/{id}/errors.csv` | `catalog.import.run` | Idem (POST'lar) — 5-modul |
| `POST /shop/catalog/imports/{id}/commit` (202) | `catalog.import.commit` (+ `quantity` bo'lsa `commerce.stock.receive`) — [18](18-catalog-import.md) §13 | Idem — 5-modul |
| `GET /shop/hardware-specs?q=&category=`, `GET /shop/skus/{id}/spec-candidates` | `catalog.product.view` | — |
| `PUT /shop/skus/{id}/spec-link`, `DELETE …/spec-link`, `POST /shop/skus/auto-link` | `catalog.spec.link`. Qo'lda uzilgan bog'lanishni avtomatika qayta tiklamaydi (`spec_autolink_blocked`), qo'lda bog'lash taqiqni oladi; ikkalasi SKU versiyasini oshiradi | — (bir xil natija) / — / Idem |
| `GET /shop/hardware-spec-requests`, `GET /shop/hardware-spec-requests/{id}`, `POST /shop/hardware-spec-requests` (`Location`) | `catalog.spec.link`. `sku_id` bo'lsa — `category` shu SKU mahsuloti turi bilan bir xil (`category/invalid_choice`, `params.expected`), arxivdagisi uchun so'rov yo'q | — / Idem |
| `POST /shop/files?purpose=PRODUCT_IMAGE&filename=…` (tana — fayl baytlari), `GET /shop/files/{id}` | maqsadga qarab (`catalog.product.edit`) | Idem / — |
| `GET /public/files/{key}` | ochiq fayl — hamma; yopiq — `?exp=&sig=` (5 daqiqa) | — |
| `POST /shop/pc-builds/check` | `catalog.compatibility.check` | Idem (natija saqlanmaydi; taklifda snapshot — `commerce`) — 6-modul |

### 9.4 `commerce`

Holat: 3-modul backend'i qurilgan (2026-10-26, [progress/M03](progress/M03-commerce.md)): ombor, tez sotuv, buyurtmalar. Lead va PC taklifi — 6-modul.

| Metod va yo'l | Ruxsat | Idem / IfM |
|---|---|---|
| `GET /shop/stock` (`branch_id`, `sku_id`, `q`, `low_only`, cursor), `GET /shop/stock/history?sku_id=&branch_id=` | `commerce.stock.view` (filial doirasi) | — |
| `GET /shop/skus` (`q`, `branch_id`, `limit` ≤ 50) — SKU tanlash: nom, kod, holat, joriy narx, `orderable` / `quick_sellable`, `branch_id` berilsa — sotuvga mavjud son | `catalog.product.view` | — |
| `POST /shop/stock/receipts` (`Location`), `GET /shop/stock/receipts`, `GET …/{id}` | `commerce.stock.receive` / `commerce.stock.view` | Idem / — |
| `POST /shop/stock/adjustments` (`Location`; omborchida PENDING, ega/menejerda darhol APPROVED — DEC-134; arxivdagi SKU — faqat kamaytiruvchi: `ADJUSTMENT` < 0, `QUARANTINE_IN`, `WRITE_OFF`), `GET /shop/stock/adjustments` (`status`, `branch_id`), `GET …/{id}` | `commerce.stock.adjust_request` | Idem / — (takror so'rovda yangi imzoli havola; havola bazada saqlanmaydi) |
| `POST /shop/stock/adjustments/{id}/approve` (qoldiq qayta tekshiriladi), `POST …/{id}/reject` (`note` majburiy) | `commerce.stock.adjust_approve` | Idem + IfM |
| `POST /shop/quick-sales` (`Location`), `GET /shop/quick-sales` (`branch_id`, `mine`), `GET …/{id}` | `commerce.quick_sale.create` | Idem / — |
| `GET /shop/leads`, `POST /shop/leads`, `PATCH /shop/leads/{id}` | `commerce.lead.view` / `commerce.lead.edit` | — / Idem / IfM |
| `GET /shop/quotes`, `GET /shop/quotes/{id}` | `commerce.quote.view` | — |
| `POST /shop/quotes`, `POST /shop/quotes/{id}/revisions`, `POST …/{id}/submit` | `commerce.quote.draft` | Idem |
| `POST /shop/quotes/{id}/approve`, `POST …/{id}/return-to-draft` | `commerce.quote.approve` | Idem + IfM |
| `POST /shop/quotes/{id}/send` | `commerce.quote.send` | Idem |
| `GET /shop/orders` (`status=A,B`, `branch_id`, `assigned=me\|unassigned\|<membership_id>`, `q` — raqam/telefon/ism, `needs_review`, `sort`, cursor), `GET /shop/orders/counts`, `GET /shop/orders/review-queue` (24/72 soat), `GET /shop/orders/{id}` (`ETag`, `allowed_actions`; `DRAFT`/`PENDING_CONFIRMATION` da filial tanlangan bo'lsa qatorlarda `available_in_branch` va `available_qty` — filialdagi sotuvga mavjud, bitta so'rov; boshqa holatda `null`) | `commerce.order.view` (operator — o'ziniki + biriktirilmagan; omborchi — tasdiqlanganlar) | — |
| `POST /shop/orders` (`DRAFT`, `Location`), `PATCH /shop/orders/{id}` (filial almashsa — mas'ul xodim yangi filialda ham ishlashi shart, aks holda `branch_id/out_of_scope`) | `commerce.order.create_draft` | Idem / IfM |
| `POST /shop/orders/{id}/lines` (`Location` — buyurtma), `PATCH …/lines/{line_id}`, `DELETE …/lines/{line_id}` — faqat `DRAFT`/`PENDING_CONFIRMATION` (DEC-134) | `commerce.order.create_draft` | Idem + IfM (buyurtma versiyasi) / IfM / IfM |
| `PUT /shop/orders/{id}/lines/{line_id}/discount` (`discount_pct`; limitgacha — darhol, undan ko'pi — so'rov) | `commerce.discount.apply` yoki `commerce.discount.request` | IfM |
| `POST /shop/orders/{id}/lines/{line_id}/discount/approve`, `…/reject` | `commerce.discount.approve` (limit — `DISCOUNT_LIMIT_EXCEEDED`) | Idem + IfM |
| `POST /shop/orders/{id}/submit` (→ `PENDING_CONFIRMATION`), `POST …/{id}/refresh-prices` (`note` → qo'ng'iroq natijasi izohi) | `commerce.order.create_draft` | Idem + IfM |
| `POST /shop/orders/{id}/confirm` (qoldiq + narx qayta tekshiriladi, band qilinadi) | `commerce.order.confirm` (operator — o'ziniki) | Idem + IfM |
| `POST /shop/orders/{id}/start-processing`, `POST …/{id}/mark-ready` (holat o'zgarmaydi; `ready_at`, `ready_by` va `transition_log` da `MARK_READY` — tarixda kim bosgani ko'rinadi), `POST …/{id}/exception` (`reason`) | `commerce.order.process` | Idem + IfM |
| `POST /shop/orders/{id}/complete` | `commerce.order.complete` | Idem + IfM |
| `POST /shop/orders/{id}/cancel` (`reason` — qoralamadan tashqari majburiy) | `commerce.order.cancel`; qoralamani — `create_draft` egasi ham | Idem + IfM |
| `POST /shop/orders/{id}/resolve-exception` (`resolution`: `PROCESSING`/`CANCELLED`), `POST …/{id}/review-decision` (`decision`: `WAIT`/`CANCEL`, 72 soat — DEC-134) | `commerce.order.cancel` | Idem + IfM |
| `POST /shop/orders/{id}/take` (biriktirilmaganini o'ziga olish), `POST …/{id}/assign` (`membership_id` yoki `null`; xodimning filial doirasi buyurtma filialini qamrashi shart — aks holda 422 `invalid_choice`) | `commerce.order.confirm` / `commerce.order.assign` | Idem + IfM |
| `POST /shop/orders/{id}/paid-mark` (bir marta) | `commerce.order.paid_mark` | Idem |
| `POST /shop/orders/{id}/notes` (`Location` — buyurtma kartochkasi) | `commerce.order.note` | Idem |
| `GET /shop/orders/{id}/history` — holat tarixi: kim (ism), qachon, `command`, `from_status → to_status`, sabab (xaridor ma'lumotisiz) | `commerce.order.view` | — |

Buyurtma javobida xaridor telefoni va manzili bor — takroriy so'rov himoyasi faqat ID'ni saqlaydi, takror kelgan so'rov buyurtmaning **joriy** holatini qaytaradi (26 §4). Omborchiga telefon yashirilgan holda, manzil faqat yetkazishda (10 §6.8). Telefon: harf bo'lsa yoki `+998` bilan 12 raqam bo'lmasa — `invalid_format`; 9 raqam — faqat mamlakat kodisiz.

### 9.5 `messaging`

| Metod va yo'l | Ruxsat | Idem / IfM |
|---|---|---|
| `GET /shop/channels`, `GET /shop/channels/{id}` | `messaging.channel.view` | — |
| `POST /shop/channels/telegram` `{token}` — `getMe`, webhook (yoki lokalda polling); token javobda va takror so'rov yozuvida yo'q | `messaging.channel.connect` | Idem |
| `POST /shop/channels/webchat` — sayt chatini yoqish (bor bo'lsa o'shani qaytaradi) | `messaging.channel.connect` | — |
| `POST /shop/channels/instagram` `{access_token}` — faqat `FEATURE_CHANNEL_INSTAGRAM_DM` yoqilganda (aks holda 404); OAuth — keyin | `messaging.channel.connect` | — |
| `POST /shop/channels/{id}/disconnect` | `messaging.channel.connect` | IfM |
| `GET /shop/conversations?status=A,B&channel=&assigned=me\|unassigned\|<membership_id>&unread=&tag=&q=&cursor=&limit=`, `GET …/counts`, `GET …/{id}` (ETag), `GET …/{id}/messages?before_seq=\|after_seq=&limit=` | `messaging.conversation.view` | — |
| `POST /shop/conversations/{id}/messages` `{body \| attachment_file_id}` → 201 | `messaging.conversation.reply` (+ `takeover`, suhbat hali uniki bo'lmasa) | Idem |
| `POST /shop/conversations/{id}/take` | `messaging.conversation.takeover` | IfM |
| `POST /shop/conversations/{id}/assign` `{membership_id}` (o'tkazish ham shu) | `messaging.conversation.assign` | IfM |
| `POST /shop/conversations/{id}/resolve`, `POST …/{id}/reopen` | `messaging.conversation.resolve` | IfM |
| `POST /shop/conversations/{id}/read` `{seq}` (versiya oshmaydi), `PUT …/{id}/tags` (IfM), `GET/POST …/{id}/notes` | `messaging.conversation.view` / `reply` | — |
| `GET /shop/conversations/{id}/orders`, `POST …/{id}/orders` (qoralama → 201, `Location`), `POST …/{id}/orders/link` `{order_id, relink?, expected_version?}` (boshqa suhbatdagi buyurtma — 409 `ORDER_LINKED_ELSEWHERE`) | `messaging.conversation.view` / `commerce.order.create_draft` | Idem (qoralama va bog'lash) |
| `GET /shop/message-templates`, `PUT …/{template_key}/{locale}` `{body}`, `DELETE …/{template_key}/{locale}` (standartga qaytarish) | `shops.settings.view` / `shops.settings.edit` | — |

**5b holati (2026-10-26):** yuqoridagi jadval qurilgan endpointlar ([progress/M05b](progress/M05b-messaging.md)). Rejadan farqlar: `…/takeover` → `…/take`; `resume-ai` — 6-modul (AI) bilan; javobda `speaker_version` talab qilinmaydi (operator javobi fencing'ni o'zi bajaradi: suhbatni oladi); Instagram OAuth o'rniga flag ostidagi `POST`. Xato kodlari: kanal yo'q yoki uzilgan — `CHANNEL_UNAVAILABLE`; bot tokeni noto'g'ri — `422 token/invalid`, boshqa shopda ulangan — `422 token/already_connected`; Telegram javob bermadi — `PROVIDER_UNAVAILABLE`; shablonda o'zgaruvchi yetishmaydi yoki noma'lum — `422 body/missing_variables`, `body/unknown_variables`; yolg'iz qavs — `body/invalid_braces`; `{0}`, `{a.b}`, `{a!r}`, `{a:>9}` — `body/invalid_placeholder` (QA 5b H1). Buyurtmalar ro'yxatida aniq raqam — `GET /shop/orders?number=1042`. Dev/test: `900000001:TEST…` ko'rinishidagi Telegram tokeni — soxta bot (tarmoqsiz, `is_fake: true`), faqat `APP_ENV=local|test`.

### 9.6 `sales_ai`

| Metod va yo'l | Ruxsat | Idem / IfM |
|---|---|---|
| `GET /shop/ai/settings`, `PATCH /shop/ai/settings` (rejim: `OFF/SUGGEST/AUTO`) | `sales_ai.settings.view` / `sales_ai.settings.edit` | — / IfM |
| `GET /shop/ai/knowledge`, `POST /shop/ai/knowledge`, `PATCH /shop/ai/knowledge/{id}` | `sales_ai.settings.view` / `sales_ai.knowledge.edit` | — / Idem / IfM |
| `POST /shop/ai/knowledge/{id}/publish`, `POST …/{id}/rollback` | `sales_ai.knowledge.publish` | Idem |
| `POST /shop/ai/sandbox/messages` | `sales_ai.knowledge.test` | Idem |

### 9.7 `storefront` (4-modul, DEC-135 — [progress/M04](progress/M04-storefront.md))

| Surface | Metod va yo'l | Ruxsat | Idem |
|---|---|---|---|
| shop | `GET /shop/storefront` — sozlamalar, `state` (xaridor nima ko'radi), `site_url`, `publish_problems`; saqlanmagan bo'lsa `version: 0` | `storefront.site.view` (ega, menejer) | — |
| shop | `PATCH /shop/storefront` — logotip (`logo_file_id`, fayl turi `SITE_LOGO`), rang, fon, shior, SEO matni, telefon, email, Telegram/Instagram username. Birinchi saqlash `If-Match: "v0"`; yuborilmagan maydon o'zgarmaydi | `storefront.site.edit` (faqat ega) | IfM |
| shop | `POST /shop/storefront/publish` (DRAFT → LIVE, telefon majburiy), `…/pause` (LIVE → PAUSED), `…/resume` (PAUSED → LIVE) | `storefront.site.edit` | IfM + Idem |
| shop | `POST /shop/storefront/preview` — 30 daqiqalik ko'rib chiqish tokeni va `preview_url` (`{shop}.{exp}.{nonce}.{sig}`, bazada saqlanmaydi; har chiqarishda boshqa token) | `storefront.site.view` | Idem |
| shop | `GET /shop/storefront/pages` (uchala tur), `PUT /shop/storefront/pages/{ABOUT\|DELIVERY_PAYMENT\|WARRANTY_RETURNS}` — Markdown, HTML yo'q | view / edit | IfM (`"v0"` — birinchi) |
| storefront | `GET /storefront/{slug}/site` — `state` (`LIVE`, `COMING_SOON`, `PAUSED`); ochiq bo'lsa ko'rinish, kontaktlar, sahifalar menyusi, `delivery_enabled`, `stock_display`, `pickup_branch_count`, `consent` (`version`, `text`), `legal` | Ommaviy | — |
| storefront | `GET …/categories`, `GET …/products?category=&q=&sort=newest\|price_asc\|price_desc&limit=&cursor=`, `GET …/products/{product_id}` (id bo'yicha; javobda `slug` va `canonical_path` `/p/{id}/{slug}`), `GET …/pages/{kind}`, `GET …/branches`, `GET …/privacy` | Ommaviy; sayt ochiq bo'lmasa — `SITE_NOT_AVAILABLE` | — |

Ommaviy o'qish: IP + shop bo'yicha 120/daq (IP — `X-Forwarded-For` faqat ishonchli proksidan: nginx va sayt serveri, `TRUSTED_PROXIES`; [22](22-infrastructure-and-deployment.md) §8), sayt javoblarida `Access-Control-Allow-Credentials` hech qachon yo'q, READ ONLY tranzaksiya, shop konteksti (RLS), faqat ruxsat etilgan maydonlar (TC-SEC-09). Ega ko'rib chiqish tokenini `X-Storefront-Preview` header'ida yoki `?preview=` da yuboradi — sayt qoralama yoki to'xtatilgan bo'lsa ham o'qiladi, buyurtma formasi esa o'chiq.

### 9.8 `commerce` va `messaging` — storefront surface

| Metod va yo'l | Domen | Izoh |
|---|---|---|
| `POST /storefront/{slug}/order-requests` | commerce | Savatcha → buyurtma so'rovi: darhol `PENDING_CONFIRMATION`, biriktirilmagan, band qilinmaydi, to'lovsiz (DEC-115, DEC-100b). Majburiy: `consent_version` (joriy versiya), olib ketishda `branch_id` (ochiq olib ketish joyi), yetkazishda `delivery_address` (`delivery_enabled` bo'lsa). Idem (`Idempotency-Key` = `orders.source_request_id`): takror — o'sha buyurtma, yangi `tracking_token`. Javob 201: `number`, `status: RECEIVED`, `tracking_token`, `tracking_path`, qatorlarda `available_in_branch`. Chegara: IP + shop + telefon — 10 daqiqada 5, IP + shop — 20 |
| `GET /storefront/{slug}/orders/{tracking_token}` | commerce | Faqat o'z buyurtmasi: raqam, xaridorga ko'rinadigan holat (`RECEIVED`, `CONFIRMED`, `PREPARING`, `READY`, `COMPLETED`, `CANCELLED`), qatorlar, summa, olib ketish filiali. Telefon, manzil, izoh yo'q. Bazada tokenning faqat SHA-256 xeshi; noto'g'ri token — 404. 30/daq per IP |
| `GET /storefront/{slug}/quotes/{token}`, `POST …/quotes/{token}/accept`, `POST …/quotes/{token}/reject` | commerce | Taklif havolasi (FSM-06 `SENT → ACCEPTED/REJECTED`). Idem |
| `POST /storefront/{slug}/chat/sessions` → `{token, expires_at, poll_interval_seconds}`, `GET …/chat/messages?after_seq=`, `POST …/chat/messages` `{client_message_id, body}`, `POST …/chat/contact` `{name?, phone?, consent: true}` → 204 (ism yoki telefon majburiy; `notice_version` yoziladi) | messaging | Saytdagi chat (5b): faqat LIVE sayt; token header'da — `X-Chat-Session` (sayt ilovasi httpOnly cookie'dan uzatadi); mehmon tili — `X-Customer-Locale` (yoki `Accept-Language`); rasmli xabarda `image_url` (imzoli, 5 daq); javoblar polling bilan (4 s), SSE — keyin ([08](08-cache-and-realtime.md) §6.6). Chegaralar: sessiya 10/soat per IP, o'qish 120/daq per IP + sessiya, yozish 20/daq per IP va 10/daq per sessiya; boshqa shop sessiyasi — 404. `GET /storefront/{slug}/site` da `chat_enabled` |

### 9.9 `support` va `reporting`

| Metod va yo'l | Ruxsat | Idem / IfM |
|---|---|---|
| `GET /shop/support-cases`, `GET …/{id}` | `support.case.view` | — |
| `POST /shop/support-cases`, `POST …/{id}/start-review` | `support.case.create` | Idem |
| `POST /shop/support-cases/{id}/approve`, `POST …/{id}/reject` | `support.case.decide` | Idem + IfM |
| `POST /shop/support-cases/{id}/start-service`, `POST …/{id}/resolve`, `POST …/{id}/close` | `support.case.service` | Idem + IfM |
| `GET /shop/reports/summary`, `POST /shop/reports/queries` | `reporting.report.read` (+ `reporting.margin.read` foyda, `reporting.staff_breakdown.read` xodimlar kesimi, `reporting.ai_cost.read` AI xarajati) | — / Idem |
| `POST /shop/reports/assistant/messages` | `reporting.assistant.ask` | Idem |
| `POST /shop/reports/voice/transcriptions` (beta, 202, arq `voice_transcribe`) | `reporting.assistant.ask` + flag `reporting.voice` | Idem |
| `POST /shop/reports/exports` (202) | `reporting.export.run` | Idem |

### 9.10 `webhooks` va `platform`

| Metod va yo'l | Izoh |
|---|---|
| `POST /webhooks/telegram/{account_ref}` | `X-Telegram-Bot-Api-Secret-Token` tekshiriladi |
| `POST /webhooks/platform-telegram` | Platforma boti (xodimlar): faqat `/start <kod>` — ulash. `X-Telegram-Bot-Api-Secret-Token` = `PLATFORM_TELEGRAM_WEBHOOK_SECRET` (doimiy vaqtda); sozlanmagan bo'lsa `404`. Javob doim `200 {"ok": true}` (5a) |
| `GET /webhooks/meta` (verify), `POST /webhooks/meta` | `X-Hub-Signature-256`; sahifa/akkaunt ID → `channel_accounts` |
| `POST /platform/shops` | `platform.shop.create`; shop + ega taklifi bitta tranzaksiyada, javobda ega havolasi. Idem. Tizim nomlari (`login`, `admin`, `api`, `www`, ...) slug sifatida band — `not_unique` |
| `GET /platform/dashboard` | `platform.shop.view_meta` — bosh sahifa ([business/15](../business/15_PLATFORM_ADMIN_PANEL.md) §1): `counts_by_status`, `review_queue` (eng uzoq kutayotgan birinchi, `waiting_days`), `pending_owners` (`invite_state`: `expired` / `expiring` <24 soat / `valid`), `pilots` (`day`, `days_left`, `ending_soon` ≤7 kun), `new_shops_7d/30d`, `recent_activity` (oxirgi 10 ta platforma amali, `auth.*` siz) |
| `GET /platform/shops` | `platform.shop.view_meta`. `q` (nomi, slug, STIR yoki ega telefoni istalgan ko'rinishda), `status` (bir nechta), `sort` (`created_desc` / `activated_desc` / `name`), `limit` ≤100, `offset`. Javob: `items[]` (+ `owner_name`, `owner_status`, `staff_count`, `branch_count`, `last_activity_at`) va `total` |
| `GET /platform/shops/{id}` | `platform.shop.view_meta`, `ETag`. Kartochkada `owners[]` (ism, telefon, holat, `membership_id`) — ega bilan bog'lanish va parol tiklash uchun |
| `PATCH /platform/shops/{id}` | `platform.shop.edit`, IfM. `name`, `legal_name`, `tin`, `default_locale` + `reason` (majburiy). Slug o'zgarmaydi. Audit'da o'zgargan maydonlar; STIR qiymati yozilmaydi |
| `GET /platform/shops/{id}/members`, `…/branches`, `…/history`, `…/audit` | `platform.shop.view_meta` — kartochka bo'limlari: xodimlar (oxirgi kirish bilan), filiallar, holat tarixi (FSM-01, kim va nega), shop jurnali (`limit`/`offset`, `total`; qiymatlarsiz — faqat `changed_fields`) |
| `GET /platform/shops/{id}/notes`, `POST /platform/shops/{id}/notes` | `platform.shop.view_meta` / `platform.shop.note` — ichki izoh, shop ko'rmaydi. `body` 1–2000 belgi; faqat qo'shiladi (tahrir/o'chirish yo'q); auditda matn yo'q. POST — Idem |
| `GET /platform/staff` | `platform.staff.view` — jamoa: `id`, `full_name`, `phone`, `role`, `status` (`INVITED`/`ACTIVE`/`DISABLED`), `last_login_at`, `invited_by_name`, `version` |
| `POST /platform/staff/invites` | `platform.staff.manage` — `{phone, full_name, role}` → `{member, invite}`; telefon band bo'lsa `phone/not_unique`; havola idempotency'da saqlanmaydi (takrorda yangisi). Idem |
| `POST /platform/staff/{id}/invite`, `POST /platform/staff/{id}/password-reset` | `platform.staff.manage` — taklifni qayta berish (faqat `INVITED`) / parol tiklash havolasi (faqat `ACTIVE`, 24 soat); eskilari bekor. Idem |
| `PUT /platform/staff/{id}/role` | `platform.staff.manage` — IfM; oxirgi faol admin rolini olib bo'lmaydi (`LAST_ADMIN_REQUIRED`) |
| `POST /platform/staff/{id}/disable` | `platform.staff.manage` — platforma sessiyalari va havolalari darhol bekor; o'zini o'chirib bo'lmaydi (`FORBIDDEN`); oxirgi faol admin himoyalangan. Idem |
| `GET /platform/audit` | `platform.shop.view_meta` — platforma jamoasi amallari jurnali. Filtr: `shop_id`, `actor_id`, `action` (boshlanishi), `date_from`, `date_to`; `limit`/`offset`, `total` |
| `POST /platform/shops/{id}/members/{membership_id}/invite` | `platform.shop.create` — ega taklifini qayta berish (72 soat o'tgan bo'lsa). Har chaqiruv yangi havola, eskisi bekor. Idem |
| `POST /platform/shops/{id}/activate`, `…/reactivate`, `…/suspend`, `…/close` | `platform.shop.activate` (activate, reactivate) / `.suspend` / `.close`; suspend, reactivate va close uchun sabab majburiy. Ochiq buyurtmali shop yopilmaydi — `SHOP_HAS_OPEN_ORDERS` (TC-023). Idem |
| `POST /platform/shops/{id}/members/{membership_id}/password-reset` | `platform.member.password_reset` — faqat shop egasi uchun. Idem |
| `GET /platform/hardware-specs`, `GET …/review-queue`, `GET …/{id}` (versiyalar bilan), `GET /platform/hardware-spec-requests` | `platform.spec.view` |
| `POST /platform/hardware-specs` (qoralama + 1-taklif), `POST …/{id}/versions` (o'zgarish taklifi), `POST …/{id}/versions/{n}/approve` / `reject`, `POST …/{id}/retire`, `POST /platform/hardware-spec-requests/{id}/resolve` / `reject` | `platform.spec.edit`. O'z taklifini tasdiqlab bo'lmaydi — `SELF_APPROVAL_NOT_ALLOWED` (17 §10). Hal qilishda SKU hozir ham faol va turi model turi bilan bir xil bo'lishi shart (navbatda `sku_spec_category`). Ro'yxatlar hozircha `offset` bilan (§4.1 dan chetlanish, M02). Idem |
| `GET /platform/catalog/categories`, `GET …/{code}`, `POST …`, `PATCH …/{code}` | ko'rish — har platforma xodimi; yozish — `platform.category.edit` (DEC-133) |
| `POST /platform/support-grants` | Break-glass so'rovi ([10](10-security-tenancy-rbac.md) §9) |
| `GET /platform/dead-letters?status=OPEN&limit=` | `platform.dead_letter.view` — bajarib bo'lmagan fon ishlari (05 §7): event turi, tinglovchi, urinishlar, xato turi (matnsiz); `open_count` (5a) |
| `POST /platform/dead-letters/{id}/replay`, `POST /platform/dead-letters/{id}/ignore` (`{note}` 3–500) | `platform.dead_letter.replay` — faqat `OPEN` dan; audit. Qayta yuborishni `outbox_reconcile` rejali ishi bajaradi (5 daqiqa ichida) |
| `GET /platform/jobs` | `platform.dead_letter.view` — har rejali ishning oxirgi holati, oxirgi muvaffaqiyati, xatosi va `details` (`platform.job_runs`) |
| `POST /platform/kill-switches` (`channel`, `ai`, `shop`) | `platform.channel.kill` / `platform.ai.kill` ([25](25-operations-runbooks.md)) |

**DEFERRED:** to'lov (`/shop/payments/*`) va yetkazish (`/shop/shipments/*`) yo'llari Stage 1 da yo'q; feature flag bilan qo'shilsa ham yoqilmaguncha `501 FEATURE_NOT_AVAILABLE`.

### 9.11 Misol: buyurtmani tasdiqlash

```http
POST /api/v1/shop/orders/0192b6f0-…/confirm
Authorization: Bearer eyJ…
Idempotency-Key: 7c1e5a0e-3b5f-4c1d-9a51-2b7e1f0c9d11
If-Match: "v3"
```
```json
200 OK
{"id": "0192b6f0-…", "number": 1042, "status": "CONFIRMED", "fulfillment_method": "PICKUP",
 "lines": [{"sku_id": "…", "qty": 1, "unit_price": {"amount_minor": 384000000, "currency": "UZS"},
            "reservation": {"status": "ACTIVE", "review_at": "2026-10-25T14:00:00Z"}}],
 "paid_mark": null, "version": 4}
```
Takror (bir xil key) — xuddi shu javob. Qoldiq yetmasa — `409 INSUFFICIENT_AVAILABLE_STOCK` ([12](12-concurrency-and-transactions.md)).

---

## 10. OpenAPI va frontend client

- **Backend — yagona manba.** CI `openapi-v1.json` ni generatsiya qiladi va commit SHA bilan artefakt sifatida saqlaydi.
- Frontend `packages/api-client` — shundan generatsiya (qo'lda yozilmaydi). Mos kelmaydigan o'zgarish — CI yiqiladi, frontend qayta generatsiya va e2e o'tguncha.
- `X-Request-ID`, `traceparent`, `Idempotency-Key`, `If-Match` — qayta ishlatiladigan komponentlar; har yozish endpoint'ida 409 va 422 misollari.
- Enum'lar sxemada; frontend noma'lum qiymat uchun `UNKNOWN` fallback.
- Buzuvchi o'zgarish (maydonni olib tashlash, ma'nosini o'zgartirish) — `/v2` yoki deprecation oynasi (kamida 1 reliz).
- Ommaviy hujjatlarda `platform` va ichki operatsiyalar yo'q.
- Frontend ishni backend'dan oldin boshlashi uchun — OpenAPI'dan mock server.

---

## 11. Qabul testlari

| ID | Sinov | Kutilgan natija |
|---|---|---|
| TC-CONV-01 | Noto'g'ri tana bilan POST | 422 `VALIDATION_FAILED`, `details.fields[]`, FastAPI `detail` formati yo'q |
| TC-CONV-02 | Mavjud bo'lmagan yo'l va noto'g'ri metod | 404 / 405, ikkalasi envelope'da |
| TC-CONV-03 | Handler ichida kutilmagan exception | 500 `INTERNAL_ERROR`, stack trace yo'q, Sentry'da hodisa, log'da `trace_id` |
| TC-CONV-04 | §6.2 dagi har kod uchun `errors.<CODE>` `uz/ru/en` da; `DomainError` klassi va status lug'ati bor | CI o'tadi; bittasi yo'q — yiqiladi |
| TC-CONV-05 | `Accept-Language: ru`, profil tili yo'q | `ActorContext.locale = ru`; eksport sarlavhalari ruscha |
| TC-CONV-06 | Xaridor kirillcha yozadi | AI va xabarnoma kirillcha; sayt interfeysi lotincha |
| TC-CONV-07 | Bir xil `Idempotency-Key` bilan 2 POST | Ikkinchisi birinchining natijasi; boshqa tana bilan — 409 `IDEMPOTENCY_KEY_REUSED` |
| TC-CONV-08 | Webhook: imzo noto'g'ri / DB ishlamayapti / takror event | 401 / 503 / 200 |
| TC-API-01 | Boshqa shop ID'si bilan har endpoint | 404, ma'lumot yo'q (= TC-ISO-01) |
| TC-API-02 | `If-Match` eskirgan | 409 `VERSION_CONFLICT`, `details.current_version` |
| TC-API-03 | Muddati o'tgan taklifni qabul qilish | 409 `QUOTE_EXPIRED` |
| TC-API-04 | Taklif tasdiqlangach narx o'zgardi, buyurtma tasdiqlanadi | 409 `PRICE_CHANGED` (= TC-031) |
| TC-API-05 | 202 ish + `GET /shop/jobs/{id}` | Holat `SUCCEEDED`, boshqa shop ishi — 404 |
| TC-API-06 | Ruxsat matritsasi: har endpoint × har rol | [10](10-security-tenancy-rbac.md) §6 ga mos (avtomatik) |
| TC-API-07 | Ikki domen bir xil yo'lni e'lon qiladi | Boot xatosi |

## Keyingi qadam

→ [12-concurrency-and-transactions.md](12-concurrency-and-transactions.md) — tasdiqlash va band qilish ichki mexanizmi
→ [21-frontend.md](21-frontend.md) — frontend client va xatolarni ko'rsatish
