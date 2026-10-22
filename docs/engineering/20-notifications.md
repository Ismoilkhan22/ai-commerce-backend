# 20 — Xabarnomalar: shablonlar, triggerlar, yetkazish

> **Versiya:** v2 (2026-10-22). Eski `31_NOTIFICATIONS_MESSAGE_CATALOG` o'rnini bosadi.
> **Modul:** `platform/notifications` (schema `platform`). Xaridorga yetkazish — `messaging` domeni orqali.
> **Biznes:** M17, BL-060…062, FSM-12, DEC-104, DEC-113.
> **Kim o'qiydi:** backend, founder (matnlarni tahrirlash), frontend (dashboard bildirishnomalari).

## 1. Muammo

1. Buyurtma tasdiqlanganda xaridorga xabar, operatorga vazifa, 24 soatdan keyin eslatma kerak. Agar har domen xabarni o'zi yozsa — matnlar, tillar va takrorlardan himoya tarqoq bo'ladi.
2. `platform` domenlarni import qila olmaydi (00 §2, 2-qoida) — u `commerce.order.confirmed` qanday tuzilganini bilmaydi.
3. Xaridorga xabar uning kanali orqali ketadi (shopning Telegram boti, Instagram) — bu `messaging` domenining ishi, platform'niki emas.

## 2. Yechim

- **Trigger — domenda.** Qaysi hodisada qaysi xabar ketishini event'ning egasi domen hal qiladi va o'z service'i yoki subscriber'idan `platform.notifications.request(...)` ni chaqiradi (domen → platform importi ruxsat etilgan).
- **Shablon, tarjima, takrordan himoya, holat (FSM-12) — `platform/notifications` da.** U faqat `NotificationRequest` kontraktini biladi: `template_key`, qabul qiluvchi, o'zgaruvchilar, `aggregate_type/id/version`.
- **Yetkazish:**
  - **Xodimga** — `platform/notifications` o'zi: dashboard (`platform/realtime`) va ixtiyoriy Telegram (platforma tizim boti; xodim o'z akkauntini bog'laydi).
  - **Xaridorga** — `messaging`: platform `platform.notification.customer_delivery_requested` event'ini chiqaradi → `messaging` subscriber matnni oladi va xaridor yozgan kanal orqali yuboradi → natijani platform'ga qaytaradi.

```
commerce: order confirm TX ──▶ notifications.request(customer.order_confirmed, recipient=conversation)  [o'sha TX]
                              ──▶ platform.notification_intents (PENDING, dedup kaliti) + outbox
outbox_worker ──▶ (xodim) arq: notifications_deliver_staff ──▶ realtime / tizim Telegram boti
             └─▶ (xaridor) platform.notification.customer_delivery_requested
                   ──▶ messaging subscriber ──▶ notifications.get_rendered(intent_id)
                   ──▶ arq: channel_send (Instagram oynasi, Telegram limitlari) ──▶ notifications.mark_result(SENT|FAILED|SUPPRESSED)
```

## 3. Kontrakt

```python
# app/platform/notifications/services/notification_service.py
async def request(
    self,
    req: NotificationRequest,        # template_key, recipient, variables, aggregate_type, aggregate_id, aggregate_version, priority
    actor: ActorContext,
    db: AsyncSession,                # chaqiruvchi domen tranzaksiyasi — intent u bilan birga COMMIT bo'ladi
) -> NotificationIntentId: ...

async def get_rendered(self, intent_id: UUID, db: AsyncSession) -> RenderedMessage: ...   # matn, locale, template_version
async def mark_result(self, intent_id: UUID, result: DeliveryResult, db: AsyncSession) -> None: ...
```

`recipient` turlari:
- `CustomerConversation(conversation_id)` — xaridor, o'z kanali orqali;
- `Staff(principal_id)` yoki `StaffRole(role, branch_id?)` — xodim(lar);
- `StaffAssigneeOrRole(principal_id?, fallback_role)` — biriktirilgan bo'lsa unga, aks holda rolga.

