# `storefront` schemasi — ma'lumotlar lug'ati (shop sayti)

> **Holat:** ✅ tasdiqlangan — DEC-135 (2026-10-25). Founder qarorlari oxirida. Diagramma: [`storefront.dbml`](storefront.dbml) → dbdiagram.io.
> **Kim o'qiydi:** founder va dasturchilar. Har jadval quyidagi tartibda: nima uchun kerak → har maydon nima va nega shunday → bog'lanishlar → misol.
> **Umumiy qoidalar** (`id`, `shop_id`, `version`, holat matn sifatida, o'chirish yo'qligi) — [platform.md](platform.md) §0. Bu yerda takrorlanmaydi.
> **Hajm:** shop sayti (M07, S1-07, DEC-115): sayt sozlamalari va ma'lumot sahifalari. Katalog nusxasi va shopning o'z domeni — keyin (DEC-135).

Misollarda **"TechPC"** shopi ishlatiladi. Ega — **Ali**. Sayt manzili — **techpc.platforma.uz** (`slug = techpc`). Filiallar — **Chilonzor** va **Yunusobod**. Xaridor — **Jasur**. Mahsulot — **"MSI GeForce RTX 4060 Ventus 2X"**, 4 800 000 so'm.

---

## 0. Asosiy g'oya: sayt — oyna

Sayt o'zi deyarli hech narsa saqlamaydi. U boshqa joylardagi ma'lumotni xaridorga chiroyli va xavfsiz ko'rsatadi:

- **Shop nomi, manzili (slug), filiallar, ish vaqti** — `platform` (1-modul). Sayt manzili `techpc.platforma.uz` shop yaratilganda band qilinadi (M01, 4-band).
- **Mahsulot, variant, narx, kurs, rasm, toifalar** — `catalog` (2-modul).
- **Qoldiq, buyurtma so'rovi, buyurtma holati** — `commerce` (3-modul). Saytdagi "Buyurtma berish" `commerce.orders` ga yoziladi (DEC-115).
- **Saytdagi chat** — `messaging` (5-modul, web chat kanali).

`storefront` schemasida faqat **saytning o'ziga tegishli** narsa turadi: rangi va logotipi, kontaktlari, ochiq yoki yopiqligi, ma'lumot sahifalari. Shuning uchun bu kichik schema: hozir 2 ta jadval.

**Sayt qachon ko'rinadi:**

```
Qoralama (DRAFT) ──(Ali "Saytni ochish" bosdi)──▶ Ochiq (LIVE)          [telefon majburiy; shop hali faol bo'lmasa, xaridor ko'rmaydi]
Ochiq ──(Ali "Vaqtincha yopish" bosdi)──▶ To'xtatilgan (PAUSED)         [xaridor: "vaqtincha ishlamayapti", buyurtma qabul qilinmaydi]
To'xtatilgan ──(Ali "Qayta ochish" bosdi)──▶ Ochiq
```

Xaridor nima ko'radi — shop holati (platforma) va sayt holati birga hal qiladi:

- Shop **faol** va sayt **ochiq** → sayt ishlaydi.
- Shop hali faollashtirilmagan (qoralama yoki tekshiruvda) yoki sayt **qoralama** → "Sayt tez orada ochiladi". Faqat shop nomi ko'rinadi (M01: platforma faollashtirmaguncha sayt ochilmaydi).
- Shop **to'xtatilgan** yoki sayt **to'xtatilgan** → "Vaqtincha ishlamayapti" (M07). Buyurtma qabul qilinmaydi.
- Shop **yopilgan** yoki bunday manzil yo'q → "Topilmadi".

**Ko'rib chiqish.** Ali saytni ochishdan oldin panelda "Ko'rib chiqish" ni bosadi va saytni xaridor ko'rganidek ko'radi. Bu 30 daqiqalik imzoli havola bilan ishlaydi, bazada saqlanmaydi. Ko'rib chiqishda buyurtma formasi o'chiq.

---

## 1. `sites` — sayt sozlamalari

**Nima uchun kerak:** saytning ko'rinishi va kontaktlari bitta joyda. Har shopga bitta yozuv. Ali panelda "Shop sayti" sahifasini ochadi, logotip yuklaydi, rang tanlaydi, telefonini yozadi va saytni ochadi (business/13, 3.3).

