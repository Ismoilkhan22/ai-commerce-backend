# TECH-25 — PC compatibility engine va reference hardware spec kutubxonasi

**Status:** Baseline (2026-10-22). DEC-011, DEC-120, ADR-028, K-09 asosida. Qoidalar chegaralari (masalan, PSU zaxirasi) pilotda PC mutaxassis bilan qayta ko'riladi.
**Bog'liq:** `business/02` M08, `business/03` BL-027…030, `06_DATABASE_ERD_AND_SCHEMA.md` (`reference_hardware_specs`, `sku_spec_links`), `15_AI_AGENTS_ARCHITECTURE.md` (`pc.compatibility_check`), `26_AI_TOOL_CONTRACTS.md`.

Bu hujjat backend dasturchi va PC mutaxassis uchun: komponent ma'lumotlari qanday saqlanadi, moslik qanday tekshiriladi va qaysi qoidalar bor.

---

## 1. Printsiplar

1. **Deterministik.** Natija faqat kod va ma'lumotdan chiqadi. LLM qoidani bajarmaydi, natijani o'zgartirmaydi; faqat tushuntiradi (BL-027, BL-041).
2. **Noma'lum ≠ mos.** Qoida uchun kerakli atribut yo'q bo'lsa — `REVIEW_REQUIRED`, hech qachon `PASS` emas (BL-028).
3. **Versiyalangan.** Har natija `rule_set_version` va ishlatilgan spec versiyalari bilan saqlanadi (BL-030).
4. **Dalil bilan.** Har finding qaysi atribut va qaysi manbadan chiqqanini ko'rsatadi.
5. **Spec'lar platformaniki.** Merchant spec'ni tahrirlay olmaydi; faqat SKU'sini bog'laydi yoki yangi model so'raydi (DEC-120).

## 2. Natija qiymatlari (K-09)

| Qiymat | Ma'nosi | Quote yuborish mumkinmi |
|---|---|---|
| `PASS` | Barcha `BLOCK` va `REVIEW` qoidalari o'tdi (`WARNING` bo'lishi mumkin) | Ha |
| `REVIEW_REQUIRED` | Kamida bitta qoida ma'lumot yetmagani yoki shartli holat sabab tekshirilmadi | Faqat Manager/Owner dalil bilan tasdiqlasa (FSM-06) |
| `BLOCK` | Kamida bitta qoida aniq buzilgan | Yo'q (`RULE_BLOCK`) |

**Yig'ish qoidasi:** birorta `BLOCK` → `BLOCK`; aks holda birorta `REVIEW_REQUIRED` → `REVIEW_REQUIRED`; aks holda `PASS`. `WARNING` va `INFO` natijaga ta'sir qilmaydi, lekin xaridorga va operatorga ko'rsatiladi.

## 3. Ma'lumot modeli

### 3.1 Kategoriyalar va atributlar

