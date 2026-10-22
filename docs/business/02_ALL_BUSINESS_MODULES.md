# 02 — ALL BUSINESS MODULES: 39 MODULNING FUNKSIONAL VA BIZNES SPETSIFIKATSIYASI

**Versiya** v1.0 | **Status** Implementation-oriented business specification (`REVIEW REQUIRED`) | **Sana** 2026-10-21

**Format:** `Mxx` — modul identity. Qoidalar `BL-xxx`, statuslar `05`, UX `06`, UAT `10`. `MUST` — tegishli bosqichda kerakli; `SHOULD` — shart/qiymatga qarab chiqariladi. Bu ishlab turgan kod emas.

## Umumiy modul xulqi (39 tasiga majburiy)

- Har bir read/write tenant principal va filial scope bilan yuradi. Public global API faqat `PublicOffer`dan o‘qiydi.
- Har bir mutation owner/role, state transition, idempotency key va audit talab qiladi (UI human event uchun server generated key ham mumkin).
- API/channel unavailable bo‘lsa vazifa yo‘qolmaydi: qayta urinish, operator task va xatolik sababi ko‘rsatiladi.
- AI maslahat: faqat tool facts va versioned merchant policies. Riskli amal uchun human approval.
- UI majburiy holatlari: empty, loading, success, validation failure, permission denied, conflict/stale, third-party unavailable.
- Veb sahifa va Telegram bot bir xil merchant katalogi, narx va buyurtma servisiga murojaat qiladi.

## Uch bosqichdagi to‘liq modul xaritasi

| Modul | Bosqich | Biznes modul | Critical KPI | Scope |
|---|---|---|---|---|
| `M01` | 1 | Merchant tashkiloti va onboarding | aktivlashgunga qadar vaqt, onboarding completion | MUST |
| `M02` | 1 | Xodimlar, rollar va filial ruxsatlari | permission denied va approval kechikishi | MUST |
| `M03` | 1 | Filiallar va xizmat hududi | filial bo‘yicha pickup so‘rovlar | MUST |
| `M04` | 1 | Katalog, variant va SKU | publishable SKU%, import rejection% | MUST |
| `M05` | 1 | Narx, valuta va chegirmalar | false price incidence, quote acceptance | MUST |
| `M06` | 1 | Ombor, kirim-chiqim va rezerv | oversell=0, inventory discrepancies | MUST |
| `M07` | 1 | Brendlangan mini-sayt va storefront | storefront qualified leads, conversions | MUST |
| `M08` | 1 | PC configurator va compatibility | incompatible quote=0, review_required% | MUST |
| `M09` | 1 | Kanallar va kanal hisoblarini ulash | connected channels, delivery failure rate | MUST |
| `M10` | 1 | Unified Inbox, conversation va human handoff | first response, open backlog, takeover rate | MUST |
| `M11` | 1 | AI Sales Agent va product discovery | grounded-answer rate, escalation rate, cost/lead | MUST |
| `M12` | 1 | Lead, CRM va quotation | qualified lead rate, quote-to-order | MUST |
| `M13` | 1 | Buyurtma va order lifecycle | order accuracy, cancellations | MUST |
| `M14` | 1 | To‘lov va chekni tekshirish | payment mismatch, false paid=0 | MUST |
| `M15` | 1 | Yetkazish va pickup | delivered %, exception age | MUST |
| `M16` | 1 | Sotuvdan keyingi xizmat va kafolat | resolution time, repeat complaints | SHOULD |
| `M17` | 1 | Notifications, automation va merchant tasks | missed SLA tasks, delivery success | MUST |
| `M18` | 1 | Dashboard, hisobot va Voice Business Copilot | metric reconciliation, answer groundedness | MUST |
| `M19` | 1 | Merchant AI controls, billing va platform operations | gross margin/tenant, active merchants | MUST |
| `M20` | 1 | Activity log va biznes audit | unaudited critical mutations=0 | MUST |
| `M21` | 2 | Self-service merchant provisioning | time to live merchant | MUST |
| `M22` | 2 | Integration hub / POS / ERP / marketplaces | sync freshness, data conflicts | MUST |
| `M23` | 2 | Global canonical product registry | precision, false merge rate | MUST |
| `M24` | 2 | Merchant public offers va opt-in | valid public offers, takedown lag | MUST |
| `M25` | 2 | Multi-branch inventory and fulfillment intelligence | transfer delay, pick success | MUST |
| `M26` | 2 | Merchant tenancy at scale va subscription automation | merchant retention, unit cost | MUST |
| `M27` | 2 | Merchant-facing AI policy/knowledge center | verified response coverage | MUST |
| `M28` | 2 | Search index publishing and catalog data quality | index age, withdrawn visibility=0 | MUST |
| `M29` | 2 | Merchant quality, verification and trust data | verification coverage, fraud reports | MUST |
| `M30` | 2 | Partner API va merchant developer access | API errors, key rotation age | MUST |
| `M31` | 3 | Global search and filters | search success, query latency | MUST |
| `M32` | 3 | Cross-store price comparison | valid comparisons, wrong-price reports | MUST |
| `M33` | 3 | Geo search, near-me va maps | map-to-store actions | MUST |
| `M34` | 3 | Global AI Shopping Advisor | grounded ranking %, conversion assist | MUST |
| `M35` | 3 | Merchant discovery and referral tracking | referral-to-response / sale | MUST |
| `M36` | 3 | Buyer account, saved products and alerts | saved-to-return, unsubscribe rate | SHOULD |
| `M37` | 3 | Organic vs sponsored ranking and transparency | buyer trust signals, complaint rate | SHOULD |
| `M38` | 3 | Global content, SEO and shareable landing pages | organic qualified traffic | SHOULD |
| `M39` | 3 | Global Telegram bot and discovery API | bot-to-merchant referrals | SHOULD |

---

## STAGE 1 — Merchant Sales OS — independent merchant sales engine

### M01 — Merchant tashkiloti va onboarding

- **Bosqich/ustuvorlik:** 1 / `MUST` (MUST — bosqich maqsadi uchun; SHOULD — reliz darvozasiga bog‘liq).
- **Nega mavjud:** Bitta do‘kon uchun ishlab ketadigan tenant muhitini ochish.
- **Kim foydalanadi:** Platform Admin, Owner.
- **Biznes maʼlumotlari:** `merchant_id, legal_name, owner_id, default_locale, time_zone, country`. Bular ERD emas, data contractga kiradigan domen tushunchalari.
- **Funksiyalar va qamrov:**
  - **01.** Email/telefon verifikatsiyasi va egani aniqlash
  - **02.** merchant profili: nom, faoliyat, valuta, manzil
  - **03.** onboarding checklist va katalog sifat ko‘rsatkichi
  - **04.** trial/active/suspended/offboarded lifecycle
  - **05.** shaxsiy subdomain band qilish va tekshirish
- **Jarayon/holatlar:** `draft→pending_verification→active→suspended→closed`; tegishli to‘liq FSM: `05_STATE_MACHINES_AND_EXCEPTIONS.md`.
- **Bajarilishi shart bo‘lgan qoidalar:**
- `BL-001`: Bitta tasdiqlangan owner va mustaqil merchant identity yaratiladi
- `BL-002`: Har qanday read/write merchant scope bilan filtrlanadi
- `BL-003`: Minimal identifikatsiya, aloqa va public terms tasdiq bo‘lmaguncha live emas
- `BL-004`: Yangi sotuv va publikatsiya to‘xtaydi, tarixiy buyurtmalar boshqariladi
- **Istisno va recovery (har biri test case):**
- takrorlangan tashkilot
- egalik bahsi
- verify tugallanmagan
- suspensionda eski buyurtmalar
- ma’lumotni eksport qilib chiqish
- **UI sirtlari:**
- Onboarding wizard
- Merchant profile
- Account status and review
- **Hamkor modullar:** `M02`, `M03`, `M07`, `M18`. Bu ro‘yxat logical collaboration, cross-module direct DB access ruxsati emas.
- **O‘lchanadigan natija:** aktivlashgunga qadar vaqt, onboarding completion.
- **Acceptance minimumi:** barcha asosiy amallar role+tenant asosida tekshiriladi; yuqoridagi istisnolar sinovdan o‘tadi; barcha saqlangan o‘zgarishlarda sabab/actor va idempotent yoki kompensatsiya qilinadigan natija bor; UI muvaffaqiyat, empty, loading, error, conflict va permission denial holatlarini ko‘rsatadi.

### M02 — Xodimlar, rollar va filial ruxsatlari

- **Bosqich/ustuvorlik:** 1 / `MUST` (MUST — bosqich maqsadi uchun; SHOULD — reliz darvozasiga bog‘liq).
- **Nega mavjud:** Kim qaysi merchant va filial ma’lumotlarini ko‘rishi/boshqarishini aniq belgilash.
- **Kim foydalanadi:** Owner, Manager, Admin.
- **Biznes maʼlumotlari:** `principal, merchant_id, branch_scope, role, approval_limit`. Bular ERD emas, data contractga kiradigan domen tushunchalari.
- **Funksiyalar va qamrov:**
  - **01.** Invite va accept
  - **02.** role assignment/disable
  - **03.** filialga scope
  - **04.** sezgir operatsiya uchun approval
  - **05.** sessiyalarni bekor qilish
  - **06.** auditda har bir qarorni aktorga bog‘lash
- **Jarayon/holatlar:** `invited→active→disabled; approval: pending→approved/rejected`; tegishli to‘liq FSM: `05_STATE_MACHINES_AND_EXCEPTIONS.md`.
- **Bajarilishi shart bo‘lgan qoidalar:**
- `BL-005`: RBAC + scope (merchant, branch, ownership) tekshiriladi
- `BL-006`: Rol va limitdan oshsa second approval talab
- `BL-007`: Oxirgi ownerni o‘chirish taqiqlanadi
- `BL-008`: AI ham aynan actor permissionlari bilan cheklanadi
- **Istisno va recovery (har biri test case):**
- o‘zini oxirgi ownerlikdan o‘chirish
- ketgan xodim tokeni
- filialdan tashqari so‘rov
- AI orqali rolni aylanib o‘tish
- **UI sirtlari:**
- Team list
- Invite panel
- Role/scope editor
- Approval queue
- **Hamkor modullar:** `M01`, `M17`, `M18`. Bu ro‘yxat logical collaboration, cross-module direct DB access ruxsati emas.
- **O‘lchanadigan natija:** permission denied va approval kechikishi.
- **Acceptance minimumi:** barcha asosiy amallar role+tenant asosida tekshiriladi; yuqoridagi istisnolar sinovdan o‘tadi; barcha saqlangan o‘zgarishlarda sabab/actor va idempotent yoki kompensatsiya qilinadigan natija bor; UI muvaffaqiyat, empty, loading, error, conflict va permission denial holatlarini ko‘rsatadi.

### M03 — Filiallar va xizmat hududi

- **Bosqich/ustuvorlik:** 1 / `MUST` (MUST — bosqich maqsadi uchun; SHOULD — reliz darvozasiga bog‘liq).
- **Nega mavjud:** Do‘konning fizik lokatsiyasini va mavjud xizmat shartlarini yuritish.
- **Kim foydalanadi:** Owner, Manager.
- **Biznes maʼlumotlari:** `branch_id, geo_point, schedule, pickup_policy, delivery_zone`. Bular ERD emas, data contractga kiradigan domen tushunchalari.
- **Funksiyalar va qamrov:**
  - **01.** filial yaratish/archivlash
  - **02.** manzil va koordinatani tasdiqlash
  - **03.** ish vaqti va pickup opsiyasi
  - **04.** filial kesimida ishchi guruh
  - **05.** delivery coverage zone
  - **06.** default fulfillment branch
