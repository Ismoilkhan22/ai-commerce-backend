# M06a — PC moslik engine'i (6-modul, birinchi qadam)

> **Holat:** 2026-10-26, kod va testlar tayyor, commit qilinmagan (founder ko'rib chiqadi).
> **Asos:** [engineering/17](../17-pc-compatibility-engine.md), K-09, BL-027…030, BL-041.
> **Kim o'qiydi:** backend dasturchi, PC mutaxassis, founder (oxirgi bo'lim — qarorlar).

## 1. Nima bitdi — qisqacha

PC yig'masi mosligini tekshiradigan **toza, deterministik engine** yozildi. U DB'ga yozmaydi, vaqt va tasodifga bog'liq emas: bir xil yig'ma — doim bir xil natija. LLM qoidani bajarmaydi; u faqat engine natijasini tushuntiradi (17 §1).

```
Shop SKU'lari ──▶ kutubxonadagi bog'langan spec (tasdiqlangan versiya) ──▶ engine qoidalari
     ──▶ natija: PASS / REVIEW_REQUIRED / BLOCK + har topilma: sabab, faktlar, dalil (spec versiyasi), tuzatish taklifi
```

- **Noma'lum ≠ mos.** Kerakli atribut yo'q bo'lsa — `MISSING_ATTRIBUTE` (REVIEW_REQUIRED), hech qachon PASS emas.
- **Bog'lanmagan SKU** — `UNLINKED_PART` (REVIEW_REQUIRED); unga tegishli qoidalar bajarilmaydi, ortiqcha "noma'lum" shovqini yo'q.
- **Qoidalar to'plami versiyalangan:** `pc-2026-10-v1`. Taklif (quote) yozilganda shu versiya saqlanadi (BL-030).
- **6-modul uchun kirish nuqtasi:** `CatalogQueryPort.check_compatibility(db, shop_id, lines, locale, full_build=…)` — `sales_ai` tool'i va `commerce/quotes` shu orqali chaqiradi, `catalog` kodini import qilmaydi (ADR-032).

## 2. Rejadagi bandlar

