# Yakuniy qurish va to'liq lokal sinov (2026-11-03)

> **Holat:** qurildi va lokal sinovdan o'tdi, commit qilinmagan — founder ko'rib chiqishi kutilmoqda.
> **Topshiriq (founder):** "qur va to'liq sina — avval o'zing qurib, keyin o'zing sinab, keyin hisobot ber".

---

## 1. Qurilgan qolgan qismlar

- **Hisobot yordamchisi** (UAT-M18, TC-013, TC-014): `POST /shop/reporting/assistant`.
  - AI savoldan faqat ko'rsatkich va davrni tanlaydi. Raqam hisobot servisidan olinadi va javobga shablon bilan qo'yiladi.
  - Ruxsat yo'q ko'rsatkich (foyda, AI xarajati) rad etiladi va urinish audit'ga yoziladi.
  - Davrda ma'lumot bo'lmasa javob "0" bo'ladi. Tannarx kiritilmagan bo'lsa "tannarx ma'lumoti yo'q" deyiladi.
  - Kod: `reporting/services/assistant.py`, migratsiya `platform_0021`.
- **Javobsiz taklifga bitta eslatma** (DEC-149):
  - Taklif yuborilganidan 12 soat o'tib, hali amal qilayotgan bo'lsa, o'sha suhbatga bitta xabar ketadi.
  - Xaridor voz kechgan bo'lsa (BL-061) yoki taklif muddati o'tgan bo'lsa yuborilmaydi.
  - Kod: `quote_service.remind_due`, `notify.on_quote_reminder`, migratsiya `commerce_0012`.
- **Instagram Direct'da rasm va ovoz** (DEC-149):
  - Rasm yopiq omborga saqlanadi, ovoz matnga o'giriladi.
  - Faqat Meta CDN hostlaridan yuklab olinadi (SSRF himoyasi), fayl 10 MB gacha va o'qish paytida cheklanadi.
- **Huquqiy sahifalar** (Meta Live):
  - `apps/marketplace` da `/privacy`, `/terms`, `/data-deletion`, uch tilda.
  - Rekvizitlar `LEGAL_*` sozlamalaridan olinadi. Matnni huquqshunos ko'rib chiqishi kerak.
- **Izolyatsiya testlari** ISO-03 (bilim bazasi) va ISO-07 (fon vazifasida soxta `shop_id`).
- **M09 dan qolgan kamchiliklar:** tekshirildi, ko'pi oldin tuzatilgan ekan: `AUTH_REVOKED` testi, rad etilgan urinish audit'i, eskirgan kursda taklif, ega uchun tarix sahifasi, to'xtatilgan shopda AI.

## 2. Sinov natijalari

- **Backend integratsiya va unit testlari:**
  - QA tuzatishlaridan oldin: 1125 ta o'tdi.
  - Oxirgi yugurish: 1129 ta. Shundan 1128 tasi birinchi urinishda o'tdi.
  - Bitta test tasodifan yiqildi: PII tekshiruvi event vaqt belgisidagi "765" mikrosekundini telefon raqami deb ushladi. Test faqat event mazmunini tekshiradigan qilindi va 3 marta ketma-ket o'tdi.
- **E2E (Playwright, alohida muhit):** 49 ta test.
  - Birinchi yugurishda 47 tasi o'tdi, 2 tasi yiqildi. Sabab: e2e backend'i dev `.env` dagi Instagram bayrog'ini o'qigan. E2E muhiti endi bayroqni aniq o'chiradi; qayta yugurishda o'tdi.
  - Yangi 14 ta e2e test:
    - Global qidiruvga chiqarish va yopish, tekshirilmagan shop;
    - ko'chirish, tarif sahifasi, API kalit;
    - narx ro'yxati sahifasi, AI bilan to'ldirish, "So'rashdi, lekin yo'q";
    - ro'yxatdan o'tish;
    - platforma tariflari, bog'lash, shikoyatlar, reklama tablari.