- **`shop_id`** — primary key. Sayt manzili shu shopning `platform.shops.slug` i, shuning uchun bu yerda manzil ustuni yo'q: ikki joyda tursa, bir-biridan farq qilib qolishi mumkin edi.
- **`status`** — `DRAFT` (qoralama), `LIVE` (ochiq), `PAUSED` (vaqtincha yopilgan). Yuqoridagi §0 ga qarang.
- **`logo_file_id`** — logotip, `platform.stored_files` da. Fayl turlariga `SITE_LOGO` qo'shiladi (§8). Mahsulot rasmlari kabi ochiq (DEC-133): Telegram va Instagram'da havola oldindan ko'rinishida chiqadi. Logotip bo'lmasa — shop nomining bosh harflari ("TP").
- **`accent_color`** — asosiy rang (tugmalar, havolalar), `#RRGGBB`. Tizim rangning matn bilan kontrastini tekshiradi: oq fonda och sariq tugma o'qilmaydi, shunday rangni tanlab bo'lmaydi.
- **`theme_mode`** — oq yoki to'q fon.
- **`tagline`** — qisqa shior, bosh sahifada va Google'da: "Kompyuter qismlari — rasmiy kafolat bilan".
- **`seo_description`** — Google natijasida va havola oldindan ko'rinishida chiqadigan 1–2 gap. Bo'sh bo'lsa, shior ishlatiladi.
- **`contact_phone`** — saytdagi asosiy telefon. Saytni ochishdan oldin **majburiy**: xaridor shopga qo'ng'iroq qila olishi kerak. Filial telefonlari `platform.branches` da, ular filial ro'yxatida ko'rinadi.
- **`contact_email`** — ixtiyoriy.
- **`telegram_username`**, **`instagram_username`** — faqat username, havola emas. Tizim havolani o'zi yasaydi (`t.me/techpc_uz`). Shunday qilib saytga begona yoki firibgar havola qo'yib bo'lmaydi.
- **`published_at`** — birinchi marta ochilgan vaqt. **`status_changed_at`** — oxirgi holat o'zgarishi.
- **`updated_by`**, **`version`** — kim o'zgartirdi; ikki oynada bir vaqtda saqlansa, ikkinchisi "o'zgargan" xabarini oladi.

**Kim o'zgartiradi:** faqat ega (`storefront.site.edit`, engineering/10 §6.6).
**Qachon yaratiladi:** Ali birinchi marta saqlaganda. Yozuv yo'q bo'lsa — sayt qoralama hisoblanadi.
**Tarix:** har o'zgarish audit'ga (faqat maydon nomlari), holat o'zgarishi `platform.transition_log` ga yoziladi.
**RLS:** ha (FORCE), `pages` da ham — 4-modulda qo'shildi. Ichidagi hamma narsa ochiq ma'lumot, lekin sayt o'qishi baribir shop kontekstini o'rnatadi; RLS panel boshqa shop sozlamasiga tegolmasligini bazaning o'zida kafolatlaydi.

**Misol:** Ali logotip yukladi, rang `#2563EB`, shior "Kompyuter qismlari — rasmiy kafolat bilan", telefon +998 71 200 00 00, Telegram `techpc_uz`. "Saytni ochish" → `LIVE`. TechPC faol, shuning uchun `techpc.platforma.uz` darhol ochiladi.

---

## 2. `pages` — ma'lumot sahifalari

**Nima uchun kerak:** xaridor sotib olishdan oldin "qanday to'layman?", "yetkazib berasizmi?", "kafolat qanday?" deb so'raydi. Stage 1 da to'lov tizimdan tashqarida (DEC-100) va yetkazishni shop o'zi tashkil qiladi (DEC-113). Shuning uchun har shop bu shartlarni o'zi yozib qo'yishi kerak. Sahifalar saytning pastki menyusida chiqadi.

- **`kind`** — sahifa turi. Uchta tayyor tur (DEC-135):
  - `ABOUT` — "Biz haqimizda";
  - `DELIVERY_PAYMENT` — "Yetkazish va to'lov";
  - `WARRANTY_RETURNS` — "Kafolat va qaytarish".
- **`title`** — sarlavha. Standart holatda turning nomi, Ali o'zgartirishi mumkin.
- **`body_md`** — matn. Oddiy formatlash mumkin: sarlavha, ro'yxat, qalin yozuv, havola. HTML qabul qilinmaydi va ko'rsatishda tozalanadi: saytga zararli kod qo'yib bo'lmaydi.
- **`is_published`** — chiqarilganmi. Pastki menyuda faqat chiqarilgan sahifalar ko'rinadi.
- **`updated_by`**, **`version`** — kim o'zgartirdi, bir vaqtda saqlash himoyasi.

