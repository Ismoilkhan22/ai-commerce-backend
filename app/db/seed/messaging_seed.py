"""Lokal demo: suhbatlar (5b) — `make seed` ichidan, qayta ishga tushirish xavfsiz.

- Ochiq saytlar (NoutbukUz, KompyuterPro, Hi-Tech Samarqand) — sayt chati yoqilgan.
- NoutbukUz — SOXTA Telegram bot (`settings.fake`, tokensiz): tashqariga hech narsa ketmaydi, javoblar
  darhol "yuborildi" bo'ladi. Haqiqiy botni panelda ulash mumkin — u soxtasini almashtiradi.
- NoutbukUz suhbatlari: operator kutayotgan (HUMAN_NEEDED), xaridor javobini kutayotgan (WAITING_CUSTOMER),
  buyurtmaga bog'langan va yopilgan (RESOLVED), sayt chatidan yopilgan suhbat.
Hammasi servislar orqali (FSM-04, handoff vazifasi, xabarnoma, audit haqiqiydagidek). Bor kanal qayta
yaratilmaydi; demo suhbatlar NoutbukUz'da Telegram akkaunti bo'lmasa (bir marta) yoziladi.
Xaridorlar — to'qima ism va raqamlar (demo).
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.settings import Settings
from app.domains.commerce.orders.models.orm import Order
from app.domains.messaging.channels.base import InboundMessage
from app.domains.messaging.common import sha256
from app.domains.messaging.models.orm import ChannelAccount, Conversation, WebchatSession
from app.domains.messaging.providers import MessagingServices
from app.platform.shops.models.orm import Shop
from app.platform.staff.models.orm import Membership
from app.platform.staff.permissions import PermissionRegistry
from app.shared.clock import utcnow
from app.shared.db.session import set_identity_context
from app.shared.types.actor import ActorContext
from app.workers.queue import RecordingQueue
from app.workers.runtime import WorkerRuntime, build_runtime

WEBCHAT_SHOPS = ("noutbukuz", "kompyuterpro", "hitech-samarqand")
FAKE_BOT_ID = "seed-noutbukuz-bot"


@dataclass
class MessagingSeedReport:
    channels: int = 0
    conversations: int = 0


async def _actors(
    db: AsyncSession, permissions: PermissionRegistry, slug: str
) -> tuple[UUID, dict[str, ActorContext]] | None:
    shop = (await db.execute(select(Shop).where(Shop.slug == slug))).scalar_one_or_none()
    if shop is None:
        return None
    await set_identity_context(db, shop_id=shop.id)
    actors: dict[str, ActorContext] = {}
    members = await db.execute(
        select(Membership)
        .where(Membership.shop_id == shop.id, Membership.status == "ACTIVE")
        .order_by(Membership.created_at)
    )
    for member in members.scalars():
        actors.setdefault(
            member.role,
            ActorContext(
                actor_type="STAFF",
                actor_id=member.principal_id,
                shop_id=shop.id,
                surface="shop",
                roles=frozenset({member.role}),
                permissions=permissions.for_role(member.role),
                membership_id=member.id,
            ),
        )
    if "OWNER" not in actors:
        return None
    return shop.id, actors


async def _fake_telegram(db: AsyncSession, svc: MessagingServices, owner: ActorContext) -> ChannelAccount:
    assert owner.shop_id is not None
    current = await svc.channels.active(db, owner.shop_id, "TELEGRAM")
    if current is not None:
        return current
    account = ChannelAccount(
        shop_id=owner.shop_id,
        channel="TELEGRAM",
        status="PENDING",
        account_ref=secrets.token_urlsafe(32),
        external_account_id=FAKE_BOT_ID,
        display_name="@noutbukuz_demo_bot",  # soxtaligi — `is_fake` belgisi (UI tarjima qiladi)
        settings={"fake": True, "mode": "webhook"},  # token yo'q — polling ham, webhook ham ishlamaydi
        version=1,
    )
    db.add(account)
    await db.flush()
    await svc.channels._connected(db, owner, account)  # ulash yo'li bilan bir xil: USE, audit, hodisa
    return account


class _Telegram:
    """Soxta botga "xaridor yozdi" — webhook bilan bir xil yo'l (`InboundService.ingest`)."""

    def __init__(self, svc: MessagingServices, account: ChannelAccount) -> None:
        self.svc, self.account = svc, account

    async def say(self, db: AsyncSession, user: tuple[str, str, str], **message: Any) -> UUID:
        user_id, name, locale = user
        result = await self.svc.inbound.ingest(
            db,
            self.account,
            InboundMessage(
                provider_event_id=f"seed-{secrets.token_hex(8)}",
                event_kind="MESSAGE",
                external_user_id=user_id,
                occurred_at=utcnow(),
                display_name=name,
                language_code=locale,
                **message,
            ),
        )
        assert result.conversation_id is not None
        return result.conversation_id


async def _version(db: AsyncSession, conversation_id: UUID) -> int:
    return int(await db.scalar(select(Conversation.version).where(Conversation.id == conversation_id)) or 0)