Barcha o'lchamlar mm, quvvat W, sig'im GB. Atribut `attributes jsonb` ichida saqlanadi va har kategoriya uchun Pydantic sxemasi bilan validatsiya qilinadi. **Yo'q atribut — noma'lum** (0 yoki bo'sh qator emas).

| Kategoriya | Atribut | Turi | Qaysi qoidalar ishlatadi |
|---|---|---|---|
| `CPU` | `socket` | enum: `AM4`, `AM5`, `LGA1200`, `LGA1700`, `LGA1851` … | CPU_MB_SOCKET, COOLER_SOCKET |
| | `memory_types` | list: `DDR4`, `DDR5` | RAM_TYPE_CPU |
| | `base_power_w` (TDP), `max_power_w` (PL2/PPT) | int | PSU_WATTAGE, COOLER_TDP |
| | `integrated_graphics` | bool | DISPLAY_OUTPUT |
| | `cooler_included` | bool | CPU_COOLER_PRESENT |
| `MOTHERBOARD` | `socket`, `chipset` | enum, str | CPU_MB_SOCKET |
| | `form_factor` | enum: `E_ATX`, `ATX`, `MICRO_ATX`, `MINI_ITX` | MB_CASE_FORM_FACTOR |
| | `memory_type` | enum: `DDR4`, `DDR5` | RAM_TYPE_MB |
| | `memory_slots`, `max_memory_gb` | int | RAM_SLOTS, RAM_CAPACITY |
| | `max_memory_speed_mts` | int | RAM_SPEED |
| | `m2_slots` | int | STORAGE_M2_SLOTS |
| | `sata_ports` | int | STORAGE_SATA_PORTS |
| | `cpu_support` | list: `{cpu_model, min_bios}` | BIOS_SUPPORT |
| | `shipped_bios` | str yoki noma'lum | BIOS_SUPPORT |
| `RAM` | `type` | enum: `DDR4`, `DDR5` | RAM_TYPE_MB |
| | `form_factor` | enum: `DIMM`, `SO_DIMM` | RAM_FORM_FACTOR |
| | `module_count`, `capacity_per_module_gb`, `speed_mts` | int | RAM_SLOTS, RAM_CAPACITY, RAM_SPEED, SINGLE_CHANNEL |
| `GPU` | `length_mm`, `slot_width` | int, float | GPU_CASE_LENGTH |
| | `board_power_w`, `recommended_psu_w` | int | PSU_WATTAGE, PSU_HEADROOM |
| | `power_connectors` | list: `{type: PCIE_6PIN \| PCIE_8PIN \| 12VHPWR \| 12V_2X6, count}` | PSU_GPU_CONNECTORS |
| `PSU` | `wattage_w` | int | PSU_WATTAGE, PSU_HEADROOM |
| | `form_factor` | enum: `ATX`, `SFX`, `SFX_L` | PSU_CASE_FORM_FACTOR |
| | `connectors` | `{pcie_8pin, pcie_6pin, 12vhpwr, eps_8pin}` (soni) | PSU_GPU_CONNECTORS |
| | `length_mm` | int | PSU_CASE_LENGTH |
| `CASE` | `supported_mb_form_factors` | list | MB_CASE_FORM_FACTOR |
| | `max_gpu_length_mm`, `max_cpu_cooler_height_mm`, `max_psu_length_mm` | int | GPU_CASE_LENGTH, COOLER_HEIGHT_CASE, PSU_CASE_LENGTH |
| | `psu_form_factor` | enum | PSU_CASE_FORM_FACTOR |
| | `radiator_support_mm` | list: 120, 240, 280, 360 | AIO_RADIATOR_CASE |
| `CPU_COOLER` | `type` | enum: `AIR`, `AIO` | COOLER_HEIGHT_CASE, AIO_RADIATOR_CASE |
| | `supported_sockets` | list | COOLER_SOCKET |
| | `height_mm` (AIR), `radiator_mm` (AIO) | int | COOLER_HEIGHT_CASE, AIO_RADIATOR_CASE |
| | `tdp_rating_w` | int | COOLER_TDP |
| `STORAGE` | `interface` | enum: `NVME`, `SATA` | STORAGE_* |
| | `form_factor` | enum: `M2_2280`, `M2_2242`, `SATA_2_5`, `SATA_3_5` | STORAGE_* |

Stage 1 dan tashqarida: noutbuklar va tayyor yig'ilgan PC'lar (`assembled_pc`) — ular oddiy mahsulot sifatida sotiladi, moslik tekshiruvi qo'llanmaydi. Monitor va periferiya — tekshiruvsiz.

### 3.2 Jadvallar

`06_DATABASE_ERD_AND_SCHEMA.md` §3 dagi DDL. Qo'shimcha:

```sql
CREATE TABLE pc_rulesets (
  version text PRIMARY KEY,           -- 'pc-2026-10-v1'
  code_ref text NOT NULL,             -- git commit / package version
  activated_at timestamptz,
  activated_by uuid,
  notes text
);
CREATE TABLE compatibility_results (
  id uuid PRIMARY KEY,
  merchant_id uuid NOT NULL,
  subject_type text NOT NULL CHECK (subject_type IN ('PC_BUILD','QUOTE_REVISION')),
  subject_id uuid NOT NULL,
  rule_set_version text NOT NULL REFERENCES pc_rulesets(version),
  decision text NOT NULL CHECK (decision IN ('PASS','REVIEW_REQUIRED','BLOCK')),
  findings jsonb NOT NULL,            -- §6
  spec_versions jsonb NOT NULL,       -- {sku_id: {spec_id, version}}
  reviewed_by uuid,                   -- REVIEW_REQUIRED tasdiqlansa
  review_note text,
  created_at timestamptz NOT NULL DEFAULT now()
);
```

## 4. SKU'ni spec'ga bog'lash

| Bosqich | Usul | `linked_by` |
|---|---|---|
| 1 | MPN aniq mos (normallashtirilgan: katta harf, bo'shliq va chiziqchasiz) | `AUTO_MPN` |
| 2 | Brend + model normallashtirilgan nomi aniq mos (variant suffikslari hisobga olinadi: `Ti`, `SUPER`, `OC`, xotira hajmi) | `AUTO_MODEL` |
| 3 | Bir nechta nomzod yoki o'xshashlik — avtomatik bog'lanmaydi; merchant ro'yxatdan tanlaydi | `MANUAL` |
| — | Topilmadi — merchant "yangi model so'rovi" yuboradi; SKU bog'lanmagan holda qoladi | — |

**Taqiqlar:** `RTX 5060` va `RTX 5060 Ti`, `8GB` va `16GB`, `DDR4` va `DDR5` versiyalari hech qachon avtomatik birlashtirilmaydi. Bog'lanmagan SKU yig'mada ishtirok etsa — `UNLINKED_PART` (REVIEW_REQUIRED). Katalog importi bog'lashni avtomatik bajaradi va natijani import hisobotida ko'rsatadi.

## 5. Qoidalar katalogi (`pc-2026-10-v1`)

Qoidalar Python'da toza funksiya sifatida yoziladi (YAML DSL emas: type-check, test va refactor osonroq). Har qoida metadata bilan ro'yxatdan o'tadi:

```python
# src/commerce_os/modules/pc_builder/domain/rules/socket.py
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

Engine `requires` dagi atributlardan birortasi noma'lum bo'lsa qoidani bajarmaydi va `MISSING_ATTRIBUTE` (REVIEW_REQUIRED) finding'ini qo'yadi. Shu tufayli har bir qoida "noma'lum" holatni alohida yozishi shart emas.

### 5.1 To'liqlik

| ID | Severity | Tekshiruv |
|---|---|---|
| `REQUIRED_PARTS` | BLOCK | CPU, MOTHERBOARD, RAM, STORAGE (≥1), PSU, CASE bor. Yetishmasa — quote berib bo'lmaydi (xaridor faqat qism so'rasa, tekshiruv qo'llanmaydi) |
| `DISPLAY_OUTPUT` | BLOCK | GPU yo'q va `cpu.integrated_graphics = false` |
| `CPU_COOLER_PRESENT` | BLOCK | Cooler yo'q va `cpu.cooler_included = false` |
| `DUPLICATE_PART` | BLOCK | Ikkita CPU, ikkita ona plata yoki ikkita PSU |
| `UNLINKED_PART` | REVIEW_REQUIRED | Kamida bitta SKU spec'ga bog'lanmagan |

### 5.2 Moslik

| ID | Severity | Tekshiruv |
|---|---|---|
| `CPU_MB_SOCKET` | BLOCK | `cpu.socket == mb.socket` |
| `BIOS_SUPPORT` | REVIEW_REQUIRED | CPU `mb.cpu_support` ro'yxatida bo'lishi va `min_bios <= shipped_bios`. Ro'yxatda yo'q, `shipped_bios` noma'lum yoki eskiroq bo'lsa — REVIEW (do'kon BIOS yangilashi kerak bo'lishi mumkin) |
| `RAM_TYPE_MB` | BLOCK | `ram.type == mb.memory_type` |
| `RAM_TYPE_CPU` | BLOCK | `ram.type in cpu.memory_types` |
| `RAM_FORM_FACTOR` | BLOCK | `ram.form_factor == DIMM` (desktop) |
| `RAM_SLOTS` | BLOCK | jami modullar `<= mb.memory_slots` |
| `RAM_CAPACITY` | BLOCK | jami GB `<= mb.max_memory_gb` |
| `MB_CASE_FORM_FACTOR` | BLOCK | `mb.form_factor in case.supported_mb_form_factors` |
| `GPU_CASE_LENGTH` | BLOCK | `gpu.length_mm <= case.max_gpu_length_mm` |
| `COOLER_SOCKET` | BLOCK | `cpu.socket in cooler.supported_sockets` |
| `COOLER_HEIGHT_CASE` | BLOCK | AIR: `cooler.height_mm <= case.max_cpu_cooler_height_mm` |
| `AIO_RADIATOR_CASE` | BLOCK | AIO: `cooler.radiator_mm in case.radiator_support_mm` |
| `PSU_CASE_FORM_FACTOR` | BLOCK | PSU form factor korpusga mos (`SFX` ko'pincha `ATX` korpusga adapter bilan — REVIEW) |
| `PSU_CASE_LENGTH` | WARNING | `psu.length_mm <= case.max_psu_length_mm` (ma'lumot bo'lsa) |
| `STORAGE_M2_SLOTS` | BLOCK | NVMe/M.2 disklar soni `<= mb.m2_slots` |
| `STORAGE_SATA_PORTS` | BLOCK | SATA disklar soni `<= mb.sata_ports` |

### 5.3 Quvvat

**Taxminiy iste'mol** = `cpu.max_power_w` + `gpu.board_power_w` + 75 W (ona plata, xotira, disklar, fanlar).

| ID | Severity | Tekshiruv |
|---|---|---|
| `PSU_WATTAGE` | BLOCK | `psu.wattage_w >= taxminiy iste'mol` |
| `PSU_HEADROOM` | REVIEW_REQUIRED | `psu.wattage_w >= max(gpu.recommended_psu_w, taxminiy iste'mol × 1.3)`. Pastroq bo'lsa — mutaxassis ko'rib chiqadi |
| `PSU_GPU_CONNECTORS` | BLOCK / REVIEW | PSU'da GPU talab qilgan konnektorlar soni va turi bor. Faqat adapter orqali mumkin bo'lsa — REVIEW |
| `COOLER_TDP` | WARNING | `cooler.tdp_rating_w >= cpu.base_power_w` (ma'lumot bo'lsa) |

### 5.4 Ogohlantirishlar

| ID | Severity | Tekshiruv |
|---|---|---|
| `RAM_SPEED` | WARNING | `ram.speed_mts > mb.max_memory_speed_mts` — RAM pastroq tezlikda ishlaydi |
| `SINGLE_CHANNEL` | WARNING | Bitta RAM moduli — unumdorlik past |
| `MIXED_RAM_KITS` | WARNING | Turli modelli RAM modullari |
| `NO_UPGRADE_SLOT` | INFO | Barcha RAM slotlari band |

Chegaralar (75 W, ×1.3) — boshlang'ich qiymatlar; PC mutaxassis pilotda tasdiqlaydi. O'zgarishi yangi `rule_set_version` sifatida chiqadi.

## 6. Kirish va chiqish kontrakti

**Kirish:** `merchant_id` (server), `sku_ids[]` (miqdor bilan), ixtiyoriy `rule_set_version` (default — aktiv versiya), `locale`.

**Chiqish:**

```json
{
  "rule_set_version": "pc-2026-10-v1",
  "decision": "REVIEW_REQUIRED",
  "can_publish_quote": false,
  "checked_sku_ids": ["sku_cpu", "sku_mb", "sku_ram", "sku_gpu", "sku_psu", "sku_case", "sku_ssd"],
  "findings": [
    {
      "rule_id": "BIOS_SUPPORT",
      "severity": "REVIEW_REQUIRED",
      "explanation": "Ona plata ushbu protsessor uchun BIOS yangilashni talab qilishi mumkin.",
      "facts": {"cpu_model": "Ryzen 7 9700X", "min_bios": "F20", "shipped_bios": null},
      "evidence": [{"spec_id": "…", "version": 2, "source_url": "https://…"}]
    },
    {
      "rule_id": "SINGLE_CHANNEL",
      "severity": "WARNING",
      "explanation": "Bitta RAM moduli: ikki modul unumdorlikni oshiradi.",
      "facts": {"module_count": 1},
      "evidence": []
    }
  ],
  "estimated_power_w": 425,
  "spec_versions": {"sku_cpu": {"spec_id": "…", "version": 2}}
}
```

`explanation` backend tomonidan `locale` bo'yicha qoida shablonidan yaratiladi (TECH-24 §5.3). AI bu matnni o'zgartirmasdan yoki qisqartirib qayta aytadi, lekin ma'nosini o'zgartirmaydi. Natija `compatibility_results` ga yoziladi va quote revision'iga bog'lanadi.

## 7. Yig'ma tavsiya qilish (S3, soddalashtirilgan)

Maqsad — byudjet ichida 2–3 ta mos variant. Algoritm deterministik, LLM faqat ehtiyojni slot'larga ajratadi va natijani tushuntiradi.

1. **Kirish slot'lari:** byudjet (UZS minor), ish turi (`GAMING_1080P`, `GAMING_1440P`, `EDITING`, `OFFICE`), monitor kerakmi, majburiy afzalliklar (brend, RAM hajmi).
2. **Nomzodlar:** faqat `published`, stokda bor (`available > 0`) va spec'ga bog'langan SKU'lar.
3. **Byudjet taqsimoti** ish turi profili bo'yicha (masalan, `GAMING_1080P`: GPU ~40%, CPU ~20%, qolganlari). Profillar konfiguratsiyada, PC mutaxassis sozlaydi.
4. **Qurish tartibi:** CPU + mos MB juftliklari → RAM → GPU → PSU (quvvat qoidasi bilan) → korpus → disk → cooler. Har qadamda `BLOCK` beradigan nomzodlar tashlanadi.
5. **Saralash:** byudjetdan oshmagan, `PASS` bo'lgan variantlar avval; keyin `REVIEW_REQUIRED`. Ball (TECH-03 §8 dagi og'irliklar) pilotda baholanadi.
6. **Natija:** har variant uchun SKU'lar, narxlar (snapshot), jami summa, compatibility natijasi. Byudjetga mos variant topilmasa — "byudjet yetarli emas" va eng yaqin variant, hech qachon "mos" deb noto'g'ri da'vo yo'q.

## 8. Versiyalash va o'zgarishlar

- Aktiv ruleset bitta (`pc_rulesets.activated_at` eng oxirgisi). Yangi versiya: PR + golden testlar + PC mutaxassis review + founder aktivlashtirishi.
- Quote snapshot'i eski versiya natijasini saqlaydi (BL-030). Yangi versiya chiqqanda **yuborilmagan** draft va review'dagi quote'lar qayta tekshiriladi; yuborilgan quote o'zgarmaydi, lekin buyurtma tasdig'ida joriy versiya bilan qayta tekshiriladi.
- Spec o'zgarsa (`reference_hardware_specs.version++`), shu spec'ga bog'langan ochiq draft'lar qayta tekshiriladi.
- Noto'g'ri qoida aniqlansa — runbook: ruleset'ni oldingi versiyaga qaytarish, ta'sirlangan quote'larni topish (`compatibility_results.rule_set_version`), regression test qo'shish.

## 9. Spec kutubxonasini yuritish (DEC-120)

| Mavzu | Qoida |
|---|---|
| Boshlang'ich qamrov | Pilot do'konlar katalogidagi eng ko'p sotiladigan ~300 model: CPU va MB (AMD AM4/AM5, Intel LGA1700/1851), GPU (NVIDIA RTX 40/50, AMD RX 7000/9000), PSU, korpus, cooler, RAM, SSD |
| Manba | Ishlab chiqaruvchi rasmiy sahifasi yoki datasheet; `source_url` majburiy. Retailer sahifalari asosiy manba emas |
| Kiritish | Platforma admin ekrani (`/api/v1/platform/hardware-specs`), Pydantic sxemasi bo'yicha validatsiya |
| Ikki ko'z printsipi | Yangi spec yoki o'zgarish ikkinchi odam tomonidan tasdiqlanadi (pilotda founder + PC mutaxassis) |
| Merchant so'rovi | "Yangi model" so'rovi → platforma navbati; maqsad — 2 ish kunida qo'shish (taklif). Ungacha SKU `UNLINKED` |
| Yangilash | Haftalik: yangi chiqqan modellar, BIOS qo'llab-quvvatlash ro'yxatlari |
| Audit | Har o'zgarish `audit_entries` da (kim, nima, manba) |

## 10. Testlar

| To'plam | Hajm | Misollar |
|---|---|---|
| Unit (har qoida) | har qoida uchun mos / mos emas / noma'lum holatlar | `CPU_MB_SOCKET`: AM5 + AM5 → ok; LGA1700 + AM5 → fail; socket yo'q → MISSING_ATTRIBUTE |
| Golden set | 150+ yig'ma (TECH-15 §8) | LGA1700 CPU + AM5 plata → BLOCK; DDR5 RAM + DDR4 plata → BLOCK; 335 mm GPU + 300 mm korpus → BLOCK; BIOS noma'lum → REVIEW_REQUIRED; 750 W PSU + 450 W GPU + 250 W CPU → REVIEW (headroom) |
| Property-based | tasodifiy yig'malar | natija deterministik; atributni olib tashlash hech qachon `BLOCK`/`REVIEW` → `PASS` ga aylantirmaydi |
| Bog'lash | 50+ juftlik | `RTX 5060` ≠ `RTX 5060 Ti`; `B650M` ≠ `B650`; MPN bo'shliq/registr farqi → mos |
| Regression | har topilgan xato | runbook bo'yicha qo'shiladi |

## 11. Ochiq savollar

- Adapter (masalan, 2×8-pin → 12VHPWR) bilan ishlashga ruxsat — hozircha REVIEW; do'kon siyosati sifatida sozlanadimi?
- Ishlatilgan (used) komponentlar uchun alohida qoidalar kerakmi (kafolat, holat)?
- Noutbuk RAM/SSD upgrade tekshiruvi — Stage 2 dan keyin.
