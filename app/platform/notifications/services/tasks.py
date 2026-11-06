"""Xodim vazifalari (db/notifications.md §3, 20 §9).

Domen vazifani o'z tranzaksiyasida ochadi (`open`) va sabab yo'qolganda o'zi yopadi (`resolve`):
buyurtma tasdiqlansa — "tasdiq eslatmasi" `RESOLVED`. Xodim "bajarildi" desa — `DONE`.
Har ochilish/yopilish — `platform.task.created` / `.closed` event'i (panelga realtime signal).

Kim ko'radi: ega va menejer — filial doirasidagi hammasini (nazorat); operator va omborchi — o'ziga
biriktirilganini yoki o'z roliga (filiali bo'yicha) qo'yilganini.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import ColumnElement, Select, and_, func, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.platform.notifications.models.orm import StaffTask
from app.platform.notifications.schemas import TaskLink, TaskList, TaskOut
from app.platform.notifications.services.recipients import resolve_members
from app.shared.clock import utcnow
from app.shared.errors.base import ForbiddenError, InvalidTransitionError, NotFoundError, ValidationError
from app.shared.events.outbox import write_outbox
from app.shared.http import check_version
from app.shared.pagination import DEFAULT_LIMIT, decode_cursor, encode_cursor
from app.shared.serialization import to_json_compatible
from app.shared.types.actor import ActorContext

TASK = "platform.task"
SUPERVISOR_ROLES = frozenset({"OWNER", "MANAGER"})
# `params` dagi kalit: vazifani yuzaga keltirgan xodim (masalan tuzatishni so'ragan omborchi) — u o'z
# tasdiq vazifasini ololmaydi va yopolmaydi (QA 5a F8)
REQUESTER_PARAM = "requested_by"


def role_qualifies(role: str, required: str | None) -> bool:
    """Vazifa turi ro'yxatda yo'q bo'lsa — `assignee_role` bo'yicha: ega hammasiga, menejer egadan boshqa
    hammasiga, qolganlar aynan o'z roliga; rolsiz vazifa — hammaga."""
    if required is None or role == "OWNER":
        return True
    if role == "MANAGER":
        return required != "OWNER"
    return role == required


# Vazifa turlari (db/notifications.dbml). Turi ro'yxati bazada CHECK emas — yangi modul o'zinikini qo'shadi
ORDER_CONFIRM_REMINDER = "ORDER_CONFIRM_REMINDER"
RESERVATION_REVIEW = "RESERVATION_REVIEW"
ADJUSTMENT_APPROVAL = "ADJUSTMENT_APPROVAL"
DISCOUNT_APPROVAL = "DISCOUNT_APPROVAL"
NOTIFICATION_FAILED = "NOTIFICATION_FAILED"
STOCK_RECONCILE_MISMATCH = "STOCK_RECONCILE_MISMATCH"
EXCHANGE_RATE_STALE = "EXCHANGE_RATE_STALE"
# 5b: suhbatlar
HANDOFF = "HANDOFF"  # operator kerak — suhbatni oling
MESSAGE_FAILED = "MESSAGE_FAILED"  # xaridorga xabar yetmadi (TC-011)
CHANNEL_DEGRADED = "CHANNEL_DEGRADED"  # kanal ishlamayapti — egaga

_LINKS: dict[str, str] = {
    ORDER_CONFIRM_REMINDER: "order",
    RESERVATION_REVIEW: "order",
    DISCOUNT_APPROVAL: "order",
    ADJUSTMENT_APPROVAL: "adjustment",
    STOCK_RECONCILE_MISMATCH: "stock",
    EXCHANGE_RATE_STALE: "exchange_rates",
    NOTIFICATION_FAILED: "notification_settings",
    HANDOFF: "conversation",
    MESSAGE_FAILED: "conversation",
    CHANNEL_DEGRADED: "channels",
}
_WITH_ID = frozenset({"order", "adjustment", "conversation"})

