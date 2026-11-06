"""Shop paneli: katalog importi (18 §13).

POST /shop/files?purpose=IMPORT_FILE  (fayl baytlari)  →  POST /catalog/imports {file_id}
PUT  /catalog/imports/{id}/mapping   →  POST .../dry-run  →  GET .../rows  →  POST .../commit
"""

from __future__ import annotations

from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Path, Query, Request, Response, status

from app.domains.catalog.imports.parsing import MAX_ROWS
from app.domains.catalog.imports.schemas import (
    ImportCreateIn,
    ImportList,
    ImportMappingIn,
    ImportMappingList,
    ImportOut,
    ImportReportOut,
    ImportRowOut,
    ImportRowPage,
    ImportRowUpdate,
    RowAction,
)
from app.domains.catalog.imports.services.import_service import ImportService
from app.domains.catalog.providers import catalog_services
from app.platform.staff.infrastructure.guard import RequestContext, require_permission
from app.shared.http import etag, require_if_match, result_field, set_location
from app.shared.idempotency.dependency import get_idempotency_key
from app.shared.idempotency.helpers import run_idempotent

router = APIRouter(prefix="/catalog/imports", tags=["catalog-import"])


def import_service(request: Request) -> ImportService:
    return catalog_services(request).imports


Imports = Annotated[ImportService, Depends(import_service)]
CanImport = Annotated[RequestContext, Depends(require_permission("catalog.import.run"))]
IdemKey = Annotated[str, Depends(get_idempotency_key)]
IfMatch = Annotated[int, Depends(require_if_match)]


def _etag(response: Response, out: ImportOut) -> ImportOut:
    response.headers["ETag"] = etag(out.version)
    return out


@router.post("", response_model=ImportOut, status_code=status.HTTP_201_CREATED)
async def create_import(
    body: ImportCreateIn, request: Request, response: Response, ctx: CanImport, svc: Imports, key: IdemKey
) -> Any:
    """Arzon tekshiruv (tur, ZIP katalogi, varaq o'lchami, kodirovka) va import `PARSING` holatida ochiladi;
    fayl fonda o'qiladi → `UPLOADED` (ustunlar, moslash taklifi, qatorlar soni). Arzon tekshiruvdan o'tmasa —
    422 IMPORT_FILE_INVALID (`details.reason`); fonda o'qib bo'lmasa — `FAILED`, `error_code` = sabab."""

    async def replay(body: Any) -> ImportOut:
        return await svc.get(ctx.db, ctx.actor, UUID(str(body["id"])))

    out = await run_idempotent(
        ctx.db,
        ctx.actor.shop_id,
        "catalog.import.create",
        key,
        body,
        lambda: svc.create(ctx.db, ctx.actor, body.file_id),
        stored=lambda o: {"id": str(o.id)},
        on_replay=replay,
        status=201,
    )
    set_location(request, response, "get_import", import_id=result_field(out))
    return out


@router.get("", response_model=ImportList)
async def list_imports(ctx: CanImport, svc: Imports) -> ImportList:
    """Oxirgi 20 ta import (tarix)."""
    return await svc.list_imports(ctx.db, ctx.actor)


@router.get("/mappings", response_model=ImportMappingList)
async def list_import_mappings(ctx: CanImport, svc: Imports) -> ImportMappingList:
    return await svc.mappings(ctx.db, ctx.actor)


@router.get("/template", response_class=Response)
async def import_template(
    ctx: CanImport, format: Annotated[Literal["csv", "xlsx"], Query()] = "xlsx"
) -> Response:
    """Namuna fayl: ustunlar foydalanuvchi tilida va bitta misol qator."""
    data, mime = ImportService.template(ctx.actor.locale, format)
    return Response(
        content=data,
        media_type=mime,
        headers={"Content-Disposition": f'attachment; filename="import-template.{format}"'},
    )


@router.get("/{import_id}", response_model=ImportOut)
async def get_import(import_id: UUID, response: Response, ctx: CanImport, svc: Imports) -> ImportOut:
    return _etag(response, await svc.get(ctx.db, ctx.actor, import_id))


