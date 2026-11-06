"""Izohga Direct orqali avtomatik javob (DEC-148, instagram_comments.md §1, §5).

Ikki bosqich, `messages` kabi:
1. `decide` (tranzaksiyali, `ig_comment.received` tinglovchisi): flag, shop va post sozlamasi, 7 kunlik oyna,
   "bir muallifga bir postda bitta javob" tekshiriladi; matn shablondan (narx — faqat bog'langan katalog
   mahsulotidan, javob paytida) yig'iladi; qator `QUEUED` yoki `SKIPPED` (sabab bilan). `intent_key` unikal —
   takroriy hodisa ikkinchi javob yaratmaydi.
2. `send` (tranzaksiyasiz, `ig_comment.reply_queued`): tashqi chaqiruv tranzaksiyadan tashqarida —
   avval `SENDING` (COMMIT), keyin Meta, keyin natija. 429/5xx — qayta urinish; timeout — `FAILED`
   (yuborildimi noma'lum, ko'r-ko'rona qayta yuborilmaydi).
Javob inbox'ga tushmaydi: Private Reply paytida xaridorning Direct id'si noma'lum.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Any
from uuid import UUID

import structlog
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.messaging.channels.base import ChannelSendError
from app.domains.messaging.channels.instagram import REPLY_WINDOW_DAYS
from app.domains.messaging.common import (
    MAX_SEND_ATTEMPTS,
    SENDABLE_CHANNEL_STATUSES,
    ChannelAdapters,
    MessagingConfig,
)
from app.domains.messaging.ig_rules import NONE, detect_locale
from app.domains.messaging.models.ig import IgComment, IgCommentReply, IgPost, IgPostProduct
from app.domains.messaging.models.orm import ChannelAccount
from app.domains.messaging.services.ig_common import (
    EV_REPLY_FINISHED,
    EV_REPLY_QUEUED,
    as_uuid,
    comment_settings,
    emit_reply,
)
from app.domains.messaging.services.notify import format_total
from app.platform.notifications.customer_templates import safe_render
from app.platform.notifications.services.customer_templates import CustomerTemplateService
from app.platform.shops.models.orm import Shop
from app.shared.clock import utcnow
from app.shared.contracts.catalog import CatalogQueryPort, PublicProductDetail
from app.shared.contracts.commerce import StockQueryPort, stock_status
from app.shared.db.session import Database
from app.shared.events.envelope import EventEnvelope
from app.shared.events.registry import RetryLater

logger = structlog.get_logger(__name__)
PRICE_TEMPLATE = "customer.ig_comment_price_reply"
GENERIC_TEMPLATE = "customer.ig_comment_generic_reply"
LIVE_REPLY = ("QUEUED", "SENDING", "SENT")  # shu muallifga shu postda "javob ketgan" hisoblanadi
# Adapter xatosi → skip_reason (13 §2 taksonomiyasiga qo'shimcha kodlar, instagram_comments.md §7.5)
SKIP_ON_ERROR = {"REPLY_WINDOW_EXPIRED": "WINDOW_EXPIRED", "ALREADY_REPLIED": "AUTHOR_ALREADY_REPLIED"}

_FROM = {"uz": "{price} dan boshlab", "ru": "от {price}", "en": "from {price}"}
_STOCK = {
    "IN_STOCK": {"uz": "bor", "ru": "в наличии", "en": "in stock"},
    "LOW_STOCK": {"uz": "oz qoldi", "ru": "осталось мало", "en": "low stock"},
    "OUT_OF_STOCK": {"uz": "hozircha yo'q", "ru": "нет в наличии", "en": "out of stock"},
    "UNKNOWN": {"uz": "mavjudligini so'rang", "ru": "наличие уточняйте", "en": "ask about availability"},
}
_EXACT = {"uz": "{n} dona bor", "ru": "{n} шт. в наличии", "en": "{n} in stock"}


@dataclass(frozen=True)
class _Job:
    token: str | None
    fake: bool
    account_id: str | None
    comment_id: str
    body: str
    attempts: int


@dataclass(frozen=True)
class _Line:
    title: str
    price: str


class IgReplyService:
    def __init__(
        self,
        adapters: ChannelAdapters,
        config: MessagingConfig,
        templates: CustomerTemplateService,
        catalog: CatalogQueryPort | None,
        stock: StockQueryPort | None,
    ) -> None:
        self.adapters = adapters
        self.config = config
        self.templates = templates
        self.catalog = catalog
        self.stock = stock

    # ------------------------------------------------------------------ 1-bosqich: qaror
    async def decide(self, db: AsyncSession, envelope: EventEnvelope) -> str:
        """Natija: queued | skipped | ignored | exists."""
        comment_id = as_uuid(envelope.payload.get("item_id"))
        if envelope.shop_id is None or comment_id is None:
            return "ignored"
        shop_id = envelope.shop_id
        comment = (
            await db.execute(
                select(IgComment)
                .where(IgComment.shop_id == shop_id, IgComment.id == comment_id)
                .with_for_update()
            )
        ).scalar_one_or_none()
        if comment is None or comment.trigger == NONE:
            return "ignored"
        intent_key = f"ig_auto:{comment.id}"
        if await self._reply_by_intent(db, shop_id, intent_key) is not None:
            return "exists"
        # Bir muallif — bir post: ikki izoh bir vaqtda kelsa ham bittasi o'tadi
        await db.execute(
            select(
                func.pg_advisory_xact_lock(
                    func.hashtext(f"igreply:{shop_id}:{comment.post_id}:{comment.author_external_id}")
                )
            )
        )
        account = await db.get(ChannelAccount, comment.channel_account_id)
        post = await db.get(IgPost, comment.post_id)
        reason = await self._skip_reason(db, comment, account, post)
        values: dict[str, Any] = {
            "shop_id": shop_id,
            "comment_id": comment.id,
            "kind": "PRIVATE_AUTO",
            "intent_key": intent_key,
            "status": "SKIPPED",
            "skip_reason": reason,
        }
        if reason is None:
            assert post is not None
            values.update(await self._compose(db, shop_id, comment, post), status="QUEUED")
        reply_id = await db.scalar(
            insert(IgCommentReply)
            .values(**values)
            .on_conflict_do_nothing(index_elements=["shop_id", "intent_key"])
            .returning(IgCommentReply.id)
        )
        if reply_id is None:
            return "exists"
        reply = await db.get(IgCommentReply, reply_id)
        assert reply is not None
        if reason is not None:
            await emit_reply(db, reply, EV_REPLY_FINISHED, status="SKIPPED", skip_reason=reason)
            return "skipped"
        await emit_reply(db, reply, EV_REPLY_QUEUED)
        return "queued"

    async def _skip_reason(
        self, db: AsyncSession, comment: IgComment, account: ChannelAccount | None, post: IgPost | None
    ) -> str | None:
        if not self.config.instagram_enabled:
            return "FLAG_OFF"
        if comment.is_own_account:
            return "OWN_ACCOUNT"
        if comment.status == "DELETED":
            return "COMMENT_DELETED"
        if account is None or account.status not in SENDABLE_CHANNEL_STATUSES:
            return "CHANNEL_DISCONNECTED"
        if not comment_settings(account)["auto_reply"]:
            return "AUTO_REPLY_OFF"
        if post is None or not post.auto_reply_enabled:
            return "POST_AUTO_REPLY_OFF"
        if comment.commented_at < utcnow() - timedelta(days=REPLY_WINDOW_DAYS):
            return "WINDOW_EXPIRED"
        taken = await db.scalar(
            select(IgCommentReply.id)
            .join(
                IgComment,
                (IgComment.shop_id == IgCommentReply.shop_id) & (IgComment.id == IgCommentReply.comment_id),
            )
            .where(
                IgComment.shop_id == comment.shop_id,
                IgComment.post_id == comment.post_id,
                IgComment.author_external_id == comment.author_external_id,
                IgComment.id != comment.id,
                IgCommentReply.kind == "PRIVATE_AUTO",
                IgCommentReply.status.in_(LIVE_REPLY),
            )
            .limit(1)
        )
        return "AUTHOR_ALREADY_REPLIED" if taken is not None else None

    @staticmethod
    async def _reply_by_intent(db: AsyncSession, shop_id: UUID, intent_key: str) -> IgCommentReply | None:
        return (
            await db.execute(
                select(IgCommentReply).where(
                    IgCommentReply.shop_id == shop_id, IgCommentReply.intent_key == intent_key
                )
            )
        ).scalar_one_or_none()

    # ------------------------------------------------------------------ matn
    async def _compose(
        self, db: AsyncSession, shop_id: UUID, comment: IgComment, post: IgPost
    ) -> dict[str, Any]:
        shop = await db.get(Shop, shop_id)
        default = shop.default_locale if shop is not None and shop.default_locale in _EXACT else "uz"
        locale = detect_locale(comment.body) or default
        lines, variables = await self._price_variables(db, shop_id, post, locale, shop)
        key = PRICE_TEMPLATE if variables else GENERIC_TEMPLATE
        template, version = await self.templates.resolve(db, shop_id, key, locale)
        text = safe_render(key, template, variables, locale)
        if lines[1:]:  # karusel: birinchisi shablonda, qolganlari qisqa ro'yxat (I3)
            text += "\n" + "\n".join(f"• {line.title} — {line.price}" for line in lines[1:])
        return {
            "template_key": key,
            "template_version": version,
            "locale": locale,
            "body": text,
            "variables": {k: v for k, v in variables.items() if v is not None},
        }

    async def _price_variables(
        self, db: AsyncSession, shop_id: UUID, post: IgPost, locale: str, shop: Shop | None
    ) -> tuple[list[_Line], dict[str, Any]]:
        """Narx — faqat post bog'langan mahsulotdan va faqat saytda ko'rinadigan (narxi bor) variantdan.
        Bog'lanish yo'q yoki mahsulot ko'rinmaydi — bo'sh (umumiy javob)."""
        if self.catalog is None:
            return [], {}
        links = (
            (
                await db.execute(
                    select(IgPostProduct)
                    .where(IgPostProduct.shop_id == shop_id, IgPostProduct.post_id == post.id)
                    .order_by(IgPostProduct.position, IgPostProduct.product_id)
                )
            )
            .scalars()
            .all()
        )
        lines: list[_Line] = []
        first: dict[str, Any] = {}
        for link in links:
            detail = await self.catalog.public_product(db, shop_id, link.product_id)
            if detail is None:
                continue
            title, minor, many, sku_ids = _choose(detail, link.sku_id)
            price = format_total(minor, locale)
            shown = _FROM[locale].format(price=price) if many else price
            lines.append(_Line(title, shown))
            if not first:
                first = {
                    "product_title": title,
                    "price": shown,
                    "stock_line": await self._stock_line(db, shop_id, sku_ids, locale),
                    "product_url": self._url(shop, detail.product_id),
                    "shop_name": shop.name if shop is not None else None,
                }
        return lines, first

    async def _stock_line(self, db: AsyncSession, shop_id: UUID, sku_ids: list[UUID], locale: str) -> str:
        if self.stock is None or not sku_ids:
            return _STOCK["UNKNOWN"][locale]
        availability = await self.stock.availability(db, shop_id, sku_ids)
        policy = await self.stock.display_policy(db, shop_id)
        total = sum(item.available for item in availability.values())
        status = stock_status(total, policy.low_stock_threshold)
        if status != "OUT_OF_STOCK" and policy.stock_display == "EXACT":
            return _EXACT[locale].format(n=total)
        return _STOCK[status][locale]

    def _url(self, shop: Shop | None, product_id: UUID) -> str:
        template = self.config.storefront_public_url
        if shop is None or not template:
            return ""
        return f"{template.replace('{slug}', shop.slug).rstrip('/')}/p/{product_id}"

    # ------------------------------------------------------------------ 2-bosqich: yuborish
    async def send(self, database: Database, shop_id: UUID, reply_id: UUID) -> str:
        """Natija: sent | skipped | failed | retry (`RetryLater` ko'tariladi)."""
        async with database.transaction(shop_id) as db:
            prepared = await self._prepare(db, shop_id, reply_id)
        if isinstance(prepared, str):
            return prepared
        try:
            if prepared.fake:  # dev seed'dagi soxta akkaunt: tashqariga hech narsa ketmaydi
                provider_message_id: str | None = "fake"
            else:
                if not prepared.token or not prepared.account_id:
                    raise ChannelSendError("AUTH_REVOKED")
                result = await self.adapters.instagram.send_private_reply(
                    prepared.token, prepared.account_id, prepared.comment_id, prepared.body
                )
                provider_message_id = result.provider_message_id
        except ChannelSendError as exc:
            async with database.transaction(shop_id) as db:
                outcome = await self._failed(db, shop_id, reply_id, exc, prepared.attempts)
            if outcome == "retry":
                raise RetryLater(exc.retry_after or min(60 * prepared.attempts, 600)) from exc
            return outcome
        async with database.transaction(shop_id) as db:
            await self._sent(db, shop_id, reply_id, provider_message_id)
        return "sent"

    async def _prepare(self, db: AsyncSession, shop_id: UUID, reply_id: UUID) -> _Job | str:
        reply = await self._locked(db, shop_id, reply_id)
        if reply is None or reply.status != "QUEUED":
            return "skipped"  # takroriy vazifa yoki allaqachon yakunlangan
        comment = await db.get(IgComment, reply.comment_id)
        assert comment is not None
        account = await db.get(ChannelAccount, comment.channel_account_id)
        reason: str | None = None
        if comment.status == "DELETED":
            reason = "COMMENT_DELETED"
        elif account is None or account.status not in SENDABLE_CHANNEL_STATUSES:
            reason = "CHANNEL_DISCONNECTED"
        elif comment.commented_at < utcnow() - timedelta(days=REPLY_WINDOW_DAYS):
            reason = "WINDOW_EXPIRED"
        if reason is not None or account is None:
            await self._skip(db, reply, reason or "CHANNEL_DISCONNECTED")
            return "skipped"
        reply.status = "SENDING"
        reply.attempts += 1
        return _Job(
            token=account.token_enc,
            fake=bool((account.settings or {}).get("fake")),
            account_id=account.external_account_id,
            comment_id=comment.external_comment_id,
            body=reply.body or "",
            attempts=reply.attempts,
        )

    async def _sent(
        self, db: AsyncSession, shop_id: UUID, reply_id: UUID, provider_message_id: str | None
    ) -> None:
        reply = await self._locked(db, shop_id, reply_id)
        if reply is None or reply.status != "SENDING":
            return
        reply.status, reply.sent_at = "SENT", utcnow()
        reply.provider_message_id, reply.last_error_code = provider_message_id, None
        await db.flush()
        await emit_reply(db, reply, EV_REPLY_FINISHED, status="SENT")

    async def _failed(
        self, db: AsyncSession, shop_id: UUID, reply_id: UUID, exc: ChannelSendError, attempts: int
    ) -> str:
        reply = await self._locked(db, shop_id, reply_id)
        if reply is None or reply.status != "SENDING":
            return "skipped"
        reply.last_error_code = exc.code
        if exc.retryable and not exc.unknown and attempts < MAX_SEND_ATTEMPTS:
            reply.status = "QUEUED"
            return "retry"
        if exc.code in SKIP_ON_ERROR:
            await self._skip(db, reply, SKIP_ON_ERROR[exc.code])
            return "skipped"
        reply.status, reply.failed_at = "FAILED", utcnow()
        await db.flush()
        await emit_reply(db, reply, EV_REPLY_FINISHED, status="FAILED")
        return "failed"

    @staticmethod
    async def _skip(db: AsyncSession, reply: IgCommentReply, reason: str) -> None:
        reply.status, reply.skip_reason = "SKIPPED", reason
        await db.flush()
        await emit_reply(db, reply, EV_REPLY_FINISHED, status="SKIPPED", skip_reason=reason)

    @staticmethod
    async def _locked(db: AsyncSession, shop_id: UUID, reply_id: UUID) -> IgCommentReply | None:
        return (
            await db.execute(
                select(IgCommentReply)
                .where(IgCommentReply.shop_id == shop_id, IgCommentReply.id == reply_id)
                .with_for_update()
            )
        ).scalar_one_or_none()


def _choose(detail: PublicProductDetail, sku_id: UUID | None) -> tuple[str, int, bool, list[UUID]]:
    """(sarlavha, narx tiyinda, "dan boshlab"mi, qoldiq tekshiriladigan SKU'lar). Aniq variant bog'langan va
    ko'rinsa — shu narx; aks holda eng arzon ko'rinadigan variant (bir nechta bo'lsa — "dan boshlab")."""
    variants = sorted(detail.variants, key=lambda v: v.price_uzs_minor)
    if sku_id is not None:
        exact = next((v for v in variants if v.sku_id == sku_id), None)
        if exact is not None:
            title = " · ".join(part for part in (detail.title, exact.variant_name) if part)
            return title, exact.price_uzs_minor, False, [exact.sku_id]
    cheapest = variants[0]
    many = len({v.price_uzs_minor for v in variants}) > 1
    return detail.title, cheapest.price_uzs_minor, many, [v.sku_id for v in variants]