# Kim bajara oladi (oladi va yopadi) — vazifa turi bo'yicha (QA 5a F8). `assignee_role` esa kimga
# ko'rinishi va kim nazorat qilishini bildiradi: tasdiq eslatmasi menejer navbatida, lekin operator bajaradi.
APPROVERS = frozenset({"OWNER", "MANAGER"})
TASK_ROLES: dict[str, frozenset[str]] = {
    ORDER_CONFIRM_REMINDER: frozenset({"OWNER", "MANAGER", "SALES"}),
    RESERVATION_REVIEW: APPROVERS,  # "kutamiz / bekor" — menejer qarori
    ADJUSTMENT_APPROVAL: APPROVERS,
    DISCOUNT_APPROVAL: APPROVERS,
    STOCK_RECONCILE_MISMATCH: APPROVERS,
    EXCHANGE_RATE_STALE: APPROVERS,  # kursni ega va menejer kiritadi
    HANDOFF: frozenset({"OWNER", "MANAGER", "SALES"}),  # suhbatni operator oladi
    MESSAGE_FAILED: frozenset({"OWNER", "MANAGER", "SALES"}),
    CHANNEL_DEGRADED: frozenset({"OWNER"}),  # kanalni faqat ega ulaydi (UAT-M09)
}


def task_role_allows(task_type: str, assignee_role: str | None, role: str) -> bool:
    roles = TASK_ROLES.get(task_type)
    return role in roles if roles is not None else role_qualifies(role, assignee_role)


def task_link(task_type: str, subject_id: UUID | None) -> TaskLink | None:
    route = _LINKS.get(task_type)
    if route is None:
        return None
    return TaskLink(route=route, id=subject_id if route in _WITH_ID else None)


def _requester(task: StaffTask) -> UUID | None:
    raw = (task.params or {}).get(REQUESTER_PARAM)
    try:
        return UUID(str(raw)) if raw else None
    except ValueError:
        return None


def task_out(task: StaffTask) -> TaskOut:
    return TaskOut(
        id=task.id,
        type=task.type,
        status=task.status,
        priority=task.priority,
        subject_type=task.subject_type,
        subject_id=task.subject_id,
        branch_id=task.branch_id,
        assignee_membership_id=task.assignee_membership_id,
        assignee_role=task.assignee_role,
        params=task.params,
        link=task_link(task.type, task.subject_id),
        due_at=task.due_at,
        created_at=task.created_at,
        resolved_at=task.resolved_at,
        version=task.version,
    )


def _event_payload(task: StaffTask) -> dict[str, Any]:
    return {
        "task_id": task.id,
        "type": task.type,
        "status": task.status,
        "subject_type": task.subject_type,
        "subject_id": task.subject_id,
        "branch_id": task.branch_id,
        "assignee_membership_id": task.assignee_membership_id,
        "assignee_role": task.assignee_role,
    }


