# `messaging` — Instagram izohlari (qo'shimcha jadvallar, DEC-132)

> **Holat:** taklif, 2026-10-27. Qarorlar qabul qilingan, chunki founder ishni to'xtatmasdan davom ettirishni topshirgan. **Founder ko'rib chiqishi kutilmoqda.** Qarorlar oxirida. Diagramma: [`instagram_comments.dbml`](instagram_comments.dbml) → dbdiagram.io.
> **Kim o'qiydi:** founder va dasturchilar. Har jadval: nima uchun kerak → maydonlar va nega → bog'lanishlar → misol.
> **Asos:** DEC-132 (DECISION_REGISTER), [13](../13-integrations-and-channels.md) §2, §3, §7. Mavjud [messaging.md](messaging.md) o'zgarmaydi; kichik ta'sirlar §7 da.
> **Qachon:** 5-modul (kanallar) va 6-modul (AI sotuvchi) tayyor bo'lgach (DEC-132). Feature flag `channel.instagram_comments` — Meta izohlar ruxsati kelmaguncha o'chiq.

Misollarda **"TechPC"**: ega **Ali**, menejer **Vali**, operator **Dilshod**. TechPC Instagram'da **"RTX 4060 — 4 800 000 so'm emas, kelib ko'ring!"** reels'ini joyladi. Ostida izohlar: **@jasur_pc**: "+", **@aziza_uz**: "narxi qancha?", **@komil**: "o'tgan safar olgan blokim 2 haftada kuydi, xizmat yomon".

---

## 0. Oddiy so'z bilan

- **«+» — "menga narxini Direct'da yozing" degani.** Instagram'da odatiy. Jasur "+" yozdi: tizim 1 daqiqa ichida Jasurning Direct'iga bitta xabar yuboradi: "Salom! MSI RTX 4060 Ventus 2X — 4 800 000 so'm, bor. Batafsil: techpc.platforma.uz/p/... Savolingiz bo'lsa, shu yerga yozing."
- **Narx faqat katalogdan.** Vali postga katalogdagi RTX 4060 ni bog'lagan bo'lsa, narx aytiladi. Bog'lanmagan bo'lsa — narxsiz xabar: "Salom! Narx va mavjudlik bo'yicha shu yerga yozing, javob beramiz." AI rasmga qarab mahsulotni taxmin qilmaydi (DEC-132, BL-038).
- **«+» ni AI emas, oddiy qoida aniqlaydi.** Arzon, xatosiz. Narx so'rovi ham kalit so'zlar bilan aniqlanadi.
- **Kayfiyatni AI baholaydi:** ijobiy, salbiy, neytral, spam yoki "aniqlanmagan". Komilning izohi — salbiy. AI ommaviy javob yozmaydi, izohni o'chirmaydi va yashirmaydi. Vali'ga vazifa va javob qoralamasi keladi (DEC-132).
- **Bir izohga — bitta Direct xabar, izohdan keyin 7 kun ichida** (Meta "Private Replies"). Jasur javob yozsa — oddiy Direct suhbati boshlanadi va 24 soatlik oyna ishlaydi (BL-033).
- **Reklama yo'q.** Faqat savolga bitta javob. Keyin xabar yuborilmaydi (BL-036, BL-061).

---

## 1. Oqim