**Unikal:** har turdan bitta sahifa — `(shop_id, kind)`.
**Til:** matn shop yozgan tilda, xuddi mahsulot tavsifi kabi (DEC-135).
**Maxfiylik siyosati bu yerda emas.** U platforma shablonidan olinadi, shop rekvizitlari (yuridik nomi, STIR, manzili) unga avtomatik qo'yiladi (engineering/26 §8). Sabab: matnni huquqshunos tekshiradi, har shop o'zicha yozsa, xato qilishi mumkin. Shablon kodda versiyalanadi. Buyurtma formasidagi rozilik shu versiya bilan `commerce.orders.consent_version` ga yoziladi.
**Bog'lanish:** `shop_id` → `sites`: sahifa saytsiz bo'lmaydi.

**Misol:** Ali "Yetkazish va to'lov" ga yozdi: "Toshkent bo'ylab yetkazamiz, narxi operator bilan kelishiladi. To'lov — naqd yoki karta orqali, mahsulotni olganda." Chiqardi → saytning pastki menyusida "Yetkazish va to'lov" paydo bo'ldi.

---

## 3. `public_products` — saytdagi katalog nusxasi (keyin — DEC-135)

**Nima uchun kerak bo'lishi mumkin:** Instagram'dagi bitta postdan keyin yuzlab odam bir vaqtda katalogni ochadi (engineering/08). Har ochilishda katalog, narx va qoldiq jadvallarini birlashtirib o'qish o'rniga, saytga kerakli hamma narsani bitta tayyor jadvalda ushlash mumkin.

Har qator — saytda ko'rinadigan bitta variant (SKU):
- **`product_id`**, **`category_code`**, **`brand`**, **`title`**, **`variant_name`**, **`condition`** — kartochka uchun.
- **`price_uzs_minor`** — xaridor ko'radigan narx, doim so'mda (DEC-121). Dollar narxi shop kursi bilan o'giriladi, yaxlitlanmaydi (DEC-133).
- **`stock_status`** — "bor", "kam qoldi" yoki "yo'q". **`available_qty`** — aniq son, faqat shop "aniq sonni ko'rsat" sozlamasini tanlagan bo'lsa (DEC-128), aks holda bo'sh.
- **`branch_availability`** — filial bo'yicha holat (DEC-135).
- **`media`**, **`warranty_months`**, **`published_at`** — rasmlar, kafolat, "yangilar" saralashi.
- **`product_version`**, **`price_version_id`**, **`exchange_rate_id`**, **`stock_version`** — o'zgarishlar xabari tartibsiz kelsa, eskisi yangisini bosib ketmasligi uchun.

**Qanday yangilanadi:** katalog va ombordagi har o'zgarish xabar (event) yuboradi, sayt shu xabar bo'yicha nusxani yangilaydi (engineering/05 §8.8). Buning uchun **fon ishlari** kerak (outbox, S0-06). Reja bo'yicha ular 5-modulda quriladi (engineering/27). Shu sababli bu jadval 4-modulda yaratilmaydi (DEC-135).
**Hech qachon nima uchun ishlatilmaydi:** buyurtma tasdiqlashda. U yerda `commerce` narx va qoldiqni o'z jadvallaridan, qulf ostida qayta tekshiradi.

---

## 4. `site_domains` — shopning o'z domeni (keyin — DEC-135)

**Nima uchun kerak bo'lishi mumkin:** TechPC'ning o'z `techpc.uz` domeni bor va sayt shu manzilda ochilishini xohlaydi (BL-025).

- **`hostname`** — `techpc.uz`. Butun platformada yagona: ikki shop bir domenni ola olmaydi.
- **`status`** — `PENDING` (DNS yozuvi kutilmoqda) → `VERIFIED` (tasdiqlandi) yoki `FAILED` (o'tmadi, sababi `failure_reason` da); `REMOVED` — olib tashlangan.
- **`verification_token`** — Ali DNS sozlamasiga qo'yadigan tekshiruv yozuvi. Bu sir emas (DNS'da hammaga ko'rinadi), shuning uchun xesh qilinmaydi.
- **`is_primary`** — asosiy manzil. Qolganlari, `techpc.platforma.uz` ham, shu yerga yo'naltiriladi. Shopda bitta asosiy domen.

**Qoida:** tasdiqlanmaguncha sayt platforma manzilida ishlaydi (BL-025). Sayt faqat tasdiqlangan domenlar ro'yxati orqali topiladi (engineering/21 §6).
**Qo'shimcha ish:** har domenga SSL sertifikatini avtomatik olish va Nginx sozlamasi (engineering/22 da hali yo'q).