class TaskService:
    # ------------------------------------------------------------------ domen chaqiradi
    async def open(
        self,
        db: AsyncSession,
        *,
        shop_id: UUID,
        actor: ActorContext,
        type: str,
        subject_type: str,
        subject_id: UUID,
        dedup_key: str,
        assignee_membership_id: UUID | None = None,
        assignee_role: str | None = None,
        branch_id: UUID | None = None,
        priority: str = "NORMAL",
        params: dict[str, Any] | None = None,
        due_at: datetime | None = None,
    ) -> StaffTask | None:
        """Yangi vazifa yoki `None` — shu `dedup_key` bilan allaqachon bor (rejali ish qayta ishladi)."""
        task_id = await db.scalar(
            insert(StaffTask)
            .values(
                shop_id=shop_id,
                type=type,
                subject_type=subject_type,
                subject_id=subject_id,
                branch_id=branch_id,
                assignee_membership_id=assignee_membership_id,
                assignee_role=assignee_role,
                priority=priority,
                params=to_json_compatible(params or {}),  # UUID → matn (JSONB)
                due_at=due_at,
                dedup_key=dedup_key,
                version=1,
            )
            .on_conflict_do_nothing(index_elements=["shop_id", "dedup_key"])
            .returning(StaffTask.id)
        )
        if task_id is None:
            return None
        task = await db.get(StaffTask, task_id)
        assert task is not None
        await self._event(db, actor, task, "platform.task.created")
        return task

    async def resolve(
        self,
        db: AsyncSession,
        *,
        shop_id: UUID,
        actor: ActorContext,
        subject_type: str,
        subject_id: UUID,
        types: Iterable[str] | None = None,
    ) -> int:
        """Sabab yo'qoldi — ochiq vazifalar `RESOLVED` (buyurtma tasdiqlandi, so'rov hal qilindi)."""
        conditions = [
            StaffTask.shop_id == shop_id,
            StaffTask.subject_type == subject_type,
            StaffTask.subject_id == subject_id,
            StaffTask.status == "OPEN",
        ]
        type_list = list(types) if types is not None else None
        if type_list is not None:
            conditions.append(StaffTask.type.in_(type_list))
        tasks = (await db.execute(select(StaffTask).where(*conditions).with_for_update())).scalars().all()
        now = utcnow()
        for task in tasks:
            task.status, task.resolved_at = "RESOLVED", now
        if tasks:
            await db.flush()
        for task in tasks:
            await self._event(db, actor, task, "platform.task.closed")
        return len(tasks)

    # ------------------------------------------------------------------ shop paneli
    def _visible(self, actor: ActorContext) -> Any:
        in_scope = (
            or_(StaffTask.branch_id.is_(None), StaffTask.branch_id.in_(actor.branch_ids))
            if actor.branch_ids is not None
            else None
        )
        if actor.roles & SUPERVISOR_ROLES:
            return in_scope if in_scope is not None else StaffTask.shop_id == actor.shop_id
        role_match: ColumnElement[bool] = StaffTask.assignee_role.in_(actor.roles)
        if in_scope is not None:
            role_match = and_(role_match, in_scope)
        return or_(StaffTask.assignee_membership_id == actor.membership_id, role_match)

    def _query(self, actor: ActorContext) -> Select[StaffTask]:
        return select(StaffTask).where(StaffTask.shop_id == actor.shop_id, self._visible(actor))

    async def list(
        self,
        db: AsyncSession,
        actor: ActorContext,
        *,
        status: str | None,
        type: str | None,
        cursor: str | None,
        limit: int = DEFAULT_LIMIT,
        assigned: str | None = None,
    ) -> TaskList:
        """`assigned`: `me` — menga biriktirilgan; `unassigned` — hech kimga; xodim ID'si — o'shanga."""
        query = self._query(actor)
        if status is not None:
            query = query.where(StaffTask.status == status)
        if type is not None:
            query = query.where(StaffTask.type == type)
        if assigned == "me":
            query = query.where(StaffTask.assignee_membership_id == actor.membership_id)
        elif assigned == "unassigned":
            query = query.where(StaffTask.assignee_membership_id.is_(None))
        elif assigned is not None:
            try:
                member = UUID(assigned)
            except ValueError as exc:
                raise ValidationError(
                    "Invalid assigned filter",
                    fields=[{"field": "assigned", "code": "invalid_format", "params": {}}],
                ) from exc
            query = query.where(StaffTask.assignee_membership_id == member)
        if cursor:
            values = decode_cursor(cursor)
            try:
                at, last_id = datetime.fromisoformat(str(values["t"])), UUID(str(values["id"]))
            except (KeyError, ValueError) as exc:
                raise ValidationError(
                    "Cursor is invalid", fields=[{"field": "cursor", "code": "invalid_format", "params": {}}]
                ) from exc
            query = query.where(
                or_(StaffTask.created_at < at, and_(StaffTask.created_at == at, StaffTask.id < last_id))
            )
        rows = (
            (
                await db.execute(
                    query.order_by(StaffTask.created_at.desc(), StaffTask.id.desc()).limit(limit + 1)
                )
            )
            .scalars()
            .all()
        )
        page, has_more = list(rows[:limit]), len(rows) > limit
        open_count = int(
            await db.scalar(
                select(func.count())
                .select_from(StaffTask)
                .where(StaffTask.shop_id == actor.shop_id, StaffTask.status == "OPEN", self._visible(actor))
            )
            or 0
        )
        next_cursor = (
            encode_cursor({"t": page[-1].created_at.isoformat(), "id": str(page[-1].id)})
            if has_more and page
            else None
        )
        return TaskList(
            items=[task_out(t) for t in page],
            next_cursor=next_cursor,
            has_more=has_more,
            open_count=open_count,
        )

    async def _load(self, db: AsyncSession, actor: ActorContext, task_id: UUID) -> StaffTask:
        task = (
            await db.execute(self._query(actor).where(StaffTask.id == task_id).with_for_update())
        ).scalar_one_or_none()
        if task is None:
            raise NotFoundError("Task not found")
        return task

    async def mark_done(
        self, db: AsyncSession, actor: ActorContext, task_id: UUID, expected_version: int
    ) -> TaskOut:
        task = await self._load(db, actor, task_id)
        check_version(task.version, expected_version)
        if task.status != "OPEN":
            raise InvalidTransitionError(
                "Task is not open", entity=TASK, **{"from": task.status}, command="DONE"
            )
        # Tasdiq vazifasini faqat tasdiqlay oladigan rol yopadi; so'rov egasi — hech qachon (QA 5a F8)
        if not any(task_role_allows(task.type, task.assignee_role, role) for role in actor.roles):
            raise ForbiddenError("Task requires another role", reason="task_role", role=task.assignee_role)
        if _requester(task) == actor.membership_id:
            raise ForbiddenError("Requester cannot close own approval task", reason="requester")
        task.status, task.resolved_by, task.resolved_at = "DONE", actor.membership_id, utcnow()
        await db.flush()
        await self._event(db, actor, task, "platform.task.closed")
        return task_out(task)

    async def assign(
        self, db: AsyncSession, actor: ActorContext, task_id: UUID, expected_version: int, membership_id: UUID
    ) -> TaskOut:
        """Ega yoki menejer (`staff.task.assign`) vazifani aniq xodimga beradi: xodim faol, filiali mos va
        roli vazifa roliga mos bo'lishi kerak; so'rov egasiga o'z tasdiq vazifasi berilmaydi."""
        task = await self._load(db, actor, task_id)
        check_version(task.version, expected_version)
        if task.status != "OPEN":
            raise InvalidTransitionError(
                "Task is not open", entity=TASK, **{"from": task.status}, command="ASSIGN"
            )
        assert actor.shop_id is not None
        if _requester(task) == membership_id or not await self._can_take(
            db, actor.shop_id, membership_id, task
        ):
            raise ValidationError(
                "Member cannot take this task",
                fields=[{"field": "membership_id", "code": "invalid_choice", "params": {}}],
            )
        task.assignee_membership_id = membership_id
        await db.flush()
        await self._event(db, actor, task, "platform.task.created")  # yangi egasi signal oladi
        return task_out(task)

    @staticmethod
    async def _can_take(db: AsyncSession, shop_id: UUID, membership_id: UUID, task: StaffTask) -> bool:
        """Faol xodim, roli vazifa turiga mos va (filialli vazifada) filial doirasi shu filialni qamraydi."""
        members = await resolve_members(db, shop_id, membership_ids=[membership_id])
        if not members or not task_role_allows(task.type, task.assignee_role, members[0].role):
            return False
        branch_id = task.branch_id
        if branch_id is None:
            return True
        in_branch = await resolve_members(db, shop_id, roles=[members[0].role], branch_id=branch_id)
        return any(m.membership_id == membership_id for m in in_branch)

    async def _event(self, db: AsyncSession, actor: ActorContext, task: StaffTask, event_type: str) -> None:
        await write_outbox(
            db,
            schema="platform",
            event_type=event_type,
            actor=actor,
            shop_id=task.shop_id,
            aggregate_type=TASK,
            aggregate_id=task.id,
            aggregate_version=task.version,
            payload=_event_payload(task),
        )
