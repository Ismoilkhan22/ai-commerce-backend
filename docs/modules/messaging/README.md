# messaging

**Qatlam:** domain · **Schema:** `messaging` · **Slice:** S2 · **Egasi:** ___
**Biznes modullar:** M09, M10 (keyin M39 adapteri) · **Qoidalar:** BL-031…033 (kanallar), BL-034…037 (inbox, handoff); BR-X04, BR-X05 · **Holatlar:** FSM-03, FSM-04 (`../../business/05`)

## 1. Nima qiladi

Telegram, Instagram va saytdagi chatni ulaydi; kiruvchi xabarlarni takrorsiz saqlaydi; bitta inbox; suhbatda hozir kim javob berishini (`speaker_mode`, `speaker_version`) boshqaradi; AI javobi va xodim javobini yuboradi; xaridorga bildirishnomalarni shop kanali orqali yetkazadi.

Nima qilmaydi: AI javobini tuzmaydi (`sales_ai`), buyurtma yaratmaydi (`commerce`). Webhook ichida AI kutilmaydi — avval saqlanadi va 200 qaytariladi.

## 2. Sub-modullar

| Sub-modul | Vazifasi | Asosiy jadvallar |
|---|---|---|
| `channels` | Kanal ulanishlari, adapterlar (`telegram`, `instagram`, `webchat`), webhook va dedup | `channel_accounts`, `provider_events` |
| `conversations` | Xaridor identifikatori, suhbatlar, xabarlar, handoff, qisqa xulosa | `customer_identities`, `conversations`, `messages`, `handoffs` (AI xulosasi — `sales_ai.conversation_summaries`) |

Batafsil — [07](../../engineering/07-data-layer.md) §4.5, kanallar — [13](../../engineering/13-integrations-and-channels.md).

## 3. Holatlar

```
Kanal (FSM-03): PENDING ──(ega ruxsat berdi, sinov xabari o'tdi)──▶ CONNECTED ──(xatolar, token muddati)──▶ DEGRADED ──(qayta ulandi)──▶ CONNECTED
               CONNECTED | DEGRADED ──(ega uzdi yoki ruxsat olib tashlandi)──▶ DISCONNECTED

Suhbat (FSM-04):
NEW ──FIRST_MESSAGE──▶ AI_ACTIVE ──REQUEST_HUMAN──▶ HUMAN_NEEDED ──TAKE_OVER──▶ HUMAN_ACTIVE   [speaker_version +1]
AI_ACTIVE | HUMAN_ACTIVE ──AWAIT_CUSTOMER──▶ WAITING_CUSTOMER ──CUSTOMER_REPLIED──▶ (oldingi speaker)
HUMAN_ACTIVE ──RETURN_TO_AI──▶ AI_ACTIVE   [speaker_version +1]
HUMAN_ACTIVE ──RESOLVE──▶ RESOLVED ──CUSTOMER_REPLIED──▶ REOPENED
```
Kod nomlari — [04](../../engineering/04-state-machines-and-use.md) §4.1. Fencing: AI javobi tayyorlangan paytdagi `speaker_version` hozirgisidan farq qilsa, javob yuborilmaydi (TC-009, [12](../../engineering/12-concurrency-and-transactions.md) §8).

## 4. Event'lar

