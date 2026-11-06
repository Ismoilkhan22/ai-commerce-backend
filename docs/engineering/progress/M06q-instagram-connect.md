# Instagram — haqiqiy ulanish, "Instagram bilan ulash", Meta talablari

> **Holat:** lokal sinovdan o'tdi (2026-10-30: haqiqiy DM tunnel orqali keldi), commit qilinmagan — founder ko'rib chiqishi kutilmoqda.
> **Asos:** DEC-116, DEC-132, DEC-148, yangi — DEC-150 (taklif).

---

## 1. Nima isbotlandi

```
Instagram'da xabar ──▶ Meta webhook ──▶ Cloudflare tunnel ──▶ imzo tekshiruvi ──▶ suhbat ──▶ AI javobi ──▶ Instagram API ──▶ xaridorga
```

- **Sinov akkauntlari:** @ismoilkhan22 akkaunti "AI Commerce Test" Page'iga ulandi. Tester akkauntdan yozilgan xabar panelga keldi, javob Instagram'ga qaytdi.
- **Soxta AI:** o'sha paytda `LLM_PROVIDER=fake` edi, shuning uchun javob qolip matni bo'ldi.

## 2. Ulash yo'li (texnik)

- **Graph API:** `graph.facebook.com/v23.0` (v19 dan ko'tarildi).
- **Qanday token qabul qilinadi:**
  - Page tokeni yoki foydalanuvchi tokeni qabul qilinadi. Foydalanuvchi tokenidan `/me/accounts` orqali Page tokeni va `instagram_business_account` topiladi.
  - Qisqa token uzun muddatliga (taxminan 60 kun) almashtiriladi.
  - Shundan keyin Page `subscribed_apps` ga obuna qilinadi.
- **Xato bo'lganda:** Meta xatolari logga kod va matni bilan yoziladi, token yozilmaydi.

## 3. "Instagram bilan ulash" tugmasi (OAuth)

```
Panel ──▶ POST /shop/channels/instagram/oauth ──▶ Facebook oynasi (Page va Instagram tanlanadi)
  ──▶ GET /webhooks/instagram/oauth?code&state ──▶ kod → token → 60 kunlik → odatdagi ulash
  ──▶ panelga qaytish (?instagram=connected | error&reason=…)
```

- **`state` himoyasi:** HMAC bilan imzolangan, 10 daqiqa amal qiladi. Shop, xodim va qaytish yo'li imzodan olinadi, begona saytga yo'naltirib bo'lmaydi.
- **Qo'lda token:** panelda "ilg'or" bo'limida qoladi.
- **Sozlamalar:** `INSTAGRAM_APP_ID`, `INSTAGRAM_APP_SECRET`, `MESSAGING_WEBHOOK_BASE_URL`, ixtiyoriy `INSTAGRAM_OAUTH_CONFIG_ID` (Facebook Login for Business konfiguratsiyasi).
- **Meta'da:** Valid OAuth Redirect URIs ga `<domen>/api/v1/webhooks/instagram/oauth` qo'shiladi.

## 4. Instagram ilovasidan yozilgan javob (echo)

- **Kim yozgan bo'lsa:** do'kon xodimi telefonda, Instagram ilovasidan javob yozsa, u suhbatga xodim xabari bo'lib yoziladi.
- **Bizning yuborgan xabar:** uning echo'si (AI yoki panel) qaytarib yozilmaydi.

## 5. Meta ma'lumot o'chirish va app'ni o'chirish callback'lari

- **Manzillar:**
  - `POST /api/v1/webhooks/instagram/data-deletion` — Meta "Data deletion request URL";
  - `POST /api/v1/webhooks/instagram/deauthorize` — "Deauthorize callback URL";
  - `GET /api/v1/webhooks/instagram/data-deletion/{code}` — holat sahifasi.
- **Nima bo'ladi:**
  - Meta `signed_request` app siri bilan tekshiriladi.
  - Shu Facebook foydalanuvchisi OAuth bilan ulagan Instagram akkauntlari uziladi (`AUTH_REVOKED`) va token o'chiriladi.
  - Javobda holat sahifasi manzili va tasdiq kodi qaytadi.
- **Shop noma'lum:** RLS'ga `app.meta_user_ref` varianti qo'shilgan (migratsiya `messaging_0005`).
- **Qo'lda token bilan ulanganlar:** ularda Facebook ID yo'q, shuning uchun callback ularga tegmaydi. Token muddati tugaganda sog'liq tekshiruvi kanalni "nosoz" qiladi.

## 6. Live uchun qolgan ishlar (founder bilan)

- **Server:** VPS va doimiy domen. trycloudflare manzili har ishga tushganda o'zgaradi va Meta uni qabul qilmaydi.
- **Sahifalar:** Privacy Policy va Terms sahifalari, ularning ichida yuridik shaxs va aloqa ma'lumotlari.
- **Meta tekshiruvlari:** Business verification va App Review (har ruxsat uchun izoh va video).

## 7. Tekshiruv

- **Testlar:**
  - `tests/unit/test_instagram_http_account.py` (12 ta);
  - `test_instagram_comments.py` ichida OAuth, echo va data deletion (5 ta);
  - messaging va unit to'plami: 614 ta o'tdi.
- **Statik tekshiruvlar:** mypy, ruff, import-linter toza.
