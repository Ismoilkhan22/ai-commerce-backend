# 1-modul — Auth, shoplar va xodimlar

> **Holat:** ✅ bitdi — 2026-10-23
> **Branch:** `feat/s0-foundation` · **Commit'lar:** `529a7cd`, `ee195a8`, `1df8738`, `d7029cb`, `4ca68c6` + frontend bilan integratsiya tuzatishlari (commit qilinmagan, §8)
> **Frontend:** `ai-commerce-frontend`, branch `feat/m1-frontend` (commit qilinmagan, §8)
> **Reja:** [27](../27-roadmap-and-tasks.md) §0, 1-qator (S0-04 + CORS, rate limit, `get_db` actor'ga bog'lanadi)
> **Baza loyihasi:** [db/platform.dbml](../db/platform.dbml), [db/platform.md](../db/platform.md) (DEC-131)

---

## 1. Nima bitdi — qisqacha

Shop egasi, xodimlar va platforma jamoasi tizimga kira oladi. Har so'rovda "kim, qaysi shopdan, nima qilishga haqqi bor" bazadan tekshiriladi. Platforma admini shop ochadi va egaga taklif havolasi beradi. Ega filial, sozlama va xodimlarni o'zi boshqaradi.

Oqim misolda:

```
Platforma admini shop yaratadi ──▶ ega taklif havolasini oladi (72 soat)
Ega havolani ochadi, parol qo'yadi ──▶ darhol tizimga kiradi (shop: DRAFT)
Ega filial va sozlamalarni to'ldiradi ──▶ "tekshiruvga yuborish"
Platforma admini faollashtiradi ──▶ shop ACTIVE
Ega operatorni taklif qiladi ──▶ operator havola orqali kiradi, faqat o'z ruxsatlari bilan
Ega operatorni o'chiradi ──▶ operatorning hamma sessiyasi shu zahoti tugaydi
```

## 2. Rejadagi bandlar

