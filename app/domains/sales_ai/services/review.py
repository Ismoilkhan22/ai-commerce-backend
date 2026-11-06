"""SUGGEST takliflari (operator yuboradi / tahrirlaydi / rad etadi → `ai_feedback`) va navbat izi (6b).

- Taklif matni bazada redact holatida; operatorga ko'rsatishda va yuborishda `[PHONE_1]` qayta tiklanadi
  (karta raqami — hech qachon). Tahrirlangan matn operatorniki — o'zgartirilmasdan yuboriladi.
- Yuborish `AiConversationPort.send_suggestion` orqali: suhbat hamon AI navbatida va versiya o'zgarmagan
  bo'lishi kerak (aks holda 409 — taklif eskirgan).
- Navbat izi (`/ai/turns`) — redact matn, tool argumentlari va natijalari faqat ID va kod bilan.
"""

from __future__ import annotations

import difflib
from collections.abc import Sequence
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.sales_ai.common import emit
from app.domains.sales_ai.models.orm import AiFeedback, AiToolExecution, AiTurn
from app.domains.sales_ai.schemas import (
    DraftLinkOut,
    SuggestionDiscardIn,
    SuggestionList,
    SuggestionOut,
    SuggestionSendIn,
    SuggestionSentOut,
    ToolCallOut,
    TurnList,
    TurnOut,
)
from app.platform.llm.redaction import DbPiiStore, restore
from app.shared.contracts.messaging import AiConversationPort
from app.shared.errors.base import InvalidTransitionError, NotFoundError
from app.shared.types.actor import ActorContext

TURN_LIMIT = 50


def drafts_of(executions: Sequence[AiToolExecution]) -> list[DraftLinkOut]:
    out: list[DraftLinkOut] = []
    for e in executions:
        draft = (e.result_summary or {}).get("draft")
        if isinstance(draft, dict) and draft.get("id"):
            out.append(
                DraftLinkOut(kind=draft["kind"], id=UUID(str(draft["id"])), label=str(draft.get("label")))
            )
    return out


def turn_out(turn: AiTurn, executions: Sequence[AiToolExecution]) -> TurnOut:
    return TurnOut(
        id=turn.id,
        conversation_id=turn.conversation_id,
        mode=turn.mode,
        status=turn.status,
        outcome=turn.outcome,
        handoff_reason=turn.handoff_reason,
        reply_text=turn.reply_text_enc,
        reply_locale=turn.reply_locale,
        suggestion_status=turn.suggestion_status,
        provider=turn.provider,
        model=turn.model_id,
        fallback_used=bool(turn.fallback_used),
        prompt_version=turn.prompt_version,
        tokens_in=turn.tokens_in or 0,
        tokens_out=turn.tokens_out or 0,
        cache_read_tokens=turn.cache_read_tokens or 0,
        cost_micros=turn.cost_micros or 0,
        latency_ms=turn.latency_ms,
        validator_codes=list(turn.validator_codes or []),
        rewrite_count=turn.rewrite_count or 0,
        error_code=turn.error_code,
        tool_calls=[
            ToolCallOut(
                seq=e.seq,
                tool=e.tool,
                decision=e.decision,
                input=e.args_redacted,
                output=e.result_summary,
                error_code=e.error_code,
                latency_ms=e.latency_ms,
            )
            for e in executions
        ],
        drafts=drafts_of(executions),
        created_at=turn.created_at,
    )


def edit_pct(original: str, edited: str) -> int:
    return round(100 * (1 - difflib.SequenceMatcher(None, original, edited).ratio()))


