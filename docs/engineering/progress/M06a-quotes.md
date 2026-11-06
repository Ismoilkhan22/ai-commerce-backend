# 6a-qism. Leadlar, PC takliflari va "PC yig'ish" sahifasi — backend

> **Holat:** backend bitdi (2026-10-26), commit qilinmagan — founder ko'rib chiqishi kutilmoqda.
> **Asos:** [db/commerce_quotes.md](../db/commerce_quotes.md) (DEC-142 taklif), [ai/M06-architecture.md](../ai/M06-architecture.md) §3 va §11 (6a), [17](../17-pc-compatibility-engine.md), business/05 FSM-05 va FSM-06.
> **Moslik engine'i** — alohida qism: [M06a-compat-engine.md](M06a-compat-engine.md). Bu qism uni `CatalogQueryPort.check_compatibility` orqali ishlatadi, engine kodiga tegmaydi.

---

## 1. Nima bitdi — qisqacha

Shop endi xaridor bilan PC yig'ma bo'yicha rasmiy narxli **taklif** tuzadi. Taklif tekshiriladi va tasdiqlanadi, keyin xaridorga havola bo'lib boradi. Xaridor havolani ochib "Qabul qilaman" desa, tizimda buyurtma qoralamasi paydo bo'ladi. Har taklif **lead**ga tegishli: "kim qiziqdi, nima bo'ldi" ro'yxati shu.

```
Operator: lead (qo'lda yoki suhbatdan) ──▶ taklif qoralamasi (qismlar; narx katalogdan, moslik jonli)
          ──▶ "Tekshiruvga" ──▶ narx yangilanib muzlaydi, moslik muzlaydi (SUBMIT)
              ├─ RISKY_ONLY + PASS + chegirmasiz ──▶ Tasdiqlandi (avtomatik)
              └─ aks holda ──▶ Tekshiruvda ──▶ menejer/ega tasdiqlaydi (o'zi tuzganini emas) yoki qaytaradi
          ──▶ "Yuborish" ──▶ havola /q/{token} (bazada faqat xeshi), muddat (quote_ttl_hours), lead "Taklif berildi"
Xaridor: havola ──▶ "Qabul qilaman" ──▶ narx va moslik qayta tekshiriladi
          ├─ o'zgargan ──▶ QUOTE_CHANGED — operator yangi versiya yuboradi
          └─ o'zgarmagan ──▶ DRAFT buyurtma (manba QUOTE, chegirma tasdiqlangan holda) + buyurtma holati havolasi
Buyurtma topshirildi ──▶ lead "Yutildi" (event orqali)
Panel: "PC yig'ish" ──▶ yig'mani tekshirish, slot uchun mos va mavjud nomzodlar (hech narsa saqlanmaydi)
```

---

## 2. Rejadagi bandlar

