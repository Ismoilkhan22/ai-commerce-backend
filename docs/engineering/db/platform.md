# `platform` schemasi — ma'lumotlar lug'ati

> **Holat:** qoralama, founder ko'rib chiqmoqda (2026-10-23). Diagramma: [`platform.dbml`](platform.dbml) → dbdiagram.io.
> **Kim o'qiydi:** founder va dasturchilar. Har jadval: nima uchun kerak → har maydon nima va nega shunday → bog'lanishlar → misol.

Misollarda bitta shop ishlatiladi: **"TechPC"** (Chilonzor va Yunusobod filiallari), egasi **Ali**, operatori **Vali**.

---

## 0. Hamma jadvallarga tegishli umumiy qarorlar

Bu qarorlar har jadvalda takrorlanadi, shuning uchun bir marta tushuntiraman.

| Narsa | Qanday | Nega shunday |
|---|---|---|
| `id uuid` | Har qatorning noyob raqami, UUIDv7 formatida (`0192b6f0-3c1a-7c2e-…`) | **Oddiy raqam (1, 2, 3) emas, chunki:** 1) URL'da `/orders/1042` bo'lsa, boshqa raqamni yozib ko'rib, birovning buyurtmasini taxmin qilish oson; 2) bir nechta server yoki dedicated o'rnatishda raqamlar to'qnashmaydi; 3) ID bazaga yozilmasdan oldin ilovada yaratiladi — event va loglarda darhol ishlatish mumkin. **v7 bo'lishi shart**, chunki u vaqt bo'yicha o'sadi — bazada indeks tez ishlaydi (tasodifiy UUID katta jadvallarni sekinlashtiradi) |
| `shop_id` | Qator qaysi shopga tegishli | Bitta bazada yuzlab shop yashaydi. Har so'rov `shop_id` bo'yicha filtrlanadi, baza ham buni RLS bilan tekshiradi. Bu ustunsiz A shop B shop ma'lumotini ko'rib qolishi mumkin edi (TC-001) |
| `(shop_id, id)` juftligi bilan bog'lash | Masalan, xodimni filialga biriktirishda ham `shop_id`, ham `branch_id` tekshiriladi | Faqat `branch_id` bilan bog'lansa, kodda xato bo'lganda Valini **boshqa shopning** filialiga biriktirib qo'yish mumkin. Juftlik bilan bog'langanda baza buni rad etadi: filial boshqa shopniki bo'lsa, `shop_id` mos kelmaydi |
| `created_at`, `updated_at` | Qachon yaratilgan va oxirgi marta o'zgargan | Muammoni tekshirish va hisobotlar uchun. **`timestamptz` (UTC)** — vaqt zonasi bilan saqlanadi. Ko'rsatishda Toshkent vaqtiga o'giriladi; shunda yozgi/qishki vaqt yoki boshqa davlatdagi server chalkashlik qilmaydi |
| `version` | O'zgarishlar hisoblagichi: 1, 2, 3… | **Ikki kishi bir vaqtda o'zgartirsa.** Ali va menejer bir vaqtda sozlamalarni ochdi: Ali saqladi (version 1 → 2), menejer eski sahifadan saqlamoqchi (u version 1 deb o'ylaydi) → tizim "Ma'lumot o'zgargan, sahifani yangilang" deydi (`VERSION_CONFLICT`). Busiz menejer Alining o'zgarishini bilmasdan ustidan yozib yuborardi |
| `status` matn sifatida | `'ACTIVE'`, `'DISABLED'`… + baza tekshiruvi (`CHECK`) | PostgreSQL'ning maxsus `ENUM` turi o'rniga oddiy matn ishlatiladi, chunki yangi holat qo'shish migratsiyada osonroq. `CHECK` esa noto'g'ri qiymat (`'ACTIV'`) yozilishiga yo'l qo'ymaydi |
| O'chirish yo'q | Xodim ketsa `DISABLED`, filial yopilsa `CLOSED` | O'chirilsa, tarix buziladi: "bu buyurtmani kim tasdiqlagan edi?" degan savolga javob yo'qoladi. Jismoniy o'chirish faqat shaxsiy ma'lumotlarni saqlash muddati tugaganda (`26`) |
| `[delete: restrict]` | Bog'langan narsa bor ekan, ota yozuvni o'chirib bo'lmaydi | Masalan, filiallari bor shopni tasodifan o'chirib bo'lmaydi |
| `[delete: cascade]` | Ota o'chsa, bola ham o'chadi | Faqat mustaqil ma'nosi yo'q yozuvlarda: a'zolik o'chsa, uning rollari ham kerak emas |

---

## 1. `shops` — shopning o'zi

**Nima uchun kerak:** platformadan foydalanadigan har do'kon — **tenant**. Qolgan hamma ma'lumot (filial, xodim, mahsulot, buyurtma) shu yerdagi qatorga bog'lanadi. Har shop uchun bitta qator.

| Maydon | Nima saqlaydi | Nega shunday |
|---|---|---|
| `id` | Shop ID'si | Boshqa jadvallardagi `shop_id` aynan shu qiymat. Bu jadvalning o'zida `shop_id` ustuni yo'q — `id` ning o'zi tenant |
| `slug` | `techpc` — sayt manzili `techpc.platforma.uz` | **`unique`** — ikki shopning manzili bir xil bo'lmasin. Faqat kichik harf, raqam va chiziqcha: manzilda bo'sh joy yoki kirill harfi muammo chiqaradi |
| `name` | "TechPC" — saytda va xabarlarda ko'rinadigan nom | `slug` dan alohida: nomni o'zgartirish manzilni buzmasligi kerak |
| `legal_name` | "TechPC MCHJ" | Shartnoma va hisob uchun. Majburiy emas: pilotda hamma shop yuridik shaxs bo'lmasligi mumkin |
| `tin` | STIR (9 raqam) | **Majburiy va unikal** (founder, 2026-10-23): pilot kelishuvi (`business/14`) va bitta korxona ikki marta ro'yxatdan o'tmasligi uchun |
| `status` | `DRAFT` → `PENDING_VERIFICATION` → `ACTIVE` → `SUSPENDED` / `CLOSED` | Holatlar ketma-ketligi FSM-01 (`business/05`). Faqat platforma jamoasi faollashtiradi (DEC-122). `SUSPENDED` da yangi buyurtma qabul qilinmaydi, eskilari yakunlanadi (TC-023). Har o'tish `transition_log` ga yoziladi |
| `default_locale` | `uz` / `ru` / `en` | Xaridor tili noma'lum bo'lsa, xabarlar shu tilda ketadi |
| `timezone` | `Asia/Tashkent` | "Bugungi buyurtmalar" — Toshkent kuni bo'yicha. Vaqtlar UTC'da saqlanadi, hisobot kunini hisoblash uchun zona kerak |
| `deployment_mode` | `SHARED` / `DEDICATED` | DEC-001: hozir hamma shop bitta tizimda (`SHARED`). Katta mijozga alohida o'rnatish bo'lsa — `DEDICATED`. Kod ikkala holatda bir xil ishlashi uchun oldindan belgi qo'yilgan |
| `activated_at` | Qachon faollashtirilgan | Pilotning 30 kuni shu sanadan sanaladi (DEC-119) |
| `created_at`, `updated_at`, `version` | §0 | |

**Bog'lanishlar:** boshqa hamma jadval shu jadvalga bog'lanadi. O'zi hech kimga bog'lanmaydi.

---

## 2. `branches` — filiallar

**Nima uchun kerak:** shopning jismoniy joylari. Qoldiq filial bo'yicha yuritiladi (Chilonzorda 2 ta, Yunusobodda 0 ta). Xaridor olib ketish joyini tanlaydi, xodimni bitta filialga cheklash mumkin.

| Maydon | Nima saqlaydi | Nega shunday |
|---|---|---|
| `id`, `shop_id` | Filial va uning shopi | §0 |
| `name` | "Chilonzor filiali" | Xodim va xaridor ko'radi |
| `address` | To'liq manzil | Saytda va AI javoblarida ("Chilonzorda olib ketsangiz bo'ladi") |
| `phone` | Filial telefoni | Majburiy emas: kichik shopda bitta umumiy raqam bo'ladi |
| `latitude`, `longitude` | Xaritadagi nuqta | Saytda xarita, keyinroq (Stage 3) "eng yaqin do'kon" qidiruvi. `numeric(9,6)` — taxminan 10 sm aniqlik, float'ning yaxlitlash xatosi yo'q |
| `working_hours` | `{"mon": [["10:00","20:00"]], ...}` | **JSON**, chunki ish vaqti murakkab: tushlik tanaffusi (bir kunda ikki oraliq), dam olish kuni. Alohida jadval qilish ortiqcha murakkablik |
| `is_pickup_point` | Xaridor shu yerdan olib keta oladimi | Ba'zi filial faqat ombor bo'lishi mumkin |
| `status` | `ACTIVE` / `CLOSED` | Yopiq filialni olib ketish joyi sifatida tanlab bo'lmaydi (UAT-M03). O'chirilmaydi — eski buyurtmalar unga bog'langan |
| `created_at`, `updated_at`, `version` | §0 | |

**Indekslar:**
- `(shop_id, id)` — unikal. Boshqa jadvallar filialga **shop bilan birga** bog'lanishi uchun (§0).
- `(shop_id, status)` — "shopning faol filiallari" so'rovi tez ishlashi uchun.

**Bog'lanish:** `branches.shop_id → shops.id`, **restrict**: filiali bor shopni o'chirib bo'lmaydi.

---

## 3. `shop_policies` — shop sozlamalari

**Nima uchun kerak:** har shop o'z qoidalarini sozlaydi (chegirma limiti, taklif muddati…). Bu qiymatlar kodga qattiq yozilmaydi — bitta shop uchun 24 soat, boshqasi uchun 48 soat bo'lishi mumkin. Har shop uchun bitta qator.

**Nega `shops` ichida emas:** sozlamalar ko'p va tez-tez o'zgaradi, `shops` esa kam o'zgaradi. Alohida jadvalda alohida `version` bor — sozlamani o'zgartirish shop profilini tahrirlayotgan odam bilan to'qnashmaydi. Faqat ega o'zgartiradi (`shops.policy.edit`).

| Maydon | Standart qiymat | Nima va nega |
|---|---|---|
| `shop_id` | — | **Primary key** ham, shopga bog'lanish ham: bitta shopga bitta sozlama |
| `quote_ttl_hours` | 24 | PC taklifi necha soat amal qiladi (DEC-103). Narxlar tez o'zgaradi — eski taklif shu muddatdan keyin bekor |
| `discount_limit_sales_pct` | 0 | Operator so'rovsiz bera oladigan chegirma, % (DEC-110). 0 — operator chegirmani faqat so'raydi |
| `discount_limit_manager_pct` | 5 | Menejer tasdiqlay oladigan chegara. Undan katta chegirmani faqat ega tasdiqlaydi |
| `order_reminder_hours` | `{24,72}` | Tasdiqlanmagan buyurtma bo'yicha operatorga eslatmalar (DEC-104). Massiv — shop o'z oraliqlarini qo'yishi mumkin |
| `quote_approval_mode` | `ALL` | `ALL` — har PC taklifi tasdiqdan o'tadi (pilot). `RISKY_ONLY` — faqat xavfli holatlarda: katta summa, moslik noaniq, chegirma bor (DEC-102) |
| `exchange_rate_source` | `MANUAL` | Dollar kursi: shop o'zi kiritadi yoki Markaziy bank kursi (DEC-121) |
| `stock_display` | `STATUS_ONLY` | Saytda qoldiq: aniq son yoki "bor / kam qoldi / yo'q" (DEC-128) |
| `low_stock_threshold` | 2 | Nechtadan kam bo'lsa "kam qoldi" deyiladi |
| `updated_at`, `version` | — | §0. `created_at` yo'q — shop bilan birga yaratiladi |

**Pul foizlari `numeric(5,2)`:** 2.5% ni aniq saqlaydi. Float'da `2.5` ba'zan `2.4999…` bo'lib qoladi.

**Bog'lanish:** `shop_policies.shop_id — shops.id` — **bittaga bitta**.

---

## 4. `principals` — tizimga kiradigan odamlar

**Nima uchun kerak:** login ma'lumotlari — kim u, qanday kiradi.

**Nega shopdan alohida:** hozircha bir odam faqat bitta shopda ishlaydi (DEC-131), lekin **odam** (`principals`) va **uning shopdagi ishi** (`memberships`) baribir ajratilgan. Sabablari: 1) platforma jamoasi ham shu jadvaldan kiradi, lekin hech qaysi shop xodimi emas; 2) keyin bir odam bir nechta shopda ishlashi kerak bo'lsa, ma'lumotni ko'chirmasdan bitta cheklovni olib tashlash yetadi. Shuning uchun bu jadvalda `shop_id` yo'q.

