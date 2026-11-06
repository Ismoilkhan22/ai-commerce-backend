"""M25: filiallar orasida ko'chirish (Stage 2) — BL-082: qoldiq ikki marta hisoblanmaydi.

```
Jo'natish (manba filial) ──▶ TRANSFER_OUT: manbadan −qty (band qilingan mahsulot ketmaydi) ──▶ IN_TRANSIT
   yo'lda: hech qaysi filialda sotuvga mavjud emas
Qabul (qabul qiluvchi filial) ──▶ TRANSFER_IN: +kelgan son ──▶ RECEIVED; kam kelgani — kamomad, egaga vazifa
Bekor (yo'lda bo'lsa) ──▶ TRANSFER_IN manbaga qaytadi ──▶ CANCELLED
```

Filial doirasi: omborchi faqat o'z filialidan jo'natadi va o'z filialiga qabul qiladi. Har qadam — audit
va `commerce.stock.changed` (StockService.apply). To'ldirish tavsiyasi: bir filialda tugagan, boshqasida
≥ 2 ta bor.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.commerce.common import field, load_branch
from app.domains.commerce.inventory.models.orm import StockBalance, StockTransfer, StockTransferLine
from app.domains.commerce.inventory.services.stock_service import Movement, StockService
from app.platform.audit.services.audit_service import AuditService
from app.platform.notifications.services.tasks import TRANSFER_SHORTAGE, TaskService
from app.platform.shops.models.orm import Branch
from app.shared.clock import utcnow
from app.shared.contracts.catalog import CatalogQueryPort
from app.shared.errors.base import InvalidTransitionError, NotFoundError, ValidationError
from app.shared.http import check_version
from app.shared.types.actor import ActorContext

TRANSFER = "commerce.stock_transfer"
MAX_LINES = 100


class TransferLineIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sku_id: UUID
    qty: int = Field(ge=1, le=100_000)


class TransferIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    from_branch_id: UUID
    to_branch_id: UUID
    lines: list[TransferLineIn] = Field(min_length=1, max_length=MAX_LINES)
    note: str | None = Field(default=None, max_length=500)


class ReceiveLineIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sku_id: UUID
    received_qty: int = Field(ge=0, le=100_000)


class ReceiveIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    lines: list[ReceiveLineIn] | None = None  # bo'sh — hammasi to'liq keldi


class TransferLineOut(BaseModel):
    sku_id: UUID
    title: str
    qty: int
    received_qty: int | None


class TransferOut(BaseModel):
    id: UUID
    version: int
    status: str
    from_branch_id: UUID
    from_branch_name: str
    to_branch_id: UUID
    to_branch_name: str
    note: str | None
    sent_at: datetime
    received_at: datetime | None
    shortage_units: int
    lines: list[TransferLineOut]


class TransferList(BaseModel):
    items: list[TransferOut]


class TransferSuggestion(BaseModel):
    sku_id: UUID
    title: str
    from_branch_id: UUID
    from_branch_name: str
    from_available: int
    to_branch_id: UUID
    to_branch_name: str
    suggested_qty: int


class TransferSuggestionList(BaseModel):
    items: list[TransferSuggestion]


class TransferService:
    def __init__(self, audit: AuditService, stock: StockService, catalog: CatalogQueryPort) -> None:
        self.audit = audit
        self.stock = stock
        self.catalog = catalog
        self.tasks = TaskService()

    async def create(self, db: AsyncSession, actor: ActorContext, data: TransferIn) -> TransferOut:
        assert actor.shop_id is not None
        if data.from_branch_id == data.to_branch_id:
            raise ValidationError("Branches must differ", fields=[field("to_branch_id", "invalid")])
        await load_branch(db, actor, data.from_branch_id, field_name="from_branch_id")
        await self._branch_open(db, actor, data.to_branch_id)
        quantities: dict[UUID, int] = {}
        for line in data.lines:
            quantities[line.sku_id] = quantities.get(line.sku_id, 0) + line.qty
        snapshots = await self.catalog.get_skus(db, actor.shop_id, list(quantities))
        unknown = [i for i, line in enumerate(data.lines) if line.sku_id not in snapshots]
        if unknown:
            raise ValidationError(
                "Unknown SKU", fields=[field(f"lines[{i}].sku_id", "invalid") for i in unknown]
            )
        transfer = StockTransfer(
            shop_id=actor.shop_id,
            from_branch_id=data.from_branch_id,
            to_branch_id=data.to_branch_id,
            note=(data.note or "").strip() or None,
            sent_by=actor.membership_id,
            version=1,
        )
        db.add(transfer)
        await db.flush()
        db.add_all(
            StockTransferLine(shop_id=actor.shop_id, transfer_id=transfer.id, sku_id=sku_id, qty=qty)
            for sku_id, qty in quantities.items()
        )
        await self.stock.apply(
            db,
            actor,
            [
                Movement(data.from_branch_id, sku_id, "TRANSFER_OUT", "TRANSFER", transfer.id, on_hand=-qty)
                for sku_id, qty in quantities.items()
            ],
        )
        await self.audit.record(
            db,
            action="commerce.transfer.sent",
            entity_type=TRANSFER,
            entity_id=transfer.id,
            actor=actor,
            diff={"lines": len(quantities), "units": sum(quantities.values())},
        )
        return await self.get(db, actor, transfer.id)

    async def receive(
        self, db: AsyncSession, actor: ActorContext, transfer_id: UUID, version: int, data: ReceiveIn
    ) -> TransferOut:
        transfer = await self._locked(db, actor, transfer_id, version, "RECEIVE")
        await self._branch_open(db, actor, transfer.to_branch_id, scope=True)
        lines = await self._lines(db, transfer)
        received = {line.sku_id: line.received_qty for line in data.lines or ()}
        extra = [str(s) for s in received if s not in {line.sku_id for line in lines}]
        if extra:
            raise ValidationError(
                "SKU is not in this transfer", fields=[field("lines", "invalid", skus=extra)]
            )
        movements: list[Movement] = []
        shortage = 0
        for line in lines:
            got = received.get(line.sku_id, line.qty)
            if got > line.qty:
                raise ValidationError(
                    "Received more than sent", fields=[field("lines", "max_value", max=line.qty)]
                )
            line.received_qty = got
            shortage += line.qty - got
            if got:
                movements.append(
                    Movement(
                        transfer.to_branch_id,
                        line.sku_id,
                        "TRANSFER_IN",
                        "TRANSFER",
                        transfer.id,
                        on_hand=got,
                    )
                )
        if movements:
            await self.stock.apply(db, actor, movements, create=True)
        transfer.status, transfer.received_by, transfer.received_at = (
            "RECEIVED",
            actor.membership_id,
            utcnow(),
        )
        transfer.shortage_units = shortage
        await db.flush()
        if shortage:  # yo'lda yo'qolgan — egaga vazifa (avtomatik hisobdan chiqarilmaydi)
            await self.tasks.open(
                db,
                shop_id=transfer.shop_id,
                actor=actor,
                type=TRANSFER_SHORTAGE,
                subject_type=TRANSFER,
                subject_id=transfer.id,
                dedup_key=f"transfer:{transfer.id}",
                assignee_role="MANAGER",
                params={"units": shortage},
            )
        await self.audit.record(
            db,
            action="commerce.transfer.received",
            entity_type=TRANSFER,
            entity_id=transfer.id,
            actor=actor,
            diff={"shortage_units": shortage},
        )
        return await self.get(db, actor, transfer.id)

    async def cancel(
        self, db: AsyncSession, actor: ActorContext, transfer_id: UUID, version: int
    ) -> TransferOut:
        transfer = await self._locked(db, actor, transfer_id, version, "CANCEL")
        await self._branch_open(db, actor, transfer.from_branch_id, scope=True)
        lines = await self._lines(db, transfer)
        await self.stock.apply(
            db,
            actor,
            [
                Movement(
                    transfer.from_branch_id,
                    line.sku_id,
                    "TRANSFER_IN",
                    "TRANSFER",
                    transfer.id,
                    on_hand=line.qty,
                )
                for line in lines
            ],
            create=True,
        )
        transfer.status, transfer.cancelled_by, transfer.cancelled_at = (
            "CANCELLED",
            actor.membership_id,
            utcnow(),
        )
        await db.flush()
        await self.audit.record(
            db, action="commerce.transfer.cancelled", entity_type=TRANSFER, entity_id=transfer.id, actor=actor
        )
        return await self.get(db, actor, transfer.id)

    async def get(self, db: AsyncSession, actor: ActorContext, transfer_id: UUID) -> TransferOut:
        transfer = (
            await db.execute(
                select(StockTransfer).where(
                    StockTransfer.shop_id == actor.shop_id, StockTransfer.id == transfer_id
                )
            )
        ).scalar_one_or_none()
        if transfer is None:
            raise NotFoundError("Transfer not found")
        return (await self._out(db, actor, [transfer]))[0]

    async def list_transfers(self, db: AsyncSession, actor: ActorContext, status: str | None) -> TransferList:
        query = select(StockTransfer).where(StockTransfer.shop_id == actor.shop_id)
        if status:
            query = query.where(StockTransfer.status == status)
        if actor.branch_ids is not None:
            ids = list(actor.branch_ids)
            query = query.where(StockTransfer.from_branch_id.in_(ids) | StockTransfer.to_branch_id.in_(ids))
        rows = await db.execute(query.order_by(StockTransfer.sent_at.desc()).limit(100))
        return TransferList(items=await self._out(db, actor, list(rows.scalars())))

    async def suggestions(
        self, db: AsyncSession, actor: ActorContext, limit: int = 50
    ) -> TransferSuggestionList:
        """Bir filialda sotuvga mavjud 0, boshqasida ≥ 2: ortiqchaning yarmini ko'chirish taklifi."""
        assert actor.shop_id is not None
        available = StockBalance.on_hand - StockBalance.reserved - StockBalance.allocated
        branches = {
            b.id: b.name
            for b in (
                await db.execute(
                    select(Branch).where(Branch.shop_id == actor.shop_id, Branch.status == "ACTIVE")
                )
            ).scalars()
        }
        rows = await db.execute(
            select(StockBalance.sku_id, StockBalance.branch_id, available.label("available")).where(
                StockBalance.shop_id == actor.shop_id, StockBalance.branch_id.in_(list(branches))
            )
        )
        by_sku: dict[UUID, dict[UUID, int]] = {}
        for sku_id, branch_id, avail in rows:
            by_sku.setdefault(sku_id, {})[branch_id] = int(avail)
        found: list[tuple[UUID, UUID, int, UUID, int]] = []
        for sku_id, levels in by_sku.items():
            empty = [b for b in branches if levels.get(b, 0) <= 0 and b in levels]
            rich = sorted(((v, b) for b, v in levels.items() if v >= 2), reverse=True)
            if empty and rich:
                top, source = rich[0]
                for target in empty:
                    found.append((sku_id, source, top, target, max(1, top // 2)))
        titles = await self.catalog.get_skus(db, actor.shop_id, list({f[0] for f in found}))
        items = [
            TransferSuggestion(
                sku_id=sku_id,
                title=titles[sku_id].title if sku_id in titles else "—",
                from_branch_id=source,
                from_branch_name=branches[source],
                from_available=top,
                to_branch_id=target,
                to_branch_name=branches[target],
                suggested_qty=qty,
            )
            for sku_id, source, top, target, qty in found
            if sku_id in titles and titles[sku_id].sku_status == "ACTIVE"
        ]
        items.sort(key=lambda s: -s.from_available)
        return TransferSuggestionList(items=items[:limit])

    async def in_transit(self, db: AsyncSession, shop_id: UUID, sku_ids: Sequence[UUID]) -> dict[UUID, int]:
        if not sku_ids:
            return {}
        rows = await db.execute(
            select(StockTransferLine.sku_id, func.sum(StockTransferLine.qty))
            .join(
                StockTransfer,
                (StockTransfer.shop_id == StockTransferLine.shop_id)
                & (StockTransfer.id == StockTransferLine.transfer_id),
            )
            .where(
                StockTransferLine.shop_id == shop_id,
                StockTransfer.status == "IN_TRANSIT",
                StockTransferLine.sku_id.in_(list(sku_ids)),
            )
            .group_by(StockTransferLine.sku_id)
        )
        return {sku_id: int(total) for sku_id, total in rows}

    # ------------------------------------------------------------------ yordamchilar
    async def _branch_open(
        self, db: AsyncSession, actor: ActorContext, branch_id: UUID, *, scope: bool = False
    ) -> None:
        branch = (
            await db.execute(select(Branch).where(Branch.id == branch_id, Branch.shop_id == actor.shop_id))
        ).scalar_one_or_none()
        if branch is None or branch.status != "ACTIVE":
            raise ValidationError("Branch not found", fields=[field("to_branch_id", "invalid")])
        if scope:
            await load_branch(db, actor, branch_id)  # filial doirasi (omborchi — faqat o'z filiali)

    async def _locked(
        self, db: AsyncSession, actor: ActorContext, transfer_id: UUID, version: int, command: str
    ) -> StockTransfer:
        transfer = (
            await db.execute(
                select(StockTransfer)
                .where(StockTransfer.shop_id == actor.shop_id, StockTransfer.id == transfer_id)
                .with_for_update()
            )
        ).scalar_one_or_none()
        if transfer is None:
            raise NotFoundError("Transfer not found")
        check_version(transfer.version, version)
        if transfer.status != "IN_TRANSIT":
            raise InvalidTransitionError(
                "Transfer is closed", entity=TRANSFER, **{"from": transfer.status}, command=command
            )
        return transfer

    @staticmethod
    async def _lines(db: AsyncSession, transfer: StockTransfer) -> list[StockTransferLine]:
        rows = await db.execute(
            select(StockTransferLine)
            .where(
                StockTransferLine.shop_id == transfer.shop_id, StockTransferLine.transfer_id == transfer.id
            )
            .order_by(StockTransferLine.sku_id)
        )
        return list(rows.scalars())

    async def _out(
        self, db: AsyncSession, actor: ActorContext, transfers: Sequence[StockTransfer]
    ) -> list[TransferOut]:
        if not transfers:
            return []
        assert actor.shop_id is not None
        names = {
            b.id: b.name
            for b in (await db.execute(select(Branch).where(Branch.shop_id == actor.shop_id))).scalars()
        }
        lines: dict[UUID, list[StockTransferLine]] = {}
        for transfer in transfers:
            lines[transfer.id] = await self._lines(db, transfer)
        titles = await self.catalog.get_skus(
            db, actor.shop_id, list({ln.sku_id for ls in lines.values() for ln in ls})
        )
        return [
            TransferOut(
                id=t.id,
                version=t.version,
                status=t.status,
                from_branch_id=t.from_branch_id,
                from_branch_name=names.get(t.from_branch_id, "—"),
                to_branch_id=t.to_branch_id,
                to_branch_name=names.get(t.to_branch_id, "—"),
                note=t.note,
                sent_at=t.sent_at,
                received_at=t.received_at,
                shortage_units=t.shortage_units,
                lines=[
                    TransferLineOut(
                        sku_id=ln.sku_id,
                        title=titles[ln.sku_id].title if ln.sku_id in titles else "—",
                        qty=ln.qty,
                        received_qty=ln.received_qty,
                    )
                    for ln in lines[t.id]
                ],
            )
            for t in transfers
        ]