async def _seed_noutbuk(
    db: AsyncSession, svc: MessagingServices, actors: dict[str, ActorContext], report: MessagingSeedReport
) -> None:
    owner = actors["OWNER"]
    manager = actors.get("MANAGER", owner)
    sales = actors.get("SALES", manager)
    bot = _Telegram(svc, await _fake_telegram(db, svc, owner))
    report.channels += 1

    # 1) Operator kutyapti: handoff vazifasi va xabarnoma (SALES + rahbarlar)
    jasur = ("910001", "Jasur Toshmatov", "uz")
    await bot.say(db, jasur, body="Assalomu alaykum! Lenovo IdeaPad 3 bormi? Narxi qancha?")

    # 2) Sotuvchi javob berdi — xaridor javobini kutyapti
    dilnoza = ("910002", "Дилноза", "ru")
    asked = await bot.say(db, dilnoza, body="Здравствуйте, ASUS TUF A15 есть в наличии?")
    await set_identity_context(db, shop_id=sales.shop_id, principal_id=sales.actor_id)
    await svc.inbox.reply(
        db,
        sales,
        asked,
        body="Здравствуйте! Да, есть в Ташкенте. Оформить заказ на самовывоз?",
        attachment_file_id=None,
        idempotency_key="seed-dilnoza-1",
    )
    await svc.inbox.set_tags(db, sales, asked, await _version(db, asked), ["ASUS"])

    # 3) Buyurtmasi bor xaridor: raqamini yubordi, menejer buyurtmaga bog'ladi va suhbatni yopdi
    gulnora = ("910003", "Gulnora Ismoilova", "uz")
    chat = await bot.say(db, gulnora, body="Salom, buyurtmam qachon tayyor bo'ladi?")
    await bot.say(db, gulnora, kind="CONTACT", contact_phone="+998977009988")
    await set_identity_context(db, shop_id=manager.shop_id, principal_id=manager.actor_id)
    await svc.inbox.reply(
        db,
        manager,
        chat,
        body="Assalomu alaykum! Buyurtmangiz tasdiqlangan, ertaga do'konda tayyor bo'ladi.",
        attachment_file_id=None,
        idempotency_key="seed-gulnora-1",
    )
    order_id = await db.scalar(
        select(Order.id).where(
            Order.shop_id == manager.shop_id,
            Order.customer_name == "Gulnora Ismoilova",
            Order.status == "CONFIRMED",
        )
    )
    if order_id is not None:
        await svc.inbox.link_order(db, manager, chat, order_id)
    await svc.inbox.add_note(db, manager, chat, "Ertaga ertalab qo'ng'iroq qilib eslatish kerak.")
    await svc.inbox.resolve(db, manager, chat, await _version(db, chat))
    report.conversations += 3


async def _seed_webchat(
    db: AsyncSession, svc: MessagingServices, owner: ActorContext, report: MessagingSeedReport
) -> None:
    """Sayt chatidan savol: mehmon yozdi, raqam qoldirdi, ega javob berdi va yopdi."""
    access = await svc.site.resolve(db, "noutbukuz")
    session = await svc.webchat.create_session(db, access)
    await svc.webchat.send(db, access, session.token, "seed-msg-0001", "HP 250 G10 ga kafolat necha oy?")
    await svc.webchat.contact(db, access, session.token, "Bekzod", "+998935556677")
    conversation_id = await db.scalar(
        select(Conversation.id)
        .join(WebchatSession, WebchatSession.customer_identity_id == Conversation.customer_identity_id)
        .where(WebchatSession.token_hash == sha256(session.token))
    )
    assert conversation_id is not None
    await set_identity_context(db, shop_id=owner.shop_id, principal_id=owner.actor_id)
    await svc.inbox.reply(
        db,
        owner,
        conversation_id,
        body="Assalomu alaykum! HP 250 G10 ga rasmiy kafolat 12 oy.",
        attachment_file_id=None,
        idempotency_key="seed-webchat-1",
    )
    await svc.inbox.resolve(db, owner, conversation_id, await _version(db, conversation_id))
    report.conversations += 1


async def _seed_shop(rt: WorkerRuntime, slug: str, report: MessagingSeedReport) -> None:
    svc: MessagingServices = rt.services.messaging
    async with rt.database.transaction() as db:
        found = await _actors(db, rt.services.permissions, slug)
        if found is None:
            return
        shop_id, actors = found
        owner = actors["OWNER"]
        await set_identity_context(db, shop_id=shop_id, principal_id=owner.actor_id)
        if await svc.channels.active(db, shop_id, "WEB_CHAT") is None:
            await svc.channels.enable_webchat(db, owner)
            report.channels += 1
        # Demo suhbatlar soxta bot bilan bir marta: bot bor (yoki ega haqiqiysini ulagan) — o'tkaziladi
        telegram = await db.scalar(
            select(func.count()).select_from(ChannelAccount).where(ChannelAccount.channel == "TELEGRAM")
        )
        if slug == "noutbukuz" and not telegram:
            await _seed_noutbuk(db, svc, actors, report)
            await _seed_webchat(db, svc, owner, report)


async def run_messaging_seed(settings: Settings) -> MessagingSeedReport:
    report = MessagingSeedReport()
    rt = build_runtime(settings, RecordingQueue())  # API bilan bir xil servislar (soxta kanal — tashqarisiz)
    try:
        for slug in WEBCHAT_SHOPS:
            await _seed_shop(rt, slug, report)
    finally:
        await rt.close()
    return report