| Maydon | Nima saqlaydi | Nega shunday |
|---|---|---|
| `id` | Odam ID'si | |
| `phone` | `+998901234567` | **Majburiy.** Asosiy login usuli: O'zbekistonda hamma telefonni ishlatadi, email kam; taklif ham shu raqamga beriladi. **E.164 formatda** saqlanadi — `90 123 45 67` va `+998 90…` bitta raqam deb tanilishi uchun. **`unique`** — bitta raqam bitta odam |
| `email` | `ali@techpc.uz` | Ixtiyoriy, ikkinchi login usuli. `unique` |
| `full_name` | "Ali Valiyev" | Panelda va tarixda: "buyurtmani Vali tasdiqladi" |
| `password_hash` | Shifrlangan parol (Argon2id) | **Parolning o'zi hech qachon saqlanmaydi**, faqat bir tomonlama hash. Baza o'g'irlansa ham parollar ochilmaydi. Argon2id — hozirgi eng xavfsiz standart. Taklif qabul qilinguncha `NULL` |
| `locale` | `uz` / `ru` / `en` | Panel interfeysi tili (11 §8.2) |
| `status` | `ACTIVE` / `BLOCKED` | `BLOCKED` — platforma odamni butunlay bloklagan, hech qaysi shopga kira olmaydi. Bitta shopdan chiqarish esa `memberships` da |
| `phone_verified_at` | Telefon tasdiqlangan vaqt | Taklif havolasini ochib parol o'rnatganda belgilanadi — raqam haqiqatan shu odamniki |
| `failed_login_attempts` | Ketma-ket xato parollar soni | **Parolni terib topishdan himoya.** Masalan, 5 marta xato bo'lsa — vaqtincha blok. To'g'ri kirganda 0 ga qaytadi |
| `locked_until` | Blok qachongacha | Masalan, 15 daqiqa. Shu vaqtgacha to'g'ri parol bilan ham kirib bo'lmaydi |
| `password_changed_at` | Parol oxirgi marta qachon o'zgargan | Parol o'zgarsa, undan oldin ochilgan sessiyalar bekor qilinadi — o'g'irlangan sessiya ishlamay qoladi |
| `last_login_at` | Oxirgi kirish | Xavfsizlik: uzoq kirmagan akkauntni aniqlash |
| `created_at`, `updated_at`, `version` | §0 | |

