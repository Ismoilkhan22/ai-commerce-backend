# Modullar (domenlar) hujjatlari

> Har domen va platform moduli uchun bitta `README.md` (`03-module-requirements.md` §1.7). Kod bilan birga yangilanadi.

## Ro'yxat

| Modul | Qatlam | Biznes modullar | Slice | README |
|---|---|---|---|---|
| `platform` (auth, shops, staff, use, audit, notifications, storage, realtime, llm, billing) | platform | M01, M02, M03, M17, M19, M20 | S0, S2, S5 | [platform/README.md](platform/README.md) |
| `catalog` | domain | M04, M05, M08 | S1, S3 | [catalog/README.md](catalog/README.md) |
| `commerce` | domain | M06, M12, M13 | S1, S3, S4 | [commerce/README.md](commerce/README.md) |
| `messaging` | domain | M09, M10 | S2 | [messaging/README.md](messaging/README.md) |
| `sales_ai` | domain | M11, M19 (AI sozlamalari) | S3 | [sales_ai/README.md](sales_ai/README.md) |
| `storefront` | domain | M07 | S1 | [storefront/README.md](storefront/README.md) |
| `support` | domain | M16 | S5 | [support/README.md](support/README.md) |
| `reporting` | domain | M18 | S5 | [reporting/README.md](reporting/README.md) |

Keyinroq: `payments` (M14), `fulfillment` (M15), `network` (Stage 2), `marketplace` (Stage 3).

---

## Shablon

```markdown
# <domain>

**Qatlam:** domain | platform · **Schema:** `<name>` · **Slice:** S_ · **Egasi:** ___
**Biznes modullar:** Mxx · **Qoidalar:** BL-xxx … · **Holatlar:** FSM-xx (`../../business/05`)

## 1. Nima qiladi
(2–4 jumla: domen vazifasi va nima qilmasligi)

## 2. Sub-modullar
| Sub-modul | Vazifasi | Asosiy jadvallar |

## 3. Holatlar
(Strelkalar — `business/05` dan qisqacha, `state_machine.py` ga mos)

## 4. Event'lar
### Chiqaradi
| Event | Qachon | Kim tinglaydi |
### Tinglaydi
| Event | Kimdan | Nima qiladi |

## 5. Query Port (boshqa domenlar uchun)
| Metod | Qaytaradi | Kim ishlatadi |

## 6. API
| Surface | Metod va yo'l | Ruxsat | Idempotency |

## 7. Ruxsatlar
(`permissions.py` kodlari ↔ `business/04` jadvali)

## 8. Fon va rejali ishlar
| Ish | Qachon | Idempotency kaliti |

## 9. Metrikalar
(`cos_<domain>_...`)

## 10. Testlar
(Asosiy TC va UAT ID'lari, maxsus izolyatsiya/concurrency testlari)

## 11. Ochiq savollar
```
