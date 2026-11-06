"""Panel: AI sozlamalari, holati va bilim bazasi (6b).

- Sozlamalar qatori birinchi o'qishda standart qiymatlar bilan yaratiladi (rejim OFF).
- Rejimni yoqish (OFF dan boshqa) — provayder sozlangan bo'lsa (M06 §10: "AI sozlanmagan").
- Profil o'zgarsa — yangi `agent_profile_versions` qatori (eski versiya saqlanadi, navbat izida versiya).
- Bilim bazasi: DRAFT → APPROVED (promptga kiradi) → RETIRED. APPROVED bandni tahrirlash uni yana DRAFT
  qiladi — qayta e'lon qilinmaguncha AI uni ko'rmaydi. Promptdagi umumiy hajm ~6k token (A5).
- Hamma o'zgarish audit jurnaliga (matnlarsiz — faqat maydon nomlari va rejim).
"""

from __future__ import annotations

import hashlib
from datetime import timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.sales_ai.common import DEFAULT_HANDOFF_RULES, DEFAULT_TOOLS
from app.domains.sales_ai.models.orm import (
    AgentProfileVersion,
    AgentSettings,
    AiFeedback,
    AiTurn,
    KnowledgeItem,
)
from app.domains.sales_ai.schemas import (
    ActiveHours,
    AgentProfileOut,
    AiSettingsOut,
    AiSettingsPatch,
    AiStatusOut,
    AutoReadiness,
    HandoffRules,
    KnowledgeIn,
    KnowledgeList,
    KnowledgeOut,
    KnowledgePatch,
    ReadinessCheck,
)
from app.domains.sales_ai.services.gate import AiGateService
from app.domains.sales_ai.services.sandbox import sandbox_cap_micros
from app.platform.audit.services.audit_service import AuditService
from app.platform.llm.models.orm import AiUsage
from app.platform.llm.usage import day_start, month_start, spent_since
from app.platform.shops.models.orm import Shop
from app.shared.clock import utcnow
from app.shared.errors.base import BusinessRuleError, InvalidTransitionError, NotFoundError
from app.shared.http import check_version
from app.shared.types.actor import ActorContext

SETTINGS = "sales_ai.agent_settings"
KNOWLEDGE = "sales_ai.knowledge_item"
KNOWLEDGE_LIMIT_CHARS = 24_000  # ~6k token (o'zbek/rus matnida ~4 belgi = 1 token)
READY_MIN_REVIEWED = 30
READY_MIN_ACCEPT_PCT = 70
READY_WINDOW = timedelta(days=30)


def _shop(actor: ActorContext) -> UUID:
    assert actor.shop_id is not None
    return actor.shop_id


