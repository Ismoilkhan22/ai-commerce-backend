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
