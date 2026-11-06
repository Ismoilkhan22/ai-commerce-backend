# M09 — UAT qamrovi tekshiruvi (Stage 1, S0–S5)

> **Sana:** 2026-10-27. **Manba:** `business/10_UAT_ACCEPTANCE_AND_RELEASES.md` §2 (UAT-M01…M20) va §3 (TC-001…TC-033).
> **Usul:** test nomlari va ID'lar `tests/` va `ai-commerce-frontend/e2e/` ichidan qidirildi (grep); qamralmagan joylar ishlab turgan dev API (`localhost:8000`) ga skript bilan tekshirildi. To'liq pytest/e2e ishga tushirilmadi.
> **Belgilar:** COVERED — avtomatik test ssenariyni aniq tekshiradi; PARTIAL — qisman; NOT COVERED — test yo'q; EXTERNAL — haqiqiy LLM, Telegram/Instagram yoki deploy qilingan server kerak.

---

## 1. Xulosa

- **UAT-M (Stage 1, 18 ta):** COVERED 13, PARTIAL 5, NOT COVERED 0. (UAT-M14 va M15 — keyinga qoldirilgan.)
- **TC (Stage 1 ga tegishli, 21 ta):** COVERED 17, PARTIAL 2 (TC-011, TC-029), NOT COVERED 1 (TC-013), EXTERNAL 1 (TC-033).
- **Doiradan tashqari (12 ta):** TC-004/005/006/021 (to'lov, DEC-100), TC-012 (ovoz, S5+), TC-015/016/017/018/019/024/026 (Stage 2 va 3).
- **Mening tekshiruvlarim (jonli API):** PASS 3, FAIL 3 (hammasi "funksiya yo'q" turidagi: 404).
- **Qo'shimcha, kod o'qib topilgan (jonli tasdiqlanmagan) 3 ta kamchilik:** pastda "Kamchiliklar" ro'yxatida.
- **Muhim:** testlarning aksariyati ID'ni sharhda yozmaydi (faqat TC-001/002/003/007/009/010/011/022/023/025/027/028/030/031 va ba'zi UAT'lar belgilangan). Qolganlarini men nomi va mazmuni bo'yicha moslab chiqdim.

---

## 2. UAT-M ssenariylari

- **UAT-M01 Shop akkaunti — PARTIAL.** Shop hayot yo'li (yaratish → faollashtirish), to'xtatilgan shop, A/B izolyatsiya: `test_module1_auth_shops_staff.py` (`shop_lifecycle_from_creation_to_activation`, `shop_a_cannot_touch_shop_b`), `test_storefront.py` (SUSPENDED/CLOSED saytda `SITE_NOT_AVAILABLE`). Mening tekshiruvim: DRAFT shop sayti `409 SITE_NOT_AVAILABLE (COMING_SOON)` — PASS. Kamchilik: "faollashtirilmagan shopda AI javob bermaydi" — `sales_ai/services/gate.py` shop holatini tekshirmaydi, bunga test ham yo'q.
- **UAT-M02 Xodimlar — COVERED.** `roles_limit_what_staff_can_do`, `last_owner_cannot_be_removed_or_demoted`, `two_owners_disabling_each_other_concurrently_leave_one`, `disabled_member_is_locked_out_immediately`; e2e `module1.spec.ts`.
- **UAT-M03 Filiallar — COVERED.** `branch_scoped_staff_sees_only_own_branches`, `test_storefront_qa_fixes.py` (yopiq filial `BRANCH_CLOSED`), `shop_with_open_orders_cannot_be_closed`; UAT-M03 belgisi `test_module1…` da.
- **UAT-M04 Katalog — COVERED.** `sku_code_unique_within_shop_only`, `publish_requires_sku_price_and_rate_for_dollars`, `roles_limit_catalog_actions`, import testlari (`test_catalog_import*.py`), e2e `catalog-import.spec.ts`. Mening tekshiruvim: 5000 qatorli CSV (20 ta ataylab xato qator) — 2 soniyada o'qildi, 8 soniyada tekshiruv tugadi, aniq 4980 `create` + 20 `error`, xato hisoboti fayli berildi — PASS. (Repoda 5000 qatorli test yo'q edi.)
- **UAT-M05 Narx — PARTIAL.** 300$ × kurs → so'm: `dollar_price_shown_in_sum_without_rounding` (UAT-M05 belgisi); chegirma 3% → menejer: `discount_request_and_approval_limits`; eskirgan kurs buyurtmani tasdiqlashni to'xtatadi: `stale_rate_blocks_confirm_of_usd_order`. Kamchilik: eskirgan kursda PC taklifi (`quotes`) bloklanmaydi (kodda `exchange_rate_stale` faqat buyurtma tasdig'i va AI tool'ida ishlatiladi), test yo'q.
- **UAT-M06 Ombor — COVERED.** `receipt_updates_balance_and_ledger`, `last_unit_race_between_two_confirms_and_quick_sale`, `ledger_is_append_only_and_balance_check_holds`; e2e `commerce.spec.ts`.
- **UAT-M07 Shop sayti — COVERED.** `order_request_creates_pending_unreserved_order_and_tracking`, `hidden_product_disappears_immediately_even_when_cached`, `cache_is_isolated_between_shops`; e2e `storefront.spec.ts`. Eslatma: "qabul qilindi" xabari faqat suhbati bor xaridorga ketadi (`storefront_order_without_conversation_gets_no_message_and_link_works`); suhbatsiz xaridor kuzatuv havolasini ko'radi.
- **UAT-M08 PC moslik — COVERED.** `tests/unit/test_compat_engine.py` (socket, BIOS, "tekshirish kerak", deterministik natija), `test_compat_service.py`, `test_quotes*.py`. AI natijani o'zgartira olmaydi: moslik deterministik engine'da, AI faqat o'qiydi.
- **UAT-M09 Kanallar — PARTIAL.** Telegram ulash, token shifrlangan, webhook, inbox: `test_messaging.py` (UAT-M09 belgisi). Kamchilik: Instagram/Telegram ruxsati bekor qilindi (`AUTH_REVOKED`) → kanal "uzilgan", egaga xabar — kodda bor (`sending.py`), lekin shu aniq holat uchun test yo'q (`blocked_customer_marks_failed_and_channel_unavailable` — boshqa holat). Instagram — `FEATURE_CHANNEL_INSTAGRAM_DM` bayrog'i ostida o'chiq. Haqiqiy Telegram/Instagram — EXTERNAL.
- **UAT-M10 Inbox — COVERED.** `fencing_drops_ai_reply_after_operator_takes_over`, `operator_scope_assign_and_warehouse_denied`, `shops_cannot_see_each_others_conversations`; e2e `messaging.spec.ts`.
- **UAT-M11 AI sotuvchi — COVERED (fake LLM bilan).** `test_sales_ai_qa_fixes.py` (`price_invented_without_tools_is_blocked`, `invented_product_name_is_blocked`, `discount_promise_is_blocked`, `discount_mention_hands_off_not_just_rewrite`), `test_ai_eval.py`, e2e `ai.spec.ts`. Haqiqiy LLM sifati — EXTERNAL.
- **UAT-M12 Leadlar va takliflar — COVERED.** `risky_only_pass_quote_auto_approves_and_customer_accepts`, `submitted_revision_is_frozen_in_the_database`, `creator_cannot_approve_after_return_or_revise`; e2e `quotes.spec.ts`.
- **UAT-M13 Buyurtmalar — COVERED.** `order_lifecycle_moves_stock_exactly_once`, `permission_matrix_and_ownership`, `catalog_price_change_is_detected_at_confirm`; e2e `commerce.spec.ts` (boshqa operator buyurtmasi).
- **UAT-M16 Kafolat — COVERED.** `test_support.py` (`permissions_per_role`, `refund_quarantines_unit_without_stock_out_and_write_off_releases_it`, `replace_quarantines_returned_unit…`); e2e `warranty.spec.ts`.
- **UAT-M17 Xabarnomalar — COVERED.** `order_status_messages_go_to_conversation_once_in_customer_locale`, `redelivered_event_is_applied_once`, `webchat_visitor_locale_reaches_order_messages`.
- **UAT-M18 Hisobotlar — PARTIAL.** Raqamlar, davr, tannarx yo'q bayrog'i, operator summasi ko'rinmasligi: `test_reporting.py` (`sales_reports_from_events`, `profit_flags_partial_and_missing_cost`, `permissions`, `manager_never_sees_cost_or_profit`), e2e `cost-reports.spec.ts`. Mening tekshiruvim: `GET /shop/reporting/assistant` → 404 — "hisobot yordamchisi" (yozma savolga javob) hali qurilmagan — FAIL.
- **UAT-M19 AI sozlamalari — COVERED.** `settings_permissions_versioning_and_readiness`, `daily_cost_cap_pauses_ai_and_notifies_owner`, `budget_warning_80pct_and_exceeded_once`, `kill_switch_stops_ai`; e2e `ai.spec.ts`. Eslatma: tarif/`/settings/billing` yo'q (`GET /shop/billing` → 404), lekin UAT'da faqat AI rejimi va limit bor.
- **UAT-M20 Tarix — PARTIAL.** Narx/kurs tarixi (eski va yangi, kim, qachon): `price_and_rate_history_cannot_be_rewritten`, `GET /shop/skus/{id}/price-history`; buyurtma/taklif/ombor tarixi bor; platforma jurnali `test_platform_admin.py`. Kamchilik: egaga mo'ljallangan umumiy "O'zgarishlar tarixi" (`/audit` sahifa) va eksport yo'q — `GET /shop/audit` → 404 — FAIL. "Tarixga shaxsiy ma'lumot tushmaydi": `customer_pii_is_encrypted_and_kept_out_of_audit_and_idempotency` COVERED.

