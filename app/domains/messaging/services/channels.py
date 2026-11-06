"""Kanal ulash va uzish (FSM-03, UAT-M09): faqat ega. Telegram — bot tokeni; sayt chati — tokensiz;
Instagram — DEC-116a flag ostida.

Ulash: `getMe` (token to'g'rimi) → prod'da `setWebhook` (taxmin qilib bo'lmaydigan `account_ref` manzil +
sir; bazada sirning faqat xeshi), lokalda `deleteWebhook` + polling (ochiq manzil yo'q). Token bazada
shifrlangan (11-qaror), API javobida va audit'da hech qachon yo'q. Boshqa bot ulansa eskisi `REPLACED`.
"""

from __future__ import annotations

import secrets
from typing import Any
from uuid import UUID

import structlog
from sqlalchemy import select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.messaging.channels.base import ChannelConnectError
from app.domains.messaging.channels.telegram import BotInfo
from app.domains.messaging.common import (
    CHANNEL,
    TEST_TELEGRAM_TOKEN,
    ChannelAdapters,
    MessagingConfig,
    emit,
    sha256,
)
from app.domains.messaging.models.orm import ChannelAccount, Conversation, WebchatSession
from app.domains.messaging.schemas import ChannelAccountOut, ChannelList
from app.domains.messaging.state_machine import CHANNEL as CHANNEL_ENTITY
from app.platform.audit.services.audit_service import AuditService
from app.platform.use.services.use_service import UseService
from app.shared.clock import utcnow
from app.shared.db.session import set_shop_context
from app.shared.errors.base import (
    FeatureNotAvailableError,
    InvalidTransitionError,
    NotFoundError,
    ProviderUnavailableError,
    ValidationError,
)
from app.shared.http import check_version
from app.shared.types.actor import ActorContext

logger = structlog.get_logger(__name__)
ACTIVE = ("PENDING", "CONNECTED", "DEGRADED")


def account_out(row: ChannelAccount) -> ChannelAccountOut:
    settings = row.settings or {}
    mode = settings.get("mode") if row.channel == "TELEGRAM" else None
    return ChannelAccountOut(
        id=row.id,
        channel=row.channel,
        status=row.status,
        display_name=row.display_name,
        external_account_id=row.external_account_id,
        mode=mode if mode in ("webhook", "polling") else None,
        is_fake=bool(settings.get("fake")),
        last_webhook_at=row.last_webhook_at,
        last_error_code=row.last_error_code,
        connected_at=row.connected_at,
        disconnected_at=row.disconnected_at,
        disconnect_reason=row.disconnect_reason,
        version=row.version,
    )


def _token_error(code: str) -> ValidationError:
    return ValidationError(
        "Channel connection failed", fields=[{"field": "token", "code": code, "params": {}}]
    )


