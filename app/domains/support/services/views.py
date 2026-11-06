"""Murojaat ko'rinishlari: ro'yxat qatori va kartochka (izohlar, rasmlar, ombor holati, tarix)."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.support.common import branch_names, member_names
from app.domains.support.models.orm import CaseAttachment, CaseNote, SupportCase
from app.domains.support.schemas import (
    CaseAttachmentOut,
    CaseDetail,
    CaseListItem,
    CaseMemberRef,
    CaseNoteOut,
    CaseStockOut,
    CaseTimelineItem,
)
from app.domains.support.state_machine import CASE
from app.platform.staff.models.orm import Principal
from app.platform.storage.services.file_service import FileService
from app.platform.use.models.orm import TransitionLog
from app.shared.contracts.support import SupportCommercePort
from app.shared.types.actor import ActorContext


def _ref(membership_id: UUID | None, names: dict[UUID, str]) -> CaseMemberRef | None:
    return (
        None
        if membership_id is None
        else CaseMemberRef(membership_id=membership_id, full_name=names.get(membership_id))
    )


class CaseViews:
    def __init__(self, files: FileService, commerce: SupportCommercePort) -> None:
        self.files = files
        self.commerce = commerce

    async def items(
        self, db: AsyncSession, actor: ActorContext, cases: Sequence[SupportCase]
    ) -> list[CaseListItem]:
        branches = await branch_names(db, actor.shop_id, (c.branch_id for c in cases))
        names = await member_names(
            db, actor.shop_id, (m for c in cases for m in (c.opened_by, c.assigned_membership_id))
        )
        return [self._item(c, branches, names) for c in cases]

    def _item(self, c: SupportCase, branches: dict[UUID, str], names: dict[UUID, str]) -> CaseListItem:
        return CaseListItem(**self._item_fields(c, branches, names))

    @staticmethod
    def _item_fields(c: SupportCase, branches: dict[UUID, str], names: dict[UUID, str]) -> dict[str, Any]:
        return {
            "id": c.id,
            "number": c.number,
            "type": c.type,
            "status": c.status,
            "source": c.source,
            "created_via": c.created_via,
            "branch_id": c.branch_id,
            "branch_name": branches.get(c.branch_id),
            "sku_id": c.sku_id,
            "title": c.title_snapshot,
            "sku_code": c.sku_code_snapshot,
            "qty": c.qty,
            "sold_at": c.sold_at,
            "warranty_months": c.warranty_months,
            "warranty_until": c.warranty_until,
            "within_warranty": c.within_warranty,
            "warranty_override_reason": c.warranty_override_reason,
            "problem_description": c.problem_description,
            "customer_name": c.customer_name,
            "conversation_id": c.conversation_id,
            "resolution": c.resolution,
            "outcome": c.outcome,
            "reject_reason": c.reject_reason,
            "item_received_at": c.item_received_at,
            "opened_by": _ref(c.opened_by, names),
            "assigned_to": _ref(c.assigned_membership_id, names),
            "created_at": c.created_at,
            "updated_at": c.updated_at,
            "version": c.version,
        }

    async def detail(self, db: AsyncSession, actor: ActorContext, case: SupportCase) -> CaseDetail:
        assert actor.shop_id is not None
        await db.refresh(case)  # `updated_at` / `version` UPDATE'dan keyin serverdan (expire bo'lgan)
        notes = list(
            (
                await db.execute(
                    select(CaseNote)
                    .where(CaseNote.shop_id == case.shop_id, CaseNote.case_id == case.id)
                    .order_by(CaseNote.created_at, CaseNote.id)
                )
            ).scalars()
        )
        attachments = list(
            (
                await db.execute(
                    select(CaseAttachment)
                    .where(CaseAttachment.shop_id == case.shop_id, CaseAttachment.case_id == case.id)
                    .order_by(CaseAttachment.created_at, CaseAttachment.id)
                )
            ).scalars()
        )
        transitions = list(
            (
                await db.execute(
                    select(TransitionLog)
                    .where(
                        TransitionLog.shop_id == case.shop_id,
                        TransitionLog.entity_type == CASE,
                        TransitionLog.entity_id == case.id,
                    )
                    .order_by(TransitionLog.occurred_at, TransitionLog.id)
                )
            ).scalars()
        )
        member_ids = [
            case.opened_by,
            case.assigned_membership_id,
            case.decided_by,
            case.resolved_by,
            case.closed_by,
            *(n.author_membership_id for n in notes),
            *(a.added_by for a in attachments),
        ]
        names = await member_names(db, actor.shop_id, member_ids)
        branches = await branch_names(db, actor.shop_id, [case.branch_id])
        principals = {t.actor_id for t in transitions if t.actor_id is not None}
        principal_names: dict[UUID, str] = {}
        if principals:
            found = await db.execute(
                select(Principal.id, Principal.full_name).where(Principal.id.in_(principals))
            )
            principal_names = {pid: name for pid, name in found}
        stored = await self.files.by_ids(db, case.shop_id, [a.file_id for a in attachments])
        attachment_out: list[CaseAttachmentOut] = []
        for a in attachments:
            file = stored.get(a.file_id)
            url, expires = self.files.url_for(file) if file is not None else (None, None)
            attachment_out.append(
                CaseAttachmentOut(
                    id=a.id,
                    file_id=a.file_id,
                    mime_type=file.mime_type if file is not None else None,
                    url=url,
                    url_expires_at=expires,
                    caption=a.caption,
                    source_message_id=a.source_message_id,
                    added_by=_ref(a.added_by, names),
                    created_at=a.created_at,
                )
            )
        timeline = [
            CaseTimelineItem(
                at=t.occurred_at,
                kind="TRANSITION",
                command=t.command,
                from_status=t.from_status,
                to_status=t.to_status,
                body=t.reason,
                actor_type=t.actor_type,
                actor_name=principal_names.get(t.actor_id) if t.actor_id else None,
            )
            for t in transitions
        ] + [
            CaseTimelineItem(
                at=n.created_at,
                kind="NOTE",
                note_kind=n.kind,
                body=n.body,
                actor_type="STAFF",
                actor_name=names.get(n.author_membership_id),
            )
            for n in notes
        ]
        timeline.sort(key=lambda item: item.at)
        stock = await self.commerce.case_stock(db, case.shop_id, case.id)
        return CaseDetail(
            **self._item_fields(case, branches, names),
            order_id=case.order_id,
            order_line_id=case.order_line_id,
            quick_sale_id=case.quick_sale_id,
            quick_sale_line_id=case.quick_sale_line_id,
            external_sale_ref=case.external_sale_ref,
            serial_number=case.serial_number,
            customer_phone=case.contact_phone_enc,
            customer_locale=case.customer_locale,
            diagnosed_at=case.diagnosed_at,
            replacement_sku_id=case.replacement_sku_id,
            decided_by=_ref(case.decided_by, names),
            decided_at=case.decided_at,
            decision_note=case.decision_note,
            service_started_at=case.service_started_at,
            refund_amount_minor=case.refund_amount_minor,
            resolved_at=case.resolved_at,
            resolved_by=_ref(case.resolved_by, names),
            closed_at=case.closed_at,
            closed_by=_ref(case.closed_by, names),
            stock=CaseStockOut(
                quarantined=stock.quarantined,
                restocked=stock.restocked,
                written_off=stock.written_off,
                replacement_issued=stock.replacement_issued,
            ),
            notes=[
                CaseNoteOut(
                    id=n.id,
                    kind=n.kind,
                    body=n.body,
                    author=_ref(n.author_membership_id, names),
                    created_at=n.created_at,
                )
                for n in notes
            ],
            attachments=attachment_out,
            timeline=timeline,
        )