```
Meta webhook (field: comments) ──▶ /webhooks/instagram/{account_ref}   (Direct bilan bir xil manzil va imzo tekshiruvi)
  BITTA tranzaksiya:
    provider_events (kind COMMENT) — takror bo'lsa hech narsa
    ig_posts topiladi / yaratiladi (media ma'lumoti keyin, arq'da)
    ig_comments saqlanadi + qoida: trigger = PLUS | PRICE_QUESTION | NONE
    outbox [messaging.ig_comment.received]
  ──▶ 200 OK

arq: ig_comment_reply (trigger ≠ NONE)                arq: ig_comment_classify (matn bor va sentiment yoqiq)
  ├─ flag, shop sozlamasi, post sozlamasi              ├─ AI limiti bormi (DEC-119)? yo'q → CLASSIFY_SKIPPED
  ├─ 7 kun o'tmaganmi, muallif shopning o'zimi          ├─ telefon/manzil yashiriladi (BL-039)
  ├─ shu muallifga shu postda javob bo'lganmi           ├─ platform/llm (COMMENT_CLASSIFY) → kayfiyat + ishonch
  ├─ post mahsuloti → CatalogQueryPort narx, qoldiq      ├─ ishonch < 0.70 → UNDETERMINED
  ├─ ig_comment_replies (QUEUED) → send_private_reply   ├─ ig_comment_sentiments + ig_comments.sentiment
  └─ SENT / FAILED / SKIPPED (+ event)                  └─ NEGATIVE → menejerga vazifa + qoralama (DRAFT)

Jasur Direct'da javob yozdi ──▶ oddiy Direct oqimi (messaging.md) ──▶ reply_to = provider_message_id
  ──▶ ig_comments.conversation_id to'ldiriladi ──▶ inbox'da "izohdan" belgisi, izoh + bizning javob ko'rinadi
```

Javob va kayfiyat bir-birini kutmaydi. Salbiy izohda «+» bo'lsa ham avtomatik javob ketadi (masalan, "+ lekin qimmat").

---

## 2. `ig_posts` — shop posti

**Nima uchun kerak:** izohlar postga bog'langan. Narx qaysi mahsulotdan olinishi va konkurs postida avtomatik javob o'chiqligi — post darajasida.

- **`external_media_id`** — Instagram media id. Post birinchi izoh kelganda yaratiladi. Hamma postlar oldindan yuklanmaydi.
- **`media_type`, `permalink`, `caption_excerpt`, `thumbnail_url`, `posted_at`** — panelda postni tanish uchun. Webhook ichida emas, arq vazifasida Meta'dan olinadi (`fetched_at`). Rasm saqlanmaydi: Meta havolasi eskiradi, faqat ko'rsatiladi.
- **`auto_reply_enabled`** — Ali konkurs postida ("+ qo'yganlar orasidan o'ynaymiz") o'chiradi, aks holda yuzlab Direct xabar ketadi (DEC-132).
- **`comment_count`** — ro'yxatda ko'rsatish uchun.

**RLS:** ha. **Misol:** RTX 4060 reels'i, `auto_reply_enabled = true`, 23 izoh.

---

## 3. `ig_post_products` — post ↔ katalog mahsuloti

**Nima uchun kerak:** narxni faqat shop o'zi bog'lagan mahsulotdan aytish uchun (BL-038).

- **`product_id`, `sku_id`** — katalog mahsuloti va (ixtiyoriy) aniq variant. Variant ko'rsatilmasa — sotuvdagi eng arzon variant narxi, "...dan boshlab" deb.
- **`linked_by`** — faqat xodim. "Instagram postlari" sahifasida Vali postni ochadi va "Mahsulot bog'lash" orqali katalogdan tanlaydi.
- Karusel postda ko'pi bilan 5 ta mahsulot. Javobda hammasi qisqa ro'yxat bo'lib chiqadi.

**Misol:** RTX 4060 reels'i → "MSI GeForce RTX 4060 Ventus 2X" (`sku_id` — 8 GB varianti).

---

## 4. `ig_comments` — izoh

**Nima uchun kerak:** har izoh — bir qator. Undan avtomatik javob, kayfiyat va hisobot chiqadi.

- **`external_comment_id`** — Meta izoh id'si. Private Reply aynan shu id'ga yuboriladi. Unikal — takror webhook ikkinchi qator yaratmaydi.
- **`parent_external_comment_id`** — izohga javob bo'lsa. Shopning o'z javoblari (`is_own_account`) qayta ishlanmaydi.
- **`author_external_id`, `author_username`** — muallif. Username — shaxsiy ma'lumot: panelda ko'rinadi, event va hisobotga tushmaydi.
- **`body`** — matn. `messages.body` kabi saqlanadi, 12 oy (26 §5). Izoh o'chirilsa (`DELETED`) — matn darhol tozalanadi.
- **`commented_at`** — Meta vaqti. 7 kunlik javob oynasi shundan.
- **`trigger`** — qoida natijasi: `PLUS`, `PRICE_QUESTION`, `NONE`. Qoida kodda: «+», "++", "+1", bo'shliqlar va emoji'lar e'tiborsiz; narx so'zlari uz (lotin va kirill), ru va en.
- **`sentiment`, `sentiment_source`, `sentiment_id`** — joriy kayfiyat va uning manbai (AI yoki xodim). Tarix — `ig_comment_sentiments` da.
- **`conversation_id`, `customer_identity_id`** — muallif Direct'da javob yozgandan keyin bog'lanadi. Oldindan bilib bo'lmaydi: izohdagi muallif id'si va Direct'dagi id har doim bir xil bo'lmaydi, shuning uchun bog'lash Meta'ning `reply_to` belgisi orqali qilinadi.
- **`status`** — `RECEIVED` → `CLASSIFIED` yoki `CLASSIFY_SKIPPED`; o'chirilsa `DELETED`.

