# AI Commerce OS & Network — BUSINESS MASTER PACKAGE v1.0

**Sana:** 2026-10-21  
**Status:** `IMPLEMENTATION-ORIENTED BUSINESS SPEC / REVIEW REQUIRED`  
**Loyiha:** Merchant sotuvini avtomatlashtirish → merchant tarmog‘i → xaridor global narx qidiruvi.  
**Bosqichlar:** aniq **3**; agro, full marketplace settlement, xalqaro B2B = **future expansion**, core roadmap emas.

## Nima tayyorlandi?

- **39 biznes modul**: 20 ta Stage 1, 10 ta Stage 2, 9 ta Stage 3; birlamchi funktsiyalar, actor, status, qoidalar, exception, UI, hamkor modul, metrikalar.
- **111 raqamlangan biznes qoida** (`BL-001..BL-111`; BL-109…111 — 2026-10-22 baseline qo'shimchalari) va **18 ta state machine** (FSM-09, FSM-10 Stage 1 da `DEFERRED`).
- **Founder baseline qarorlari:** `../decisions/DECISION_REGISTER.md` — hujjatlar shu qarorlarga moslangan (2026-10-22).
- Rollar/ruxsatlar, business ER model, sotuv va AI user journey, UI navigation, notificationlar, xatolik/recovery, UAT checklist, faza release gate, biznes qarorlar.
- Hujjatlar bir-biriga `Mxx`, `BL-xxx`, `FSM`, `UX`, `UAT` orqali bog‘lanadi.

## Hujjatlar navigatsiyasi

| Tartib | Fayl | Tayyor natija |
|---|---|---|
| 00 | `00_README_AND_SCOPE.md` | Ushbu boshlang‘ich fayl, scope, hujjat siyosati |
| 01 | `01_BUSINESS_VISION_AND_3_PHASES.md` | Product mission, 3 bosqich, kim, qiymat, nima sotamiz |
| 02 | `02_ALL_BUSINESS_MODULES.md` | **39 ta modulning detalli spetsifikatsiyasi** |
| 03 | `03_BUSINESS_RULES_108.md` | **111 ta normativ biznes qoida** (fayl nomi tarixiy), edge-case bilan |
| 04 | `04_ROLES_PERMISSIONS_AND_APPROVALS.md` | Tenant/branch scope, action matrix, sensitive approvals |
| 05 | `05_STATE_MACHINES_AND_EXCEPTIONS.md` | **18 ta FSM**, valid transitions, cancellation/recovery |
| 06 | `06_UI_SITEMAP_AND_USER_FLOWS.md` | Har modul uchun UI coverage, 3 phase wireflow, Mermaid |
| 07 | `07_BUSINESS_ENTITIES_AND_DATA_BOUNDARIES.md` | Mantiqiy entitylari, owner, public/private, invariants |
| 08 | `08_AI_AND_CHANNEL_BUSINESS_CONTRACTS.md` | 3 agent, 3 til voice, merchant/global permissions, integrations |
| 09 | `09_MODULE_INTERACTIONS_AND_NOTIFICATIONS.md` | Modul interaction, outbound notification, event & failure semantics |
| 10 | `10_UAT_ACCEPTANCE_AND_RELEASES.md` | Har modul uchun acceptance + kritikal regression va phase gates |
| 11 | `11_BUSINESS_DECISIONS_ASSUMPTIONS_AND_RISKS.md` | Default qilingan qarorlar, farazlar, kelajakdagi imkoniyatlar |
| 12 | `12_TRACEABILITY_INDEX.md` | Module → BL → FSM → UI → UAT ko‘rsatkichlari |

## Hozirgi ishning yakunlash mezoni

Bu paket **biznes konsepsiya, modullar va ishlash mantig‘ini batafsil spetsifikatsiya qiladi**, ammo rasmiy real merchant ma’lumotlari, do‘kon shartnomalari va live provider API ruxsatlarini o‘rnini bosa olmaydi. `REVIEW REQUIRED` deb belgilangan talablar founder tomonidan tasdiqlanishi kerak. **Backend arxitektura implementatsiyasi, yakuniy ERD/SQL, OpenAPI, ADR va test kodi hali boshqa ish**; bu hujjatlar ularni qurish uchun biznes manba bo‘ladi.

**Oldingi 4 bosqichli vision bilan farqi:** 4-bosqich sifatida ko‘rsatilgan global commerce/logistika/B2B/agro bu yerda `future extensions` ro‘yxatiga o‘tkazildi. U 1–3 bosqichdagi relizlarni og‘irlashtirmaydi.

## Qatʼiy biznes invariants

1. **Merchant o‘z katalogi, mijozlari va sotuv tarixining egasi**; public listing faqat explicit opt-in bilan.
2. **Global catalog ≠ merchant inventory**: canonical product birlashadi, sotuvchining offer/stock/price o‘zgacha saqlanadi.
3. **AI hech qachon o‘zi narx, stock, to‘lov yoki foyda raqamini ixtiro qilmaydi.** Tool va business rule yagona manba.
4. **Chek rasmi paid degani emas.** Paid = tekshirilgan provider settlement yoki vakolatli reconciliation. Stage 1 da to'lov tizimdan tashqarida; "to'landi" — merchant qo'ygan, tekshirilmagan belgi (DEC-100a).
5. **Rezerv ≠ fizik sotuv**; rezervning boshlanishi/tugashi, expired, payment-late yo‘li nazorat qilinadi.
6. **Merchant bot ≠ global buyer bot**; private data hech qachon umumiy qidiruvga yashirin chiqmaydi.
7. Xaridor uchun **jami narx** faqat barcha tarkibiy xarajatlar mavjud bo‘lsa hisoblanadi, aks holda «yetkazish narxi noma’lum».
8. Operator/sotuvchi/AI bir vaqtda bir suhbatga qarama-qarshi javob yubormaydi.
9. Har bir critical mutatsiya uchun actor, tenant, trace/correlation va audit talab qilinadi.
10. Nomuvofiq mahsulot, eskirgan narx, expired payment, noto‘g‘ri role → **blocked + human review**, silent acceptance emas.

## Ishlash tartibi

1. `01` va `02` biznes xususiyatlari uchun asosiy material; `03` yagona qoida manbai.
2. Har bir o‘zgarish uchun `Mxx`/`BL-xxx`ni ko‘rsatish; UI/FSM/UAT taʼsirini birga ko‘rib chiqish.
3. Uch bosqichni bir vaqtda qurmaymiz; Stage 1 ichida mustaqil deploy qilinadigan vertical slicelar bo‘ladi.
4. Keyingi engineering ish: domain context map → aggregate & invariants → ERD → OpenAPI/events → concurrency/outbox/observability → screen implementations → tests.
