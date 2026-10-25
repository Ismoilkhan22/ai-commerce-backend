"""Ochiq manzil: `GET /api/v1/public/files/{object_key}` — dev va testda fayllar shu yerdan beriladi.

Production'da ochiq rasmlar to'g'ridan-to'g'ri ombor/CDN'dan beriladi (S0-10); bu endpoint esa yopiq
fayllarning imzoli havolalari uchun qoladi. Fayl topilmasa, o'chirilgan bo'lsa yoki imzo noto'g'ri bo'lsa —
bir xil 404 (borligini bildirmaydi).
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query, Request, Response

from app.platform.storage.providers import file_service
from app.platform.storage.services.file_service import shop_id_from_key
from app.shared.db.session import Database, set_identity_context
from app.shared.errors.base import NotFoundError

router = APIRouter(prefix="/files", tags=["files"])

_PUBLIC_CACHE = "public, max-age=31536000, immutable"  # manzil o'zgarmaydi — fayl almashsa, yangi kalit


@router.get("/{object_key:path}", response_class=Response, responses={200: {"content": {"image/*": {}}}})
async def serve_file(
    object_key: str,
    request: Request,
    exp: Annotated[int | None, Query()] = None,
    sig: Annotated[str | None, Query(max_length=128)] = None,
) -> Response:
    shop_id = shop_id_from_key(object_key)
    if shop_id is None:
        raise NotFoundError("File not found")
    database: Database = request.app.state.db
    async with database.transaction(read_only=True) as db:
        await set_identity_context(db, shop_id=shop_id)  # stored_files RLS: faqat shu shop fayllari
        served = await file_service(request).serve(db, object_key, exp, sig)
    if served is None:
        raise NotFoundError("File not found")
    return Response(
        content=served.data,
        media_type=served.mime_type,
        headers={
            "Cache-Control": _PUBLIC_CACHE if served.is_public else "private, no-store",
            "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": "default-src 'none'; sandbox",
        },
    )
