# 15 — Platforma paneli (platforma jamoasi uchun)

**Holat:** A bosqich to'liq qurildi (2026-10-24), ichki izoh va jamoa boshqaruvi bilan. Founder qarorlari: yordam roli faqat ko'radi, pilot tugashi — faqat ogohlantirish. Savollar 2 va 3 — tavsiya bo'yicha (izoh kerak, yopishda nom yoziladi).
**Kim uchun:** founder, platforma jamoasi, dasturchilar.
**Bog'liq qarorlar:** DEC-122 (shopni platforma qo'lda faollashtiradi), DEC-119 (30 kunlik pilot), DEC-120 (texnik kutubxona), DEC-131 (rollar).

## Bu hujjat nima uchun

Biznes hujjatlarda (`02`, `06`) shop paneli va shop sayti batafsil yozilgan. Platforma jamoasi esa faqat "shopni faollashtiradi" degan joylarda tilga olinadi. Bu hujjat o'sha bo'shliqni to'ldiradi: platforma paneli nimani ko'rsatadi va jamoa unda nima qila oladi.

---

## Kim ishlatadi

Platforma jamoasi — biz. Uchta rol bor:

- **Platforma admini (`PLATFORM_ADMIN`)** — hamma narsa: shop yaratish, faollashtirish, to'xtatish, yopish, jamoani boshqarish.
- **Yordam (`PLATFORM_SUPPORT`)** — shoplarni ko'radi va shop egalariga yordam beradi. Holatni o'zgartira olmaydi.
- **Kutubxona muharriri (`SPEC_EDITOR`)** — faqat PC texnik ma'lumotlar kutubxonasi (2-modulda).

**Asosiy cheklov:** platforma jamoasi shopning ichki savdo ma'lumotini ko'rmaydi: suhbatlar, xaridorlar, buyurtma tafsilotlari. Ko'radigani — holat, sanoqlar va xatolar (engineering/10 §9). Shop murojaat qilsa, egasining ruxsati bilan vaqtinchalik kirish beriladi. Bu keyingi bosqichda qo'shiladi.

---

## A bosqich — hozir (shoplarni boshqarish va kuzatish)

Bu bosqich 1-modul ustiga quriladi. Unda faqat hozir ma'lumoti bor narsalar bo'ladi.

### 1. Bosh sahifa

Panelga kirganda jamoa birinchi navbatda nima qilish kerakligini ko'radi:

- **Shoplar soni holat bo'yicha:** qoralama, tekshiruvda, faol, to'xtatilgan, yopilgan. Har biri bosilsa, ro'yxat shu holat bo'yicha filtrlanadi.
- **"Tekshiruv kutmoqda" navbati:** eng eskisi birinchi, necha kundan beri kutayotgani ko'rinadi. "Faollashtirish" tugmasi shu yerning o'zida.
- **"Ega hali kirmagan" shoplar:** taklif muddati o'tgan yoki tugashiga oz qolgan. "Taklifni qayta berish" tugmasi shu yerda.
- **Pilot muddati:** faol shopning faollashtirilganiga necha kun bo'lgani (30 kunlik pilot). Tugashiga 7 kundan kam qolganlari ajratib ko'rsatiladi.
- **Yangi shoplar:** oxirgi 7 va 30 kun.
- **Oxirgi faoliyat:** jamoaning so'nggi 10 ta amali.

### 2. Shoplar ro'yxati

- **Qidiruv:** nomi, sayt manzili (slug), STIR yoki ega telefoni bo'yicha.
- **Filtr:** holat. **Saralash:** yaratilgan va faollashtirilgan sana bo'yicha.
- **Har qatorda:** nomi, sayt manzili, holat, ega ismi, xodimlar soni, filiallar soni, yaratilgan sana, oxirgi faollik (shopdan kimdir oxirgi marta qachon kirgan).
- Ro'yxat sahifalarga bo'linadi.

### 3. Shop yaratish va tahrirlash

- **Yaratish (bor):** nom, sayt manzili, STIR, yuridik nom, til, ega telefoni va ismi → ega uchun taklif havolasi.
- **Tahrirlash (yangi):** platforma nom, yuridik nom, STIR va tilni tuzata oladi. Sabab majburiy, o'zgarish jurnalga yoziladi. Sayt manzili o'zgarmaydi: u saytning manzili va havolalar buzilmasligi kerak.
- **Ichki izoh (yangi):** faqat jamoa ko'radigan qayd, masalan "kelishuv imzolangan 20.10", "aloqa uchun: Vali, operator". Shop uni ko'rmaydi.

### 4. Shop kartochkasi

Bitta shop haqida hamma narsa bo'limlarga bo'linadi:

