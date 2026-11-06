# Bajarilgan ishlar — rejaning holati

> **Nima uchun:** reja [27-roadmap-and-tasks.md](../27-roadmap-and-tasks.md) da. Bu papkada esa **haqiqatda nima qilingani** yoziladi: qaysi bandlar bitdi, qaysi faylda qanday kod bor, qanday tekshirildi.
> **Qoida:** har modul tugaganda shu yerga hisobot qo'shiladi. Yangi odam (yoki AI yordamchi) kodni o'qishdan oldin shu fayllarni o'qiydi.

---

## Reja bo'yicha holat (2026-10-26)

```
Texnik asos ──▶ 1. Auth, shop, xodimlar ──▶ 1b. Platforma paneli ──▶ 2. Katalog ──▶ 3. Savdo ──▶ 4. Shop sayti
     ✅           ✅ backend + frontend       ✅ A bosqich + QA      ✅ + QA        ✅ + QA       ✅ + QA (commit kutmoqda)
──▶ 5. Kanallar va inbox (+ fon ishlari) ──▶ 6. AI sotuvchi ──▶ 7. Xabarnomalar, kafolat, hisobotlar
   ✅ + QA (commit kutmoqda)
```

- [x] **Texnik asos** — S0-01, S0-02, S0-03, S0-07 → [M00-foundation.md](M00-foundation.md)
- [x] **1-modul. Auth, shoplar va xodimlar** — S0-04 → [M01-auth-shops-staff.md](M01-auth-shops-staff.md)
- [x] **1b. Platforma paneli, A bosqich** — business/15 to'liq: bosh sahifa, shoplar, kartochka, jurnal, jamoa, izohlar, ⌘K, demo ma'lumot. Mustaqil QA tekshiruvi va tuzatishlar (2026-10-25) → [M01b-platform-admin.md](M01b-platform-admin.md)
- [x] **2-modul. Katalog** — mahsulot va SKU, narx va kurs, texnik ma'lumotlar kutubxonasi, fayllar (S1-02, S1-03, S1-04, S0-08). Baza — DEC-133. Backend + frontend + e2e, mustaqil QA 2 tur (2026-10-25) → [M02-catalog.md](M02-catalog.md)
- [x] **3-modul. Savdo (commerce)** — ombor (S1-05), tez sotuv, buyurtmalar va band qilish. Baza — DEC-134, DEC-136. Backend + frontend + e2e, mustaqil QA 2 tur (2026-10-26) → [M03-commerce.md](M03-commerce.md). Lead va PC taklifi — 6-modul bilan
- [x] **4-modul. Shop sayti** — S1-07. Baza — DEC-135, DEC-141 (taklif). Backend + xaridor sayti (`shop-storefront`) + panelda "Sayt" bo'limi, e2e, mustaqil QA 2 tur (2026-10-26) → [M04-storefront.md](M04-storefront.md). Commit founder ko'rib chiqqandan keyin
- [x] **5-modul. Kanallar va inbox** — S2, fon ishlari (S0-06), katalog importi (S1-06). Baza — DEC-137…140 (taklif, founder ko'rib chiqadi). 5a fon ishlari, vazifalar, xabarnomalar, realtime → [M05a](M05a-jobs-notifications.md); 5b sayt chati, Telegram, inbox, xaridorga holat xabarlari → [M05b](M05b-messaging.md); 5c katalog importi (CSV/XLSX) → [M05c](M05c-catalog-import.md). Har biri backend + frontend + e2e + mustaqil QA (2026-10-26). Commit founder ko'rib chiqqandan keyin
- [ ] **6-modul. AI sotuvchi** — S3, PC moslik engine'i. Baza — DEC-142…144 (taklif). **6a backend bitdi (2026-10-26):** leadlar, PC takliflari, xaridor havolasi, "PC yig'ish" → [M06a-quotes.md](M06a-quotes.md); moslik engine'i → [M06a-compat-engine.md](M06a-compat-engine.md). **6b backend bitdi (2026-10-26):** LLM qatlami (Gemini, Claude, Fake), agent loop va 8 tool, OFF/SHADOW/SUGGEST/AUTO, inbox'da AI takliflari, limitlar → [M06b-ai-runtime.md](M06b-ai-runtime.md). **6c backend bitdi (2026-10-27):** baholash (golden 40 savol, deterministik ball, judge), bake-off solishtiruvi, shop "AI sifati" → [M06c-ai-eval.md](M06c-ai-eval.md). **6+ (Instagram izohlari) backend bitdi (2026-10-27):** «+» va narx so'rovi → Direct'ga javob, kayfiyat (AI), panel API, `FEATURE_CHANNEL_INSTAGRAM_DM` ostida → [M06p-instagram-comments.md](M06p-instagram-comments.md).
- [x] **Instagram izohlari** — DEC-132: backend 6+ da bitdi (yuqoriga qarang), haqiqiy akkaunt bilan sinov qoldi
- [ ] **7-modul. Xabarnomalar, kafolat, hisobotlar** — S2/S5 **7a backend bitdi (2026-10-27):** tannarx → [M07-cost-reporting.md](M07-cost-reporting.md). **7b backend bitdi (2026-10-27):** kafolat murojaatlari (`support`), ombor karantini va almashtirish, xaridorga 4 xabar → [M07b-warranty.md](M07b-warranty.md)
- [x] **AI avtomatlashtirish (pilotgacha)** — DEC-149 (founder tasdiqladi), tafsilotlar DEC-151 (taklif). 4 qismi ham bitdi (2026-11-02): narx ro'yxati, ovozli xabar, kartochka qoralamasi, "So'rashdi, lekin yo'q" + omborda yo'q tovar uchun "buyurtma asosida" → [M10-ai-automation.md](M10-ai-automation.md). Commit founder ko'rib chiqqandan keyin
- [x] **Instagram haqiqiy ulanish** — haqiqiy DM keldi (2026-10-30); "Instagram bilan ulash" tugmasi, Instagram ilovasidan yozilgan javob, Meta ma'lumot o'chirish callback'i, DEC-150 (taklif) → [M06q-instagram-connect.md](M06q-instagram-connect.md)
- [ ] **Stage 2 — shoplar tarmog'i** — DEC-152 (taklif). **Backend va panel (2026-11-02…03):** M21 o'zi ro'yxatdan o'tish, M22 kassa/ERP qoldig'i (umumiy ulagich), M23/M24 umumiy mahsulot va ommaviy takliflar, M25 ko'chirish, M26 tariflar, M29 belgi va shikoyatlar, M30 hamkor API; DEC-153 → [S2-network.md](S2-network.md)
- [ ] **Stage 3 — global qidiruv** — 1-bo'lak (2026-11-03): M31 qidiruv, M32 narx solishtirish, M35 do'konga o'tish; xaridor sayti `apps/marketplace` → [db/marketplace.md](../db/marketplace.md). Qoldi: M33 xarita, M34 global AI, M36 xaridor akkaunti, M37 reklama, M38 sitemap, M39 global Telegram bot
- [x] **Frontend: 1-modul** — shop paneli + platforma paneli, e2e → [M01 §8](M01-auth-shops-staff.md#8-frontend-va-integratsiya-2026-10-23)
- [ ] **Frontend: keyingi modullar** — har modul bilan birga
- [x] **Monitoring va deploy** — S0-05, S0-10: Docker image'lar, `deploy/docker-compose.prod.yml` (bitta VPS), nginx + certbot, kunlik backup va tiklash, Sentry, JSON loglar, CI. Founder uchun "Serverga chiqarish" qo'llanmasi (2026-10-27) → [M08-deploy.md](M08-deploy.md). Hali serverga o'rnatilmagan; commit founder ko'rib chiqqandan keyin

## Muddati bor texnik qarzlar

- [x] **TD-01** — partition'larni oldinga yaratadigan rejali ish: `audit_partition_create` (har oy 25-si), `platform.ensure_monthly_partitions` (SECURITY DEFINER) → [M05a](M05a-jobs-notifications.md)
- [x] **TD-02** — eskirgan `idempotency_keys` ni tozalash: `idempotency_cleanup` (har soat) → [M05a](M05a-jobs-notifications.md)
- [x] **TD-03** — production fayl ombori: S3-mos adapter `app/platform/storage/s3.py` (boto3, yopiq + ixtiyoriy ochiq bucket, havolalar avvalgidek API orqali imzoli), `STORAGE_BACKEND=s3` sozlamasi, moto testlari → [M08](M08-deploy.md). **Qoldi:** `app/main.py` va seed'larda `build_file_storage(settings.storage_config())` ga o'tish (bir qator; boshqa ish ketayotgan fayl)

---

## Hisobot qanday yoziladi

Har modul uchun bitta fayl: `M<raqam>-<nom>.md`. Ichida quyidagi bo'limlar shu tartibda bo'ladi:

1. **Nima bitdi — qisqacha.** Ikki-uch gap va asosiy oqim strelkalar bilan.
2. **Rejadagi bandlar.** Checklist. Alohida yoziladi: ataylab keyinga qoldirilganlar (sababi bilan) va kartadan farqlar.
3. **Fayllar xaritasi.** Papka daraxti, har faylga bir qator izoh.
4. **Qaysi faylda nima bor.** Papkalar bo'yicha bo'lingan: har fayl, ichidagi asosiy klass va funksiyalar, ular nima qiladi va nega shunday.
5. **Testlar.** Natija va har bir tekshirilgan holat.
6. **Jarayonda topilgan muammolar.** Nima bo'ldi va qanday tuzatildi.
7. **Keyingi modulga meros.** Keyingi modul nimadan foydalanadi va qaysi qoidaga amal qiladi.
