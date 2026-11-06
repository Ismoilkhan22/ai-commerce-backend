# `messaging` schemasi — ma'lumotlar lug'ati (kanallar, suhbatlar, inbox)

> **Holat:** taklif, 2026-10-26 — qarorlar qabul qilingan (founder ishni to'xtatmasdan davom ettirishni topshirgan), **founder ko'rib chiqishi kutilmoqda**. Qarorlar oxirida. Diagramma: [`messaging.dbml`](messaging.dbml) → dbdiagram.io.
> **Kim o'qiydi:** founder va dasturchilar. Har jadval: nima uchun kerak → har maydon nima va nega → bog'lanishlar → misol.
> **Umumiy qoidalar** (`id`, `shop_id`, `(shop_id, id)` bilan bog'lash, `version`, holat matn sifatida, o'chirish yo'qligi) — [platform.md](platform.md) §0. Bu yerda takrorlanmaydi.
> **Hajm:** sayt chati (S2-01), Telegram bot (S2-02), yagona inbox va operatorga uzatish (S2-03), chiquvchi xabar va yetkazish (S2-04), Instagram Direct — flag ostida (S2-05). Fon ishlari va outbox — [jobs.md](jobs.md); xabarnomalar va vazifalar — [notifications.md](notifications.md).

Misollarda **"TechPC"** shopi. Ega — **Ali**, menejer — **Vali**, operator — **Dilshod**. Telegram bot — **@techpc_uz_bot**. Xaridor — **Jasur** (Telegram'da `@jasur_98`). Mahsulot — **"MSI GeForce RTX 4060 Ventus 2X"**.

---

## 0. Bu schemada yangi narsalar

- **Kanal adapteri.** Telegram, Instagram va sayt chati har biri o'z formatida keladi, lekin bazada hammasi bir xil ko'rinadi: xaridor → suhbat → xabarlar. Inbox, AI va operator kanal farqini bilmaydi (13 §1).
- **Webhook avval saqlaydi, keyin o'ylaydi.** Telegram xabar yuborsa, tizim uni bir zumda bazaga yozadi va "qabul qildim" deydi. AI javobi keyin, fon vazifasida tayyorlanadi (BL-032). Telegram bir xabarni ikki marta yuborsa, ikkinchisi tashlab yuboriladi (TC-010).
- **"Hozir kim javob beradi?"** Har suhbatda bitta belgi bor: AI yoki operator. Operator "Suhbatni olish"ni bosganda belgi o'zgaradi va **versiya raqami** bittaga oshadi. AI javobi tayyor bo'lsa ham, yuborishdan oldin versiya qayta tekshiriladi — o'zgargan bo'lsa javob tashlanadi (BL-034, TC-009). Buni "fencing" deyiladi.
- **Chiquvchi xabar ham yozuv.** Xaridorga ketadigan har xabar avval bazaga "navbatda" bo'lib yoziladi, keyin fon vazifasi uni Telegram'ga yuboradi. Yuborilmasa — inbox'da "yuborilmadi" belgisi qoladi, xato yo'qolmaydi (TC-011).
- **Shaxsiy ma'lumot.** Xabar matni bazada disk darajasida shifrlangan, faqat o'z shopi operatorlari ko'radi, 12 oydan keyin o'chiriladi. Xaridor bergan telefon raqami alohida ustunda, shifrlangan. Matn log, event, audit va WebSocket signaliga tushmaydi (26).

---

## 1. `channel_accounts` — ulangan kanal

**Nima uchun kerak:** Ali TechPC botini ulaganda tizim bot tokenini va "bu bot qaysi shopniki" degan bog'lanishni saqlaydi. Telegram webhook yuborganda shop **faqat** shu jadval orqali aniqlanadi: URL'dagi `account_ref` → akkaunt → shop. Webhook tanasidagi biror maydon shopni belgilay olmaydi (13 §3).

- **`channel`** — `TELEGRAM`, `INSTAGRAM` yoki `WEB_CHAT`.
- **`status`** — FSM-03:
  ```
  Kutilmoqda (PENDING) ──(token tekshirildi, sinov o'tdi)──▶ Ulangan (CONNECTED)
  Ulangan ──(xatolar ko'p / token muddati yaqin / 24 soat jim)──▶ Muammoli (DEGRADED)   [egaga ogohlantirish]
  Muammoli ──(qayta ulandi yoki tekshiruv o'tdi)──▶ Ulangan
  Ulangan / Muammoli ──(ega uzdi / ruxsat bekor qilindi)──▶ Uzilgan (DISCONNECTED)       [yuborish to'xtaydi]
  ```
  Ruxsatsiz kanalni "ulangan" deb ko'rsatish taqiqlanadi (BL-031).
- **`account_ref`** — webhook manzilidagi tasodifiy, taxmin qilib bo'lmaydigan kod: `/api/v1/webhooks/telegram/{account_ref}`. Yagona himoya emas — Telegram imzosi ham tekshiriladi.
- **`external_account_id`**, **`display_name`** — bot ID'si va `@techpc_uz_bot`.
- **`token_enc`** — bot tokeni, **shifrlangan** (3-moduldagi xaridor telefoni bilan bir xil usul, kalit almashtirish imkoni bilan). API javobida hech qachon qaytmaydi.
- **`webhook_secret_hash`** — Telegram har webhook'da yuboradigan maxfiy so'zning **xeshi**. Kelgan so'z xeshlanib solishtiriladi; so'zning o'zi bazada yo'q.
- **`token_expires_at`**, **`scopes`** — Instagram tokeni muddati va berilgan ruxsatlar. Muddat yaqinlashsa egaga eslatma.
- **`settings`** — tillar, `/start` matni kaliti, Telegram Business flag. Shaxsiy ma'lumot yo'q.
- **`last_webhook_at`**, **`last_health_check_at`**, **`last_error_code`** — kanal sog'ligi. 24 soat jim bo'lsa yoki xato ko'paysa — `DEGRADED`.
- **`connected_by`**, **`connected_at`**, **`disconnected_at`**, **`disconnect_reason`** — kim va qachon uladi/uzdi. Kanalni faqat ega ulaydi (`messaging.channel.connect`).

**Unikal:**
- `account_ref` — global;
- bitta bot bir vaqtda faqat bitta shopda (uzilganlardan tashqari);
- shopda har kanal turidan bitta faol akkaunt (**7-qaror**).

**RLS:** ha, "identity varianti": shop konteksti **yoki** webhook qabul qilinayotgan paytdagi `account_ref` konteksti. Webhook kelganda shop hali noma'lum — xuddi login paytidagi `platform.memberships` kabi (10 §4).

**Misol:** Ali tokenni kiritdi. Tizim Telegram'dan botni tekshirdi (`getMe`), webhook'ni o'rnatdi, sinov o'tdi → `CONNECTED`, `display_name = @techpc_uz_bot`.

---

## 2. `provider_events` — webhook takroridan himoya

**Nima uchun kerak:** Telegram javob kechiksa, xuddi shu update'ni qayta yuboradi. Bu jadval "bu update'ni ko'rganmiz" degan belgini saqlaydi. Ikkinchi marta kelsa — hech narsa qilinmaydi: inbox'da bitta xabar, AI bitta javob beradi (BR-X04).

- **`provider_event_id`** — Telegram `update_id`, Meta `mid`, sayt chatida brauzer yaratgan `client_message_id`.
- **`kind`** — xabar, tahrir, tugma bosildi ("Olaman"), yetkazish belgisi. `COMMENT` — keyingi modul uchun joy (Instagram izohlari, DEC-132).
- **`status`** — saqlandi / e'tiborsiz (guruh chati, botning o'z xabari) / normallashtirib bo'lmadi.
- **`message_id`**, **`error_code`** — natija.

**Xom payload saqlanmaydi** (**5-qaror**): Telegram yuborgan JSON ichida ism, telefon, matn bor. Faqat dedup kaliti va natija qoladi.
**Saqlash:** 30 kun — provayderning qayta yuborish oynasidan ancha uzun.
**RLS:** ha.

---

## 3. `customer_identities` — xaridor kanalda

**Nima uchun kerak:** Jasur Telegram'da yozdi. Tizim uni Telegram ID'si bo'yicha taniydi: keyingi safar yozsa, o'sha suhbat davom etadi. Har shopda alohida — Jasur TechPC va MegaComp'ga yozsa, bu ikki xil yozuv, hech qachon birlashtirilmaydi (BL-042).

- **`channel`** + **`external_user_id`** — Telegram user ID, Instagram scoped ID yoki sayt chatida tasodifiy mehmon ID'si.
- **`display_name`**, **`username`** — taxallus, `@jasur_98`.
- **`locale`** — xaridor tili. Xabarnomalar shu tilda ketadi (20 §5).
- **`phone_enc`** + **`phone_hmac`** — Jasur "Raqamni yuborish" tugmasini bossa, raqam shu yerga **shifrlangan** holda yoziladi (**6-qaror**). HMAC — raqam bo'yicha qidirish va buyurtma bilan moslash uchun.
- **`contact_consent_at`** — raqam berishga rozilik vaqti (BL-036). Reklama roziligi Stage 1 da yig'ilmaydi.
- **`notice_version`** — ko'rsatilgan maxfiylik bildirishnomasi versiyasi (26 §8).
- **`blocked_at`** — Jasur botni bloklagan bo'lsa (Telegram 403), xabarnoma yuborilmaydi.
- **`erased_at`** — xaridor ma'lumoti o'chirilgan vaqt: ism, username, telefon tozalanadi, yozuv ID'si qoladi (26 §6).

**Unikal:** `(shop_id, channel, external_user_id)`.
**RLS:** ha.

---

## 4. `conversations` — suhbat

**Nima uchun kerak:** xaridor bilan butun yozishma va uning holati: kim javob beryapti, kimga biriktirilgan, qachondan beri operator kutyapti. Inbox shu jadvaldan quriladi.

**Bir xaridor — bitta suhbat** (**3-qaror**). Jasur bir haftadan keyin yana yozsa, yangi suhbat ochilmaydi — yopilgan suhbat qayta ochiladi va butun tarix ko'rinadi (FSM-04 `REOPENED`).

- **`status`** — FSM-04:
  ```
  Yangi (NEW) ──(birinchi xabar)──▶ AI javob beryapti (AI_ACTIVE)
  AI_ACTIVE ──(AI javob berdi)──▶ Xaridor javobi kutilmoqda (WAITING_CUSTOMER)
  AI_ACTIVE ──(AI operatorni chaqirdi)──▶ Operator kerak (HUMAN_NEEDED)              [vazifa + xabar]
  HUMAN_NEEDED ──(operator oldi)──▶ Operator javob beryapti (HUMAN_ACTIVE)            [speaker_version +1]
  HUMAN_ACTIVE ──(operator javob berdi)──▶ WAITING_CUSTOMER
  WAITING_CUSTOMER ──(xaridor yozdi)──▶ HUMAN_ACTIVE yoki AI_ACTIVE                   [kim olgan bo'lsa]
  HUMAN_ACTIVE ──("AI'ga qaytarish")──▶ AI_ACTIVE                                     [speaker_version +1]
  HUMAN_ACTIVE ──(operator yopdi)──▶ Yopildi (RESOLVED)
  RESOLVED ──(xaridor yana yozdi)──▶ Qayta ochildi (REOPENED)                         [tarix saqlanadi]
  ```
  Har o'tish `platform.transition_log` ga yoziladi. `REOPENED` dan keyingi yo'l — **10-qaror**.
- **`speaker_mode`** — hozir kim javob beradi: `AI`, `HUMAN` yoki `PAUSED`. `PAUSED` — hech kim avtomatik yozmaydi: shop to'xtatilgan, AI o'chirilgan yoki AI limiti tugagan.
- **`speaker_version`** — fencing raqami. Har "Suhbatni olish", "AI'ga qaytarish" yoki pauzada **bitta UPDATE bilan** +1 bo'ladi (12 §8).
- **`assignee_membership_id`** — mas'ul operator. Operator faqat o'ziga biriktirilgan suhbatni ko'radi va yozadi (business/04 "O'ziniki").
- **`channel`**, **`channel_account_id`** — qaysi kanal. Ali botni almashtirsa, suhbat yangi bot akkauntiga o'tadi.
- **`locale`** — suhbat tili.
- **`tags`** — operator teglari ("PC yig'ma", "ulgurji") — inbox filtri (M10, 4-band). **9-qaror**.
- **`message_seq`** — oxirgi xabar tartib raqami. Har yangi xabar suhbat qatori qulflangan holda +1 oladi.
- **`staff_last_read_seq`** — xodim o'qigan oxirgi xabar. O'qilmaganlar soni shundan hisoblanadi (**8-qaror**).
- **`last_message_at`** — inbox tartibi (yangisi tepada).
- **`last_inbound_at`** — xaridorning oxirgi xabari. Instagram'da 24 soatlik javob oynasi shundan hisoblanadi (BL-033).
- **`last_outbound_at`** — oxirgi chiquvchi xabar.
- **`waiting_since`** — `HUMAN_NEEDED` ga o'tgan vaqt. "Operator kutilmoqda" eslatmasi shundan (06 §5.2).
- **`first_staff_reply_at`** — birinchi operator javobi: javob vaqti ko'rsatkichi (M10, 6-band).
- **`last_order_id`** — suhbatdan yaratilgan oxirgi buyurtma (`commerce.order.drafted` event'idan). Operator suhbat yonida buyurtmani ko'radi.
- **`resolved_at`**, **`resolved_by`** — kim yopdi.

**Indekslar:** inbox (yangisi birinchi), holat bo'yicha, "mening suhbatlarim", "operator kutayotganlar".
**RLS:** ha.

**Misol:** Jasur "RTX 4060 bormi?" deb yozdi → suhbat `NEW` → `AI_ACTIVE`. AI javob berdi → `WAITING_CUSTOMER`. Jasur "operator kerak" dedi → `HUMAN_NEEDED`, Dilshodga vazifa. Dilshod oldi → `HUMAN_ACTIVE`, `speaker_version` 1 → 2.

---

## 5. `messages` — xabar

**Nima uchun kerak:** suhbat lentasi. Kiruvchi va chiquvchi xabarlar **bitta jadvalda** (**1-qaror**) — operator ekrani bitta so'rov bilan to'liq lentani oladi.

**Kim va nima:**
- **`seq`** — suhbat ichidagi tartib raqami. Xabarlar tartibsiz kelsa ham lenta to'g'ri ko'rinadi (BL-035). Sayt chati `?after=` shu raqam bilan so'raydi.
- **`direction`** — `IN` (xaridordan) yoki `OUT` (xaridorga).
- **`author_type`** + **`author_membership_id`** — xaridor, AI, xodim yoki tizim; xodim bo'lsa — kim.
- **`origin`** — chiquvchi xabar qayerdan: AI avtomatik, AI taklifini operator tasdiqlagan (SUGGEST rejimi), operator, xabarnoma, salomlashish.
- **`kind`** — matn, rasm, ovoz, fayl, kontakt, joylashuv, stiker. Kontakt turida raqam **matnga yozilmaydi** — `customer_identities` ga shifrlangan holda tushadi.
- **`body`** — matn. **2-qaror:** ustun darajasida shifrlanmaydi, disk darajasida (26 §4 "at rest").
- **`intent_hint`** — "Olaman" tugmasi bosilgan bo'lsa `PURCHASE_INTENT`. AI buni taxmin qilmaydi, faqat belgiga qaraydi (13 §6.2).
- **`reply_to_message_id`** — qaysi xabarga javob.
- **`provider_message_id`**, **`parts`** — Telegram xabar raqami; 4096 belgidan uzun matn bo'laklarga bo'linib yuborilgan bo'lsa, nechta bo'lak.
- **`occurred_at`** — kiruvchida Telegram vaqti, chiquvchida yaratilgan vaqt.
- **`edited_at`** — Jasur xabarini tahrirlasa, matn yangilanadi (eski matn saqlanmaydi).

**Chiquvchi xabar maydonlari:**
- **`speaker_version`** — AI javobi qaysi versiya uchun tayyorlangan. Yuborishdan oldin suhbatdagi versiya bilan solishtiriladi.
- **`intent_key`** — takror himoyasi: `ai:{javob id}`, `notif:{xabarnoma id}`, `staff:{Idempotency-Key}`. Bir niyat bir marta yuboriladi.
- **`ai_reply_id`** — AI javobi (`sales_ai.ai_turns`). Matn event'da emas — messaging uni `SalesAiQueryPort.get_reply()` orqali oladi (05 §8.4).
- **`notification_id`** — xabarnoma (`platform.notifications`). Natija platformaga `mark_result` bilan qaytadi.
- **`delivery_status`**:
  ```
  (yozildi) ──▶ Navbatda (QUEUED) ──(vazifa oldi)──▶ Yuborilmoqda (SENDING) ──(Telegram qabul qildi)──▶ Yuborildi (SENT)
  SENDING ──(429 / vaqtinchalik xato)──▶ QUEUED                         [Retry-After, 5 martagacha]
  SENDING ──(yakuniy xato / 5 marta)──▶ Yuborilmadi (FAILED)            [inbox'da belgi, xodimga vazifa]
  SENDING ──(javob kelmadi, yuborildimi noma'lum)──▶ Noma'lum (UNKNOWN)  [operator ko'radi, qayta yuborilmaydi]
  QUEUED ──(speaker o'zgardi / AI javobi tekshiruvdan o'tmadi)──▶ Tashlandi (DISCARDED)
  ```
  Kiruvchi xabar doim `RECEIVED`.
- **`attempts`**, **`last_error_code`**, **`sent_at`**, **`failed_at`** — urinishlar va natija. Xato kodi adapterning yagona ro'yxatidan (13 §2), matnsiz.
- **`sending_started_at`** — `SENDING` ga o'tgan vaqt: "osilib qolgan" yuborish (5 daqiqa) shundan hisoblanadi, `created_at` dan emas; rejali ish `UNKNOWN` qilgandan keyin kanal "qabul qildi" desa ham — `SENT` (QA 5b M5).
- **`parts_sent`** — bo'laklab yuborishda nechta bo'lak (yoki rasm) ketgani: qayta urinish to'xtagan joydan davom etadi, xaridor bo'lakni ikki marta olmaydi (QA 5b L8). Rasm izohi 1024 belgidan uzun bo'lsa — izohga birinchi bo'lak, qolgani rasmdan keyin matn bo'lib ketadi.

**Unikal va indekslar:**
- `(conversation_id, seq)` — tartib;
- `intent_key` — bir niyat bir marta;
- **bir suhbatda bir vaqtda bitta navbatdagi AI xabari** (`origin = AI_AUTO`, holat `QUEUED`/`SENDING`, bir xil `speaker_version`) — 12 §8;
- navbatda qotib qolganlar — 5 daqiqadan eski `QUEUED`/`SENDING` rekonsilyatsiya qilinadi (06 §6).

**Saqlash:** suhbatdagi oxirgi faollikdan 12 oy, keyin o'chiriladi; hisobot raqamlari qoladi (26 §5).
**RLS:** ha.

**Misol:** AI "RTX 4060 4 800 000 so'm, Chilonzorda bor" javobini tayyorladi (`speaker_version = 1`). Shu payt Dilshod suhbatni oldi (`speaker_version = 2`). Yuborish vazifasi versiyani solishtirdi: 1 ≠ 2 → xabar `DISCARDED`, Jasurga ketmadi. Jasur faqat Dilshodning javobini ko'radi.

---

## 6. `attachments` — rasm, ovoz, fayl

**Nima uchun kerak:** Jasur kompyuterining rasmini yubordi. Webhook ichida rasm yuklab olinmaydi (sekin, xavfli) — fon vazifasi Telegram'dan olib, **yopiq** fayl omboriga saqlaydi. Operator uni 5 daqiqalik imzoli havola orqali ko'radi.

- **`file_id`** — `platform.stored_files` (yangi fayl turi `CHAT_ATTACHMENT`, yopiq). Yuklab olinmaguncha bo'sh.
- **`kind`**, **`mime`**, **`size_bytes`**, **`duration_seconds`** — tur va o'lcham; ovozli xabar uzunligi.
- **`status`** — kutilmoqda → saqlandi / yuklab bo'lmadi → o'chirildi.
- **`provider_file_ref`** — Telegram `file_id`: yuklab olish uchun kerak, saqlangandan keyin tozalanadi.
- **`purge_after`** — o'chirish vaqti: suhbat muddati bilan; ovozli xabar — matnga o'girilgach (DEC-117, keyin).

Chiquvchi mahsulot rasmi ham shu yerda yoziladi (fayl — katalog rasmi, ochiq).
**RLS:** ha.

---

## 7. `handoffs` — operatorga uzatish

**Nima uchun kerak:** "operator kerak" so'rovlari tarixi va navbati: kim chaqirdi, nega, kim oldi.

- **`reason`** — xaridor so'radi, "Olaman", AI ishonchsiz, shikoyat, to'lov, kafolat, chegirma, AI ishlamayapti, AI javobi kechikdi yoki tekshiruvdan o'tmadi, Instagram oynasi yopiq, operator o'zi oldi.
- **`requested_by_type`** + **`requested_by_membership_id`** — AI, xodim, tizim yoki xaridor.
- **`status`** — ochiq → olindi / bekor (xaridor yozishni to'xtatdi, AI'ga qaytarildi).
- **`speaker_version_at_request`** — AI'ning "operator chaqir" event'i ikki marta kelsa ham, bir xil versiya bilan — bitta uzatish.
- **`taken_by`**, **`taken_at`**, **`closed_at`**.

**Unikal:** suhbatda bitta ochiq uzatish (07).
**Bog'liqlik:** ochiq uzatish = `platform.staff_tasks` dagi `HANDOFF` vazifasi ([notifications.md](notifications.md)).
**RLS:** ha.

---

## 8. `conversation_notes` — ichki izoh

**Nima uchun kerak:** Dilshod Vali uchun yozib qo'yadi: "Jasur ulgurji narx so'rayapti, ertaga qo'ng'iroq qilaman". Xaridorga ko'rinmaydi (M10, 4-band).

- **`author_membership_id`**, **`body`**, **`created_at`**.

Faqat qo'shiladi, tahrirlanmaydi. Ichida telefon bo'lishi mumkin — xaridor ma'lumoti o'chirilganda izohlar ham tozalanadi.
**RLS:** ha.

---

## 9. `webchat_sessions` — sayt chati sessiyasi

**Nima uchun kerak:** saytdagi mehmon login qilmaydi. Brauzer bir martalik tasodifiy token oladi; shu token bilan u o'z suhbatini davom ettiradi (13 §8).

- **`channel_account_id`** — shopning `WEB_CHAT` akkaunti.
- **`customer_identity_id`** — mehmon (tasodifiy `visitor_id`).
- **`token_hash`** — tokenning **xeshi**. Token o'zi bazada yo'q.
- **`last_seen_at`**, **`expires_at`** — 30 kun, har faollikda suriladi; **`revoked_at`**.

**Token qayerda turadi** (**4-qaror**): sayt domenidagi httpOnly cookie'da. API boshqa domenda, shuning uchun sayt ilovasi (Next.js) chat so'rovlarini API'ga o'zi uzatadi — brauzer uchinchi tomon cookie'siga muhtoj emas (Safari ularni bloklaydi).
**Javoblar:** 5b da — polling (`GET …/chat/messages?after_seq=`, har 4 s); SSE — keyin (08 §6.6, progress/M05b 1-qaror). Token API'ga `X-Chat-Session` header'ida keladi.
**Himoya:** boshqa shop `slug`i bilan sessiya so'ralsa — 404 (TC-CH-06). IP va mehmon bo'yicha so'rovlar chegarasi.
**RLS:** ha.

---

## 10. Boshqa jadvallar bilan bog'lanish (FK'siz)

- **`commerce.orders.conversation_id`** — buyurtma qaysi suhbatdan. Teskari bog'lanish — `conversations.last_order_id`.
- **`sales_ai`** — AI konteksti `MessagingQueryPort.get_conversation_context()` orqali o'qiladi (redaction bilan, 14 §7); AI javobi `sales_ai.reply.ready` event'i bilan keladi.
- **`platform.notifications`** — xaridorga xabarnoma `platform.notification.customer_delivery_requested` event'i → messaging xabarni yozadi va yuboradi → `mark_result`.
- **`platform.stored_files`** — biriktirmalar (`CHAT_ATTACHMENT`).

**Event'lar** (05 §8.3, o'zgarishsiz): `messaging.message.received`, `.message.sent`, `.message.failed`, `.conversation.handed_off`, `.conversation.returned_to_ai`, `.channel.connected`, `.channel.disconnected`. Payload'da matn va telefon yo'q.

---

## 11. Keyin qo'shiladigan narsalar

- **Instagram izohlari (DEC-132)** — alohida modul. Kerak bo'ladi: `instagram_comments` (izoh, post, kayfiyat, "+" qoidasi natijasi) va izohdan Direct'ga birinchi xabar (Private Reply, 7 kun). Hozirgi jadvallar mos: kanal `INSTAGRAM`, `provider_events.kind = COMMENT`, Direct suhbati odatiy `conversations` qatori.
- **Telegram Business** (egasining shaxsiy akkaunti) — `channel_accounts.settings` dagi flag, yangi jadval kerak emas.
- **Tayyor javoblar** (quick replies) — Stage 1 da yo'q (**9-qaror**).
- **Ovozli xabarni matnga o'girish** — ovozli hisobot betasi bilan (DEC-112, DEC-117).

---

## Bog'lanishlar xaritasi

```
channel_accounts ──< provider_events
       │
       ├──< conversations >── customer_identities ──< webchat_sessions >── channel_accounts
       │          │
       │          ├──< messages ──< attachments
       │          ├──< handoffs
       │          └──< conversation_notes
       │
──<  bir → ko'p (FK, shop_id bilan)
Boshqa schemalar (faqat uuid): platform.memberships, platform.stored_files, platform.notifications,
commerce.orders, sales_ai.ai_turns
```

---

## engineering/07 §4.5 va 13 dan farqlar

- **`channel_accounts`:** `secret_ref` (secret manager) o'rniga `token_enc` (shifrlangan ustun) va `webhook_secret_hash` (**11-qaror**); `display_name`, `scopes`, `settings`, `last_*`, `connected_*`, `disconnect_reason` qo'shildi; `provider` → `channel` (13 dagi nom).
- **`provider_events`:** `payload_ref` olib tashlandi (**5-qaror**); `kind`, `message_id`, `error_code` qo'shildi; dedup kaliti `(shop_id, channel_account_id, provider_event_id)`.
- **`customer_identities`:** `consent_flags` → `contact_consent_at`; telefon (`phone_enc`, `phone_hmac`), `username`, `blocked_at`, `erased_at` qo'shildi.
- **`conversations`:** suhbat yagona (`(shop_id, customer_identity_id)` unikal — **3-qaror**); `tags`, `message_seq`, `staff_last_read_seq`, `last_inbound_at`, `waiting_since`, `first_staff_reply_at`, `last_order_id`, `resolved_*` qo'shildi; `speaker_mode` ga `PAUSED` (12 §8 dagidek).
- **`messages`:** chiquvchilar uchun alohida `outbound_messages` (12, 13) o'rniga bitta jadval (**1-qaror**); `body_enc` → `body` (**2-qaror**); `attachments` ustuni → alohida jadval; `intent_id` → `intent_key`; `seq`, `origin`, `kind`, `intent_hint`, `parts`, `ai_reply_id`, `notification_id`, `attempts`, `last_error_code` qo'shildi.
- **Yangi:** `attachments` (26 §4 da tilga olingan), `conversation_notes` (M10), `webchat_sessions` (13 §8).

---

## 5b amalga oshirishdagi farqlar (2026-10-26)

Kod: `app/domains/messaging/`, migratsiya `messaging_0002`. Batafsil — [progress/M05b](../progress/M05b-messaging.md).

- **`handoffs.reminded_at`** qo'shildi — "operator kutyapti" eslatmasi bitta uzatishga bir marta ketadi (`messaging_handoff_reminders`).
- **`channel_accounts` RLS** — uch variant: `shop_id`, `app.channel_account_ref` (Telegram webhook URL'idagi ref), `app.channel_external_ref` = `INSTAGRAM:<sahifa id>` (Instagram webhook'ida shop faqat sahifa ID'si bilan topiladi; SECURITY DEFINER FORCE RLS'ni chetlab o'tmagani uchun).
- **`channel_accounts.settings`** — `mode` (`webhook` / `polling`), `polling_offset` (lokal polling), `fake` (dev seed akkaunti — tashqariga yubormaydi).
- **AI yo'q paytidagi yo'l:** yangi suhbat `NEW → HUMAN_NEEDED`, `speaker_mode = PAUSED` (12 §8); operator olganda `HUMAN`, `speaker_version` +1.
- **FSM-04 kengaytmalari** (`state_machine.py`, `tests/architecture/fsm_spec.yaml`): `TAKE_OVER` — `AI_ACTIVE`, `WAITING_CUSTOMER`, `REOPENED` dan ham; `RESOLVE` — `WAITING_CUSTOMER`, `HUMAN_NEEDED`, `REOPENED` dan ham; `REOPEN` — xodim ham; `REQUEST_HUMAN` — `REOPENED` dan; `CUSTOMER_REPLIED_TO_AI`. Founder tasdig'i kerak (progress/M05b 4-qaror).
- **Xaridorga holat xabari** — `messages` qatori (`origin = SYSTEM`, `intent_key = order:{order_id}:{status}`); `platform.notifications` da xaridor qatori yozilmaydi.
- **Sayt chati** — polling (yuqorida, 9-bo'lim).
- **Rasm** — `attachments.file_id` → `platform.stored_files` (`purpose = CHAT_ATTACHMENT`); ovoz, fayl, stiker yuklab olinmaydi (`FAILED`, `UNSUPPORTED_TYPE`).

---

## Founder ko'rib chiqishi uchun qarorlar

Founder 2026-10-26 da ishni to'xtatmasdan davom ettirishni va eng yaxshi variantni tanlashni topshirgan. Quyidagi qarorlar shu asosda **qabul qilingan va kodda shunday quriladi**. Har birini o'zgartirish mumkin — o'zgarsa, kod shunga moslanadi.

**1. Kiruvchi va chiquvchi xabarlar bitta jadvalda.**
- Tanlov: bitta `messages` jadvali (07 dagidek).
- Nega: suhbat lentasi bitta so'rov; fencing indeksi shu jadvalda; chiquvchi xabar holati ustunlar bilan yetadi.
- Muqobil: chiquvchilar uchun alohida `outbound_messages` (12, 13). Afzallik — yuborish navbati alohida. Kamchilik — lenta uchun ikki jadvalni birlashtirish, holat ikki joyda.

**2. Xabar matni ustun darajasida shifrlanmaydi.**
- Tanlov: disk shifrlash + RLS + 12 oylik saqlash (26 §4 "at rest").
- Nega: operator matnni baribir o'qiydi, qidiruv va AI konteksti tez ishlaydi; matn ichidagi raqamni ustun shifrlash himoya qilmaydi.
- Muqobil: xaridor telefoni kabi AES-GCM bilan (07 dagi `body_enc`). Afzallik — bazadan nusxa o'g'irlansa matn o'qilmaydi. Kamchilik — qidiruv imkonsiz, har o'qishda shifr ochish.

**3. Bir xaridor — bitta suhbat.**
- Tanlov: `(shop, xaridor)` uchun bitta suhbat, yopilgani qayta ochiladi (FSM-04 `REOPENED`).
- Nega: operator butun tarixni bir joyda ko'radi; business/05 "oldingi tarix saqlanadi" deydi.
- Muqobil: har murojaatga yangi suhbat. Afzallik — hisobotda murojaatlar alohida. Kamchilik — tarix bo'linadi.

**4. Sayt chati tokeni — sayt domenidagi httpOnly cookie, sayt ilovasi orqali uzatiladi.**
- Nega: 13 §8 talabi (httpOnly, sayt domenida); API boshqa domen, uchinchi tomon cookie'lari Safari'da ishlamaydi.
- Muqobil: token brauzer xotirasida (localStorage) va header'da. Afzallik — sodda. Kamchilik — sahifadagi skript tokenni o'qiy oladi.

**5. Webhook'ning xom JSON'i saqlanmaydi.**
- Tanlov: faqat dedup kaliti va natija, 30 kun.
- Nega: JSON ichida ism, telefon, matn; hajm katta; xabar baribir normallashtirilgan holda saqlanadi.
- Muqobil: xom payload 7 kun (07 `payload_ref`). Afzallik — xatoni tekshirish oson. Kamchilik — PII ikkinchi joyda.

**6. Xaridor Telegram'da bergan telefon `customer_identities` da (shifrlangan).**
- Nega: raqam xaridorga tegishli, keyingi buyurtmada ham kerak; HMAC orqali buyurtma bilan moslanadi.
- Muqobil: faqat AI xaritasida (`platform.llm_pii_refs`, 30 kun). Kamchilik — raqam operator ekranida yo'qoladi.

**7. Shopda har kanal turidan bitta faol akkaunt** (bitta bot, bitta Instagram, bitta sayt chati).
- Nega: pilot shoplari uchun yetarli, inbox va sozlama sodda.
- Muqobil: bir nechta bot (filial bo'yicha). Keyin kerak bo'lsa — unikal indeksni olib tashlash kifoya.

**8. O'qilganlik — suhbat darajasida.**
- Tanlov: `staff_last_read_seq` (biriktirilgan xodim o'qigani).
- Nega: Stage 1 da suhbat bitta operatorda.
- Muqobil: har xodim uchun alohida o'qilganlik jadvali. Menejer va operator alohida hisob ko'rardi, lekin jadval va yozuvlar ko'payadi.

**9. Teglar — suhbat ustunida, izohlar — alohida jadvalda, tayyor javoblar — yo'q.**
- Nega: M10 teg va izohni talab qiladi; tayyor javoblar hujjatlarda talab qilinmagan, AI `SUGGEST` rejimi o'rnini bosadi.
- Muqobil: teglar ro'yxati alohida jadvalda (rang, nom). Keyin kerak bo'lsa qo'shiladi.

**10. FSM-04 dagi aniq bo'lmagan strelkalar** (04 §11.1).
- Tanlov: `WAITING_CUSTOMER ──(xaridor yozdi)──▶ AI_ACTIVE` (AI javob bergan bo'lsa); `REOPENED` dan keyin suhbat oldingi `speaker_mode` bilan davom etadi va yo'l `AI_ACTIVE`/`HUMAN_NEEDED` dagidek. Avtomatik yopish yo'q.
- Nega: 04 dagi talqin, business/05 ruhiga mos.
- **business/05 ga shu strelkalarni qo'shishni founder tasdiqlashi kerak.**

**11. Kanal tokeni bazada shifrlangan ustunda.**
- Nega: pilotda alohida secret manager yo'q; 3-moduldagi shifrlash kaliti va almashtirish mexanizmi tayyor.
- Muqobil: secret manager (13 dagi `*_secret_ref`). Afzallik — kalit bazadan butunlay tashqarida. Kamchilik — yangi infratuzilma (deploy bosqichida qo'shilishi mumkin).

**12. `channel_accounts` RLS bilan, webhook uchun "identity varianti"** (`account_ref` konteksti).
- Nega: 1-moduldagi `memberships`/`sessions` bilan bir xil usul, token ustuni himoyada.
- Muqobil: RLS'siz jadval (10 §4 ro'yxatida yo'q edi) yoki `SECURITY DEFINER` funksiya.