### Chiqaradi
| Event | Qachon | Kim tinglaydi |
|---|---|---|
| `messaging.message.received` | xaridor xabari saqlandi | sales_ai (`speaker_mode=AI` bo'lsa), reporting |
| `messaging.message.sent` | kanal yuborishni tasdiqladi | platform/notifications (FSM-12), reporting |
| `messaging.message.failed` | yakuniy yuborish xatosi | platform/notifications, reporting |
| `messaging.conversation.handed_off` | `TAKE_OVER` | sales_ai, reporting |
| `messaging.conversation.returned_to_ai` | `RETURN_TO_AI` | sales_ai, reporting |
| `messaging.channel.connected` / `disconnected` | FSM-03 | sales_ai, reporting |

### Tinglaydi
| Event | Kimdan | Nima qiladi |
|---|---|---|
| `sales_ai.reply.ready` | sales_ai | `AUTO`: versiya mos bo'lsa `channel_send`; `SUGGEST`: operatorga taklif |
| `sales_ai.reply.validation_failed` | sales_ai | Yubormaydi, `REQUEST_HUMAN` |
| `sales_ai.handoff.requested` | sales_ai | `REQUEST_HUMAN`, operatorga vazifa |
| `commerce.order.drafted`, `commerce.lead.created`, `commerce.quote.sent` | commerce | Suhbatni buyurtma/lead/taklifga bog'lash, havolani yuborish |
| `platform.notification.customer_delivery_requested` | platform | Xaridorga shop kanali orqali xabar |
| `platform.shop.suspended`, `platform.staff.access_revoked` | platform | Avtomatik javoblar to'xtaydi / suhbatlar qayta taqsimlanadi |
| `platform.privacy.*` | platform | `privacy_handlers` |

Payload'lar — [05](../../engineering/05-events-and-outbox.md) §8.3. Xabar matni event'da yo'q.

## 5. Query Port (`MessagingQueryPort`)

| Metod | Kim ishlatadi |
|---|---|
| `get_conversation_context` | sales_ai (redaction bilan, [14](../../engineering/14-ai-sales-agent-and-tools.md)) |
| `list_conversations_for_backfill` | reporting |

`messaging` o'zi `SalesAiQueryPort` dan AI javob matnini oladi (`01` §3).

## 6. API

`shop` surface: `/shop/channels` (+ `/telegram`, `/instagram/oauth-start`, `/instagram/oauth-callback`, `/{id}/disconnect`), `/shop/conversations` (+ `/{id}/messages`, `/takeover`, `/resume-ai`, `/assign`, `/resolve`).
`storefront` surface: `/storefront/{slug}/chat/sessions`, `/chat/messages`, SSE `/chat/sessions/{session_id}/events` (`08` §6.6).
`webhooks` surface: `POST /webhooks/telegram/{account_ref}`, `GET|POST /webhooks/meta`.
Real vaqt — WebSocket inbox ([08](../../engineering/08-cache-and-realtime.md)).

To'liq ro'yxat — [11](../../engineering/11-api-conventions-errors-i18n.md) §9.5, §9.8, §9.10. Asosiy xatolar: `SPEAKER_CONFLICT`, `CHANNEL_UNAVAILABLE`, `VERSION_CONFLICT`.

## 7. Ruxsatlar

`messaging.channel.view|connect`, `messaging.conversation.view|reply|takeover|assign|resolve`, `messaging.handoff.request` — [10](../../engineering/10-security-tenancy-rbac.md) §6.4. Faqat ega kanal ulaydi (UAT-M09); operator faqat o'ziga biriktirilgan suhbatlarni ko'radi (UAT-M10).

## 8. Fon va rejali ishlar

| Ish | Qachon | Idempotency kaliti |
|---|---|---|
| `channel_send` (arq) | chiquvchi xabar | `outbound_message_id` |
| `conversation_waiting_reminder` | har 5 daq; `HUMAN_NEEDED` uzoq | `conv_waiting:{conversation_id}:{speaker_version}` |
| `channel_health_check` | har 30 daq | `channel_health:{channel_id}:{hour}` |

429 → `Retry-After`; noaniq natijada ko'r-ko'rona qayta yuborilmaydi (TC-032) — [06](../../engineering/06-background-jobs.md) §4.2.

## 9. Metrikalar

`cos_messaging_webhook_received_total`, `cos_messaging_webhook_duplicates_total`, `cos_messaging_webhook_invalid_signature_total`, `cos_messaging_webhook_ack_duration_seconds`, `cos_messaging_message_sent_total`, `cos_messaging_send_failed_total`, `cos_messaging_channel_degraded`, `cos_messaging_handoff_requested_total`, `cos_messaging_stale_ai_reply_dropped_total` — [09](../../engineering/09-observability.md).

## 10. Testlar

TC-009 (operator oldi — AI javobi ketmaydi), TC-010 (takror webhook), TC-011 (kanal ruxsati bekor qilindi), TC-032 (Telegram 429), TC-ISO (webhook → to'g'ri shop); UAT-M09, UAT-M10.

## 11. Ochiq savollar

1. FSM-04: `WAITING_CUSTOMER → AI_ACTIVE` va `REOPENED` dan keyingi yo'l `business/05` da to'liq strelka bilan yo'q — [04](../../engineering/04-state-machines-and-use.md) §11 dagi talqin tasdiqlanishi kerak.
2. Meta ruxsati pilot sanasiga kelmasa — Instagram'siz boshlash (DEC-116a).
