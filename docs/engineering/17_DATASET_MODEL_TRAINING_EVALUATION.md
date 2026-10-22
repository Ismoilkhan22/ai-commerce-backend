# TECH-17 — Dataset governance, model strategy and evaluation

**Status:** dataset/model program design; no model currently trained. **Primary objective:** product matching and multilingual sales/voice accuracy that outperforms baseline, not train large foundation LLM prematurely.

## 1. Datasets and owners
| Dataset | Example label/schema | Collection permission | Use |
|---|---|---|---|
| Merchant SKU catalog | id, brand, MPN, specs, condition, merchant | merchant license/contract | retrieval and matching |
| PC compatibility golden | part IDs, rule version, PASS/BLOCK/REVIEW, evidence | verified vendor/manufacturer specs | deterministic engine evaluation |
| Multilingual customer intents | utterance, language, intent, slots, ambiguity | consented/anonymized or synthetic | intent/tool accuracy |
| Product-pair matches S2 | SKU A/B, true_identity_bool, reason, reviewer | merchant public identifiers/allowed sources | precision-first match training |
| ASR/TTS voice | audio, transcript, locale, accent bucket, consent | explicit voice consent | STT evaluation/tuning |
| Support correction feedback | model output, verified correction, evidence, error class | restricted, redacted | regression set |
| Prompt injection corpus | hostile text, expected blocked tool | synthetic/safe research | safety red-team |

## 2. Versioning and storage
Dataset manifest `{dataset_id,version,license_basis,owner,source_system,extracted_at,consent_scope,retention,rows,checksum,split_seed,label_schema}`. Separate raw/restricted from cleaned training-ready; immutable snapshots and SHA-256 checksums. No raw user chats imported by default, no public leak through notebooks or Git. Training and evaluation split by **merchant/product family and time** to reduce leakage (not random near-duplicates in test).

## 3. Data preparation pipeline
1. Source contract + lawful basis/merchant permission.
2. Collect with provenance, PII detection and redaction; quarantine unlicensed.
3. Normalize manufacturer, MPN, capacity, Cyrillic/Latin, units, currency, condition.
4. Label with clear guidelines, hard negative examples (5060 vs Ti; 8GB vs 16GB).
5. Double-label a representative set, record disagreements, adjudicate expert rules.
6. Split train/dev/test with out-of-merchant family holdout; freeze blind golden set.
7. Register artifacts and benchmark; deploy via explicit model alias and rollback.
8. Log opt-in anonymized correction with human moderation for future training.

## 4. Baseline model strategy
| Task | Phase 1 approach | Upgrade condition |
|---|---|---|
| PC compatibility | deterministic rule engine & curated evidence | unknown rules added after expert validation, not LLM |
| Catalog search | structured filters + PG FTS/trgm | embeddings only if measured recall gain |
| Sales dialogue | hosted multilingual LLM + strict tools | fine-tune after enough licensed annotated errors |
| Voice transcription | provider STT trial comparison in 3 languages | fine-tune/local when quality/privacy/cost justify |
| Merchant report answers | metric registry + fixed template/LLM paraphrase | evaluate if template suffices |
| Canonical matching S2 | rules/exact IDs → candidate retrieval → reranker→review | supervised match classifier when gold pairs mature |

## 5. Evaluation contract
- Every model/provider has `eval_dataset_version`, prompt_version, rubric, score, cost, latency and region/compliance check.
- Measures: merchant sales intent/slot accuracy, product groundedness, PC rule exactness, hallucinated price count (zero tolerated on critical set), cross-tenant leak rate (zero), ASR numeric exact match, matching **precision** and false-merge rate, total cost per successful lead/order.
- Thresholds configured after baseline and risk review; claiming “99% model accuracy” without held-out contextual set is prohibited.
- Shadow rollout, 5% test tenant/feature flag, A/B only with privacy review, nightly regression. Rollback on wrong price/stock, unauthorized action, quality or cost spike.

## 6. Sample annotation structure
```json
{
  "utterance":"Menga 10 million so'mgacha CS2 uchun kompyuter kerak",
  "language":"uz",
  "intent":"find_pc_build",
  "slots":{"budget_minor":1000000000,"currency":"UZS","workload":"cs2"},
  "ambiguities":[],"allowed_tools":["pc.compatibility_check","catalog.search"],
  "must_not_do":["mark_payment_verified","write_stock_balance"]
}
```
*Note:* `budget_minor` assumes ISO currency exponent 2 and represents 10,000,000 UZS; implementation must use currency metadata and human-readable display, not literal float conversion.

## 7. Training compute and governance
No training GPU initially required; use hosted inference and evaluation runner (bounded concurrency); encrypted object storage for curated datasets; training after threshold with reproducible environment/model cards/hardware resource budget. Track license constraints for product images/specs and data retention, locale quality fairness, vendor terms on model provider storage/training, user revocation.

## 8. Required evaluations before launch
Red-team on AI tools/injection, merchant boundaries, money/stock claim, hallucinated hardware benchmark, ambiguous voice amount, user opt-out data retention. Sign-off from founder after inspecting errors, not just aggregate score.