- [x] Jadvallar va RLS: shops, branches, shop_policies, principals, memberships, membership_branches, invitations, sessions, platform_staff
- [x] Auth: login, refresh (rotatsiya), logout, logout-all, me, parolni o'zgartirish, taklifni qabul qilish, parol tiklashni tasdiqlash, sessiyalar ro'yxati
- [x] Shop paneli: profil, sozlamalar, filiallar, xodimlar (taklif, rol, filial doirasi, o'chirish, parol tiklash havolasi)
- [x] Platforma paneli: shop yaratish va ega taklifi, FSM-01 o'tishlari, ega parolini tiklash, birinchi admin uchun CLI
- [x] Xavfsizlik: actor har so'rovda bazadan, ruxsatlar kodda, tranzaksiya actor bilan bog'langan, CORS, Redis rate limit, audit
- [x] Testlar: 22 ta HTTP qabul testi (haqiqiy PostgreSQL), unit testlar, FSM moslik testi

Ataylab keyinga qoldirildi:

- **Xodim parolini o'zi tiklashi** — SMS provayder kerak. Hozir havolani ega yoki platforma admini beradi.
- **`/auth/switch-shop`** — bir odam faqat bitta shopda ishlaydi (DEC-131).
- **`/auth/ws-ticket`** — realtime moduli bilan keladi.

Kartadan bitta farq bor. Shop paneli DRAFT, PENDING_VERIFICATION va SUSPENDED holatlarida ham ishlaydi, faqat CLOSED holat bloklaydi. Sababi business/13: ega aktivatsiyadan oldin shopni sozlashi kerak, to'xtatilgan shop esa bor buyurtmalarini yakunlashi kerak.

---

## 3. Fayllar xaritasi

```
app/
├── shared/
│   ├── phone.py                 # telefonni +998XXXXXXXXX ko'rinishiga keltirish
│   ├── clock.py                 # utcnow() — testda vaqtni boshqarish uchun bitta joy
│   ├── ratelimit.py             # so'rovlar sonini cheklash (Redis / xotira)
│   ├── http.py                  # ETag va If-Match yordamchilari
│   ├── idempotency/helpers.py   # run_idempotent — takroriy so'rovdan himoya, sirlarni saqlamasdan
│   ├── db/session.py            # + set_identity_context (RLS uchun shop/odam/sessiya)
│   └── types/manifest.py        # + role_grants maydoni
├── config/settings.py           # + JWT, cookie, CORS, Redis, Argon2 sozlamalari
├── main.py                      # + servislarni yig'ish, CORS, rate limiter, manifest.py ni topish
├── db/
│   ├── models.py                # + shops, staff, auth modellari ro'yxatga olindi
│   └── migrations/platform/versions/platform_0004_shops_staff_auth.py
└── platform/
    ├── auth/                    # kirish, tokenlar, sessiyalar
    │   ├── config.py  passwords.py  tokens.py  schemas.py  manifest.py
    │   ├── models/orm.py        # AuthSession (platform.sessions)
    │   ├── services/auth_service.py
    │   └── api/routes.py        # /api/v1/auth/*
    ├── shops/                   # shop, filial, sozlamalar; platforma paneli
    │   ├── state_machine.py  schemas.py  manifest.py
    │   ├── models/orm.py        # Shop, Branch, ShopPolicy
    │   ├── services/shop_service.py
    │   └── api/shop_routes.py  api/platform_routes.py
    └── staff/                   # odamlar, a'zolik, ruxsatlar, so'rov konteksti
        ├── permissions.py  state_machine.py  schemas.py  manifest.py  cli.py
        ├── models/orm.py        # Principal, Membership, MembershipBranch, Invitation, PlatformStaff
        ├── infrastructure/guard.py  infrastructure/providers.py
        ├── services/staff_service.py  services/links.py
        └── api/routes.py        # /api/v1/shop/members/*
tests/
├── unit/test_auth_units.py
├── architecture/test_fsm_parity.py  fsm_spec.yaml
└── integration/test_module1_auth_shops_staff.py
```

---

## 4. Qaysi faylda nima bor

### 4.1 Baza — `platform_0004_shops_staff_auth.py`

Jadvallar ORM modellaridan avtomatik yaratildi. Quyidagilar qo'lda qo'shildi:

- **Trigger `trg_memberships_last_owner`** — shopdagi oxirgi faol egani o'chirish yoki uning rolini almashtirishga baza ham yo'l qo'ymaydi. Trigger shop qatorini qulflaydi, shuning uchun ikki ega bir vaqtda bir-birini o'chirmoqchi bo'lsa ham bittasi to'xtatiladi.
- **RLS `memberships_isolation`, `sessions_isolation`** — `FORCE` bilan. Qator faqat shu holatda ko'rinadi: joriy shopniki bo'lsa, odamning o'zinikimi bo'lsa yoki (sessiyalarda) joriy sessiyaning o'zi bo'lsa. Kontekst o'rnatilmagan bo'lsa, hech narsa ko'rinmaydi.
- **`NULLIF(current_setting(...), '')`** — sozlama bir marta ishlatilgach bo'sh satr bo'lib qoladi. Busiz `''::uuid` xato beradi.

### 4.2 Modellar

- **`shops/models/orm.py`**
  - `Shop` — slug va STIR unikal, STIR 9 raqam (CHECK), holat va joylashuv rejimi CHECK bilan.
  - `Branch` — `UNIQUE (shop_id, id)`, shunda boshqa jadvallar filialga shop bilan birga bog'lanadi.
  - `ShopPolicy` — shop sozlamalari: chegirma limitlari, taklif muddati, eslatmalar, saytda qoldiq ko'rinishi. `version` bilan.
- **`staff/models/orm.py`**
  - `Principal` — tizimga kiradigan odam: telefon (E.164, unikal), parol hash'i, blok maydonlari (`failed_login_attempts`, `locked_until`).
  - `Membership` — odam ↔ shop. Bir odam bitta shopda (`UNIQUE principal_id`), bitta rol (4 tadan biri).
  - `MembershipBranch` — `SELECTED` doiradagi xodimning filiallari. Composite FK boshqa shop filialini biriktirishga yo'l qo'ymaydi.
  - `Invitation` — bir martalik havolalar: `purpose` = `INVITE` yoki `PASSWORD_RESET`, faqat `token_hash` saqlanadi.
  - `PlatformStaff` — bizning jamoa va ularning platforma roli.
- **`auth/models/orm.py`**
  - `AuthSession` — refresh token hash'i, `family_id` (token zanjiri), `audience` (`shop` / `platform`), bekor qilish sababi.

### 4.3 Auth — `app/platform/auth/`

- **`config.py`** — `AuthConfig`: access token 15 daqiqa, refresh 30 kun, 5 xato → 15 daqiqa blok, taklif 72 soat, tiklash 24 soat.
- **`passwords.py`**
  - `validate_new_password(password, phone)` — kamida 8 belgi, oddiy parollar ro'yxati, telefon raqamini o'z ichiga olmasin. Xato kodlari: `min_length`, `max_length`, `too_weak`.
  - `PasswordHasher` — Argon2id. Hisoblash alohida thread'da bajariladi va server qotmaydi. Hash yo'q bo'lsa ham soxta hash tekshiriladi, shunda javob vaqti noma'lum telefonni oshkor qilmaydi.
- **`tokens.py`**
  - `issue_access_token` / `decode_access_token` — JWT HS256, `kid`, `aud` = `cos-shop` yoki `cos-platform`. Tokenda rol yo'q.
  - `new_refresh_token(session_id)` — `<session_id>.<sir>`. Bazaga faqat sirning sha256 hash'i yoziladi.
  - `new_link_token`, `hash_token` — taklif va tiklash havolalari uchun.
- **`services/auth_service.py`** — `AuthService`
  - `login` — telefon normallashtiriladi, blok tekshiriladi, parol solishtiriladi. Xato urinish hisoblagichi xatodan **oldin** COMMIT qilinadi, aks holda ROLLBACK uni o'chirib yuborardi.
  - `refresh` — eski sessiya `ROTATED` bo'ladi, o'sha `family_id` da yangisi ochiladi. Allaqachon almashtirilgan token qayta kelsa, butun oila bekor qilinadi (`REUSE_DETECTED`).
  - `logout`, `logout_all`, `list_sessions`, `revoke_session`.
  - `change_password` — joriy parol so'raladi, boshqa sessiyalar bekor bo'ladi.
  - `accept_invite` — havola tekshiriladi, a'zolik `INVITED → ACTIVE` (USE orqali), parol o'rnatiladi, sessiya ochiladi.
  - `confirm_password_reset` — yangi parol qo'yiladi, hamma sessiyalar bekor bo'ladi.
- **`api/routes.py`** — `/api/v1/auth/*`. Refresh token har panelning o'z cookie'sida: `cos_refresh_shop` / `cos_refresh_platform` (`httpOnly`, `SameSite=Strict`, faqat `/api/v1/auth/refresh` yo'lida). Login va refresh tanasida `audience`. Rate limit (daqiqasiga):
  - login: IP bo'yicha 30, IP + telefon bo'yicha 10;
  - refresh: 60;
  - havola bilan amallar: 10.

### 4.4 So'rov konteksti va ruxsatlar — `app/platform/staff/`

- **`infrastructure/guard.py`** — har himoyalangan endpoint shu yerdan o'tadi:

  ```
  Bearer token ──▶ imzo, muddat, panel (aud) tekshiriladi
              ──▶ bitta tranzaksiya ochiladi + RLS konteksti (shop, odam, sessiya)
              ──▶ bazadan: sessiya faolmi → odam faolmi → a'zolik ACTIVE mi → shop yopilmaganmi
              ──▶ ActorContext (rol, ruxsatlar, filiallar) ──▶ endpoint xuddi shu tranzaksiyada ishlaydi
  ```

  - `ShopContext`, `PlatformContext`, `AnyContext` — endpoint parametrlarida ishlatiladigan tayyor turlar.
  - `require_permission("staff.member.invite")` — rolda bu ruxsat bo'lmasa, 403.
  - Endpoint ichida xato bo'lsa, tranzaksiya darhol ROLLBACK qilinadi (`asynccontextmanager`).
- **`permissions.py`** — `PermissionRegistry`: har modul manifest'idagi `role_grants` ni birlashtiradi. Platforma rollari ruxsatlari `PLATFORM_ROLE_PERMISSIONS` da.
- **`state_machine.py`** — a'zolik holatlari: `ACCEPT_INVITE`, `DISABLE`, `REVOKE_INVITE`.
- **`services/links.py`**
  - `issue_link` — yangi havola beradi, shu a'zolikning oldingi ochiq havolalarini bekor qiladi.
  - `find_valid_link` — havola noto'g'ri, ishlatilgan, bekor qilingan yoki muddati o'tgan bo'lsa, 404 va `reason` qaytaradi.
- **`services/staff_service.py`** — `StaffService`
  - `invite` — telefon boshqa joyda ro'yxatdan o'tgan bo'lsa, `not_unique`.
  - `update_access` — rol va filial doirasini o'zgartiradi. `If-Match` majburiy. Filiallar shu shopniki va ochiq bo'lishi tekshiriladi.
  - `disable` — sessiyalar va havolalar shu zahoti bekor qilinadi (TC-025).
  - `issue_password_reset`, `resend_invite`.
  - `flush_guarding_owner` — trigger xatosini `LAST_OWNER_REQUIRED` ga aylantiradi.
- **`cli.py`** — `create-platform-admin --phone ... --name ...`. Parol `PLATFORM_ADMIN_PASSWORD` dan yoki klaviaturadan olinadi.

### 4.5 Shoplar — `app/platform/shops/`

- **`state_machine.py`** — FSM-01:

  ```
  DRAFT ──(ega: tekshiruvga yubordi)──▶ PENDING_VERIFICATION
  PENDING_VERIFICATION ──(platforma: faollashtirdi)──▶ ACTIVE
  ACTIVE ──(platforma: to'xtatdi, sabab bilan)──▶ SUSPENDED ──(qayta yoqdi)──▶ ACTIVE
  ACTIVE ──(platforma: yopdi, sabab bilan)──▶ CLOSED
  ```

- **`services/shop_service.py`** — `ShopService`
  - Shop paneli: `profile`, `update_profile`, `submit_for_verification`, `policies`, `update_policies`, `branches`, `create_branch`, `update_branch`, `close_branch`. Yopilgan filialni tahrirlab bo'lmaydi (`BRANCH_CLOSED`). Filial doirasi `SELECTED` bo'lgan xodim faqat o'z filiallarini ko'radi.
  - Platforma paneli: `create_shop` (shop, sozlamalar, ega va taklif bitta tranzaksiyada), `list_shops`, `get_shop`, `platform_transition`, `member_password_reset` (faqat egalar uchun).
- **`api/shop_routes.py`** — `/api/v1/shop/profile`, `/policies`, `/branches`.
- **`api/platform_routes.py`** — `/api/v1/platform/shops/*`. Takroriy "shop yaratish" so'rovi o'sha shopni qaytaradi, lekin havola yangi bo'ladi: eski havola bazada saqlanmagan, u bekor qilinadi.

### 4.6 Umumiy yordamchilar — `app/shared/`

- **`phone.py`** — `normalize_phone("90 123-45-67")` → `+998901234567`.
- **`ratelimit.py`** — `RedisRateLimiter` (production), `MemoryRateLimiter` (test). `enforce(...)` limit oshsa `429 RATE_LIMITED` va `retry_after_seconds` qaytaradi.
- **`http.py`** — `etag(v)` → `"v3"`, `require_if_match` (header yo'q bo'lsa, `INVALID_REQUEST`), `check_version` (`VERSION_CONFLICT` + joriy versiya).
- **`idempotency/helpers.py`** — `run_idempotent(...)`:
  - `stored=` — javobning sirsiz qismi saqlanadi;
  - `on_replay=` — takroriy so'rovda yangi havola beriladi.

### 4.7 Ilovani yig'ish — `app/main.py`

- Manifest'lar `manifest.py` / `domain_manifest.py` fayllaridan topiladi. Paket `__init__.py` fayllari bo'sh qoladi, shunda modullar orasida aylanma import bo'lmaydi.
- `_wire_platform_services` — `AuthService`, `StaffService`, `ShopService`, `UseService`, ruxsatlar reyestri bir marta yaratilib, `app.state` ga qo'yiladi.
- Lifespan — Redis rate limiter va `/health/ready` uchun Redis tekshiruvi.
- CORS eng tashqi qatlam. `Idempotency-Key`, `If-Match` header'lariga ruxsat bor, `ETag` va `Retry-After` frontendga ko'rinadi.

---

## 5. Testlar

Natija: `make check` → **172 passed** (frontend integratsiyasidan keyin; commit paytida 168). ruff, mypy strict va import-linter xatosiz. Har commit alohida toza nusxada tekshirildi.

`tests/integration/test_module1_auth_shops_staff.py` (haqiqiy PostgreSQL, HTTP orqali):

- [x] Shop hayot sikli: DRAFT → PENDING → ACTIVE; o'tishlar `transition_log` da
- [x] Sababsiz to'xtatish rad etiladi; yopilgan shop paneli `SHOP_NOT_ACTIVE`
- [x] Takroriy "shop yaratish": o'sha shop, yangi havola, eski havola ishlamaydi, havola bazada yo'q
- [x] Bir xil STIR, bir xil telefon → `not_unique`
- [x] Rollar: menejer xodimni ko'radi, lekin taklif qila olmaydi; operator sozlamalarni ko'rmaydi
- [x] Filial doirasi: xodim faqat o'z filialini ko'radi; yopilgan filial tahrirlanmaydi
- [x] TC-025: o'chirilgan xodimning tokeni va refresh'i shu zahoti ishlamaydi
- [x] Oxirgi ega: o'chirib ham, rolini almashtirib ham bo'lmaydi, parallel so'rovlarda ham
- [x] A va B shop izolyatsiyasi: B ning xodimi, filiali va havolasi A uchun 404
- [x] Shop paneli tokeni platforma panelida ishlamaydi
- [x] RLS: kontekstsiz so'rov 0 qator qaytaradi
- [x] Brute force: 5 xatodan keyin to'g'ri parol ham `429`; auditda 5 ta `auth.login.failed`
- [x] Noma'lum telefon va noto'g'ri parol — bir xil javob
- [x] Login rate limit
- [x] Refresh rotatsiyasi; eski token qayta ishlatilsa, butun oila bekor qilinadi
- [x] Logout va logout-all; parolni o'zgartirish boshqa sessiyalarni yopadi
- [x] Parol tiklash havolasi bir martalik; muddati o'tgan taklif rad etiladi
- [x] `If-Match` yo'q → `INVALID_REQUEST`; eski versiya → `VERSION_CONFLICT`

`tests/unit/test_auth_units.py` — telefon formati, parol qoidalari, Argon2, tokenlar (boshqa panel, muddati o'tgan, soxta imzo), refresh token, ruxsatlar reyestri.
`tests/architecture/test_fsm_parity.py` — koddagi FSM-01 va a'zolik holatlari `business/05` dagi strelkalar bilan bir xil.

## 6. Jarayonda topilgan va tuzatilgan muammolar

- **Audit 500 xatosi.** Audit yozuvida `Decimal` bo'lsa, server 500 qaytarardi. Endi diff `to_json_compatible` orqali saqlanadi, regression testi bor.
- **Idempotency jadvalida sir.** Takroriy so'rov himoyasi javobni to'liq saqlab, taklif havolasini bazaga yozib qo'yardi. Endi faqat sirsiz qismi saqlanadi.
- **Tranzaksiya ochiq qolishi.** Guard'da endpoint xatosi tranzaksiyaga yetib bormasdi. `asynccontextmanager` ga o'tkazildi.
- **Parallel test 0 qator ko'rardi.** `FORCE RLS` migrator roliga ham ta'sir qiladi, shuning uchun testlardagi tekshiruv so'rovlari admin ulanish orqali yuboriladi.

## 7. Keyingi modulga meros

- Yangi modul o'z ruxsatlarini `manifest.py` dagi `role_grants` da e'lon qiladi. Endpoint'da `require_permission("...")` ishlatiladi.
- Shop jadvallari composite FK `(shop_id, id)` bilan bog'lanadi. Sezgir jadvallarga RLS `set_identity_context` orqali qo'yiladi.
- Yozish endpoint'lari: POST uchun `run_idempotent`, PATCH/PUT uchun `require_if_match` + `check_version`.

---

## 8. Frontend va integratsiya (2026-10-23)

**Nima bitdi:** 1-modulni brauzerda ishlatish mumkin. Shop paneli (`localhost:3000`) va platforma paneli (`localhost:3001`) backend bilan haqiqiy oqimda tekshirildi:

```
platforma admini shop yaratadi ──▶ havolani nusxalaydi
ega havolani ochadi, parol qo'yadi ──▶ shop paneliga kiradi ──▶ filial qo'shadi ──▶ tekshiruvga yuboradi
ega operatorni taklif qiladi ──▶ operator kiradi va faqat o'z bo'limlarini ko'radi
platforma faollashtiradi ──▶ ega "Faol" ni ko'radi ──▶ ega operatorni o'chiradi ──▶ operator chiqib ketadi
```

### 8.1 Integratsiyada topilgan va backend'da tuzatilgan muammolar

Bular testlarda ko'rinmagan edi. Frontendni hozir qurishning foydasi shu:

- **Ikki panel bitta brauzerda bir-birini chiqarib yuborardi.** Ikkalasi ham bitta `cos_refresh` cookie'sini ishlatardi. Endi har panelning o'z cookie'si bor va login/refresh'da `audience` beriladi. Shop egasi platforma paneliga kira olmaydi va aksincha. Test: `test_shop_and_platform_panels_keep_separate_sessions_in_one_browser` + e2e.
- **Platforma kartochkasida ega yo'q edi.** `GET /platform/shops/{id}` endi `owners[]` qaytaradi, shusiz "ega parolini tiklash" tugmasi ishlamasdi.
- **Ega taklifini qayta berib bo'lmasdi.** 72 soat o'tsa, shop "yetim" qolardi. Yangi endpoint: `POST /platform/shops/{id}/members/{membership_id}/invite` (audit bilan).
- **Shop slug'i panel yo'llari bilan to'qnashishi mumkin edi** (`login`, `invite`, `admin`, `api`, `www`, ...). Bunday nomlar endi band (`RESERVED_SLUGS`).
- **Swagger'da Authorize yo'q edi.** Token header'dan qo'lda o'qilardi. Endi OpenAPI'da Bearer sxemasi bor, `operationId` lar o'qiladigan (`auth_login`, `staff_invite_member`), spec manzili `/api/v1/openapi.json` (frontend shundan generatsiya qiladi).
- **`make bootstrap` `.env` ni o'qimasdi** va standart 5432 portga ulanardi, ya'ni dasturchining o'z PostgreSQL'iga. Endi `.env` dan o'qiydi; docker portlari 5433 va 6380.
- **Testlar lokal `.env` ga bog'liq bo'lib qolgan edi** (`COOKIE_SECURE=false` production testini buzdi). Testlar endi `.env` ni o'qimaydi.

### 8.2 Frontend fayllar xaritasi (`ai-commerce-frontend`)

```
apps/
├── shop-dashboard/src/
│   ├── app/
│   │   ├── login/  invite/[token]/  reset-password/[token]/     # kirish, taklif, parol tiklash
│   │   └── [shop]/                                                # himoyalangan qism (RequireAuth + slug tekshiruvi)
│   │       ├── overview/  setup/  branches/  team/  settings/  profile/
│   │       └── layout.tsx                                         # ShopGuard: URL'dagi slug ≠ o'z shopi → o'z shopiga
│   ├── components/  shell.tsx  gate.tsx                           # menyu (rolga qarab), sahifa ruxsati
│   └── lib/  nav.ts  config.ts  use-action-key.ts
└── platform-admin/src/
    ├── app/  login/  (admin)/shops/  (admin)/shops/[id]/  (admin)/profile/
    ├── components/shell.tsx
    └── lib/  config.ts  use-action-key.ts
packages/
├── api-client/src/  index.ts  schema.d.ts (generatsiya)
├── auth/src/        session.ts  provider.tsx  screens.tsx  account.tsx
├── app-kit/src/     index.tsx  shop-status.tsx
├── i18n/src/        index.tsx  messages/{uz,ru,en}.ts
└── ui/src/          components/*  styles/globals.css
e2e/module1.spec.ts
```

### 8.3 Qaysi faylda nima bor

- **`packages/api-client`**
  - `schema.d.ts` — backend OpenAPI'dan `pnpm api:generate` bilan yaratiladi, qo'lda yozilmaydi.
  - `createApiClient` — openapi-fetch klienti. Yo'llar va javoblar turlari bilan tekshiriladi: noto'g'ri endpoint yoki maydon bo'lsa, kod kompilyatsiya bo'lmaydi.
  - `unwrap()` — javobni oddiy qiymatga aylantiradi. Xato bo'lsa `ApiError` (`code`, `details`, `fields`, `traceId`) tashlaydi.
  - `newIdempotencyKey()`, `ifMatch(version)`.
- **`packages/auth`**
  - `session.ts` — `Session`:
    - access token faqat xotirada;
    - `refresh()` bir vaqtda bitta bo'ladi: tab ichida umumiy promise, tablar orasida Web Locks;
    - middleware har so'rovga token va `Accept-Language` qo'yadi, 401 kelsa bir marta refresh qilib qayta yuboradi.
  - `provider.tsx` — `AuthProvider`: sahifa ochilganda jim kirish, `login`, `signInWith` (taklifdan keyin), `logout`. Hook'lar: `useMe`, `usePermission`, `useApi`. `RequireAuth` — kirmagan bo'lsa `/login?next=...`.
  - `screens.tsx` — `LoginScreen` (bloklanganda "N soniyadan keyin"), `InviteAcceptScreen`, `PasswordResetScreen`. Havola xatolari sababi bilan: ishlatilgan, bekor qilingan, muddati o'tgan.
  - `account.tsx` — `AccountScreen`: parolni o'zgartirish, faol qurilmalar, hamma joydan chiqish.
- **`packages/app-kit`**
  - `useErrorHandler` — `VALIDATION_FAILED` maydon xatolari forma ostida, qolganlari toast'da (backend matni foydalanuvchi tilida keladi, `trace_id` bilan).
  - `ConflictAlert` — `VERSION_CONFLICT` bo'lsa "ma'lumot o'zgargan, yangilang".
  - `Forbidden`, `LanguageSwitcher`, `ShopStatusBadge`, `QueryProvider` (4xx da qayta urinmaydi, yozish so'rovlari hech qachon avtomatik qayta yuborilmaydi).
- **`packages/i18n`** — uz/ru/en matnlar. ru va en ning kalitlari uz bilan bir xil bo'lishini TypeScript tekshiradi. Til `useSyncExternalStore` orqali saqlanadi, hydration xatosi bo'lmaydi. Sana hamma tilda `23.10.2026 18:15` (Toshkent vaqti).
- **`packages/ui`** — Tailwind 4 tokenlari (`globals.css`) va komponentlar: Button, Input, NativeSelect, Field, Card, Dialog, DropdownMenu, Table, Badge, Alert, CopyField (havolani nusxalash). Figma kelsa, faqat tokenlar almashtiriladi.
- **`apps/shop-dashboard`**
  - `[shop]/layout.tsx` — URL'dagi slug faqat navigatsiya uchun; shop a'zolikdan aniqlanadi.
  - `setup` — FSM-01 qadamlari, "tekshiruvga yuborish" (filial bo'lmasa tugma o'chiq), shop ma'lumotlari (`If-Match`).
  - `branches` — ro'yxat, qo'shish, tahrirlash, yopish.
  - `team` — taklif (havola + nusxalash), rol va filial doirasi, parol tiklash havolasi, o'chirish.
  - `settings` — shop sozlamalari (faqat ega o'zgartiradi, menejer ko'radi).
  - `use-action-key.ts` — `Idempotency-Key` bitta harakat uchun: xatodan keyin qayta bosilsa, o'sha kalit ketadi.
- **`apps/platform-admin`**
  - `shops` — ro'yxat va shop yaratish (natijada ega havolasi).
  - `shops/[id]` — holat va amallar: faollashtirish, to'xtatish, qayta yoqish, yopish (sabab bilan); egalar ro'yxati, taklifni qayta berish, parol tiklash havolasi.

### 8.4 Tekshiruv

- [x] `pnpm check` — typecheck va lint (7 paket va app), xatosiz
- [x] `pnpm build` — ikkala app production build
- [x] `pnpm test:e2e` — 2 ta Playwright testi: to'liq oqim (8 qadam) va bitta brauzerda ikki panel
- [x] Skrinshotlar bilan ko'rib chiqildi: kompyuter va telefon (390 px) o'lchami
- [x] `pnpm audit` — Next.js 16.4.0 da kritik zaiflik topildi (GHSA-2464-fhr4-w9xw, GHSA-673q-mjm6-r5xr) → 16.4.2 ga yangilandi. Qolgani: `braces` (faqat lint vositasi ichida, tuzatilgan versiya hali chiqmagan)

### 8.5 Ataylab keyinga qoldirildi

- Bosh sahifadagi metrikalar — hisobotlar modulida.
- Filial ish vaqtini UI'da tahrirlash — kerak bo'lganda (backend tayyor).
- Qorong'i rejim — tokenlar tayyor, almashtirish tugmasi yo'q.