- **Jarayon/holatlar:** `draft→active→temporarily_closed→archived`; tegishli to‘liq FSM: `05_STATE_MACHINES_AND_EXCEPTIONS.md`.
- **Bajarilishi shart bo‘lgan qoidalar:**
- `BL-009`: Manzil/koordinata merchant tomonidan tasdiqlanadi
- `BL-010`: Pickup va delivery promise filial holatidan kelib chiqadi
- **Istisno va recovery (har biri test case):**
- noto‘g‘ri geolokatsiya
- do‘kon yopiq
- filialda qoldiq yo‘q
- yopilgan filialga bog‘liq active order
- **UI sirtlari:**
- Branch list/map
- Schedule editor
- Service radius
- Pickup rules
- **Hamkor modullar:** `M01`, `M02`, `M06`, `M16`. Bu ro‘yxat logical collaboration, cross-module direct DB access ruxsati emas.
- **O‘lchanadigan natija:** filial bo‘yicha pickup so‘rovlar.
- **Acceptance minimumi:** barcha asosiy amallar role+tenant asosida tekshiriladi; yuqoridagi istisnolar sinovdan o‘tadi; barcha saqlangan o‘zgarishlarda sabab/actor va idempotent yoki kompensatsiya qilinadigan natija bor; UI muvaffaqiyat, empty, loading, error, conflict va permission denial holatlarini ko‘rsatadi.

### M04 — Katalog, variant va SKU

- **Bosqich/ustuvorlik:** 1 / `MUST` (MUST — bosqich maqsadi uchun; SHOULD — reliz darvozasiga bog‘liq).
- **Nega mavjud:** AI ham, sayt ham, operator ham bir xil tekshirilgan mahsulot kartasidan foydalansin.
- **Kim foydalanadi:** Owner, Catalog Manager.
- **Biznes maʼlumotlari:** `product_id, sku, variant_attributes, brand, condition, photos, availability_policy`. Bular ERD emas, data contractga kiradigan domen tushunchalari.
- **Funksiyalar va qamrov:**
  - **01.** mahsulot+variant/SKU
  - **02.** brand/model/spec/serial policy
  - **03.** rasm va tavsif
  - **04.** kategoriya atribut template
  - **05.** qo‘lda qo‘shish va mass edit
  - **06.** publish/unpublish/archive
  - **07.** CSV/XLSX import preview va error report
- **Jarayon/holatlar:** `draft→in_review→published→hidden→archived`; tegishli to‘liq FSM: `05_STATE_MACHINES_AND_EXCEPTIONS.md`.
- **Bajarilishi shart bo‘lgan qoidalar:**
- `BL-011`: Merchant ichida unique SKU, variant va condition mustaqil saqlanadi
- `BL-012`: Majburiy atribut, narx va public kontent tekshiriladi
- `BL-013`: Preview/dry-run va row error; tanlangan yozuvlargina commit
- `BL-014`: Yangi orderga kirmaydi, eski order snapshots saqlanadi
- **Istisno va recovery (har biri test case):**
- dublikat SKU
- import qator xatosi
- atribut to‘liq emas
- boshqa merchantga tegishli media
- import vaqtida narxni buzish
- **UI sirtlari:**
- Products table
- Product editor
- Import preview
- Publish validation
- **Hamkor modullar:** `M05`, `M06`, `M08`, `M10`, `M11`, `M23`. Bu ro‘yxat logical collaboration, cross-module direct DB access ruxsati emas.
- **O‘lchanadigan natija:** publishable SKU%, import rejection%.
- **Acceptance minimumi:** barcha asosiy amallar role+tenant asosida tekshiriladi; yuqoridagi istisnolar sinovdan o‘tadi; barcha saqlangan o‘zgarishlarda sabab/actor va idempotent yoki kompensatsiya qilinadigan natija bor; UI muvaffaqiyat, empty, loading, error, conflict va permission denial holatlarini ko‘rsatadi.

### M05 — Narx, valuta va chegirmalar

- **Bosqich/ustuvorlik:** 1 / `MUST` (MUST — bosqich maqsadi uchun; SHOULD — reliz darvozasiga bog‘liq).
- **Nega mavjud:** Tasdiqlangan sotuv narxini barcha kanallarda yagona manbadan berish.
- **Kim foydalanadi:** Owner, Manager, Sales limited.
- **Biznes maʼlumotlari:** `sku_id, currency, amount_minor, price_version, valid_until`. Bular ERD emas, data contractga kiradigan domen tushunchalari.
- **Funksiyalar va qamrov:**
  - **01.** bazaviy narx va price-list
  - **02.** narx tarixi va effective time
  - **03.** discount policy/limit
  - **04.** manual quote price approval
  - **05.** ko‘p valyuta bo‘lsa exchange rate snapshot
  - **06.** narx muddati va stale flag
- **Jarayon/holatlar:** `draft→active→expired/superseded`; tegishli to‘liq FSM: `05_STATE_MACHINES_AND_EXCEPTIONS.md`.
- **Bajarilishi shart bo‘lgan qoidalar:**
- `BL-015`: Currency+minor units, version, source va valid_until bo‘ladi
- `BL-016`: Yuborilgan quote immutable snapshot; qayta tasdiqda fresh pricing
- `BL-017`: Max discount rule/approver check; margin confidential
- `BL-018`: Kurs manbasi/vaqti snapshot; eskirsa final quote block
- **Istisno va recovery (har biri test case):**
- narx almashgan paytdagi eski quote
- manfiy narx
- chegirma vakolatidan oshishi
- kurs eskirishi
- **UI sirtlari:**
- Pricing table
- Change price dialog
- History
- Price approval
- **Hamkor modullar:** `M04`, `M08`, `M10`, `M12`, `M13`. Bu ro‘yxat logical collaboration, cross-module direct DB access ruxsati emas.
- **O‘lchanadigan natija:** false price incidence, quote acceptance.
- **Acceptance minimumi:** barcha asosiy amallar role+tenant asosida tekshiriladi; yuqoridagi istisnolar sinovdan o‘tadi; barcha saqlangan o‘zgarishlarda sabab/actor va idempotent yoki kompensatsiya qilinadigan natija bor; UI muvaffaqiyat, empty, loading, error, conflict va permission denial holatlarini ko‘rsatadi.

### M06 — Ombor, kirim-chiqim va rezerv

- **Bosqich/ustuvorlik:** 1 / `MUST` (MUST — bosqich maqsadi uchun; SHOULD — reliz darvozasiga bog‘liq).
- **Nega mavjud:** Soxta mavjudlik va ikki marta sotuvni oldini oladigan stock source of truth.
- **Kim foydalanadi:** Warehouse, Manager, Owner.
- **Biznes maʼlumotlari:** `branch_id, sku_id, on_hand, reserved, ledger_reason, expiry`. Bular ERD emas, data contractga kiradigan domen tushunchalari.
- **Funksiyalar va qamrov:**
  - **01.** filial-SKU fizik qoldiq
  - **02.** kirim/chiqim ledger
  - **03.** stock adjustment sababi
  - **04.** qisqa muddatli reservation
  - **05.** reserve expiry/release
  - **06.** damaged/returned stock status
  - **07.** low-stock notification
- **Jarayon/holatlar:** `available / reserved / allocated / sold / returned-damaged`; tegishli to‘liq FSM: `05_STATE_MACHINES_AND_EXCEPTIONS.md`.
- **Bajarilishi shart bo‘lgan qoidalar:**
- `BL-019`: available = on_hand - reserved - allocated, >= 0
- `BL-020`: Atomik check+increment, expiry; unique order/item reference
- `BL-021`: Faqat faol rezerv bo‘shatiladi; qayta release no-op
- `BL-022`: Ledger sababi, actor, timestamp va approval bilan
- `BL-023`: Row lock/CAS va DB constraint bilan oversell oldi olinadi
- **Istisno va recovery (har biri test case):**
- ikki parallel rezerv
- nol stok
- qayta kelgan payment webhook
- expired reservationdan so‘ng payment
- manfiy stock
- drift
- **UI sirtlari:**
- Stock list
- SKU stock ledger
- Adjustment approval
- Reservation monitor
- **Hamkor modullar:** `M03`, `M04`, `M12`, `M13`, `M14`, `M17`. Bu ro‘yxat logical collaboration, cross-module direct DB access ruxsati emas.
- **O‘lchanadigan natija:** oversell=0, inventory discrepancies.
- **Acceptance minimumi:** barcha asosiy amallar role+tenant asosida tekshiriladi; yuqoridagi istisnolar sinovdan o‘tadi; barcha saqlangan o‘zgarishlarda sabab/actor va idempotent yoki kompensatsiya qilinadigan natija bor; UI muvaffaqiyat, empty, loading, error, conflict va permission denial holatlarini ko‘rsatadi.

### M07 — Brendlangan mini-sayt va storefront

- **Bosqich/ustuvorlik:** 1 / `MUST` (MUST — bosqich maqsadi uchun; SHOULD — reliz darvozasiga bog‘liq).
- **Nega mavjud:** Sayti bo‘lmagan merchant katalogidan avtomatik sotuv sahifasi chiqishi.
- **Kim foydalanadi:** Owner, Customer.
- **Biznes maʼlumotlari:** `merchant_slug, theme, public_catalog, channel_entrypoints`. Bular ERD emas, data contractga kiradigan domen tushunchalari.
- **Funksiyalar va qamrov:**
  - **01.** subdomain va brand theme
  - **02.** responsive katalog/qidiruv/filtr
  - **03.** mahsulot detail va availability
  - **04.** savatcha yoki quote request
  - **05.** contact/pickup/delivery
  - **06.** SEO-friendly metadata va sitemap
  - **07.** privacy/contact policies
- **Jarayon/holatlar:** `preview→published→maintenance→disabled`; tegishli to‘liq FSM: `05_STATE_MACHINES_AND_EXCEPTIONS.md`.
- **Bajarilishi shart bo‘lgan qoidalar:**
- `BL-024`: Faqat shu merchantning visible mahsulotlari chiqadi
- `BL-025`: Unique slug; domain verification; tls; revocation
- `BL-026`: Display label va checkoutda fresh check
- **Istisno va recovery (har biri test case):**
- subdomain conflict
- unpublished product havolasi
- stok cache eskirgan
- merchant suspended
- sayt kontentini yashirish
- **UI sirtlari:**
- Storefront builder
- Website preview
- Public catalog
- Product detail
- Cart/request
- **Hamkor modullar:** `M01`, `M04`, `M05`, `M06`, `M12`, `M16`. Bu ro‘yxat logical collaboration, cross-module direct DB access ruxsati emas.
- **O‘lchanadigan natija:** storefront qualified leads, conversions.
- **Acceptance minimumi:** barcha asosiy amallar role+tenant asosida tekshiriladi; yuqoridagi istisnolar sinovdan o‘tadi; barcha saqlangan o‘zgarishlarda sabab/actor va idempotent yoki kompensatsiya qilinadigan natija bor; UI muvaffaqiyat, empty, loading, error, conflict va permission denial holatlarini ko‘rsatadi.

### M08 — PC configurator va compatibility

- **Bosqich/ustuvorlik:** 1 / `MUST` (MUST — bosqich maqsadi uchun; SHOULD — reliz darvozasiga bog‘liq).
- **Nega mavjud:** Kompyuter qismlarini moslik qoidalari orqali yig‘ish va budjetli taklif berish.
- **Kim foydalanadi:** Buyer, Sales, AI, Manager.
- **Biznes maʼlumotlari:** `requested_budget, workload, component_specs, rule_set_version`. Bular ERD emas, data contractga kiradigan domen tushunchalari.
- **Funksiyalar va qamrov:**
  - **01.** ready PC builds
  - **02.** CPU socket, board chipset/BIOS review
  - **03.** RAM DDR/form factor
  - **04.** GPU length/case clearance
  - **05.** PSU headroom va connector
  - **06.** cooler/case dimensions
  - **07.** budget recommendation
  - **08.** alternatives/human review