---

## 5. Sayt ma'lumotni qanday xavfsiz o'qiydi

Xaridor tizimga kirmaydi, so'rov anonim. Shuning uchun himoya qatlamlari:

1. **Shop manzildan aniqlanadi.** `techpc.platforma.uz` → `slug = techpc` → `platform.shops`. Brauzer yuborgan `Host` ga ko'r-ko'rona ishonilmaydi: faqat platforma domeni va (keyin) tasdiqlangan domenlar (engineering/21 §6). `slug → shop` bog'lanishi 10 daqiqa keshda.
2. **Holat tekshiriladi.** Shop faol va sayt ochiq bo'lmasa — §0 dagi sahifalar.
3. **Faqat o'qish.** Sayt so'rovi `READ ONLY` tranzaksiyada ishlaydi va `app.shop_id` shu shopga o'rnatiladi. Shuning uchun RLS yoqilgan jadvallar (narx, kurs, qoldiq) xuddi paneldagidek faqat shu shop qatorlarini beradi.
4. **Faqat ochiq maydonlar.** Sayt kodi katalog va ombor jadvallariga o'zi tegmaydi. U `CatalogQueryPort` va `CommerceQueryPort` dan tayyor "ommaviy" javob oladi: faqat chiqarilgan mahsulot, faol va narxi bor variant. Tannarx, ichki izoh, xodim va xaridor ma'lumoti bu javobda umuman yo'q. Test buni tekshiradi (TC-SEC-09). Kursi yo'q dollar narxi so'mga o'girilmaydi, shuning uchun bunday mahsulot saytga chiqmaydi (BL-012).
5. **Kesh** (engineering/08 §4), har kalitda shop prefiksi bor, shuning uchun bir shop keshida boshqa shop mahsuloti hech qachon ko'rinmaydi:
   - katalog ro'yxati — 60 soniya;
   - mahsulot sahifasi — 60 soniya, lekin mahsulot holati har safar qayta tekshiriladi: yashirilgan mahsulot havolasi darhol "mavjud emas" deydi (UAT-M07);
   - sayt sozlamalari — 300 soniya, Ali saqlasa darhol tozalanadi.
6. **Narx va qoldiq "taxminiy".** Saytdagi raqam 60 soniyagacha eski bo'lishi mumkin va bu ochiq ko'rsatiladi (BL-026). Buyurtma so'rovida `commerce` hammasini bazadan qayta tekshiradi, operator tasdiqlashda yana bir marta (DEC-134).
7. **So'rovlar chegarasi.** O'qish — bir IP dan daqiqasiga 120 ta. Buyurtma so'rovi — bir IP va telefondan 10 daqiqada 5 ta (engineering/08 §5).
8. **Rasmlar** — ochiq manzil, brauzer va CDN keshlaydi (DEC-133).

**Mahsulot havolasi:** `techpc.platforma.uz/p/{mahsulot id}/{nomi}` — masalan, `/p/01a16e27…/msi-geforce-rtx-4060-ventus-2x`. Mahsulotni **id** topadi, nom faqat chiroy va Google uchun, bazada saqlanmaydi. Ali nomni o'zgartirsa, eski havola ishlashda davom etadi (to'g'ri nomga yo'naltiriladi). AI chatda yuborgan havola ham hech qachon buzilmaydi.

---

## 6. Savatcha va buyurtma so'rovi

**Savatcha bazada saqlanmaydi**, xaridorning brauzerida turadi (commerce.md §12). Ichida faqat "qaysi variant, nechta". Ism va telefon saqlanmaydi.

```
Jasur savatga RTX 4060 soladi               [brauzerda: {sku_id, qty}]
  ──▶ /cart ochiladi                        [narx va mavjudlik serverdan qayta olinadi, brauzerdagiga ishonilmaydi]
  ──▶ ism, telefon, olib ketish (filial) yoki yetkazish (manzil), rozilik belgisi
  ──▶ "Buyurtma berish"                     [POST /storefront/techpc/order-requests, takror himoyasi bilan]
  ──▶ commerce: mahsulot, narx, filial qayta tekshiriladi ──▶ buyurtma "Tasdiq kutilmoqda", operatorga vazifa
  ──▶ Jasur: "Buyurtmangiz qabul qilindi, operator bog'lanadi" + buyurtma holati havolasi
```

