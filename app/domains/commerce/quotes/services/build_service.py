"""Panel'dagi "PC yig'ish" sahifasi (6a): yig'mani tekshirish va slot uchun mos nomzodlar.

Hech narsa saqlamaydi (C2): moslik — `CatalogQueryPort.check_compatibility` (engine kodda), narx — katalog,
mavjudlik — `StockQueryPort`. Nomzodlar soni cheklangan (har biri uchun engine bir marta ishlaydi).
"""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.commerce.common import field, load_branch
from app.domains.commerce.orders.services.pricing import line_total, usable
from app.domains.commerce.quotes.common import PC_ROLES, compat_out, findings_out, line_role
from app.domains.commerce.quotes.schemas import (
    BuildCheckIn,
    BuildCheckOut,
    BuildLineIn,
    BuildLineOut,
    CandidateOut,
    CandidatesIn,
    CandidatesOut,
)
from app.shared.contracts.catalog import CatalogQueryPort
from app.shared.contracts.commerce import StockQueryPort
from app.shared.contracts.compatibility import BuildLine
from app.shared.errors.base import ValidationError
from app.shared.i18n.locale import get_display_locale
from app.shared.types.actor import ActorContext

DECISION_ORDER = {"PASS": 0, "REVIEW_REQUIRED": 1, "BLOCK": 2}
CANDIDATE_SCAN = 1000  # arzon saralash uchun olinadigan SKU'lar (atribut + mavjudlik, engine'siz)
CANDIDATE_POOL = 40  # saralangandan keyin engine bilan tekshiriladiganlar (QA 6a F6)


def _first(parts: list[dict[str, Any]], key: str) -> Any:
    return next((p[key] for p in parts if p.get(key) is not None), None)


def prefilter(role: str, candidate: dict[str, Any], build: dict[str, list[dict[str, Any]]]) -> bool | None:
    """Engine'dan oldin arzon tekshiruv: joriy yig'maning ma'lum atributlariga zid nomzod — False;
    mos — True; tekshirib bo'lmasa (atribut noma'lum) — None. Yakuniy hukm baribir engine'da."""
    checks: list[bool] = []

    def compare(ok: bool | None) -> None:
        if ok is not None:
            checks.append(ok)

    cpu, mb, ram, case = (
        build.get("CPU", []),
        build.get("MOTHERBOARD", []),
        build.get("RAM", []),
        build.get("CASE", []),
    )
    if role == "CPU":
        socket, mem = _first(mb, "socket"), _first(ram, "type")
        compare(None if socket is None or candidate.get("socket") is None else candidate["socket"] == socket)
        types = candidate.get("memory_types")
        compare(None if mem is None or types is None else mem in types)
    elif role == "MOTHERBOARD":
        socket, mem = _first(cpu, "socket"), _first(ram, "type")
        compare(None if socket is None or candidate.get("socket") is None else candidate["socket"] == socket)
        compare(
            None if mem is None or candidate.get("memory_type") is None else candidate["memory_type"] == mem
        )
        forms = _first(case, "supported_mb_form_factors")
        form = candidate.get("form_factor")
        compare(None if forms is None or form is None else form in forms)
    elif role == "RAM":
        mem, types = _first(mb, "memory_type"), _first(cpu, "memory_types")
        kind = candidate.get("type")
        compare(None if mem is None or kind is None else kind == mem)
        compare(None if types is None or kind is None else kind in types)
    elif role == "CASE":
        form = _first(mb, "form_factor")
        forms = candidate.get("supported_mb_form_factors")
        compare(None if form is None or forms is None else form in forms)
    elif role == "CPU_COOLER":
        socket, sockets = _first(cpu, "socket"), candidate.get("supported_sockets")
        compare(None if socket is None or sockets is None else socket in sockets)
    elif role == "GPU":
        limit, length = _first(case, "max_gpu_length_mm"), candidate.get("length_mm")
        compare(None if limit is None or length is None else int(length) <= int(limit))
    if not checks:
        return None
    return all(checks)