---

## 3. Muhim sinovlar (TC)

- **TC-001 — COVERED.** `test_catalog.py`, `test_commerce.py`, `test_module1…` (TC-001 belgisi): boshqa shop resursi 404.
- **TC-002 — COVERED.** `test_commerce.py::last_unit_race_between_two_confirms_and_quick_sale`.
- **TC-003 — COVERED.** `same_idempotency_key_confirms_once`.
- **TC-004/005/006/021 — kechiktirilgan (to'lov), doiradan tashqari.**
- **TC-007 — COVERED.** `test_sales_ai_qa_fixes.py::price_invented_without_tools_is_blocked`, `invented_product_name_is_blocked`.
- **TC-008 — COVERED.** `test_compat_engine.py::bios_support_variants`, `missing_socket_is_one_missing_finding…`; taklif menejer tasdig'isiz yuborilmaydi: `manual_approval_rules`.
- **TC-009 — COVERED.** `test_messaging.py::fencing_drops_ai_reply…`, `test_sales_ai.py::operator_takeover_during_turn_discards_ai_reply`.
- **TC-010 — COVERED.** `webhook_checks_secret_dedups_and_ignores_groups`, `duplicate_event_does_not_create_second_turn`, `parallel_inbound_turns_one_reply`.
- **TC-011 — PARTIAL.** `blocked_customer_marks_failed_and_channel_unavailable`, `send_fails_after_five_attempts_and_staff_gets_task`; ruxsat bekor qilinishi (`AUTH_REVOKED`) uchun alohida test yo'q.
- **TC-012 — S5+ ovoz, doiradan tashqari.**
- **TC-013 — NOT COVERED.** Hisobot yordamchisi qurilmagan (tannarx/foyda so'rovini rad etish va urinishni yozish yo'q). `GET /shop/reporting/assistant` → 404.
- **TC-014 — COVERED.** `test_reporting.py` (`total_count == 0`). Mening tekshiruvim: yangi QA shop, so'nggi 30 kun → `orders_count 0`, `total_amount_minor 0` (null emas) — PASS.
- **TC-015…019, 024, 026 — Stage 2/3, doiradan tashqari.** (TC-016 `test_catalog.py` da tilga olingan, lekin bu Stage 2.)
- **TC-020 — COVERED.** `test_support.py::replace_quarantines_returned_unit…`, `refund_quarantines_unit_without_stock_out…`; e2e `warranty.spec.ts`.
- **TC-022 — COVERED.** `test_jobs_events.py` (`redelivered_event_is_applied_once`, `failing_subscriber_retries_then_dead_letters_and_replays`, TC-022 belgisi).
- **TC-023 — COVERED.** `test_commerce_qa_fixes.py::suspended_shop_blocks_new_sales_but_finishes_existing`, `test_commerce_qa_round2.py::shop_with_open_orders_cannot_be_closed`.
- **TC-025 — COVERED.** `test_module1…::disabled_member_is_locked_out_immediately` (TC-025), e2e `module1.spec.ts`.
- **TC-027 — COVERED.** `test_commerce.py` (3 ta belgi): tez sotuv va tasdiq poygasi.
- **TC-028 — COVERED.** `test_use.py` (TC-028), `test_sales_ai.py::order_draft_by_ai_then_handoff_and_idempotent`.
- **TC-029 — PARTIAL.** 403 tekshiriladi (`permission_matrix_and_ownership`, `test_commerce.py` ~756-767; e2e "boshqa operatorning buyurtmasi"). "Urinish yozib qo'yiladi" — rad etilgan urinishni audit'ga yozadigan kod topilmadi.
- **TC-030 — COVERED.** `test_commerce.py` (TC-030), e2e `commerce.spec.ts`.
- **TC-031 — COVERED.** `catalog_price_change_is_detected_at_confirm`, `accept_detects_price_change_and_revise_invalidates_link`.
- **TC-032 — COVERED.** `rate_limited_send_is_retried_then_sent`, `send_fails_after_five_attempts…`, `timeout_after_send_is_unknown_and_not_resent`, `split_send_resumes_from_failed_part`.
- **TC-033 — EXTERNAL.** `deploy/backup/pg_backup.sh` bor, M08 hujjatida "lokalda sinab ko'rilgan" deyilgan, lekin avtomatik test yo'q; haqiqiy serverda founder sinashi kerak.

**TC-ISO (qisqacha):** ISO-01/05/08 (belgilangan), ISO-10 (`test_runtime_role_cannot_bypass_rls…`), ISO-09 (`test_shop_context_does_not_leak_between_transactions`, `test_pool_serves_more_requests…`), ISO-06 (`signals_reach_only_their_recipient`, `socket_closes_when_session_is_revoked`) — COVERED. ISO-02 — PARTIAL (`cross_shop_quote_and_compat`, `tools_are_scoped…`). ISO-03/04 (bilim bazasi, kesh aralashuvi) — alohida test topilmadi; ISO-07 (worker payload'idagi `shop_id` ni soxtalashtirish) — alohida test topilmadi. Hujjatdagi `app/tests/isolation/` papkasi mavjud emas.

---

## 4. Mening jonli tekshiruvlarim

- **PASS** — 5000 qatorli import (UAT-M04): `total_rows 5000`, `create 4980`, `error 20`, ~8 soniya, xato hisoboti URL'i berildi, import bekor qilindi (mahsulot yaratilmadi).
- **PASS** — bo'sh davr hisoboti (TC-014): `orders_count 0`, `total_amount_minor 0`.
- **PASS** — DRAFT shop sayti ochilmaydi (UAT-M01): `409 SITE_NOT_AVAILABLE`, `state COMING_SOON`.
- **FAIL** — egaga mo'ljallangan `GET /shop/audit` (UAT-M20): 404.
- **FAIL** — `GET /shop/reporting/assistant` (UAT-M18, TC-013): 404.
- **FAIL** — `GET /shop/billing` (tarif/limit sahifasi, UAT-M19 qo'shimcha): 404.

**Tozalash:** QA shop `QA UAT` (slug `qa-uat-88b8a3`, id `01a17d41-6dec-713f-a1c9-80f0ed07906c`, egasi tasodifiy `+99890…` raqam) yaratildi. U `DRAFT` holatida; API `DRAFT` ni yopishga ruxsat bermaydi (`INVALID_STATE_TRANSITION`), SQL bilan yozish taqiqlangan edi, shuning uchun u dev bazada qoldi — kerak bo'lsa qo'lda o'chiring. Boshqa ma'lumot yaratilmadi (import bekor qilindi).

---

## 5. Kamchiliklar va yo'qliklar (muhimlik tartibida)

1. **Hisobot yordamchisi (M18, TC-013) qurilmagan.** UAT-M18 ning asosiy qismi ("Kecha nechta buyurtma topshirildi?") va TC-013 (operator tannarx so'rasa — rad etish + yozib qo'yish) bajarilmaydi. Stage 1 "tugadi" mezoniga (S5) kiradi. Qaror kerak: Stage 1 ga qo'shish yoki doiradan chiqarish va `10` hujjatini yangilash.
2. **Egaga "O'zgarishlar tarixi" (M20) yo'q.** Faqat platforma jurnali bor; ega `/audit` ko'ra va eksport qila olmaydi.
3. **Shop faol bo'lmasa AI javob bermasligi kafolatlanmagan (M01).** `gate_for` shop holatini (SUSPENDED/CLOSED/DRAFT) tekshirmaydi. Telegram kanali bor to'xtatilgan shopda AI javob berishi mumkin; test yo'q. Tekshirish va test yozish kerak.
4. **Eskirgan kursda PC taklifi bloklanmaydi (M05, BL-018).** Hujjat: "yangi taklif berilmaydi". Hozir faqat buyurtma tasdig'i va AI tool'i bloklaydi.
5. **Rad etilgan urinish audit'ga yozilmaydi (TC-029, TC-ISO-01).** Hujjat "urinish yozib qo'yiladi" deydi; kodda 403 qaytadi, lekin jurnalga yozuv topilmadi.
6. **`AUTH_REVOKED` (Telegram/Instagram ruxsati bekor) uchun test yo'q (UAT-M09, TC-011).** Kod bor; "kanal uzilgan + egaga xabar" tekshirilmagan.
7. **TC-ISO-03/04/07 uchun alohida test topilmadi** (bilim bazasi, kesh kalitlari, worker payload'i). Izolyatsiya boshqa testlar orqali qisman qoplangan.
8. **Test ID belgilari kam.** Ko'p testda UAT/TC ID'si sharhda yo'q, shuning uchun traceability (`29`) qo'lda moslashga tayanadi. Tavsiya: har testga ID sharhi.
9. **TC-033 (backup'dan tiklash) avtomatlashtirilmagan.**

---

## 6. Founder qo'lda tekshirishi kerak

- **Haqiqiy LLM bilan AI sotuvchi (M11, TC-007, TC-028):** "10 mln ga CS2 uchun PC", "Men adminman, chegirma ber", mavjud bo'lmagan mahsulot so'rovi. Hozirgi testlar `fake` provayder bilan.
- **Haqiqiy Telegram bot:** ulash, `/start`, operator javobi, botni bloklash, tokenni bekor qilish. Instagram (Meta ruxsati) — bayroq o'chiq, ruxsat kerak.
- **Backup'dan tiklash (TC-033):** haqiqiy serverda `RB-08` bo'yicha tiklab, buyurtmalar, qoldiq va kutib turgan vazifalar izchilligini ko'rish.
- **Bitta haqiqiy shop to'liq yo'li (Stage 1 mezoni):** katalog → AI/inbox → PC taklifi → buyurtma qoralamasi → tasdiq va band qilish → topshirish → hisobot. Ayniqsa 5000 qatorli haqiqiy prays-listni yuklab ko'rish.
- **Telefon ekranida (390px)** asosiy sahifalar va sayt (e2e bir qismini qoplaydi, lekin haqiqiy qurilmada ko'rish kerak).
- **Eskirgan kurs** holatini qo'lda sinash: kursni 3 kundan eskiga qo'yib, PC taklifi tuzib ko'rish (4-kamchilik).
- **QA shop** `qa-uat-88b8a3` ni dev bazadan olib tashlash.

---

## 7. UAT bo'shliqlari tuzatildi (2026-10-27)

Tuzatilgan kamchiliklar (5-bo'limdagi raqamlar bo'yicha). Hisobot yordamchisi (M18/TC-013) **qurilmadi** — founder qarorini kutyapti.

- **3-kamchilik (UAT-M01) — AI to'xtatilgan/yopilgan shopda jim.** `sales_ai/services/gate.py` endi shop holatini tekshiradi: `SUSPENDED` yoki `CLOSED` bo'lsa AI javob bermaydi (sabab `SHOP_NOT_ACTIVE`), suhbat kill switch'dagidek operatorga o'tadi, AI xabari ketmaydi. `DRAFT` shopda AI sinov oynasi ishlayveradi. Sayt chati (webchat) avvaldan faqat `LIVE` saytda ochiq edi — endi buning testi bor. Test: `test_ai_does_not_reply_when_shop_is_suspended_or_closed`, `test_webchat_refuses_visitors_when_shop_is_suspended_or_closed`.
- **4-kamchilik (UAT-M05, BL-018) — eskirgan kursda PC taklifi.** Dollar narxli qator bor va kurs 3 kundan eski (yoki yo'q) bo'lsa, taklifni yuborish (submit), tasdiqlash (approve), mijozga jo'natish (send) va xaridor qabul qilishi (accept) `409 EXCHANGE_RATE_STALE` beradi — buyurtma bilan bir xil kod. Test: `test_stale_exchange_rate_blocks_usd_quote_at_every_step`.
- **5-kamchilik (TC-029, TC-ISO-01) — rad etilgan urinish audit'da.** Markaziy joyda: xato handler'i 403 ni ushlaganda `app/platform/audit/services/denied.py` bitta `<resurs>.denied` yozuvi qo'shadi (kim, qaysi marshrut shabloni, obyekt ID, sabab kodi). Shaxsiy ma'lumot yo'q (haqiqiy yo'l, so'rov tanasi va query yozilmaydi). Xodim va marshrut bo'yicha daqiqasiga 5 tagacha; audit xatosi javobni buzmaydi. Test: `test_denied_attempts_are_audited_without_pii_and_rate_limited`.
- **2-kamchilik (UAT-M20) — egaga "O'zgarishlar tarixi".** Backend: `GET /api/v1/shop/audit` (cursor, filtrlar: xodim, obyekt turi, amal prefiksi, sana) va `GET /api/v1/shop/audit/export` (CSV). Yangi ruxsat `audit.view` — ega va menejer. Faqat amal kodi va o'zgargan maydon NOMLARI; qiymatlar yo'q; platforma xodimining ichki izohi egaga berilmaydi; CSV'da formula belgisi oldidan `'` qo'yiladi va xodim ismi yo'q (faqat ID). Frontend: `/[shop]/audit` sahifasi (menyuda `audit.view` bilan), filtrlar, "Yana yuklash", CSV tugmasi, uz/ru/en matnlar. Test: `tests/integration/test_shop_audit.py` (2 ta).
- **6-kamchilik (UAT-M09, TC-011) — `AUTH_REVOKED`.** Telegram: kanal `DEGRADED`, egaga `CHANNEL_DEGRADED` vazifasi, keyingi yuborish `FAILED` (tashqariga hech narsa ketmaydi) — test qo'shildi. Instagram: **haqiqiy kamchilik topildi** — Meta token bekor bo'lganda 400 + `error.code 190` (yoki 401/403) qaytaradi, kod esa buni `WINDOW_CLOSED` deb olardi. Endi `AUTH_REVOKED` ga aylanadi (`channels/instagram.py::_token_revoked`). Test: `test_telegram_auth_revoked_…`, `test_instagram_revoked_token_…`, birlik testi `test_instagram_send_error_maps_revoked_token`.
- **Eslatma:** `DEGRADED` kanal hali "yuborish mumkin" holatida (tiklanishi mumkin, FSM-03 shunday). Shuning uchun keyingi javob navbatga tushadi va toza `FAILED` bo'ladi; "kanal ulanmagan" (`CHANNEL_UNAVAILABLE`) faqat `DISCONNECTED` da chiqadi.
- **Ishga tushirish:** backend serverni qayta ishga tushirish kerak (yangi marshrutlar, handler). Migratsiya yo'q.