**Shaxsiy ma'lumot:** telefon va email logga ham, event'larga ham yozilmaydi (`09`, `26`).

---

## 5. `memberships` — kim qaysi shopda ishlaydi

**Nima uchun kerak:** odamni shopga bog'laydi. Ruxsatlar shu yerdan boshlanadi: "Vali TechPC'da faol xodim, faqat Chilonzor filialida".

| Maydon | Nima saqlaydi | Nega shunday |
|---|---|---|
| `id`, `shop_id` | A'zolik va shop | §0 |
| `principal_id` | Qaysi odam | `principals` ga bog'lanadi |
| `role` | `OWNER` / `MANAGER` / `SALES` / `WAREHOUSE` | **Bitta xodim — bitta rol** (DEC-131). Kichik shopda ega baribir hamma narsani qila oladi, shuning uchun bir odamga bir nechta rol berish kerak emas. Rollar va ular nima qila olishi — `business/04` |
| `status` | `INVITED` → `ACTIVE` → `DISABLED` | `INVITED` — taklif yuborilgan, hali qabul qilinmagan. `DISABLED` — ishdan ketgan: kira olmaydi, sessiyalari darhol tugaydi (TC-025), lekin tarixi qoladi |
| `branch_scope` | `ALL` / `SELECTED` | `ALL` — hamma filiallar (ega, menejer). `SELECTED` — faqat `membership_branches` dagilari. Alohida belgi kerak, chunki "ro'yxat bo'sh" bilan "hamma filial" farqini aniq bilish lozim |
| `invited_by` | Kim taklif qilgan (boshqa a'zolik) | Audit: "Valini Ali qo'shgan" |
| `activated_at`, `disabled_at` | Qachon qo'shilgan va qachon o'chirilgan | Hisobot va audit |
| `created_at`, `updated_at`, `version` | §0 | |

**Indekslar:**
- `(shop_id, principal_id)` **unikal** — bir odamning bir shopda ikkita a'zoligi bo'lmaydi (rollar alohida jadvalda).
- `(shop_id, id)` unikal — rollar va filiallar a'zolikka shop bilan birga bog'lanishi uchun.
- `principal_id` **unikal** — hozircha bir odam faqat bitta shopda ishlaydi (founder, 2026-10-23). Jadvallar ajratilgani uchun keyin ko'p shopga o'tish faqat shu cheklovni olib tashlash bilan bo'ladi, ma'lumotni qayta ko'chirish kerak emas.

**Muhim qoida:** shopda kamida bitta faol `OWNER` qolishi shart. Oxirgi egani o'chirib yoki rolini o'zgartirib bo'lmaydi (`LAST_OWNER_REQUIRED`, UAT-M02). Bu kodda **va** bazadagi trigger bilan tekshiriladi.

**Ruxsatlar qayerda:** "Operator nima qila oladi" ro'yxati bazada emas, **kodda** (`app/platform/staff/permissions.py`, DEC-131). Rollar hamma shop uchun bir xil va o'zgarmaydi, shuning uchun ro'yxat kod bilan birga versiyalanadi va testlar uni avtomatik tekshiradi (TC-API-06). Ruxsat kodlarining to'liq katalogi — `engineering/10` §6. Shop o'z rolini yaratadigan bo'lsa (Stage 2), jadval qo'shiladi.

**Bog'lanishlar:** `→ shops` (restrict), `→ principals` (restrict), `invited_by → memberships` (o'ziga).

