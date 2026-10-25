"""Platforma paneli: platforma jamoasi (business/15 §5, 11 §9.10). Boshqaradi — faqat platforma admini."""

from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Response, status

from app.platform.staff.infrastructure.guard import RequestContext, require_platform_permission
from app.platform.staff.infrastructure.providers import platform_team
from app.platform.staff.platform_schemas import (
    PlatformInviteIn,
    PlatformInviteOut,
    PlatformRoleUpdate,
    PlatformStaffList,
    PlatformStaffOut,
)
from app.platform.staff.schemas import DisableIn, LinkOut
from app.platform.staff.services.platform_team_service import PlatformTeamService
from app.shared.http import etag, require_if_match
from app.shared.idempotency.dependency import get_idempotency_key
from app.shared.idempotency.helpers import run_idempotent

router = APIRouter(prefix="/staff", tags=["platform"])

Team = Annotated[PlatformTeamService, Depends(platform_team)]
IdemKey = Annotated[str, Depends(get_idempotency_key)]
CanView = Annotated[RequestContext, Depends(require_platform_permission("platform.staff.view"))]
CanManage = Annotated[RequestContext, Depends(require_platform_permission("platform.staff.manage"))]


@router.get("", response_model=PlatformStaffList)
async def list_staff(ctx: CanView, team: Team) -> PlatformStaffList:
    return PlatformStaffList(items=await team.list_staff(ctx.db))


@router.post("/invites", response_model=PlatformInviteOut, status_code=status.HTTP_201_CREATED)
async def invite_staff(body: PlatformInviteIn, ctx: CanManage, team: Team, key: IdemKey) -> Any:
    async def replay(saved: Any) -> PlatformInviteOut:
        # Havola bazada saqlanmagan — takroriy so'rovga yangisi (eskisi bekor)
        member = PlatformStaffOut.model_validate(saved["member"])
        return PlatformInviteOut(member=member, invite=await team.resend_invite(ctx.db, ctx.actor, member.id))

    return await run_idempotent(
        ctx.db,
        None,
        "platform.staff.invite",
        key,
        body,
        lambda: team.invite(ctx.db, ctx.actor, body),
        stored=lambda out: {"member": out.member},
        on_replay=replay,
        status=201,
    )


@router.post("/{staff_id}/invite", response_model=LinkOut)
async def resend_staff_invite(staff_id: UUID, ctx: CanManage, team: Team, _: IdemKey) -> LinkOut:
    # Har chaqiruv yangi havola beradi va eskisini bekor qiladi — takrorlansa ham xavfsiz
    return await team.resend_invite(ctx.db, ctx.actor, staff_id)


@router.post("/{staff_id}/password-reset", response_model=LinkOut)
async def staff_password_reset(staff_id: UUID, ctx: CanManage, team: Team, _: IdemKey) -> LinkOut:
    return await team.issue_password_reset(ctx.db, ctx.actor, staff_id)


@router.put("/{staff_id}/role", response_model=PlatformStaffOut)
async def change_staff_role(
    staff_id: UUID,
    body: PlatformRoleUpdate,
    response: Response,
    ctx: CanManage,
    team: Team,
    version: Annotated[int, Depends(require_if_match)],
) -> PlatformStaffOut:
    member = await team.change_role(ctx.db, ctx.actor, staff_id, version, body.role)
    response.headers["ETag"] = etag(member.version)
    return member


@router.post("/{staff_id}/disable", response_model=PlatformStaffOut)
async def disable_staff(staff_id: UUID, body: DisableIn, ctx: CanManage, team: Team, key: IdemKey) -> Any:
    return await run_idempotent(
        ctx.db,
        None,
        f"platform.staff.disable:{staff_id}",
        key,
        body,
        lambda: team.disable(ctx.db, ctx.actor, staff_id, body.reason),
    )