`variables` — faqat formatlangan qiymatlar (`order_number`, `total` — `Money`, `items_summary`); xaridor telefoni yoki manzili yuborilmaydi.

## 4. Qoidalar

1. **Bir hodisa — bitta xabar** (BL-060). Dedup kaliti: `UNIQUE (shop_id, template_key, aggregate_type, aggregate_id, aggregate_version, recipient_key)`. Event 3 marta kelsa ham intent bitta.
2. **Holat (FSM-12):**
   ```
   PENDING ──(navbatga qo'yildi)──▶ SCHEDULED ──(yuborildi)──▶ SENT
   SCHEDULED ──(xato, qayta urinish)──▶ SCHEDULED   [5 martagacha, eksponensial]
   SCHEDULED ──(5 marta xato)──▶ FAILED   [xodimga vazifa, BL-062]
   PENDING ──(xaridor rad etgan / kanal qoidasi ruxsat bermaydi)──▶ SUPPRESSED
   ```
   O'tishlar `platform/use` orqali (ADR-034).
3. **Xaridorga faqat tranzaksion xabarlar** — buyurtma holati, operator javobi. Marketing Stage 1 da yo'q (BL-061).
4. **Instagram 24 soatlik javob oynasi** — `messaging` tekshiradi; yopiq bo'lsa `SUPPRESSED` + xodimga `staff.instagram_window_closed` (`13` §3).
5. **Xodim tinch soatlari** — xodim sozlamasi; `HIGH` muhimlikdagilar bundan mustasno.
6. **Retry egasi:** xodim yetkazishi — `platform` arq vazifasi; xaridor yetkazishi — `messaging` `channel_send` vazifasi (bitta retry siyosati, `13`). Natija har doim `mark_result` orqali qaytadi.
7. **Taqiq:** xaridor shablonlarida "to'landi", "yetkazildi" (tizim tasdiqlamasa), chegirma va'dasi yo'q.
8. Har yuborilgan xabarda `template_key`, `locale`, `template_version` saqlanadi.

## 5. Shablonni tanlash va tahrirlash

1. Tanlash tartibi: shop override (xaridor tilida) → platforma default (xaridor tilida) → platforma default (`uz`).
2. Til: xaridor suhbatining `locale` qiymati (`messaging` — `get_rendered` chaqiruvida beradi); xodim — profil tili.
3. Shop tahrirlay oladigan kalitlar: `customer.*` (ruxsat `shops.settings.edit`, ega). Xodim shablonlari — faqat platforma.
4. Tahrirda tekshiruv: majburiy o'zgaruvchilar saqlangan, ≤ 1000 belgi, taqiqlangan iboralar yo'q. Har tahrir — yangi `version`, audit.
5. Formatlash (summa, sana) — `11-api-conventions-errors-i18n.md` qoidalari; o'zbek kirill (`uz-Cyrl`) — lotin matnidan transliteratsiya + qo'lda tekshiruv.

Jadvallar (`platform` schemasi): `message_templates` (`key`, `locale`, `version`, `body`, `required_vars`, `shop_id NULL` = default), `notification_intents`, `notification_deliveries` (urinishlar), `staff_tasks`, `staff_notification_settings`.

## 6. Trigger matritsasi (kim chaqiradi)