---

## 6. `membership_branches` — xodim qaysi filiallarda ishlaydi

**Nima uchun kerak:** Vali faqat Chilonzorni ko'rishi va o'zgartirishi kerak (`business/04` qoida 2). Faqat `branch_scope = SELECTED` bo'lsa ishlatiladi.

| Maydon | Nega |
|---|---|
| `shop_id`, `membership_id`, `branch_id` | Uchala ustun ham shop bilan birga bog'lanadi: xodimni **boshqa shopning** filialiga biriktirib bo'lmaydi |

**Primary key `(membership_id, branch_id)`** — bir filial bir odamga ikki marta yozilmaydi.
**Bog'lanishlar:** `→ memberships` (cascade), `→ branches` (restrict: xodim biriktirilgan filialni o'chirib bo'lmaydi; faqat yopish mumkin).

---

## 7. `invitations` — xodimni taklif qilish

**Nima uchun kerak:** Ali Valini qo'shadi → Valiga havola ketadi → Vali bosib, parol o'rnatadi → a'zoligi `ACTIVE` bo'ladi.

| Maydon | Nima saqlaydi | Nega shunday |
|---|---|---|
| `id`, `shop_id` | | §0 |
| `membership_id` | `INVITED` holatidagi a'zolik | Taklif qabul qilinganda shu a'zolik faollashadi |
| `token_hash` | Havoladagi maxfiy kodning hash'i | **Kodning o'zi saqlanmaydi.** Baza o'g'irlansa ham havolalar ishlamaydi (parol kabi). `unique` |
| `channel` | Hozir faqat `LINK` | **Ega havolani o'zi nusxalab yuboradi** (masalan, Telegram'da) — bepul, qo'shimcha xizmat kerak emas (DEC-131). Ustun keyin SMS yoki Telegram bot qo'shilishi uchun qoldirilgan |
| `expires_at` | Muddati (masalan, 72 soat) | Eski havola cheksiz ishlamasligi kerak — xavfsizlik |
| `accepted_at`, `revoked_at` | Qabul qilindi yoki bekor qilindi | Qayta yuborilsa — yangi qator yoziladi, eskisi bekor qilinadi. Shunda faqat oxirgi havola ishlaydi |
| `created_at` | | |

