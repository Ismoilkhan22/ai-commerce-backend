# 1b-modul — Platforma paneli, A bosqich

> **Holat:** ✅ to'liq bitdi — 2026-10-24 (2-tur: jamoa, izohlar, ⌘K, demo ma'lumot). **Commit qilinmagan** — founder ko'rib chiqishini kutmoqda.
> **TZ:** [business/15](../../business/15_PLATFORM_ADMIN_PANEL.md) — A bosqich. Founder qarorlari: yordam (support) roli faqat ko'radi, pilot tugashi — faqat ogohlantirish.
> **Dizayn:** to'q "buyruqlar markazi" (founder tanlovi, 2026-10-24). Hamma funksiya qurilgach qayta chiziladi. Maketlar: kanvas "3-tur".
> **Repolar:** `ai-commerce-backend` (`feat/s0-foundation`), `ai-commerce-frontend` (`feat/m1-frontend`).

---

## 1. Nima bitdi — qisqacha

Platforma jamoasi endi panelning o'zida ko'radi:
- nima qilish kerak: tekshiruv navbati, egasi kirmagan shoplar, pilot muddati;
- har shopning ichi: xodimlar, filiallar, holat tarixi, jurnal.

Shopni qidirish, tahrirlash (sabab bilan) va jamoaning hamma amallarini jurnalda ko'rish mumkin.

```
Bosh sahifa ──▶ "TechPC 3 kundan beri kutmoqda" ──▶ Faollashtirish
           ──▶ "GameZone egasi kirmagan, havola eskirgan" ──▶ Havolani qayta berish
Shoplar ──▶ qidiruv (nom, STIR, ega telefoni) ──▶ shop kartochkasi ──▶ tablar
Faoliyat jurnali ──▶ kim, qachon, qaysi shopda, nima qildi va nega
```

## 2. Rejadagi bandlar (business/15, A bosqich)

- [x] §1 Bosh sahifa: holat bo'yicha sanoqlar, tekshiruv navbati, egasi kirmaganlar, pilot kunlari, yangi shoplar, oxirgi faoliyat
- [x] §2 Shoplar ro'yxati: qidiruv, holat filtri, saralash, sahifalash, ega, xodim va filial soni, oxirgi faollik
- [x] §3 Shopni tahrirlash: sabab majburiy, versiya tekshiruvi, sayt manzili o'zgarmaydi
- [x] §3 Ichki izoh — `platform.shop_notes` (migratsiya `platform_0005`), faqat qo'shiladi, shop ko'rmaydi
- [x] §4 Shop kartochkasi: ishga tushirish qadamlari, egalar va xodimlar, filiallar, holat tarixi, jurnal; yopishda shop nomini yozib tasdiqlash
- [x] §5 Platforma jamoasi: ro'yxat, havola orqali taklif va qabul qilish, rol, o'chirish (sessiyalar darhol tugaydi), parol tiklash; oxirgi adminni o'chirib bo'lmaydi (`LAST_ADMIN_REQUIRED`), o'zini o'chirib bo'lmaydi
- [x] §6 Faoliyat jurnali: shop, amal turi va sana bo'yicha filtr
- [x] Qoidalar: har amal sabab bilan jurnalda; yordam roli holatni o'zgartira olmaydi va tahrirlay olmaydi (API 403, tugma ko'rinmaydi); platforma shop xodimini o'chirmaydi

## 3. Fayllar xaritasi

