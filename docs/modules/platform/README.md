# platform

**Qatlam:** platform · **Schema:** `platform` (+ `audit`) · **Slice:** S0 (auth, shops, staff, use, audit, storage), S2 (notifications, realtime), S3 (llm), S5 (billing, privacy) · **Egasi:** ___
**Biznes modullar:** M01, M02, M03, M17, M19 (tarif va limitlar), M20 · **Qoidalar:** BL-001…004 (shop), BL-005…008 (xodimlar), BL-009…010 (filiallar), BL-060…062 (xabarnomalar), BL-067…072 (tarif, AI, audit) · **Holatlar:** FSM-01, a'zolik, FSM-12 (`../../business/05`)

## 1. Nima qiladi

Hamma domenlar ishlatadigan xizmatlar: kirish, shop (tenant) va filiallar, xodimlar va ruxsatlar, holat o'tishlari jurnali, audit, xabarnomalar, fayllar, WebSocket, LLM adapteri, tarif va AI limitlari, shaxsiy ma'lumot so'rovlari.

**Qoida:** `platform` domenlarni import qilmaydi (ADR-031). Domenlar platform service'larini to'g'ridan-to'g'ri chaqiradi; platform domenga faqat event bilan yozadi (`platform.notification.customer_delivery_requested`, `platform.privacy.*`, `platform.shop.*`).

## 2. Modullar