- [x] Jadvallar: `leads`, `lead_counters`, `quotes`, `quote_revisions`, `quote_lines`, `quote_compatibility_snapshots`, `quote_counters`; `orders` ga `QUOTE` manbasi, `lead_id`, taklif va versiya FK'lari. RLS FORCE — besh ma'lumot jadvalida; hisoblagichlarda (`lead_counters`, `quote_counters`) RLS yo'q, `order_counters` kabi. Migratsiya `commerce_0007` dev bazaga qo'llandi.
- [x] Yuborilgan versiya muzlaydi — bazadagi trigger (qatorlar, jami, kurs).
- [x] Lead API: yaratish (qo'lda / suhbatdan), ro'yxat va hisoblagichlar, tahrirlash, aniqlandi, yo'qotildi (sabab bilan), qayta ochish, o'ziga olish, biriktirish, tarix.
- [x] Taklif API: qoralama, qatorlar, tekshiruvga, tasdiq, qaytarish, yuborish (havola), xodim belgilagan qabul / rad, yangi versiya, bekor qilish, eski versiyani ko'rish, tarix.
- [x] Moslik snapshot'lari: SUBMIT, APPROVAL, ACCEPT bosqichlarida (har biri bir marta).
- [x] Xaridor havolasi: ko'rish, qabul, rad (sayt surface, anonim).
- [x] "PC yig'ish" sahifasi: tekshirish va nomzodlar.
- [x] Rejali ishlar: taklif muddati (`quote_expiry`, har 15 daq), 30 kun jim lead (`lead_followup`, har kuni 09:00 — vazifa).
- [x] Event'lar (`commerce.lead.*`, `commerce.quote.*`) — PII'siz; realtime signal `lead.changed`, `quote.changed`; vazifalar `QUOTE_APPROVAL`, `LEAD_FOLLOWUP`.
- [x] Dev seed: NoutbukUz'da 3 lead, 2 taklif (bittasi yuborilgan, bittasi qabul qilingan → buyurtma qoralamasi).
- **Ataylab keyinga:**
  - havolani suhbatga avtomatik yuborish — hozir operator `public_url` ni inbox orqali yuboradi (token xabar navbatiga yozilmasligi uchun);
  - `viewed_at` (xaridor havolani qachon ochgani) — GET so'rovda yozuv bo'lmasin deb qilinmadi;
  - AI tool'lari (`capture_lead`, `prepare_quote_draft`) — 6b; jadval va servislar `ai_request_id` bilan tayyor.

---

## 3. Fayllar xaritasi

```
app/domains/commerce/quotes/
├── models/orm.py          jadvallar (commerce_quotes.dbml) va holatlar ro'yxati
├── state_machine.py       FSM-05 (lead) va FSM-06 (taklif) strelkalari
├── schemas.py             API kontrakti: lead, taklif, versiya, PC yig'ish, sayt havolasi
├── common.py              raqamlar, havola tokeni, qator roli, narx nusxasi, moslik natijasini saqlash/ko'rsatish
├── services/
│   ├── lead_service.py    leadlar: ko'rish doirasi, yaratish, o'tishlar, avtomatik QUOTED/WON
│   ├── quote_service.py   takliflar: qoralama, tekshiruv, tasdiq, yuborish, qabul → buyurtma, muddat
│   ├── public_service.py  xaridor havolasi: topish (xesh), ko'rish (PII'siz), qabul, rad
│   └── build_service.py   "PC yig'ish": tekshirish va nomzodlar
├── api/routes.py          panel: /shop/leads, /shop/quotes, /shop/pc-builds
├── api/public_routes.py   sayt: /storefront/{slug}/quotes/{token}
└── jobs.py                quote_expiry, lead_followup va lead WON tinglovchisi
app/db/migrations/commerce/versions/commerce_0007_leads_quotes.py
app/db/seed/quotes_seed.py
tests/integration/test_quotes.py
```

O'zgargan fayllar: `commerce/{permissions, providers, domain_manifest}.py`, `orders/models/orm.py`, `orders/schemas.py` (QUOTE manbasi), `inventory/{schemas, services/stock_service}.py` (SKU tanlash qatorida PC roli), `shared/contracts/catalog.py` va `catalog/query_port.py` (`sku_spec_categories`, `candidate_sku_ids`), `shared/errors` (`QUOTE_CHANGED`), `platform/notifications` (vazifa turlari, havola yo'nalishlari), `platform/realtime/subscribers.py`, `main.py`, `db/models.py`, `db/seed/dev_seed.py`, `tests/architecture/fsm_spec.yaml`.

---

## 4. Qaysi faylda nima bor

