# AI Commerce OS & Network — hujjatlar indeksi

**Holat:** v2 (2026-10-22). Biznes hujjatlari oddiy o'zbek tilida qayta yozildi. Engineering hujjatlari keyingi navbatda `bismuth_platform_v2` standartlariga moslab qayta ko'rib chiqiladi (DEC-125). Kod hali yo'q. Qarorlar `decisions/` papkasida.

## Papkalar va haqiqat manbai

| Papka | Nima bor | Kim uchun |
|---|---|---|
| [`business/`](business/00_README_AND_SCOPE.md) | 3 bosqich, 39 modul (`M01–M39`), 111 qoida (`BL-001…111`), holatlar ketma-ketligi, rollar, sahifalar, qabul sinovlari, shopni ulash (13), pilot kelishuvi (14) | Hamma |
| [`GLOSSARY.md`](GLOSSARY.md) | Atamalar lug'ati: o'zbekcha ↔ kodda (do'kon = `shop`, DEC-124) | Hamma |
| [`discovery/`](discovery/A01_MARKET_PROBLEM_DISCOVERY.md) | Bozor va muammo tadqiqoti: shoplar bilan suhbat rejasi, farazlar (`HYP-xxx`) | Founder, sotuv |
| [`engineering/`](engineering/README.md) | v2 (bismuth standarti): prinsiplar, arxitektura, papkalar, modul talablari, holatlar, event'lar, fon ishlari, DB, xavfsizlik, API va xatolar, AI, kanallar, infra, testlar, roadmap (00–29) va `ADR/` | Backend, frontend, AI |
| [`modules/`](modules/README.md) | Har domen uchun README: vazifasi, jadvallar, event'lar, API, ruxsatlar | Modul egasi |
| [`decisions/`](decisions/DECISION_REGISTER.md) | Qarorlar registri: har qaror uchun variantlar, afzallik va kamchiliklar, tanlov va sana (boshlang'ich — o'zgartirish mumkin) | Founder |

**Qoidalar:**

1. Har bir fakt **bitta joyda** yashaydi. Nusxa ko'chirmang, havola bering.
2. Biznes qoidasi bo'yicha manba — `business/03`. Status nomlari — `business/05`. Texnik qaror — `engineering/ADR/README.md` (ADR).
3. Qaror o'zgarsa, avval `decisions/DECISION_REGISTER.md` yangilanadi, keyin ta'sirlangan hujjatlar.
4. Hujjatda `PROPOSED` deb yozilgan narsa tasdiqlangan emas. Tasdiqlangani `APPROVED` + sana bilan belgilanadi.
5. Birlashtirilgan (concatenated) yoki bosqich bo'yicha ajratilgan nusxalar saqlanmaydi. Kerak bo'lsa skript bilan generatsiya qilinadi.

## O'qish tartibi

1. `business/00` → `business/01` → `business/02` (modullar) → `business/03` (qoidalar)
2. `engineering/README.md` → `engineering/00` → `01` → `02` → `03` → `engineering/27-roadmap-and-tasks.md` (vazifalar)
3. `decisions/DECISION_REGISTER.md` — kod boshlashdan oldin tasdiqlanishi kerak bo'lgan qarorlar

## Hujjat ID'lari

| Prefiks | Ma'nosi | Manba |
|---|---|---|
| `Mxx` | Biznes modul | `business/02` |
| `BL-xxx` | Biznes qoida | `business/03` |
| `FSM-xx` | Status mashinasi | `business/05` |
| `UAT-Mxx`, `TC-xxx` | Qabul testlari | `business/10`, `engineering/24-testing-and-release.md` |
| Domen nomlari | `catalog`, `commerce`, ... | `engineering/01-architecture-overview.md` |
| `ADR-xxx` | Arxitektura qarori | `engineering/ADR/README.md` |
| `DEC-xxx` | Ochiq qaror (registr) | `decisions/` |
| `O-xx`, `D-xx`, `DDD-Oxx`, `C4-Oxx` | Eski ochiq savollar ro'yxatlari — `DEC-xxx` ga ko'chirilgan | `decisions/` |