| `template_key` | Trigger | Kim `request()` chaqiradi | Qabul qiluvchi |
|---|---|---|---|
| `customer.ai_greeting` | Suhbatning birinchi xabari / `/start` | `messaging` (yangi suhbat ochilganda) | Xaridor |
| `customer.order_received` | `commerce.order.drafted` (AI yoki sayt) | `commerce` (qoralama yaratish service'i) | Xaridor |
| `customer.handoff_notice` | `messaging.conversation.handed_off` | `messaging` | Xaridor |
| `customer.handoff_after_hours` | handoff ish vaqtidan tashqarida | `messaging` | Xaridor |
| `customer.order_confirmed` | `commerce.order.confirmed` | `commerce` (confirm TX) | Xaridor |
| `customer.order_processing` | `commerce.order.processing` | `commerce` | Xaridor |
| `customer.order_ready_pickup` | `commerce.order.ready` (PICKUP) | `commerce` | Xaridor |
| `customer.order_completed` | `commerce.order.completed` | `commerce` | Xaridor |
| `customer.order_cancelled` | `commerce.order.cancelled` | `commerce` | Xaridor |
| `customer.quote_sent` | `commerce.quote.sent` | `commerce` | Xaridor |
| `customer.quote_expired` | `commerce.quote.expired` | `commerce` (rejali ish) | Xaridor |
| `customer.price_changed` | Tasdiqlashda `PRICE_CHANGED`, operator yuborishni tasdiqladi | `commerce` | Xaridor |
| `staff.new_order` | `commerce.order.drafted` / `commerce.order.submitted` | `commerce` | Biriktirilgan operator, bo'lmasa menejerlar |
| `staff.handoff` | `messaging.conversation.handed_off` | `messaging` | Biriktirilgan operator / navbat |
| `staff.order_confirm_reminder` | 24 soat `PENDING_CONFIRMATION` (DEC-104) | `commerce` rejali ishi | Operator, menejer |
| `staff.reservation_review` | 72 soat faol band qilish (DEC-104) | `commerce` rejali ishi | Menejer |
| `staff.quote_approval_needed` | `commerce.quote.approval_requested` | `commerce` | Menejer, ega |
| `staff.discount_approval_needed` | Limitdan katta chegirma so'rovi (DEC-110) | `commerce` | Menejer / ega |
| `staff.stock_low` | `available` ≤ chegara (kunlik guruhlangan) | `commerce` rejali ishi | Omborchi, ega |
| `staff.channel_degraded` | `messaging.channel.disconnected` | `messaging` | Ega |
| `staff.instagram_window_closed` | Javob oynasi yopiq, xabar yuborilmadi | `messaging` | Biriktirilgan operator |
| `staff.ai_budget_warning` | AI limitining 80% / 100% (`platform.ai_quota.exhausted`) | `platform/billing` | Ega |
| `staff.spec_request_done` | Spec kutubxonasiga model qo'shildi (DEC-120) | `catalog` | So'rov yuborgan xodim |
| `staff.notification_failed` | Intent `FAILED` | `platform/notifications` | Biriktirilgan operator, menejer |
| `staff.support_case_opened` | `support.case.opened` | `support` | Menejer |

Eslatmalar hech narsani avtomatik bekor qilmaydi (`../business/05`, 4-qism).

## 7. Xaridorga xabarlar matni

O'zgaruvchilar: `{shop_name}`, `{order_number}` (`A-1042`), `{total}` (formatlangan so'm), `{items_summary}`, `{fulfillment_line}`, `{shop_address}`, `{shop_phone}`, `{quote_url}`, `{valid_until}`, `{hours}`, `{reason_line}`, `{sku_title}`, `{old}`, `{new}`.

`{fulfillment_line}`: PICKUP — "Olib ketish: {shop_address}"; DELIVERY — "Yetkazish bo'yicha operator siz bilan kelishadi." (DEC-113, DEC-100h).

