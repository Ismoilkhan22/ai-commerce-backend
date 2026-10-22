# TECH-16 — Business Voice Copilot in Uzbek, Russian and English

**Status:** baseline (2026-10-22, DEC-112, DEC-010, DEC-117); model/provider quality unverified. **Stage 1:** S5 da avval **matnli** hisobot-chat (xuddi shu metric registry va ruxsatlar); ovoz — STT/TTS bake-off (2–3 provayder, o'zbekcha 300 yozuv + 100 raqam/sana) va golden set'dan keyin feature flag bilan beta. READ-ONLY. **Not voice identity biometrics** or unconstrained voice-driven money transfer.

## 1. Experience requirements
Owner opens Voice Copilot in merchant dashboard (staff auth already established), selects or auto-detects `uz/ru/en`, speaks: “Oxirgi 7 kunda qaysi GPU eng ko‘p sotildi?” → sees editable transcript → approved metric resolution → result table/chart + optional spoken answer. If the speaker asks for money/stock mutation, only show a *draft* request for an authorized human confirmation flow, initially disabled.

## 2. Pipeline
```mermaid
sequenceDiagram
 participant U as Merchant user
 participant UI as Voice frontend
 participant API as Voice API (server)
 participant STT as Speech-to-text
 participant O as Intent/tool broker
 participant Q as Metric registry
 participant TTS as Text-to-speech
 U->>UI: Record / press-to-talk
 UI->>API: POST /merchant/voice/transcriptions (audio)
 API->>STT: Audio (server-side; provider kaliti brauzerga chiqmaydi)
 STT-->>API: Transcript+language+confidence
 API-->>UI: Tahrirlanadigan transcript (audio o'chiriladi, DEC-117)
 UI->>U: Preview / correction
 UI->>API: POST /merchant/voice/queries (tasdiqlangan transcript)
 API->>O: Approved transcript + context
 O->>Q: Authorized metric IDs/date filters
 Q-->>O: Facts, units, data_as_of
 O-->>UI: Answer + chart + evidence
 UI->>TTS: Optional localized answer text
 TTS-->>U: Audio response
```

## 3. Language and numbers
UZ Latin+mixed Cyrillic, Russian, English; code-switch terms GPU/RTX/SSD, spoken currency sum/dollar, decimals, quantities, date expressions ('shu oy', 'прошлая неделя', 'last Friday'). Normalize timezone with merchant `Asia/Tashkent` default configurable, distinguish paid revenue vs created-order amount. Human transcript correction mandatory on low confidence, metric ambiguity or large sum.

## 4. Metric allowlist

**Yagona manba:** `29_REPORTING_METRICS_REGISTRY.md` (2026-10-22). Quyidagi jadval — ovoz uchun qisqa ko'rinish; farq bo'lsa 29 to'g'ri.

| Approved metric | Definition | Visibility |
|---|---|---|
| `orders_completed_count` | `COMPLETED` buyurtmalar soni (Stage 1 asosiy, DEC-100) | owner, manager, approved sales |
| `orders_completed_amount` | `COMPLETED` buyurtmalar summasi, valyuta bo'yicha | owner, manager, finance |
| `orders_paid_marked_amount` | merchant "to'landi" belgilagan summa — **tekshirilmagan** (DEC-100a) | owner, finance |
| `orders_pending_confirmation_count` | tasdiq kutayotgan buyurtmalar | owner, manager, sales |
| `leads_by_channel` | kanal bo'yicha leadlar (Telegram / Instagram / web) | owner, manager |
| `orders_paid_count`, `sales_paid_gross_minor`, `sales_refunded_minor` | verified settlement — `DEFERRED` (DEC-100) | — |
| `profit_gross` | Stage 1 da yo'q — tannarx kiritilmaydi; so'ralsa `NO_COST_DATA` (TECH-29 §3.5) | — |
| `top_products_by_units` | unit count on paid/fulfilled policy version | owner, manager, authorized sales |
| `conversation_first_response_p50` | median first response latency on eligible conversations | owner, manager |
| `stock_low_count` | SKU-by-branch below merchant threshold | owner, warehouse |

Natural language planner maps to these metric IDs. It cannot generate raw SQL from voice. Every response states time range, timezone, currency and data freshness; never mix UZS/USD totals silently.

## 5. API and privacy
Ikki bosqich (TECH-08): `POST /api/v1/merchant/voice/transcriptions` (audio → tahrirlanadigan transcript) va `POST /api/v1/merchant/voice/queries` (tasdiqlangan transcript → intent, metric IDs, result JSON, optional TTS asset TTL). Audio transkripsiyadan keyin o'chiriladi, faqat redact qilingan transcript qoladi (DEC-117); ASR golden set alohida, yozma rozilik bilan. No cross-tenant audio used for global training without explicit agreement. If voice input contains customer PII, filter before model provider where feasible.

## 6. Speaker authorization
Voice does not prove identity; current logged-in principal and role decide metric access. Margin/PII sensitive query requires verified session, optionally step-up MFA for exports. Do not interpret someone else's audible command as merchant approval. No always-listening microphone by default; user-initiated press-to-talk, explicit recording indicator.

## 7. Reliability and evaluation
Golden set minimum 300 recordings split across UZ/RU/EN accents and code-switching, plus 100 numeric/date/currency cases; licenses/consent documented. Measure word/character error, `intent_accuracy`, numeric `slot_exact_match`, metric ID selection, p95 latency, TTS pronunciation, hallucinated number count. *Gate*: no user-facing incorrect financial claim on reviewed critical set; unreadable transcript → clarification UI rather than guessing.

## 8. Future write-enabled voice (separate release)
Workflow: parse action → policy validate → preview exact diff (`SKU`,`old/new`, scope) → step-up human confirmation in UI → domain service and audit → result readback. Never allow “pulni yubor”, “hamma narxni pasaytir” to auto-run, even if model confident.

## 9. Failure UX
STT unavailable → text input; language uncertain → choose language; ambiguous request → 2 explicit options; metric unavailable → say unavailable and what data is missing; TTS failure → display correct text/chart; long job → progress and safe cancel. All audio links expiring and tenant scoped.
