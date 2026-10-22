# Atamalar lug'ati (Glossary)

**Maqsad:** hujjatlar, kod va suhbatlarda bitta narsa bitta nom bilan atalsin. Kodda inglizcha nom (o'ng ustun) ishlatiladi; o'zbekcha matnda chap ustundagi atama.
**Manba:** `engineering/03` §2 (ubiquitous language), K-01…K-10 (`decisions/DECISION_REGISTER.md`).

## Biznes atamalari

| O'zbekcha | Kodda | Ma'nosi |
|---|---|---|
| Do'kon, merchant | `merchant` | Platformadan foydalanuvchi mustaqil do'kon (tenant). Identifikatori — `merchant_id` (K-01) |
| Filial | `branch` | Do'konning jismoniy joyi; stok filial bo'yicha yuritiladi |
| Xodim, a'zolik | `principal`, `membership` | Tizimga kiruvchi odam va uning do'kondagi roli |
| Ega | `OWNER` | Do'kon egasi, barcha huquqlar |
| Menejer | `MANAGER` | Tasdiqlash huquqi bor (quote, buyurtma, bekor qilish) |
| Operator, sotuvchi | `SALES` | Xaridor bilan gaplashadi, o'ziga biriktirilgan buyurtmani tasdiqlaydi (DEC-108) |
| Omborchi | `WAREHOUSE` | Kirim, tuzatish, "tez sotuv" |
| Xaridor, mijoz | `customer`, `buyer` | Do'kondan sotib oluvchi |
| Mahsulot | `merchant_product` | Do'kon katalogidagi mahsulot kartochkasi |
| SKU, variant | `sku` | Sotiladigan aniq variant (model + xotira + holat). Do'kon ichida `sku_code` noyob |
| Reference spec | `reference_hardware_spec` | Platforma yuritadigan komponent texnik xususiyatlari (DEC-011) |
| Canonical product | `canonical_product` | Stage 2: bir xil model uchun global identifikator |
| Public offer | `public_offer` | Stage 2: do'kon roziligi bilan ommaga chiqarilgan taklif |
| Narx versiyasi | `price_version` | Narxning har o'zgarishi alohida versiya |
| Kurs | `exchange_rate` | USD → UZS kursi, manba va vaqti bilan (DEC-121) |
| Qoldiq | `on_hand` | Ombordagi jismoniy soni (K-04) |
| Band qilingan | `reserved` | Tasdiqlangan buyurtma uchun ajratilgan, hali tayyorlanmagan |
| Ajratilgan | `allocated` | Tayyorlanayotgan / jo'natilayotgan buyurtma uchun |
| Sotuvga mavjud | `available` | `on_hand − reserved − allocated` |
| Rezerv | `stock_reservation` | Buyurtma uchun stokni band qilish yozuvi (FSM-07) |
| Tez sotuv | `offline_quick_sale` | Do'kondagi oddiy sotuvni stokdan chiqarish (DEC-123) |
| Lead | `lead` | Sotuv imkoniyati (qiziqqan xaridor) |
| Taklif (narxli taklif) | `quote` | PC yig'ma uchun rasmiy taklif: narx snapshot, muddat, moslik natijasi (DEC-100e) |
| Buyurtma, zakaz | `order` | Xaridor olmoqchi bo'lgan narsa; FSM-08 |
| Buyurtma qoralamasi | `order` + `DRAFT` | AI yoki sayt yaratgan, hali odam ko'rmagan buyurtma |
| Tasdiqlash | `confirm` | Sotuvchi mahsulot borligini tasdiqlashi; stok band qilinadi |
| Topshirildi | `COMPLETED` | Xaridorga berildi; stok kamayadi |
| "To'landi" belgisi | `paid_mark` | Do'kon qo'yadigan, tizim tekshirmagan belgi (DEC-100a) |
| Olib ketish / yetkazish | `PICKUP` / `DELIVERY` | `fulfillment_method` |
| Kafolat murojaati | `support_case` | Nosozlik, qaytarish (DEC-114) |
| Operatorga uzatish | `handoff` | Suhbatni AI'dan odamga o'tkazish |
| Gapirish huquqi | `speaker_mode`, `speaker_version` | Suhbatda hozir kim javob bera oladi: AI yoki operator |
| Moslik tekshiruvi | `compatibility_check` | PC qismlarining mosligi: `PASS` / `REVIEW_REQUIRED` / `BLOCK` (K-09) |
| Merchant siyosati | `merchant_policy` | Do'kon sozlamalari: quote muddati, chegirma limiti, eslatma vaqtlari |

## Texnik atamalar

| Atama | Ma'nosi |
|---|---|
| Tenant | Bitta do'kon va uning barcha ma'lumotlari; boshqa tenant'ni ko'rmaydi |
| Bounded context (`Cxx`) | Kodning mustaqil biznes qismi (masalan, `orders`, `inventory`); `engineering/03` §4 |
| Workflow | Bir nechta context'ni bitta tranzaksiyada boshqaradigan use case (ADR-021) |
| UoW (Unit of Work) | Bitta DB tranzaksiyasi chegarasi |
| Outbox | Biznes o'zgarishi bilan bitta tranzaksiyada yoziladigan "keyin yuborilsin" yozuvi |
| Job | Fonda bajariladigan vazifa (PG leased jobs, ADR-005) |
| Idempotency | Bir xil so'rov takrorlansa, natija bir marta bajariladi (`Idempotency-Key`, K-06) |
| FSM | Holatlar mashinasi: qaysi status qaysiga o'tishi mumkin (`business/05`) |
| RLS | PostgreSQL row level security — DB darajasidagi tenant himoyasi (ADR-026) |
| ActorContext | So'rov kim nomidan, qaysi do'kon uchun bajarilayotgani (server tomonida aniqlanadi) |
| Surface | API guruhi: `merchant`, `storefront`, `webhooks`, `platform` (ADR-024) |
| Tool | AI chaqira oladigan backend funksiyasi (`catalog.search` va h.k., K-10) |
| Tool broker | AI tool chaqiruvlarini tekshiradigan va bajaradigan qatlam |
| Redaction | Shaxsiy ma'lumotni `[PHONE_1]` kabi tokenga almashtirish |
| Golden set | AI yoki qoidalarni tekshirish uchun to'g'ri javobi ma'lum misollar to'plami |
| Bake-off | Bir nechta provayderni bir xil test to'plamida solishtirish |
| Slice (S0–S5) | Ishlab chiqish bosqichi; Stage 2/3 — `N1`/`G1` (DEC-005) |
| Stage 1/2/3 | Tijoriy bosqichlar: Merchant Sales OS / Merchant Network / Global AI Shopping |
| `DEFERRED` | Keyingi bosqichga qoldirilgan (masalan, to'lov moduli — DEC-100) |