**RLS:** ha. **Misol:** @jasur_pc, "+", `PLUS`, `POSITIVE` (AI, 0.81), Direct javobi SENT.

---

## 5. `ig_comment_sentiments` va `ig_comment_replies`

### `ig_comment_sentiments` — kayfiyat tarixi
**Nima uchun kerak:** AI bahosi va xodim tuzatishlari alohida-alohida saqlanadi. Hisobotda "AI bahosi" va "tuzatilgan" ajratiladi (DEC-132), tuzatishlardan esa AI sifati o'lchanadi.
- **`source`, `sentiment`, `confidence`, `raw_label`** — kim baholadi va natija. Ishonch 0.70 dan past bo'lsa `UNDETERMINED` yoziladi, asl taxmin `raw_label` da qoladi. Sabab: kinoya, o'zbek-rus aralash til, kirill va lotin aralash.
- **`language`** — qaysi tilda yozilgan (sifat tahlili uchun).
- **`model_id`, `prompt_version`, `ai_usage_id`** — qaysi model va qancha turdi (`platform.ai_usage`, yangi `COMMENT_CLASSIFY` maqsadi — tarif hisobida alohida ko'rinadi).
- **`staff_membership_id`** — tuzatgan xodim.

Faqat qo'shiladi.
**Misol:** Komilning izohi: AI `NEGATIVE` 0.93 → Vali'ga `IG_NEGATIVE_COMMENT` vazifasi.

### `ig_comment_replies` — izohga javoblar
**Nima uchun kerak:** Direct'ga avtomatik javob, xodim javobi va salbiy izohga qoralama — bitta joyda, takrorlanmasdan.
- **`kind`** — `PRIVATE_AUTO` (avtomatik Direct), `PRIVATE_STAFF` (xodim Direct'ga), `PUBLIC_STAFF` (izoh ostida ommaviy, faqat xodim).
- **`status`** — `DRAFT` (AI qoralamasi, faqat salbiy izohga) → `QUEUED` → `SENDING` → `SENT` / `FAILED`; yoki `SKIPPED` / `DISCARDED`.
- **`template_key`, `template_version`, `locale`, `body`, `variables`** — avtomatik javob shablondan (shop o'zgartira oladi, 20 §5):
  - `customer.ig_comment_price_reply` — "Salom! {product_title} — {price}, {stock_line}. Batafsil: {product_url}. Savolingiz bo'lsa, shu yerga yozing.";
  - `customer.ig_comment_generic_reply` — "Salom! Narx va mavjudlik bo'yicha shu yerga yozing, javob beramiz."
  Narx va qoldiq — javob paytida `CatalogQueryPort` dan. Qoldiqni shopning `stock_display` sozlamasi bo'yicha ko'rsatadi (DEC-128). Javob tili — izoh tilidan, aniqlanmasa shop standarti.
- **`skip_reason`** — nega yuborilmadi: flag o'chiq, shop yoki post sozlamasi, 7 kun o'tgan, muallifga shu postda allaqachon javob ketgan, shopning o'z izohi, kanal uzilgan, izoh o'chirilgan.
- **`intent_key`** — takror himoyasi (`ig_auto:{comment_id}`), `messages.intent_key` kabi.
- **`provider_message_id`** — Meta javob id'si. Xaridor javob yozsa, suhbat shu orqali izohga bog'lanadi.
- **`ai_draft`, `author_membership_id`** — qoralamani AI tayyorlagan va uni xodim tasdiqlagan/yozgan.

**Bir izohga bitta Direct xabar** — qisman unikal indeks (Meta qoidasi). Ommaviy javoblar soni cheklanmaydi.
**Bir muallifga bir postda bitta avtomatik javob:** Jasur "+" ni 5 marta yozsa, Direct'ga bitta xabar ketadi.
**Nega `messages` ga yozilmaydi:** Private Reply paytida Jasurning Direct id'si hali noma'lum. Soxta xaridor yaratmaslik uchun javob shu jadvalda turadi. Jasur javob yozsa, oddiy suhbat yaratiladi va inbox izohni hamda bizning javobni "izohdan" kartochkasida ko'rsatadi.
**Salbiy izoh:** AI ommaviy javob **qoralamasini** tayyorlaydi (`PUBLIC_STAFF`, `DRAFT`). Vali uni tahrirlab "Javob berish" bosadi yoki rad etadi. Izoh o'chirilmaydi va yashirilmaydi.

---

## 6. Event'lar (05 ga qo'shiladi, egasi yangilaydi)

- **`messaging.ig_comment.received`** — `comment_id`, `post_id`, `trigger`, `has_text`, `commented_at`. Consumer: reporting.
- **`messaging.ig_comment.classified`** — `comment_id`, `sentiment`, `source`, `confidence_bucket` (`HIGH`/`LOW`). Consumer: reporting.
- **`messaging.ig_comment.reply_finished`** — `comment_id`, `reply_id`, `kind`, `status` (`SENT`/`SKIPPED`/`FAILED`), `skip_reason?`. Consumer: reporting.
- **`messaging.ig_comment.linked`** — `comment_id`, `conversation_id` (xaridor Direct'da javob yozdi). Consumer: reporting (`comment_facts.converted_to_conversation`, `conversation_facts.from_ig_comment`).
- **`messaging.ig_comment.deleted`** — `comment_id`. Consumer: reporting.

Matn, username, narx — event'da yo'q.

---

## 7. `messaging.dbml` va boshqalarga ta'sir

1. `provider_events.ig_comment_id` (ixtiyoriy) — `COMMENT` turidagi event qaysi izohni yaratdi. `kind = COMMENT` allaqachon zaxirada.
2. `channel_accounts.settings.comments = {auto_reply, sentiment}` — shop sozlamasi, standart ikkalasi yoqiq. `scopes` da izohlar ruxsati bo'lmasa, panel "Meta ruxsati yo'q" deydi va flag yoqilmaydi.
3. `platform.llm_purpose` ga `COMMENT_CLASSIFY` (sales_ai.dbml).
4. Xodim vazifalari: `IG_NEGATIVE_COMMENT` (menejer, ega) va `IG_REPLY_FAILED` (operator). Bildirishnoma: `staff.ig_negative_comment` (o'rta muhimlik).
5. **Adapter.** `ChannelPort` (13 §2) o'zgarmaydi. Yonida `InstagramCommentsPort`: `parse_comment_events`, `send_private_reply(account, comment_id, text)`, `send_public_reply`, `fetch_media`. Hozirgi Instagram adapter stub'i (flag ostida, 5b) shu port bilan kengaytiriladi. Xato kodlari — o'sha taksonomiya; qo'shimcha `REPLY_WINDOW_EXPIRED` (7 kun) va `ALREADY_REPLIED` (Meta "bir marta" xatosi) → `SKIPPED`.
6. **Rate limit:** shu akkaunt uchun Redis token bucket (13 §4), Private Reply'lar uchun alohida limit (qiymat — Meta hujjatidan, ariza paytida).
7. **Shaxsiy ma'lumot:** xaridor o'chirish so'rovi (`platform.privacy.erasure_requested`) — `body`, `author_username` tozalanadi, `pii_erased_at` yoziladi.

---

## Bog'lanishlar xaritasi

```
channel_accounts ──< ig_posts ──< ig_post_products ─ ─ ▶ catalog.products / skus
        │               │
        └─────────────< ig_comments ──< ig_comment_sentiments   (sentiment_id ─▶ joriy qator)
                            │   └────< ig_comment_replies ── provider_message_id ─ ─ ▶ Direct reply_to
                            └─ ─ ▶ messaging.conversations / customer_identities   (xaridor Direct'da javob bersa)
provider_events (COMMENT) ─ ─ ▶ ig_comments          ig_comment_sentiments ─ ─ ▶ platform.ai_usage

──<  bir → ko'p (FK, shop_id bilan)      ─ ─▶  ishora, FK'siz
```

---

## Founder ko'rib chiqishi uchun qarorlar

**I1. Jadvallar qaysi schemada?**
- **Tanlov:** `messaging` ga qo'shimcha (commerce_quotes kabi).
- **Nega:** o'sha webhook, o'sha kanal akkaunti va tokeni, o'sha dedup va yuborish navbati.
- **Muqobil:** alohida `social` schemasi. Chegaralar aniqroq, lekin webhook ikki domenga bo'linadi.

**I2. Izohga javob inbox suhbatimi?**
- **Tanlov:** yo'q. Javob `ig_comment_replies` da; xaridor Direct'da javob yozgandagina suhbat yaratiladi va izohga bog'lanadi.
- **Nega:** Private Reply paytida xaridorning Direct id'si noma'lum; soxta xaridor va bo'sh suhbatlar inbox'ni to'ldirmaydi.
- **Muqobil:** har «+» uchun darhol suhbat. Operator hammasini ko'radi, lekin inbox yuzlab javobsiz suhbatga to'ladi.

**I3. Narx so'rovini kim aniqlaydi?**
- **Tanlov:** «+» kabi oddiy qoida — kalit so'zlar (uz lotin/kirill, ru, en).
- **Nega:** arzon, oldindan aytib bo'ladigan natija; DEC-132 ruhida.
- **Kamchilik:** g'ayrioddiy yozilgan savollar ("skoka turadi") o'tib ketishi mumkin. Lug'at pilotdan keyin to'ldiriladi.
- **Muqobil:** AI niyatni aniqlaydi. Aniqroq, lekin har izoh pul turadi va kechikadi.

**I4. Post mahsulotga bog'lanmagan bo'lsa.**
- **Tanlov:** narxsiz umumiy javob ("shu yerga yozing").
- **Nega:** xaridor javobsiz qolmaydi, narx esa taxmin qilinmaydi (BL-038).
- **Muqobil:** javob yubormaslik. Narxsiz «+» lar yo'qoladi.

**I5. Bir muallif bir postga ko'p «+» yozsa.**
- **Tanlov:** bir postda bir muallifga bitta avtomatik javob.
- **Nega:** spam ko'rinmaydi, Meta limiti tejaladi.
- **Muqobil:** har izohga bittadan (Meta ruxsat beradi). Xaridorga bir xil xabar bir necha marta keladi.

**I6. Kayfiyat ishonch chegarasi.**
- **Tanlov:** 0.70; pastroq bo'lsa "aniqlanmagan".
- **Muqobil:** chegarasiz. Kinoya va aralash tilda xato baholar hisobotni buzadi.

**I7. Salbiy izohga nima qilinadi?**
- **Tanlov:** menejerga vazifa va AI tayyorlagan ommaviy javob qoralamasi. Yuborishni faqat xodim qiladi; o'chirish va yashirish yo'q.
- **Nega:** DEC-132 so'zma-so'z.
- **Muqobil:** qoralamasiz, faqat vazifa. Menejer ishi ko'payadi.

**I8. Kayfiyat xarajati qanday hisoblanadi?**
- **Tanlov:** yangi `COMMENT_CLASSIFY` maqsadi, shop AI limitiga kiradi (DEC-119). Limit tugasa kayfiyat to'xtaydi, «+» javoblari ishlayveradi (ular AI emas).
- **Muqobil:** umumiy `CLASSIFY` ichida. Tarifda izohlar xarajati ko'rinmaydi.

**I9. Postlar qachon yuklanadi?**
- **Tanlov:** birinchi izoh kelganda, arq vazifasida.
- **Muqobil:** ulashda hamma postlarni import qilish. Ko'p API chaqiruvi, eski postlar keraksiz.
