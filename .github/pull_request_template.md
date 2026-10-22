## Vazifa
Roadmap ID: S_-__ · Biznes: M__ / BL-___ · DEC: ___ · Test: TC-___ / UAT-M__
Domen / platform moduli: ______

## Nima o'zgardi

## Checklist (docs/engineering/03-module-requirements.md)
- [ ] Qatlamlar: domen boshqa domenni import qilmaydi; lint-imports va tests/architecture o'tadi
- [ ] Domenlararo yozish faqat event (outbox), o'qish faqat Query Port (shared/contracts)
- [ ] shop_id faqat ActorContext'dan; A/B izolyatsiya testi qo'shildi yoki mavjud
- [ ] Migratsiya: o'z schemasi, expand/contract, downgrade ishlaydi, shop_id + RLS
- [ ] Holat o'zgarishi: use.validate_transition + log_transition; repository status yozmaydi
- [ ] Yozish amali: Idempotency-Key, tranzaksiya chegarasi aniq, tranzaksiya ichida tashqi chaqiruv yo'q
- [ ] Event: nomi <domain>.<entity>.<action>, payload versiyalangan, PII yo'q
- [ ] Xatolar K-07 kodlari bilan; yangi kod — katalog va uz/ru/en tarjima
- [ ] Audit yozuvi (sezgir amallar)
- [ ] Log/trace/metrika: PII yo'q, cos_<domain>_... metrikalar
- [ ] Testlar: unit + integratsiya (PostgreSQL) + kerak bo'lsa concurrency
- [ ] docs/modules/<domain>/README.md yangilandi

## Xavf va rollback