- **Jarayon/holatlar:** `draft→compatible / review_required / incompatible→quote_ready`; tegishli to‘liq FSM: `05_STATE_MACHINES_AND_EXCEPTIONS.md`.
- **Bajarilishi shart bo‘lgan qoidalar:**
- `BL-027`: CPU/board/RAM/PSU/case bo‘yicha deterministik rules
- `BL-028`: Unknown != compatible; REVIEW_REQUIRED
- `BL-029`: Narx va stock filtrdan so‘ng tavsiya
- `BL-030`: Quote rule_version va evidence snapshot saqlanadi
- **Istisno va recovery (har biri test case):**
- unknown BIOS
- aniq o‘lcham yo‘q
- GPU stok tugagan
- foydalanuvchi noaniq workload
- qism nomi chalkash
- **UI sirtlari:**
- PC Builder
- Compatibility findings
- Budget alternatives
- Quote action
- **Hamkor modullar:** `M04`, `M05`, `M06`, `M10`, `M11`. Bu ro‘yxat logical collaboration, cross-module direct DB access ruxsati emas.
- **O‘lchanadigan natija:** incompatible quote=0, review_required%.
- **Acceptance minimumi:** barcha asosiy amallar role+tenant asosida tekshiriladi; yuqoridagi istisnolar sinovdan o‘tadi; barcha saqlangan o‘zgarishlarda sabab/actor va idempotent yoki kompensatsiya qilinadigan natija bor; UI muvaffaqiyat, empty, loading, error, conflict va permission denial holatlarini ko‘rsatadi.

### M09 — Kanallar va kanal hisoblarini ulash

- **Bosqich/ustuvorlik:** 1 / `MUST` (MUST — bosqich maqsadi uchun; SHOULD — reliz darvozasiga bog‘liq).
- **Nega mavjud:** Bitta merchant uchun ruxsatli Telegram/web/Meta kanal akkauntlarini integratsiya qilish.
- **Kim foydalanadi:** Owner, Manager.
- **Biznes maʼlumotlari:** `channel_account, provider_id, token_reference, provider_permissions`. Bular ERD emas, data contractga kiradigan domen tushunchalari.
- **Funksiyalar va qamrov:**
  - **01.** Telegram bot / Business bog‘lash
  - **02.** web widget joylashtirish
  - **03.** Meta professional account ruxsatiga tayyor adapter
  - **04.** OAuth/token rotate/revoke
  - **05.** channel policy/message window
  - **06.** webhook health
  - **07.** manual fallback
- **Jarayon/holatlar:** `pending→connected→degraded→disconnected/revoked`; tegishli to‘liq FSM: `05_STATE_MACHINES_AND_EXCEPTIONS.md`.
- **Bajarilishi shart bo‘lgan qoidalar:**
- `BL-031`: Rasmiy scope, account owner authorization va token vault
- `BL-032`: Auth/signature, provider event uniqueness, durable persistence before ACK
- `BL-033`: Provider window/recipient consent/rate-policy amal qilinadi
- **Istisno va recovery (har biri test case):**
- provider ruxsat bermaydi
- token muddati tugaydi
- webhook takrorlanadi
- outbound yuborish taqiqlangan
- rate limit
- **UI sirtlari:**
- Channel connect wizard
- Permission status
- Webhook health
- Disconnect
- **Hamkor modullar:** `M01`, `M02`, `M10`, `M11`, `M17`. Bu ro‘yxat logical collaboration, cross-module direct DB access ruxsati emas.
- **O‘lchanadigan natija:** connected channels, delivery failure rate.
- **Acceptance minimumi:** barcha asosiy amallar role+tenant asosida tekshiriladi; yuqoridagi istisnolar sinovdan o‘tadi; barcha saqlangan o‘zgarishlarda sabab/actor va idempotent yoki kompensatsiya qilinadigan natija bor; UI muvaffaqiyat, empty, loading, error, conflict va permission denial holatlarini ko‘rsatadi.

### M10 — Unified Inbox, conversation va human handoff

- **Bosqich/ustuvorlik:** 1 / `MUST` (MUST — bosqich maqsadi uchun; SHOULD — reliz darvozasiga bog‘liq).
- **Nega mavjud:** Kanallardagi suhbatlarni yo‘qotmasdan bitta operator navbatiga keltirish.
- **Kim foydalanadi:** Sales, Manager, AI.
- **Biznes maʼlumotlari:** `channel_msg_id, thread_id, sender_ref, consent_flags, assignee`. Bular ERD emas, data contractga kiradigan domen tushunchalari.
- **Funksiyalar va qamrov:**
  - **01.** inbound normalization/dedup
  - **02.** thread va customer identity linking
  - **03.** AI/on hold/manual mode
  - **04.** assign/escalate/transfer
  - **05.** agent suggested replies
  - **06.** attachments/voice transkript
  - **07.** follow-up/task reminder
  - **08.** consent/retention flag
- **Jarayon/holatlar:** `new→ai_active→waiting_customer→human_needed→human_active→resolved→reopened`; tegishli to‘liq FSM: `05_STATE_MACHINES_AND_EXCEPTIONS.md`.
- **Bajarilishi shart bo‘lgan qoidalar:**
- `BL-034`: Bitta vaqtda AI yoki human send authority, har ikkisi emas
- `BL-035`: Provider timestamp/event id bilan reorder/dedupe; unsafe gap = wait/reconcile
- `BL-036`: Xabarlardan kontakt/marketingga ruxsat farqlanadi
- `BL-037`: AI uncertain/complaint/payment/warranty = operator handoff
- **Istisno va recovery (har biri test case):**
- takrorlangan xabar
- out-of-order kelgan xabar
- operator va AI bir vaqtda javob
- provider window yopilgan
- unresponsive operator
- **UI sirtlari:**
- Unified inbox
- Conversation detail
- Human takeover
- Assignments
- Escalation queue
- **Hamkor modullar:** `M02`, `M09`, `M11`, `M12`, `M17`. Bu ro‘yxat logical collaboration, cross-module direct DB access ruxsati emas.
- **O‘lchanadigan natija:** first response, open backlog, takeover rate.
- **Acceptance minimumi:** barcha asosiy amallar role+tenant asosida tekshiriladi; yuqoridagi istisnolar sinovdan o‘tadi; barcha saqlangan o‘zgarishlarda sabab/actor va idempotent yoki kompensatsiya qilinadigan natija bor; UI muvaffaqiyat, empty, loading, error, conflict va permission denial holatlarini ko‘rsatadi.

### M11 — AI Sales Agent va product discovery

- **Bosqich/ustuvorlik:** 1 / `MUST` (MUST — bosqich maqsadi uchun; SHOULD — reliz darvozasiga bog‘liq).
- **Nega mavjud:** Mahsulot bo‘yicha ishonchli javob va mos tanlovni real katalogga tayangan holda berish.
- **Kim foydalanadi:** Customer, AI, Sales.
- **Biznes maʼlumotlari:** `conversation_context, merchant_catalog_scope, tool_policy, customer_intent`. Bular ERD emas, data contractga kiradigan domen tushunchalari.
- **Funksiyalar va qamrov:**
  - **01.** uz/ru/en niyat va tilni aniqlash
  - **02.** budget/attributes/need clarify
  - **03.** catalog-only search tools
  - **04.** photo, variant, stock va price explain
  - **05.** PC builds va alternatives
  - **06.** structured lead capture
  - **07.** guardrails va approval
  - **08.** fallback to human
  - **09.** AI usage metering
- **Jarayon/holatlar:** `idle→qualifying→recommending→quote_requested / handed_off / stopped`; tegishli to‘liq FSM: `05_STATE_MACHINES_AND_EXCEPTIONS.md`.
- **Bajarilishi shart bo‘lgan qoidalar:**
- `BL-038`: Faqat merchant allowlisted catalog tool natijasidagi SKU, narx, stock
- `BL-039`: Prompt injection va PII egress limit; tool-call schema validation
- `BL-040`: Configurable quota/timeout/fallback; foydalanuvchiga inson mavjud
- `BL-041`: Narx/delivery/discountni backend policy computes
- **Istisno va recovery (har biri test case):**
- LLM hallucinated SKU
- provider outage
- no matching product
- prompt injection
- boshqa merchant ma’lumoti
- token quota
- **UI sirtlari:**
- AI agent config
- Tool permissions
- Test playground
- Conversation explanation
- Fallback
- **Hamkor modullar:** `M04`, `M05`, `M06`, `M08`, `M10`, `M12`, `M17`, `M19`. Bu ro‘yxat logical collaboration, cross-module direct DB access ruxsati emas.
- **O‘lchanadigan natija:** grounded-answer rate, escalation rate, cost/lead.
- **Acceptance minimumi:** barcha asosiy amallar role+tenant asosida tekshiriladi; yuqoridagi istisnolar sinovdan o‘tadi; barcha saqlangan o‘zgarishlarda sabab/actor va idempotent yoki kompensatsiya qilinadigan natija bor; UI muvaffaqiyat, empty, loading, error, conflict va permission denial holatlarini ko‘rsatadi.

### M12 — Lead, CRM va quotation

- **Bosqich/ustuvorlik:** 1 / `MUST` (MUST — bosqich maqsadi uchun; SHOULD — reliz darvozasiga bog‘liq).
- **Nega mavjud:** Suhbatdan sotuv imkoniyati va qayta tiklab bo‘ladigan quote yaratish.
- **Kim foydalanadi:** Sales, Manager, AI limited.
- **Biznes maʼlumotlari:** `lead_id, source, customer_contact, snapshot, currency, quote_expiry`. Bular ERD emas, data contractga kiradigan domen tushunchalari.
- **Funksiyalar va qamrov:**
  - **01.** lead dedup va source attribution
  - **02.** qualification (budget, spec, phone consent)
  - **03.** priority/owner/follow-up
  - **04.** PC quotation snapshot
  - **05.** quote expiry/approve/send
  - **06.** win/loss reason
  - **07.** customer acceptance
  - **08.** quote revisions with immutable history
- **Jarayon/holatlar:** `lead: new→qualified→quoted→won/lost; quote: draft→review→approved→sent→accepted/expired/rejected`; tegishli to‘liq FSM: `05_STATE_MACHINES_AND_EXCEPTIONS.md`.
- **Bajarilishi shart bo‘lgan qoidalar:**
- `BL-042`: Consent va minimal contact; duplicate logic scoped per merchant
- `BL-043`: Immutable SKU, price, taxes/fee if any, condition, warranty snapshot
- `BL-044`: Expiry/stock/price qayta check; old quote paid order qilinmaydi
- `BL-045`: Threshold/compatibility REVIEW uchun authorized approver
- **Istisno va recovery (har biri test case):**
- operator forgot lead
- quote price changed
- no consent contact
- rejected quote revisions
- duplicate lead cross-channel
- **UI sirtlari:**
- Lead pipeline
- Lead detail
- Quote builder
- Quote preview
- Approval
- **Hamkor modullar:** `M05`, `M08`, `M10`, `M11`, `M13`, `M17`. Bu ro‘yxat logical collaboration, cross-module direct DB access ruxsati emas.
- **O‘lchanadigan natija:** qualified lead rate, quote-to-order.
- **Acceptance minimumi:** barcha asosiy amallar role+tenant asosida tekshiriladi; yuqoridagi istisnolar sinovdan o‘tadi; barcha saqlangan o‘zgarishlarda sabab/actor va idempotent yoki kompensatsiya qilinadigan natija bor; UI muvaffaqiyat, empty, loading, error, conflict va permission denial holatlarini ko‘rsatadi.

### M13 — Buyurtma va order lifecycle

