# 21 — Frontend arxitekturasi va sahifa kontraktlari

> **Versiya:** v2 (2026-10-22). Eski `18_FRONTEND_ARCHITECTURE_AND_UI` o'rnini bosadi. DEC-014 / ADR-010 (ikki Next.js app), DEC-008 / ADR-023 (auth), DEC-124 (`shop`).
> **Kim o'qiydi:** frontend dasturchi, backend dasturchi (API kontraktlari uchun).
> **Holat (2026-10-23):** `ai-commerce-frontend` da 1-modul qurilgan: `shop-dashboard`, `platform-admin`, umumiy paketlar va e2e. Nima qilingani — [progress/M01](progress/M01-auth-shops-staff.md) §8.
> **Biznes manbai:** sahifalar va oqimlar — [../business/06](../business/06_UI_SITEMAP_AND_USER_FLOWS.md), rollar — [../business/04](../business/04_ROLES_PERMISSIONS_AND_APPROVALS.md).

## 1. Muammo va yechim

**Muammo:** frontend backend'dan alohida yoziladi. Agar API turlari qo'lda takrorlansa, ular tez orada farqlanadi; agar ruxsatlar faqat UI'da tekshirilsa, tenant izolyatsiyasi buziladi; agar har sahifa xatolarni o'zicha ko'rsatsa, foydalanuvchi "nima bo'ldi" ni tushunmaydi.

**Yechim:**
1. Alohida repo, bitta pnpm workspace, uch Next.js app: shop paneli, shop sayti va platforma paneli.
2. API client **faqat OpenAPI'dan generatsiya** qilinadi.
3. Ruxsat UI'da — faqat qulaylik uchun; haqiqiy tekshiruv backend'da (`10-security-tenancy-rbac.md`).
4. Har sahifa bir xil holatlar modeli (§6) va bir xil xato envelope'ini (K-07) ishlatadi.

---

## 2. Repo tuzilmasi

```
ai-commerce-frontend/
├── apps/
│   ├── shop-dashboard/                  # app.<platforma>.uz/{shop}/... — xodimlar paneli (auth)
│   │   └── src/app/
│   │       ├── (auth)/login/
│   │       └── (workspace)/[shop]/
│   │           ├── overview/  setup/  inbox/  orders/  leads/  pc-builder/
│   │           ├── catalog/  prices/  inventory/  support/  reports/
│   │           ├── storefront/  channels/  team/  branches/  notifications/
│   │           ├── settings/ai/  settings/billing/  audit/
│   │           # payments/, fulfillment/ — DEFERRED (DEC-100, DEC-113)
│   ├── shop-storefront/                 # {shop}.<platforma>.uz — shop sayti (4-modulda)
│   └── platform-admin/                  # admin.<platforma>.uz — platforma jamoasi: shop yaratish, holatlar (1-modul)
│       └── src/app/
│           ├── page.tsx                 # / — katalog
│           ├── p/[product]/             # mahsulot
│           ├── cart/                    # savatcha → buyurtma so'rovi
│           ├── quote/[code]/            # PC taklifi
│           └── orders/[code]/           # buyurtma holati
├── packages/
│   ├── ui/                              # dizayn tokenlari, accessible komponentlar
│   ├── api-client/                      # OpenAPI'dan generatsiya — QO'LDA YOZILMAYDI
│   ├── auth/                            # sessiya (token xotirada), silent refresh, login/taklif/parol/profil ekranlari
│   ├── app-kit/                         # umumiy: so'rovlar keshi, xatolarni ko'rsatish, til tanlash
│   ├── i18n/                            # uz/ru/en matnlar, maydon xatolari tarjimasi
│   └── analytics/                       # PII'siz tipli event logger
├── e2e/                                 # Playwright
└── tooling/                             # eslint, tsconfig, CI
```

Bular workspace papkalari, alohida repo'lar emas. Stage 3 dagi ommaviy qidiruv uchun alohida `shopping-web` app keyin qo'shiladi (§10).

---

## 3. Texnologiyalar

| Qatlam | Tanlov | Qoida |
|---|---|---|
| Framework | Next.js 16 (App Router) + React 19 + TypeScript `strict` | Versiyalar aniq qotiriladi; xavfsizlik patch'i chiqsa darhol yangilanadi (`pnpm audit`) |
| Stil | Tailwind + accessible komponentlar (`packages/ui`) | Vendor almashtirish mumkin |
| Server holati | TanStack Query | Mutatsiyadan keyin aniq invalidatsiya |
| Lokal UI holati | Zustand (kichik) | Faqat vaqtinchalik UI holati |
| Formalar | React Hook Form + Zod | Zod sxemalari OpenAPI'dan olinadi yoki generatsiya qilinadi |
| Grafiklar | Recharts yoki ECharts | Faqat hisobotlarda |
| Test | Vitest, Playwright | §9 |

