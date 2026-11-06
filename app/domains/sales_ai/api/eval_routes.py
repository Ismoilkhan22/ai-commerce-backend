"""Platforma paneli: AI baholash — `/api/v1/platform/ai-eval/*` (6c, 16 §5, A15).

Ko'rish (`platform.ai_eval.view`) va boshqarish (`platform.ai_eval.manage`, LLM xarajati bor) — faqat
platforma admini. Yaratish va ishga tushirish — `Idempotency-Key`; to'plamni tahrirlash — `If-Match`
(`revision`). Yugurish holati realtime signal (`ai_eval.run.changed`, faqat ID va sonlar) yoki so'rov bilan.
"""

from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response, status

from app.domains.sales_ai.eval.schemas import (
    BakeoffIn,
    BakeoffOut,
    CompareOut,
    DatasetDetail,
    DatasetIn,
    DatasetList,
    DatasetPatch,
    QualityOut,
    ResultList,
    RunIn,
    RunList,
    RunOut,
    RunStatus,
)
from app.domains.sales_ai.providers import SalesAiServices, sales_ai_services
from app.platform.staff.infrastructure.guard import RequestContext, require_platform_permission
from app.shared.db.session import Database
from app.shared.http import etag, require_if_match, result_field, set_location
from app.shared.idempotency.dependency import get_idempotency_key
from app.shared.idempotency.helpers import run_idempotent

VIEW = "platform.ai_eval.view"
MANAGE = "platform.ai_eval.manage"

router = APIRouter(prefix="/ai-eval", tags=["platform", "ai_eval"])

SalesAi = Annotated[SalesAiServices, Depends(sales_ai_services)]
IdemKey = Annotated[str, Depends(get_idempotency_key)]
IfMatch = Annotated[int, Depends(require_if_match)]
CanView = Annotated[RequestContext, Depends(require_platform_permission(VIEW))]
CanManage = Annotated[RequestContext, Depends(require_platform_permission(MANAGE))]


# ------------------------------------------------------------------ to'plamlar
@router.get("/datasets", response_model=DatasetList)
async def list_datasets(ctx: CanView, svc: SalesAi, include_archived: bool = False) -> DatasetList:
    return await svc.eval.list_datasets(ctx.db, include_archived=include_archived)


@router.post("/datasets", response_model=DatasetDetail, status_code=status.HTTP_201_CREATED)
async def create_dataset(
    body: DatasetIn, request: Request, response: Response, ctx: CanManage, svc: SalesAi, key: IdemKey
) -> Any:
    """Yangi to'plam (yoki mavjud `key` ning keyingi versiyasi). Holatlar kutilmalari bilan."""
    out = await run_idempotent(
        ctx.db,
        None,
        "sales_ai.eval.dataset.create",
        key,
        body,
        lambda: svc.eval.create_dataset(ctx.db, ctx.actor, body),
        status=201,
    )
    set_location(request, response, "get_eval_dataset", dataset_id=result_field(out))
    return out


@router.post("/datasets/golden", response_model=DatasetDetail)
async def install_golden(response: Response, ctx: CanManage, svc: SalesAi) -> DatasetDetail:
    """Kodda yozilgan boshlang'ich golden to'plamni (40 holat, muzlatilgan) o'rnatadi. Takroriy chaqiruv —
    o'sha to'plam (200); birinchi marta — 201."""
    out, created = await svc.eval.install_golden(ctx.db, ctx.actor)
    response.status_code = status.HTTP_201_CREATED if created else status.HTTP_200_OK
    return out


@router.get("/datasets/{dataset_id}", response_model=DatasetDetail, name="get_eval_dataset")
async def get_dataset(dataset_id: UUID, response: Response, ctx: CanView, svc: SalesAi) -> DatasetDetail:
    out = await svc.eval.get_dataset(ctx.db, dataset_id)
    response.headers["ETag"] = etag(out.revision)
    return out


@router.patch("/datasets/{dataset_id}", response_model=DatasetDetail)
async def update_dataset(
    dataset_id: UUID, body: DatasetPatch, response: Response, ctx: CanManage, svc: SalesAi, revision: IfMatch
) -> DatasetDetail:
    """Muzlatilmagan to'plam. Holatlar faqat yugurishi yo'q to'plamda almashtiriladi; `frozen: true` —
    bir tomonlama."""
    out = await svc.eval.patch_dataset(ctx.db, ctx.actor, dataset_id, revision, body)
    response.headers["ETag"] = etag(out.revision)
    return out