- **Bosqich/ustuvorlik:** 1 / `MUST` (MUST — bosqich maqsadi uchun; SHOULD — reliz darvozasiga bog‘liq).
- **Nega mavjud:** Tasdiqlangan talabni auditli, idempotent buyurtma operatsiyasiga aylantirish.
- **Kim foydalanadi:** Customer, Sales, Manager.
- **Biznes maʼlumotlari:** `order_id, quote_snapshot, lines, fulfillment_method, idempotency_key`. Bular ERD emas, data contractga kiradigan domen tushunchalari.
- **Funksiyalar va qamrov:**
  - **01.** cart/quote to order
  - **02.** merchant order number
  - **03.** customer contact+pickup/shipping
  - **04.** reserve / confirm
  - **05.** cancel/partial cancel
  - **06.** order timeline, reason
  - **07.** duplicate order prevention
  - **08.** merchant comments/internal notes
- **Jarayon/holatlar:** `draft→pending_confirmation→confirmed→processing→completed/cancelled`; tegishli to‘liq FSM: `05_STATE_MACHINES_AND_EXCEPTIONS.md`.
- **Bajarilishi shart bo‘lgan qoidalar:**
- `BL-046`: Quote/order idempotency key, tenant and source uniqueness
- `BL-047`: Current stock or valid reservation, price and terms checked
- `BL-048`: Only allowed FSM transition with role and reason
- `BL-049`: Reservation release and payment reconciliation orchestrated; no silent paid loss
- **Istisno va recovery (har biri test case):**
- parallel confirm
- buyurtma bekor bo‘lganidan keyin payment
- out of stock
- partial fulfill
- stale quote
- merchant pause
- **UI sirtlari:**
- Order list
- Order detail
- Confirm/cancel dialog
- Timeline
- Order exceptions
- **Hamkor modullar:** `M06`, `M12`, `M14`, `M15`, `M16`, `M17`. Bu ro‘yxat logical collaboration, cross-module direct DB access ruxsati emas.
- **O‘lchanadigan natija:** order accuracy, cancellations.
- **Acceptance minimumi:** barcha asosiy amallar role+tenant asosida tekshiriladi; yuqoridagi istisnolar sinovdan o‘tadi; barcha saqlangan o‘zgarishlarda sabab/actor va idempotent yoki kompensatsiya qilinadigan natija bor; UI muvaffaqiyat, empty, loading, error, conflict va permission denial holatlarini ko‘rsatadi.

### M14 — To‘lov va chekni tekshirish

- **Bosqich/ustuvorlik:** 1 / `MUST` (MUST — bosqich maqsadi uchun; SHOULD — reliz darvozasiga bog‘liq).
- **Nega mavjud:** Tasdiqlanmagan chek rasmini real paid holatiga aylantirmaslik.
- **Kim foydalanadi:** Customer, Cashier, Manager.
- **Biznes maʼlumotlari:** `payment_id, provider_ref, amount, currency, proof, settlement_status`. Bular ERD emas, data contractga kiradigan domen tushunchalari.
- **Funksiyalar va qamrov:**
  - **01.** pay link yoki merchant rekvizitlari
  - **02.** manual proof upload
  - **03.** admin verifies settlement
  - **04.** provider callback adapter
  - **05.** partial payment/refund request
  - **06.** reconciliation dashboard
  - **07.** financial evidence audit
- **Jarayon/holatlar:** `initiated→awaiting_confirmation→verified/failed/cancelled; refund pending→approved→completed/failed`; tegishli to‘liq FSM: `05_STATE_MACHINES_AND_EXCEPTIONS.md`.
- **Bajarilishi shart bo‘lgan qoidalar:**
- `BL-050`: Proof != verified; authorized reviewer matches actual receipt
- `BL-051`: Authenticity, amount, currency, merchant account and provider ref checked
- `BL-052`: Idempotent processing and ledger reconciliation
- `BL-053`: Merchant policy, evidence, approval, exact amount limits
- **Istisno va recovery (har biri test case):**
- screenshot forged
- webhook replay
- paid amount mismatch
- late success after expiry
- double refund
- provider down
- **UI sirtlari:**
- Payments list
- Review receipt
- Payment detail
- Reconciliation
- Refund approval
- **Hamkor modullar:** `M02`, `M06`, `M13`, `M17`, `M18`. Bu ro‘yxat logical collaboration, cross-module direct DB access ruxsati emas.
- **O‘lchanadigan natija:** payment mismatch, false paid=0.
- **Acceptance minimumi:** barcha asosiy amallar role+tenant asosida tekshiriladi; yuqoridagi istisnolar sinovdan o‘tadi; barcha saqlangan o‘zgarishlarda sabab/actor va idempotent yoki kompensatsiya qilinadigan natija bor; UI muvaffaqiyat, empty, loading, error, conflict va permission denial holatlarini ko‘rsatadi.

### M15 — Yetkazish va pickup

- **Bosqich/ustuvorlik:** 1 / `MUST` (MUST — bosqich maqsadi uchun; SHOULD — reliz darvozasiga bog‘liq).
- **Nega mavjud:** Buyurtmani jo‘natish/olib ketish nazoratini merchantga berish.
- **Kim foydalanadi:** Manager, Courier, Customer.
- **Biznes maʼlumotlari:** `shipment_id, method, branch, courier, address, POD`. Bular ERD emas, data contractga kiradigan domen tushunchalari.
- **Funksiyalar va qamrov:**
  - **01.** pickup vs local delivery
  - **02.** courier assignment
  - **03.** address confirmation
  - **04.** ETA only verified estimates
  - **05.** status updates
  - **06.** proof-of-delivery
  - **07.** failed delivery retry/reschedule
  - **08.** customer notification
- **Jarayon/holatlar:** `pending→ready→assigned→in_transit→delivered; exception→rescheduled/returned`; tegishli to‘liq FSM: `05_STATE_MACHINES_AND_EXCEPTIONS.md`.
- **Bajarilishi shart bo‘lgan qoidalar:**
- `BL-054`: Address, contact permission, branch and shipment method verified
- `BL-055`: Courier/manager scoped; POD where applicable
- `BL-056`: Retry/reschedule/return recorded, customer informed
- **Istisno va recovery (har biri test case):**
- noto‘g‘ri address
- courier not assigned
- mijoz uyda yo‘q
- delivery cancelled
- lost parcel
- **UI sirtlari:**
- Fulfillment board
- Shipment timeline
- Courier view
- Tracking page
- **Hamkor modullar:** `M03`, `M13`, `M17`. Bu ro‘yxat logical collaboration, cross-module direct DB access ruxsati emas.
- **O‘lchanadigan natija:** delivered %, exception age.
- **Acceptance minimumi:** barcha asosiy amallar role+tenant asosida tekshiriladi; yuqoridagi istisnolar sinovdan o‘tadi; barcha saqlangan o‘zgarishlarda sabab/actor va idempotent yoki kompensatsiya qilinadigan natija bor; UI muvaffaqiyat, empty, loading, error, conflict va permission denial holatlarini ko‘rsatadi.

### M16 — Sotuvdan keyingi xizmat va kafolat

- **Bosqich/ustuvorlik:** 1 / `SHOULD` (MUST — bosqich maqsadi uchun; SHOULD — reliz darvozasiga bog‘liq).
- **Nega mavjud:** Qaytarish, da’vo va kafolat jarayonini sotuvchi mas’uliyatida kuzatish.
- **Kim foydalanadi:** Customer, Support, Manager.
- **Biznes maʼlumotlari:** `order_ref, warranty_terms, issue_evidence, resolution`. Bular ERD emas, data contractga kiradigan domen tushunchalari.
- **Funksiyalar va qamrov:**
  - **01.** warranty terms snapshot
  - **02.** RMA/support ticket
  - **03.** return eligibility review
  - **04.** exchange/repair/refund request
  - **05.** customer feedback
  - **06.** dispute escalation
  - **07.** return-to-stock review
- **Jarayon/holatlar:** `new→review→approved/rejected→in_service→resolved/closed`; tegishli to‘liq FSM: `05_STATE_MACHINES_AND_EXCEPTIONS.md`.
- **Bajarilishi shart bo‘lgan qoidalar:**
- `BL-057`: Terms snapshot order line at time of sale
- `BL-058`: Eligibility and product condition reviewed by human
- `BL-059`: Inspect return; damaged not saleable
- **Istisno va recovery (har biri test case):**
- warranty ambiguous
- used product sold as new
- refund provider failed
- returned item damaged
- **UI sirtlari:**
- Support inbox
- RMA case
- Warranty detail
- Resolution history
- **Hamkor modullar:** `M13`, `M14`, `M15`, `M17`. Bu ro‘yxat logical collaboration, cross-module direct DB access ruxsati emas.
- **O‘lchanadigan natija:** resolution time, repeat complaints.
- **Acceptance minimumi:** barcha asosiy amallar role+tenant asosida tekshiriladi; yuqoridagi istisnolar sinovdan o‘tadi; barcha saqlangan o‘zgarishlarda sabab/actor va idempotent yoki kompensatsiya qilinadigan natija bor; UI muvaffaqiyat, empty, loading, error, conflict va permission denial holatlarini ko‘rsatadi.

### M17 — Notifications, automation va merchant tasks

- **Bosqich/ustuvorlik:** 1 / `MUST` (MUST — bosqich maqsadi uchun; SHOULD — reliz darvozasiga bog‘liq).
- **Nega mavjud:** Hech bir buyurtma/operator vazifasi yo‘qolib ketmasin.
- **Kim foydalanadi:** Owner, Sales, Courier, Customer.
- **Biznes maʼlumotlari:** `event_type, recipient, template_version, preference`. Bular ERD emas, data contractga kiradigan domen tushunchalari.
- **Funksiyalar va qamrov:**
  - **01.** notification template va locale
  - **02.** order/payment/escalation triggers
  - **03.** in-app/Telegram/email adapter
  - **04.** reminder due dates
  - **05.** delivery status message
  - **06.** quiet hours/opt-out
  - **07.** retry/dedup/failure log
- **Jarayon/holatlar:** `pending→scheduled→sent/failed/suppressed`; tegishli to‘liq FSM: `05_STATE_MACHINES_AND_EXCEPTIONS.md`.
- **Bajarilishi shart bo‘lgan qoidalar:**
- `BL-060`: Event/template/version/recipient and dedup key recorded
- `BL-061`: Respect legal and channel transactional exceptions
- `BL-062`: Retry bounded; DLQ and visible merchant task
- **Istisno va recovery (har biri test case):**
- takror notification
- provider unavailable
- opt-out
- quiet hour
- stale recipient
- message loop
- **UI sirtlari:**
- Notification center
- Template editor
- Task queue
- Delivery log
- **Hamkor modullar:** `M09`, `M10`, `M12`, `M13`, `M14`, `M15`, `M18`. Bu ro‘yxat logical collaboration, cross-module direct DB access ruxsati emas.
- **O‘lchanadigan natija:** missed SLA tasks, delivery success.
- **Acceptance minimumi:** barcha asosiy amallar role+tenant asosida tekshiriladi; yuqoridagi istisnolar sinovdan o‘tadi; barcha saqlangan o‘zgarishlarda sabab/actor va idempotent yoki kompensatsiya qilinadigan natija bor; UI muvaffaqiyat, empty, loading, error, conflict va permission denial holatlarini ko‘rsatadi.

### M18 — Dashboard, hisobot va Voice Business Copilot

- **Bosqich/ustuvorlik:** 1 / `MUST` (MUST — bosqich maqsadi uchun; SHOULD — reliz darvozasiga bog‘liq).
- **Nega mavjud:** Egaga real biznes ma’lumotlari asosida uch tilda hisob berish.
- **Kim foydalanadi:** Owner, Manager, Analyst.
- **Biznes maʼlumotlari:** `metric_id, scoped_period, branch, timezone, data_as_of`. Bular ERD emas, data contractga kiradigan domen tushunchalari.
- **Funksiyalar va qamrov:**
  - **01.** KPI: orders/paid turnover/margin only if COGS exists
  - **02.** period/branch/channel comparisons
  - **03.** saved reports+export
  - **04.** uz/ru/en voice STT→intent→typed metric query→TTS
  - **05.** read-only first
  - **06.** explain data freshness
  - **07.** dashboard drill-down
  - **08.** access-based aggregation