- Takror himoyasi: kalit forma ochilganda yaratiladi. Jasur tugmani ikki marta bossa yoki internet uzilib qayta yuborilsa, ikkinchi buyurtma yaratilmaydi (BL-046, `commerce.orders.source_request_id`).
- Yetkazish shopda o'chiq bo'lsa, formada faqat "olib ketish" chiqadi (§8, `delivery_enabled`).
- Olib ketishda faqat ochiq olib ketish joylari tanlanadi (BL-010). Bir buyurtma — bitta filial (DEC-134).
- Tashlab ketilgan savatchalar bazani to'ldirmaydi.

---

## 7. Bu schemaga kirmaganlar va nega

- **Buyurtma so'rovi va buyurtma holati sahifasi** — `commerce.orders` (DEC-115). Holat havolasi — `orders.tracking_token_hash`: bazada havolaning o'zi emas, xeshi.
- **Sayt chati** — `messaging` dagi web chat kanali (5-modul). Chat yoqilgan yoki o'chirilganini kanal holati hal qiladi, sayt sozlamasi emas.
- **Toifalar menyusi** — platforma toifalari (DEC-133). Menyuda faqat chiqarilgan mahsuloti bor toifalar chiqadi, bu har safar hisoblanadi.
- **PC taklifi sahifasi** (`/quote/{kod}`) — `commerce` (S3, 6-modul bilan).
- **Xaridor sessiyasi** — imzoli token, bazada emas.
- **Bannerlar, "tavsiya etilgan" mahsulotlar, sayt statistikasi** — hujjatlarda Stage 1 uchun yo'q. "Saytdan kelgan buyurtmalar soni" `commerce.orders.source = STOREFRONT` dan hisoblanadi.

---

## 8. Boshqa schemalarga takliflar

Bu fayl ularni o'zgartirmaydi; tasdiqlansa, tegishli DBML'ga qo'shiladi.

