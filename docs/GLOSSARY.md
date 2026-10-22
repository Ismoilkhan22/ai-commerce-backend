# Atamalar lug'ati

**Versiya:** v2 (2026-10-22).

**Maqsad:** hujjatlarda, kodda va suhbatlarda bitta narsa bitta nom bilan atalsin. O'zbekcha matnda chap ustundagi so'z, kodda o'rta ustundagi inglizcha nom ishlatiladi.

**Muhim (DEC-124):** platformadan foydalanadigan do'kon hamma joyda **shop** deb ataladi (ilgari "merchant" edi). Kodda: `shop`, `shop_id`. Engineering hujjatlari va kod shu nomga engineering bosqichida o'tkaziladi. Boshqa nomlar o'zgarsa, alohida savol bilan hal qilinadi va shu yerda yangilanadi.

## Biznes atamalari

| O'zbekcha | Kodda | Ma'nosi |
|---|---|---|
| Shop | `shop` | Platformadan foydalanadigan mustaqil do'kon. Har bir ma'lumot qaysi shopga tegishli ekani `shop_id` bilan belgilanadi (K-01) |
| Filial | `branch` | Shopning jismoniy joyi. Qoldiq filial bo'yicha yuritiladi |
| Xodim, a'zolik | `principal`, `membership` | Tizimga kiradigan odam va uning shopdagi roli |
| Ega | `OWNER` | Shop egasi, hamma huquqlar |
| Menejer | `MANAGER` | Tasdiqlaydi: PC takliflari, buyurtmalar, bekor qilish |
| Operator | `SALES` | Xaridor bilan gaplashadi, o'ziga biriktirilgan buyurtmani tasdiqlaydi (DEC-108) |
| Omborchi | `WAREHOUSE` | Kirim, tuzatish, "tez sotuv" |
| Xaridor | `customer` | Shopdan sotib oladigan odam |
| Mahsulot | `shop_product` | Shop katalogidagi mahsulot kartochkasi |
| Variant (SKU) | `sku` | Sotiladigan aniq variant: model + xotira + holat. Shop ichida `sku_code` takrorlanmaydi |
| Texnik ma'lumotlar kutubxonasi | `reference_hardware_spec` | Platforma yuritadigan PC qismlari texnik xususiyatlari (DEC-011) |
| Umumiy mahsulot | `canonical_product` | Stage 2: bir xil model uchun hamma shoplarga umumiy yozuv |
| Ommaviy taklif | `public_offer` | Stage 2: shop roziligi bilan hammaga ko'rinadigan taklif |
| Narx versiyasi | `price_version` | Narxning har bir o'zgarishi alohida saqlanadi |
| Kurs | `exchange_rate` | Dollar → so'm kursi, manbasi va vaqti bilan (DEC-121) |
| Qoldiq | `on_hand` | Omborda jismonan bor soni (K-04) |
| Band qilingan | `reserved` | Tasdiqlangan buyurtma uchun ajratilgan, hali tayyorlanmagan |
| Tayyorlanayotgan | `allocated` | Tayyorlanayotgan buyurtma uchun ajratilgan |
| Sotuvga mavjud | `available` | `on_hand − reserved − allocated` |
| Band qilish yozuvi | `stock_reservation` | Buyurtma uchun mahsulotni band qilish (FSM-07) |
| Tez sotuv | `offline_quick_sale` | Do'kondagi oddiy sotuvni qoldiqdan chiqarish (DEC-123) |
| Lead | `lead` | Sotuv imkoniyati — qiziqqan xaridor |
| PC taklifi | `quote` | PC yig'ma uchun rasmiy taklif: belgilangan narx, amal qilish muddati, moslik natijasi (DEC-100e) |
| Buyurtma | `order` | Xaridor olmoqchi bo'lgan narsa (FSM-08) |
| Buyurtma qoralamasi | `order` + `DRAFT` | AI yoki sayt yaratgan, hali xodim ko'rmagan buyurtma |
| Tasdiqlash | `confirm` | Xodim mahsulot borligini tasdiqlaydi; mahsulot band qilinadi |
| Topshirildi | `COMPLETED` | Xaridorga berildi; qoldiq kamayadi |
| "To'landi" belgisi | `paid_mark` | Shop qo'yadigan, tizim tekshirmaydigan belgi (DEC-100a) |
| Olib ketish / yetkazish | `PICKUP` / `DELIVERY` | Buyurtma qanday beriladi (`fulfillment_method`) |
| Kafolat murojaati | `support_case` | Nosozlik yoki qaytarish (DEC-114) |
| Operatorga uzatish | `handoff` | Suhbatni AI'dan odamga o'tkazish |
| Kim javob beradi | `speaker_mode`, `speaker_version` | Suhbatda hozir kim javob bera oladi: AI yoki operator |
| Moslik tekshiruvi | `compatibility_check` | PC qismlari mosligi: `PASS` (mos) / `REVIEW_REQUIRED` (tekshirish kerak) / `BLOCK` (mos emas) (K-09) |
| Shop sozlamalari | `shop_policy` | Taklif muddati, chegirma limitlari, eslatma vaqtlari |

## Texnik atamalar

| Atama | Ma'nosi |
|---|---|
| Tenant | Bitta shop va uning barcha ma'lumotlari. Bir tenant boshqasini ko'rmaydi |
| Bounded context (`Cxx`) | Kodning mustaqil biznes qismi (masalan, `orders`, `inventory`) — `engineering/03` §4 |
| Workflow | Bir nechta context'ni bitta tranzaksiyada boshqaradigan amal (ADR-021) |
| UoW (Unit of Work) | Bitta ma'lumotlar bazasi tranzaksiyasi chegarasi |
| Outbox | Biznes o'zgarishi bilan birga yoziladigan "keyin yuborilsin" yozuvi — xabar yo'qolmasligi uchun |
| Job | Fonda bajariladigan vazifa (ADR-005) |
| Idempotency | Bir xil so'rov takrorlansa ham natija bir marta bajariladi (`Idempotency-Key`, K-06) |
| FSM | Holatlar ketma-ketligi: qaysi holatdan qaysiga o'tish mumkin (`business/05`) |
| RLS | Ma'lumotlar bazasi darajasida shoplarni bir-biridan ajratish (ADR-026) |
| ActorContext | So'rov kim nomidan va qaysi shop uchun bajarilayotgani (server aniqlaydi) |
| Surface | API guruhi: `shop`, `storefront`, `webhooks`, `platform` (ADR-024) |
| Tool | AI chaqira oladigan backend funksiyasi (`catalog.search` va h.k., K-10) |
| Tool broker | AI chaqiruvlarini tekshirib, bajaradigan qatlam |
| Redaction | Shaxsiy ma'lumotni `[PHONE_1]` kabi belgiga almashtirish |
| Golden set | To'g'ri javobi oldindan ma'lum bo'lgan sinov misollari to'plami |
| Bake-off | Bir nechta AI provayderini bir xil sinovlarda solishtirish |
| Slice (S0–S5) | Ishlab chiqish bo'lagi; Stage 2 — `N1`, Stage 3 — `G1` (DEC-005) |
| Stage 1/2/3 | Bosqichlar: shop uchun savdo tizimi / shoplar tarmog'i / global AI qidiruv |
| `DEFERRED` | Keyingi bosqichga qoldirilgan (masalan, to'lov moduli — DEC-100) |