- **Jarayon/holatlar:** `requested→running→completed/partial/failed`; tegishli to‘liq FSM: `05_STATE_MACHINES_AND_EXCEPTIONS.md`.
- **Bajarilishi shart bo‘lgan qoidalar:**
- `BL-063`: Metric registry defines paid turnover vs profit vs revenue
- `BL-064`: Speech-to-text transcript confirmation for sensitive sums
- `BL-065`: Branch/role; sensitive costs hidden from sales users
- `BL-066`: Every generated answer displays period/timezone/data_as_of
- **Istisno va recovery (har biri test case):**
- ASR currency mistake
- missing COGS
- report stale
- unauthorized margin query
- AI invented number
- recording consent
- **UI sirtlari:**
- Overview dashboard
- Report builder
- Voice mic/transcript
- Chart/export
- **Hamkor modullar:** `M02`, `M10`, `M12`, `M13`, `M14`, `M17`, `M19`. Bu ro‘yxat logical collaboration, cross-module direct DB access ruxsati emas.
- **O‘lchanadigan natija:** metric reconciliation, answer groundedness.
- **Acceptance minimumi:** barcha asosiy amallar role+tenant asosida tekshiriladi; yuqoridagi istisnolar sinovdan o‘tadi; barcha saqlangan o‘zgarishlarda sabab/actor va idempotent yoki kompensatsiya qilinadigan natija bor; UI muvaffaqiyat, empty, loading, error, conflict va permission denial holatlarini ko‘rsatadi.

### M19 — Merchant AI controls, billing va platform operations

- **Bosqich/ustuvorlik:** 1 / `MUST` (MUST — bosqich maqsadi uchun; SHOULD — reliz darvozasiga bog‘liq).
- **Nega mavjud:** AI va SaaS foydalanishni tarif, xavfsizlik va qo‘llab-quvvatlash chegarasida saqlash.
- **Kim foydalanadi:** Owner, Platform Admin.
- **Biznes maʼlumotlari:** `plan_id, entitlements, usage_ledger, support_case`. Bular ERD emas, data contractga kiradigan domen tushunchalari.
- **Funksiyalar va qamrov:**
  - **01.** AI enable/disable/policy
  - **02.** usage limits and soft stop
  - **03.** subscription lifecycle
  - **04.** seat/channel/SKU quotas
  - **05.** support issue queue
  - **06.** error state/health
  - **07.** merchant data export/offboarding
  - **08.** tenant billing invoice
- **Jarayon/holatlar:** `trial→active→past_due→restricted→cancelled`; tegishli to‘liq FSM: `05_STATE_MACHINES_AND_EXCEPTIONS.md`.
- **Bajarilishi shart bo‘lgan qoidalar:**
- `BL-067`: Usage measured by merchant and stable billing windows
- `BL-068`: Grace and downgrade policies; existing paid orders remain accessible
- `BL-069`: Human sale/catalog/order operate independent of AI model
- `BL-070`: Export available according to policy, access revoke, retention purge
- **Istisno va recovery (har biri test case):**
- over-quota conversation
- downgrade active order
- provider fee spike
- suspended account
- tenant offboarding
- **UI sirtlari:**
- Plan/usage
- Settings
- Billing
- Support center
- AI safe mode
- **Hamkor modullar:** `M01`, `M02`, `M09`, `M11`, `M17`, `M18`. Bu ro‘yxat logical collaboration, cross-module direct DB access ruxsati emas.
- **O‘lchanadigan natija:** gross margin/tenant, active merchants.
- **Acceptance minimumi:** barcha asosiy amallar role+tenant asosida tekshiriladi; yuqoridagi istisnolar sinovdan o‘tadi; barcha saqlangan o‘zgarishlarda sabab/actor va idempotent yoki kompensatsiya qilinadigan natija bor; UI muvaffaqiyat, empty, loading, error, conflict va permission denial holatlarini ko‘rsatadi.

### M20 — Activity log va biznes audit

- **Bosqich/ustuvorlik:** 1 / `MUST` (MUST — bosqich maqsadi uchun; SHOULD — reliz darvozasiga bog‘liq).
- **Nega mavjud:** Moliyaviy yoki stok bilan bog‘liq harakatlarni qayta tekshirish imkonini berish.
- **Kim foydalanadi:** Owner, Auditor, Platform Support limited.
- **Biznes maʼlumotlari:** `actor, tenant, action, object_ref, correlation_id`. Bular ERD emas, data contractga kiradigan domen tushunchalari.
- **Funksiyalar va qamrov:**
  - **01.** who/when/why/change trace
  - **02.** before-after safe diffs
  - **03.** read views by role
  - **04.** tamper-evident append only
  - **05.** export with approval
  - **06.** PII redaction
  - **07.** support break-glass audit
- **Jarayon/holatlar:** `recorded→retained→expired by policy`; tegishli to‘liq FSM: `05_STATE_MACHINES_AND_EXCEPTIONS.md`.
- **Bajarilishi shart bo‘lgan qoidalar:**
- `BL-071`: Actor, trace, entity, before/after safe diff audit in same logical operation
- `BL-072`: Secrets, card data and unnecessary PII not logged
- **Istisno va recovery (har biri test case):**
- logga PII tushishi
- audit yozilmasdan state mutatsiya
- unauthorized export
- operator denied access
- **UI sirtlari:**
- Audit search
- Object activity timeline
- Security event view
- **Hamkor modullar:** `M01`, `M02`, `M05`, `M06`, `M13`, `M14`, `M18`. Bu ro‘yxat logical collaboration, cross-module direct DB access ruxsati emas.
- **O‘lchanadigan natija:** unaudited critical mutations=0.
- **Acceptance minimumi:** barcha asosiy amallar role+tenant asosida tekshiriladi; yuqoridagi istisnolar sinovdan o‘tadi; barcha saqlangan o‘zgarishlarda sabab/actor va idempotent yoki kompensatsiya qilinadigan natija bor; UI muvaffaqiyat, empty, loading, error, conflict va permission denial holatlarini ko‘rsatadi.


---

## STAGE 2 — Merchant Network — merchant scaling and shared data

### M21 — Self-service merchant provisioning

- **Bosqich/ustuvorlik:** 2 / `MUST` (MUST — bosqich maqsadi uchun; SHOULD — reliz darvozasiga bog‘liq).
- **Nega mavjud:** Qo‘lda integratsiyasiz merchant va sayt/bot ishga tushirishni ommaviylashtirish.
- **Kim foydalanadi:** Prospective Owner, Platform Admin.
- **Biznes maʼlumotlari:** `merchant_signup, chosen_plan, provision_job`. Bular ERD emas, data contractga kiradigan domen tushunchalari.
- **Funksiyalar va qamrov:**
  - **01.** public signup and anti-fraud
  - **02.** automated workspace/subdomain
  - **03.** self-serve plan purchase
  - **04.** guided catalog import
  - **05.** publish readiness score
  - **06.** auto health checks
  - **07.** support escalation
- **Jarayon/holatlar:** `registered→verified→provisioned→ready/blocked`; tegishli to‘liq FSM: `05_STATE_MACHINES_AND_EXCEPTIONS.md`.
- **Bajarilishi shart bo‘lgan qoidalar:**
- `BL-001`: Bitta tasdiqlangan owner va mustaqil merchant identity yaratiladi
- `BL-003`: Minimal identifikatsiya, aloqa va public terms tasdiq bo‘lmaguncha live emas
- `BL-067`: Usage measured by merchant and stable billing windows
- **Istisno va recovery (har biri test case):**
- fraud signup
- subdomain conflict
- partial provisioning
- billing failed
- **UI sirtlari:**
- Public signup
- Provision checklist
- Retry setup
- **Hamkor modullar:** `M01`, `M07`, `M19`, `M22`. Bu ro‘yxat logical collaboration, cross-module direct DB access ruxsati emas.
- **O‘lchanadigan natija:** time to live merchant.
- **Acceptance minimumi:** barcha asosiy amallar role+tenant asosida tekshiriladi; yuqoridagi istisnolar sinovdan o‘tadi; barcha saqlangan o‘zgarishlarda sabab/actor va idempotent yoki kompensatsiya qilinadigan natija bor; UI muvaffaqiyat, empty, loading, error, conflict va permission denial holatlarini ko‘rsatadi.

### M22 — Integration hub / POS / ERP / marketplaces

- **Bosqich/ustuvorlik:** 2 / `MUST` (MUST — bosqich maqsadi uchun; SHOULD — reliz darvozasiga bog‘liq).
- **Nega mavjud:** Do‘konning mavjud ma’lumot manbalarini ikkinchi qo‘lda qayta yuritmaslik.
- **Kim foydalanadi:** Owner, Integrator.
- **Biznes maʼlumotlari:** `connector_account, mapping, cursor, source_priority`. Bular ERD emas, data contractga kiradigan domen tushunchalari.
- **Funksiyalar va qamrov:**
  - **01.** connector registry and credentials
  - **02.** field mapping & dry run
  - **03.** incremental sync
  - **04.** source priority and conflict policy
  - **05.** sync error review
  - **06.** revocation/health
  - **07.** rate limits/resume
  - **08.** manual reconciliation
- **Jarayon/holatlar:** `draft→authorized→syncing→healthy/degraded→revoked`; tegishli to‘liq FSM: `05_STATE_MACHINES_AND_EXCEPTIONS.md`.
- **Bajarilishi shart bo‘lgan qoidalar:**
- `BL-073`: Source-of-truth priority per field (stock, price, metadata) declared
- `BL-074`: Provider-specific cursor, idempotency and rate limits
- `BL-075`: Test import dry-run and log unresolved SKU
- **Istisno va recovery (har biri test case):**
- API credentials revoked
- data overwrite
- stock race across POS
- stale cursor
- provider unavailable
- **UI sirtlari:**
- Integration catalog
- Mapping wizard
- Sync health
- Conflict resolution
- **Hamkor modullar:** `M04`, `M05`, `M06`, `M09`, `M21`, `M23`. Bu ro‘yxat logical collaboration, cross-module direct DB access ruxsati emas.
- **O‘lchanadigan natija:** sync freshness, data conflicts.
- **Acceptance minimumi:** barcha asosiy amallar role+tenant asosida tekshiriladi; yuqoridagi istisnolar sinovdan o‘tadi; barcha saqlangan o‘zgarishlarda sabab/actor va idempotent yoki kompensatsiya qilinadigan natija bor; UI muvaffaqiyat, empty, loading, error, conflict va permission denial holatlarini ko‘rsatadi.

### M23 — Global canonical product registry

- **Bosqich/ustuvorlik:** 2 / `MUST` (MUST — bosqich maqsadi uchun; SHOULD — reliz darvozasiga bog‘liq).
- **Nega mavjud:** Turli merchantlarning bir xil mahsulotlarini ehtiyotkorlik bilan bitta canonical modelga bog‘lash.
- **Kim foydalanadi:** Catalog Operator, Merchant, AI assist.
- **Biznes maʼlumotlari:** `canonical_product, offer_candidate, evidence, match_score`. Bular ERD emas, data contractga kiradigan domen tushunchalari.
- **Funksiyalar va qamrov:**
  - **01.** brand/model/MPN/GTIN normalize
  - **02.** variant and condition differentiation
  - **03.** matching confidence and evidence
  - **04.** review queue
  - **05.** merge/split/version history
  - **06.** provenance and aliases
  - **07.** multilingual synonyms