- [x] Engine: model, qoidalar reyestri, yig'uvchi (`check`)
- [x] 17 §6 dagi barcha qoidalar (to'liqlik, moslik, quvvat, ogohlantirishlar)
- [x] Quvvat hisobi va tavsiya qilinadigan quvvat bloki
- [x] Har topilma uchun xabar kaliti va uz/ru/en matnlari, tuzatish taklifi (ma'lumot + matn)
- [x] SKU → spec yuklovchi xizmat va port metodi
- [x] Unit testlar (har qoida), real yig'malar, xossa testlari (hypothesis), integratsiya testi
- **Ataylab keyinga:**
  - `catalog.pc_rulesets` va `build_profiles` jadvallari, ruleset'ni aktivlashtirish — 6-modulning keyingi qadamida (dizayn agenti hujjatida). Hozir versiya kodda: `RULESET_VERSION`.
  - Yig'ma tavsiya qilish (`suggest_builds`, 17 §8) — AI tool'lari bilan birga (6b).
  - NVMe avlodi (PCIe Gen) tekshiruvi — kutubxona sxemasida bunday atribut yo'q; kerak bo'lsa avval atribut qo'shiladi.
  - Shop panelidagi "PC yig'ish" sahifasi va `POST /shop/pc-builds/check` — frontend bilan birga.

## 3. Fayllar xaritasi

```
app/shared/contracts/compatibility.py      natija turlari: BuildLine, Finding, Evidence, CompatibilityResult
app/shared/contracts/catalog.py            CatalogQueryPort.check_compatibility (yangi metod)
app/domains/catalog/compatibility/
├── __init__.py                            ommaviy API: check, Build, Part, RULESET_VERSION, quvvat yordamchilari
├── model.py                               Part, Build, chegaralar (75 W, ×1.3), BIOS versiyasini solishtirish
├── registry.py                            @rule dekoratori, Outcome, Missing
├── power.py                               taxminiy iste'mol, zaxira maqsadi, tavsiya qilinadigan blok
├── engine.py                              qoidalarni qo'llash, MISSING'ni yig'ish, natija, tarjima
├── service.py                             shop SKU'lari → spec'lar → engine (6-modul integratsiya nuqtasi)
└── rules/
    ├── completeness.py                    REQUIRED_PARTS, DISPLAY_OUTPUT, CPU_COOLER_PRESENT, DUPLICATE_PART, UNLINKED_PART
    ├── fit.py                             soket, BIOS, RAM, korpus, cooler, quvvat bloki joyi, disklar
    ├── power.py                           PSU_WATTAGE, PSU_HEADROOM, PSU_GPU_CONNECTORS, COOLER_TDP
    └── advisory.py                        RAM_SPEED, SINGLE_CHANNEL, MIXED_RAM_KITS, NO_UPGRADE_SLOT
app/domains/catalog/query_port.py          check_compatibility → service.check_skus
app/shared/i18n/locales/{uz,ru,en}.yml     compat.categories, compat.rules, compat.hints
tests/unit/test_compat_engine.py           31 test: har qoida, real yig'malar, xossalar
tests/integration/test_compat_service.py   1 test: haqiqiy DB, avtomatik bog'langan SKU'lar orqali
```

## 4. Qaysi faylda nima bor

### 4.1 `model.py`

- **`Part`** — yig'madagi qism: toifa, spec atributlari (o'zgartirilmagan), soni, SKU, spec id va versiyasi, manba havolasi, model nomi. O'zligi bo'yicha solishtiriladi: bir xil ikkita SSD qatori — ikki qism.
- **`Build`** — qismlar va `full_build` belgisi. Xaridor faqat qism so'rasa (`full_build=False`), to'liqlik qoidalari (REQUIRED_PARTS, DISPLAY_OUTPUT, CPU_COOLER_PRESENT) qo'llanmaydi (17 §6.1).
- **`version_key`** — BIOS versiyalarini "tabiiy" tartibda solishtiradi: F9 < F20, 1.9 < 1.10, 7D78v9 < 7D78v10.

### 4.2 `registry.py` va `engine.py`

- Har qoida — `@rule(id, severity, requires=…, full_build_only=…)` bilan ro'yxatdan o'tgan toza funksiya.
- **`requires`** dagi atribut noma'lum bo'lsa qoida bajarilmaydi va `MISSING_ATTRIBUTE` qo'yiladi. Shartli atributlar (cooler turi AIR/AIO, disk turi) qoida ichida `Missing` bilan qaytariladi.
- Bitta atribut bir nechta qoidaga kerak bo'lsa — **bitta** topilma, `facts.rules` da qaysi qoidalar to'xtagani ro'yxati.
- Kerakli toifa yig'mada yo'q yoki qism bog'lanmagan — qoida qo'llanmaydi.
- **Yig'ish (K-09):** birorta BLOCK → BLOCK; aks holda birorta REVIEW_REQUIRED → REVIEW_REQUIRED; aks holda PASS. `can_publish_quote` faqat PASS'da.
- **Matn:** `compat.rules.<ID>[.<sabab>]` kaliti so'ralgan tilda; toifa kodlari matnda toifa nomiga aylanadi ("корпус", "quvvat bloki").

### 4.3 Qoidalar va darajasi

**To'liqlik (17 §6.1):**
- `REQUIRED_PARTS` — BLOCK: CPU, ona plata, RAM, disk, PSU, korpus bo'lishi kerak (faqat to'liq yig'mada).
- `DISPLAY_OUTPUT` — BLOCK: GPU yo'q va protsessorda o'rnatilgan grafika yo'q.
- `CPU_COOLER_PRESENT` — BLOCK: cooler yo'q va protsessor coolersiz sotiladi.
- `DUPLICATE_PART` — BLOCK: ikkita CPU, ona plata, PSU, korpus yoki cooler.
- `UNLINKED_PART` — REVIEW_REQUIRED: SKU kutubxonaga bog'lanmagan.

**Moslik (17 §6.2):**
- `CPU_MB_SOCKET` — BLOCK.
- `BIOS_SUPPORT` — REVIEW_REQUIRED, uch sabab: ro'yxatda yo'q / platadagi BIOS noma'lum / yangilash kerak. Soket mos kelmasa so'ralmaydi (BLOCK baribir bor).
- `RAM_TYPE_MB`, `RAM_TYPE_CPU`, `RAM_FORM_FACTOR`, `RAM_SLOTS`, `RAM_CAPACITY` — BLOCK.
- `MB_CASE_FORM_FACTOR`, `GPU_CASE_LENGTH` — BLOCK.
- `COOLER_SOCKET`, `COOLER_HEIGHT_CASE` (AIR), `AIO_RADIATOR_CASE` (AIO) — BLOCK.
- `PSU_CASE_FORM_FACTOR` — katta blok kichik joyga: BLOCK; kichik blok katta joyga (SFX → ATX): adapter bilan, REVIEW_REQUIRED.
- `PSU_CASE_LENGTH` — WARNING.
- `STORAGE_M2_SLOTS`, `STORAGE_SATA_PORTS` — BLOCK. M.2 SATA disk SATA portni emas, M.2 slotni egallaydi. Turi aniqlanmasa (faqat "SATA" interfeysi, form-faktor yo'q) — `MISSING_ATTRIBUTE`.

**Quvvat (17 §6.3):**
- Taxminiy iste'mol = CPU `max_power_w` + har GPU `board_power_w` + 75 W.
- `PSU_WATTAGE` — BLOCK: blok iste'moldan kichik. Taklif: "kamida N W" (50 W ga yaxlitlangan).
- `PSU_HEADROOM` — REVIEW_REQUIRED: blok iste'molga yetadi, lekin `max(GPU tavsiyasi, iste'mol × 1.3)` dan kichik. Taklif: tavsiya qilinadigan quvvat.
- `PSU_GPU_CONNECTORS` — ulagich yetmasa BLOCK; 16-pin (12VHPWR / 12V-2x6) yo'q, lekin yetarli 8-pin bor — adapter bilan, REVIEW_REQUIRED. 8-pin (6+2) 6-pin o'rnida ishlaydi.
- `COOLER_TDP` — WARNING.

**Ogohlantirishlar (17 §6.4):** `RAM_SPEED`, `SINGLE_CHANNEL`, `MIXED_RAM_KITS` — WARNING; `NO_UPGRADE_SLOT` — INFO. Natijaga ta'sir qilmaydi.

### 4.4 `power.py`

- `estimate_power_w(build)` — CPU va hamma GPU quvvati ma'lum bo'lsagina son, aks holda `None` (hech qachon 0 emas).
- `recommended_psu_w(build)` — xaridorga aytiladigan blok: zaxira bilan, 50 W ga yaxlitlangan. GPU tavsiyasi noma'lum bo'lsa — `None`.
- Ikkalasi natijada ham qaytadi (`estimated_power_w`, `recommended_psu_w`) — AI va interfeys "kamida 650 W" deb aytishi uchun.

### 4.5 `service.py` — 6-modul integratsiya nuqtasi

- Shop SKU'lari → mahsulot toifasi → bog'langan spec (`APPROVED` yoki `RETIRED`; DRAFT spec bog'lanmagan hisoblanadi).
- PC qismi bo'lmagan toifa (monitor, sichqoncha) — tekshirilmaydi, `ignored_sku_ids` da qaytadi.
- Boshqa shopning yoki yo'q SKU — `ValidationError`, maydon `lines[i].sku_id`.
- Faqat o'qiydi; RLS shop konteksti chaqiruvchining tranzaksiyasidan.

## 5. Testlar

- **Unit — 31 ta** (`tests/unit/test_compat_engine.py`):
  - har qoida: mos, mos emas, noma'lum;
  - real yig'malar: Ryzen 5 7600 + B650 + DDR5 + RTX 4060 + 550 W → PASS; i5-12400F + B660 DDR4 + RTX 4060 → PASS; RTX 4070 Super + 550 W (faqat 8-pin) → REVIEW (zaxira kam + adapter); RTX 4070 Super + 650 W 16-pin → PASS; 350 W → BLOCK "kamida 450 W"; mATX plata ITX korpusda → BLOCK; DDR4 xotira DDR5 platada → BLOCK;
  - matnlar uch tilda, dalil (spec versiyasi), bitta "noma'lum" topilmasi bir nechta qoida uchun;
  - xossalar (hypothesis, 700 ta tasodifiy yig'ma): natija deterministik; atributni olib tashlash muammoli natijani hech qachon PASS ga aylantirmaydi (17 §12).
- **Integratsiya — 1 ta** (`tests/integration/test_compat_service.py`): platformada ikki ko'z bilan tasdiqlangan 7 ta spec, shop SKU'lari avtomatik bog'lanadi, port orqali PASS; monitor e'tiborsiz; bog'lanmagan GPU → REVIEW (ruscha matn); 3 ta M.2 disk → BLOCK; boshqa shop SKU'si → xato.

## 6. Jarayonda topilgan muammolar

- `Part` dastlab qiymat bo'yicha solishtirilardi (frozen dataclass), ichidagi `dict` tufayli xeshlanmasdi. O'zlik bo'yicha solishtirishga o'tkazildi — bir xil ikkita qator alohida qism bo'lib qoladi.

## 7. Keyingi modulga meros

- `commerce/quotes` taklif versiyasini yozganda `check_compatibility` natijasini to'liq saqlaydi (`rule_set_version`, `spec_versions`, topilmalar) — engine o'zi saqlamaydi.
- `sales_ai` tool'i natijani o'zgartirmasdan tushuntiradi: `explanation` va `hint_text` tayyor matn, `facts` va `hint` — ma'lumot.
- Yangi qoida qo'shish: `rules/` da `@rule`, `compat.rules.<ID>` matni uch tilda, unit test; chegara o'zgarsa — `RULESET_VERSION` yangilanadi.

## 8. Founder ko'rib chiqishi uchun qarorlar

1. **Natija nomlari** — topshiriqda OK / WARNING / INCOMPATIBLE / UNKNOWN deyilgan edi; tasdiqlangan konvensiya K-09 va 17 §3 bo'yicha **PASS / REVIEW_REQUIRED / BLOCK** ishlatildi (WARNING va INFO — alohida, natijaga ta'sir qilmaydi). Muqobil: yangi nomlar — konvensiyani o'zgartirish kerak bo'lardi.
2. **Quvvat chegaralari** — hujjatdagidek: iste'mol = CPU max + GPU + **75 W**, zaxira **×1.3** yoki GPU ishlab chiqaruvchisi tavsiyasi (qaysi katta). Tavsiya 50 W ga yaxlitlanadi. Pilotda PC mutaxassis bilan qayta ko'riladi; o'zgarsa yangi `rule_set_version`.
3. **GPU tavsiyasi noma'lum bo'lsa** — `PSU_HEADROOM` "noma'lum" (REVIEW) beradi, faqat ×1.3 bilan "yetarli" deb o'tkazilmaydi. Sabab: "noma'lum ≠ mos" va xossa testi (ma'lumot kamaysa natija yaxshilanmasligi kerak). Muqobil: ×1.3 bilan kifoyalanish — ko'proq yig'ma PASS bo'ladi, lekin xavfliroq.
4. **Adapter holatlari** — 16-pin ulagich 8-pin'lardan adapter bilan (kamida 2 ta bo'sh 8-pin) va SFX blok ATX korpusda — **REVIEW_REQUIRED** (hujjatdagidek). 17 §13 ochiq savoli: shop siyosati qilinsinmi — hozir yo'q.
5. **BIOS ro'yxati bo'lmasa** — kutubxonada `cpu_support` kiritilmagan ona plata uchun `MISSING_ATTRIBUTE` (REVIEW). Bu ko'p yig'malarni REVIEW ga tushiradi, toki kutubxona to'ldirilmaguncha. Muqobil: ro'yxat yo'q bo'lsa qoidani o'tkazib yuborish — 17 §6.2 ga zid.
6. **DUPLICATE_PART** — hujjatdagi CPU, ona plata, PSU ga **korpus va cooler** qo'shildi (bitta yig'mada ikkitasi ma'nosiz).
7. **WARNING/INFO qoidalari uchun ma'lumot yo'q** — topilma chiqarilmaydi (natijaga baribir ta'sir qilmaydi, shovqin kamayadi).
8. **RETIRED spec** — eski bog'lanishlar saqlanadi (M02), shuning uchun tekshiruvda ishlatiladi. DRAFT spec — bog'lanmagan hisoblanadi.
9. **NVMe avlodi** — kutubxona sxemasida atribut yo'q, shuning uchun tekshirilmaydi.

---

## 9. QA tekshiruvi va tuzatishlar (2026-10-26)

- **F2 (jiddiy) — bog'lanmagan qism ma'lum BLOCK'ni yashirardi.** Avval kerakli toifada birorta bog'lanmagan qism bo'lsa qoida umuman ishlamas edi: DDR4 plata + DDR5 RAM + bog'lanmagan RAM → REVIEW (BLOCK yo'qolardi). Endi `_applicable` qaror qoidalarini (BLOCK/REVIEW) **bog'langan qismlarda** ishlatadi — bog'lanmagan qism faqat ehtiyojni oshiradi (modul, disk, quvvat), shuning uchun bog'langanlarda topilgan BLOCK haqiqiy. Noma'lum qism `UNLINKED_PART` (REVIEW) bilan belgilanadi. WARNING/INFO qoidalar bunday holatda o'tkaziladi (yolg'on ogohlantirish bo'lmasin). Toifada birorta bog'langan qism yo'q bo'lsa — qoida qo'llanmaydi.
- **Quvvat** — `PSU_WATTAGE` bog'lanmagan GPU bo'lsa ham bog'langan qismlar bo'yicha pastki chegarani tekshiradi (`_known_draw_floor`): bog'langanlarning o'zi sig'masa — BLOCK.
- **Versiya** — `RULESET_VERSION = "pc-2026-10-v2"` (17 §6.4: xatti-harakat o'zgardi).
- **F19** — `PSU_GPU_CONNECTORS` adapter (REVIEW) topilmasiga maslahat: `PSU_NATIVE_16PIN` (uz/ru/en).
- **F3** — matn yasash `app/shared/compat_text.py` ga ko'chdi (`render_explanation`, `render_hint`) — engine va muzlagan taklif snapshot'lari bir xil funksiyadan foydalanadi; snapshot'da kalit + faktlar, matn o'qishda so'rov tilida.
- **Testlar** — 4 ta yangi: bog'lanmagan qo'shni qism BLOCK'ni yashirmaydi (RAM turi, M.2 slotlar, RAM slotlar), faqat bog'lanmagan toifa — REVIEW, adapter maslahati, xossa testi "mavjud toifaga bog'lanmagan qism qo'shish qarorni hech qachon yengillashtirmaydi va BLOCK qoidalarini olib tashlamaydi" (400 misol).