- **`platform.shop_policies.delivery_enabled`** (boolean). Shop yetkazib beradimi yoki yo'q. Hozir hech qayerda yo'q, lekin buyurtma formasi, `commerce` (so'rovni tekshirish) va AI ("yetkazib berasizmi?") uchun kerak. Shart va narx matni "Yetkazish va to'lov" sahifasida.
- **`platform.file_purpose` ga `SITE_LOGO`** — ochiq fayl, 2 MB gacha, PNG, JPEG, WebP yoki SVG. SVG xavfsiz bo'lishi uchun tozalanadi yoki PNG ga o'giriladi.
- **`catalog.products.title` ga trigram indeks** (pg_trgm) — saytdagi qidiruv uchun. Qidiruv nom, brend va SKU kodi bo'yicha. Filtrlar: toifa, narx oralig'i, brend, holati, "faqat borlari". Saralash: yangilar, arzon, qimmat.
- **Filial manzilini tasdiqlash (BL-009).** `platform.branches` da "tasdiqlangan" belgisi yo'q. Stage 1 da: filialni ega o'zi kiritadi, demak tasdiqlangan. Xaritada nuqta (`latitude`/`longitude`) bo'lmasa, xarita ko'rsatilmaydi.

---

## Bog'lanishlar xaritasi

```
sites ──< pages
  │
  └─< site_domains                (keyin — DEC-135)

public_products                   (keyin — DEC-135; boshqa jadvalga FK yo'q — nusxa)

──<  bir → ko'p (FK, shop_id orqali)
Boshqa schemalar (faqat uuid, FK'siz): platform.shops (slug, holat, rekvizitlar), platform.branches,
platform.shop_policies (stock_display, low_stock_threshold), platform.stored_files (logotip);
catalog.* — CatalogQueryPort orqali; commerce.* — CommerceQueryPort va buyurtma so'rovi API'si orqali
```

---

## engineering/07 §4.7 dan farqlar (taklif)

- **`sites.subdomain` olib tashlandi** — manzil `platform.shops.slug` da (1-modulda bor, unikal, taqiqlangan so'zlar ro'yxati bilan). Ikki joyda saqlansa, farq qilib qolishi mumkin edi.
- **`sites.contacts` (JSONB) → alohida ustunlar:** `contact_phone`, `contact_email`, `telegram_username`, `instagram_username`. Har biri tekshiriladi, ixtiyoriy havola qo'yib bo'lmaydi.
- **`sites.theme` → `theme_mode` + `accent_color`** — M07 dagi "logotip va ranglar" ning aniq shakli.
- **`sites.locales` olib tashlandi** — sayt tugmalari doim 3 tilda, shop matni bitta tilda (DEC-135).
- **`sites.status` qiymatlari aniqlandi:** `DRAFT`, `LIVE`, `PAUSED`. `tagline`, `seo_description`, `published_at`, `status_changed_at`, `updated_by` qo'shildi.
- **`pages`:** `slug` + `locale` → `kind` (uchta tayyor tur, DEC-135); `body` → `body_md` (HTML'siz); `is_published`, `version` qo'shildi.
- **`public_products` keyinga** (DEC-135). Maydonlari aniqlandi:
  - `price_minor` + `currency` → `price_uzs_minor`, chunki xaridorga doim so'm;
  - `branch_availability` qo'shildi (DEC-135);
  - bitta `source_version` → har manba uchun alohida versiya;
  - `product_slug` olib tashlandi (§5, havola id bo'yicha).
- **`site_domains` qo'shildi** (keyin — DEC-135) — BL-025 dagi domen tasdig'i uchun joy.

**Boshqa hujjatlardagi ziddiyatlar va tanlov:**

- **Mahsulot havolasi.** business/06 `/p/{mahsulot}`, engineering/21 `GET …/products/{id}`, engineering/08 kesh kalitida `slug=rtx-4060-msi`. Tanlandi: id + bazada saqlanmaydigan nom (§5). 08 dagi kesh kaliti `product:id=…` bo'ladi.
- **Katalog nusxasi va fon ishlari.** Engineering/07, 10 §4 va 05 §8.8: sayt faqat event'lardan qurilgan nusxani o'qiydi. Engineering/27: event'lar (outbox) 5-modulda, sayt esa 4-modulda. Founder qarori: hozir to'g'ridan o'qiladi, nusxa keyin (DEC-135).
- **App nomi.** DEC-115 da `apps/merchant-storefront`, engineering/21 va 02 da `apps/shop-storefront`. Tanlandi: `shop-storefront` (hujjatlar qoidasi: `shop`, merchant emas).
- **Yetkazishni yoqish/o'chirish** hech qayerda aniqlanmagan, holbuki M07 formasida ikkala yo'l bor. Taklif — §8.

---

## Founder qarorlari — DEC-135 (2026-10-25)

Bulardan oldin hal bo'lganlar: sayt to'lovsiz (DEC-115), saytdan kelgan buyurtmani operator tasdiqlaydi (DEC-100d), qoldiq ko'rinishi shop sozlamasi (DEC-128), narx doim so'mda (DEC-121), maxfiylik siyosati — platforma shabloni (engineering/26 §8).

**1. Sayt katalog va ombordan to'g'ridan o'qiydi.**
Faqat ochiq maydonlar va faqat chiqarilgan mahsulot; ro'yxat 60 soniya keshda. `public_products` nusxa jadvali 4-modulda yaratilmaydi: u fon ishlari bilan (5-modul) yoki yuklama oshganda qo'shiladi, loyihasi tayyor (§3).

**2. Stage 1 da faqat platforma subdomeni** (`techpc.platforma.uz`).
Shopning o'z domeni pilotdan keyin; `site_domains` jadvali hozir yaratilmaydi (§4).

**3. Filial bo'yicha mavjudlik — mahsulot sahifasida.**
Ro'yxatda umumiy holat ("bor" / "kam qoldi"). Mahsulot sahifasida, shopda 2 va undan ko'p olib ketish joyi bo'lsa, filial bo'yicha. Savatchada tanlangan filialda yo'q mahsulot belgilanadi, so'rov baribir qabul qilinadi (operator muqobil taklif qiladi).

**4. Uchta tayyor sahifa:** "Biz haqimizda", "Yetkazish va to'lov", "Kafolat va qaytarish". Ega faqat matnni yozadi, pastki menyu avtomatik.

**5. Shop matnlari bitta tilda** (shior va sahifalar), mahsulot tavsifi kabi. Saytning tugmalari va yozuvlari doim 3 tilda.
