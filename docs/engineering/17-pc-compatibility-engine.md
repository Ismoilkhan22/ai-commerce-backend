# 17 — PC moslik engine va texnik ma'lumotlar kutubxonasi

> **Versiya:** v2 (2026-10-22). Eski `25_PC_COMPATIBILITY_ENGINE` o'rnini bosadi.
> **Domen:** `catalog` → `pc_specs` (kutubxona, SKU bog'lash) va `compatibility` (engine, qoidalar) sub-modullari (M08).
> **Qarorlar:** DEC-011 (platforma kutubxonasi), DEC-120 (kim yuritadi), ADR-028, K-09. **Qoidalar:** BL-027…030, BL-041.
> **Kim o'qiydi:** backend dasturchi va PC mutaxassis. Chegaralar (PSU zaxirasi va h.k.) pilotda mutaxassis bilan qayta ko'riladi.

## 1. Muammo va yechim

**Muammo:** xaridor "10 mln ga CS2 uchun PC" so'raydi. Agar protsessor va ona plata soketi mos kelmasa yoki quvvat bloki yetmasa — xaridor ishlamaydigan kompyuter oladi, shop pul va obro' yo'qotadi. Shopning Excel faylida soket, RAM turi, GPU uzunligi kabi ma'lumotlar odatda yo'q. LLM bu ma'lumotlarni "taxmin qilsa" — xavfli.

**Yechim:**
1. **Platforma yuritadigan texnik ma'lumotlar kutubxonasi** (`reference_hardware_specs`) — rasmiy manbalardan, versiyalangan.
2. Shop SKU'si kutubxonadagi modelga **bog'lanadi** — shop spec kiritmaydi.
3. **Deterministik qoidalar engine'i** — toza Python funksiyalari. LLM qoidani bajarmaydi va natijani o'zgartirmaydi, faqat tushuntiradi.
4. **Noma'lum ≠ mos:** kerakli atribut yo'q bo'lsa — `REVIEW_REQUIRED`, hech qachon `PASS`.

---

## 2. Printsiplar

1. **Deterministik.** Natija faqat kod va ma'lumotdan (BL-027, BL-041).
2. **Noma'lum ≠ mos** (BL-028).
3. **Versiyalangan.** Har natija `rule_set_version` va ishlatilgan spec versiyalari bilan (BL-030).
4. **Dalil bilan.** Har finding qaysi atribut va qaysi manbadan chiqqanini ko'rsatadi.
5. **Spec'lar platformaniki.** Shop spec'ni tahrirlay olmaydi; faqat SKU'sini bog'laydi yoki yangi model so'raydi (DEC-120).
6. **Engine toza (pure).** `check()` DB'ga yozmaydi — natijani chaqiruvchi o'z domenida saqlaydi (§7).

## 3. Natija qiymatlari (K-09)

| Qiymat | Ma'nosi | Taklif yuborish mumkinmi |
|---|---|---|
| `PASS` | Barcha `BLOCK` va `REVIEW_REQUIRED` qoidalari o'tdi (`WARNING` bo'lishi mumkin) | Ha |
| `REVIEW_REQUIRED` | Ma'lumot yetmadi yoki shartli holat | Faqat menejer/ega dalil bilan tasdiqlasa (FSM-06) |
| `BLOCK` | Kamida bitta qoida aniq buzilgan | Yo'q (`RULE_BLOCK`) |

**Yig'ish:** birorta `BLOCK` → `BLOCK`; aks holda birorta `REVIEW_REQUIRED` → `REVIEW_REQUIRED`; aks holda `PASS`. `WARNING`/`INFO` natijaga ta'sir qilmaydi, lekin ko'rsatiladi.

---

## 4. Ma'lumot modeli (`catalog` schemasi)

### 4.1 Kategoriyalar va atributlar

