# Bajarilgan ishlar — rejaning holati

> **Nima uchun:** reja [27-roadmap-and-tasks.md](../27-roadmap-and-tasks.md) da. Bu papkada esa **haqiqatda nima qilingani** yoziladi: qaysi bandlar bitdi, qaysi faylda qanday kod bor, qanday tekshirildi.
> **Qoida:** har modul tugaganda shu yerga hisobot qo'shiladi. Yangi odam (yoki AI yordamchi) kodni o'qishdan oldin shu fayllarni o'qiydi.

---

## Reja bo'yicha holat (2026-10-25)

```
Texnik asos ──▶ 1. Auth, shop, xodimlar ──▶ 1b. Platforma paneli ──▶ 2. Katalog ──▶ 3. Savdo ──▶ 4. Shop sayti
     ✅           ✅ backend + frontend       ✅ A bosqich + QA   ⏳ backend ✅   ⏳ baza ✅
──▶ 5. Kanallar va inbox (+ fon ishlari) ──▶ 6. AI sotuvchi ──▶ 7. Xabarnomalar, kafolat, hisobotlar
```

- [x] **Texnik asos** — S0-01, S0-02, S0-03, S0-07 → [M00-foundation.md](M00-foundation.md)
- [x] **1-modul. Auth, shoplar va xodimlar** — S0-04 → [M01-auth-shops-staff.md](M01-auth-shops-staff.md)
- [x] **1b. Platforma paneli, A bosqich** — business/15 to'liq: bosh sahifa, shoplar, kartochka, jurnal, jamoa, izohlar, ⌘K, demo ma'lumot. Mustaqil QA tekshiruvi va tuzatishlar (2026-10-25) → [M01b-platform-admin.md](M01b-platform-admin.md)
- [ ] **2-modul. Katalog** — mahsulot va SKU, narx va kurs, texnik ma'lumotlar kutubxonasi, fayllar (S1-02, S1-03, S1-04, S0-08). Baza tasdiqlangan — DEC-133 ([db/catalog.dbml](../db/catalog.dbml)). Backend bitdi (2026-10-25) → [M02-catalog.md](M02-catalog.md). Hozir: frontend
- [ ] **3-modul. Savdo (commerce)** — ombor (S1-05), tez sotuv, buyurtmalar va band qilish, saytdan buyurtma so'rovi. Baza tasdiqlangan — DEC-134 ([db/commerce.dbml](../db/commerce.dbml)). Lead va PC taklifi — 6-modul bilan
- [ ] **4-modul. Shop sayti** — S1-07
- [ ] **5-modul. Kanallar va inbox** — S2, fon ishlari (S0-06), katalog importi (S1-06)
- [ ] **6-modul. AI sotuvchi** — S3, PC moslik engine'i
- [ ] **Instagram izohlari** — DEC-132: 5 va 6-modullardan keyin
- [ ] **7-modul. Xabarnomalar, kafolat, hisobotlar** — S2/S5
- [x] **Frontend: 1-modul** — shop paneli + platforma paneli, e2e → [M01 §8](M01-auth-shops-staff.md#8-frontend-va-integratsiya-2026-10-23)
- [ ] **Frontend: keyingi modullar** — har modul bilan birga
- [ ] **Monitoring va deploy** — S0-05, S0-10, pilotdan oldin

## Muddati bor texnik qarzlar

- [ ] **TD-01** — partition'larni oldinga yaratadigan rejali ish — **2027-12-01 gacha**
- [ ] **TD-02** — eskirgan `idempotency_keys` ni tozalash — 1-pilotdan oldin
- [ ] **TD-03** — production fayl ombori: `FileStorage` porti tayyor, dev va testda disk adapteri (`var/storage`). MinIO olib tashlandi (obrazi Docker Hub'dan yuklanmaydi). S3-mos adapter (masalan, O'zbekistondagi S3-mos xizmat) — deploy bilan, **S0-10 gacha**

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
