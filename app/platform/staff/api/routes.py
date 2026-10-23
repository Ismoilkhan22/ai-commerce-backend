"""Shop paneli: xodimlar (11 §9.2). Faqat ega boshqaradi, menejer ko'radi (business/04, DEC-131)."""

from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Response, status

from app.platform.staff.infrastructure.guard import RequestContext, require_permission
from app.platform.staff.infrastructure.providers import staff_service
from app.platform.staff.schemas import (
    AccessUpdate,
    DisableIn,
    InviteIn,
    InviteOut,
    LinkOut,
    MemberList,
    MemberOut,
)
from app.platform.staff.services.staff_service import StaffService
from app.shared.http import etag, require_if_match
from app.shared.idempotency.dependency import get_idempotency_key
from app.shared.idempotency.helpers import run_idempotent

router = APIRouter(prefix="/members", tags=["staff"])

Staff = Annotated[StaffService, Depends(staff_service)]
IdemKey = Annotated[str, Depends(get_idempotency_key)]


@router.get("", response_model=MemberList)
async def list_members(
    ctx: Annotated[RequestContext, Depends(require_permission("staff.member.view"))], svc: Staff
) -> MemberList:
    return MemberList(items=await svc.list_members(ctx.db, ctx.actor))


@router.post("/invites", response_model=InviteOut, status_code=status.HTTP_201_CREATED)
async def invite_member(
    body: InviteIn,
    ctx: Annotated[RequestContext, Depends(require_permission("staff.member.invite"))],
    svc: Staff,
    key: IdemKey,
) -> Any:
    async def replay(saved: Any) -> InviteOut:
        # Havola bazada saqlanmagan — takroriy so'rovga yangisi (eskisi bekor)
        link = await svc.resend_invite(ctx.db, ctx.actor, UUID(saved["member"]["id"]))
        return InviteOut(member=MemberOut.model_validate(saved["member"]), invite=link)

    return await run_idempotent(
        ctx.db,
        ctx.actor.shop_id,
        "staff.member.invite",
        key,
        body,
        lambda: svc.invite(ctx.db, ctx.actor, body),
        stored=lambda out: {"member": out.member},
        on_replay=replay,
        status=201,
    )


@router.post("/{membership_id}/invites", response_model=LinkOut)
async def resend_invite(
    membership_id: UUID,
    ctx: Annotated[RequestContext, Depends(require_permission("staff.member.invite"))],
    svc: Staff,
    _: IdemKey,
) -> LinkOut:
    # Har chaqiruv yangi havola beradi va eskisini bekor qiladi — takrorlansa ham xavfsiz
    return await svc.resend_invite(ctx.db, ctx.actor, membership_id)


@router.put("/{membership_id}/roles", response_model=MemberOut)
async def update_access(
    membership_id: UUID,
    body: AccessUpdate,
    response: Response,
    ctx: Annotated[RequestContext, Depends(require_permission("staff.member.edit_roles"))],
    svc: Staff,
    version: Annotated[int, Depends(require_if_match)],
) -> MemberOut:
    member = await svc.update_access(ctx.db, ctx.actor, membership_id, version, body)
    response.headers["ETag"] = etag(member.version)
    return member


@router.post("/{membership_id}/disable", response_model=MemberOut)
async def disable_member(
    membership_id: UUID,
    body: DisableIn,
    ctx: Annotated[RequestContext, Depends(require_permission("staff.member.disable"))],
    svc: Staff,
    key: IdemKey,
) -> Any:
    return await run_idempotent(
        ctx.db,
        ctx.actor.shop_id,
        f"staff.member.disable:{membership_id}",
        key,
        body,
        lambda: svc.disable(ctx.db, ctx.actor, membership_id, body.reason),
    )


@router.post("/{membership_id}/password-reset", response_model=LinkOut)
async def issue_password_reset(
    membership_id: UUID,
    ctx: Annotated[RequestContext, Depends(require_permission("staff.member.password_reset"))],
    svc: Staff,
    _: IdemKey,
) -> LinkOut:
    # Yangi havola eskisini bekor qiladi — takrorlansa ham xavfsiz; havola bazada saqlanmaydi
    return await svc.issue_password_reset(ctx.db, ctx.actor, membership_id)
