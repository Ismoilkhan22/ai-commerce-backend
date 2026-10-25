"""Shop paneli: fayl yuklash va havola olish (S0-08).

Fayl so'rov tanasining o'zida keladi (multipart emas): `POST /files?purpose=PRODUCT_IMAGE&filename=a.jpg`,
tana — fayl baytlari. Turi Content-Type'dan emas, fayl ichidan aniqlanadi.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response, status

from app.platform.auth.tokens import AccessClaims
from app.platform.staff.infrastructure.guard import ShopContext, shop_token_claims
from app.platform.storage.providers import file_service
from app.platform.storage.schemas import StoredFileOut, UploadPurpose
from app.platform.storage.services.file_service import FileService, purpose_rule
from app.shared.errors.base import PayloadTooLargeError
from app.shared.http import result_field, set_location
from app.shared.idempotency.dependency import get_idempotency_key
from app.shared.idempotency.helpers import run_idempotent

router = APIRouter(prefix="/files", tags=["files"])

Files = Annotated[FileService, Depends(file_service)]
IdemKey = Annotated[str, Depends(get_idempotency_key)]

_BINARY = {"schema": {"type": "string", "format": "binary"}}
_UPLOAD_BODY = {
    "requestBody": {
        "required": True,
        "description": "Fayl baytlari (JPEG, PNG yoki WebP; ko'pi bilan 5 MB)",
        "content": {
            "image/jpeg": _BINARY,
            "image/png": _BINARY,
            "image/webp": _BINARY,
            "application/octet-stream": _BINARY,
        },
    }
}


async def _read_limited(request: Request, max_bytes: int) -> bytes:
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > max_bytes:
        raise PayloadTooLargeError("File too large", max_bytes=max_bytes)
    chunks: list[bytes] = []
    size = 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > max_bytes:  # Content-Length yolg'on bo'lsa ham xotiraga cheksiz o'qilmaydi
            raise PayloadTooLargeError("File too large", max_bytes=max_bytes)
        chunks.append(chunk)
    return b"".join(chunks)


@dataclass(frozen=True)
class Upload:
    purpose: str
    data: bytes


async def _upload(
    request: Request,
    purpose: Annotated[UploadPurpose, Query()],
    _claims: Annotated[AccessClaims, Depends(shop_token_claims)],  # avval token (401), keyin tana
) -> Upload:
    return Upload(purpose, await _read_limited(request, purpose_rule(purpose).max_bytes))


@router.post(
    "", response_model=StoredFileOut, status_code=status.HTTP_201_CREATED, openapi_extra=_UPLOAD_BODY
)
async def upload_file(
    # Tana tranzaksiya ochilishidan OLDIN o'qiladi: sekin yuklash DB ulanishini band qilib turmasin
    upload: Annotated[Upload, Depends(_upload)],
    ctx: ShopContext,
    svc: Files,
    key: IdemKey,
    request: Request,
    response: Response,
    filename: Annotated[str | None, Query(max_length=255)] = None,
) -> Any:
    fingerprint = {
        "purpose": upload.purpose,
        "filename": filename,
        "sha256": hashlib.sha256(upload.data).hexdigest(),
    }
    stored = await run_idempotent(
        ctx.db,
        ctx.actor.shop_id,
        "storage.file.upload",
        key,
        fingerprint,
        lambda: svc.upload(ctx.db, ctx.actor, upload.purpose, upload.data, filename),
        status=201,
    )
    set_location(request, response, "get_file", file_id=result_field(stored))
    return stored


@router.get("/{file_id}", response_model=StoredFileOut)
async def get_file(file_id: UUID, ctx: ShopContext, svc: Files) -> StoredFileOut:
    """Fayl ma'lumoti va yangi havola (yopiq fayl havolasi 5 daqiqa amal qiladi)."""
    return await svc.get(ctx.db, ctx.actor, file_id)