### 4.1 `quote_service.py`
- **`create`** — lead berilmasa avtomatik ochadi (suhbatdan bo'lsa — o'sha suhbatning ochiq leadi). Raqam `T-n` alohida hisoblagichdan.
- **`_set_lines`** — qatorlar to'liq almashtiriladi. Narx, kurs, kafolat — katalogdan nusxa (`apply_line_snapshot`). Chegirmani faqat xodim qo'yadi (AI — 403). Rol — toifaning PC roli (`sku_spec_categories`).
- **`submit`** — narxni joriyga yangilaydi va muzlatadi, moslikni tekshiradi (BLOCK → 422 `RULE_BLOCK`), `spec_id/spec_version` ni qatorga yozadi, SUBMIT snapshot. Keyin `RISKY_ONLY` shartlari bajarilsa — avto-tasdiq, aks holda REVIEW va `QUOTE_APPROVAL` vazifasi.
- **`approve`** — o'zi tuzganini tasdiqlamaydi (DEC-109), chegirma tasdiqlovchi limiti ichida (DEC-110), moslik qayta: BLOCK — rad, REVIEW_REQUIRED — `note` majburiy (17 §2). APPROVAL snapshot.
- **`send`** — to'xtatilgan shop yubormaydi; token yaratiladi, bazada xeshi, `expires_at = now + quote_ttl_hours`. Lead → QUOTED. Takroriy yuborish (`reissue_link`) — yangi havola.
- **`accept_core`** — muddat, sotuv darvozasi, har qator narxi va mavjudligi, moslik (yomonlashsa yoki BLOCK) — o'zgargan bo'lsa `QUOTE_CHANGED`. Aks holda ACCEPT snapshot va `_order_from_quote`: buyurtma qatorlari taklifdan nusxa, chegirma taklif tasdiqlovchisi nomidan tasdiqlangan.
- **`revise`** — yangi versiya (qatorlar nusxasi), eski havola bekor.
- **`check`** — protsessor yoki ona plata bo'lsa to'liq yig'ma qoidalari, aks holda faqat qismlar (noutbuk, monitor taklifida "yetishmayapti" xatosi chiqmasin).
- **`detail`** — qoralamada jonli moslik, keyin oxirgi snapshot; `price_changed` (tasdiqlangan/yuborilgan narx katalogdan farq qilsa), `approver_discount_limit_pct`, `allowed_actions`.

### 4.2 `lead_service.py`
- Ko'rish doirasi: ega/menejer — hammasi; operator — o'ziga biriktirilgan va biriktirilmaganlari (`ensure_lead_visible` — aks holda 403 `other_operator`).
- Telefon faqat `consent_contact` bilan, shifrlangan, HMAC bilan (shop ichida dublikat qidirish); javobda niqoblangan.
- Bitta suhbatda bitta ochiq lead — unikal indeks; parallel ikkinchi so'rov mavjudini qaytaradi.
- `mark_quoted` (taklif yuborilganda) va `mark_won` (buyurtma topshirilganda, `SYSTEM` aktor bilan).

### 4.3 `public_service.py`
- Token formati tekshiriladi, xesh solishtiriladi (`compare_digest`), boshqa shop — 404.
- Ko'rinishda ism, telefon, xodim va spec ID yo'q. Muddati o'tgan, lekin hali rejali ish ulgurmagan taklif — "EXPIRED" ko'rinadi.
- Takroriy qabul — o'sha buyurtma, yangi buyurtma holati havolasi (eskisi bekor). Xatoda ichki ID olib tashlanadi.

### 4.4 `build_service.py`
- `check` — moslik, narx, mavjudlik (filial berilsa — shu filialda).
- `candidates` — shu roldagi 40 tagacha sotiladigan SKU, har biri joriy yig'ma bilan tekshiriladi, tartib: mos → mavjud → arzon.

---

## 5. Testlar