class AiReviewService:
    def __init__(self, conversations: AiConversationPort) -> None:
        self.conversations = conversations

    async def turns(self, db: AsyncSession, actor: ActorContext, conversation_id: UUID) -> TurnList:
        assert actor.shop_id is not None
        await self.conversations.ensure_visible(db, actor, conversation_id)
        turns = list(
            (
                await db.execute(
                    select(AiTurn)
                    .where(AiTurn.shop_id == actor.shop_id, AiTurn.conversation_id == conversation_id)
                    .order_by(AiTurn.created_at.desc())
                    .limit(TURN_LIMIT)
                )
            ).scalars()
        )
        executions = await self._executions(db, actor.shop_id, [t.id for t in turns])
        return TurnList(items=[turn_out(t, executions.get(t.id, [])) for t in turns])

    async def suggestions(
        self, db: AsyncSession, actor: ActorContext, conversation_id: UUID
    ) -> SuggestionList:
        assert actor.shop_id is not None
        speaker_version = await self.conversations.ensure_visible(db, actor, conversation_id)
        turns = (
            await db.execute(
                select(AiTurn)
                .where(
                    AiTurn.shop_id == actor.shop_id,
                    AiTurn.conversation_id == conversation_id,
                    AiTurn.suggestion_status == "PENDING",
                )
                .order_by(AiTurn.created_at.desc())
                .limit(5)
            )
        ).scalars()
        store = DbPiiStore(db, actor.shop_id, conversation_id)
        context = await self.conversations.context(db, actor.shop_id, conversation_id, limit=1)
        latest_in = context.latest_inbound_seq if context else 0
        status = context.status if context else None
        items = [
            SuggestionOut(
                reply_id=t.id,
                conversation_id=conversation_id,
                body=await restore(store, t.reply_text_enc or ""),
                created_at=t.created_at,
                stale=t.speaker_version != speaker_version
                or t.trigger_seq < latest_in
                or status != "AI_ACTIVE",
                handoff_reason=t.handoff_reason,
                validator_codes=list(t.validator_codes or []),
            )
            for t in turns
        ]
        return SuggestionList(items=items)

    async def send(
        self,
        db: AsyncSession,
        actor: ActorContext,
        conversation_id: UUID,
        reply_id: UUID,
        body: SuggestionSendIn,
    ) -> SuggestionSentOut:
        assert actor.shop_id is not None and actor.membership_id is not None
        turn = await self._pending(db, actor, conversation_id, reply_id)
        context = await self.conversations.context(db, actor.shop_id, conversation_id, limit=1)
        if context is not None and context.latest_inbound_seq > turn.trigger_seq:
            # xaridor yangi xabar yozgan — eski savolga javob yuborilmaydi (F-18)
            raise InvalidTransitionError(
                "AI suggestion is stale",
                entity="sales_ai.suggestion",
                **{"from": "PENDING"},
                command="SEND",
                reason="stale",
            )
        original = await restore(DbPiiStore(db, actor.shop_id, conversation_id), turn.reply_text_enc or "")
        text = body.body if body.body is not None else original
        verdict = "SENT_AS_IS" if text.strip() == original.strip() else "EDITED"
        message_id = await self.conversations.send_suggestion(
            db, actor, conversation_id, body=text, ai_reply_id=turn.id, speaker_version=turn.speaker_version
        )
        turn.suggestion_status, turn.sent_message_id = "SENT", message_id
        await self._feedback(
            db,
            actor,
            turn,
            verdict=verdict,
            sent_message_id=message_id,
            edit_distance_pct=0 if verdict == "SENT_AS_IS" else edit_pct(original, text),
        )
        await self._signal(db, turn, "SENT")
        return SuggestionSentOut(reply_id=turn.id, message_id=message_id, verdict=verdict)

    async def discard(
        self,
        db: AsyncSession,
        actor: ActorContext,
        conversation_id: UUID,
        reply_id: UUID,
        body: SuggestionDiscardIn,
    ) -> None:
        turn = await self._pending(db, actor, conversation_id, reply_id)
        turn.suggestion_status = "DISCARDED"
        await self._feedback(
            db, actor, turn, verdict="REJECTED", error_tags=body.error_tags, comment=body.comment
        )
        await self._signal(db, turn, "DISCARDED")

    # ------------------------------------------------------------------ ichki
    async def _pending(
        self, db: AsyncSession, actor: ActorContext, conversation_id: UUID, reply_id: UUID
    ) -> AiTurn:
        assert actor.shop_id is not None
        await self.conversations.ensure_visible(db, actor, conversation_id)
        turn = (
            await db.execute(
                select(AiTurn)
                .where(
                    AiTurn.shop_id == actor.shop_id,
                    AiTurn.conversation_id == conversation_id,
                    AiTurn.id == reply_id,
                    AiTurn.suggestion_status.is_not(None),
                )
                .with_for_update()
            )
        ).scalar_one_or_none()
        if turn is None:
            raise NotFoundError("AI suggestion not found")
        if turn.suggestion_status != "PENDING":
            raise InvalidTransitionError(
                "AI suggestion was already handled",
                entity="sales_ai.suggestion",
                **{"from": turn.suggestion_status},
                command="REVIEW",
            )
        return turn

    async def _feedback(self, db: AsyncSession, actor: ActorContext, turn: AiTurn, **fields: Any) -> None:
        assert actor.membership_id is not None
        await db.execute(
            insert(AiFeedback)
            .values(shop_id=turn.shop_id, turn_id=turn.id, membership_id=actor.membership_id, **fields)
            .on_conflict_do_nothing(index_elements=["shop_id", "turn_id", "membership_id"])
        )

    async def _signal(self, db: AsyncSession, turn: AiTurn, status: str) -> None:
        await emit(
            db,
            turn.shop_id,
            "sales_ai.suggestion.reviewed",
            turn_id=turn.id,
            conversation_id=turn.conversation_id,
            suggestion_status=status,
        )

    async def _executions(
        self, db: AsyncSession, shop_id: UUID, turn_ids: list[UUID]
    ) -> dict[UUID, list[AiToolExecution]]:
        if not turn_ids:
            return {}
        rows = (
            await db.execute(
                select(AiToolExecution)
                .where(AiToolExecution.shop_id == shop_id, AiToolExecution.turn_id.in_(turn_ids))
                .order_by(AiToolExecution.turn_id, AiToolExecution.seq)
            )
        ).scalars()
        out: dict[UUID, list[AiToolExecution]] = {}
        for row in rows:
            out.setdefault(row.turn_id, []).append(row)
        return out
