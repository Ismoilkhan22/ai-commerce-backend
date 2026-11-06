"""Kafolat murojaatini ochish, ko'rish, ro'yxat, izoh, rasm, qabul va mas'ul (7b, DEC-145).

Kafolat muddati — sotuv qatoridagi `warranty_months` nusxasi (BL-057), katalog emas. Muddat tugagan sotuvga
murojaat ochilmaydi (422 `WARRANTY_EXPIRED`); menejer/ega sabab bilan ochishi mumkin. Xaridor telefoni —
shifrlangan ustunda + HMAC; log, audit va event'ga tushmaydi.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.support import permissions as perm
from app.domains.support.common import (
    MAX_ATTACHMENTS,
    ensure_branch_scope,
    field,
    in_branch_scope,
    load_branch,
    make_cursor,
    read_cursor,
    shop_zone,
    warranty_window,
)
from app.domains.support.events import OPENED, UPDATED, case_event
from app.domains.support.models.orm import OPEN_STATUSES, CaseAttachment, CaseNote, SupportCase
from app.domains.support.schemas import (
    CaseAssignIn,
    CaseAttachmentIn,
    CaseDetail,
    CaseList,
    CaseNoteIn,
    CaseOpenIn,
    CaseReceiveItemIn,
)
from app.domains.support.services.views import CaseViews
from app.domains.support.state_machine import CASE
from app.platform.audit.services.audit_service import AuditService
from app.platform.notifications.services.notifications import NotificationService
from app.platform.notifications.services.tasks import SUPPORT_CASE_DECISION, TaskService
from app.platform.staff.models.orm import Membership
from app.platform.storage.services.file_service import FileService
from app.shared.clock import utcnow
from app.shared.contracts.catalog import CatalogQueryPort
from app.shared.contracts.messaging import ConversationLookupPort
from app.shared.contracts.support import SaleLine, SupportCommercePort
from app.shared.db.encryption import search_hmac
from app.shared.errors.base import ForbiddenError, NotFoundError, ValidationError, WarrantyExpiredError
from app.shared.http import check_version
from app.shared.pagination import DEFAULT_LIMIT
from app.shared.phone import normalize_phone
from app.shared.types.actor import ActorContext

SEARCH_FILE_PURPOSE = "SUPPORT_EVIDENCE"
_ORDER_REFS = ("order_id", "order_line_id")
_QUICK_REFS = ("quick_sale_id", "quick_sale_line_id")


async def next_number(db: AsyncSession, shop_id: UUID) -> int:
    """Shop ichida ketma-ket murojaat raqami. Qator qulflanadi: bir shopda ochish ketma-ket (qty yig'indisi
    tekshiruvi ham shu qulf ostida)."""
    number = (
        await db.execute(
            text(
                "INSERT INTO support.case_counters AS c (shop_id, last_number) VALUES (:shop_id, 1) "
                "ON CONFLICT (shop_id) DO UPDATE SET last_number = c.last_number + 1 "
                "RETURNING last_number"
            ),
            {"shop_id": shop_id},
        )
    ).scalar_one()
    return int(number)


class CaseService:
    def __init__(
        self,
        audit: AuditService,
        files: FileService,
        catalog: CatalogQueryPort,
        conversations: ConversationLookupPort,
        commerce: SupportCommercePort,
        views: CaseViews,
    ) -> None:
        self.audit = audit
        self.files = files
        self.catalog = catalog
        self.conversations = conversations
        self.commerce = commerce
        self.views = views
        self.tasks = TaskService()
        self.notifications = NotificationService()

    # ================================================================== o'qish
    async def load(
        self, db: AsyncSession, actor: ActorContext, case_id: UUID, *, for_update: bool = False
    ) -> SupportCase:
        query = select(SupportCase).where(SupportCase.id == case_id, SupportCase.shop_id == actor.shop_id)
        case = (await db.execute(query.with_for_update() if for_update else query)).scalar_one_or_none()
        if case is None or not in_branch_scope(actor, case.branch_id):
            raise NotFoundError("Case not found")  # boshqa shop yoki doiradan tashqari filial — bir xil javob
        return case

    async def get(self, db: AsyncSession, actor: ActorContext, case_id: UUID) -> CaseDetail:
        return await self.views.detail(db, actor, await self.load(db, actor, case_id))

    async def list_cases(
        self,
        db: AsyncSession,
        actor: ActorContext,
        *,
        status: list[str] | None,
        resolution: str | None,
        branch_id: UUID | None,
        source: str | None,
        assigned: str | None,
        q: str | None,
        sku_id: UUID | None,
        number: int | None,
        limit: int,
        cursor: str | None,
    ) -> CaseList:
        limit = max(1, min(limit or DEFAULT_LIMIT, 200))
        query = select(SupportCase).where(SupportCase.shop_id == actor.shop_id)
        if actor.branch_ids is not None:
            query = query.where(SupportCase.branch_id.in_(actor.branch_ids))
        if status:
            query = query.where(SupportCase.status.in_(status))
        if resolution:
            query = query.where(SupportCase.resolution == resolution)
        if branch_id:
            query = query.where(SupportCase.branch_id == branch_id)
        if source:
            query = query.where(SupportCase.source == source)
        if sku_id:
            query = query.where(SupportCase.sku_id == sku_id)
        if number:
            query = query.where(SupportCase.number == number)
        if assigned == "me":
            query = query.where(SupportCase.assigned_membership_id == actor.membership_id)
        elif assigned == "unassigned":
            query = query.where(SupportCase.assigned_membership_id.is_(None))
        elif assigned:
            query = query.where(SupportCase.assigned_membership_id == _uuid(assigned, "assigned"))
        if q:
            query = query.where(self._search(q))
        if cursor:
            moment, ident = read_cursor(cursor)
            query = query.where(
                or_(
                    SupportCase.created_at < moment,
                    (SupportCase.created_at == moment) & (SupportCase.id < ident),
                )
            )
        rows = list(
            (
                await db.execute(
                    query.order_by(SupportCase.created_at.desc(), SupportCase.id.desc()).limit(limit + 1)
                )
            ).scalars()
        )
        has_more = len(rows) > limit
        page = rows[:limit]
        return CaseList(
            items=await self.views.items(db, actor, page),
            next_cursor=make_cursor(page[-1].created_at, page[-1].id) if has_more and page else None,
            has_more=has_more,
        )

    @staticmethod
    def _search(q: str) -> Any:
        """Raqam ("K-12" yoki "12"), telefon (HMAC bo'yicha aniq) yoki xaridor ismi/mahsulot nomi."""
        raw = q.strip()
        like = f"%{raw.replace('%', r'\%').replace('_', r'\_')}%"
        conditions: list[Any] = [
            SupportCase.title_snapshot.ilike(like),
            SupportCase.customer_name.ilike(like),
        ]
        digits = raw.upper().removeprefix("K-").removeprefix("K").strip("- ")
        if digits.isdigit() and len(digits) <= 9:
            conditions.append(SupportCase.number == int(digits))
        try:
            conditions.append(SupportCase.contact_phone_hmac == search_hmac(normalize_phone(raw)))
        except ValidationError:
            pass  # telefon emas — matn qidiruvi
        return or_(*conditions)

    # ================================================================== ochish
    async def open(self, db: AsyncSession, actor: ActorContext, data: CaseOpenIn) -> CaseDetail:
        assert actor.shop_id is not None and actor.membership_id is not None
        override = data.warranty_override_reason
        if override and perm.CASE_DECIDE not in actor.permissions:
            raise ForbiddenError(
                "Only a manager or owner may override the warranty", permission=perm.CASE_DECIDE
            )
        number = await next_number(db, actor.shop_id)  # qulf: shu shopda ochish ketma-ket
        sale = await self._sale_line(db, actor, data)
        title, sku_id, product_id, sku_code, branch_id, sold_at, months, line_qty = await self._basis(
            db, actor, data, sale
        )
        await self._check_qty(db, actor, data, line_qty)

        zone = await shop_zone(db, actor.shop_id)
        now = utcnow()
        until, within = warranty_window(sold_at, months, zone, now)
        if data.type == "WARRANTY" and not within and not override:
            raise WarrantyExpiredError(
                "Warranty period has expired",
                warranty_until=until.isoformat() if until else None,
                warranty_months=months,
            )

        phone = normalize_phone(data.customer_phone, "customer_phone") if data.customer_phone else None
        phone = phone or (sale.customer_phone if sale else None)
        conversation_id = data.conversation_id or (sale.conversation_id if sale else None)
        if data.conversation_id is not None and not await self.conversations.conversation_exists(
            db, actor.shop_id, data.conversation_id
        ):
            raise ValidationError("Conversation not found", fields=[field("conversation_id", "invalid")])
        locale = data.customer_locale or (sale.customer_locale if sale else None) or "uz"

        case = SupportCase(
            shop_id=actor.shop_id,
            number=number,
            type=data.type,
            status="NEW",
            created_via=data.created_via,
            source=data.source,
            order_id=data.order_id,
            order_line_id=data.order_line_id,
            quick_sale_id=data.quick_sale_id,
            quick_sale_line_id=data.quick_sale_line_id,
            external_sale_ref=data.external_sale_ref,
            branch_id=branch_id,
            sku_id=sku_id,
            product_id=product_id,
            title_snapshot=title,
            sku_code_snapshot=sku_code,
            qty=data.qty,
            serial_number=data.serial_number,
            sold_at=sold_at,
            warranty_months=months,
            warranty_until=until,
            within_warranty=within,
            warranty_override_reason=override if (data.type == "WARRANTY" and not within) else None,
            warranty_override_by=actor.membership_id
            if (override and data.type == "WARRANTY" and not within)
            else None,
            problem_description=data.problem_description,
            customer_name=data.customer_name or (sale.customer_name if sale else None),
            contact_phone_enc=phone,
            contact_phone_hmac=search_hmac(phone) if phone else None,
            customer_identity_id=sale.customer_ref if sale else None,
            conversation_id=conversation_id,
            customer_locale=locale,
            opened_by=actor.membership_id,
        )
        db.add(case)
        await db.flush()
        await self.audit.record(
            db,
            action="support.case.opened",
            entity_type=CASE,
            entity_id=case.id,
            actor=actor,
            entity_version=case.version,
            reason=case.warranty_override_reason,
            # Faqat kodlar va sonlar: ism, telefon, muammo matni yo'q (26 §4)
            diff={
                "number": case.number,
                "source": case.source,
                "type": case.type,
                "within_warranty": within,
                "qty": case.qty,
            },
        )
        await case_event(db, actor, case, OPENED, created_via=case.created_via)
        await self._notify_opened(db, actor, case)
        return await self.views.detail(db, actor, case)

    async def _sale_line(self, db: AsyncSession, actor: ActorContext, data: CaseOpenIn) -> SaleLine | None:
        assert actor.shop_id is not None
        given = {name: getattr(data, name) for name in (*_ORDER_REFS, *_QUICK_REFS)}
        if data.source == "EXTERNAL":
            extra = [name for name, value in given.items() if value is not None]
            problems = [field(name, "not_allowed") for name in extra]
            if not data.external_sale_ref:
                problems.append(field("external_sale_ref", "required"))
            if data.branch_id is None:
                problems.append(field("branch_id", "required"))
            if data.sold_at is None:
                problems.append(field("sold_at", "required"))
            elif data.sold_at.tzinfo is None:
                problems.append(field("sold_at", "invalid_format"))
            elif data.sold_at > utcnow() + timedelta(minutes=5):  # kelajakdagi sotuv bo'lmaydi
                problems.append(field("sold_at", "in_future"))
            if data.sku_id is None and not data.title:
                problems.append(field("title", "required"))
            if problems:
                raise ValidationError("External sale is incomplete", fields=problems)
            return None
        own, other = (_ORDER_REFS, _QUICK_REFS) if data.source == "ORDER_LINE" else (_QUICK_REFS, _ORDER_REFS)
        problems = [field(n, "required") for n in own if given[n] is None]
        problems += [field(n, "not_allowed") for n in other if given[n] is not None]
        if data.external_sale_ref:
            problems.append(field("external_sale_ref", "not_allowed"))
        if problems:
            raise ValidationError("Sale reference is invalid", fields=problems)
        if data.source == "ORDER_LINE":
            assert data.order_id and data.order_line_id
            line = await self.commerce.order_line(db, actor.shop_id, data.order_id, data.order_line_id)
        else:
            assert data.quick_sale_id and data.quick_sale_line_id
            line = await self.commerce.quick_sale_line(
                db, actor.shop_id, data.quick_sale_id, data.quick_sale_line_id
            )
        if line is None:
            raise ValidationError("Sale line not found", fields=[field(own[1], "invalid")])
        if line.sale_status is not None and line.sale_status != "COMPLETED":
            raise ValidationError("Order is not completed", fields=[field("order_id", "order_not_completed")])
        return line

    async def _basis(
        self, db: AsyncSession, actor: ActorContext, data: CaseOpenIn, sale: SaleLine | None
    ) -> tuple[str, UUID | None, UUID | None, str | None, UUID, datetime, int | None, int | None]:
        """(nom, sku, product, sku_code, filial, sotilgan vaqt, kafolat oylari, qatordagi son)."""
        assert actor.shop_id is not None
        if sale is not None:
            if sale.branch_id is None or sale.sold_at is None:
                raise ValidationError("Sale is incomplete", fields=[field("order_id", "order_not_completed")])
            ensure_branch_scope(actor, sale.branch_id)
            return (
                sale.title,
                sale.sku_id,
                sale.product_id,
                sale.sku_code,
                sale.branch_id,
                sale.sold_at,
                sale.warranty_months,
                sale.qty,
            )
        assert data.branch_id is not None and data.sold_at is not None
        branch = await load_branch(db, actor, data.branch_id)
        title, product_id, sku_code, months = data.title, None, None, data.warranty_months
        if data.sku_id is not None:
            snapshot = (await self.catalog.get_skus(db, actor.shop_id, [data.sku_id])).get(data.sku_id)
            if snapshot is None:
                raise ValidationError("SKU not found", fields=[field("sku_id", "invalid")])
            title = data.title or snapshot.title
            product_id, sku_code = snapshot.product_id, snapshot.sku_code
            months = data.warranty_months if data.warranty_months is not None else snapshot.warranty_months
        assert title is not None
        return title, data.sku_id, product_id, sku_code, branch.id, data.sold_at, months, None

    async def _check_qty(
        self, db: AsyncSession, actor: ActorContext, data: CaseOpenIn, line_qty: int | None
    ) -> None:
        """Bitta qatorga ochiq murojaatlar yig'indisi qatordagi sondan oshmaydi (support.md §2)."""
        if line_qty is None:
            return
        column = SupportCase.order_line_id if data.source == "ORDER_LINE" else SupportCase.quick_sale_line_id
        line_id = data.order_line_id if data.source == "ORDER_LINE" else data.quick_sale_line_id
        taken = int(
            await db.scalar(
                select(func.coalesce(func.sum(SupportCase.qty), 0)).where(
                    SupportCase.shop_id == actor.shop_id,
                    column == line_id,
                    SupportCase.status.in_(OPEN_STATUSES),
                )
            )
            or 0
        )
        if taken + data.qty > line_qty:
            raise ValidationError(
                "Quantity exceeds the sold quantity of this line",
                fields=[field("qty", "max_value", max=max(line_qty - taken, 0))],
            )

    async def _notify_opened(self, db: AsyncSession, actor: ActorContext, case: SupportCase) -> None:
        """Menejer va egaga xabar + qaror vazifasi (DEC-130). O'zi ochgan menejerga xabar shart emas."""
        await self.tasks.open(
            db,
            shop_id=case.shop_id,
            actor=actor,
            type=SUPPORT_CASE_DECISION,
            subject_type=CASE,
            subject_id=case.id,
            dedup_key=f"support_case_decision:{case.id}",
            assignee_role="MANAGER",
            branch_id=case.branch_id,
            params={"case_number": case.number},
        )
        await self.notifications.notify_staff(
            db,
            shop_id=case.shop_id,
            actor=actor,
            template_key="staff.support_case_opened",
            aggregate_type=CASE,
            aggregate_id=case.id,
            aggregate_version=case.version,
            variables={"case_number": case.number},
            roles=("OWNER", "MANAGER"),
            branch_id=case.branch_id,
            exclude=[actor.membership_id],
        )

    # ================================================================== qabul, mas'ul
    async def receive_item(
        self,
        db: AsyncSession,
        actor: ActorContext,
        case_id: UUID,
        expected_version: int,
        data: CaseReceiveItemIn,
    ) -> CaseDetail:
        """Mahsulot do'konga jismonan topshirildi (`item_received_at`). Yakuniy holatlarda emas."""
        case = await self.load(db, actor, case_id, for_update=True)
        check_version(case.version, expected_version)
        if (
            case.status in ("REJECTED", "IN_SERVICE", "RESOLVED", "CLOSED")
            or case.item_received_at is not None
        ):
            raise ValidationError("Item cannot be received now", fields=[field("status", "invalid_state")])
        case.item_received_at, case.item_received_by = utcnow(), actor.membership_id
        await db.flush()
        await self.audit.record(
            db,
            action="support.case.item_received",
            entity_type=CASE,
            entity_id=case.id,
            actor=actor,
            entity_version=case.version,
        )
        await case_event(db, actor, case, UPDATED, change="ITEM_RECEIVED")
        if data.note:
            db.add(
                CaseNote(
                    shop_id=case.shop_id,
                    case_id=case.id,
                    kind="CUSTOMER_CONTACT",
                    body=data.note,
                    author_membership_id=actor.membership_id,
                )
            )
        return await self.views.detail(db, actor, case)

    async def assign(
        self, db: AsyncSession, actor: ActorContext, case_id: UUID, expected_version: int, data: CaseAssignIn
    ) -> CaseDetail:
        case = await self.load(db, actor, case_id, for_update=True)
        check_version(case.version, expected_version)
        if data.membership_id is not None:
            ok = await db.scalar(
                select(Membership.id).where(
                    Membership.id == data.membership_id,
                    Membership.shop_id == actor.shop_id,
                    Membership.status == "ACTIVE",
                )
            )
            if ok is None:
                raise ValidationError("Member not found", fields=[field("membership_id", "invalid")])
        old = case.assigned_membership_id
        case.assigned_membership_id = data.membership_id
        await db.flush()
        await self.audit.record(
            db,
            action="support.case.assigned",
            entity_type=CASE,
            entity_id=case.id,
            actor=actor,
            entity_version=case.version,
            diff={"assigned": {"old": old, "new": data.membership_id}},
        )
        await case_event(db, actor, case, UPDATED, change="ASSIGNED", previous_staff_id=old)
        return await self.views.detail(db, actor, case)

    # ================================================================== izoh va rasm
    async def add_note(
        self, db: AsyncSession, actor: ActorContext, case_id: UUID, data: CaseNoteIn
    ) -> CaseDetail:
        """Ichki izoh (xaridorga ko'rinmaydi). `DIAGNOSIS` — faqat `IN_REVIEW` da, `diagnosed_at` yoziladi."""
        assert actor.membership_id is not None
        case = await self.load(db, actor, case_id, for_update=data.kind == "DIAGNOSIS")
        if data.kind == "DIAGNOSIS":
            if case.status != "IN_REVIEW":
                raise ValidationError(
                    "Diagnosis is written during review", fields=[field("kind", "invalid_state")]
                )
            case.diagnosed_at, case.diagnosed_by = utcnow(), actor.membership_id
        db.add(
            CaseNote(
                shop_id=case.shop_id,
                case_id=case.id,
                kind=data.kind,
                body=data.body,
                author_membership_id=actor.membership_id,
            )
        )
        await db.flush()
        await self.audit.record(  # matn audit'ga tushmaydi (PII bo'lishi mumkin)
            db,
            action="support.case.noted",
            entity_type=CASE,
            entity_id=case.id,
            actor=actor,
            entity_version=case.version,
            diff={"kind": data.kind},
        )
        await case_event(db, actor, case, UPDATED, change="NOTE", note_kind=data.kind)
        return await self.views.detail(db, actor, case)

    async def add_attachment(
        self, db: AsyncSession, actor: ActorContext, case_id: UUID, data: CaseAttachmentIn
    ) -> CaseDetail:
        assert actor.shop_id is not None and actor.membership_id is not None
        case = await self.load(db, actor, case_id, for_update=True)
        try:  # shu shopniki, faol va SUPPORT_EVIDENCE (birovning fayl ID'si — TC-ISO-05)
            await self.files.usable(db, actor.shop_id, data.file_id, SEARCH_FILE_PURPOSE)
        except ValidationError as exc:
            raise ValidationError("File not usable", fields=[field("file_id", "invalid")]) from exc
        count = int(
            await db.scalar(
                select(func.count()).where(
                    CaseAttachment.shop_id == case.shop_id, CaseAttachment.case_id == case.id
                )
            )
            or 0
        )
        if count >= MAX_ATTACHMENTS:
            raise ValidationError(
                "Too many attachments", fields=[field("file_id", "max_items", max=MAX_ATTACHMENTS)]
            )
        duplicate = await db.scalar(
            select(CaseAttachment.id).where(
                CaseAttachment.shop_id == case.shop_id,
                CaseAttachment.case_id == case.id,
                CaseAttachment.file_id == data.file_id,
            )
        )
        if duplicate is not None:
            raise ValidationError("File already attached", fields=[field("file_id", "duplicate")])
        db.add(
            CaseAttachment(
                shop_id=case.shop_id,
                case_id=case.id,
                file_id=data.file_id,
                caption=data.caption,
                source_message_id=data.source_message_id,
                added_by=actor.membership_id,
            )
        )
        await db.flush()
        await self.audit.record(
            db,
            action="support.case.attachment_added",
            entity_type=CASE,
            entity_id=case.id,
            actor=actor,
            entity_version=case.version,
            diff={"file_id": data.file_id},
        )
        await case_event(db, actor, case, UPDATED, change="ATTACHMENT")
        return await self.views.detail(db, actor, case)


def _uuid(value: str, name: str) -> UUID:
    try:
        return UUID(value)
    except ValueError as exc:
        raise ValidationError("Invalid value", fields=[field(name, "invalid_format")]) from exc
