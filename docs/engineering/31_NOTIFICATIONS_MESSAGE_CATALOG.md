# TECH-31 — Xabarnomalar va xabar shablonlari katalogi

**Status:** Baseline (2026-10-22). M17, BL-060…062, FSM-12, `business/09` (trigger matritsasi), TECH-24 §5.6 (`message_templates`).
**Kim uchun:** backend (engagement context), founder (matnlarni tahrirlash), frontend (in-app bildirishnomalar).

Matnlar — platforma default'lari. Merchant o'z ohangiga moslab override qilishi mumkin (o'zgaruvchilar saqlanishi shart). Rus va ingliz matnlari tarjimon tomonidan tekshiriladi.

---

## 1. Kanallar va qoidalar

| Qabul qiluvchi | Kanal | Qoida |
|---|---|---|
| Xaridor | xaridor yozgan kanal (Telegram / Instagram / web chat) | Faqat tranzaksion xabarlar (buyurtma holati, operator javobi). Marketing — Stage 1 da yo'q (BL-036, BL-061). Instagram'da javob oynasi qoidasi (TECH-30 §3.3) |
| Xodim | in-app (dashboard) + ixtiyoriy Telegram (xodim o'z akkauntini bog'laydi) | Muhimlik bo'yicha; `quiet hours` xodim sozlamasi (yuqori muhimlikdagilar bundan mustasno) |

**Dedup kaliti:** `(merchant_id, template_key, aggregate_id, aggregate_version, recipient)` — bir hodisa uchun bitta xabar (BL-060). Xato: cheklangan retry (5 marta, backoff), keyin `FAILED` + operator vazifasi (BL-062, FSM-12).

**O'zgaruvchilar:** `{shop_name}`, `{order_number}` (masalan, `A-1042`), `{total}` (formatlangan UZS), `{items_summary}`, `{fulfillment_method}`, `{shop_address}`, `{shop_phone}`, `{tracking_url}`, `{operator_name}`, `{hours}`. Formatlash TECH-24 §5.7 bo'yicha.

## 2. Xaridorga xabarlar

| `template_key` | Trigger | uz (default) |
|---|---|---|
| `customer.ai_greeting` | birinchi xabar / `/start` | "Assalomu alaykum! Men {shop_name} do'konining AI yordamchisiman. Mahsulot tanlash va narxlar bo'yicha yordam beraman. Istalgan payt operatorni chaqirishingiz mumkin." |
| `customer.order_received` | `order.created` (`DRAFT`, AI yoki sayt) | "Buyurtmangiz qabul qilindi: {items_summary}. Operatorimiz tez orada siz bilan bog'lanib, mavjudligini tasdiqlaydi." |
| `customer.handoff_notice` | `chat.request_handoff` | "Savolingizni operatorga uzatdim, u tez orada javob beradi." |
| `customer.handoff_after_hours` | handoff ish vaqtidan tashqarida | "Hozir ish vaqtidan tashqari. Operatorimiz {hours} oralig'ida javob beradi." |
| `customer.order_confirmed` | `order.confirmed` | "Buyurtma {order_number} tasdiqlandi. Jami: {total}. {fulfillment_line}" |
| `customer.order_processing` | `order.processing` | "Buyurtma {order_number} tayyorlanmoqda." |
| `customer.order_ready_pickup` | merchant "olib ketishga tayyor" belgisi (PICKUP) | "Buyurtma {order_number} tayyor. Manzil: {shop_address}. Tel: {shop_phone}." |
| `customer.order_completed` | `order.completed` | "Xaridingiz uchun rahmat! Savollar bo'lsa, shu yerga yozing." |
| `customer.order_cancelled` | `order.cancelled` | "Buyurtma {order_number} bekor qilindi. {reason_line}Savollar bo'lsa, operatorga yozing." |
| `customer.quote_sent` | `quote.sent` (PC) | "Siz uchun kompyuter taklifi tayyor: {quote_url}. Taklif {valid_until} gacha amal qiladi." |
| `customer.quote_expired` | `quote.expired` | "Taklif muddati tugadi. Narxlar o'zgargan bo'lishi mumkin — yangilangan taklif uchun yozing." |
| `customer.price_changed` | confirm paytida `PRICE_CHANGED` (operator tasdiqlab yuboradi) | "{sku_title} narxi o'zgardi: {old} → {new}. Davom ettiramizmi?" |

`{fulfillment_line}`: PICKUP — "Olib ketish: {shop_address}"; DELIVERY — "Yetkazish bo'yicha operator siz bilan kelishadi." (DEC-113, DEC-100h).

### ru (default)

| `template_key` | ru |
|---|---|
| `customer.ai_greeting` | "Здравствуйте! Я AI-помощник магазина {shop_name}. Помогу с выбором и ценами. Оператора можно позвать в любой момент." |
| `customer.order_received` | "Ваш заказ принят: {items_summary}. Оператор скоро свяжется с вами и подтвердит наличие." |
| `customer.handoff_notice` | "Передал ваш вопрос оператору, он скоро ответит." |
| `customer.order_confirmed` | "Заказ {order_number} подтверждён. Итого: {total}. {fulfillment_line}" |
| `customer.order_ready_pickup` | "Заказ {order_number} готов. Адрес: {shop_address}. Тел.: {shop_phone}." |
| `customer.order_cancelled` | "Заказ {order_number} отменён. {reason_line}Если есть вопросы, напишите оператору." |

### en (default)

| `template_key` | en |
|---|---|
| `customer.ai_greeting` | "Hello! I'm the AI assistant of {shop_name}. I can help with products and prices. You can ask for a human operator at any time." |
| `customer.order_received` | "Your order has been received: {items_summary}. Our operator will contact you shortly to confirm availability." |
| `customer.handoff_notice` | "I've passed your question to an operator; they'll reply shortly." |
| `customer.order_confirmed` | "Order {order_number} is confirmed. Total: {total}. {fulfillment_line}" |

Qolgan kalitlarning ru/en matnlari seed faylida (`message_templates` migratsiyasi) to'liq beriladi; bu jadval asosiy namunalar. Kirill yozuvidagi o'zbekcha (`uz-Cyrl`) — lotin matnidan avtomatik transliteratsiya + qo'lda tekshiruv.

**Taqiq:** xaridor shablonlarida "to'landi", "yetkazildi" (tizim buni tasdiqlamasa), chegirma va'dasi yo'q.

## 3. Xodimlarga bildirishnomalar

| `template_key` | Qabul qiluvchi | Muhimlik | Trigger | Matn (uz) |
|---|---|---|---|---|
| `staff.new_order` | biriktirilgan operator, bo'lmasa menejerlar | yuqori | `order.created` / `order.submitted` | "Yangi buyurtma ({channel}): {items_summary}. Xaridor: {customer_label}." |
| `staff.handoff` | biriktirilgan operator / navbat | yuqori | `conversation.handoff_requested` | "Operator kerak ({reason}): {conversation_link}" |
| `staff.order_confirm_reminder` | operator, menejer | o'rta | 24 soat `PENDING_CONFIRMATION` (DEC-104) | "{order_number} buyurtma {hours} soatdan beri tasdiq kutmoqda." |
| `staff.reservation_review` | menejer | o'rta | 72 soat faol rezerv (DEC-104) | "{order_number}: mahsulot {days} kundan beri band. Bekor qilinsinmi?" |
| `staff.quote_approval_needed` | menejer, owner | yuqori | `quotes.request_approval` | "PC taklifi tasdiq kutmoqda: {quote_link} ({reason})." |
| `staff.discount_approval_needed` | menejer / owner | yuqori | limitdan katta chegirma so'rovi (DEC-110) | "{requested}% chegirma so'raldi ({order_number}). Tasdiqlaysizmi?" |
| `staff.stock_low` | omborchi, owner | past (kunlik guruhlangan) | `available` ≤ chegara | "Kam qolgan mahsulotlar: {count} ta. {list_link}" |
| `staff.channel_degraded` | owner | yuqori | kanal `DEGRADED`/`DISCONNECTED` | "{channel} ulanishida muammo: {reason}. Qayta ulang: {link}" |
| `staff.instagram_window_closed` | biriktirilgan operator | o'rta | javob oynasi yopildi | "Instagram'da {customer_label} ga javob oynasi yopildi — boshqa kanal orqali bog'laning." |
| `staff.ai_budget_warning` | owner | o'rta | AI limitining 80% / 100% | "AI limitining {percent}% ishlatildi." |
| `staff.spec_request_done` | so'rov yuborgan xodim | past | spec kutubxonasiga model qo'shildi (DEC-120) | "{model} spetsifikatsiyasi qo'shildi, SKU'larni bog'lashingiz mumkin." |

## 4. Shablonni tanlash va tahrirlash

1. `message_templates` dan: merchant override (xaridor tilida) → platforma default (xaridor tilida) → platforma default (`uz`) (TECH-24 §5.6).
2. Merchant tahrirlay oladigan kalitlar: `customer.*` (Owner, `merchant.settings.write`). Xodim bildirishnomalari — faqat platforma.
3. Tahrir paytida tekshiruv: barcha majburiy o'zgaruvchilar saqlangan, uzunlik ≤ 1000 belgi, taqiqlangan iboralar yo'q. Har tahrir — yangi `version`, audit.
4. Yuborilgan har xabarda `template_key`, `locale`, `version` saqlanadi.

## 5. Testlar

| ID | Sinov | Natija |
|---|---|---|
| TC-NOT-01 | `order.confirmed` event 3 marta (replay) | xaridorga bitta xabar |
| TC-NOT-02 | Xaridor ruscha yozgan | `customer.order_confirmed` ruscha |
| TC-NOT-03 | Merchant override'dan `{order_number}` olib tashlandi | saqlash rad etiladi |
| TC-NOT-04 | Instagram oynasi yopiq paytda `order.confirmed` | xaridorga yuborilmaydi; `staff.instagram_window_closed` |
| TC-NOT-05 | Telegram 5 marta xato | `FAILED`, operator vazifasi, retry to'xtaydi |
