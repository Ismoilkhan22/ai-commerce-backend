# ADR-027: LLM: provayderdan mustaqil `LLMPort` + bake-off; PII redaction, zero-retention

**Sana:** 2026-10-21 (v2 formatiga ko'chirildi 2026-10-22)
**Holat:** Accepted (2026-10-21)
**Qaror qabul qiluvchi:** Founder
**Bog'liq:** DEC-009, DEC-016, DEC-118

## Kontekst

LLM provayderi narx, sifat (ayniqsa o'zbekcha) va huquqiy shartlar bo'yicha farq qiladi; xaridor shaxsiy ma'lumoti chet elga ketmasligi kerak.

## Qaror

1. `app/platform/llm` da `LLMPort`; provayder adapterlari almashtiriladi.
2. S3 dan oldin 1 haftalik bake-off (uz/ru/en 200 dialog: tool-calling aniqligi, narx, kechikish); default nomzod — Claude Sonnet (eng so'nggi).
3. LLM'ga faqat redaction'dan o'tgan matn (`[PHONE_1]` kabi); provayder bilan zero-retention / no-training sharti (DEC-016).
4. Shop ma'lumoti bilan AI o'qitilmaydi (DEC-118).

## Ko'rib chiqilgan variantlar

### Darhol multi-provider
- ❌ Rad etildi: murakkab

### Self-hosted model
- ❌ Rad etildi: GPU qimmat, o'zbekcha sifat past

## Oqibatlar

### Ijobiy
Dalilga asoslangan tanlov, huquqiy xavf kam.

### Salbiy
Bake-off uchun test to'plami va vaqt.

### Neytral
Xarajat hisobi `platform/billing`.

## Tekshiruv

Bake-off hisoboti; redaction testlari.

## Qayta ko'rish sharti

Bake-off natijasi yoki narx o'zgarsa.

## Havolalar

- Manba: eski `05_ARCHITECTURE_DECISIONS_ADR.md` (v1)
- [../../decisions/DECISION_REGISTER.md](../../decisions/DECISION_REGISTER.md)