```
ai-commerce-backend/
├── app/platform/shops/
│   ├── platform_schemas.py                 # bosh sahifa, ro'yxat, kartochka va jurnal javoblari
│   ├── services/platform_queries.py        # PlatformQueryService — faqat o'qish (bosh sahifa, ro'yxat, jurnal)
│   ├── services/shop_service.py            # + platform_update (tahrir), _on_shop (amalga shop_id yoziladi)
│   ├── api/platform_overview_routes.py     # /platform/dashboard, /platform/audit
│   ├── api/platform_routes.py              # + ro'yxat parametrlari, PATCH, members/branches/history/audit
│   └── manifest.py                         # ikkala router birlashtirildi
├── app/platform/staff/permissions.py       # + platform.shop.edit (faqat PLATFORM_ADMIN)
├── app/platform/auth/services/auth_service.py  # taklif qabul qilinganda last_login_at yoziladi
├── tests/integration/helpers.py            # World — testlar uchun umumiy yordamchi
├── tests/integration/test_platform_admin.py
└── docs/engineering/db/platform.dbml       # TAKLIF: shop_notes, platform_staff_invitations

ai-commerce-frontend/
├── packages/ui/src/styles/globals.css      # to'q tokenlar (binafsha urg'u), Inter va JetBrains Mono
├── packages/i18n/src/messages/*.ts         # + admin, actions bo'limlari (uz/ru/en); actionLabel()
└── apps/platform-admin/src/
    ├── components/
    │   ├── shell.tsx                       # chap menyu (telefonda tepada, faqat ikon)
    │   ├── create-shop-dialog.tsx          # "Shop yaratish" — bosh sahifa va ro'yxatda
    │   ├── transition-dialog.tsx           # holat o'zgartirish: sabab, yopishda nomni yozish
    │   ├── edit-shop-dialog.tsx            # tahrir: sabab, If-Match, VERSION_CONFLICT
    │   ├── link-dialog.tsx                 # berilgan havolani ko'rsatish va nusxalash
    │   └── activity-row.tsx                # jurnal qatori (bosh sahifa, kartochka, jurnal)
    ├── lib/shops.ts                        # holatlar, FSM-01 amallari, query kalitlari
    └── app/(admin)/
        ├── dashboard/page.tsx
        ├── shops/layout.tsx                # chapda ro'yxat (qidiruv, filtr, sahifalash)
        ├── shops/page.tsx                  # "shopni tanlang"
        ├── shops/[id]/page.tsx             # kartochka va 5 tab
        └── audit/page.tsx
```

## 4. Qaysi faylda nima bor

### 4.1 Backend

