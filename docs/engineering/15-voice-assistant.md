# 15 — Ovozli hisobot yordamchisi (beta)

> **Versiya:** v2 (2026-10-22). Eski `16_VOICE_AI_ARCHITECTURE` o'rnini bosadi.
> **Domen:** `reporting` → `assistant` sub-moduli (M18). **Platform:** `llm` (STT/TTS adapterlari, redaction), `storage`.
> **Qarorlar:** DEC-112 (avval matn, ovoz — bake-off'dan keyin beta), DEC-010 (STT/TTS bake-off), DEC-117 (audio transkripsiyadan keyin o'chiriladi), ADR-012.
> **Holat:** S5 da **matnli** hisobot yordamchisi; ovoz — feature flag `reporting.voice` bilan beta. Faqat o'qiydi. Ovoz identifikatsiya emas.

## 1. Muammo va yechim

**Muammo:** shop egasi do'konda yoki yo'lda tez savol bermoqchi: "Kecha nechta buyurtma topshirildi?". Lekin ovozni tanish o'zbek-rus aralash nutqda xato qilishi mumkin — "15 mln" va "50 mln" adashsa, noto'g'ri qaror qabul qilinadi (TC-012).

**Yechim:**
1. Ovoz → matn → **foydalanuvchi matnni ko'radi va tuzatadi** → keyin so'rov.
2. So'rov faqat **metrika registridagi** ruxsat etilgan metrikalarga aylantiriladi (`19-reporting-metrics.md`). SQL yo'q.
3. Ovoz orqali hech narsa o'zgartirilmaydi.
4. Matnli yordamchi bilan bitta yo'l: ovoz faqat kirish va chiqish qatlami.

---

## 2. Oqim

```
Ega "Gapirish"ni bosib turadi (press-to-talk, yozish belgisi ko'rinadi)
  ──▶ POST /api/v1/shop/reports/voice/transcriptions   (audio, ≤ 60 s)
        reporting/assistant ──▶ platform/llm.SpeechToTextPort (server tomonida, kalit brauzerga chiqmaydi)
        ◀── matn + til + ishonch darajasi
        audio darhol o'chiriladi (DEC-117); faqat matn qaytadi
  ──▶ UI: tahrirlanadigan matn. Ishonch past, katta summa yoki noaniq metrika → tasdiq majburiy
  ──▶ POST /api/v1/shop/reports/assistant/queries   (tasdiqlangan matn — matnli yordamchi bilan BIR XIL endpoint)
        intent → metric_ids + davr + filtrlar (LLM faqat ajratadi, platform/llm redaction bilan)
        ruxsat: foydalanuvchi roli (ActorContext) — operator faqat o'z raqamlarini
        reporting.metrics.query(...) → qiymat, valyuta, timezone, data_as_of, quality_flags
  ◀── javob: matn + jadval/grafik + dalil
  ──▶ ixtiyoriy: TTS (platform/llm.TextToSpeechPort) → qisqa muddatli audio havola (TTL 10 daqiqa)
```

Ikki bosqich ataylab ajratilgan: matn tasdiqlanmaguncha so'rov bajarilmaydi.

---

## 3. Til va raqamlar

- Tillar: o'zbek (lotin va kirill aralash), rus, ingliz; aralash atamalar (GPU, RTX, SSD).
- Raqamlar: "o'n besh million", "15 mln", "пятнадцать миллионов" → bitta normal ko'rinish; valyuta (so'm/dollar) aniq.
- Sanalar: "shu oy", "прошлая неделя", "last Friday" → shop timezone'ida (`Asia/Tashkent` default).
- "Topshirilgan buyurtma summasi" va "to'landi belgisi qo'yilgan summa" farqlanadi (DEC-100a).
- Ishonch past yoki ikki ma'noli bo'lsa — 2 ta aniq variant taklif qilinadi.

---

## 4. Metrikalar

**Yagona manba:** `19-reporting-metrics.md`. Ovozli va matnli yordamchi faqat u yerdagi `metric_id` larni ishlatadi. Stage 1 asosiylari: `orders_completed_count`, `orders_completed_amount`, `orders_paid_marked_amount` (tekshirilmagan, `quality_flags: UNVERIFIED_PAID_MARK`), `orders_pending_confirmation_count`, `leads_by_channel`, `top_products_by_units`, `conversation_first_response_p50`, `stock_low_count`. Foyda — Stage 1 da yo'q: `NO_COST_DATA`.