class AiPanelService:
    def __init__(self, gate: AiGateService, audit: AuditService, models: dict[str, str]) -> None:
        self.gate = gate
        self.audit = audit
        self.models = models  # alias → asosiy model ID (panel uchun)

    # ------------------------------------------------------------------ sozlamalar
    async def ensure_settings(self, db: AsyncSession, shop_id: UUID) -> AgentSettings:
        await db.execute(
            insert(AgentSettings)
            .values(
                shop_id=shop_id, mode="OFF", allowed_tools=DEFAULT_TOOLS, handoff_rules=DEFAULT_HANDOFF_RULES
            )
            .on_conflict_do_nothing(index_elements=["shop_id"])
        )
        settings = await db.get(AgentSettings, shop_id, populate_existing=True)
        assert settings is not None
        return settings

    async def get_settings(self, db: AsyncSession, actor: ActorContext) -> AiSettingsOut:
        settings = await self.ensure_settings(db, _shop(actor))
        return await self._settings_out(db, settings)

    async def patch_settings(
        self, db: AsyncSession, actor: ActorContext, expected_version: int, body: AiSettingsPatch
    ) -> AiSettingsOut:
        shop_id = _shop(actor)
        settings = await self.ensure_settings(db, shop_id)
        check_version(settings.version, expected_version)
        fields = body.model_fields_set
        diff: dict[str, Any] = {}
        if "mode" in fields and body.mode is not None and body.mode != settings.mode:
            if body.mode != "OFF" and not self.gate.provider_ready:
                raise InvalidTransitionError(
                    "AI provider is not configured",
                    entity=SETTINGS,
                    **{"from": settings.mode},
                    command=f"SET_MODE_{body.mode}",
                    reason="AI_NOT_CONFIGURED",
                )
            diff["mode"] = {"old": settings.mode, "new": body.mode}
            settings.mode = body.mode
        simple = ("languages", "allowed_tools", "greeting_enabled")
        for name in simple:
            if name in fields and getattr(body, name) is not None:
                setattr(settings, name, getattr(body, name))
                diff[name] = {"changed": True}
        if "handoff_rules" in fields and body.handoff_rules is not None:
            settings.handoff_rules = body.handoff_rules.model_dump()
            diff["handoff_rules"] = {"changed": True}
        if "active_hours" in fields:
            settings.active_hours = body.active_hours.model_dump() if body.active_hours else None
            diff["active_hours"] = {"changed": True}
        for name in ("daily_cost_cap_minor", "monthly_cost_cap_minor"):
            if name in fields and getattr(body, name) != getattr(settings, name):
                old = getattr(settings, name)
                new = getattr(body, name)
                setattr(settings, name, new)
                diff[name] = {"old": old, "new": new}
                raised = new is None or (old is not None and new > old)
                if raised:  # faqat limit oshirilsa (yoki olib tashlansa) pauza bekor bo'ladi (F-21)
                    settings.paused_until = settings.paused_reason = None
        if "kill_switch" in fields and body.kill_switch is not None:
            if body.kill_switch and settings.kill_switch_at is None:
                settings.kill_switch_at = utcnow()
                settings.kill_switch_reason = body.kill_switch_reason
            elif not body.kill_switch:
                settings.kill_switch_at = settings.kill_switch_reason = None
            diff["kill_switch"] = {"new": body.kill_switch}
        if "profile" in fields and body.profile is not None:
            profile = await self._new_profile(db, actor, settings, body)
            if profile is not None:
                settings.active_profile_version_id = profile.id
                diff["profile_version"] = {"new": profile.version}
        if diff:
            settings.updated_by = actor.membership_id
            await db.flush()
            await db.refresh(settings)  # updated_at (onupdate) va version
            await self.audit.record(
                db,
                action="sales_ai.settings.updated",
                entity_type=SETTINGS,
                entity_id=shop_id,
                actor=actor,
                entity_version=settings.version,
                diff=diff,
            )
        return await self._settings_out(db, settings)

    async def _new_profile(
        self, db: AsyncSession, actor: ActorContext, settings: AgentSettings, body: AiSettingsPatch
    ) -> AgentProfileVersion | None:
        assert body.profile is not None
        data = body.profile.model_dump()
        content_hash = hashlib.sha256(repr(sorted(data.items())).encode()).hexdigest()
        if settings.active_profile_version_id is not None:
            current = await db.get(AgentProfileVersion, settings.active_profile_version_id)
            if current is not None and current.content_hash == content_hash:
                return None
            if current is not None:
                current.status = "RETIRED"
        latest = await db.scalar(
            select(func.max(AgentProfileVersion.version)).where(
                AgentProfileVersion.shop_id == settings.shop_id
            )
        )
        profile = AgentProfileVersion(
            shop_id=settings.shop_id,
            version=int(latest or 0) + 1,
            status="ACTIVE",
            content_hash=content_hash,
            approved_by=actor.membership_id,
            approved_at=utcnow(),
            created_by=actor.membership_id,
            **data,
        )
        db.add(profile)
        await db.flush()
        return profile

    async def _settings_out(self, db: AsyncSession, settings: AgentSettings) -> AiSettingsOut:
        profile = (
            await db.get(AgentProfileVersion, settings.active_profile_version_id)
            if settings.active_profile_version_id
            else None
        )
        rules = {**DEFAULT_HANDOFF_RULES, **(settings.handoff_rules or {})}
        return AiSettingsOut(
            mode=settings.mode,
            languages=settings.languages,
            allowed_tools=settings.allowed_tools,
            handoff_rules=HandoffRules.model_validate(rules),
            active_hours=ActiveHours.model_validate(settings.active_hours) if settings.active_hours else None,
            daily_cost_cap_minor=settings.daily_cost_cap_minor,
            monthly_cost_cap_minor=settings.monthly_cost_cap_minor,
            greeting_enabled=settings.greeting_enabled,
            kill_switch_active=settings.kill_switch_at is not None,
            kill_switch_reason=settings.kill_switch_reason,
            paused_until=settings.paused_until
            if settings.paused_until and settings.paused_until > utcnow()
            else None,
            paused_reason=settings.paused_reason,
            profile=(
                AgentProfileOut(
                    version=profile.version,
                    shop_display_name=profile.shop_display_name,
                    tone=profile.tone,
                    about_text=profile.about_text,
                    extra_instructions=profile.extra_instructions,
                )
                if profile
                else None
            ),
            provider=self.gate.status.provider,
            provider_configured=self.gate.provider_ready,
            auto_readiness=await self.readiness(db, settings),
            version=settings.version,
            updated_at=settings.updated_at,
        )

    async def readiness(self, db: AsyncSession, settings: AgentSettings) -> AutoReadiness:
        since = utcnow() - READY_WINDOW
        published = await db.scalar(
            select(func.count()).where(
                KnowledgeItem.shop_id == settings.shop_id, KnowledgeItem.status == "APPROVED"
            )
        )
        rows = (
            await db.execute(
                select(AiFeedback.verdict, func.count())
                .where(AiFeedback.shop_id == settings.shop_id, AiFeedback.created_at >= since)
                .group_by(AiFeedback.verdict)
            )
        ).all()
        counts = {str(verdict): int(n) for verdict, n in rows}
        reviewed = sum(counts.get(v, 0) for v in ("SENT_AS_IS", "EDITED", "REJECTED"))
        accept = round(100 * counts.get("SENT_AS_IS", 0) / reviewed) if reviewed else 0
        checks = [
            ReadinessCheck(code="PROVIDER_CONFIGURED", ok=self.gate.provider_ready),
            ReadinessCheck(code="PROFILE_SET", ok=settings.active_profile_version_id is not None),
            ReadinessCheck(
                code="KNOWLEDGE_PUBLISHED", ok=bool(published), value=int(published or 0), required=1
            ),
            ReadinessCheck(
                code="SUGGEST_REVIEWED",
                ok=reviewed >= READY_MIN_REVIEWED,
                value=reviewed,
                required=READY_MIN_REVIEWED,
            ),
            ReadinessCheck(
                code="SUGGEST_ACCEPTANCE",
                ok=reviewed >= READY_MIN_REVIEWED and accept >= READY_MIN_ACCEPT_PCT,
                value=accept,
                required=READY_MIN_ACCEPT_PCT,
            ),
        ]
        return AutoReadiness(ready=all(c.ok for c in checks), checks=checks)

    # ------------------------------------------------------------------ holat
    async def status(self, db: AsyncSession, actor: ActorContext) -> AiStatusOut:
        shop_id = _shop(actor)
        settings = await db.get(AgentSettings, shop_id)
        gate = await self.gate.gate_for(db, shop_id, settings)
        now = utcnow()
        today = day_start(now)
        rows = (
            await db.execute(
                select(AiTurn.outcome, func.count(), func.count(func.distinct(AiTurn.conversation_id)))
                .where(AiTurn.shop_id == shop_id, AiTurn.created_at >= today)
                .group_by(AiTurn.outcome)
            )
        ).all()
        by_outcome = {str(outcome): int(n) for outcome, n, _ in rows}
        conversations = await db.scalar(
            select(func.count(func.distinct(AiTurn.conversation_id))).where(
                AiTurn.shop_id == shop_id, AiTurn.created_at >= today
            )
        )
        today_cost, _, _ = await spent_since(db, shop_id, today)
        month_cost, _, _ = await spent_since(db, shop_id, month_start(now))
        sandbox_cost, _, _ = await spent_since(db, shop_id, today, only=("SANDBOX",))
        price_unknown = bool(
            await db.scalar(
                select(func.count()).where(
                    AiUsage.shop_id == shop_id, AiUsage.occurred_at >= today, AiUsage.price_unknown.is_(True)
                )
            )
        )
        return AiStatusOut(
            provider=self.gate.status.provider,
            provider_configured=self.gate.provider_ready,
            model=self.models.get("seller"),
            mode=gate.mode,
            effective_mode=gate.mode if gate.active else "OFF",
            pause_reason=None if gate.active else gate.reason,
            paused_until=settings.paused_until if settings and gate.reason == "BUDGET_EXCEEDED" else None,
            today_conversations=int(conversations or 0),
            today_replies=by_outcome.get("REPLY_QUEUED", 0),
            today_suggestions=by_outcome.get("SUGGESTED", 0),
            today_handoffs=by_outcome.get("HANDOFF", 0) + by_outcome.get("ERROR", 0),
            today_cost_micros=today_cost,
            month_cost_micros=month_cost,
            daily_cost_cap_minor=settings.daily_cost_cap_minor if settings else None,
            monthly_cost_cap_minor=settings.monthly_cost_cap_minor if settings else None,
            price_unknown=price_unknown,
            sandbox_today_cost_micros=sandbox_cost,
            sandbox_daily_cap_micros=sandbox_cap_micros(settings),
        )

    # ------------------------------------------------------------------ bilim bazasi
    async def list_knowledge(self, db: AsyncSession, actor: ActorContext) -> KnowledgeList:
        shop_id = _shop(actor)
        rows = (
            await db.execute(
                select(KnowledgeItem)
                .where(KnowledgeItem.shop_id == shop_id, KnowledgeItem.status != "RETIRED")
                .order_by(KnowledgeItem.kind, KnowledgeItem.created_at)
            )
        ).scalars()
        items = [_knowledge_out(r) for r in rows]
        return KnowledgeList(
            items=items,
            published_chars=await self._published_chars(db, shop_id),
            limit_chars=KNOWLEDGE_LIMIT_CHARS,
        )

    async def create_knowledge(
        self, db: AsyncSession, actor: ActorContext, body: KnowledgeIn
    ) -> KnowledgeOut:
        item = KnowledgeItem(
            shop_id=_shop(actor), created_by=actor.membership_id, status="DRAFT", **body.model_dump()
        )
        db.add(item)
        await db.flush()
        await db.refresh(item)
        await self._audit_knowledge(db, actor, item, "created")
        return _knowledge_out(item)

    async def update_knowledge(
        self,
        db: AsyncSession,
        actor: ActorContext,
        item_id: UUID,
        expected_version: int,
        body: KnowledgePatch,
    ) -> KnowledgeOut:
        item = await self._knowledge(db, actor, item_id)
        check_version(item.version, expected_version)
        if item.status == "RETIRED":
            raise _knowledge_transition(item, "EDIT")
        changed = False
        for name in body.model_fields_set:
            value = getattr(body, name)
            if value is not None and value != getattr(item, name):
                setattr(item, name, value)
                changed = True
        if not changed:  # bo'sh yoki o'zgarishsiz PATCH bandni e'londan olib tashlamaydi (F-26)
            return _knowledge_out(item)
        item.status, item.approved_by, item.approved_at = "DRAFT", None, None
        item.version += 1
        await db.flush()
        await self._audit_knowledge(db, actor, item, "updated")
        return _knowledge_out(item)

    async def publish_knowledge(
        self, db: AsyncSession, actor: ActorContext, item_id: UUID, expected_version: int | None = None
    ) -> KnowledgeOut:
        # shop darajasidagi qulf: parallel e'lonlar chegaradan oshirmaydi (F-14)
        await db.execute(
            select(func.pg_advisory_xact_lock(func.hashtextextended(f"sales_ai.knowledge:{_shop(actor)}", 0)))
        )
        item = await self._knowledge(db, actor, item_id)
        if expected_version is not None:
            check_version(item.version, expected_version)
        if item.status != "DRAFT":
            raise _knowledge_transition(item, "PUBLISH")
        used = await self._published_chars(db, item.shop_id)
        if used + len(item.title) + len(item.body) > KNOWLEDGE_LIMIT_CHARS:
            raise BusinessRuleError(
                "Knowledge base limit reached",
                reason="KNOWLEDGE_LIMIT",
                used=used,
                limit=KNOWLEDGE_LIMIT_CHARS,
            )
        item.status, item.approved_by, item.approved_at = "APPROVED", actor.membership_id, utcnow()
        item.version += 1
        await db.flush()
        await self._audit_knowledge(db, actor, item, "published")
        return _knowledge_out(item)

    async def retire_knowledge(
        self, db: AsyncSession, actor: ActorContext, item_id: UUID, expected_version: int | None = None
    ) -> KnowledgeOut:
        item = await self._knowledge(db, actor, item_id)
        if expected_version is not None:
            check_version(item.version, expected_version)
        if item.status == "RETIRED":
            raise _knowledge_transition(item, "RETIRE")
        item.status = "RETIRED"
        item.version += 1
        await db.flush()
        await self._audit_knowledge(db, actor, item, "retired")
        return _knowledge_out(item)

    async def _knowledge(self, db: AsyncSession, actor: ActorContext, item_id: UUID) -> KnowledgeItem:
        item = (
            await db.execute(
                select(KnowledgeItem)
                .where(KnowledgeItem.shop_id == _shop(actor), KnowledgeItem.id == item_id)
                .with_for_update()
            )
        ).scalar_one_or_none()
        if item is None:
            raise NotFoundError("Knowledge item not found")
        return item

    async def _published_chars(self, db: AsyncSession, shop_id: UUID) -> int:
        used = await db.scalar(
            select(
                func.coalesce(
                    func.sum(func.char_length(KnowledgeItem.title) + func.char_length(KnowledgeItem.body)), 0
                )
            ).where(KnowledgeItem.shop_id == shop_id, KnowledgeItem.status == "APPROVED")
        )
        return int(used or 0)

    async def _audit_knowledge(
        self, db: AsyncSession, actor: ActorContext, item: KnowledgeItem, verb: str
    ) -> None:
        await self.audit.record(
            db,
            action=f"sales_ai.knowledge.{verb}",
            entity_type=KNOWLEDGE,
            entity_id=item.id,
            actor=actor,
            entity_version=item.version,
            diff={"status": {"new": item.status}, "kind": {"new": item.kind}},
        )


def _knowledge_transition(item: KnowledgeItem, command: str) -> InvalidTransitionError:
    return InvalidTransitionError(
        "Knowledge item cannot change", entity=KNOWLEDGE, **{"from": item.status}, command=command
    )


def _knowledge_out(item: KnowledgeItem) -> KnowledgeOut:
    return KnowledgeOut(
        id=item.id,
        kind=item.kind,
        locale=item.locale,
        title=item.title,
        body=item.body,
        status=item.status,
        version=item.version,
        approved_at=item.approved_at,
        created_at=item.created_at,
    )


async def shop_name(db: AsyncSession, shop_id: UUID) -> str:
    shop = await db.get(Shop, shop_id)
    return shop.name if shop else "Shop"