class BuildService:
    def __init__(self, catalog: CatalogQueryPort, stock: StockQueryPort) -> None:
        self.catalog = catalog
        self.stock = stock

    async def check(self, db: AsyncSession, actor: ActorContext, data: BuildCheckIn) -> BuildCheckOut:
        assert actor.shop_id is not None
        _unique(data.lines)
        if data.branch_id is not None:  # QA 6a F19: shu shop va xodim doirasidagi filial
            await load_branch(db, actor, data.branch_id)
        ids = [line.sku_id for line in data.lines]
        result = await self.catalog.check_compatibility(
            db,
            actor.shop_id,
            [BuildLine(sku_id=line.sku_id, quantity=line.qty) for line in data.lines],
            get_display_locale(),
            full_build=data.full_build,
        )
        snapshots = await self.catalog.get_skus(db, actor.shop_id, ids)
        categories = await self.catalog.sku_spec_categories(db, actor.shop_id, ids)
        available = await self._available(db, actor.shop_id, ids, data.branch_id)
        lines: list[BuildLineOut] = []
        total = 0
        for line in data.lines:
            snap = snapshots[line.sku_id]
            price = snap.uzs_amount_minor if usable(snap) else None
            line_sum = line_total(line.qty, price, Decimal(0)) if price is not None else None
            total += line_sum or 0
            lines.append(
                BuildLineOut(
                    sku_id=line.sku_id,
                    qty=line.qty,
                    title=snap.title,
                    role=line_role(categories.get(line.sku_id)),
                    unit_price_uzs_minor=price,
                    line_total_uzs_minor=line_sum,
                    sellable=usable(snap),
                    available=available.get(line.sku_id, 0),
                )
            )
        return BuildCheckOut(lines=lines, total_uzs_minor=total, compatibility=compat_out(result))

    async def candidates(self, db: AsyncSession, actor: ActorContext, data: CandidatesIn) -> CandidatesOut:
        """Slot (rol) uchun sotiladigan SKU'lar: har biri joriy yig'ma bilan tekshiriladi, mosi birinchi."""
        assert actor.shop_id is not None
        if data.role not in PC_ROLES:
            raise ValidationError("Role is not a PC part", fields=[field("role", "invalid_choice")])
        _unique(data.lines)
        if data.branch_id is not None:
            await load_branch(db, actor, data.branch_id)
        current = [line for line in data.lines]
        # Avval keng ro'yxat, keyin engine'siz saralash (atribut + mavjudlik), keyin engine — mos va omborda
        # bor nomzodlar nomi alfavitda keyin bo'lsa ham tushib qolmaydi (QA 6a F6)
        pool = await self.catalog.candidate_sku_ids(db, actor.shop_id, data.role, data.q, CANDIDATE_SCAN)
        existing = {line.sku_id for line in current}
        pool = [sku for sku in pool if sku not in existing]
        snapshots = await self.catalog.get_skus(db, actor.shop_id, pool)
        pool = [sku for sku in pool if usable(snapshots.get(sku))]
        available = await self._available(db, actor.shop_id, pool, data.branch_id)
        attributes = await self.catalog.spec_attributes(db, actor.shop_id, [*pool, *existing])
        roles = await self.catalog.sku_spec_categories(db, actor.shop_id, list(existing))
        build_attrs: dict[str, list[dict[str, Any]]] = {}
        for sku_id in existing:
            role = roles.get(sku_id)
            if role and sku_id in attributes:
                build_attrs.setdefault(role, []).append(attributes[sku_id])
        fit = {sku: prefilter(data.role, attributes.get(sku, {}), build_attrs) for sku in pool}
        pool.sort(
            key=lambda sku: (
                {True: 0, None: 1, False: 2}[fit[sku]],
                available.get(sku, 0) <= 0,
                snapshots[sku].uzs_amount_minor or 0,
            )
        )
        if data.only_compatible:
            pool = [sku for sku in pool if fit[sku] is not False]
        pool = pool[:CANDIDATE_POOL]
        items: list[CandidateOut] = []
        base = [BuildLine(sku_id=line.sku_id, quantity=line.qty) for line in current]
        locale = get_display_locale()
        for sku in pool:
            result = await self.catalog.check_compatibility(
                db, actor.shop_id, [*base, BuildLine(sku_id=sku, quantity=1)], locale, full_build=False
            )
            if data.only_compatible and result.decision == "BLOCK":
                continue
            snap = snapshots[sku]
            assert snap.uzs_amount_minor is not None
            related = [f for f in result.findings if str(sku) in f.parts or not f.parts]
            items.append(
                CandidateOut(
                    sku_id=sku,
                    product_id=snap.product_id,
                    title=snap.title,
                    sku_code=snap.sku_code,
                    unit_price_uzs_minor=snap.uzs_amount_minor,
                    available=available.get(sku, 0),
                    decision=result.decision,
                    findings=findings_out(result) if related else [],
                )
            )
        # Mos → mavjud → arzon (tanlash qulay); BLOCK oxirida (sababi ko'rinadi)
        items.sort(key=lambda c: (DECISION_ORDER[c.decision], c.available <= 0, c.unit_price_uzs_minor))
        return CandidatesOut(role=data.role, items=items[: data.limit])

    async def _available(
        self, db: AsyncSession, shop_id: UUID, sku_ids: list[UUID], branch_id: UUID | None
    ) -> dict[UUID, int]:
        if not sku_ids:
            return {}
        found = await self.stock.availability(db, shop_id, sku_ids)
        result: dict[UUID, int] = {}
        for sku_id, item in found.items():
            if branch_id is None:
                result[sku_id] = item.available
            else:
                branch = next((b for b in item.pickup_branches if b.branch_id == branch_id), None)
                result[sku_id] = branch.available if branch else 0
        return result


def _unique(lines: Sequence[BuildLineIn]) -> None:
    seen: set[UUID] = set()
    for index, line in enumerate(lines):
        sku = line.sku_id
        if sku in seen:
            raise ValidationError("Duplicate SKU", fields=[field(f"lines[{index}].sku_id", "not_unique")])
        seen.add(sku)
