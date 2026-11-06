# `sales_ai` schemasi — ma'lumotlar lug'ati (AI sotuvchi) + `platform/llm` jadvallari

> **Holat:** taklif, 2026-10-26. Qarorlar qabul qilingan, chunki founder ishni to'xtatmasdan davom ettirishni topshirgan. **Founder ko'rib chiqishi kutilmoqda.** Qarorlar oxirida. Diagramma: [`sales_ai.dbml`](sales_ai.dbml) → dbdiagram.io. PC moslik engine'i — kodda, jadvali yo'q (C1–C4). Arxitektura: [`../ai/M06-architecture.md`](../ai/M06-architecture.md).
> **Kim o'qiydi:** founder va dasturchilar. Har jadval: nima uchun kerak → har maydon nima va nega → bog'lanishlar → misol.
> **Umumiy qoidalar** — [platform.md](platform.md) §0. Bu yerda takrorlanmaydi.
> **Hajm:** AI sozlamalari va bilim bazasi (S3-07), AI navbatlari va tool chaqiruvlari jurnali (S3-04), operator bahosi, baholash (S3-00, S3-08), LLM redaction xaritasi va xarajat hisobi (`platform/llm`, S3-01).

Misollarda **"TechPC"**. Ega — **Ali**, operator — **Dilshod**. Xaridor **Jasur** Telegram'da yozadi: "Assalomu alaykum, 10 mln gacha CS2 uchun kompyuter kerak, raqamim +998 90 123 45 67".

---

## 0. Bu schemada yangi narsalar