| Modul | Vazifasi | Asosiy jadvallar | Batafsil |
|---|---|---|---|
| `auth` | Login, access JWT + rotating refresh cookie (ADR-023), sessiyalar, shop almashtirish, WS ticket | `sessions` | [10](../../engineering/10-security-tenancy-rbac.md) §5 |
| `shops` | Shop (FSM-01), filiallar, shop sozlamalari (`shop_policy`), subdomen | `shops`, `branches`, `shop_policies` | [07](../../engineering/07-data-layer.md) §4.1 |
| `staff` | Principal, a'zolik, rollar, ruxsat katalogi, `require_permission` guard, platforma jamoasi, break-glass | `principals`, `memberships`, `membership_roles`, `role_permissions`, `membership_branches`, `platform_staff`, `support_grants` | [10](../../engineering/10-security-tenancy-rbac.md) §3, §6, §9 |
| `use` | Slim USE: `validate_transition`, `log_transition`, `force_transition`; idempotency | `transition_log`, `idempotency_keys` | [04](../../engineering/04-state-machines-and-use.md), ADR-034 |
| `audit` | Append-only o'zgarishlar tarixi, oyma-oy partition | `audit.audit_entries` | [07](../../engineering/07-data-layer.md) §4.2 |
| `notifications` | Shablonlar (ICU, uz/ru/en), xabar so'rovlari (FSM-12), xodim vazifalari, xodimga yetkazish — dashboard va platformaning tizim Telegram boti (ikkalasi ham, founder qarori 2026-10-22) | `message_templates`, `notifications`, `staff_tasks` | [20](../../engineering/20-notifications.md) |
| `storage` | S3-compatible (MinIO), signed URL, egalik tekshiruvi | `stored_files` | [22](../../engineering/22-infrastructure-and-deployment.md) |
| `realtime` | `/ws`, ConnectionManager, Redis pub/sub relay (ko'p worker) | — | [08](../../engineering/08-cache-and-realtime.md) |
| `llm` | `LLMPort`, provayder adapterlari, PII redaction, xarajat hisobi | `ai_usage`, `llm_pii_refs` | [14](../../engineering/14-ai-sales-agent-and-tools.md), ADR-027 |
| `billing` | Tarif, limitlar, ishlatilish hisoblagichlari (DEC-119) | `subscriptions`, `usage_counters` | [07](../../engineering/07-data-layer.md) §4.1 |
| `privacy` | Xaridor va shop ma'lumotini eksport/o'chirish so'rovlari, domenlar bo'yicha muvofiqlashtirish | `privacy_requests` | [26](../../engineering/26-privacy-and-retention.md) |

## 3. Holatlar

```
Shop (FSM-01):
DRAFT ──(ega ma'lumot yubordi)──▶ PENDING_VERIFICATION ──(platforma faollashtirdi)──▶ ACTIVE
ACTIVE ──(platforma to'xtatdi)──▶ SUSPENDED ──(muammo hal qilindi)──▶ ACTIVE
ACTIVE ──(ega va platforma kelishdi)──▶ CLOSED   [eksport, keyin o'chirish]

A'zolik: INVITED ──(taklif qabul qilindi)──▶ ACTIVE ──(ega o'chirdi)──▶ DISABLED   [sessiyalar darhol tugaydi]

Xabar (FSM-12): PENDING ──(vaqt keldi)──▶ SCHEDULED ──(yuborildi)──▶ SENT
                SCHEDULED ──(5 marta xato)──▶ FAILED   [xodimga vazifa]
                PENDING ──(xaridor rad etgan / kanal ruxsat bermaydi)──▶ SUPPRESSED
```
Kod nomlari — [04](../../engineering/04-state-machines-and-use.md) §4.

## 4. Event'lar

### Chiqaradi
| Event | Qachon | Kim tinglaydi |
|---|---|---|
| `platform.shop.activated` | FSM-01 → `ACTIVE` | storefront, sales_ai, reporting |
| `platform.shop.suspended` | → `SUSPENDED` | storefront, sales_ai, messaging |
| `platform.staff.access_revoked` | a'zolik `DISABLED` yoki rol olindi | messaging, commerce |
| `platform.shop.policy_changed` | shop sozlamalari (masalan `stock_display`) o'zgardi | storefront, sales_ai, commerce |
| `platform.ai_quota.exhausted` | AI limiti tugadi | sales_ai (rejim `OFF`) |
| `platform.notification.customer_delivery_requested` | xaridorga kanal orqali xabar | messaging |
| `platform.privacy.export_requested` / `erasure_requested` / `shop_export_requested` / `shop_purge_requested` | `26` | barcha domenlar |

### Tinglaydi
| Event | Kimdan | Nima qiladi |
|---|---|---|
| `messaging.message.sent` / `failed` | messaging | FSM-12 → `SENT` / `FAILED` |

Payload'lar — [05](../../engineering/05-events-and-outbox.md) §8.6.

## 5. Domenlar chaqiradigan service'lar

| Service | Kim chaqiradi | Tranzaksiya |
|---|---|---|
| `use.validate_transition` / `log_transition` | holati bor har domen | o'sha TX |
| `audit.record` | har domen (muhim o'zgarish, BL-071) | o'sha TX |
| `notifications.request(template_key, recipient, ...)` | domen service yoki subscriber | o'sha TX (platform outbox) |
| `privacy.mark_part_done(request_id, domain, summary)` | domen `privacy_handlers` | domen TX |
| `require_permission(code)`, `get_actor_context()` | router dependency | — |

## 6. API

`auth`: `/auth/login`, `/auth/refresh`, `/auth/logout`, `/auth/switch-shop`, `/auth/ws-ticket`, `/auth/password-reset[/confirm]`, `/auth/invites/{token}/accept`.
`shop` surface: `/shop/profile`, `/shop/policies`, `/shop/branches`, `/shop/members` (+ `/invites`, `/{id}/roles`, `/{id}/disable`), `/shop/tasks`, `/shop/audit-entries`, `/shop/audit-exports`, `/shop/billing/usage`, `/shop/jobs/{job_id}`.
`platform` surface: `/platform/shops` (+ `/activate`, `/suspend`), `/platform/support-grants`, `/platform/outbox/{schema}/{event_id}/replay`, `/platform/kill-switches`.

To'liq ro'yxat — [11](../../engineering/11-api-conventions-errors-i18n.md) §9.1, §9.2, §9.10. Asosiy xatolar: `LAST_OWNER_REQUIRED`, `SHOP_NOT_ACTIVE`, `AI_QUOTA_EXCEEDED`, `IDEMPOTENCY_KEY_REUSED`.

## 7. Ruxsatlar

Shop xodimlari: `shops.settings.view|edit`, `shops.policy.edit`, `shops.branch.edit`, `staff.member.view|invite|edit_roles|disable`, `staff.task.view`, `audit.entry.view|export`, `billing.plan.view`.
Platforma jamoasi: `platform.shop.activate|suspend|view_meta`, `platform.spec.edit`, `platform.support.grant_request`, `platform.outbox.replay`, `platform.channel.kill`, `platform.ai.kill`.
Jadval — [10](../../engineering/10-security-tenancy-rbac.md) §6.1, §6.7.

## 8. Fon va rejali ishlar

| Ish | Qachon | Idempotency kaliti |
|---|---|---|
| `notification_send` (arq) | xodimga bildirishnoma | `notification_id` |
| `audit_partition_create` | har oy 25-sanasi | partition nomi |
| `outbox_cleanup`, `idempotency_cleanup` | har kuni 03:00 / 03:30 | — |
| `retention_purge` | har kuni 04:00 (huquqshunos tasdig'idan keyin yoqiladi) | `retention:{table}:{date}` |
| `ai_usage_rollup` | har 10 daq | `ai_quota:{shop_id}:{period}` |

Batafsil — [06](../../engineering/06-background-jobs.md) §5.2.

## 9. Metrikalar

`cos_security_auth_denied_total`, `cos_security_permission_denied_total`, `cos_security_rls_violation_total`, `cos_security_cross_shop_access_attempt_total`, `cos_security_break_glass_active`, `cos_llm_request_duration_seconds`, `cos_llm_requests_total`, `cos_llm_tokens_total`, `cos_llm_cost_minor_total`, `cos_billing_ai_quota_exhausted_total` — [09](../../engineering/09-observability.md).

## 10. Testlar

TC-ISO-01…10 (S0 gate, [10](../../engineering/10-security-tenancy-rbac.md) §12), TC-001, TC-025 (ruxsat ish paytida olindi), TC-023 (shop yopilmoqda); RLS spike; UAT-M01, UAT-M02, UAT-M03, UAT-M17, UAT-M19, UAT-M20.

## 11. Ochiq savollar

1. RLS spike natijasi (S0) — [07](../../engineering/07-data-layer.md) §14.
2. `business/04` dagi nomuvofiqliklar (AI'ni pauza qilish faqat egami, Analyst uchun shaxsiy ma'lumot ruxsati) — [10](../../engineering/10-security-tenancy-rbac.md) §13.