**Taqiqlangan:** pul, qoldiq yoki buyurtma tasdiqlash uchun optimistic update; `localStorage` da token; brauzerda provayder kaliti yoki AI kaliti.

---

## 4. API client va backend bilan kontrakt

```
Backend OpenAPI (/api/v1/openapi.json)
   ──▶ pnpm api:generate                (openapi-typescript)
   ──▶ packages/api-client (tiplar + fetch funksiyalari)
   ──▶ apps/* faqat shu client'ni ishlatadi
```

- Surface'lar (`01` §7): dashboard — `/api/v1/shop/*`, sayt — `/api/v1/storefront/{slug}/*`.
- Har yozish so'rovi `Idempotency-Key` yuboradi. Kalit **bir marta, harakat boshlanganda** yaratiladi va qayta urinishda o'zgarmaydi. Yangi kalit bilan qayta yuborish — TAQIQ.
- Har so'rov `Accept-Language` (`uz`/`ru`/`en`) va `traceparent` yuboradi.
- CI: backend OpenAPI o'zgarsa — client qayta generatsiya qilinadi, typecheck yiqilsa PR o'tmaydi.

---

## 5. Autentifikatsiya (ADR-023)

```
Login ──▶ access JWT (10–15 daq) — faqat xotirada
       ──▶ refresh token — httpOnly Secure SameSite=Strict cookie (rotating)
Sahifa yangilandi ──▶ silent refresh ──▶ yangi access token
401 ──▶ bir marta refresh ──▶ yana 401 ──▶ /login
Ikki tab bir vaqtda ──▶ Web Locks qulfi ──▶ bir vaqtda faqat bitta refresh (rotatsiya "qayta ishlatish" bo'lib qolmasin)
WebSocket ──▶ POST /api/v1/auth/ws-ticket ──▶ qisqa ticket ──▶ /ws?ticket=...   (realtime moduli bilan)
```

- `app.<platforma>.uz` va `api.<platforma>.uz` bitta site ostida (cookie SameSite uchun). Lokalda hammasi `localhost` da.
- Login va refresh so'rovida panel aniq beriladi (`audience: "shop" | "platform"`). Har panelning o'z refresh cookie'si bor (`cos_refresh_shop` / `cos_refresh_platform`), shuning uchun bitta brauzerda ikkala panel bir-biriga xalaqit bermaydi.
- Sahifa ochilganda token yo'q — avval refresh, keyin `/auth/me`. Token tugashiga 30 soniya qolganda oldindan yangilanadi; 401 kelsa bir marta refresh qilib so'rov qayta yuboriladi.
- `shop_id` hech qachon frontend'dan "ishonchli" qiymat sifatida yuborilmaydi. URL'dagi `[shop]` faqat navigatsiya uchun; backend a'zolikdan aniqlaydi va mos kelmasa 404 qaytaradi.
- Rol bo'yicha tugma yashirish — UX; backend 403 qaytarsa, UI "Ruxsat yo'q" holatini ko'rsatadi.

---

## 6. Sahifa kontraktlari (shop paneli)

Har sahifa: kim ishlatadi, qaysi API, qaysi mutatsiyalar, qaysi muhim xato holatlari. Manzillar `../business/06` §1 bilan bir xil.