@router.get("/{import_id}/rows", response_model=ImportRowPage)
async def list_import_rows(
    import_id: UUID,
    ctx: CanImport,
    svc: Imports,
    action: RowAction | None = None,
    errors_only: bool = False,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    cursor: Annotated[str | None, Query(max_length=200)] = None,
) -> ImportRowPage:
    return await svc.rows(
        ctx.db, ctx.actor, import_id, action=action, errors_only=errors_only, limit=limit, cursor=cursor
    )


@router.put("/{import_id}/mapping", response_model=ImportOut)
async def set_import_mapping(
    import_id: UUID, body: ImportMappingIn, response: Response, ctx: CanImport, svc: Imports, version: IfMatch
) -> ImportOut:
    """Ustunlar va to'qnashuv siyosati. Sinovdan keyin qayta moslash — eski natija o'chadi."""
    return _etag(response, await svc.set_mapping(ctx.db, ctx.actor, import_id, version, body))


@router.post("/{import_id}/dry-run", response_model=ImportOut, status_code=status.HTTP_202_ACCEPTED)
async def start_import_dry_run(
    import_id: UUID, response: Response, ctx: CanImport, svc: Imports, version: IfMatch
) -> ImportOut:
    """Sinov fonda ishlaydi (hech narsa yozilmaydi): holat `VALIDATING` → `VALIDATED`. Natija —
    `GET .../rows`. Shopda boshqa faol import bo'lsa — 409 IMPORT_ALREADY_RUNNING."""
    return _etag(response, await svc.start_dry_run(ctx.db, ctx.actor, import_id, version))


@router.patch("/{import_id}/rows/{row_number}", response_model=ImportRowOut)
async def update_import_row(
    import_id: UUID,
    row_number: Annotated[int, Path(ge=1, le=MAX_ROWS + 1)],  # int4 doirasida — 422, 500 emas (QA F6)
    body: ImportRowUpdate,
    ctx: CanImport,
    svc: Imports,
) -> ImportRowOut:
    """Ko'rib chiqishda: qatorni yozishdan chiqarish yoki bir nechta nomzoddan kutubxona modelini tanlash."""
    return await svc.update_row(ctx.db, ctx.actor, import_id, row_number, body)


@router.post("/{import_id}/commit", response_model=ImportOut, status_code=status.HTTP_202_ACCEPTED)
async def commit_import(
    import_id: UUID, response: Response, ctx: CanImport, svc: Imports, key: IdemKey, version: IfMatch
) -> Any:
    """Tasdiq: yozish fonda, 500 qatorlik bo'laklarda (qoralama mahsulot, SKU, narx versiyasi), keyin
    qoldiq — commerce (kirim yoki tuzatish)."""

    async def replay(body: Any) -> ImportOut:
        return await svc.get(ctx.db, ctx.actor, import_id)

    out = await run_idempotent(
        ctx.db,
        ctx.actor.shop_id,
        f"catalog.import.commit:{import_id}",
        key,
        {"if_match": version},
        lambda: svc.commit(ctx.db, ctx.actor, import_id, version),
        stored=lambda o: {"id": str(o.id)},
        on_replay=replay,
        status=202,
    )
    return _etag(response, out) if isinstance(out, ImportOut) else out


@router.post("/{import_id}/cancel", response_model=ImportOut)
async def cancel_import(
    import_id: UUID, response: Response, ctx: CanImport, svc: Imports, version: IfMatch
) -> ImportOut:
    return _etag(response, await svc.cancel(ctx.db, ctx.actor, import_id, version))


@router.post("/{import_id}/error-report", response_model=ImportReportOut)
async def import_error_report(import_id: UUID, ctx: CanImport, svc: Imports) -> ImportReportOut:
    """Xato qatorlari CSV'si (asl ustunlar + xato kodi va izoh) — yopiq fayl, vaqtinchalik imzoli havola."""
    return await svc.errors_report(ctx.db, ctx.actor, import_id)