- **`platform_queries.py` — `PlatformQueryService` (faqat o'qish)**
  - `dashboard()`:
    - holat bo'yicha sanoqlar (har doim 5 ta holat);
    - tekshiruv navbati — yuborilgan vaqt `transition_log` dan, eng eskisi birinchi;
    - egasi kirmaganlar — ochiq havolalar: `expired` / `expiring` (24 soatdan kam) / `valid`;
    - pilotlar — `day` = faollashtirilgandan beri kunlar + 1, `days_left`, `ending_soon` (≤ 7 kun);
    - oxirgi 10 ta platforma amali.
  - `list_shops()`:
    - qidiruv nom, slug va STIR bo'yicha. Matn telefonga o'xshasa, normallashtirilib ega telefoni bo'yicha qidiriladi;
    - holat filtri, saralash, `limit`/`offset` va `total`.
  - Shop kartochkasi: `members`, `branches`, `history` (FSM-01, yangisi birinchi), `audit` (sahifalangan).
  - `platform_audit()` — faqat platforma amallari, shop, kim, amal va sana bo'yicha filtr bilan.
  - **Jurnalda qiymatlar ko'rsatilmaydi**, faqat o'zgargan maydon nomlari (`changed_fields`).
- **`shop_service.py`**
  - `platform_update()` — tahrir: `If-Match`, sabab majburiy, STIR unikalligi tekshiriladi, audit. STIR qiymati diff'ga yozilmaydi, faqat "o'zgardi" belgisi.
  - `_on_shop()` — platforma shop ustida amal qilsa, `transition_log` va audit'ga o'sha shopning `shop_id` si yoziladi. Oldin NULL edi va kartochkada platforma amallari ko'rinmasdi.
- **RLS:** `memberships` jadvali shop bo'yicha himoyalangan va chetlab o'tadigan rol yo'q. Shuning uchun xodim sanoqlari har shop uchun alohida kontekst bilan olinadi. Pilotda (≤ 100 shop) bu yetarli; keyin hisobot proyeksiyasi bilan almashtiriladi (kodda izoh bor).
- **`auth_service.accept_invite`** — taklifni qabul qilish birinchi kirish hisoblanadi, shuning uchun `last_login_at` yoziladi. Aks holda "oxirgi faollik" bo'sh qolardi.

### 4.2 Frontend

- **`shell.tsx`** — maketdagidek chap menyu:
  - Bosh sahifa, Shoplar, Faoliyat jurnali;
  - "Platforma jamoasi" — "tez orada";
  - telefonda tepada, faqat ikonlar bilan.
- **`dashboard/page.tsx`**
  - Ko'rsatkichlar bosilsa, ro'yxat shu holat bo'yicha ochiladi.
  - "Bugun sizni kutayotgan ishlar": faollashtirish va havolani qayta berish shu yerning o'zida.
  - 30 kunlik pilot chiziqlari, oxirgi faoliyat.
- **`shops/layout.tsx`** — chapdagi ro'yxat:
  - qidiruv (300 ms kutib yuboriladi), holat chiplari sanoq bilan, sahifalash;
  - tanlangan shop belgilanadi;
  - telefonda ro'yxat va kartochka navbat bilan ko'rinadi.
- **`shops/[id]/page.tsx`** — kartochka:
  - sarlavhada `slug.platforma.uz`, holat, "Tahrirlash" va ruxsat etilgan holat amallari (FSM-01);
  - **Umumiy:** 5 ta ishga tushirish qadami (bajarilgan — yashil, keyingisi — binafsha) va asosiy ma'lumotlar;
  - **Egalar va xodimlar:** rol, holat, oxirgi kirish. Ega uchun: taklifni qayta berish, parol tiklash havolasi;
  - **Filiallar**, **Holat tarixi** (kim, nima, sabab), **Jurnal** (sahifalangan).
- **`transition-dialog.tsx`** — to'xtatish, qayta yoqish va yopish uchun sabab majburiy. Yopish qaytarib bo'lmaydigan amal, shuning uchun shop nomini aynan yozmaguncha tugma o'chiq turadi.
- **`edit-shop-dialog.tsx`** — sabab majburiy (formada ham, serverda ham). Ikki kishi bir vaqtda tahrirlasa, "ma'lumot o'zgargan" ogohlantirishi chiqadi.
- **`audit/page.tsx`** — filtrlar: amal guruhi (shop, ega takliflari, xodimlar, platforma), shop, sana oralig'i (Toshkent vaqti bilan).
- **i18n** — amal kodlari (`shops.shop.activate` va boshqalar) uch tilda odam o'qiydigan nomga aylanadi (`actionLabel`).

## 5. Testlar

- [x] Backend `make check` → **181 passed** (+9 yangi). ruff, mypy strict va import-linter xatosiz.
  `test_platform_admin.py` tekshiradi:
  - bosh sahifa raqamlari va navbat tartibi;
  - havola holati: muddati o'tgan yoki tugayapti;
  - pilot kunlari;
  - nom va ega telefoni bo'yicha qidiruv, filtr, `total`;
  - tahrir: `If-Match`, sabab, STIR band, slug o'zgarmaydi, audit;
  - yordam roli: o'qishi mumkin, tahrir va holat o'zgartirish 403;
  - kartochka bo'limlari; jurnalda qiymatlar yo'q; jurnal filtrlari.
- [x] Frontend: `pnpm check` (typecheck va lint) xatosiz, ikkala production build muvaffaqiyatli.
- [x] Playwright — **3 test**: 1-modul oqimi, bitta brauzerda ikki panel, va yangi test (bosh sahifa → ega kirmagani ishlar ro'yxatida → telefon bo'yicha qidiruv → tahrir sababsiz rad etiladi → sabab bilan saqlanadi → kartochka va umumiy jurnalda ko'rinadi).
- [x] Skrinshotlar bilan ko'rib chiqildi: bosh sahifa, kartochka tablari, jurnal, telefon ko'rinishi, to'q uslubdagi shop paneli.

## 6. 2-tur (2026-10-24): platforma qismini to'liq tugatish

**Backend:**
- **Migratsiya `platform_0005_platform_team_notes`:**
  - `platform_staff` ga INVITED holati, `invited_by`, `updated_at` va `version` qo'shildi;
  - yangi jadvallar: `platform_staff_invitations` (havolaning faqat hash'i saqlanadi) va `shop_notes` (1–2000 belgi, faqat qo'shiladi).
- **`staff/services/platform_team_service.py`:**
  - jamoa a'zosini taklif qilish, taklifni qayta yuborish, parol tiklash havolasi;
  - rolni o'zgartirish (`If-Match` bilan), o'chirish;
  - oxirgi faol admin barcha admin qatorlarini qulflash bilan himoyalangan — ikki admin bir vaqtda ham uni o'chira olmaydi.
- **`staff/services/platform_links.py`** — jamoa havolalari, `PLATFORM_APP_PUBLIC_URL` asosida (`/invite`, `/reset-password`).
- **Auth:**
  - `POST /auth/platform-invites/{token}/accept` — darhol platforma sessiyasi ochiladi;
  - `POST /auth/platform-password-reset/confirm`.
- **Izohlar:** `GET/POST /platform/shops/{id}/notes`. Auditga izoh matni yozilmaydi.
- **Yangi ruxsatlar va xato kodi:**
  - `platform.staff.view` (admin, yordam), `platform.staff.manage` (admin), `platform.shop.note` (admin, yordam);
  - xato kodi `LAST_ADMIN_REQUIRED`.
- **`app/db/seed/dev_seed.py` (`make seed`):**
  - 8 ta shop turli holatlarda, egalari, xodimlari, filiallari, tarixi va izohlari bilan; jamoa: admin, yordam, taklif qilingan muharrir;
  - ma'lumot servislar orqali yaratiladi, shuning uchun jurnal va holat tarixi haqiqiyga o'xshaydi;
  - ikki marta ishga tushirilsa, takrorlamaydi.

**Frontend:**
- `(admin)/team/page.tsx` — jamoa ro'yxati, taklif (havola va nusxalash), rol, o'chirish, parol tiklash.
- `invite/[token]`, `reset-password/[token]` — jamoa a'zosi sahifalari. `@cos/auth` ekranlari panelga qarab o'z endpoint'ini chaqiradi.
- Kartochkada "Ichki izohlar" tabi. Xatodan keyin qayta bosilsa, o'sha kalit ketadi va izoh ikki marta yozilmaydi.
- `command-palette.tsx`:
  - menyudagi tugma yoki ⌘K / Ctrl+K bilan ochiladi;
  - shopni topib ochish, sahifalarga o'tish, "yangi shop yaratish";
  - klaviaturadan boshqariladi.
  Shop yaratish oynasi bitta umumiy joyda (`CreateShopProvider`), shuning uchun istalgan sahifadan ochiladi.
- Shoplar ro'yxatida saralash va "oxirgi faollik"; kartochkada pilot kuni; jurnalda "kim" filtri.
- Sahifaga qaytilganda ma'lumot doim yangilanadi (`staleTime: 0`). Boshqa odam o'zgartirgan holat darhol ko'rinadi — buni e2e testi aniqladi.

**Demo va testlar muhiti:**
- **Demo baza `commerce_os_dev`** (backend `.env`). Eski `commerce_os` bazasiga tegilmagan, unda eski test yozuvlari qolgan.
- **E2E o'z muhitida:**
  - baza `commerce_os_e2e`, backend :8001, frontend :3100/:3101;
  - `e2e/env.ts`, `e2e/global-setup.ts`, `playwright.config.ts`;
  - Playwright backend'ni ham, frontendni ham o'zi ko'taradi, demo ma'lumot ifloslanmaydi.

**Tekshiruv:**
- [x] backend `make check` → **191 passed** (+10)
- [x] frontend `pnpm check` va ikkala build xatosiz
- [x] Playwright → **4 test**, alohida muhitda. Yangisi: admin yordamchini havola bilan taklif qiladi → yordamchi kiradi → tahrir tugmasi yo'q → izoh yozadi → admin uni o'chiradi → yordamchi chiqib ketadi
- [x] demo ma'lumot bilan skrinshotlar ko'rib chiqildi. Yangi amallar nomi va ⌘K'dagi ustma-ust tushish tuzatildi

## 6. Ochiq qolganlar

- **Ichki izoh va jamoa takliflari** — DBML'dagi taklif bo'yicha qurildi (founder: "platforma qismini to'liq tugat"). Commit'dan oldin o'zgartirish mumkin.
- **API o'zgarishi:** `GET /platform/shops` endi `{items, total}` qaytaradi. Frontend client qayta generatsiya qilingan.
- **Eski jurnal yozuvlari** (bu o'zgarishdan oldingi) `shop_id` siz. Kartochka jurnalida ular `entity_id` orqali topiladi, umumiy jurnalda esa shop nomisiz ko'rinadi.

## 7. QA tekshiruvi (2026-10-25)

Mustaqil QA: 11 o'rta va 26 kichik topilma. O'rtalarning hammasi va kichiklarning ko'pi tuzatildi; qolgan 7 tasi 8-bo'limda.

**Founder qarori (M11):** "Platforma jamoasi" bo'limi faqat adminga (business/15 §5). `PLATFORM_SUPPORT` dan `platform.staff.view` olindi → support menyuda bo'limni ko'rmaydi, to'g'ridan manzilda "Ruxsat yo'q", jurnaldagi "Kim" filtri ham yashirin.

**Backend:**
- Shop yopilsa (`CLOSE`) → shopning hamma sessiyasi tugaydi (`revoked_reason = SHOP_CLOSED`). Shu sessiya bilan kelgan so'rov va refresh → `SHOP_NOT_ACTIVE`, klient sababini ko'rsatadi. To'xtatilganda (`SUSPEND`) sessiyalar qoladi — shop ichki ishini davom ettiradi (business/13).
- `PATCH /shop/profile` va `PATCH /platform/shops/{id}`: body'da yo'q maydon o'zgarmaydi (`exclude_unset`). Oldin `legal_name`, til va vaqt zonasi standart qiymatga qaytib qolardi.
- Vaqt zonasi IANA ro'yxatidan tekshiriladi → noma'lumi `VALIDATION_FAILED`, `timezone / invalid_choice`.
- Tekshiruvga yuborish → kamida bitta ochiq filial shart (`branches / required`).
- Sozlamalar: operator chegirma limiti menejernikidan oshmaydi (`discount_limit_sales_pct / max_value`); eslatma soatlari 1…720.
- Platforma tahririda sabab kamida 3 belgi (holat o'zgartirish sababi bilan bir xil).
- Buzuq JSON → `400 INVALID_REQUEST` (oldin `VALIDATION_FAILED` edi). Har 429 javobida `Retry-After` sarlavhasi (bloklash ham, rate limit ham).
- Parol: oddiy parollar ro'yxati ~220 ta (xalqaro + mahalliy: `toshkent`, `uzbekistan`, `parol123`…). Parolda telefonning oxirgi 7 raqami bo'lsa (ajratgichlar bilan ham) → `too_weak`.
- Parolni o'zgartirish: joriy parol noto'g'ri → `current_password / invalid`; yangisi joriysi bilan bir xil → `new_password / same_as_current`; oddiy parol → `new_password / too_weak`. Ikki yangi kod 11 §6.3 ro'yxatiga qo'shildi.
- Bosh sahifadagi "Ega kirmagan" ro'yxati → faqat havolasi eskirgan yoki 24 soatda eskiradiganlar.

**Frontend:**
- Xato matnlari kod bo'yicha tarjima qilinadi (`errors.codes`, katalogdagi hamma kod, uz/ru/en). Noma'lum kodda — umumiy "Kutilmagan xato" matni, backend'ning inglizcha matni hech qachon ko'rsatilmaydi (11 §8.8; 2026-10-25 tuzatildi, M02 §9). Forma ostiga tushmagan `VALIDATION_FAILED` → "Maydonlarni tekshiring" va qaysi maydon ekani.
- Har qanday so'rov `SHOP_NOT_ACTIVE` qaytarsa → sessiya tugaydi, login sahifasida "Shop yopilgan…". Oynaga qaytilganda `me` yangilanadi (ko'pi bilan daqiqada bir marta).
- Platforma menyusi va ⌘K amallari ruxsatga qarab. Sahifalar ruxsat yo'q bo'lsa `Forbidden`. Biror so'rov 403 qaytarsa → ruxsatlar qayta olinadi, sahifa eski ma'lumot o'rniga "Ruxsat yo'q" ko'rsatadi. Kutubxona muharriri bosh sahifada bo'sh oyna emas, "bo'limingiz katalog moduli bilan keladi" ko'radi.
- Holat oynasi: sabab 3 belgidan qisqa bo'lsa tugma o'chiq va ostida qoida; server xatosi maydon ostida. Izoh matni endi "shop egasi ko'radi" demaydi (ko'rmaydi).
- Jurnal: `auth.*` amallari va o'zgargan maydon nomlari tarjima qilingan (`fields`).
- Uzun matn (izoh, sabab, nom) qatorga sig'adi; textarea faqat bo'yiga cho'ziladi.
- Shop paneli 390px da gorizontal aylanmaydi (jadvallar karta ichida aylanadi). Platforma menyusi telefonda hamma bandi bilan ko'rinadi. E2E ikkalasini ham tekshiradi.
- Vaqt zonasi — ro'yxatdan tanlanadi. Sessiyalarda "Chrome · macOS". Login: "Telefon raqamini to'liq kiriting", bloklash daqiqada. Foydalanuvchi menyusida rol tarjimasi. Shop ro'yxatida slug va "3 xodim · 2 filial". Bosh sahifada qoralama, yopilgan va 7 kunlik yangi shoplar. Ruscha/inglizcha sonli matnlar ko'plik shaklisiz yozildi. Kartochkada tanlangan tab ko'rinadigan joyga suriladi. Jamoa oynalarida amal xato bersa ro'yxat yangilanadi; holat boshqa joyda o'zgargan bo'lsa (404/409) oyna yopiladi.

**Tekshiruv:**
- [x] backend `make check` → **205 passed** (+14)
- [x] frontend `pnpm check` va ikkala build xatosiz
- [x] Playwright → **5 test**. Yangilari: support jamoa bo'limini ocha olmaydi; shop yopilsa ega darhol chiqariladi va sababini ko'radi; shop va platforma paneli 390px da enidan oshmaydi

## 8. QA topilmalari — keyinga qoldirilgan

- **L6 — login javobidan telefon bor-yo'qligini bilish.** Hozir bir xil xabar va vaqt; to'liq himoya (CAPTCHA, IP bo'yicha qattiqroq limit) — ochiq ro'yxatdan o'tish paydo bo'lganda.
- **L10 — `working_hours` sxemasi.** Filial ish vaqti UI'si yo'q (L24), sxemani u bilan birga belgilaymiz.
- **L11 — o'xshash nomli shop haqida ogohlantirish.** STIR va slug noyob; nom takrori xato emas, pilot hajmida kerak emas.
- **L12 — telefonning bir qismi bo'yicha qidiruv.** Hozir to'liq raqam (istalgan ko'rinishda); qisman qidiruv uchun indeks kerak — shoplar ko'payganda.
- **L14 — jurnal qatorida nishon nomi (qaysi xodim, qaysi filial).** Audit'da faqat `entity_id`; nomni olish uchun har domen bo'yicha qo'shimcha so'rov kerak — reporting proyeksiyasi bilan.
- **L22 — havolani oldindan tekshirish endpoint'i.** Hozir xato parol yuborilganda chiqadi; oldindan tekshirish havolani "ishlatmasdan" holatini oshkor qiladi — xavfsizlik bilan birga ko'rib chiqiladi.
- **L24 — filial ish vaqti va xarita UI.** Buyurtma va olib ketish moduli bilan keladi (u yerda kerak bo'ladi).