- **Jarayon/holatlar:** `unmatched→candidate→reviewed→matched/rejected`; tegishli to‘liq FSM: `05_STATE_MACHINES_AND_EXCEPTIONS.md`.
- **Bajarilishi shart bo‘lgan qoidalar:**
- `BL-076`: GTIN/MPN/brand+model+variant evidence required
- `BL-077`: Capacity, color, condition, revision/material specs never silently merged
- `BL-078`: Keep provenance and reversible links
- **Istisno va recovery (har biri test case):**
- false merge
- GTIN collision
- different capacity
- used/new mismatch
- title translation misleading
- **UI sirtlari:**
- Global product review
- Merge diff
- Provenance audit
- **Hamkor modullar:** `M04`, `M22`, `M24`, `M28`. Bu ro‘yxat logical collaboration, cross-module direct DB access ruxsati emas.
- **O‘lchanadigan natija:** precision, false merge rate.
- **Acceptance minimumi:** barcha asosiy amallar role+tenant asosida tekshiriladi; yuqoridagi istisnolar sinovdan o‘tadi; barcha saqlangan o‘zgarishlarda sabab/actor va idempotent yoki kompensatsiya qilinadigan natija bor; UI muvaffaqiyat, empty, loading, error, conflict va permission denial holatlarini ko‘rsatadi.

### M24 — Merchant public offers va opt-in

- **Bosqich/ustuvorlik:** 2 / `MUST` (MUST — bosqich maqsadi uchun; SHOULD — reliz darvozasiga bog‘liq).
- **Nega mavjud:** Do‘kon o‘z ma’lumotini global tarmoqqa qanday chiqarishini o‘zi boshqarsin.
- **Kim foydalanadi:** Owner, Manager.
- **Biznes maʼlumotlari:** `merchant_offer, canonical_product_ref, consent, public_fields`. Bular ERD emas, data contractga kiradigan domen tushunchalari.
- **Funksiyalar va qamrov:**
  - **01.** per-SKU public opt-in/out
  - **02.** public price/availability/warranty terms
  - **03.** offer version+freshness
  - **04.** branch visibility settings
  - **05.** hide/unpublish/revoke
  - **06.** public/private field contract
  - **07.** legal policy acknowledgement
- **Jarayon/holatlar:** `private→pending_validation→published→stale/hidden/withdrawn`; tegishli to‘liq FSM: `05_STATE_MACHINES_AND_EXCEPTIONS.md`.
- **Bajarilishi shart bo‘lgan qoidalar:**
- `BL-079`: Merchant explicitly selects offered public fields
- `BL-080`: Index is eventually consistent but withdrawal prioritized; fail closed after revoke
- `BL-081`: Only approved public price, terms, branch location; never COGS/leads
- **Istisno va recovery (har biri test case):**
- merchant revokes permission
- missing warranty
- stock stale
- search still cached after hide
- **UI sirtlari:**
- Public listings settings
- Offer publish preview
- Freshness report
- **Hamkor modullar:** `M05`, `M06`, `M23`, `M28`, `M29`. Bu ro‘yxat logical collaboration, cross-module direct DB access ruxsati emas.
- **O‘lchanadigan natija:** valid public offers, takedown lag.
- **Acceptance minimumi:** barcha asosiy amallar role+tenant asosida tekshiriladi; yuqoridagi istisnolar sinovdan o‘tadi; barcha saqlangan o‘zgarishlarda sabab/actor va idempotent yoki kompensatsiya qilinadigan natija bor; UI muvaffaqiyat, empty, loading, error, conflict va permission denial holatlarini ko‘rsatadi.

### M25 — Multi-branch inventory and fulfillment intelligence

- **Bosqich/ustuvorlik:** 2 / `MUST` (MUST — bosqich maqsadi uchun; SHOULD — reliz darvozasiga bog‘liq).
- **Nega mavjud:** Filiallar kesimida qoldiq, pickup va yetkazishga mos lead routing.
- **Kim foydalanadi:** Owner, Warehouse, Manager.
- **Biznes maʼlumotlari:** `branch_id, transfer_id, sku, qty, fulfillment_policy`. Bular ERD emas, data contractga kiradigan domen tushunchalari.
- **Funksiyalar va qamrov:**
  - **01.** branch stock splits
  - **02.** transfer requisitions
  - **03.** warehouse→branch movement
  - **04.** replenishment suggestions
  - **05.** branch-specific pickup SLA
  - **06.** negative stock protection
  - **07.** transfer ledger
- **Jarayon/holatlar:** `transfer: draft→approved→in_transit→received/cancelled`; tegishli to‘liq FSM: `05_STATE_MACHINES_AND_EXCEPTIONS.md`.
- **Bajarilishi shart bo‘lgan qoidalar:**
- `BL-019`: available = on_hand - reserved - allocated, >= 0
- `BL-021`: Faqat faol rezerv bo‘shatiladi; qayta release no-op
- `BL-082`: Atomic decrement origin at dispatched, receive destination after confirmation; in-transit tracked
- **Istisno va recovery (har biri test case):**
- transfer and reservation collide
- in transit vanished
- reconciliation mismatch
- two branches reserve same SKU
- **UI sirtlari:**
- Branch stock matrix
- Transfer order
- Transfer audit
- **Hamkor modullar:** `M03`, `M06`, `M15`, `M22`. Bu ro‘yxat logical collaboration, cross-module direct DB access ruxsati emas.
- **O‘lchanadigan natija:** transfer delay, pick success.
- **Acceptance minimumi:** barcha asosiy amallar role+tenant asosida tekshiriladi; yuqoridagi istisnolar sinovdan o‘tadi; barcha saqlangan o‘zgarishlarda sabab/actor va idempotent yoki kompensatsiya qilinadigan natija bor; UI muvaffaqiyat, empty, loading, error, conflict va permission denial holatlarini ko‘rsatadi.

### M26 — Merchant tenancy at scale va subscription automation

- **Bosqich/ustuvorlik:** 2 / `MUST` (MUST — bosqich maqsadi uchun; SHOULD — reliz darvozasiga bog‘liq).
- **Nega mavjud:** Minglab merchantga support va tariflarni avtomatlashtirish.
- **Kim foydalanadi:** Platform Admin, Owner.
- **Biznes maʼlumotlari:** `plan, billing_period, entitlements, usage`. Bular ERD emas, data contractga kiradigan domen tushunchalari.
- **Funksiyalar va qamrov:**
  - **01.** plan self-service changes
  - **02.** quota calculation
  - **03.** usage invoice
  - **04.** merchant health scoring
  - **05.** fraud/abuse suppression
  - **06.** billing dunning
  - **07.** tenant data export/termination
- **Jarayon/holatlar:** `active→grace_period→limited→restored/terminated`; tegishli to‘liq FSM: `05_STATE_MACHINES_AND_EXCEPTIONS.md`.
- **Bajarilishi shart bo‘lgan qoidalar:**
- `BL-067`: Usage measured by merchant and stable billing windows
- `BL-068`: Grace and downgrade policies; existing paid orders remain accessible
- `BL-083`: Effective dates/usage and rights calculated deterministically
- **Istisno va recovery (har biri test case):**
- billing webhook replay
- quota race
- tenant deletion active dispute
- billing provider down
- **UI sirtlari:**
- Billing console
- Tenant fleet
- Usage analytics
- **Hamkor modullar:** `M19`, `M21`, `M22`. Bu ro‘yxat logical collaboration, cross-module direct DB access ruxsati emas.
- **O‘lchanadigan natija:** merchant retention, unit cost.
- **Acceptance minimumi:** barcha asosiy amallar role+tenant asosida tekshiriladi; yuqoridagi istisnolar sinovdan o‘tadi; barcha saqlangan o‘zgarishlarda sabab/actor va idempotent yoki kompensatsiya qilinadigan natija bor; UI muvaffaqiyat, empty, loading, error, conflict va permission denial holatlarini ko‘rsatadi.

### M27 — Merchant-facing AI policy/knowledge center

- **Bosqich/ustuvorlik:** 2 / `MUST` (MUST — bosqich maqsadi uchun; SHOULD — reliz darvozasiga bog‘liq).
- **Nega mavjud:** Har merchant AI sotuvchisining ruxsatli bilimlarini mustaqil boshqara olsin.
- **Kim foydalanadi:** Owner, Manager, AI Operator.
- **Biznes maʼlumotlari:** `knowledge_revision, policies, language, tool_grants`. Bular ERD emas, data contractga kiradigan domen tushunchalari.
- **Funksiyalar va qamrov:**
  - **01.** FAQ/returns/warranty knowledge
  - **02.** source revision approval
  - **03.** tone/language setting
  - **04.** AI answer preview
  - **05.** tool enable matrix
  - **06.** abuse/prompt injection review
  - **07.** quality eval feedback
- **Jarayon/holatlar:** `draft→review→approved→published→rolled_back`; tegishli to‘liq FSM: `05_STATE_MACHINES_AND_EXCEPTIONS.md`.
- **Bajarilishi shart bo‘lgan qoidalar:**
- `BL-038`: Faqat merchant allowlisted catalog tool natijasidagi SKU, narx, stock
- `BL-039`: Prompt injection va PII egress limit; tool-call schema validation
- `BL-084`: Policies reviewed and versioned before AI answers
- **Istisno va recovery (har biri test case):**
- policy contradicts merchant terms
- owner accidentally enables unsafe tool
- bad multilingual translation
- **UI sirtlari:**
- Knowledge hub
- Agent sandbox
- Policy release
- **Hamkor modullar:** `M10`, `M11`, `M16`, `M18`. Bu ro‘yxat logical collaboration, cross-module direct DB access ruxsati emas.
- **O‘lchanadigan natija:** verified response coverage.
- **Acceptance minimumi:** barcha asosiy amallar role+tenant asosida tekshiriladi; yuqoridagi istisnolar sinovdan o‘tadi; barcha saqlangan o‘zgarishlarda sabab/actor va idempotent yoki kompensatsiya qilinadigan natija bor; UI muvaffaqiyat, empty, loading, error, conflict va permission denial holatlarini ko‘rsatadi.

### M28 — Search index publishing and catalog data quality

- **Bosqich/ustuvorlik:** 2 / `MUST` (MUST — bosqich maqsadi uchun; SHOULD — reliz darvozasiga bog‘liq).
- **Nega mavjud:** Uchinchi bosqich global qidiruv uchun yangi va tekshirilgan public index shakllantirish.
- **Kim foydalanadi:** Catalog Operator, Platform Admin.
- **Biznes maʼlumotlari:** `public_offer_events, index_version, watermark`. Bular ERD emas, data contractga kiradigan domen tushunchalari.
- **Funksiyalar va qamrov:**
  - **01.** incremental index from public offers
  - **02.** freshness SLA
  - **03.** denormalization without sensitive fields
  - **04.** stale suppression
  - **05.** rebuild/replay
  - **06.** search result sampling
  - **07.** quality score by merchant
- **Jarayon/holatlar:** `pending_index→indexed→stale→hidden/reindexed`; tegishli to‘liq FSM: `05_STATE_MACHINES_AND_EXCEPTIONS.md`.
- **Bajarilishi shart bo‘lgan qoidalar:**
- `BL-080`: Index is eventually consistent but withdrawal prioritized; fail closed after revoke
- `BL-085`: Event ordering/aggregate_version and replay semantics
- `BL-086`: Merchant-defined TTL; stale prices hidden/warned
- **Istisno va recovery (har biri test case):**
- lost event
- out-of-order price update
- withdrawn offer still visible
- index rebuild drift
- **UI sirtlari:**
- Index health
- Publish queue
- Quality diagnostics
- **Hamkor modullar:** `M23`, `M24`, `M29`. Bu ro‘yxat logical collaboration, cross-module direct DB access ruxsati emas.
- **O‘lchanadigan natija:** index age, withdrawn visibility=0.
- **Acceptance minimumi:** barcha asosiy amallar role+tenant asosida tekshiriladi; yuqoridagi istisnolar sinovdan o‘tadi; barcha saqlangan o‘zgarishlarda sabab/actor va idempotent yoki kompensatsiya qilinadigan natija bor; UI muvaffaqiyat, empty, loading, error, conflict va permission denial holatlarini ko‘rsatadi.