- **Jonli dev API** (NoutbukUz demo do'koni):
  - yangi endpoint'lar: 28 tadan 28 tasi o'tdi, birorta 500 xato yo'q;
  - to'liq oqimlar: 14 tadan 14 tasi o'tdi (chiqarish, qidiruv, narx o'zgarishi fon jarayonida yangilanishi, reklama, yopish, ko'chirish).
- **Statik tekshiruvlar:** backend'da mypy (624 fayl), ruff va import-linter (2 shartnoma); frontend'da typecheck (4 ilova va paketlar) va eslint. Hammasi toza.

## 3. Mustaqil QA tekshiruvi — 16 topilma, hammasi tuzatildi

- **HIGH 1** — platforma shikoyat bo'yicha yashirgan taklifni ega "yopib qayta ochish" orqali qaytara olardi. Endi bunday taklifni yopish sababni o'zgartirmaydi.
- **MEDIUM 2** — shikoyat bo'yicha yashirish tizim sababi bilan yashirilgan taklifga ta'sir qilmasdi. Endi har holatda `PLATFORM_REPORT`.
- **MEDIUM 3** — kassa vaqti vaqt zonasisiz kelsa butun paket qulardi. Endi vaqt zonasi majburiy, kelajak vaqti `FUTURE` bo'ladi, buzuq qator `ERROR`.
- **MEDIUM 4** — bekor qilingan hisob o'rniga yangisi chiqmasdi. Endi `VOID` e'tiborga olinmaydi (qisman noyob indeks).
- **MEDIUM 5** — platforma panelida foydalanish 0 ko'rinardi (RLS). Endi shop konteksti o'rnatiladi.
- **MEDIUM 6** — hisob chiqqandan keyin tarif almashtirilsa, almashish e'tiborsiz qolardi. Endi eski hisob bekor qilinadi va yangi tarifga qayta chiqadi.
- **MEDIUM 7** — bitta shop xatosi butun billing ishini to'xtatardi. Endi har shop alohida. Hisob raqami Postgres ketma-ketligidan olinadi.
- **MEDIUM 8** — eski shoplar birinchi kunning o'zida "sinov tugadi" holatiga tushardi. Endi sinov obuna ochilgan paytdan boshlanadi.
- **MEDIUM 9** — spec muharriri boshqa shoplar takliflarini yashira va reklamani tasdiqlay olardi. Endi alohida `platform.network.moderate` ruxsati kerak (faqat admin).
- **LOW 10** — reklama bosishlarini sun'iy oshirish mumkin edi. Endi bosish faqat o'sha taklifga tegishli bo'lsa sanaladi.
- **LOW 11** — ikki shop bir vaqtda bir xil (brend, MPN) chiqarsa, javob 500 bo'lardi. Endi savepoint va qayta o'qish.
- **LOW 12** — AI maslahatchiga juda katta narx berilsa 500 bo'lardi. Narx endi chegaralanadi va xarajat har holda yoziladi.
- **LOW 13** — hisobot yordamchisida AI noto'g'ri turdagi javob qaytarsa 500 bo'lardi. Tuzatildi.
- **LOW 14** — SMS xizmati HTML qaytarsa 500 bo'lardi. Tuzatildi. Ro'yxatdan o'tish limiti endi normallashgan telefon bo'yicha hisoblanadi.
- **LOW 15** — Instagram fayllari o'qilgandan keyin cheklanardi. Endi o'qish paytida cheklanadi; ovoz xarajati har holda yoziladi.
- **LOW 16** — matnsiz echo noto'g'ri xabarga mos kelib qolishi mumkin edi; muddati o'tgan taklifga eslatma ketishi mumkin edi. Ikkalasi tuzatildi.
- **Regressiya testlari:** `test_qa_stage23_fixes.py` (4 ta).

**Ataylab qoldirilgan (founder qarori):** ro'yxatdan o'tishda STIR noyob. Kimdir begona STIR bilan ro'yxatdan o'tib, egasini bloklashi mumkin. Hozircha himoya — admin tekshiruvi va soxta shopni yopish. Kerak bo'lsa: STIR faqat ACTIVE shop uchun noyob bo'ladi.

## 4. Lokal sinab bo'lmaganlar (tashqi xizmat kerak)

- **Haqiqiy AI kaliti:** soxta provayderda yordamchi va maslahatchi faqat namuna javob beradi.
- **Telegram va SMS:** haqiqiy global Telegram bot va Eskiz SMS.
- **Meta:** Meta Live, OAuth haqiqiy oynasi, data deletion callback haqiqiy so'rovi.
- **Server:** serverga deploy, domen, zaxira nusxadan tiklash (TC-033).
- **Ko'z bilan tekshiruv:** sahifalarning ko'rinishini inson ko'zi bilan baholash. E2E ishlashni tekshiradi, dizaynni emas.