O'lchamlar mm, quvvat W, sig'im GB. Atributlar `attributes jsonb` da, har kategoriya uchun Pydantic sxemasi bilan validatsiya. **Yo'q atribut — noma'lum** (0 yoki bo'sh qator emas).

| Kategoriya | Atribut | Turi | Qoidalar |
|---|---|---|---|
| `CPU` | `socket` | enum: `AM4`, `AM5`, `LGA1200`, `LGA1700`, `LGA1851` … | CPU_MB_SOCKET, COOLER_SOCKET |
| | `memory_types` | list: `DDR4`, `DDR5` | RAM_TYPE_CPU |
| | `base_power_w`, `max_power_w` | int | PSU_WATTAGE, COOLER_TDP |
| | `integrated_graphics`, `cooler_included` | bool | DISPLAY_OUTPUT, CPU_COOLER_PRESENT |
| `MOTHERBOARD` | `socket`, `chipset` | enum, str | CPU_MB_SOCKET |
| | `form_factor` | enum: `E_ATX`, `ATX`, `MICRO_ATX`, `MINI_ITX` | MB_CASE_FORM_FACTOR |
| | `memory_type`, `memory_slots`, `max_memory_gb`, `max_memory_speed_mts` | enum, int | RAM_* |
| | `m2_slots`, `sata_ports` | int | STORAGE_* |
| | `cpu_support` (`{cpu_model, min_bios}`), `shipped_bios` | list, str | BIOS_SUPPORT |
| `RAM` | `type`, `form_factor` (`DIMM`, `SO_DIMM`) | enum | RAM_TYPE_*, RAM_FORM_FACTOR |
| | `module_count`, `capacity_per_module_gb`, `speed_mts` | int | RAM_SLOTS, RAM_CAPACITY, RAM_SPEED, SINGLE_CHANNEL |
| `GPU` | `length_mm`, `slot_width` | int, float | GPU_CASE_LENGTH |
| | `board_power_w`, `recommended_psu_w` | int | PSU_WATTAGE, PSU_HEADROOM |
| | `power_connectors` (`{type: PCIE_6PIN \| PCIE_8PIN \| 12VHPWR \| 12V_2X6, count}`) | list | PSU_GPU_CONNECTORS |
| `PSU` | `wattage_w`, `form_factor` (`ATX`, `SFX`, `SFX_L`), `connectors`, `length_mm` | int, enum | PSU_* |
| `CASE` | `supported_mb_form_factors`, `max_gpu_length_mm`, `max_cpu_cooler_height_mm`, `max_psu_length_mm`, `psu_form_factor`, `radiator_support_mm` | list, int | MB_CASE_*, GPU_CASE_*, COOLER_HEIGHT_CASE, PSU_CASE_*, AIO_RADIATOR_CASE |
| `CPU_COOLER` | `type` (`AIR`, `AIO`), `supported_sockets`, `height_mm`, `radiator_mm`, `tdp_rating_w` | enum, list, int | COOLER_* |
| `STORAGE` | `interface` (`NVME`, `SATA`), `form_factor` (`M2_2280`, `M2_2242`, `SATA_2_5`, `SATA_3_5`) | enum | STORAGE_* |

Stage 1 dan tashqarida: noutbuklar va tayyor yig'ilgan PC'lar — oddiy mahsulot, tekshiruvsiz. Monitor va periferiya — tekshiruvsiz.

### 4.2 Jadvallar

| Jadval | `shop_id` | Egasi | Izoh |
|---|---|---|---|
| `catalog.reference_hardware_specs` | yo'q (global) | Platforma | `id, category, brand, model_name, mpn_normalized, variant_key, attributes jsonb, source_url, version, status (DRAFT/APPROVED/RETIRED), approved_by` |
| `catalog.reference_hardware_spec_versions` | yo'q | Platforma | Har o'zgarishning to'liq nusxasi |
| `catalog.sku_spec_links` | ✅ | Shop | `(shop_id, sku_id) → spec_id`, `linked_by (AUTO_MPN \| AUTO_MODEL \| MANUAL)`, `linked_at`; RLS |
| `catalog.spec_requests` | ✅ | Shop → platforma | "Yangi model so'rovi" navbati |
| `catalog.pc_rulesets` | yo'q | Platforma | `version ('pc-2026-10-v1'), code_ref, activated_at, activated_by, notes` |
| `catalog.build_profiles` | yo'q | Platforma | Ish turi bo'yicha byudjet taqsimoti (§8) |

Global jadvallar (`shop_id` yo'q) faqat `platform` surface orqali yoziladi; shop surface ularni faqat o'qiydi.

---

## 5. SKU'ni spec'ga bog'lash

| Bosqich | Usul | `linked_by` |
|---|---|---|
| 1 | MPN aniq mos (normallashtirilgan: katta harf, bo'shliq va chiziqchasiz) | `AUTO_MPN` |
| 2 | Brend + model normallashtirilgan nomi aniq mos (`Ti`, `SUPER`, `OC`, xotira hajmi hisobga olinadi) | `AUTO_MODEL` |
| 3 | Bir nechta nomzod — avtomatik bog'lanmaydi; shop ro'yxatdan tanlaydi | `MANUAL` |
| — | Topilmadi — shop "yangi model so'rovi" yuboradi; SKU bog'lanmagan | — |

**Taqiqlar:** `RTX 5060` ↔ `RTX 5060 Ti`, `8GB` ↔ `16GB`, `DDR4` ↔ `DDR5` hech qachon avtomatik birlashtirilmaydi. Bog'lanmagan SKU yig'mada → `UNLINKED_PART` (REVIEW_REQUIRED). Katalog importi bog'lashni avtomatik bajaradi va natijani import hisobotida ko'rsatadi (`18`).

---

## 6. Qoidalar katalogi (`pc-2026-10-v1`)

Qoidalar — Python'da toza funksiyalar (YAML DSL emas: type-check, test, refactor oson), metadata bilan ro'yxatdan o'tadi:

```python
# app/domains/catalog/compatibility/rules/socket.py
@rule(
    id="CPU_MB_SOCKET", severity=Severity.BLOCK,
    requires={"CPU": ["socket"], "MOTHERBOARD": ["socket"]},
    explain={
        "uz": "Protsessor soketi ({cpu_socket}) ona plata soketiga ({mb_socket}) mos emas.",
        "ru": "Сокет процессора ({cpu_socket}) не совпадает с сокетом материнской платы ({mb_socket}).",
        "en": "CPU socket ({cpu_socket}) does not match motherboard socket ({mb_socket}).",
    },
)
def cpu_mb_socket(b: Build) -> Outcome:
    return Outcome.ok() if b.cpu.socket == b.mb.socket else Outcome.fail(
        cpu_socket=b.cpu.socket, mb_socket=b.mb.socket)
```

`requires` dagi atributlardan biri noma'lum bo'lsa — qoida bajarilmaydi, `MISSING_ATTRIBUTE` (REVIEW_REQUIRED) qo'yiladi.

### 6.1 To'liqlik

| ID | Severity | Tekshiruv |
|---|---|---|
| `REQUIRED_PARTS` | BLOCK | CPU, MOTHERBOARD, RAM, STORAGE (≥1), PSU, CASE bor (xaridor faqat qism so'rasa — tekshiruv qo'llanmaydi) |
| `DISPLAY_OUTPUT` | BLOCK | GPU yo'q va `cpu.integrated_graphics = false` |
| `CPU_COOLER_PRESENT` | BLOCK | Cooler yo'q va `cpu.cooler_included = false` |
| `DUPLICATE_PART` | BLOCK | Ikkita CPU, ona plata yoki PSU |
| `UNLINKED_PART` | REVIEW_REQUIRED | Kamida bitta SKU spec'ga bog'lanmagan |

### 6.2 Moslik

| ID | Severity | Tekshiruv |
|---|---|---|
| `CPU_MB_SOCKET` | BLOCK | `cpu.socket == mb.socket` |
| `BIOS_SUPPORT` | REVIEW_REQUIRED | CPU `mb.cpu_support` da va `min_bios <= shipped_bios`; aks holda yoki noma'lum — REVIEW |
| `RAM_TYPE_MB` | BLOCK | `ram.type == mb.memory_type` |
| `RAM_TYPE_CPU` | BLOCK | `ram.type in cpu.memory_types` |
| `RAM_FORM_FACTOR` | BLOCK | `ram.form_factor == DIMM` |
| `RAM_SLOTS` | BLOCK | Jami modullar `<= mb.memory_slots` |
| `RAM_CAPACITY` | BLOCK | Jami GB `<= mb.max_memory_gb` |
| `MB_CASE_FORM_FACTOR` | BLOCK | `mb.form_factor in case.supported_mb_form_factors` |
| `GPU_CASE_LENGTH` | BLOCK | `gpu.length_mm <= case.max_gpu_length_mm` |
| `COOLER_SOCKET` | BLOCK | `cpu.socket in cooler.supported_sockets` |
| `COOLER_HEIGHT_CASE` | BLOCK | AIR: `cooler.height_mm <= case.max_cpu_cooler_height_mm` |
| `AIO_RADIATOR_CASE` | BLOCK | AIO: `cooler.radiator_mm in case.radiator_support_mm` |
| `PSU_CASE_FORM_FACTOR` | BLOCK / REVIEW | Mos; `SFX` + `ATX` korpus (adapter bilan) — REVIEW |
| `PSU_CASE_LENGTH` | WARNING | `psu.length_mm <= case.max_psu_length_mm` |
| `STORAGE_M2_SLOTS` | BLOCK | M.2 disklar `<= mb.m2_slots` |
| `STORAGE_SATA_PORTS` | BLOCK | SATA disklar `<= mb.sata_ports` |

### 6.3 Quvvat

**Taxminiy iste'mol** = `cpu.max_power_w` + `gpu.board_power_w` + 75 W.

| ID | Severity | Tekshiruv |
|---|---|---|
| `PSU_WATTAGE` | BLOCK | `psu.wattage_w >= taxminiy iste'mol` |
| `PSU_HEADROOM` | REVIEW_REQUIRED | `psu.wattage_w >= max(gpu.recommended_psu_w, iste'mol × 1.3)` |
| `PSU_GPU_CONNECTORS` | BLOCK / REVIEW | Kerakli konnektorlar bor; faqat adapter bilan — REVIEW |
| `COOLER_TDP` | WARNING | `cooler.tdp_rating_w >= cpu.base_power_w` |

### 6.4 Ogohlantirishlar

| ID | Severity | Tekshiruv |
|---|---|---|
| `RAM_SPEED` | WARNING | `ram.speed_mts > mb.max_memory_speed_mts` |
| `SINGLE_CHANNEL` | WARNING | Bitta RAM moduli |
| `MIXED_RAM_KITS` | WARNING | Turli modelli RAM |
| `NO_UPGRADE_SLOT` | INFO | Barcha RAM slotlari band |

Chegaralar (75 W, ×1.3) — boshlang'ich; o'zgarishi yangi `rule_set_version`.

---

## 7. Kirish/chiqish kontrakti va kim ishlatadi

**Query Port** (`app/shared/contracts/catalog.py`):
```python
class CatalogQueryPort(Protocol):
    async def check_compatibility(self, shop_id: UUID, lines: list[BuildLine],
                                  locale: Locale, rule_set_version: str | None = None) -> CompatibilityResult: ...
    async def suggest_builds(self, shop_id: UUID, req: BuildRequirements,
                             locale: Locale) -> list[BuildProposal]: ...
```

**Chiqish (`CompatibilityResult`):**
```json
{
  "rule_set_version": "pc-2026-10-v1",
  "decision": "REVIEW_REQUIRED",
  "can_publish_quote": false,
  "checked_sku_ids": ["…"],
  "findings": [
    {
      "rule_id": "BIOS_SUPPORT",
      "severity": "REVIEW_REQUIRED",
      "explanation": "Ona plata ushbu protsessor uchun BIOS yangilashni talab qilishi mumkin.",
      "facts": {"cpu_model": "Ryzen 7 9700X", "min_bios": "F20", "shipped_bios": null},
      "evidence": [{"spec_id": "…", "version": 2, "source_url": "https://…"}]
    }
  ],
  "estimated_power_w": 425,
  "spec_versions": {"<sku_id>": {"spec_id": "…", "version": 2}}
}
```

`explanation` — backend `locale` bo'yicha qoida shablonidan (`11` i18n). AI uni ma'nosini o'zgartirmasdan aytadi.

Panelda `locale` — interfeys tili (`Accept-Language`, `get_display_locale`; QA 6a F3). Muzlagan natijada matn emas, `message_key` + `facts` saqlanadi va o'qishda qayta yasaladi (`app/shared/compat_text.py`). Bog'lanmagan qism bo'lsa ham qaror qoidalari bog'langan qismlarda ishlaydi — ma'lum BLOCK yashirinmaydi (`pc-2026-10-v2`, QA 6a F2).

| Kim | Qanday | Natija qayerda saqlanadi |
|---|---|---|
| `sales_ai` (`catalog.check_compatibility` tool) | Query Port | `sales_ai.ai_tool_executions` (hash) — faqat log |
| `commerce/quotes` (taklif yaratish, tasdiqlash, buyurtma tasdig'i) | Query Port | `commerce.quote_compatibility_snapshots` — taklif revision'iga bog'langan to'liq nusxa (BL-030) |
| Shop paneli (PC yig'ish sahifasi) | `POST /api/v1/shop/pc-builds/check` (catalog router) | Saqlanmaydi |

Engine o'zi DB'ga yozmaydi — snapshot egasi `commerce` (ADR-032: invariant ichkarida, boshqa domen faqat o'qiydi).

---

## 8. Yig'ma tavsiya qilish (S3)

Maqsad — byudjet ichida 2–3 mos variant. Algoritm deterministik; LLM faqat ehtiyojni slot'larga ajratadi va natijani tushuntiradi.

1. **Slot'lar:** byudjet (minor units), ish turi (`GAMING_1080P`, `GAMING_1440P`, `EDITING`, `OFFICE`), monitor kerakmi, afzalliklar.
2. **Nomzodlar:** `PUBLISHED`, mavjud (`CommerceQueryPort.get_availability` — `available > 0`) va spec'ga bog'langan SKU'lar. `catalog` qoldiq uchun `commerce` ga Query Port orqali murojaat qiladi — import emas.
3. **Byudjet taqsimoti** — `build_profiles` (masalan, `GAMING_1080P`: GPU ~40%, CPU ~20%); PC mutaxassis sozlaydi.
4. **Qurish tartibi:** CPU + mos MB → RAM → GPU → PSU (quvvat qoidasi bilan) → korpus → disk → cooler; har qadamda `BLOCK` beradigan nomzodlar tashlanadi.
5. **Saralash:** byudjetdan oshmagan `PASS` variantlar avval, keyin `REVIEW_REQUIRED`.
6. **Natija:** SKU'lar, narxlar (`observed_at` bilan), jami, moslik natijasi. Mos variant yo'q — "byudjet yetarli emas" va eng yaqin variant; hech qachon noto'g'ri "mos" da'vosi.

---

## 9. Versiyalash va o'zgarishlar

- Aktiv ruleset bitta. Yangi versiya: PR + golden testlar + PC mutaxassis review + founder aktivlashtiradi → outbox `catalog.pc_ruleset.activated`.
- Spec o'zgarsa (`version++`) → outbox `catalog.hardware_spec.updated {spec_id, version}`.
- `commerce` ikkala event'ni tinglaydi: **yuborilmagan** draft va review'dagi takliflar qayta tekshiriladi; yuborilgan taklif o'zgarmaydi, lekin buyurtma tasdig'ida joriy versiya bilan qayta tekshiriladi (BL-030).
- Noto'g'ri qoida topilsa — runbook (`25`): oldingi versiyaga qaytarish, ta'sirlangan takliflarni `quote_compatibility_snapshots.rule_set_version` bo'yicha topish, regression test qo'shish.

## 10. Kutubxonani yuritish (DEC-120)

| Mavzu | Qoida |
|---|---|
| Boshlang'ich qamrov | Pilot shoplarda eng ko'p sotiladigan ~300 model: CPU va MB (AM4/AM5, LGA1700/1851), GPU (RTX 40/50, RX 7000/9000), PSU, korpus, cooler, RAM, SSD |
| Manba | Ishlab chiqaruvchi sahifasi yoki datasheet; `source_url` majburiy |
| Kiritish | `/api/v1/platform/hardware-specs` (catalog domenining `platform` surface router'i), Pydantic validatsiya |
| Ikki ko'z | Yangi spec yoki o'zgarish ikkinchi odam tasdig'i bilan (`DRAFT → APPROVED`) |
| Shop so'rovi | `catalog.spec_requests` → platforma navbati; maqsad 2 ish kuni. Ungacha SKU bog'lanmagan |
| Yangilash | Haftalik: yangi modellar, BIOS ro'yxatlari |
| Audit | Har o'zgarish `platform/audit` da (kim, nima, manba) |

## 11. Kuzatuv

- Metrikalar: `cos_catalog_compatibility_checks_total{decision}`, `cos_catalog_compatibility_check_duration_seconds`, `cos_catalog_unlinked_sku_ratio{shop}` (gauge), `cos_catalog_spec_requests_open`.
- Span: `catalog.compatibility.check` (qoidalar soni, natija; SKU nomlarisiz).

## 12. Testlar

| To'plam | Hajm | Misollar |
|---|---|---|
| Unit (har qoida) | mos / mos emas / noma'lum | `CPU_MB_SOCKET`: AM5+AM5 → ok; LGA1700+AM5 → fail; soket yo'q → MISSING_ATTRIBUTE |
| Golden | 150+ yig'ma | DDR5 RAM + DDR4 plata → BLOCK; 335 mm GPU + 300 mm korpus → BLOCK; BIOS noma'lum → REVIEW (TC-008); 750 W PSU + 450 W GPU + 250 W CPU → REVIEW |
| Property-based | tasodifiy yig'malar | Natija deterministik; atributni olib tashlash hech qachon `BLOCK`/`REVIEW` ni `PASS` ga aylantirmaydi |
| Bog'lash | 50+ juftlik | `RTX 5060` ≠ `RTX 5060 Ti` (TC-016 bilan bir xil printsip); `B650M` ≠ `B650` |
| Izolyatsiya | — | A shop `sku_spec_links` B shopga ko'rinmaydi |
| Regression | har topilgan xato | Runbook bo'yicha |

## 13. Ochiq savollar

- Adapter bilan ishlash (2×8-pin → 12VHPWR) — hozir REVIEW; shop siyosati sifatida sozlanadimi?
- Ishlatilgan komponentlar uchun alohida qoidalar kerakmi?
- Noutbuk RAM/SSD upgrade tekshiruvi — Stage 2 dan keyin.

## Keyingi qadam

→ [18-catalog-import.md](18-catalog-import.md) — import va avtomatik bog'lash
→ [../modules/catalog/README.md](../modules/catalog/README.md)