Har javobda: davr, timezone, valyuta, `data_as_of`. So'm va dollar jim qo'shilmaydi.

---

## 5. API

| Metod va yo'l | Ruxsat | Izoh |
|---|---|---|
| `POST /api/v1/shop/reports/voice/transcriptions` | `reporting.assistant.use` + feature flag | multipart audio, ≤ 60 s, ≤ 2 MB; javob: `{transcript, language, confidence, needs_confirmation}` |
| `POST /api/v1/shop/reports/assistant/queries` | `reporting.assistant.use` | `{text, source: "TEXT" \| "VOICE"}`; javob: `{answer_text, metrics[], period, data_as_of, quality_flags, tts_url?}` |

Rate limit: foydalanuvchiga daqiqasiga 10 so'rov. Xarajat `platform/billing` ga yoziladi.

---

## 6. Maxfiylik va ruxsat

- Audio faqat xotirada yoki vaqtinchalik storage'da, transkripsiyadan keyin o'chiriladi (DEC-117); faqat redact qilingan matn qoladi.
- STT golden set — alohida yozma rozilik bilan yig'iladi (`16`), mahsulot ma'lumotidan alohida.
- Ovoz shaxsni tasdiqlamaydi: ruxsatni joriy login qilgan foydalanuvchi va uning roli belgilaydi.
- Tannarx va xaridor ma'lumoti kabi sezgir metrikalar — faqat ruxsati borlarga; eksport uchun qo'shimcha tasdiq (`10`).
- Mikrofon doim tinglamaydi — faqat tugma bosilganda.

---

## 7. Sifat va beta shartlari

**Bake-off (DEC-010):** 2–3 hosted STT/TTS provayder; o'zbekcha golden set — 300 yozuv (uz/ru/en, turli talaffuz, aralash nutq) + 100 ta raqam/sana/summa.

| O'lchov | Nima |
|---|---|
| WER / CER | So'z va belgi xatosi |
| `numeric_slot_exact_match` | Raqam, summa, sana aniq to'g'rimi |
| `intent_accuracy`, `metric_id_accuracy` | To'g'ri metrika tanlandimi |
| p95 latency | Ovozdan javobgacha |
| TTS talaffuzi | Raqam va mahsulot nomlari |

**Beta sharti:** tekshirilgan muhim to'plamda **birorta ham noto'g'ri moliyaviy raqam yo'q**; tushunarsiz matn — taxmin emas, aniqlashtirish. Chegara qiymatlari bake-off'dan keyin `16` da qotiriladi.

---

## 8. Xato holatlari

| Holat | Foydalanuvchi ko'radi |
|---|---|
| STT ishlamayapti | Matn bilan yozish taklifi |
| Til noaniq | Tilni tanlash |
| So'rov ikki ma'noli | 2 ta aniq variant |
| Metrika yo'q yoki ruxsat yo'q | Nima uchun yo'qligi, qanday ma'lumot yetishmasligi |
| TTS ishlamayapti | To'g'ri matn va grafik |
| Uzoq hisob | Jarayon belgisi va bekor qilish |

## 9. Kelajak: ovoz bilan o'zgartirish (alohida reliz)

Hozir yo'q. Agar keyin qo'shilsa: niyat → siyosat tekshiruvi → aniq o'zgarishni ko'rsatish (SKU, eski/yangi qiymat) → UI'da qo'shimcha tasdiq → domen service va audit → natijani o'qib berish. "Hamma narxni tushir" kabi buyruqlar hech qachon avtomatik bajarilmaydi. Alohida ADR talab qilinadi.

## 10. Testlar

| ID | Sinov |
|---|---|
| TC-012 | "15 mln" / "50 mln" — matn ko'rsatiladi va tasdiq so'raladi |
| TC-013 | Operator tannarx yoki foyda so'raydi → rad, urinish yoziladi |
| TC-014 | Davrda buyurtma yo'q → "0", "ma'lumot yo'q" emas |
| TC-VO-01 | Audio transkripsiyadan keyin storage'da qolmaydi |
| TC-VO-02 | Feature flag o'chiq → transcription endpoint 404 `FEATURE_NOT_AVAILABLE` |

## Keyingi qadam

→ [16-ai-data-and-evaluation.md](16-ai-data-and-evaluation.md) — golden set va bake-off
→ [19-reporting-metrics.md](19-reporting-metrics.md) — metrika registri