### M29 — Merchant quality, verification and trust data

- **Bosqich/ustuvorlik:** 2 / `MUST` (MUST — bosqich maqsadi uchun; SHOULD — reliz darvozasiga bog‘liq).
- **Nega mavjud:** Xaridor uchun do‘kon ishonchliligi bo‘yicha asosli dalillar yig‘ish.
- **Kim foydalanadi:** Platform Verification, Owner.
- **Biznes maʼlumotlari:** `verification_docs, evidence, decisions, complaint`. Bular ERD emas, data contractga kiradigan domen tushunchalari.
- **Funksiyalar va qamrov:**
  - **01.** merchant business verification
  - **02.** branch ownership proof
  - **03.** trust attributes as evidence
  - **04.** complaint review
  - **05.** fulfillment quality metrics
  - **06.** moderation appeal
  - **07.** display only justified badges
- **Jarayon/holatlar:** `unverified→in_review→verified/rejected/expired`; tegishli to‘liq FSM: `05_STATE_MACHINES_AND_EXCEPTIONS.md`.
- **Bajarilishi shart bo‘lgan qoidalar:**
- `BL-087`: Badges require verified evidence and expiry
- `BL-088`: Complaint, appeal, removal policy; unbiased written reasons
- **Istisno va recovery (har biri test case):**
- fake business document
- false negative complaint
- verification expired
- review manipulation
- **UI sirtlari:**
- Trust center
- Verification queue
- Appeals
- **Hamkor modullar:** `M01`, `M03`, `M16`, `M24`. Bu ro‘yxat logical collaboration, cross-module direct DB access ruxsati emas.
- **O‘lchanadigan natija:** verification coverage, fraud reports.
- **Acceptance minimumi:** barcha asosiy amallar role+tenant asosida tekshiriladi; yuqoridagi istisnolar sinovdan o‘tadi; barcha saqlangan o‘zgarishlarda sabab/actor va idempotent yoki kompensatsiya qilinadigan natija bor; UI muvaffaqiyat, empty, loading, error, conflict va permission denial holatlarini ko‘rsatadi.

### M30 — Partner API va merchant developer access

- **Bosqich/ustuvorlik:** 2 / `MUST` (MUST — bosqich maqsadi uchun; SHOULD — reliz darvozasiga bog‘liq).
- **Nega mavjud:** Yirik merchant/agentlik uchun xavfsiz integratsiya va delegated access.
- **Kim foydalanadi:** Owner, Developer, Platform Admin.
- **Biznes maʼlumotlari:** `client_id, scopes, webhook_secret, quotas`. Bular ERD emas, data contractga kiradigan domen tushunchalari.
- **Funksiyalar va qamrov:**
  - **01.** API key/service account with scopes
  - **02.** webhook subscriptions
  - **03.** idempotency contract
  - **04.** usage and rate dashboards
  - **05.** sandbox environment
  - **06.** key rotation/revoke
  - **07.** mapping troubleshooting
- **Jarayon/holatlar:** `requested→active→limited/revoked`; tegishli to‘liq FSM: `05_STATE_MACHINES_AND_EXCEPTIONS.md`.
- **Bajarilishi shart bo‘lgan qoidalar:**
- `BL-005`: RBAC + scope (merchant, branch, ownership) tekshiriladi
- `BL-074`: Provider-specific cursor, idempotency and rate limits
- `BL-089`: Scoped key, throttle, revoke, service audit
- **Istisno va recovery (har biri test case):**
- leaked key
- cross-tenant integration
- replay webhook
- untrusted third-party app
- **UI sirtlari:**
- Developer settings
- API usage
- Webhook tester
- **Hamkor modullar:** `M02`, `M22`, `M26`. Bu ro‘yxat logical collaboration, cross-module direct DB access ruxsati emas.
- **O‘lchanadigan natija:** API errors, key rotation age.
- **Acceptance minimumi:** barcha asosiy amallar role+tenant asosida tekshiriladi; yuqoridagi istisnolar sinovdan o‘tadi; barcha saqlangan o‘zgarishlarda sabab/actor va idempotent yoki kompensatsiya qilinadigan natija bor; UI muvaffaqiyat, empty, loading, error, conflict va permission denial holatlarini ko‘rsatadi.


---

## STAGE 3 — Global AI Shopping — buyer discovery and comparison

### M31 — Global search and filters

- **Bosqich/ustuvorlik:** 3 / `MUST` (MUST — bosqich maqsadi uchun; SHOULD — reliz darvozasiga bog‘liq).
- **Nega mavjud:** Xaridor ehtiyojiga mos bir xil mahsulotni turli do‘konlardan tez topishi.
- **Kim foydalanadi:** Visitor, Buyer.
- **Biznes maʼlumotlari:** `query, filters, public_product, indexed_offers`. Bular ERD emas, data contractga kiradigan domen tushunchalari.
- **Funksiyalar va qamrov:**
  - **01.** query uz/ru/en/translit
  - **02.** category/brand/condition filters
  - **03.** canonical product result
  - **04.** public offer availability
  - **05.** city/branch filtering
  - **06.** facets and sorting
  - **07.** no-result suggestion
  - **08.** rate limiting
- **Jarayon/holatlar:** `query→results/no_results/degraded`; tegishli to‘liq FSM: `05_STATE_MACHINES_AND_EXCEPTIONS.md`.
- **Bajarilishi shart bo‘lgan qoidalar:**
- `BL-090`: Search only published canonical and opt-in offers
- `BL-091`: Condition/variant discriminators respected
- **Istisno va recovery (har biri test case):**
- query ambiguity
- incorrect product merge
- stale public index
- merchant opt-out
- no geolocation consent
- **UI sirtlari:**
- Global home/search
- Results
- Filters
- No results
- **Hamkor modullar:** `M23`, `M24`, `M28`, `M32`, `M33`. Bu ro‘yxat logical collaboration, cross-module direct DB access ruxsati emas.
- **O‘lchanadigan natija:** search success, query latency.
- **Acceptance minimumi:** barcha asosiy amallar role+tenant asosida tekshiriladi; yuqoridagi istisnolar sinovdan o‘tadi; barcha saqlangan o‘zgarishlarda sabab/actor va idempotent yoki kompensatsiya qilinadigan natija bor; UI muvaffaqiyat, empty, loading, error, conflict va permission denial holatlarini ko‘rsatadi.

### M32 — Cross-store price comparison

- **Bosqich/ustuvorlik:** 3 / `MUST` (MUST — bosqich maqsadi uchun; SHOULD — reliz darvozasiga bog‘liq).
- **Nega mavjud:** Bir mahsulotning barcha ruxsatli, haqiqiy offerlarini adolatli ko‘rsatish.
- **Kim foydalanadi:** Buyer, Visitor.
- **Biznes maʼlumotlari:** `product_id, public_offer_refs, destination, comparison_dimensions`. Bular ERD emas, data contractga kiradigan domen tushunchalari.
- **Funksiyalar va qamrov:**
  - **01.** same variant normalization
  - **02.** item price+delivery total
  - **03.** warranty/condition/stock columns
  - **04.** last verified timestamp
  - **05.** low-to-high/nearest sorting
  - **06.** price history only with real snapshots
  - **07.** report wrong offer
- **Jarayon/holatlar:** `available→stale/excluded; report: new→verified→closed`; tegishli to‘liq FSM: `05_STATE_MACHINES_AND_EXCEPTIONS.md`.
- **Bajarilishi shart bo‘lgan qoidalar:**
- `BL-092`: Show base price, delivery cost if known, currency, warranty, updated_at
- `BL-093`: Total cost used only when comparable and valid
- `BL-094`: Evidence and merchant review, suppress severe false claim
- **Istisno va recovery (har biri test case):**
- comparison variant mismatch
- unavailable shipping quote
- seller manipulated price
- missing warranty
- outdated offer
- **UI sirtlari:**
- Compare table
- Merchant offer card
- Price history
- Report issue
- **Hamkor modullar:** `M23`, `M24`, `M28`, `M33`, `M34`. Bu ro‘yxat logical collaboration, cross-module direct DB access ruxsati emas.
- **O‘lchanadigan natija:** valid comparisons, wrong-price reports.
- **Acceptance minimumi:** barcha asosiy amallar role+tenant asosida tekshiriladi; yuqoridagi istisnolar sinovdan o‘tadi; barcha saqlangan o‘zgarishlarda sabab/actor va idempotent yoki kompensatsiya qilinadigan natija bor; UI muvaffaqiyat, empty, loading, error, conflict va permission denial holatlarini ko‘rsatadi.

### M33 — Geo search, near-me va maps

- **Bosqich/ustuvorlik:** 3 / `MUST` (MUST — bosqich maqsadi uchun; SHOULD — reliz darvozasiga bog‘liq).
- **Nega mavjud:** Mahsulotni qaysi filialdan olish osonroq ekanini tanlash.
- **Kim foydalanadi:** Buyer, Visitor.
- **Biznes maʼlumotlari:** `user_approved_geo, branch_coordinates, pickup_policy`. Bular ERD emas, data contractga kiradigan domen tushunchalari.
- **Funksiyalar va qamrov:**
  - **01.** city and neighborhood query
  - **02.** voluntary precise location
  - **03.** distance from validated branches
  - **04.** pickup availability
  - **05.** working hours
  - **06.** merchant directions link
  - **07.** delivery-zone distinction
- **Jarayon/holatlar:** `unknown→location_allowed/denied; branch pickup: available/unavailable`; tegishli to‘liq FSM: `05_STATE_MACHINES_AND_EXCEPTIONS.md`.
- **Bajarilishi shart bo‘lgan qoidalar:**
- `BL-095`: Request explicit consent for device precise geo; city query without it
- `BL-096`: Straight-line vs provider travel distance clearly labeled
- **Istisno va recovery (har biri test case):**
- precise location denied
- merchant coordinate invalid
- branch closed
- distance vs travel time confused
- **UI sirtlari:**
- Map + list
- Nearby merchants
- Pickup selector
- **Hamkor modullar:** `M03`, `M24`, `M31`, `M32`. Bu ro‘yxat logical collaboration, cross-module direct DB access ruxsati emas.
- **O‘lchanadigan natija:** map-to-store actions.
- **Acceptance minimumi:** barcha asosiy amallar role+tenant asosida tekshiriladi; yuqoridagi istisnolar sinovdan o‘tadi; barcha saqlangan o‘zgarishlarda sabab/actor va idempotent yoki kompensatsiya qilinadigan natija bor; UI muvaffaqiyat, empty, loading, error, conflict va permission denial holatlarini ko‘rsatadi.

### M34 — Global AI Shopping Advisor

- **Bosqich/ustuvorlik:** 3 / `MUST` (MUST — bosqich maqsadi uchun; SHOULD — reliz darvozasiga bog‘liq).
- **Nega mavjud:** Global ommaviy ofertalarni dalil bilan solishtiradigan xaridor agenti.
- **Kim foydalanadi:** Buyer, Global AI.
- **Biznes maʼlumotlari:** `buyer_query, public_offer_evidence, preference, locale`. Bular ERD emas, data contractga kiradigan domen tushunchalari.
- **Funksiyalar va qamrov:**
  - **01.** intent and budget clarifying
  - **02.** tool-based public search
  - **03.** criteria explainability
  - **04.** top candidates with provenance
  - **05.** cross-store comparison
  - **06.** model/variant guardrails
  - **07.** why-not and uncertainty
  - **08.** multilingual answer
  - **09.** no sponsored-as-organic