| `template_key` | uz (default) |
|---|---|
| `customer.ai_greeting` | "Assalomu alaykum! Men {shop_name} do'konining AI yordamchisiman. Mahsulot tanlash va narxlar bo'yicha yordam beraman. Istalgan payt operatorni chaqirishingiz mumkin." |
| `customer.order_received` | "Buyurtmangiz qabul qilindi: {items_summary}. Operatorimiz tez orada siz bilan bog'lanib, mavjudligini tasdiqlaydi." |
| `customer.handoff_notice` | "Savolingizni operatorga uzatdim, u tez orada javob beradi." |
| `customer.handoff_after_hours` | "Hozir ish vaqtidan tashqari. Operatorimiz {hours} oralig'ida javob beradi." |
| `customer.order_confirmed` | "Buyurtma {order_number} tasdiqlandi. Jami: {total}. {fulfillment_line}" |
| `customer.order_processing` | "Buyurtma {order_number} tayyorlanmoqda." |
| `customer.order_ready_pickup` | "Buyurtma {order_number} tayyor. Manzil: {shop_address}. Tel: {shop_phone}." |
| `customer.order_completed` | "Xaridingiz uchun rahmat! Savollar bo'lsa, shu yerga yozing." |
| `customer.order_cancelled` | "Buyurtma {order_number} bekor qilindi. {reason_line}Savollar bo'lsa, operatorga yozing." |
| `customer.quote_sent` | "Siz uchun kompyuter taklifi tayyor: {quote_url}. Taklif {valid_until} gacha amal qiladi." |
| `customer.quote_expired` | "Taklif muddati tugadi. Narxlar o'zgargan bo'lishi mumkin — yangilangan taklif uchun yozing." |
| `customer.price_changed` | "{sku_title} narxi o'zgardi: {old} → {new}. Davom ettiramizmi?" |

| `template_key` | ru (default) |
|---|---|
| `customer.ai_greeting` | "Здравствуйте! Я AI-помощник магазина {shop_name}. Помогу с выбором и ценами. Оператора можно позвать в любой момент." |
| `customer.order_received` | "Ваш заказ принят: {items_summary}. Оператор скоро свяжется с вами и подтвердит наличие." |
| `customer.handoff_notice` | "Передал ваш вопрос оператору, он скоро ответит." |
| `customer.order_confirmed` | "Заказ {order_number} подтверждён. Итого: {total}. {fulfillment_line}" |
| `customer.order_ready_pickup` | "Заказ {order_number} готов. Адрес: {shop_address}. Тел.: {shop_phone}." |
| `customer.order_cancelled` | "Заказ {order_number} отменён. {reason_line}Если есть вопросы, напишите оператору." |

| `template_key` | en (default) |
|---|---|
| `customer.ai_greeting` | "Hello! I'm the AI assistant of {shop_name}. I can help with products and prices. You can ask for a human operator at any time." |
| `customer.order_received` | "Your order has been received: {items_summary}. Our operator will contact you shortly to confirm availability." |
| `customer.handoff_notice` | "I've passed your question to an operator; they'll reply shortly." |
| `customer.order_confirmed` | "Order {order_number} is confirmed. Total: {total}. {fulfillment_line}" |

Qolgan kalitlarning ru/en matnlari seed faylida (`app/db/seed/platform_seed.py`) to'liq beriladi. Rus va ingliz matnlari tarjimon tomonidan tekshiriladi.

## 8. Xodimlarga bildirishnomalar matni (uz)

| `template_key` | Muhimlik | Matn |
|---|---|---|
| `staff.new_order` | Yuqori | "Yangi buyurtma ({channel}): {items_summary}. Xaridor: {customer_label}." |
| `staff.handoff` | Yuqori | "Operator kerak ({reason}): {conversation_link}" |
| `staff.order_confirm_reminder` | O'rta | "{order_number} buyurtma {hours} soatdan beri tasdiq kutmoqda." |
| `staff.reservation_review` | O'rta | "{order_number}: mahsulot {days} kundan beri band. Bekor qilinsinmi?" |
| `staff.quote_approval_needed` | Yuqori | "PC taklifi tasdiq kutmoqda: {quote_link} ({reason})." |
| `staff.discount_approval_needed` | Yuqori | "{requested}% chegirma so'raldi ({order_number}). Tasdiqlaysizmi?" |
| `staff.stock_low` | Past (kunlik) | "Kam qolgan mahsulotlar: {count} ta. {list_link}" |
| `staff.channel_degraded` | Yuqori | "{channel} ulanishida muammo: {reason}. Qayta ulang: {link}" |
| `staff.instagram_window_closed` | O'rta | "Instagram'da {customer_label} ga javob oynasi yopildi — boshqa yo'l bilan bog'laning." |
| `staff.ai_budget_warning` | O'rta | "AI limitining {percent}% ishlatildi." |
| `staff.spec_request_done` | Past | "{model} spetsifikatsiyasi qo'shildi, SKU'larni bog'lashingiz mumkin." |
| `staff.notification_failed` | Yuqori | "Xaridorga xabar yuborilmadi ({template}): {conversation_link}. Qo'lda bog'laning." |
| `staff.support_case_opened` | O'rta | "Yangi kafolat murojaati: {case_link}." |

