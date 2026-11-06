# UI concept bo'yicha qayta chizish (2026-11-03)

> **Holat:** qurildi va lokal sinovdan o'tdi, commit qilinmagan — founder ko'rib chiqishi kutilmoqda.
> **Topshiriq (founder):** "UI qismini to'liq almashtir, concept HTML'ga moslab, testni boshqattan o'tkaz".
> **Manba:** loyiha ildizidagi `design-system-concept.html`, `platform-admin-concept.html`, `shop-dashboard-concept.html`, `shop-storefront-concept.html`. Backend `docs/` dagi HTML'lar UI emas: biri savdo oqimi simulyatori, ikkinchisi arxitektura sxemasi. Qaror: DEC-155 (PROPOSED).

---

## 1. Nima o'zgardi

- **Umumiy uslub** (`packages/ui`):
  - Ranglar concept'dan olindi: shop paneli binafsha, platforma paneli ko'k (`<html data-app="admin">`).
  - Shrift Plus Jakarta Sans. Unda kirill harflari yo'q, shuning uchun ruscha matn Inter shriftida chiqadi. Raqamlar JetBrains Mono.
  - Karta, tugma, belgi (badge), jadval, input va sahifa sarlavhasi concept shaklida: yumaloq burchak, qalin sarlavha, mono raqamlar.
- **Platforma paneli:**
  - Qobiq: tepada sarlavha qatori (logo, rol, ⌘K qidiruv, "Shop yaratish", til, avatar). Chapda ikki bo'limli menyu: "Platforma boshqaruvi" va "Sun'iy intellekt va tizim".
  - `/shops`: endi to'liq kenglikdagi jadval. Shop tanlansa, avvalgidek ro'yxat va tafsilot yonma-yon.
  - Bosh sahifa: 7 ta holat ko'rsatkichi va kutilayotgan ishlar concept shaklida.
- **Shop paneli:**
  - Qobiq: tepada shop nomi, holati, "Tez sotuv" tugmasi, bildirishnoma, til va avatar.
  - Chap menyu uch bo'limga ajratildi: "Savdo va mijozlar", "Mahsulotlar va ombor", "AI va do'kon".
  - Bosh sahifa: 4 ta ko'rsatkich (bugungi savdo, tasdiq kutayotganlar, AI suhbatlari, kam qolgan tovar). Ostida 8/4 ustun.
  - Eskirgan "keyingi modullarda paydo bo'ladi" kartasi olib tashlandi.
  - "Tez sotuv" sahifasi kassa ko'rinishida: chapda filial va tovar qidiruvi, o'ngda joriy chek, yashil jami va "Sotish" tugmasi.
- **Xaridor sayti:**
  - Concept tuzilishi: aloqa qatori, shaffof yopishqoq sarlavha, logo plitkasi, katta kirish bloki (hero), mahsulot kartalari va footer.
  - Rang va yorug'/to'q rejim avvalgidek shop tanlovi. To'q rejim concept ranglarida.
- **Marketplace:** concept'i yo'q. Umumiy shrift va komponentlar orqali yangilandi.

## 2. Ataylab ko'chirilmagan (soxta ma'lumot)

- **Platforma:** GMV, DB latency, Redis navbati, LLM reytingi, tarif ustuni.
- **Shop paneli:** "Bugungi tushum +18%" taqqoslash, "AI maslahati" matni.
- **Sayt:** "rasmiy kafolat", "12 oylik muddatli to'lov", "2 soatda yetkazish" va'dalari (shop sozlamasida yo'q). Manzil ham ko'chirilmadi: sayt sozlamasida bunday maydon yo'q.

## 3. Sinov natijalari

- **E2E (Playwright, alohida muhit):** 49 ta test, hammasi birinchi yugurishda o'tdi (5 daqiqa).
- **Statik tekshiruvlar:** typecheck (4 ilova va 5 paket) va eslint toza.
- **Ko'z bilan tekshiruv (skrinshot):**
  - kompyuter (1440px): shop panelining 11 ta sahifasi, platforma panelining 4 ta sahifasi, sayt;
  - telefon (390px): shop bosh sahifasi, "Tez sotuv", buyurtmalar, `/shops`, sayt. Hech qayerda gorizontal siljish yo'q.
- **Backend o'zgarmadi**, shuning uchun backend testlari qayta yugurtirilmadi.

## 4. Founder ko'rishi kerak

- Sahifalarni o'zi ochib ko'rishi: ranglar, o'lchamlar, menyu tartibi.
- Saytning standart rejimi. Hozir yangi shopda yorug' rejim, concept esa to'q. Kerak bo'lsa standartni to'q qilish mumkin.