`tests/integration/test_quotes.py` — 8 ta katta stsenariy (haqiqiy PostgreSQL, HTTP):
- RISKY_ONLY: PASS taklif avto-tasdiq → yuborish → havola (PII yo'q, token bazada emas) → qabul, takror qabul o'sha buyurtma → DRAFT buyurtma `QUOTE`, snapshot'lar SUBMIT va ACCEPT, holat havolasi ishlaydi;
- qo'lda tasdiq: operator tasdiqlay olmaydi, vazifa ochiladi, menejer tasdiqlaydi; o'zi tuzganini — 403; 10% chegirma — menejer limiti yetmaydi, ega tasdiqlaydi; REVIEW_REQUIRED — dalilsiz 422; BLOCK — tekshiruvga o'tmaydi; qaytarish → 2-versiya; eski versiyani ko'rish;
- qabulda narx o'zgargan → `QUOTE_CHANGED` (saytda `sku_id` yo'q), yangi versiya → eski havola 404;
- havola xavfsizligi: boshqa shop sayti, qisqa/soxta token — 404; rad etilgandan keyin qabul — 409;
- leadlar: rozilik, niqob, shifrlash, event'da PII yo'q, navbat va `take`, hisoblagichlar, ko'rish doirasi, omborchi — 403, boshqa shop — 404, yo'qotildi/qayta ochish va tarix, RLS;
- yuborilgan versiya bazada o'zgarmaydi (trigger);
- taklif buyurtmasi topshirildi → event → lead WON;
- "PC yig'ish": tekshirish, nomzodlar (mos birinchi), PC bo'lmagan rol — 422, omborchi — 403.

---

## 6. Founder ko'rib chiqishi uchun qarorlar

