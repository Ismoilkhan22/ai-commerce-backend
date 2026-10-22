# AI Commerce OS & Network — hujjatlar indeksi

**Holat:** v2 (2026-10-22). Biznes hujjatlari oddiy o'zbek tilida qayta yozildi. Engineering hujjatlari keyingi navbatda `bismuth_platform_v2` standartlariga moslab qayta ko'rib chiqiladi (DEC-125). Kod hali yo'q. Qarorlar `decisions/` papkasida.

## Papkalar va haqiqat manbai

| Papka | Nima bor | Kim uchun |
|---|---|---|
| [`business/`](business/00_README_AND_SCOPE.md) | 3 bosqich, 39 modul (`M01–M39`), 111 qoida (`BL-001…111`), holatlar ketma-ketligi, rollar, sahifalar, qabul sinovlari, shopni ulash (13), pilot kelishuvi (14) | Hamma |
| [`GLOSSARY.md`](GLOSSARY.md) | Atamalar lug'ati: o'zbekcha ↔ kodda (do'kon = `shop`, DEC-124) | Hamma |
| [`discovery/`](discovery/A01_MARKET_PROBLEM_DISCOVERY.md) | Bozor va muammo tadqiqoti: shoplar bilan suhbat rejasi, farazlar (`HYP-xxx`) | Founder, sotuv |
| [`engineering/`](engineering/00_ENGINEERING_README.md) | `TECH-03…33`: DDD, C4, ADR, DB, API, events, security, AI, voice, infra, test, roadmap; konvensiyalar va i18n (24), PC compatibility (25), AI tool kontraktlari (26), dev setup (27), katalog importi (28), metrikalar (29), kanallar (30), xabarnomalar (31), shaxsiy ma'lumotlar (32), runbook'lar (33) | Backend, frontend, AI |
| [`decisions/`](decisions/DECISION_REGISTER.md) | Qarorlar registri: har qaror uchun variantlar, afzallik va kamchiliklar, tanlov va sana (boshlang'ich — o'zgartirish mumkin) | Founder |

**Qoidalar:**

1. Har bir fakt **bitta joyda** yashaydi. Nusxa ko'chirmang, havola bering.
2. Biznes qoidasi bo'yicha manba — `business/03`. Status nomlari — `business/05`. Texnik qaror — `engineering/05` (ADR).
3. Qaror o'zgarsa, avval `decisions/DECISION_REGISTER.md` yangilanadi, keyin ta'sirlangan hujjatlar.
4. Hujjatda `PROPOSED` deb yozilgan narsa tasdiqlangan emas. Tasdiqlangani `APPROVED` + sana bilan belgilanadi.
5. Birlashtirilgan (concatenated) yoki bosqich bo'yicha ajratilgan nusxalar saqlanmaydi. Kerak bo'lsa skript bilan generatsiya qilinadi.

## O'qish tartibi

1. `business/00` → `business/01` → `business/02` (modullar) → `business/03` (qoidalar)
2. `engineering/00` → `engineering/05` (ADR) → `engineering/21` (review) → `engineering/22` (roadmap)
3. `decisions/DECISION_REGISTER.md` — kod boshlashdan oldin tasdiqlanishi kerak bo'lgan qarorlar

## Hujjat ID'lari

| Prefiks | Ma'nosi | Manba |
|---|---|---|
| `Mxx` | Biznes modul | `business/02` |
| `BL-xxx` | Biznes qoida | `business/03` |
| `FSM-xx` | Status mashinasi | `business/05` |
| `UAT-Mxx`, `TC-xxx` | Qabul testlari | `business/10`, `engineering/20` |
| `Cxx` | Bounded context | `engineering/03` |
| `ADR-xxx` | Arxitektura qarori | `engineering/05` |
| `TECH-xx` | Engineering hujjati | `engineering/` |
| `DEC-xxx` | Ochiq qaror (registr) | `decisions/` |
| `O-xx`, `D-xx`, `DDD-Oxx`, `C4-Oxx` | Eski ochiq savollar ro'yxatlari — `DEC-xxx` ga ko'chirilgan | `decisions/` |