`{customer_label}` — xaridor ismi yoki kanal taxallusi; xodim dashboard'ida ko'rsatiladi, tizim Telegram botiga faqat qisqartirilgan holda (`Ali K.`) yuboriladi.

## 9. Xodim vazifalari

`platform.staff_tasks` — "kimdir biror narsa qilishi kerak" degan yozuvlar: tasdiq kutayotgan buyurtma, yuborilmagan xabar, band qilishni ko'rib chiqish. Vazifa `aggregate_type/id` ga bog'langan; aggregate holati o'zgarganda vazifani yaratgan domen `notifications.resolve_tasks(aggregate)` ni chaqiradi. Dedup — xuddi intent kabi.

## 10. API

| Surface | Endpoint | Ruxsat |
|---|---|---|
| `shop` | `GET /api/v1/shop/notifications` (cursor) | autentifikatsiya |
| `shop` | `POST /api/v1/shop/notifications/{id}/read` | autentifikatsiya |
| `shop` | `GET /api/v1/shop/tasks`, `POST /api/v1/shop/tasks/{id}/done` | autentifikatsiya, rol bo'yicha |
| `shop` | `GET/PUT /api/v1/shop/settings/message-templates/{key}` | `shops.settings.edit` |
| `shop` | `PUT /api/v1/shop/me/notification-settings` | o'zi |
| WS | `notification.created`, `task.created` (`08-cache-and-realtime.md`) | — |

## 11. Kuzatuv

- `cos_platform_notification_intents_total{template_key,result}`.
- `cos_platform_notification_delivery_seconds` — intent'dan `SENT` gacha.
- Alert: `FAILED` ulushi > 5% (1 soat), yoki `SCHEDULED` 15 daqiqadan eski.

## 12. Testlar

| ID | Sinov | Natija |
|---|---|---|
| TC-NOT-01 | `commerce.order.confirmed` 3 marta (replay) | Xaridorga bitta xabar |
| TC-NOT-02 | Xaridor ruscha yozgan | `customer.order_confirmed` ruscha |
| TC-NOT-03 | Shop override'dan `{order_number}` olib tashlandi | Saqlash rad etiladi |
| TC-NOT-04 | Instagram oynasi yopiq, `order.confirmed` | Xaridorga yuborilmaydi (`SUPPRESSED`), `staff.instagram_window_closed` |
| TC-NOT-05 | Telegram 5 marta xato | `FAILED`, xodimga vazifa, retry to'xtaydi (TC-032 bilan) |
| TC-NOT-06 | Confirm TX rollback bo'ldi | Intent ham yo'q (xabar ketmaydi) |
| TC-NOT-07 | A shop intent'i | B shop xodimiga ko'rinmaydi (TC-ISO) |
| TC-NOT-08 | import-linter | `platform.notifications` hech qaysi `app.domains` ni import qilmaydi |

## Keyingi qadam

→ [13-integrations-and-channels.md](13-integrations-and-channels.md) — xaridorga kanal orqali yuborish
→ [08-cache-and-realtime.md](08-cache-and-realtime.md) — dashboard bildirishnomalari