- **Havolani suhbatga yuborish.** Tanlov: tizim havolani o'zi yozmaydi — `send` javobida `public_url`, operator uni inbox orqali yuboradi. Nega: token xabar navbati va outbox'ga yozilmasin. Muqobil: send paytida xabarni avtomatik navbatga qo'yish (token `messaging.messages` da saqlanadi).
- **Qabulda o'zgarish.** Tanlov: narx yoki moslik o'zgargan bo'lsa qabul to'xtaydi (`QUOTE_CHANGED`), operator yangi versiya yuboradi — xaridor yangi havolada qayta qabul qiladi. Muqobil: havolaning o'zida yangi summani ko'rsatib qayta rozilik so'rash (bitta havola).
- **Tasdiq paytida moslik.** Tanlov: har tasdiqda APPROVAL snapshot yoziladi (o'zgarmagan bo'lsa ham). Muqobil: faqat ruleset yoki spec o'zgargan bo'lsa.
- **REVIEW_REQUIRED tasdig'i.** Engine `can_publish_quote = false` beradi, lekin 17 §2 bo'yicha menejer/ega dalil bilan tasdiqlaydi — shunday qilindi; BLOCK hech qachon.
- **To'liq yig'ma qoidalari** faqat protsessor yoki ona plata bor taklifda.
- **Qabuldan keyingi buyurtma**: olib ketish, filial tanlanmagan; xaridor ismi va (rozilik bo'lsa) telefoni leaddan; mas'ul — lead egasi. Operator filialni tanlab, odatdagidek tasdiqlaydi.
- **`RISKY_ONLY` dagi "summa chegarasi"** (DEC-102) — shop sozlamasida yo'q, hozir chegarasiz. Muqobil: `shop_policies.quote_auto_approve_max_minor`.
- **Lead faolligi** — yangi ustun `leads.last_activity_at` (dbml'da yo'q): 30 kunlik vazifa shu bo'yicha.
- **`viewed_at`** qilinmadi (GET da yozuv yo'q). Muqobil: alohida "ko'rildi" POST yoki asinxron yozuv.
- **Ruxsat kodlari** engineering/10 dagidek: `commerce.lead.view|edit|assign`, `commerce.quote.view|draft|approve|send`. Operator: lead va taklif tuzadi, tasdiqlangan taklifni yuboradi, tasdiqlamaydi.

---

## 7. Keyingi qismga meros

- 6b AI tool'lari: `LeadService.create(..., source="AI", ai_request_id=...)` va `QuoteService.create` (AI aktor — `AI_AGENT`; chegirma qo'ya olmaydi, SUBMIT dan nariga o'tolmaydi — FSM).
- Frontend: lead kanban (`/shop/leads`, `counts`), taklif muharriri (`allowed_actions` bo'yicha tugmalar), eski versiya (`revisions/{n}`), "PC yig'ish" (`/shop/pc-builds/*`, SKU tanlashda `spec_category`), sayt sahifasi `/q/{token}`.

---

## 8. Frontend (2026-10-26)

Shop panelida leadlar, takliflar va "PC yig'ish" sahifasi, saytda esa xaridor havolasi `/q/{token}` qurildi. Hamma chaqiruv generatsiya qilingan turlar bilan (`pnpm api:generate`), qo'lda yozilgan yo'l qolmadi.

```
Operator: "PC yig'ish" ──▶ slot tanlaydi (mos va mavjud nomzodlar) ──▶ moslik jonli ──▶ "Taklif yaratish"
          ──▶ taklif sahifasi: qatorlar, chegirma, saqlash ──▶ "Tekshiruvga yuborish"
Menejer:  taklif ──▶ "Tasdiqlash" (moslik "tekshirish kerak" bo'lsa — dalil izohi majburiy) yoki "Qaytarish"
Operator: "Xaridorga yuborish" ──▶ havola bir marta ko'rinadi ──▶ nusxalab, inbox orqali yuboradi
Xaridor:  /q/{token} ──▶ "Qabul qilaman" ──▶ buyurtma raqami va holat havolasi
          o'zgargan bo'lsa (QUOTE_CHANGED) ──▶ "taklif o'zgardi — do'kon yangilangan taklif yuboradi"
```

### 8.1 Sahifalar

- **`/[shop]/leads`** — holat tablari (sonlari `leads/counts` dan), "Menga" / "Biriktirilmagan", qidiruv (ism yoki L-raqam), "yana yuklash".
- **`/[shop]/leads/[id]`** — talablar (byudjet, ish turlari, monitor, brend, izoh), takliflar, yutgan buyurtma, tarix (`leads/{id}/history`). Tugmalar faqat `allowed_actions` bo'yicha: aniqlandi, o'zimga olish, biriktirish, yo'qotildi (sabab bilan), qayta ochish, yangi taklif, suhbatni ochish.
- **`/[shop]/quotes`** — ro'yxat: holat, moslik belgisi, jami, kim tuzgani.
- **`/[shop]/quotes/[id]`** — taklif muharriri:
  - qatorlar: SKU qidiruvi, soni, chegirma, olib tashlash, saqlash (If-Match); rolni server SKU toifasidan qo'yadi;
  - o'ngda moslik paneli: qoralamada jonli (`pc-builds/check`), keyin muzlagan natija;
  - amallar `allowed_actions` bo'yicha: tekshiruvga yuborish (BLOCK yoki saqlanmagan o'zgarish bo'lsa o'chiq), tasdiqlash, qaytarish, yuborish, "xaridor qabul qildi / rad etdi" (xodim belgisi), yangi versiya, bekor qilish;
  - `price_changed` — "katalog narxi o'zgargan, yangi versiya oching" (yuborish o'chiq);
  - versiyalar: eskisini ochish (`revisions/{n}`), faqat o'qish.
- **`/[shop]/build`** — 8 ta slot va qo'shimcha mahsulotlar, filial bo'yicha mavjudlik, jonli moslik, jami, yetishmayotgan majburiy qismlar, "Taklif yaratish" (`?lead=`, `?conversation=`). Nomzodlar — `pc-builds/candidates`; qo'shimcha qidiruvda PC qismi tanlansa (`spec_category`) — o'z slotiga tushadi. Telefonda nomzod oynasi butun ekran.
- **Inbox** — suhbat tafsilotida "Yangi taklif" (yig'ish sahifasi suhbat bilan ochiladi).
- **Sayt `/q/{token}`** — qismlar, jami, moslik xulosasi (xaridorga ichki "ma'lumot yetishmaydi" ko'rsatilmaydi), muddat; qabul (tasdiq oynasi, `Idempotency-Key`), rad (sabab bilan); holatlar: qabul qilingan, muddati o'tgan, rad etilgan, bekor qilingan, yangilangan, havola noto'g'ri. `noindex`, `Referrer-Policy: no-referrer`.

### 8.2 Fayllar xaritasi

```
apps/shop-dashboard/src/
├── lib/quotes.ts                       API chaqiruvlari (tiplangan), moslik natijasini bir shaklga keltirish, kesh kalitlari
├── components/quotes/
│   ├── common.tsx                      holat va moslik belgilari, moslik paneli, sotuv tablari
│   ├── lead-dialogs.tsx                leadni biriktirish, yo'qotildi deb belgilash
│   ├── quote-lines.tsx                 taklif ish maydoni (qatorlar + moslik), jonli moslik hook'i
│   ├── quote-actions.tsx               taklif amallari, havola (bir marta)
│   └── candidate-picker.tsx            slot uchun nomzodlar (telefonda butun ekran)
└── app/[shop]/{leads, leads/[id], quotes, quotes/[id], build}/page.tsx
apps/shop-storefront/src/
├── lib/quote.ts                        turlar, xaridorga ko'rinadigan moslik izohlari
├── components/quote-accept.tsx         qabul / rad
└── app/[site]/q/[token]/page.tsx       xaridor sahifasi
e2e/quotes.spec.ts                      2 ta stsenariy
```

O'zgargan: `lib/nav.ts` (Leadlar), `components/commerce/sku-picker.tsx` (`spec_category`), `components/inbox/conversation-details.tsx`, `shop-storefront/next.config.ts` (`/q/` uchun `no-referrer`), `packages/i18n` (uz/ru/en: leadlar, takliflar, moslik, yig'ish, xaridor sahifasi, xato kodlari).

### 8.3 Qarorlar

- **Havola faqat bir marta.** `send` javobidagi `public_url` sahifada nusxa olish maydoni bilan ko'rinadi; sahifa yangilansa yo'qoladi (bazada xesh). Kerak bo'lsa — yangi versiya va qayta yuborish.
- **Qoida matnlari backenddan** (`explanation`, `hint_text`); frontend faqat qaror va og'irlik nomlarini tarjima qiladi. `MISSING_ATTRIBUTE` neytral ko'rinadi: "ma'lumot yetarli emas — tekshiruv kerak".
- **Yig'ma saqlanmaydi** (DEC-144): "Taklif yaratish" darhol qoralama ochadi.
- **Taxminiy narx** frontendda, yakuniysini server qo'yadi.
- **Taklif muddati matni** — standart 24 soat (DEC-103); aniq vaqt yuborilgandan keyin `expires_at` dan.

### 8.4 Tekshiruv

- `pnpm check` toza; production build'lar o'tadi.
- E2E `quotes.spec.ts`:
  1. Yig'ish: soketi mos kelmaydigan ona plata → BLOCK (`CPU_MB_SOCKET`) → almashtiriladi → taklif → tekshiruvga (ikki marta bosish) → operator tasdiqlay olmaydi → menejer izoh bilan tasdiqlaydi → yuborish, havola → xaridor qabul qiladi (ikki marta bosish) → buyurtma raqami va holat sahifasi → panelda ACCEPTED, leadda taklif, buyurtma "Manba: PC taklifi".
  2. Telefonda: xaridor sahifasi yonga surilmaydi; yangi versiyadan keyin eski havola "noto'g'ri" sahifasini ko'rsatadi; soxta token ham; yig'ish sahifasi, nomzod oynasi butun ekranda, taklif va leadlar sahifalari 390px da.

---

## 9. QA tekshiruvi va tuzatishlar (2026-10-26)

Mustaqil QA (faqat API va SQL) 6a ni tekshirdi: 2 ta jiddiy (High), 4 ta o'rtacha, 9 ta kichik, 4 ta kuzatuv. Hammasi tuzatildi, har biriga test yozildi (`tests/integration/test_quotes_qa_fixes.py` — 10 ta; engine — `tests/unit/test_compat_engine.py` ga 4 ta). Yangi migratsiya: `commerce_0008_quote_revision_editors`.

### 9.1 Jiddiy

- **F1 — o'zi tuzganini tasdiqlash (DEC-109).** Avval faqat versiya muallifi solishtirilardi; qaytarish yoki qayta ishlashdan keyin taklif muallifi tasdiqlay olardi. Endi tasdiqlay olmaydiganlar: taklifni tuzgan (`quotes.created_by`), joriy versiya qatorlarini oxirgi tahrirlagan (`quote_revisions.edited_by`, yangi) va tekshiruvga yuborgan (`submitted_by`, yangi). Menejer operatorning qoralamasini tahrirlab, o'zi tasdiqlay olmaydi. Versiyani qaytargan menejer qatorlarga tegmagan bo'lsa — tasdiqlay oladi. `allowed_actions` da APPROVE ham shu qoida bilan.
- **F2 — bog'lanmagan qism ma'lum BLOCK'ni yashirardi.** Engine endi qaror qoidalarini (BLOCK/REVIEW) bog'langan qismlarda baribir ishlatadi, noma'lum qism `UNLINKED_PART` (REVIEW) bo'ladi. Quvvat qoidasi ham bog'langan qismlar bo'yicha pastki chegarani tekshiradi. Qoidalar to'plami `pc-2026-10-v2` (M06a-compat-engine §9).

### 9.2 O'rtacha

- **F3 — til.** Moslik izohi interfeys tilida: panel har so'rovga `Accept-Language` qo'yadi, backend shu tilda yasaydi (`get_display_locale`). Profil tili (11 §8.2) bot va xabarnoma matnlari uchun ustun qoladi. Snapshot'larda matn emas — `message_key` + faktlar saqlanadi, o'qishda xodim yoki xaridor tilida qayta yasaladi (`app/shared/compat_text.py`). Eski snapshot'lar (matn saqlangan) ham ochiladi.
- **F4 — boshqa operatorning leadi suhbat orqali.** `POST /leads` va `POST /quotes` mavjud ochiq leadni qaytarganda ko'rinish tekshiriladi: begona operatorning leadi — 403 (`other_operator`), ma'lumot qaytmaydi.
- **F5 — parallel yaratish 500 berardi.** Lead savepoint ichida qo'shiladi: unikal indeks to'qnashuvi faqat savepoint'ni bekor qiladi, ikkinchi so'rov mavjud leadni oladi. 6 ta parallel lead va 4 ta parallel taklif — 500 yo'q.
- **F6 — "PC yig'ish" nomzodlari.** Avval nomi bo'yicha birinchi 40 ta olinardi. Endi 1000 tagacha olinadi, engine'siz saralanadi (joriy yig'maning soket, xotira turi, form-faktor, korpus o'lchami bo'yicha atributlar + omborda borligi + narx), keyin eng yaxshi 40 tasi engine bilan tekshiriladi. 42 ta "Aaa…" aldovchi nomzod bilan test.

### 9.3 Kichik

- **F7** — takroriy "yuborish" (Idempotency-Key) ham huquqni tekshiradi: boshqa xodim o'sha kalit bilan yangi havola ololmaydi.
- **F8** — `RULE_BLOCK` tafsiloti 11 §6 shaklida: `{ruleset_version, decision, findings:[{rule_id, severity}]}`.
- **F9** — `NEW → QUOTED` va `NEW → LOST` amaliy o'tishlar sifatida qoldi va hujjatlandi (§9.4 — founder tasdig'i kerak). `NEW → WON` — faqat tizim.
- **F10** — yopilgan (WON/LOST) leadni tahrirlash va biriktirish — 409.
- **F11** — `conversation_id` shu shop suhbati ekani tekshiriladi (messaging `ConversationLookupPort`) — begona yoki yo'q suhbat 422.
- **F12** — lead yo'qotilganda ochiq takliflari (DRAFT, REVIEW, APPROVED, SENT) bekor bo'ladi (yangi buyruq `LEAD_LOST`), havola o'chadi, tasdiq vazifalari yopiladi; audit va event yoziladi.
- **F13** — qabulda tasdiqlovchi ko'rmagan yangi BLOCK/REVIEW qoidasi (APPROVAL, avto-tasdiqda SUBMIT snapshot'ida yo'q) ham o'zgarish: `QUOTE_CHANGED`, tafsilotda `new_rule_ids`.
- **F14** — qoldiq taklifni bloklamaydi (DEC-100b — operator tasdiqlagunga qadar band yo'q). Xodim uchun `QuoteOut.availability`: har qator — omborda nechta va yetadimi; muharrirda "Omborda" kartasi.
- **F15** — muddati o'tgan (rejali ish hali ulgurmagan) taklifni xaridor ham, xodim ham rad etolmaydi — `QUOTE_EXPIRED`.
- **F16** — xaridor sahifasida ichki so'zlar yo'q: `PublicCompatibilityOut` — qaror, `expert_checked` + qisqa izoh ("do'kon mutaxassisi tekshirgan"), faqat WARNING/INFO maslahatlar. Tasdiqlovchining dalil izohi ichki qoladi.
- **F17** — lead suhbatidagi kiruvchi/chiquvchi xabar `leads.last_activity_at` ni yangilaydi (`commerce.lead_activity` tinglovchisi `messaging.message.*` ga), faol suhbatda "yopilsinmi?" vazifasi chiqmaydi.
- **F18** — hujjat aniqlandi: hisoblagichlarda RLS yo'q.
- **F19** — `PSU_GPU_CONNECTORS` adapter topilmasiga maslahat (`PSU_NATIVE_16PIN`); sayt `/q/{noto'g'ri}` — haqiqiy 404; `pc-builds/check` va `candidates` da `branch_id` shu shop va xodim doirasidagi filial bo'lishi shart (422/403).
- **Frontend so'ragani:** lead ro'yxatida manba filtri (`?source=AI|STAFF`), taklif ro'yxatida va lead'da xaridor ismi, lead'ning buyurtmalar ro'yxati (`LeadOut.orders`), `RevisionSummary.created_at`.

### 9.4 Founder ko'rib chiqishi uchun qarorlar (QA'dan keyin)

- **FSM-05 amaliy o'tishlar** — `NEW → QUOTED` (aniqlashsiz birinchi taklif) va `NEW → LOST` (spam). Muqobil: avval "Aniqlandi" majburiy. business/05 ga qo'shish kerak.
- **Qoldiq va taklif** — bloklamaydi, faqat ko'rsatadi. Muqobil: qoldiq yetmasa yuborishni bloklash.
- **Lead yo'qotilsa** — yuborilgan taklif ham bekor (havola o'chadi). Muqobil: yuborilgani muddati tugaguncha qoladi.
- **Moslik matni tili** — interfeys tili (`Accept-Language`), profil tili emas. Muqobil: profil tilini panel tanlagichi bilan sinxron qilish.
- **Qaytargan menejer tasdiqlay oladi**, agar qatorlarga tegmagan bo'lsa. Muqobil: qaytargan ham tasdiqlay olmaydi.

### 9.5 SPEC_EDITOR dev ma'lumoti

QA vaqtida demo kutubxona muharriri (+998900000004) o'chiq edi. Audit: 2026-10-26 12:06:58 UTC da platforma admini (+998900000001) "nimadir" sababi bilan o'chirgan (`platform.staff.disabled`) — avtomatik ish emas, panel orqali qo'lda. Qayta yoqish endpointi yo'q, bazaga qo'lda tegilmadi; demo kerak bo'lsa — yangi taklif yoki `make seed` qayta.
