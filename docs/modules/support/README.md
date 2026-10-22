# support

**Qatlam:** domain · **Schema:** `support` · **Slice:** S5 · **Egasi:** ___
**Biznes modullar:** M16 · **Qoidalar:** BL-057, BL-058, BL-059, DEC-114 · **Holatlar:** FSM-11 (`../../business/05`, "Kafolat murojaati")

## 1. Nima qiladi

Buyurtmaga bog'liq kafolat va qaytarish murojaatlarini yuritadi. Kafolat shartlari sotuv paytidagidek saqlanadi (BL-057). Qaytarishga ruxsatni odam beradi (BL-058). Qaytgan mahsulot tekshiruvgacha sotuvga chiqmaydi (BL-059). Bu `commerce` ga event orqali yetkaziladi.

Bu domen qilmaydi:
- **Pul qaytarish** — shop tizimdan tashqarida qiladi (DEC-100).
- **Ombordagi qoldiq yozuvlari** — `commerce` qiladi.

## 2. Sub-modullar

| Sub-modul | Vazifasi | Asosiy jadvallar |
|---|---|---|
| `cases` | Murojaat ochish, ko'rib chiqish, qaror, xizmat, yopish | `support_cases` |

`support_cases` ustunlari: `id`, `shop_id`, `order_id`, `order_line_id`, `sku_id`, `type` (`WARRANTY`, `RETURN`), `status`, `warranty_snapshot`, `resolution`, `reject_reason`, `version`.
- `order_id` — UUID, `commerce` ga FK yo'q (ADR-035, [07](../../engineering/07-data-layer.md) §4.8).

## 3. Holatlar (FSM-11, `support.case`)

```
NEW ──(operator ko'rib chiqishni boshladi)──▶ IN_REVIEW
IN_REVIEW ──(menejer qabul qildi)──▶ APPROVED
IN_REVIEW ──(menejer rad etdi, sabab bilan)──▶ REJECTED
APPROVED ──(mahsulot qabul qilindi, tekshirilmoqda)──▶ IN_SERVICE   [omborda "tekshiruvda", sotilmaydi]
IN_SERVICE ──(ta'mirlandi / almashtirildi / qaytarildi)──▶ RESOLVED
RESOLVED ──(xaridor tasdiqladi yoki muddat o'tdi)──▶ CLOSED
```

- Buyruq nomlari: `APPROVE`, `START_SERVICE`, … ([04](../../engineering/04-state-machines-and-use.md), "Qolgan FSM'lar"). To'liq ro'yxat — `state_machine.py`.
- Har o'tish `use.validate_transition` va `use.log_transition` orqali o'tadi (ADR-034).

## 4. Event'lar

### Chiqaradi ([05](../../engineering/05-events-and-outbox.md) §8.5)

| Event | Qachon | Kim tinglaydi |
|---|---|---|
| `support.case.opened` | `NEW` | reporting |
| `support.case.status_changed` | Har bir FSM-11 o'tishi | commerce (`IN_SERVICE` → mahsulot "tekshiruvda", BR-X11), reporting |
| `support.case.resolved` | → `RESOLVED`; `outcome`: `REPAIRED`, `REPLACED` yoki `RETURNED` | commerce (omborchiga qaror vazifasi), reporting |

### Tinglaydi

| Event | Kimdan | Nima qiladi |
|---|---|---|
| `commerce.order.completed` | commerce | Kafolat sanasi uchun kontekst ([05](../../engineering/05-events-and-outbox.md) §8.2) |
| `platform.privacy.export_requested` / `erasure_requested` | platform/privacy | Murojaat kontaktlarini eksport qiladi yoki anonimlashtiradi ([26](../../engineering/26-privacy-and-retention.md)) |

**Xabarnoma:** murojaat ochilganda domen `platform.notifications.request()` ni chaqiradi. Shablon: `staff.support_case_opened` (menejerga, [20](../../engineering/20-notifications.md)).

## 5. Query Port

**Beradi:** yo'q.

**Ishlatadi:** `CommerceQueryPort.get_order_for_support(order_id)` — murojaat ochilganda buyurtma shu shopniki va topshirilganini tekshiradi, qatorlar va `warranty_snapshot` (kafolat shartlari, muddati — BL-057) shu yerdan olinadi ([05](../../engineering/05-events-and-outbox.md) §8.9).

## 6. API (`shop` surface)

| Metod va yo'l | Ruxsat | Idempotency / If-Match |
|---|---|---|
| `GET /shop/support-cases`, `GET …/{id}` | `support.case.view` | — |
| `POST /shop/support-cases`, `POST …/{id}/start-review` | `support.case.create` | Idem |
| `POST …/{id}/approve`, `POST …/{id}/reject` | `support.case.decide` | Idem + If-Match |
| `POST …/{id}/start-service`, `…/resolve`, `…/close` | `support.case.service` | Idem + If-Match |

Manba: [11](../../engineering/11-api-conventions-errors-i18n.md) §9.9.

## 7. Ruxsatlar ([10](../../engineering/10-security-tenancy-rbac.md))

| Kod | Ega | Menejer | Operator | Omborchi |
|---|---|---|---|---|
| `support.case.view` | ✓ | ✓ | ✓ | ✓ |
| `support.case.create` | ✓ | ✓ | ✓ | — |
| `support.case.decide` | ✓ | ✓ | — | — |
| `support.case.service` | ✓ | ✓ | — | ✓ (o'z filiali) |

- Tahlilchi faqat umumiy raqamlarni ko'radi.
- Operator murojaatni ochadi va ma'lumot yig'adi, qabul/rad qarorini menejer yoki ega qiladi (founder qarori, 2026-10-22).

## 8. Fon va rejali ishlar

`06` da `support` uchun rejali ish yo'q. Saqlash muddati — kafolat muddati + 12 oy, keyin kontakt anonimlashtiriladi ([26](../../engineering/26-privacy-and-retention.md)).

## 9. Metrikalar

- `09` ro'yxatida `cos_support_*` metrikalari yo'q.
- Biznes o'lchovi — "murojaatni hal qilish vaqti" (M16). `reporting` da metrika sifatida hali yo'q (§11).

## 10. Testlar

- **UAT-M16:**
  - murojaat ochiladi → ko'rib chiqiladi → hal qilinadi;
  - qaytgan mahsulot tekshirilmaguncha sotuvga chiqmaydi;
  - operator rad eta olmaydi.
- **TC-020** — shikastlangan mahsulot sotuvga chiqmaydi.
- **TC-ISO** — boshqa shop murojaati ko'rinmaydi.
- **State machine testi** — har ruxsat etilgan va taqiqlangan o'tish.

## 11. Ochiq savollar

1. **Murojaat ochilishi.** Xaridor saytdan ochadimi yoki faqat xodim? Stage 1 API faqat `shop` surface'da.