**Nega `memberships` ichida emas:** taklif bir necha marta qayta yuborilishi mumkin va har birining o'z muddati bor. Qabul qilingach esa taklif kerak emas, a'zolik qoladi.

**Bog'lanish:** `(shop_id, membership_id) → memberships`, cascade.

---

## 8. `sessions` — kim tizimga kirib turibdi

**Nima uchun kerak:** login qilingandan keyin har safar parol so'ramaslik uchun (ADR-023, DEC-008):
- **access token** — 10–15 daqiqa yashaydi, brauzer xotirasida, bazaga yozilmaydi;
- **refresh token** — uzoq yashaydi, `httpOnly` cookie'da, uning hash'i shu jadvalda. Access token tugaganda yangisini olish uchun ishlatiladi.

| Maydon | Nima saqlaydi | Nega shunday |
|---|---|---|
| `id` | Sessiya | |
| `principal_id` | Kimning sessiyasi | |
| `shop_id` | Xodim qaysi shopda ishlayapti | Hozir har odamda bitta shop. Platforma xodimi uchun `NULL`. Bu faqat **ishora**: har so'rovda a'zolik bazadan qayta tekshiriladi |
| `family_id` | Token zanjiri | Har refresh'da yangi token beriladi, eskisi bekor qilinadi (rotation). **O'g'irlangan eski token** qayta ishlatilsa, tizim buni ko'radi va butun zanjirni bekor qiladi — o'g'ri ham, egasi ham chiqib ketadi, egasi qayta kiradi |
| `refresh_token_hash` | Token hash'i | Tokenning o'zi saqlanmaydi. `unique` |
| `expires_at`, `revoked_at`, `revoked_reason` | Muddati, bekor qilinganmi, nega | `revoked_reason`: chiqib ketdi, almashtirildi, o'g'irlik shubhasi, xodim o'chirildi — xavfsizlik tekshiruvi uchun |
| `user_agent` | Qaysi qurilma yoki brauzer | "Faol qurilmalar" ro'yxati va shubhali kirishni aniqlash |
| `created_at`, `last_used_at` | | |