- **AI — faqat til va orkestratsiya qatlami.** Narx, qoldiq, moslik va buyurtma holati faqat tool'lardan keladi (Query Port). AI ularni o'zgartira olmaydi. Yozish faqat **qoralama so'rovi** sifatida, event orqali ketadi (14 §1).
- **Har navbatning to'liq izi bor.** Qaysi xabarga javob berildi, qaysi model va prompt versiyasi ishladi, qaysi tool'lar chaqirildi, nechta token va qancha pul ketdi, javob tekshiruvdan o'tdimi. Shu iz bilan "AI nega bunday dedi?" savoliga javob topiladi.
- **Shaxsiy ma'lumot tashqi AI'ga bormaydi.** "+998 90 123 45 67" LLM'ga `[PHONE_1]` bo'lib ketadi. Haqiqiy raqam faqat bizning bazamizda, shifrlangan holda turadi (DEC-016).
- **Rejimlar:** o'chiq → soya (AI yozadi, hech kim ko'rmaydi) → taklif (operator ko'rib yuboradi) → avtomatik. Ega yoqadi. AI o'chsa ham savdo to'xtamaydi (BL-069).
- **Prompt va qoidalar kodda, bazada faqat ro'yxat.** Platforma tizim prompti PR va eval'dan o'tadi. Bazada faqat "qaysi versiya aktiv" yoziladi.

---

## 1. `agent_settings` — shopning AI sozlamasi

**Nima uchun kerak:** Ali AI'ni yoqadi, rejimni tanlaydi va qaysi tillarda gaplashishini belgilaydi.

- **`mode`** — `OFF` (standart), `SHADOW`, `SUGGEST`, `AUTO` (14 §10).
- **`active_profile_version_id`** — hozir ishlatilayotgan shop profili versiyasi (§2).
- **`languages`** — AI javob beradigan tillar. Standart uz va ru.
- **`allowed_tools`** — platforma ruxsat bergan tool'larning kichik to'plami. Masalan, Ali "AI buyurtma qoralamasi yaratmasin, faqat maslahat bersin" desa, `commerce.create_order_draft` o'chiriladi. Qoralama tool'lari o'chsa, AI "olaman" degan xaridorni darhol operatorga uzatadi.
- **`handoff_rules`** — qaysi mavzuda doim operatorga (shikoyat, kafolat), nechta AI javobidan keyin "operator bilan gaplashasizmi?" deb taklif qilish, ish vaqtidan tashqari xatti-harakat.
- **`daily_cost_cap_minor`** — kunlik AI xarajati chegarasi (USD sentda). Bo'sh bo'lsa, faqat tarif limiti amal qiladi (DEC-119).
- **`greeting_enabled`** — birinchi xabarda AI o'zini AI deb tanishtiradi (14 §14.10: AI ekanini yashirmaslik).
- **`kill_switch_at`**, **`kill_switch_reason`** — favqulodda o'chirish (platforma yoki ega). Rejim o'zgarmaydi, lekin AI ishlamaydi.
- **`model_alias`** — faqat platforma o'zgartiradi (bake-off natijasi). Bo'sh bo'lsa, global standart.

**Chegirma maydoni yo'q:** AI chegirma aytmaydi va va'da qilmaydi. Chegirma so'ralsa, operatorga uzatadi (`DISCOUNT_REQUEST`, DEC-110, nol toqat).
**AUTO'ga o'tish:** ekranda oxirgi 7 kundagi SHADOW/SUGGEST sifati ko'rsatiladi (tahrirsiz yuborilgan ulush, xato belgilari). Ega baribir o'zi qaror qiladi.
**RLS:** ha.

**Misol:** TechPC — `SUGGEST`, tillar `{uz, ru}`, kunlik chegara 500 sent (5 $), shikoyatlar doim operatorga.

---

## 2. `agent_profile_versions` — shop profili (promptning 2-qatlami)

**Nima uchun kerak:** AI shop nomidan gapiradi. U shopning ohangini va "biz kimmiz" degan qisqa matnni biladi.

- **`version`**, **`status`** (`DRAFT` → `APPROVED` → `RETIRED`) — Ali tahrirlaydi va tasdiqlaydi (business/04 §3).
- **`shop_display_name`**, **`tone`** (`FRIENDLY` / `FORMAL` / `CONCISE`).
- **`about_text`** — "TechPC — Chilonzordagi PC do'koni, 2018 yildan…" (≤ 1000 belgi).
- **`extra_instructions`** — egasining qo'shimcha ko'rsatmasi (≤ 1000 belgi). Promptga **ishonchsiz blok** sifatida kiradi va platforma qoidalarini bekor qila olmaydi: "chegirma ber" desa ham AI bermaydi.
- **`content_hash`** — prompt keshi va audit uchun.

**O'zgarmaydi:** tahrir yangi versiya bo'ladi. Har AI javobi qaysi versiya bilan yozilgani `ai_turns.profile_version` da saqlanadi.
**RLS:** ha.

---

## 3. `knowledge_items` — FAQ va siyosatlar

**Nima uchun kerak:** Jasur "yetkazib berasizmi?" deb so'raydi. AI javobni o'zi to'qimaydi, Ali tasdiqlagan matndan oladi.

- **`kind`** — `FAQ` yoki `POLICY` (yetkazish, kafolat, qaytarish, to'lov).
- **`locale`**, **`title`**, **`body`** (≤ 2000 belgi).
- **`status`**, **`version`**, **`supersedes_id`** — tahrir yangi qator bo'ladi, eskisi `RETIRED`. Faqat `APPROVED` bandlar promptga kiradi.

**Stage 1:** tasdiqlangan bandlar to'liq matn sifatida promptga kiradi (jami ~6k tokengacha). Semantik qidiruv (embedding) yo'q, u faqat o'lchangan foyda bo'lsa qo'shiladi (16 §4).
**Ishonchsiz kontent:** FAQ matnidagi "ko'rsatmalar" bajarilmaydi (BL-039).
**RLS:** ha.

---

## 4. `prompt_versions` — platforma tizim prompti ro'yxati (global)

- **`key`** — Stage 1 da bitta: `shop_seller`.
- **`version`** — "seller-2026-11-v1". Kodda `PROMPT_VERSION` bilan mos bo'lishi shart.
- **`code_ref`** — git SHA. Prompt matni repo'da turadi va PR review qilinadi.
- **`eval_run_id`** — aktivlashtirishdan oldin o'tgan baholash.

**Tartib:** yangi versiya → eval (nol toqat buzilmasa) → shadow → aktivlashtirish (14 §5). Bir vaqtda bitta `ACTIVE`.

---

## 5. `ai_sessions` — suhbatning AI holati

**Nima uchun kerak:** Jasur bilan suhbat davomida AI nimani bilib olganini eslab qoladi: byudjet 10 mln, ish turi CS2, tanlangan SKU'lar, lead L-57.

- **`stage`** — `IDLE → QUALIFYING → RECOMMENDING → QUOTE_PENDING → ORDER_DRAFTED → HANDED_OFF` (yoki `STOPPED`). Bu faqat operator ekrani va hisobot uchun. Asosiy holat `messaging` dagi FSM-04 (14 §10).
- **`slots`** — byudjet, ish turi, brend afzalligi, tanlangan SKU'lar, yetkazish usuli, til. Shaxsiy ma'lumot yo'q.
- **`lead_id`**, **`last_quote_id`**, **`last_order_id`** — `commerce` event'laridan yangilanadi (14 §6).
- **`summary_redacted`**, **`summary_upto_seq`** — eski xabarlar xulosasi. Har 10 xabarda arzon model yangilaydi, PII'siz.
- **`turn_count`**, **`handoff_count`**, **`last_turn_at`**.

**07 dan farq:** `conversation_summaries` alohida jadval emas, shu yerda turadi.
**RLS:** ha. Suhbat bilan birga 12 oyda o'chiriladi.

---

## 6. `ai_turns` — AI navbati

**Nima uchun kerak:** Jasurning har xabariga AI qanday javob tayyorlagani, qanchaga tushgani va nima bilan tugagani.

- **`id`** — bu `reply_id`. `messaging.messages.ai_reply_id` aynan shu.
- **`trigger_message_id`**, **`trigger_seq`** — qaysi kiruvchi xabarga javob.
- **`speaker_version`** — navbat boshlangandagi versiya. Yuborishdan oldin `messaging` uni qayta tekshiradi (fencing, 12 §8, TC-009).
- **`mode`**, **`status`** (`QUEUED → RUNNING → COMPLETED/FAILED`), **`outcome`** (`REPLY_QUEUED`, `SUGGESTED`, `SHADOWED`, `DISCARDED`, `HANDOFF`, `NO_REPLY`, `ERROR`), **`handoff_reason`**.
- **`provider`**, **`model_alias`**, **`model_id`**, **`fallback_used`** — masalan, `anthropic`, "seller" → `claude-sonnet-5-5` yoki dev'da `gemini`. Agar model xavfsizlik sababli rad etib, server boshqa modelga o'tkazgan bo'lsa, `fallback_used` belgilanadi.
- **`prompt_version`**, **`profile_version`** — qaysi prompt va qaysi shop profili bilan.
- **`reply_text_enc`** — javob, **redact holatida** (`[PHONE_1]`) va shifrlangan. Haqiqiy qiymatga almashtirish `messaging` ga topshirish paytida bajariladi (14 §7.5).
- **`validator_codes`**, **`rewrite_count`** — javob tekshiruvi (14 §8): narx mos emas, noma'lum SKU, taqiqlangan da'vo ("tasdiqlandi"), noto'g'ri til. Qayta yozish ko'pi bilan bir marta.
- **`tool_call_count`**, **`tokens_in/out`**, **`cache_read/write_tokens`**, **`cost_micros`** (USD × 10⁶), **`latency_ms`**, **`provider_request_ids`**, **`error_code`**, **`trace_id`**.

**Unikal:** bitta kiruvchi xabarga bitta navbat. Worker o'chib qayta yonsa ham ikkinchi javob yo'q (TC-AI-02).
**LLM chaqiruvi tranzaksiya ichida emas:** qisqa tranzaksiyada `RUNNING` bo'ladi, keyin LLM va tool'lar ishlaydi, so'ng qisqa tranzaksiyada `COMPLETED` va outbox yoziladi.
**Saqlash:** 12 oy. Keyin javob matni tozalanadi, raqamlar hisobot uchun qoladi.
**RLS:** ha.

**Misol:** Jasurning 1-xabari → navbat, `SUGGEST`, tool'lar: `catalog.suggest_builds` → `catalog.check_compatibility`; 3 variant, PASS. Natija `SUGGESTED`, 4 200 token, 0,018 $, 6,1 soniya.

---

## 7. `ai_tool_executions` — tool chaqiruvlari jurnali

- **`seq`** — navbat ichidagi tartib (ko'pi bilan 6, 14 §3.1).
- **`tool`** — ichki nom `catalog.search`. API'da `catalog_search` deb yuriladi: Claude tool nomida nuqta ruxsat etilmaydi.
- **`decision`** — `ALLOWED` / `DENIED` (sxema, ruxsat yoki budget).
- **`args_redacted`** — redact qilingan argumentlar.
- **`result_summary`** — faqat ID va dalil (SKU ID'lari, natija, `observed_at`). Matn yo'q.
- **`result_hash`** — to'liq natija xeshi. Javob tekshiruvi va eval shunga tayanadi.
- **`idempotency_key`**, **`emitted_event_id`** — yozuvchi tool (qoralama so'rovi) ikki marta bajarilmaydi.
- **`error_code`**, **`latency_ms`**.

**Saqlash:** 90 kun (07 §4.6).
**RLS:** ha.

---

## 8. `ai_feedback` — operator bahosi

**Nima uchun kerak:** SUGGEST rejimida Dilshod AI taklifini o'zgartirmay yuborsa, tahrirlasa yoki rad etsa, shu yoziladi. Shu ma'lumot bilan "AUTO'ga o'tish mumkinmi?" degan savolga javob beriladi.

- **`verdict`** — `SENT_AS_IS`, `EDITED`, `REJECTED` (avtomatik), `FLAGGED` (qo'lda, "bu javob xato").
- **`error_tags`** — noto'g'ri narx, noto'g'ri mahsulot, uydirma, operatorga uzatmadi, noto'g'ri til, ohang, juda uzun, boshqa.
- **`sent_message_id`** — operator yuborgan yakuniy xabar.
- **`edit_distance_pct`** — tahrir ulushi.
- **`comment`**.

**Regression to'plamiga** faqat shop roziligi bilan va redact qilingan holda o'tadi (DEC-118).
**RLS:** ha.

---

## 9. `eval_datasets`, `eval_runs`, `eval_results` — baholash (global)

**Nima uchun kerak:** "AI yaxshi ishlayapti" degan da'voni tekshirish uchun. Har yangi prompt, model yoki qoida shu to'plamlardan o'tadi (16).

- **`eval_datasets`** — to'plamlar: dialoglar (uz/uz-Cyrl/ru/en), PC, red-team, redaction. Har biri versiya, manifest (litsenziya asosi, rozilik doirasi), fayl (`platform.stored_files`, yopiq), SHA-256 va `frozen` (golden to'plam muzlatiladi).
- **`eval_runs`** — bitta yugurish: qaysi to'plam, prompt, model, ruleset va git SHA. Natijada metrikalar, **`zero_tolerance_violations`** va xarajat. Holat `PASSED` faqat nol toqat buzilmasa bo'ladi.
- **`eval_results`** — har holat: o'tdimi, xato kodlari, judge bali (0–5), chaqirilgan tool'lar, vaqt, narx. Muvaffaqiyatsiz holatning redact qilingan transkripti saqlanadi.

**Nol toqat** (16 §5): noto'g'ri narx, mavjud bo'lmagan SKU, "tasdiqlandi", boshqa shop ma'lumoti, chegirma va'dasi, ruxsatsiz amal. Bular **deterministik** tekshiriladi (tool natijasi bilan solishtirish). LLM-judge faqat sifat ballari uchun ishlatiladi.

**6c holati ([progress/M06c](../progress/M06c-ai-eval.md)):** to'rt jadval — `eval_datasets` (+ `name`, `description`, `archived_at`, `revision`; fayl va `file_id` o'rniga), **`eval_cases`** (savol, til, kategoriya, tarix, kutilmalar JSON), `eval_runs` (+ nishon shop, judge, bake-off ID, xarajat chegarasi, hisoblagichlar; holatlar `QUEUED`, `BUDGET_EXCEEDED`, `CANCELLED` qo'shildi), `eval_results` (+ `case_key`, kategoriya, til, javob matni redact holatida, judge JSON, `transcript` JSONB — `transcript_file_id` o'rniga). Global — shop_id va RLS yo'q, faqat platforma admini API'si. `platform.ai_usage.purpose` ga `EVAL` qo'shildi; shop_id'siz qatorlarni faqat shop kontekstisiz tranzaksiya ko'radi.

---

## 10. `platform.llm_pii_refs` — redaction xaritasi

**Nima uchun kerak:** Jasur raqamini yozdi. LLM'ga `[PHONE_1]` boradi. AI `commerce.create_order_draft(contact_ref="PHONE_1")` deydi va server `PHONE_1` ni haqiqiy raqamga aylantiradi.

- **`id`** — bu `contact_ref_id`. Domenlararo event'da kontaktning o'zi emas, shu UUID ketadi. `commerce` uni `SalesAiQueryPort.resolve_contact_ref` orqali bir marta o'qiydi va o'z jadvaliga shifrlab yozadi (14 §7.4).
- **`token`** (`PHONE_1`), **`kind`** (`PHONE`, `ADDRESS`, `NAME`, `EMAIL`, `CARD`).
- **`value_enc`** — shifrlangan qiymat. Karta raqami hech qachon qayta tiklanmaydi: faqat niqob saqlanadi.
- **`value_hmac`** — bir suhbatda bir qiymat uchun bitta token.
- **`resolved_by_commerce_at`**, **`expires_at`** — kontakt ref 30 kun, qolganlari suhbat saqlash muddati bilan (26 §5).

**Nega `platform` da:** redaction `platform/llm` qatlamida turadi va hisobot yordamchisi (S5) ham shundan foydalanadi (07 §4.1, 14 §7, 26).
**RLS:** ha. Xaridor so'rovi bilan o'chiriladi.

---

## 11. `platform.ai_usage` — har LLM chaqiruvi xarajati

- **`shop_id`** — baholashda bo'sh bo'ladi (platforma xarajati).
- **`provider`** (`anthropic`, `gemini`, `fake`), **`model_id`**, **`purpose`** (`SALES_TURN`, `SUMMARY`, `CLASSIFY`, `EVAL_JUDGE`, keyin `REPORT_ASSISTANT`), **`ref_id`**.
- **`tokens_in/out`**, **`cache_read/write_tokens`**, **`cost_micros`**.

**Limit:** `platform/billing.check_ai_quota` navbatdan oldin bugungi va oylik summani tekshiradi. Tez ishlashi uchun Redis kunlik hisoblagich bor, manba esa shu jadval. 80% to'lganda egaga ogohlantirish ketadi. 100% bo'lganda speaker `PAUSED` bo'ladi va xabarlar operatorga o'tadi (BL-040, BL-067).
**Saqlash:** 13 oy.

---

## Bog'lanishlar xaritasi

```
agent_settings ── active_profile_version ──▶ agent_profile_versions
knowledge_items (supersedes_id ─▶ o'zi)            prompt_versions ── eval_run_id ──▶ eval_runs
ai_sessions (1 suhbat = 1 qator)
ai_turns ──< ai_tool_executions                    eval_datasets ──< eval_runs ──< eval_results
    └──< ai_feedback
ai_turns.id ─ ─ ▶ messaging.messages.ai_reply_id   ai_turns ─ ─ ▶ platform.ai_usage.ref_id
ai_tool_executions.emitted_event_id ─ ─ ▶ sales_ai.outbox_events ─ ─ ▶ commerce (lead / quote / order DRAFT)
platform.llm_pii_refs.id = contact_ref_id ─ ─ ▶ commerce (bir martalik o'qish)
```

---

## engineering/07 §4.6 dan farqlar

- **`agent_profiles` → `agent_settings` + `agent_profile_versions`:** sozlama (rejim, tillar, tool'lar, limit) bitta qatorda, profil matni esa versiyalangan va ega tasdiqlaydi. Rejimga `SHADOW` qo'shildi (16 §5 dagi soya rejimi uchun).
- **`prompt_versions`:** 07 da shop darajasida (`shop_id`, `content`) edi. Endi **global va kodda** (`code_ref`), shopning sozlashi profil va FAQ orqali bo'ladi. Sabab: 14 §5 "1-qatlam faqat platforma (PR + eval)".
- **`knowledge_items`:** `embedding` olib tashlandi (Stage 1 da kerak emas, 16 §4). `supersedes_id` qo'shildi.
- **`conversation_summaries` → `ai_sessions.summary_redacted`.**
- **`ai_turns`:** `trigger_seq`, `status`, `handoff_reason`, `model_id`, `fallback_used`, `profile_version`, `validator_codes`, `rewrite_count`, `cache_*_tokens`, `provider_request_ids` qo'shildi. `cost_minor` → `cost_micros` (USD; provayder dollarda hisoblaydi).
- **`ai_tool_executions`:** `seq`, `result_summary`, `idempotency_key`, `emitted_event_id` qo'shildi.
- **Yangi:** `ai_feedback`, `eval_datasets`, `eval_results`. 16 §7 da `eval_runs` "yoki CI artefakti" deyilgan edi, jadval tanlandi.

---

## Founder ko'rib chiqishi uchun qarorlar

**A1. AI rejimi standart holatda qaysi?**
- **Tanlov:** `OFF`. Ega yoqadi; yoqilganda tavsiya etilgan birinchi rejim `SUGGEST` (14 §10).
- **Nega:** AI shopning roziligisiz gapirmaydi.
- **Muqobil:** standart `SUGGEST`. Tezroq boshlanadi, lekin ega bilmay AI ishlab ketishi mumkin.

**A2. Soya (SHADOW) rejimi alohida rejimmi?**
- **Tanlov:** ha. AI yozadi, hech kim ko'rmaydi; operator javobi bilan solishtiriladi.
- **Nega:** 16 §5 dagi yoqish tartibi (eval → shadow → SUGGEST → AUTO).
- **Muqobil:** shadow faqat platforma sinovida. Shop'ning haqiqiy suhbatlarida sifat o'lchanmaydi.

**A3. AI chegirma haqida gapira oladimi?**
- **Tanlov:** **yo'q, umuman.** Chegirma so'ralsa, operatorga uzatadi. "AI aytishi mumkin bo'lgan maksimal chegirma" sozlamasi qilinmadi.
- **Nega:** 16 §5 nol toqat ("chegirma va'dasi 0"), DEC-110.
- **Muqobil:** ega belgilagan foizgacha "chegirma bo'lishi mumkin" deyish. Va'da va kutish paydo bo'ladi.

**A4. Platforma tizim prompti qayerda?**
- **Tanlov:** kodda (repo, PR review, eval). Bazada faqat ro'yxat va aktivlashtirish.
- **Muqobil:** bazada, admin paneldan tahrirlash. Tez, lekin eval'siz o'zgarish xavfi bor.

**A5. FAQ qanday ishlatiladi?**
- **Tanlov:** tasdiqlangan bandlar to'liq matn sifatida promptga kiradi (~6k token chegarasi, oshsa ogohlantirish). Embedding yo'q.
- **Muqobil:** semantik qidiruv (pgvector). Faqat o'lchangan foyda bo'lsa (16 §4).

**A6. Suhbat xulosasi alohida jadvalmi?**
- **Tanlov:** yo'q, `ai_sessions` ichida.
- **Nega:** bitta suhbat = bitta qator, kamroq join.
- **Muqobil:** 07 dagidek alohida `conversation_summaries`.

**A7. Xarajat qaysi valyutada?**
- **Tanlov:** USD × 10⁶ (`cost_micros`). Shopga ko'rsatishda tarif limiti birligida hisoblanadi.
- **Nega:** provayder dollarda hisob beradi, yaxlitlash xatosi bo'lmaydi.
- **Muqobil:** so'mga o'girib saqlash. Kurs o'zgarsa tarix buziladi.

**A8. Kunlik xarajat chegarasi.**
- **Tanlov:** ixtiyoriy `daily_cost_cap_minor` va tarifning oylik limiti (DEC-119). Chegaraga yetganda speaker `PAUSED` bo'ladi va xabarlar operatorga ketadi.
- **Muqobil:** faqat oylik limit. Bir kunda butun oylik limit sarflanishi mumkin.

**A9. `llm_pii_refs` qayerda?**
- **Tanlov:** `platform` da (07, 14, 26 dagidek). U `contact_ref_id` ham bo'ladi, alohida jadval kerak emas.
- **Muqobil:** `sales_ai` ichida. Hisobot yordamchisi uchun takrorlash kerak bo'ladi.

**A10. Tool chaqiruvlari jurnali qancha saqlanadi?**
- **Tanlov:** 90 kun. `ai_turns` raqamlari 12 oy qoladi, matn 12 oydan keyin tozalanadi.
- **Muqobil:** hammasi 12 oy. Jadval tez o'sadi.

**A11. Operator bahosi.**
- **Tanlov:** SUGGEST'da yuborish yoki rad etish avtomatik yoziladi. Xato belgisi qo'lda. Regression'ga faqat opt-in bilan.
- **Muqobil:** faqat qo'lda baho. Ma'lumot kam yig'iladi.

**A12. Baholash natijalari qayerda?**
- **Tanlov:** bazada (`eval_runs`, `eval_results`) va transkriptlar yopiq faylda.
- **Nega:** founder xatolarni o'zi ko'rib chiqadi (16 §8).
- **Muqobil:** faqat CI artefakti. Tarix va solishtirish qiyin.

**A13. LLM provayderi bitta kompaniyaga bog'lanadimi?**
- **Tanlov:** yo'q. Bitta neytral `LlmProvider` port (o'z xabar, tool chaqiruvi va usage turlari bilan) va uchta adapter:
  - `GeminiProvider` — lokal va dev uchun, founder'da hozir bor;
  - `AnthropicProvider` — Claude, production uchun tavsiya;
  - `FakeProvider` — testlar uchun.
  Tanlov `LLM_PROVIDER=gemini|anthropic|fake` bilan.
- **Nega:** dev arzon va tez boshlanadi, production modelini bake-off hal qiladi (DEC-009), domen kodi o'zgarmaydi (ADR-027).
- **Kamchilik:** ikki adapter, ikki xil tool va kesh formati. Neytral tur faqat umumiy imkoniyatlarni oladi. Provayderga xos funksiyalar adapter ichida qoladi.
- **Muqobil:** faqat Claude. Kod oddiyroq, lekin dev uchun ham pullik kalit kerak.

**A14. Bepul Gemini kaliti va maxfiylik.**
- **Tanlov:** bepul (free tier) kalit **faqat demo va sintetik ma'lumot** bilan ishlatiladi. Haqiqiy xaridor suhbati yoki PII hech qachon unga bormaydi. Redaction provayderdan qat'i nazar har doim ishlaydi. Production faqat pullik tarifda (Gemini paid yoki Claude), ma'lumotda o'qitmaslik shartlari bilan (ADR-027, DEC-118).
- **Texnik himoya:** `ENVIRONMENT=production` da `LLM_PROVIDER=gemini` bo'lsa, `GEMINI_TIER=paid` belgilanmaguncha ilova ishga tushmaydi. Dev seed ma'lumoti sintetik.
- **Afzallik:** dev bepul, haqiqiy ma'lumot himoyalangan.
- **Kamchilik:** dev'da haqiqiy suhbat bilan sinab bo'lmaydi. Pilot sinovi pullik kalit bilan qilinadi.
- **Muqobil:** dev'da ham pullik kalit. Xavfsizroq, lekin xarajat bor.

**A15. Baholash ikki provayderda.**
- **Tanlov:** bir xil to'plam ikkala provayderda yuritiladi (`eval_runs.provider`) va natija yonma-yon solishtiriladi: nol toqat, tool tanlash, o'zbek tili sifati, latency, narx.
- **Nega:** bake-off (DEC-009, S3-00) shu asosda o'tadi.
- **Muqobil:** faqat production provayderi baholanadi. Dev'dagi xatti-harakat farqi ko'rinmaydi.

**C1. PC qoidalari qayerda?**
- **Tanlov:** **faqat kodda** — toza Python funksiyalari, spec atributlari ustida (17 §6). Ruleset versiyasi kod konstantasi (`RULESET_VERSION`), chegaralar (75 W, ×1.3) ham kodda. Aktivlashtirish = deploy (PR + golden testlar + PC mutaxassis review). Bazada qoidalar uchun jadval yo'q.
- **Nega:** engine alohida agent tomonidan toza kod sifatida quriladi. Saqlash faqat yig'ma va taklif uchun kerak.
- **Muqobil:** `catalog.pc_rulesets` ro'yxat jadvali (17 §4.2 rejasi). Kerak bo'lsa keyin qo'shiladi; hozircha versiya snapshot'larda yoziladi.

**C2. Moslik natijasi keshlanadimi?**
- **Tanlov:** yo'q. Engine deterministik va tez, har safar hisoblanadi. Faqat taklif snapshot'i saqlanadi (`commerce.quote_compatibility_snapshots`).
- **Muqobil:** natija keshi. Spec yoki ruleset o'zgarganda eskirish xavfi bor. Profil ko'rsatsa keyin.

**C3. "PC yig'ish" alohida obyektmi?**
- **Tanlov:** yo'q. Saqlanadigan yig'ma — bu taklif versiyasi (DRAFT). Panel'dagi PC yig'ish sahifasi saqlamaydi, faqat "taklif qoralamasi sifatida saqlash" tugmasi bor.
- **Muqobil:** alohida `builds` jadvali. Taklif bilan takrorlanadi.

**C4. Yig'ma profillari (byudjet taqsimoti).**
- **Tanlov:** Stage 1 da kodda (versiyalangan ma'lumot fayli), PC mutaxassis PR orqali o'zgartiradi.
- **Nega:** engine bilan bir xil "kodda" printsipi, jadval va admin ekran kerak emas.
- **Muqobil:** `catalog.build_profiles` jadvali va admin ekrani. Mutaxassis o'zi tahrirlaydi; pilotdan keyin kerak bo'lsa.