- **Umumiy:** holat, sanalar, pilot kunlari va ishga tushirish qadamlari (`13`):
  ```
  ega kirdi ──▶ filial qo'shildi ──▶ xodimlar qo'shildi ──▶ tekshiruvga yuborildi ──▶ faollashtirildi
  ```
  Har qadam bajarilgan yoki bajarilmagani belgilanadi. Keyingi modullarda katalog, kanallar va AI qadamlari qo'shiladi.
- **Egalar va xodimlar:** ism, telefon, rol, holat, oxirgi kirish vaqti. Ega uchun: taklifni qayta berish, parol tiklash havolasi. Oddiy xodimlarni platforma faqat ko'radi: ularni ega boshqaradi.
- **Filiallar:** ro'yxat, faqat ko'rish uchun.
- **Holat tarixi:** kim, qachon, qaysi holatdan qaysiga va nega o'zgartirgan.
- **O'zgarishlar jurnali:** shopda kim nima qilgani (xodim qo'shdi, sozlama o'zgartirdi). Shaxsiy ma'lumot ko'rsatilmaydi.
- **Amallar (bor):** faollashtirish, to'xtatish, qayta yoqish, yopish. To'xtatish va yopishda sabab majburiy. Yopish qaytarib bo'lmaydigan amal, shuning uchun shop nomini qayta yozib tasdiqlanadi.

### 5. Platforma jamoasi

Hozir yangi admin faqat dasturchi buyrug'i (CLI) bilan qo'shiladi. Panelda:

- **Ro'yxat:** ism, telefon, rol, holat, oxirgi kirish.
- **Yangi a'zo:** taklif havolasi orqali, xuddi shop xodimi kabi.
- **Rolni o'zgartirish va o'chirish.** O'zini ham, oxirgi adminni ham o'chirib bo'lmaydi.
- Bu bo'limni faqat platforma admini ko'radi.

### 6. Faoliyat jurnali

- Jamoaning hamma amallari: kim, qachon, qaysi shop, nima qildi, nega.
- **Filtr:** shop, jamoa a'zosi, amal turi, sana.

### 7. Mening profilim (bor)

Parolni o'zgartirish, faol qurilmalar, hamma joydan chiqish.

---

## Qoidalar

- Platforma qiladigan har bir amal jurnalga yoziladi. Holat o'zgarishi va tahrir uchun sabab majburiy.
- Platforma shopning savdo ma'lumotini ko'rmaydi (yuqoridagi asosiy cheklov).
- Yordam roli holatni o'zgartira olmaydi va jamoani boshqara olmaydi. Tugmalar unga ko'rinmaydi, to'g'ridan so'rov yuborsa ham rad etiladi.
- Platforma shop xodimini o'chirmaydi va rolini o'zgartirmaydi. Bu egasining ishi. Istisno — egaga parol tiklash havolasi.

## Keyingi bosqichlarda (har modul bilan) qo'shiladi

- **2-modul, katalog:** texnik ma'lumotlar kutubxonasi (kiritish, ikkinchi odam tasdig'i), shoplardan kelgan "yangi model" so'rovlari navbati, toifalar.
- **3-modul, savdo:** shop bo'yicha buyurtmalar soni (faqat sanoq, tafsilotsiz).
- **5-modul, kanallar:** har shopda Telegram/Instagram holati, chiquvchi xabarlarni to'xtatish tugmasi.
- **6-modul, AI:** hamma shoplarda AI'ni bir tugma bilan o'chirish, shop AI rejimi, AI xarajati, qoidalar va prompt versiyasini orqaga qaytarish.
- **7-modul:** tarif va limitlar, pilot hisoboti (`14`), egasi ruxsati bilan vaqtinchalik kirish (break-glass).

## Qabul mezonlari (A bosqich)

- Admin bosh sahifada tekshiruv kutayotgan shopni ko'radi va ikki bosishda faollashtiradi.
- Ega telefoni bo'yicha qidirsa, shop topiladi.
- Shop kartochkasida ishga tushirish qadamlari to'g'ri belgilanadi.
- Yordam roli shopni faollashtira olmaydi: tugma ko'rinmaydi, API 403 qaytaradi.
- Jamoaga yangi a'zo panel orqali, havola bilan qo'shiladi.
- Holat tarixi va jurnal har bir amalni sababi bilan ko'rsatadi.
- Platforma shop xodimini o'chira olmaydi.

## Founder uchun savollar

1. Yordam roli ega havolasini qayta bera oladimi yoki faqat ko'radimi?
2. Ichki izoh kerakmi?
3. Shopni yopishda nomni qayta yozib tasdiqlash kerakmi?
4. Pilotning 30 kuni tugaganda nima bo'ladi: faqat ogohlantirishmi yoki biror amal ham (masalan, tarifga o'tish taklifi)?
