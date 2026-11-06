# Global saytda xaridor hisobi va yangi dizayn (2026-11-03)

> **Holat:** qurildi va lokal sinovdan o'tdi, commit qilinmagan — founder ko'rib chiqishi kutilmoqda. Qaror: DEC-156 (PROPOSED).
> **Topshiriq (founder):** "global xaridor saytini login bilan kiradigan qil — tarixlarini saqlab qolish uchun; keyin chiroyli dizayn qil".

---

## 1. Nima qurildi

- **Kirish:**
  - Telefon raqami va SMS kod bilan, parolsiz.
  - Dev muhitida SMS haqiqiy yuborilmaydi, kod ekranda "Test rejimi" bo'lib chiqadi.
- **Saqlanadigan ma'lumot:**
  - ko'rilgan mahsulotlar (200 tagacha);
  - qidiruvlar (100 tagacha);
  - saqlanganlar (saqlagan paytdagi narx bilan, narx tushganini ko'rsatadi);
  - AI maslahatchi suhbati (200 xabargacha).
- **"Mening sahifam"** (`/hisobim`) besh bo'limdan iborat: Saqlanganlar, Ko'rilganlar, Qidiruvlar, AI suhbatlar, Sozlamalar. Sozlamalarda ism, til, chiqish va hisobni butunlay o'chirish bor.
- **Mahsulot sahifasi:** "Saqlash" tugmasi qo'shildi.
- **Xavfsizlik:**
  - Telefon shifrlangan holda saqlanadi.
  - Sessiya cookie'si faqat sayt serverida turadi, brauzerdagi skript uni ko'rmaydi.
  - Begona saytdan kelgan o'zgartirish so'rovi rad etiladi.
  - Tashqi manzilga yo'naltirib bo'lmaydi.
- **Login'siz** sayt avvalgidek ishlaydi va hech narsa saqlamaydi.
- **Maxfiylik siyosati** (uch tilda) yangilandi: nima saqlanadi va qanday o'chiriladi.
- **Dizayn:** to'q fon, indigo-binafsha urg'u, katta qidiruvli bosh qism, natija kartalari, narx solishtirish, messenger ko'rinishidagi AI chat.

Texnik tafsilot: migratsiya `network_0010`, `network/services/buyers.py`, `network/api/buyer_routes.py`, frontendda `apps/marketplace/src/app/api/buyer/*`.

## 2. Sinov natijalari

- **Backend:** 1140 ta testning hammasi o'tdi, 11 tasi yangi. mypy, ruff va import-linter toza.
- **E2E:**
  - To'liq yugurish: 50 ta testdan 49 tasi o'tdi. Yangi xaridor testi yiqildi: test "Saqlash" so'rovi tugashini kutmasdan sahifani yangilagan.
  - Test tuzatildi. Qayta faqat shu test yugurtirildi va o'tdi. 49 tasi to'liq yugurishda o'tgan.
- **Jonli dev server:** kirish, qidiruv, ko'rish, saqlash, tarix va chiqish qo'lda tekshirildi.
- **Telefon (390px):** hech qaysi sahifa yonga siljimaydi.

## 3. Sinalmagan

- Kirgan xaridorning AI suhbati haqiqiy AI kalit bilan sinalmagan; soxta AI'da maslahatchi o'chiq.
- Saqlanganlardagi "narx tushdi" va "sotuvda yo'q" holatlari jonli sinalmagan, chunki dev ma'lumotda narx o'zgarmagan. Backend testlari bu holatlarni qamraydi.
- Haqiqiy Eskiz SMS.

## 4. Dev ma'lumot

Global qidiruvda 3 ta noutbuk ochildi: NoutbukUz'ning ASUS, HP va Lenovo mahsulotlari. Ular oddiy oqim orqali chiqarildi: shop chiqardi, admin bog'lashni tasdiqladi. QA test mahsulotlari qidiruvdan olib tashlandi.