@router.post(
    "/datasets/{dataset_id}/clone", response_model=DatasetDetail, status_code=status.HTTP_201_CREATED
)
async def clone_dataset(dataset_id: UUID, ctx: CanManage, svc: SalesAi, key: IdemKey) -> Any:
    """Shu `key` ning yangi (muzlatilmagan) versiyasi — muzlatilgan to'plamni o'zgartirish yo'li."""
    return await run_idempotent(
        ctx.db,
        None,
        f"sales_ai.eval.dataset.clone:{dataset_id}",
        key,
        None,
        lambda: svc.eval.clone_dataset(ctx.db, ctx.actor, dataset_id),
        status=201,
    )


@router.delete("/datasets/{dataset_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_dataset(dataset_id: UUID, ctx: CanManage, svc: SalesAi) -> Response:
    """Yugurishi yo'q — o'chiriladi; bor — arxivlanadi (natijalar saqlanadi)."""
    await svc.eval.delete_dataset(ctx.db, ctx.actor, dataset_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ------------------------------------------------------------------ yugurishlar
@router.post("/runs", response_model=RunOut, status_code=status.HTTP_202_ACCEPTED)
async def start_run(body: RunIn, ctx: CanManage, svc: SalesAi, key: IdemKey) -> Any:
    """To'plamni tanlangan provayder/model bilan yuritadi (fon ishi). Holat — `GET /runs/{id}`."""
    return await run_idempotent(
        ctx.db,
        None,
        "sales_ai.eval.run.start",
        key,
        body,
        lambda: svc.eval.start_run(ctx.db, ctx.actor, body),
        status=202,
    )


@router.post("/bakeoffs", response_model=BakeoffOut, status_code=status.HTTP_202_ACCEPTED)
async def start_bakeoff(body: BakeoffIn, ctx: CanManage, svc: SalesAi, key: IdemKey) -> Any:
    """Bake-off (A15): bir xil to'plam, nishon va judge bilan ikki yugurish. Natija —
    `GET /compare?base=…&candidate=…`."""
    return await run_idempotent(
        ctx.db,
        None,
        "sales_ai.eval.bakeoff.start",
        key,
        body,
        lambda: svc.eval.start_bakeoff(ctx.db, ctx.actor, body),
        status=202,
    )


@router.get("/runs", response_model=RunList)
async def list_runs(
    ctx: CanView,
    svc: SalesAi,
    dataset_id: UUID | None = None,
    bakeoff_id: UUID | None = None,
    status: RunStatus | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0, le=100_000)] = 0,
) -> RunList:
    return await svc.eval.list_runs(
        ctx.db, dataset_id=dataset_id, bakeoff_id=bakeoff_id, status=status, limit=limit, offset=offset
    )


@router.get("/runs/{run_id}", response_model=RunOut)
async def get_run(run_id: UUID, ctx: CanView, svc: SalesAi) -> RunOut:
    return await svc.eval.get_run(ctx.db, run_id)


@router.get("/runs/{run_id}/results", response_model=ResultList)
async def run_results(run_id: UUID, ctx: CanView, svc: SalesAi, failed_only: bool = False) -> ResultList:
    """Har holat: o'tdimi, xato kodlari (nol toqat alohida), tool'lar, javob (redact), judge, vaqt, narx;
    muvaffaqiyatsiz holatda — tool izi."""
    return await svc.eval.results(ctx.db, run_id, failed_only=failed_only)


@router.post("/runs/{run_id}/cancel", response_model=RunOut)
async def cancel_run(run_id: UUID, ctx: CanManage, svc: SalesAi) -> RunOut:
    return await svc.eval.cancel(ctx.db, ctx.actor, run_id)


@router.get("/compare", response_model=CompareOut)
async def compare_runs(base: UUID, candidate: UUID, ctx: CanView, svc: SalesAi) -> CompareOut:
    """Bake-off hisoboti: umumiy farqlar (o'tish ulushi, nol toqat, tool/handoff aniqligi, judge, latency,
    narx), kategoriya va til bo'yicha, har holat (REGRESSION / IMPROVEMENT / …)."""
    return await svc.eval.compare(ctx.db, base, candidate)


# ------------------------------------------------------------------ production sifati (shop bo'yicha)
@router.get("/quality/{shop_id}", response_model=QualityOut)
async def shop_quality(
    shop_id: UUID,
    request: Request,
    ctx: CanView,
    svc: SalesAi,
    days: Annotated[int, Query(ge=1, le=90)] = 30,
) -> QualityOut:
    """Shop "AI sifati" — platforma ko'rinishi (shop paneli bilan bir xil ma'lumot)."""
    database: Database = request.app.state.db
    async with database.transaction(shop_id) as db:
        return await svc.quality.quality(db, shop_id, days)