| Sahifa | Rollar | Asosiy o'qish | Mutatsiyalar | Muhim xato holatlari |
|---|---|---|---|---|
| `/overview` | ega, menejer | Bugungi metrikalar, tasdiq kutayotganlar | sana filtri | ma'lumot eski (`data_as_of`) |
| `/setup` | ega | Shop holati (FSM-01), qadamlar | filial, katalog, kanal | qadam bajarilmagan |
| `/inbox` | operator, menejer | Suhbatlar, xabarlar, `speaker_mode` | olish, javob, AI'ga qaytarish, biriktirish | WS uzildi, 409 (boshqa odam oldi) |
| `/orders` | operator, menejer, omborchi | FSM-08 holati, qatorlar, band qilish, izohlar, "to'landi" belgisi | tasdiqlash, tayyorlash, topshirish, bekor qilish (menejer/ega), izoh, belgi | 409 `INSUFFICIENT_AVAILABLE_STOCK`, 409 `PRICE_CHANGED`, 403 |
| `/leads` | operator, menejer | Leadlar, PC takliflari (FSM-05/06) | taklif tuzish, tasdiqqa yuborish, tasdiqlash | narx muddati o'tgan, tasdiq rad etildi |
| `/pc-builder` | operator, menejer | Qismlar, moslik natijasi | baholash, qoralama | `REVIEW_REQUIRED`, `BLOCK` |
| `/catalog` | katalog xodimi, menejer | Mahsulotlar, variantlar, rasmlar, import holati | yaratish, import, saytga chiqarish | takror SKU, import xatolari |
| `/prices` | ega, menejer | Narx versiyalari, kurs | narx o'zgartirish, chegirma tasdig'i | kurs eski |
| `/inventory` | omborchi, menejer, operator | Qoldiq (`on_hand`, `reserved`, `allocated`, `available` — alohida ko'rinadi), ledger | kirim, tuzatish (sabab bilan), **tez sotuv** (mobil) | 409 versiya, yetarli emas |
| `/support` | operator, menejer | Kafolat murojaatlari (FSM-11) | ochish, ko'rib chiqish, hal qilish | — |
| `/reports` | ega, menejer | Metrikalar, hisobot yordamchisi | savol, eksport | ruxsat yo'q (tannarx), ma'lumot yo'q |
| `/storefront` | ega | Sayt sozlamalari | logotip, rang, chiqarish | — |
| `/channels` | ega | Kanallar holati (FSM-03) | ulash, uzish | ruxsat bekor qilindi |
| `/team`, `/branches` | ega (menejer — ko'radi) | Xodimlar, rollar, filiallar | taklif, rol, o'chirish | oxirgi egani o'chirish taqiqlangan |
| `/notifications` | hamma | Bildirishnomalar, vazifalar | o'qildi | — |
| `/settings/ai` | ega | AI rejimi, profil, FAQ, sinov oynasi | qoralama, sinov, qo'llash | limit tugagan |
| `/settings/billing` | ega | Tarif, ishlatilish | — | limitga yaqin |
| `/audit` | ega | O'zgarishlar tarixi | eksport | — |

**Telefonda qulay bo'lishi shart:** `/inbox`, `/orders`, `/inventory` (tez sotuv), `/reports`.

### Shop sayti

| Sahifa | API | Muhim |
|---|---|---|
| `/` | `GET /storefront/{slug}/products` | Faqat `PUBLISHED`; kesh (`08`) |
| `/p/{product}` | `GET /storefront/{slug}/products/{id}` | Narx va mavjudlik "holatiga" vaqti bilan |
| `/cart` | `POST /storefront/{slug}/order-requests` | Idempotency-Key; to'lovsiz (DEC-115); javob — "qabul qilindi", "tasdiqlandi" emas |
| `/quote/{code}` | `GET .../quotes/{code}` | Muddati o'tgan bo'lsa — aniq ko'rsatiladi |
| `/orders/{code}` | `GET .../orders/{code}` | Faqat signed kod bilan; boshqa xaridor ma'lumoti yo'q |
| Chat vidjeti | `/ws` (anonim sessiya) | Barcha sahifalarda |

Saytda shop `Host` header'dan aniqlanadi, lekin faqat Nginx allowlist va tasdiqlangan domenlar ro'yxati orqali (`10`).

---

## 7. Holatlar modeli (har sahifa uchun)

`../business/06` §4 ning texnik ko'rinishi:

| Holat | Qachon | UI nima qiladi |
|---|---|---|
| `initial_loading` | Birinchi yuklash | Skeleton |
| `empty` | Ro'yxat bo'sh | Keyingi qadam tugmasi bilan |
| `ready` | Ma'lumot bor | — |
| `pending_mutation` | So'rov ketdi | Tugma bloklanadi (ikki marta bosish yo'q) |
| `validation_error` | 422 `VALIDATION_FAILED` | `details` bo'yicha maydon ostida xabar |
| `not_authorized` | 403 | "Ruxsat yo'q", maxfiy ma'lumot ko'rsatilmaydi |
| `not_found` | 404 | "Topilmadi" (boshqa shopniki ham shunday) |
| `version_conflict` | 409 `VERSION_CONFLICT` va boshqa 409 | Yangi holatni ko'rsatish, ustidan yozmaslik |
| `provider_unavailable` | 503, kanal uzilgan | Nima ishlamayotgani va keyingi qadam |
| `offline_reconnect` | WS uzildi | REST bilan sinxronlash, "qayta ulanmoqda" |
| `stale_read_model` | `data_as_of` eski | "14:30 holatiga" + yangilash |
| `long_job` | Import, eksport | Jarayon holati; sahifa yangilansa ham davom etadi |

**Qoida:** tasdiqlash, qoldiq tuzatish yoki "tez sotuv" hech qachon yangi `Idempotency-Key` bilan avtomatik qayta yuborilmaydi.

### Xato envelope'ini ko'rsatish

```ts
// Backend (K-07): { error: { code, message, details, trace_id } }
// message — backend allaqachon Accept-Language bo'yicha tarjima qilgan
// Frontend: code bo'yicha holat tanlaydi, message'ni ko'rsatadi,
// trace_id'ni "Yordam uchun kod" sifatida ko'rsatadi (nusxa olish tugmasi bilan)
```
Frontend'da qo'shimcha tarjima faqat backend bermaydigan matnlar uchun (`packages/i18n`). Xato kodlari ro'yxati — `11-api-conventions-errors-i18n.md`.

---

## 8. WebSocket inbox

```
Dashboard ──ticket──▶ /ws ──▶ platform/realtime (Redis pub/sub orqali ko'p worker)
Kanallar: shop:{shop_id}:inbox, conversation:{id}
Event'lar: message.created, conversation.updated (speaker_mode, speaker_version), task.created
```
- Server faqat xodim ruxsati bor suhbat kanallariga obuna qiladi (TC-ISO-06).
- Uzilsa: eksponensial qayta ulanish + `GET` bilan oxirgi holatni olish (event'lar yo'qolishi mumkin deb hisoblanadi).
- Operator "olish" bosganda `speaker_version` bilan so'rov; 409 bo'lsa — "boshqa odam oldi".

---

## 9. Xavfsizlik, analitika, accessibility

- CSP, foydalanuvchi matnini sanitizatsiya, rasm va fayllar — signed URL orqali.
- Analitika event'larida telefon, ism, chat matni yo'q; faqat `feature_id`, rol turi, qadam.
- Klaviatura bilan boshqarish, aniq fokus, `prefers-reduced-motion`.
- Barcha matnlar uch tilda; standart til — shop sozlamasi, foydalanuvchi almashtira oladi.
- Ovozli hisobot (beta): mikrofon ruxsati aniq so'raladi, yozish belgisi ko'rinadi, transkript tasdiqlanadi (TC-012).
- `../business/06` §6 dagi taqiqlangan iboralar UI matnlarida ishlatilmaydi (masalan, `DRAFT` uchun "tasdiqlandi").

---

## 10. Testlar

| Tur | Nima |
|---|---|
| Unit (Vitest) | Holat mapper'lari, xato kodi → holat, formatlash (pul: `amount_minor` + exponent → "3 840 000 so'm") |
| Storybook / UI holatlari | Qoldiq to'qnashuvi, narx o'zgardi, AI'dan olingan suhbat, kanal uzilgan, limit tugagan |
| E2E (Playwright) | 1-modul (bor): platforma shop ochadi → ega taklif orqali kiradi → filial, tekshiruvga yuborish → operator taklifi → operator faqat o'z bo'limlarini ko'radi → faollashtirish → operatorni o'chirish; bitta brauzerda ikki panel. Keyin: login → katalog → chat → taklif → qoralama → tasdiqlash → topshirish; ruxsat (operator bekor qila olmaydi — TC-029); klaviatura navigatsiyasi |
| Kontrakt | Generatsiya qilingan client typecheck; mock'lar OpenAPI'dan |

---

## 11. Stage 2 va 3

- **Stage 2:** shopning o'zi ro'yxatdan o'tishi, tarif tanlash, ommaviy takliflarga rozilik sahifasi (`/settings/network`).
- **Stage 3:** alohida `apps/shopping-web` — global qidiruv, solishtirish, xarita. UI va client'ni bo'lishadi, lekin **shop xodimining auth kontekstini hech qachon ishlatmaydi**. Bu app Stage 2 ma'lumoti bo'lmaguncha qurilmaydi.

## Keyingi qadam

→ [22-infrastructure-and-deployment.md](22-infrastructure-and-deployment.md)
→ [24-testing-and-release.md](24-testing-and-release.md)
