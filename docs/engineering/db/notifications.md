# Xabarnomalar, xodim vazifalari, platforma boti (`platform/notifications`, S2-06)

> **Holat:** taklif, 2026-10-26 — qarorlar qabul qilingan (founder topshirig'i bilan), **founder ko'rib chiqishi kutilmoqda**. Qarorlar oxirida. Diagramma: [`notifications.dbml`](notifications.dbml) (platform schemasiga qo'shiladigan jadvallar; `shops`, `memberships`, `branches`, `principals` — diagramma uchun qisqa nusxa, to'liq tavsifi [platform.md](platform.md) da).
> **Kim o'qiydi:** founder va dasturchilar.
> **Batafsil mexanizm:** [20-notifications.md](../20-notifications.md) — matnlar va trigger jadvali o'sha yerda.

Misollarda **"TechPC"**: ega **Ali**, menejer **Vali**, operator **Dilshod**, omborchi **Bobur**, xaridor **Jasur**.

---

## 0. Asosiy g'oya

- **Qachon xabar ketishini domen hal qiladi**, qanday yetkazishni — platforma. Buyurtma tasdiqlanganda `commerce` o'z tranzaksiyasida "xaridorga `customer.order_confirmed` kerak" deydi. Matnni topish, tilni tanlash, takrordan himoya va yuborish holatini platforma yuritadi (20 §2).
- **Bir hodisa — bitta xabar** (BL-060). Event 3 marta kelsa ham Jasurga bitta xabar ketadi.
- **Xodimga ikki joyga:** panel (real vaqtda, darhol) va platformaning Telegram boti. Bot — bitta, platformaniki, shop botlaridan alohida. Xodim uni bir marta bog'laydi (DEC-129).
- **Xaridorga** — o'zi yozgan kanal orqali (Telegram, Instagram, sayt chati), `messaging` yuboradi.
- **Hech narsa avtomatik bekor qilinmaydi.** Eslatma va vazifa faqat odamni chaqiradi (business/05, 4-qism).

```
commerce: buyurtma tasdiqlandi ──▶ notifications.request(customer.order_confirmed) ──▶ platform.notifications (PENDING) + outbox
   ──▶ xaridorga: platform.notification.customer_delivery_requested ──▶ messaging yozadi va yuboradi ──▶ SENT / FAILED / SUPPRESSED
   ──▶ xodimga: panel (WebSocket signal) + platforma boti (arq: notification_send)
```

---

## 1. `shop_message_templates` — shop o'zgartirgan matnlar

**Nima uchun kerak:** Ali xaridorga ketadigan matnni o'z ohangiga moslamoqchi: "Buyurtma {order_number} tasdiqlandi" o'rniga "Rahmat, Jasur aka! {order_number} tayyorlanmoqda...".

- **`template_key`** — faqat `customer.*` kalitlar; xodim matnlari faqat platformaniki (20 §5).
- **`locale`** — `uz`, `ru`, `en`.
- **`version`**, **`is_active`** — har tahrir yangi versiya, bittasi faol. Audit bilan.
- **`body`** — 1000 belgigacha. Majburiy o'zgaruvchi (`{order_number}`) o'chirilsa saqlanmaydi (TC-NOT-03). Taqiqlangan iboralar ("to'landi", chegirma va'dasi) tekshiriladi.
- **`created_by`** — ega (`shops.settings.edit`).

**Platforma standart matnlari bazada emas, kodda** (**1-qaror**): tarjima fayllarida, versiyasi bilan.
**Tanlash tartibi:** shop matni (xaridor tilida) → standart (xaridor tilida) → standart (o'zbekcha).
**RLS:** ha.

**5b da qurilgani (2026-10-26):** migratsiya `platform_0010`; ustunlar DBML bo'yicha (`template_key`, `locale`, `version`, `body`, `is_active`, `created_by`, `created_at`), faol versiya — qisman unikal indeks (`uq_shop_message_templates_active`), CHECK: faqat `customer.*`, til `uz/ru/en`, 1–1000 belgi, versiya > 0. Saqlash advisory lock bilan (parallel saqlashda versiya to'qnashmaydi). Standart matnlar — `app/platform/notifications/customer_templates.py`. Farq: taqiqlangan iboralar tekshiruvi hali yo'q (7-modul bilan); `DELETE` — standartga qaytarish (faol versiya o'chiriladi, tarix qoladi).

---

## 2. `notifications` — xabarnoma

**Nima uchun kerak:** har yuborilgan (yoki yuborilmagan) xabarning yozuvi: qaysi hodisa, qaysi matn, kimga, qanday natija. Xodimning "bildirishnomalar markazi" ham shu jadval.

**Har qabul qiluvchiga bitta qator** (**2-qaror**). "Menejerlarga" deb so'ralsa, hozirgi har menejerga alohida qator — har biri o'zi o'qiydi.

- **`template_key`**, **`template_version`**, **`locale`** — qaysi matn, qaysi versiya, qaysi tilda (20 §4, 8-qoida).
- **`recipient_type`** — xaridor yoki xodim. *5b:* xaridor xabarlari hozircha bu jadvalga yozilmaydi — yozuv `messaging.messages` da (yetkazish holati, lenta); `customer_delivery_requested` oqimi o'rniga `messaging` buyurtma event'ini o'zi tinglaydi (progress/M05b 5-qaror).
- **`recipient_membership_id`** — xodim bo'lsa, kim.
- **`conversation_id`** — xaridor bo'lsa, qaysi suhbat orqali.
- **`priority`** — yuqori (tinch soatga qaramaydi), o'rta, past (kunlik guruhlanadi).
- **`aggregate_type`**, **`aggregate_id`**, **`aggregate_version`** — qaysi hodisa: `commerce.order`, buyurtma ID'si, versiyasi.
- **`variables`** — matnga qo'yiladigan tayyor qiymatlar: buyurtma raqami, summa, mahsulotlar qisqacha. **Telefon va manzil yo'q.**
- **`title`**, **`body`** — tayyor matn. Xodim panelida shundan ko'rsatiladi.
- **`dedup_key`** — takror himoyasi: `kalit:obyekt:id:versiya:qabul qiluvchi`. Unikal.
- **`status`** — FSM-12, tashqi yetkazish holati:
  ```
  Kutilmoqda (PENDING) ──(navbatga qo'yildi)──▶ Rejalashtirilgan (SCHEDULED) ──(yuborildi)──▶ Yuborildi (SENT)
  SCHEDULED ──(xato)──▶ SCHEDULED                [5 martagacha, kutish oshib boradi]
  SCHEDULED ──(5 marta xato)──▶ Yuborilmadi (FAILED)   [xodimga vazifa, BL-062]
  PENDING ──(yuborib bo'lmaydi)──▶ To'xtatildi (SUPPRESSED)
  ```
  Xodim uchun: panelda **doim** ko'rinadi; status — platforma botiga yetkazish. Botni bog'lamagan xodimda `SUPPRESSED` (`NOT_LINKED`), lekin panelda bor.
- **`attempts`**, **`last_error_code`**, **`scheduled_at`** (tinch soatdan keyin), **`sent_at`**, **`failed_at`**.
- **`suppressed_reason`** — nega yuborilmadi: Instagram oynasi yopiq, xaridor bloklagan, xodim botni bog'lamagan, xodim o'chirib qo'ygan.
- **`read_at`** — xodim panelda o'qigan vaqt.

**Saqlash:** 90 kun (taklif).
**RLS:** ha.

**Misol:** Dilshod #1042 ni tasdiqladi. Bitta tranzaksiyada: buyurtma `CONFIRMED` + `notifications` da Jasur uchun `customer.order_confirmed` (Jasur suhbatining tili — ruscha) + outbox. Event uchinchi marta kelsa ham `dedup_key` tufayli qator bitta. `messaging` ruscha matnni Telegram'ga yubordi → `SENT`.

---

## 3. `staff_tasks` — xodim vazifasi

**Nima uchun kerak:** "kimdir biror narsa qilishi kerak" degan yozuv: tasdiq kutayotgan buyurtma, 72 soat olib ketilmagan band, operator kutayotgan suhbat, yuborilmagan xabar. Xabarnomadan farqi — vazifa **bajarilguncha** ochiq turadi.

- **`type`** — `ORDER_CONFIRM_REMINDER`, `RESERVATION_REVIEW`, `HANDOFF`, `DISCOUNT_APPROVAL`, `ADJUSTMENT_APPROVAL`, `NOTIFICATION_FAILED`, `INSTAGRAM_WINDOW_CLOSED`, `CHANNEL_DEGRADED`, `STOCK_LOW`, `IMPORT_REVIEW`.
- **`subject_type`**, **`subject_id`** — nimaga tegishli: buyurtma, band, suhbat.
- **`branch_id`** — filial. Filial doirasidagi xodim faqat o'z filiali vazifalarini ko'radi.
- **`assignee_membership_id`** yoki **`assignee_role`** — aniq xodimga (biriktirilgan operator) yoki rolga ("menejerlar").
- **`priority`**, **`due_at`**, **`params`** (ekran uchun: buyurtma raqami, soat — PII yo'q).
- **`dedup_key`** — `order_reminder:{order_id}:24h`. Rejali ish ikki marta ishlasa ham vazifa bitta (06 §5.1).
- **`status`** — ochiq → bajarildi (xodim belgiladi) / hal bo'ldi (sabab yo'qoldi: buyurtma tasdiqlandi) / bekor.
- **`resolved_by`**, **`resolved_at`**, **`version`**.

**Kim yopadi:** vazifani yaratgan domen. Buyurtma tasdiqlansa, commerce "tasdiq eslatmasi" vazifasini o'zi `RESOLVED` qiladi (`resolve_tasks`).
**Kim oladi va "bajarildi" deydi** (QA 5a F8): vazifa turi bo'yicha — tasdiq vazifalari (tuzatish, chegirma, band muddati, ombor farqi, eskirgan kurs) faqat ega va menejer; "tasdiq eslatmasi" — operator ham. So'rov egasi (`params.requested_by`) o'z tasdiq vazifasini ololmaydi va yopolmaydi. Batafsil — engineering/20 §9.
**3-modul bilan bog'liqlik:** hozirgi "Ko'rib chiqish kerak" ro'yxati (sahifada hisoblanadi) shu vazifalarga o'tadi — menejer qarori ("Kutamiz" / "Bekor") o'zgarmaydi.
**RLS:** ha.

**Misol:** #1050 24 soatdan beri tasdiq kutyapti. Scheduler Dilshodga `ORDER_CONFIRM_REMINDER` vazifasini va xabarnomani yaratdi. Dilshod tasdiqladi → vazifa o'zi `RESOLVED`.

---

## 4. `staff_notification_settings` — xodim sozlamasi

- **`quiet_from`**, **`quiet_to`** — tinch soatlar (shop vaqti). Yuqori muhimlikdagilar bundan mustasno.
- **`telegram_enabled`** — platforma boti orqali ham olsinmi.
- **`muted_types`** — o'chirilgan o'rta/past turlar.

Yozuv yo'q bo'lsa — standart: tinch soat yo'q, bot yoqilgan.

---

## 5. `staff_telegram_links` va `telegram_link_codes` — platforma botiga ulanish

**Nima uchun kerak:** Dilshod buyurtma xabarlarini telefonidagi Telegram'da olmoqchi.

```
Panel: "Telegram'ga ulash" ──▶ bir martalik kod (10 daqiqa) ──▶ Dilshod botga /start <kod> yozadi
   ──▶ kod xeshi topildi, ishlatilmagan ──▶ staff_telegram_links (Dilshod ↔ Telegram ID) ──▶ kod "ishlatildi"
```

- **`staff_telegram_links`**: **`principal_id`** (odam, shop emas — bot hamma shop uchun bitta), **`telegram_user_id`**, **`telegram_chat_id`**, **`linked_at`**, **`unlinked_at`** (xodim uzdi yoki botni blokladi), **`last_error_code`**.
- **`telegram_link_codes`**: **`code_hash`** (kodning o'zi saqlanmaydi), **`expires_at`**, **`used_at`**.

**Platforma boti tokeni** — muhit sozlamasida, bazada emas (**4-qaror**).
**RLS:** "o'zim" varianti (`principal_id` = joriy odam).

---

## 6. Realtime (WebSocket) — jadval yo'q

Panelga signal (08 §6): ticket — Redis db2 (bir martalik, 30 soniya), tarqatish — Redis pub/sub. Signal ichida matn va xaridor ma'lumoti yo'q — faqat "suhbat X o'zgardi, versiya 18". Klient ma'lumotni REST'dan oladi.

Signal yo'qolsa ham ma'lumot yo'qolmaydi: klient qayta ulanganda ro'yxatlarni qayta yuklaydi (**3-qaror**).

---

## 7. Boshqa schemalarga takliflar (fayllarga hali tegilmagan)

- **`platform.shop_policies.handoff_reminder_minutes`** (standart 15) — "operator kutayotgan suhbat" eslatmasi (business/05, 4-qism: "shop sozlaydi").
- **`platform.shop_policies.inbox_hours`** (ixtiyoriy, jsonb) — ish vaqtidan tashqari handoff'da `customer.handoff_after_hours` matni uchun. Bo'sh — doim ish vaqti.
- **`platform.file_purpose`** ga **`CHAT_ATTACHMENT`** (yopiq) — suhbat biriktirmalari ([messaging.md](messaging.md) §6).

---

## engineering/07 §4.1 va 20 dan farqlar

- **`message_templates` → `shop_message_templates`**: faqat shop matnlari; standart matnlar kodda (**1-qaror**).
- **`notification_intents` + `notification_deliveries` (20) → bitta `notifications`** (07 dagi nom), har qabul qiluvchiga qator (**2-qaror**). `title`, `body`, `read_at`, `priority`, `scheduled_at`, `suppressed_reason` qo'shildi.
- **`staff_tasks`**: `assignee_role`, `branch_id`, `params`, `priority`, `dedup_key`, `resolved_*`, `version` qo'shildi; `RESOLVED` holati (domen yopgan).
- **Yangi:** `staff_notification_settings` (20 §5 da tilga olingan), `staff_telegram_links`, `telegram_link_codes` (20 §2 dagi bog'lash oqimi).

---

## Founder ko'rib chiqishi uchun qarorlar

Founder 2026-10-26 da ishni to'xtatmasdan davom ettirishni topshirgan. Qarorlar qabul qilingan, o'zgarsa kod moslanadi.

**1. Platforma standart matnlari kodda, bazada faqat shop o'zgartirganlari.**
- Nega: standart matnlar dastur bilan birga versiyalanadi, PR'da tekshiriladi, tarjima jarayoni oddiy; bazada "kim o'zgartirdi" chalkashligi yo'q.
- Muqobil: hammasi bazada (20 dagi `message_templates`, `shop_id NULL` = standart). Afzallik — platforma admini matnni deploysiz o'zgartiradi. Kamchilik — matn va kod versiyasi ajralib ketadi.

**2. Bitta `notifications` jadvali, har qabul qiluvchiga qator.**
- Nega: xodim bildirishnomalar markazi, o'qilganlik va yetkazish holati bitta joyda; Stage 1 da har xabar uchun bitta tashqi kanal.
- Muqobil: `notification_intents` + `notification_deliveries` (20). Afzallik — bitta xabar bir nechta kanalga (panel + bot + SMS) alohida holat bilan. Kamchilik — ikki jadval, murakkabroq.

**3. Realtime uchun jadval yo'q.**
- Tanlov: tartib raqami Redis'da, bo'shliqda klient ro'yxatni qayta yuklaydi (08 §6.5 ikkinchi yo'li).
- Muqobil: `realtime_changes` jadvali (bo'shliqni aniq to'ldirish uchun). Afzallik — aniq. Kamchilik — har o'zgarishda qo'shimcha yozuv.

**4. Platforma boti — bitta, tokeni muhit sozlamasida; xodim bir martalik kod bilan bog'laydi.**
- Nega: DEC-129 va 20 §2 dagi oqim; kodning faqat xeshi saqlanadi.
- Muqobil: har shop o'z boti orqali xodimlarga ham yozadi. Kamchilik — xodim bir nechta botni kuzatadi, shop boti xaridorlar uchun.

**5. Suhbat eslatmasi va ish vaqti shop sozlamasida** (`handoff_reminder_minutes = 15`, `inbox_hours` ixtiyoriy).
- Nega: business/05 "shop sozlaydi" deydi; 20 dagi `customer.handoff_after_hours` matni ish vaqtini talab qiladi.
- Muqobil: platforma bo'yicha bitta qiymat. Kamchilik — shoplar ish tartibi har xil.
