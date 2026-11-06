# Ma'lumotlar bazasi loyihasi (DBML)

Har domen jadvallari shu papkada, [DBML](https://dbml.dbdiagram.io/docs/) formatida. Bu — bazaning **yagona loyihasi**: kod va migratsiyalar shundan keyin yoziladi.

## Ko'rish

1. [dbdiagram.io](https://dbdiagram.io) → **Create your diagram** (ro'yxatdan o'tish shart emas; saqlash va ulashish uchun bepul akkaunt).
2. Chap tomondagi namuna matnni o'chirib, kerakli `.dbml` faylni to'liq nusxalab qo'ying (`pbcopy < docs/engineering/db/platform.dbml`).
3. O'ngda diagramma chiqadi: jadvallarni sudrab joylashtirish mumkin, maydon ustiga borsangiz izohi ko'rinadi.

## Ish tartibi

1. Domen jadvallari shu yerda loyihalanadi → founder ko'rib chiqadi → tasdiqlanadi (holat faylning boshida).
2. Shundan keyin migratsiya va ORM modellari yoziladi; ular DBML bilan mos bo'lishi shart.
3. O'zgarish kerak bo'lsa — avval DBML, keyin kod.

## Fayllar

| Fayl | Domen | Holat |
|---|---|---|
| `platform.dbml` + [`platform.md`](platform.md) (har jadval va maydon izohi) | Shop, filiallar, foydalanuvchilar, rollar, sessiyalar | ✅ Tasdiqlangan (DEC-131), kodda — 1-modul |
| `catalog.dbml` + [`catalog.md`](catalog.md) | Toifalar, mahsulot va SKU, narx va kurs, texnik kutubxona, fayllar | ✅ Tasdiqlangan (DEC-133) — 2-modul |
| `commerce.dbml` + [`commerce.md`](commerce.md) | Ombor (qoldiq, daftar, kirim, tuzatish), tez sotuv, buyurtmalar, band qilish, saytdan buyurtma so'rovi | ✅ Tasdiqlangan (DEC-134) — 3-modul |
| `storefront.dbml` + [`storefront.md`](storefront.md) | Shop sayti: sozlamalar (logotip, rang, kontaktlar, ochiq/yopiq), ma'lumot sahifalari; keyin — katalog nusxasi va o'z domeni | ✅ Tasdiqlangan (DEC-135) — 4-modul |
| `messaging.dbml` + [`messaging.md`](messaging.md) | Kanallar (Telegram, Instagram, sayt chati), xaridorlar, suhbatlar, xabarlar, biriktirmalar, operatorga uzatish, sayt chati sessiyalari | Taklif — qarorlar qabul qilingan, founder ko‘rib chiqishi kutilmoqda; 5b da qurilgan (`messaging_0002`) |
| `jobs.dbml` + [`jobs.md`](jobs.md) | Fon ishlari: outbox va event qabul qilish (har schemada), dead-letter, rejali ishlar jurnali | Taklif — qarorlar qabul qilingan, founder ko'rib chiqishi kutilmoqda (5-modul) |
| `notifications.dbml` + [`notifications.md`](notifications.md) | Xabarnomalar, xodim vazifalari, shop matnlari, xodimning platforma botiga ulanishi | Taklif — qarorlar qabul qilingan, founder ko'rib chiqishi kutilmoqda (5-modul) |
| `catalog_import.dbml` + [`catalog_import.md`](catalog_import.md) | Katalog importi (CSV/XLSX) — catalog'ga qo'shimcha jadvallar va commerce qoldiq natijasi | Taklif — qarorlar qabul qilingan, founder ko'rib chiqishi kutilmoqda (5-modul) |
| `commerce_quotes.dbml` + [`commerce_quotes.md`](commerce_quotes.md) | Leadlar (FSM-05), PC takliflari (FSM-06): versiyalar, qatorlar, muzlagan moslik natijasi; qabuldan DRAFT buyurtma — commerce'ga qo'shimcha | Taklif — qarorlar qabul qilingan, founder ko'rib chiqishi kutilmoqda (6-modul) |
| `sales_ai.dbml` + [`sales_ai.md`](sales_ai.md) | AI sotuvchi: sozlamalar, profil va FAQ, suhbat holati, AI navbatlari va tool jurnali, operator bahosi, baholash; `platform/llm` (redaction xaritasi, xarajat). PC moslik qoidalari — kodda, jadvalsiz ([../ai/M06-architecture.md](../ai/M06-architecture.md)) | Taklif — qarorlar qabul qilingan, founder ko'rib chiqishi kutilmoqda (6-modul) |
| `support.dbml` + [`support.md`](support.md) | Kafolat va qaytarish murojaatlari (FSM-11): buyurtma, tez sotuv yoki tashqi sotuvdan; karantin commerce daftari orqali; murojaat xabarlari va qolgan xaridor xabarnomalari bo'shliqlari | Taklif — qarorlar qabul qilingan, founder ko'rib chiqishi kutilmoqda (7-modul) |
| `reporting.dbml` + [`reporting.md`](reporting.md) | Hisobot read model'lari: sotuv, tez sotuv, operator javob vaqti va uzatishlar, ombor qiymati (kunlik), AI xarajati, foyda, kafolat, izohlar kayfiyati — shaxsiy ma'lumotsiz | Taklif — qarorlar qabul qilingan, founder ko'rib chiqishi kutilmoqda (7-modul) |
| `commerce_cost_price.dbml` + [`commerce_cost_price.md`](commerce_cost_price.md) | Tannarx: kirim qatori narxi, o'rtacha tortilgan tannarx, sotuv qatoridagi nusxa — commerce'ga qo'shimcha | Taklif — qarorlar qabul qilingan, founder ko'rib chiqishi kutilmoqda (7-modul) |
| `instagram_comments.dbml` + [`instagram_comments.md`](instagram_comments.md) | Instagram izohlari (DEC-132): postlar va mahsulot bog'lash, izohlar, «+» va narx so'roviga Direct javobi, kayfiyat — messaging'ga qo'shimcha | Taklif — qarorlar qabul qilingan, founder ko'rib chiqishi kutilmoqda (6+ modul) |