class ChannelService:
    def __init__(
        self, use: UseService, audit: AuditService, adapters: ChannelAdapters, config: MessagingConfig
    ) -> None:
        self.use = use
        self.audit = audit
        self.adapters = adapters
        self.config = config

    # ------------------------------------------------------------------ panel
    async def list_accounts(self, db: AsyncSession, actor: ActorContext) -> ChannelList:
        rows = (
            (
                await db.execute(
                    select(ChannelAccount)
                    .where(ChannelAccount.shop_id == actor.shop_id)
                    .order_by(ChannelAccount.created_at.desc())
                )
            )
            .scalars()
            .all()
        )
        return ChannelList(
            items=[account_out(r) for r in rows],
            telegram_mode="polling" if self.config.telegram_mode == "polling" else "webhook",
            instagram_available=self.config.instagram_enabled,
            instagram_oauth_available=bool(
                self.config.instagram_enabled
                and self.config.instagram_app_id
                and self.config.instagram_app_secret
            ),
        )

    async def active(self, db: AsyncSession, shop_id: UUID, channel: str) -> ChannelAccount | None:
        return (
            await db.execute(
                select(ChannelAccount)
                .where(
                    ChannelAccount.shop_id == shop_id,
                    ChannelAccount.channel == channel,
                    ChannelAccount.status.in_(ACTIVE),
                )
                .with_for_update()
            )
        ).scalar_one_or_none()

    async def connect_telegram(self, db: AsyncSession, actor: ActorContext, token: str) -> ChannelAccountOut:
        assert actor.shop_id is not None
        test = TEST_TELEGRAM_TOKEN.fullmatch(token) if self.config.telegram_test_tokens else None
        if test is not None:  # local/test: soxta bot, tashqariga so'rov yo'q (QA 5b frontend c)
            bot = BotInfo(id=int(test.group("bot")), username=f"cos_test_{test.group('bot')[-4:]}_bot")
        else:
            try:
                bot = await self.adapters.telegram.get_me(token)
            except ChannelConnectError as exc:
                if exc.code == "INVALID_TOKEN":
                    raise _token_error("invalid") from exc
                raise ProviderUnavailableError("Telegram is not reachable", provider="telegram") from exc
        current = await self.active(db, actor.shop_id, "TELEGRAM")
        if current is not None and current.external_account_id == str(bot.id):
            account = current  # o'sha bot — token yangilanadi (masalan @BotFather'da qayta chiqarilgan)
        else:
            if current is not None:
                await self._disconnect(db, actor, current, "REPLACED")
            account = ChannelAccount(
                shop_id=actor.shop_id,
                channel="TELEGRAM",
                status="PENDING",
                account_ref=secrets.token_urlsafe(32),
                external_account_id=str(bot.id),
                version=1,
            )
            db.add(account)
            try:
                async with db.begin_nested():
                    await db.flush()
            except IntegrityError as exc:
                raise _token_error("already_connected") from exc  # bu bot boshqa shopda ulangan
        settings: dict[str, Any] = {"mode": self.config.telegram_mode}
        if test is not None:
            settings["fake"] = True
        try:
            if test is not None:
                account.webhook_secret_hash = None
            elif self.config.telegram_mode == "polling":
                await self.adapters.telegram.delete_webhook(token)
                account.webhook_secret_hash = None
            else:
                secret = secrets.token_urlsafe(32)
                base = self.config.webhook_base_url.rstrip("/")
                url = f"{base}/api/v1/webhooks/telegram/{account.account_ref}"
                await self.adapters.telegram.set_webhook(token, url, secret)
                account.webhook_secret_hash = sha256(secret)
        except ChannelConnectError as exc:
            raise ProviderUnavailableError("Telegram webhook setup failed", provider="telegram") from exc
        account.token_enc = token
        account.display_name = f"@{bot.username}" if bot.username else None
        account.settings = settings
        account.last_error_code = None
        await self._connected(db, actor, account)
        return account_out(account)

    def _app_token(self) -> str | None:
        if self.config.instagram_app_id and self.config.instagram_app_secret:
            return f"{self.config.instagram_app_id}|{self.config.instagram_app_secret}"
        return None

    async def connect_instagram(
        self,
        db: AsyncSession,
        actor: ActorContext,
        access_token: str,
        account_id: str | None = None,
        *,
        meta_user_id: str | None = None,
    ) -> ChannelAccountOut:
        if not self.config.instagram_enabled:
            raise NotFoundError("Not found")  # DEC-116a: flag o'chiq — kanal yo'qdek
        assert actor.shop_id is not None
        try:
            ig = await self.adapters.instagram.get_account(
                access_token, app_token=self._app_token(), account_id=account_id
            )
        except ChannelConnectError as exc:
            raise ValidationError(
                "Channel connection failed",
                fields=[{"field": "access_token", "code": "invalid", "params": {}}],
            ) from exc
        stored_token = ig.token or access_token
        if self.config.instagram_app_id and self.config.instagram_app_secret:  # qisqa token -> ~60 kunlik
            stored_token = (
                await self.adapters.instagram.extend_token(
                    stored_token,
                    app_id=self.config.instagram_app_id,
                    app_secret=self.config.instagram_app_secret,
                )
                or stored_token
            )
        # obuna muvaffaqiyatsiz bo'lsa ulanish to'xtamaydi — xato logga tushadi
        await self.adapters.instagram.subscribe(stored_token, ig)
        current = await self.active(db, actor.shop_id, "INSTAGRAM")
        if current is not None:
            await self._disconnect(db, actor, current, "REPLACED")
        account = ChannelAccount(
            shop_id=actor.shop_id,
            channel="INSTAGRAM",
            status="PENDING",
            account_ref=secrets.token_urlsafe(32),
            external_account_id=ig.id,
            display_name=f"@{ig.username}" if ig.username else None,
            token_enc=stored_token,
            scopes=list(ig.scopes) or None,
            settings={"meta_user_id": meta_user_id}
            if meta_user_id
            else {},  # Meta ma'lumot o'chirish so'rovi uchun
            version=1,
        )
        db.add(account)
        try:
            async with db.begin_nested():
                await db.flush()
        except IntegrityError as exc:
            raise ValidationError(
                "Channel connection failed",
                fields=[{"field": "access_token", "code": "already_connected", "params": {}}],
            ) from exc
        await self._connected(db, actor, account)
        return account_out(account)

    async def enable_webchat(self, db: AsyncSession, actor: ActorContext) -> ChannelAccountOut:
        assert actor.shop_id is not None
        current = await self.active(db, actor.shop_id, "WEB_CHAT")
        if current is not None:
            return account_out(current)
        account = ChannelAccount(
            shop_id=actor.shop_id,
            channel="WEB_CHAT",
            status="PENDING",
            account_ref=secrets.token_urlsafe(32),
            display_name="Sayt chati",
            settings={},
            version=1,
        )
        db.add(account)
        await db.flush()
        await self._connected(db, actor, account)
        # Qayta yoqilganda eski sayt chati suhbatlari va mehmon sessiyalari yangi akkauntga o'tadi:
        # operator eski suhbatga yoza oladi, mehmon o'sha chatni davom ettiradi (QA 5b L4)
        for model in (Conversation, WebchatSession):
            await db.execute(
                update(model)
                .where(model.shop_id == actor.shop_id, model.channel_account_id != account.id)
                .where(
                    model.channel_account_id.in_(
                        select(ChannelAccount.id).where(
                            ChannelAccount.shop_id == actor.shop_id, ChannelAccount.channel == "WEB_CHAT"
                        )
                    )
                )
                .values(channel_account_id=account.id)
            )
        return account_out(account)

    async def disconnect(
        self, db: AsyncSession, actor: ActorContext, account_id: UUID, expected_version: int
    ) -> ChannelAccountOut:
        account = (
            await db.execute(
                select(ChannelAccount)
                .where(ChannelAccount.shop_id == actor.shop_id, ChannelAccount.id == account_id)
                .with_for_update()
            )
        ).scalar_one_or_none()
        if account is None:
            raise NotFoundError("Channel not found")
        check_version(account.version, expected_version)
        if account.status not in ("CONNECTED", "DEGRADED"):
            raise InvalidTransitionError(
                "Channel is not connected", entity=CHANNEL, **{"from": account.status}, command="DISCONNECT"
            )
        token = account.token_enc
        await self._disconnect(db, actor, account, "OWNER")
        if account.channel == "TELEGRAM" and token and not (account.settings or {}).get("fake"):
            try:  # best effort: bot boshqa joyda ishlatilsa, eski webhook unga xalaqit bermasin
                await self.adapters.telegram.delete_webhook(token)
            except ChannelConnectError:
                logger.warning("messaging.channel.webhook_delete_failed", channel_account_id=str(account.id))
        return account_out(account)

    async def revoke_meta_user(self, db: AsyncSession, meta_user_id: str) -> int:
        """Meta "Deauthorize" / "Data deletion" callback'i: shu Facebook foydalanuvchisi OAuth bilan ulagan
        Instagram akkauntlari uziladi va token o'chiriladi. Shop noma'lum — RLS identity varianti
        (`app.meta_user_ref`, messaging_0005); har akkaunt o'z shop kontekstida yopiladi."""
        if not meta_user_id or len(meta_user_id) > 64:
            return 0
        await db.execute(text("SELECT set_config('app.meta_user_ref', :ref, true)"), {"ref": meta_user_id})
        accounts = (
            (
                await db.execute(
                    select(ChannelAccount)
                    .where(
                        ChannelAccount.channel == "INSTAGRAM",
                        ChannelAccount.settings["meta_user_id"].astext == meta_user_id,
                    )
                    .with_for_update()
                )
            )
            .scalars()
            .all()
        )
        for account in accounts:
            await set_shop_context(db, account.shop_id)
            if account.status in ("CONNECTED", "DEGRADED", "PENDING"):
                await self._disconnect(db, ActorContext.system(account.shop_id), account, "AUTH_REVOKED")
            account.token_enc = None
            account.settings = {k: v for k, v in (account.settings or {}).items() if k != "meta_user_id"}
            await db.flush()
        return len(accounts)

    # ------------------------------------------------------------------ webhook va polling
    async def resolve_by_ref(self, db: AsyncSession, channel: str, account_ref: str) -> ChannelAccount | None:
        """Webhook: shop hali noma'lum — RLS "identity varianti" (`app.channel_account_ref`, 12-qaror).
        Topilsa tranzaksiyaga shop konteksti o'rnatiladi."""
        if not account_ref or len(account_ref) > 100:
            return None
        await db.execute(
            text("SELECT set_config('app.channel_account_ref', :ref, true)"), {"ref": account_ref}
        )
        account = (
            await db.execute(
                select(ChannelAccount)
                .where(ChannelAccount.account_ref == account_ref, ChannelAccount.channel == channel)
                .with_for_update()
            )
        ).scalar_one_or_none()
        if account is None or account.status not in ("CONNECTED", "DEGRADED"):
            return None
        await set_shop_context(db, account.shop_id)
        return account

    async def by_external(
        self, db: AsyncSession, channel: str, external_account_id: str
    ) -> ChannelAccount | None:
        """Instagram webhook: Meta bitta app manzili bilan keladi, akkaunt `entry.id` bo'yicha. RLS — identity
        varianti (`app.channel_external_ref` = "INSTAGRAM:<id>"), topilsa shop konteksti o'rnatiladi."""
        if not external_account_id or len(external_account_id) > 64:
            return None
        await db.execute(
            text("SELECT set_config('app.channel_external_ref', :ref, true)"),
            {"ref": f"{channel}:{external_account_id}"},
        )
        account = (
            await db.execute(
                select(ChannelAccount)
                .where(
                    ChannelAccount.channel == channel,
                    ChannelAccount.external_account_id == external_account_id,
                    ChannelAccount.status.in_(("CONNECTED", "DEGRADED")),
                )
                .with_for_update()
            )
        ).scalar_one_or_none()
        if account is not None:
            await set_shop_context(db, account.shop_id)
        return account

    async def polling_accounts(self, db: AsyncSession, shop_id: UUID) -> list[ChannelAccount]:
        rows = await db.execute(
            select(ChannelAccount).where(
                ChannelAccount.shop_id == shop_id,
                ChannelAccount.channel == "TELEGRAM",
                ChannelAccount.status.in_(("CONNECTED", "DEGRADED")),
            )
        )
        return [
            r
            for r in rows.scalars()
            if (r.settings or {}).get("mode") == "polling"
            and r.token_enc
            and not (r.settings or {}).get("fake")
        ]

    # ------------------------------------------------------------------ ichki
    async def _connected(self, db: AsyncSession, actor: ActorContext, account: ChannelAccount) -> None:
        now = utcnow()
        if account.status == "PENDING":
            rule = self.use.validate_transition(CHANNEL_ENTITY, "PENDING", "CONNECTED", "CONNECT", actor)
        elif account.status == "DEGRADED":
            rule = self.use.validate_transition(CHANNEL_ENTITY, "DEGRADED", "CONNECTED", "RECONNECT", actor)
        else:
            rule = None
        account.status = "CONNECTED"
        account.connected_by, account.connected_at = actor.membership_id, now
        account.disconnected_at, account.disconnect_reason = None, None
        await db.flush()
        if rule is not None:
            await self.use.log_transition(db, entity_id=account.id, rule=rule, actor=actor)
        await self.audit.record(
            db,
            action="messaging.channel.connected",
            entity_type=CHANNEL,
            entity_id=account.id,
            actor=actor,
            entity_version=account.version,
            diff={"channel": {"new": account.channel}, "display": {"new": account.display_name}},
        )
        await emit(
            db,
            actor,
            event_type="messaging.channel.connected",
            shop_id=account.shop_id,
            aggregate_type=CHANNEL,
            aggregate_id=account.id,
            aggregate_version=account.version,
            payload={"channel_account_id": account.id, "channel": account.channel, "status": account.status},
        )

    async def _disconnect(
        self, db: AsyncSession, actor: ActorContext, account: ChannelAccount, reason: str
    ) -> None:
        if account.status == "PENDING":
            account.status = "DISCONNECTED"  # ulanib ulgurmagan — FSM'da strelka yo'q, faqat yopiladi
        else:
            rule = self.use.validate_transition(
                CHANNEL_ENTITY, account.status, "DISCONNECTED", "DISCONNECT", actor
            )
            account.status = "DISCONNECTED"
            await self.use.log_transition(db, entity_id=account.id, rule=rule, actor=actor, reason=reason)
        account.disconnected_at, account.disconnect_reason = utcnow(), reason
        await db.flush()
        await self.audit.record(
            db,
            action="messaging.channel.disconnected",
            entity_type=CHANNEL,
            entity_id=account.id,
            actor=actor,
            entity_version=account.version,
            reason=reason,
        )
        await emit(
            db,
            actor,
            event_type="messaging.channel.disconnected",
            shop_id=account.shop_id,
            aggregate_type=CHANNEL,
            aggregate_id=account.id,
            aggregate_version=account.version,
            payload={"channel_account_id": account.id, "channel": account.channel, "reason_code": reason},
        )

    def require_instagram(self) -> None:
        if not self.config.instagram_enabled:
            raise FeatureNotAvailableError("Instagram channel is not enabled")