**Indekslar:** `(principal_id, revoked_at)` — "odamning faol sessiyalari", xodim o'chirilganda hammasini bekor qilish uchun. `family_id` — zanjirni tez bekor qilish uchun.
**Bog'lanishlar:** `→ principals` (cascade), `→ shops`.

---

## 9. `platform_staff` — bizning jamoa

**Nima uchun kerak:** shoplarni faollashtiradigan, texnik ma'lumotlar kutubxonasini yuritadigan, yordam beradigan odamlar. Ular shop xodimi emas, shuning uchun `memberships` da emas.

| Maydon | Nega |
|---|---|
| `principal_id` | Oddiy foydalanuvchi akkaunti. `unique` — bir odam jamoada bir marta |
| `role` | `PLATFORM_ADMIN` (shopni faollashtiradi), `PLATFORM_SUPPORT` (yordam), `SPEC_EDITOR` (PC texnik ma'lumotlari, DEC-120) |
| `status` | `ACTIVE` / `DISABLED` |

**Muhim:** platforma jamoasi shopning suhbat va savdolarini **odatiy holatda ko'rmaydi** (`business/04`). Faqat shop egasi roziligi bilan, vaqtinchalik va yozib qo'yiladigan tarzda kiradi — buning jadvali (`support_grants`) keyingi bosqichda qo'shiladi.

---

## 10. `transition_log` — holat o'zgarishlari jurnali (kodda bor)

**Nima uchun kerak:** "TechPC qachon va kim tomonidan faollashtirildi?", "Bu buyurtmani kim, qachon tasdiqladi?" degan savollarga javob. Hamma domenlarning holat o'zgarishlari shu bitta jadvalda (ADR-034).

| Maydon | Nega |
|---|---|
| `entity_type`, `entity_id` | Nima o'zgardi: `platform.shop` + TechPC ID'si |
| `command`, `from_status`, `to_status` | Qanday o'zgardi: `ACTIVATE`, `PENDING_VERIFICATION` → `ACTIVE` |
| `actor_type`, `actor_id` | Kim: xodim, AI, tizim, xaridor yoki platforma |
| `reason` | Nega (bekor qilishda majburiy) |
| `forced` | Platforma admini qoidani chetlab o'tganmi (faqat favqulodda holatlarda) |
| `trace_id` | Loglardagi shu so'rovni topish uchun |
| `occurred_at` | Qachon |

**Nega `(id, occurred_at)` primary key:** jadval oyma-oy bo'lingan (partition) — u tez o'sadi, eski oylarni arxivlash oson bo'lishi kerak. PostgreSQL bo'lingan jadvalda bo'lish ustunini primary key ichida talab qiladi.
**Faqat qo'shiladi:** ilova bu yozuvlarni o'zgartira yoki o'chira olmaydi — baza ruxsat bermaydi. Tarixni soxtalashtirib bo'lmaydi.
**Nega bog'lanish yo'q:** u hamma domenlardan yozuv oladi. Boshqa schemalarga FK qo'yish taqiqlangan (ADR-035).

---

## 11. `idempotency_keys` — takroriy so'rov himoyasi (kodda bor)

**Nima uchun kerak:** internet sekin bo'lib, operator "Tasdiqlash" tugmasini ikki marta bosdi yoki brauzer so'rovni qayta yubordi. Tizim buni bitta amal deb bilishi kerak, aks holda mahsulot ikki marta band qilinadi (TC-003).

| Maydon | Nega |
|---|---|
| `shop_id`, `operation`, `key` | So'rovning noyob kaliti; frontend har amal uchun yangi kalit yaratadi. Shop bo'yicha ajratilgan |
| `request_hash` | So'rov tanasining izi. Kalit bir xil-u, tana boshqa bo'lsa — bu xato (409) |
| `response_status`, `response_body` | Birinchi javob. Takroriy so'rovga aynan shu qaytariladi |
| `expires_at` | 24 soatdan keyin tozalanadi — jadval cheksiz o'smasin |

---

## Bog'lanishlar xaritasi

```
shops ─┬─< branches ─────────────────────────┐
       ├── shop_policies (1:1)                │
       ├─< memberships (role) >── principals ──< sessions
       │      ├─< membership_branches >───────┘ (shop_id bilan birga)
       │      └─< invitations
       └─< sessions (tanlangan shop)
principals ── platform_staff (1:1)
transition_log, idempotency_keys — mustaqil (FK yo'q)

─<  bittaga ko'p        ──  bittaga bitta
```

## Founder qarorlari (2026-10-23, DEC-131)

1. Bir odam hozircha **faqat bitta shopda** ishlaydi (`memberships.principal_id` unikal).
2. **Bitta xodim — bitta rol**; Stage 1 da 4 ta rol: Ega, Menejer, Operator, Omborchi.
3. Rol → ruxsatlar ro'yxati **kodda**, bazada jadval yo'q.
4. Taklif havolasini **ega o'zi yuboradi**.
5. **STIR majburiy.**

## Hali ochiq

- Kirish usuli: telefon + parol (hozirgi loyiha). SMS kod (OTP) keyinroq — SMS provayder kerak bo'ladi.
- Standart qiymatlar: chegirma 0% / 5%, eslatmalar 24/72 soat, taklif muddati 24 soat, "kam qoldi" — 2 ta.