- **Jarayon/holatlar:** `understanding→searching→comparing→answered/clarify/handoff`; tegishli to‘liq FSM: `05_STATE_MACHINES_AND_EXCEPTIONS.md`.
- **Bajarilishi shart bo‘lgan qoidalar:**
- `BL-097`: Explain input constraints and evidence source; no invented product quality
- `BL-098`: Public index only, no merchant internal data
- `BL-099`: Organic unaffected by paid ads; sponsored clearly separated
- **Istisno va recovery (har biri test case):**
- LLM recommends private SKU
- no evidence for quality
- biased ranking
- phantom cheapest offer
- unsupported price guarantee
- **UI sirtlari:**
- AI search chat
- Evidence drawer
- Compare recommendation
- Feedback
- **Hamkor modullar:** `M23`, `M24`, `M31`, `M32`, `M33`, `M35`. Bu ro‘yxat logical collaboration, cross-module direct DB access ruxsati emas.
- **O‘lchanadigan natija:** grounded ranking %, conversion assist.
- **Acceptance minimumi:** barcha asosiy amallar role+tenant asosida tekshiriladi; yuqoridagi istisnolar sinovdan o‘tadi; barcha saqlangan o‘zgarishlarda sabab/actor va idempotent yoki kompensatsiya qilinadigan natija bor; UI muvaffaqiyat, empty, loading, error, conflict va permission denial holatlarini ko‘rsatadi.

### M35 — Merchant discovery and referral tracking

- **Bosqich/ustuvorlik:** 3 / `MUST` (MUST — bosqich maqsadi uchun; SHOULD — reliz darvozasiga bog‘liq).
- **Nega mavjud:** Global qidiruvdagi xaridorni to‘g‘ri, kuzatiladigan merchant kanali tomon yo‘naltirish.
- **Kim foydalanadi:** Buyer, Merchant, Platform.
- **Biznes maʼlumotlari:** `merchant_id, product_id, referral_id, consent`. Bular ERD emas, data contractga kiradigan domen tushunchalari.
- **Funksiyalar va qamrov:**
  - **01.** merchant profile and offers
  - **02.** click-to-chat/storefront
  - **03.** lead handoff with consent
  - **04.** referral attribution token
  - **05.** merchant acceptance
  - **06.** conversion feedback optional
  - **07.** spam control
- **Jarayon/holatlar:** `created→delivered→acknowledged→converted/lost/expired`; tegishli to‘liq FSM: `05_STATE_MACHINES_AND_EXCEPTIONS.md`.
- **Bajarilishi shart bo‘lgan qoidalar:**
- `BL-100`: Buyer consent and visible destination; tracked referral id
- `BL-101`: Merchant receives only necessary lead data after opt-in
- **Istisno va recovery (har biri test case):**
- merchant ignores referral
- spam repeated lead
- consent absent
- attribution lost across channel
- **UI sirtlari:**
- Merchant page
- Contact CTA
- Lead routing receipt
- **Hamkor modullar:** `M10`, `M12`, `M24`, `M31`, `M34`. Bu ro‘yxat logical collaboration, cross-module direct DB access ruxsati emas.
- **O‘lchanadigan natija:** referral-to-response / sale.
- **Acceptance minimumi:** barcha asosiy amallar role+tenant asosida tekshiriladi; yuqoridagi istisnolar sinovdan o‘tadi; barcha saqlangan o‘zgarishlarda sabab/actor va idempotent yoki kompensatsiya qilinadigan natija bor; UI muvaffaqiyat, empty, loading, error, conflict va permission denial holatlarini ko‘rsatadi.

### M36 — Buyer account, saved products and alerts

- **Bosqich/ustuvorlik:** 3 / `SHOULD` (MUST — bosqich maqsadi uchun; SHOULD — reliz darvozasiga bog‘liq).
- **Nega mavjud:** Xaridor foydali izlanishini davom ettirsin, lekin kuzatuv nazorat ostida bo‘lsin.
- **Kim foydalanadi:** Buyer.
- **Biznes maʼlumotlari:** `account_id, saved_search, alert_threshold, consent`. Bular ERD emas, data contractga kiradigan domen tushunchalari.
- **Funksiyalar va qamrov:**
  - **01.** guest browsing
  - **02.** optional account
  - **03.** saved comparisons and offers
  - **04.** price-drop notification opt-in
  - **05.** availability watch opt-in
  - **06.** privacy/delete/export
  - **07.** unsubscribe
- **Jarayon/holatlar:** `watch: active→triggered/expired/cancelled`; tegishli to‘liq FSM: `05_STATE_MACHINES_AND_EXCEPTIONS.md`.
- **Bajarilishi shart bo‘lgan qoidalar:**
- `BL-102`: Explicit opt-in with one-click unsubscribe
- `BL-103`: Alerts only on fresh verified offer and throttled per user
- **Istisno va recovery (har biri test case):**
- price changed but out of stock
- notification repeated
- buyer unsubscribed
- private data leaked
- **UI sirtlari:**
- Saved items
- Alert preferences
- Account privacy
- **Hamkor modullar:** `M17`, `M31`, `M32`. Bu ro‘yxat logical collaboration, cross-module direct DB access ruxsati emas.
- **O‘lchanadigan natija:** saved-to-return, unsubscribe rate.
- **Acceptance minimumi:** barcha asosiy amallar role+tenant asosida tekshiriladi; yuqoridagi istisnolar sinovdan o‘tadi; barcha saqlangan o‘zgarishlarda sabab/actor va idempotent yoki kompensatsiya qilinadigan natija bor; UI muvaffaqiyat, empty, loading, error, conflict va permission denial holatlarini ko‘rsatadi.

### M37 — Organic vs sponsored ranking and transparency

- **Bosqich/ustuvorlik:** 3 / `SHOULD` (MUST — bosqich maqsadi uchun; SHOULD — reliz darvozasiga bog‘liq).
- **Nega mavjud:** Monetizatsiya imkonini xaridor ishonchidan ajratish.
- **Kim foydalanadi:** Platform Admin, Buyer, Merchant.
- **Biznes maʼlumotlari:** `candidate_offers, sponsored_flag, rank_explanations`. Bular ERD emas, data contractga kiradigan domen tushunchalari.
- **Funksiyalar va qamrov:**
  - **01.** organic ranking relevance rules
  - **02.** sponsored slots only with label
  - **03.** ad targeting boundaries
  - **04.** seller disclosure
  - **05.** bad actor takedown
  - **06.** experiment governance
  - **07.** user report mechanism
- **Jarayon/holatlar:** `eligible→ranked/filtered; ad approved/rejected`; tegishli to‘liq FSM: `05_STATE_MACHINES_AND_EXCEPTIONS.md`.
- **Bajarilishi shart bo‘lgan qoidalar:**
- `BL-104`: Clearly marked and approved; not presented as AI-best
- `BL-105`: Match quality, offer freshness and disclosed scoring criteria
- **Istisno va recovery (har biri test case):**
- seller pays to fake quality
- unverified sponsorship
- biased recommendation
- malicious listings
- **UI sirtlari:**
- Search placements
- Sponsor disclosure
- Ranking explanation
- **Hamkor modullar:** `M24`, `M29`, `M31`, `M32`, `M34`. Bu ro‘yxat logical collaboration, cross-module direct DB access ruxsati emas.
- **O‘lchanadigan natija:** buyer trust signals, complaint rate.
- **Acceptance minimumi:** barcha asosiy amallar role+tenant asosida tekshiriladi; yuqoridagi istisnolar sinovdan o‘tadi; barcha saqlangan o‘zgarishlarda sabab/actor va idempotent yoki kompensatsiya qilinadigan natija bor; UI muvaffaqiyat, empty, loading, error, conflict va permission denial holatlarini ko‘rsatadi.

### M38 — Global content, SEO and shareable landing pages

- **Bosqich/ustuvorlik:** 3 / `SHOULD` (MUST — bosqich maqsadi uchun; SHOULD — reliz darvozasiga bog‘liq).
- **Nega mavjud:** Foydali global product sahifalari qidiruv tizimidan xaridor topa olsin.
- **Kim foydalanadi:** Visitor, Platform Content.
- **Biznes maʼlumotlari:** `canonical_product_id, published_offers, page_metadata`. Bular ERD emas, data contractga kiradigan domen tushunchalari.
- **Funksiyalar va qamrov:**
  - **01.** canonical product public pages
  - **02.** structured product/offer markup when valid
  - **03.** public seller detail
  - **04.** indexation hygiene and canonical URLs
  - **05.** sitemap
  - **06.** content quality review
  - **07.** out-of-stock status transparency
- **Jarayon/holatlar:** `draft→indexable→noindex/retired`; tegishli to‘liq FSM: `05_STATE_MACHINES_AND_EXCEPTIONS.md`.
- **Bajarilishi shart bo‘lgan qoidalar:**
- `BL-106`: Structured data only for currently valid public offers
- `BL-107`: Canonical URL and noindex for thin duplicate states
- **Istisno va recovery (har biri test case):**
- thin duplicate pages
- unverified price markup
- withdrawn public offer remains
- robots blocking
- **UI sirtlari:**
- Product landing
- Merchant landing
- SEO preview
- **Hamkor modullar:** `M23`, `M24`, `M28`, `M31`. Bu ro‘yxat logical collaboration, cross-module direct DB access ruxsati emas.
- **O‘lchanadigan natija:** organic qualified traffic.
- **Acceptance minimumi:** barcha asosiy amallar role+tenant asosida tekshiriladi; yuqoridagi istisnolar sinovdan o‘tadi; barcha saqlangan o‘zgarishlarda sabab/actor va idempotent yoki kompensatsiya qilinadigan natija bor; UI muvaffaqiyat, empty, loading, error, conflict va permission denial holatlarini ko‘rsatadi.

### M39 — Global Telegram bot and discovery API

- **Bosqich/ustuvorlik:** 3 / `SHOULD` (MUST — bosqich maqsadi uchun; SHOULD — reliz darvozasiga bog‘liq).
- **Nega mavjud:** Umumiy qidiruvni shaxsiy merchant botlardan ma’lumot-chegara bilan ajratish.
- **Kim foydalanadi:** Buyer, Global Bot.
- **Biznes maʼlumotlari:** `global_bot_user, search_query, result_token`. Bular ERD emas, data contractga kiradigan domen tushunchalari.
- **Funksiyalar va qamrov:**
  - **01.** global query in Telegram
  - **02.** product results in cards
  - **03.** store price deep-links
  - **04.** saved search opt-in
  - **05.** referral to private merchant bot
  - **06.** conversation privacy
  - **07.** request quotas
- **Jarayon/holatlar:** `idle→searching→results→handoff`; tegishli to‘liq FSM: `05_STATE_MACHINES_AND_EXCEPTIONS.md`.
- **Bajarilishi shart bo‘lgan qoidalar:**
- `BL-098`: Public index only, no merchant internal data
- `BL-100`: Buyer consent and visible destination; tracked referral id
- `BL-108`: Separate bot identity and principal from merchant bot
- **Istisno va recovery (har biri test case):**
- merchant AI leaks private data
- user chat linked across sellers
- telegram restrictions
- expired offer
- **UI sirtlari:**
- Global bot
- Results cards
- Merchant link
- **Hamkor modullar:** `M09`, `M24`, `M31`, `M34`, `M35`. Bu ro‘yxat logical collaboration, cross-module direct DB access ruxsati emas.
- **O‘lchanadigan natija:** bot-to-merchant referrals.
- **Acceptance minimumi:** barcha asosiy amallar role+tenant asosida tekshiriladi; yuqoridagi istisnolar sinovdan o‘tadi; barcha saqlangan o‘zgarishlarda sabab/actor va idempotent yoki kompensatsiya qilinadigan natija bor; UI muvaffaqiyat, empty, loading, error, conflict va permission denial holatlarini ko‘rsatadi.
