"""platform/staff moduli: xodimlar, a'zolik, havolalar; platforma jamoasi (business/04, 15; DEC-131)."""

from __future__ import annotations

from app.platform.staff.api.platform_team_routes import router as platform_team_router
from app.platform.staff.api.routes import router
from app.platform.staff.state_machine import MEMBERSHIP_RULES
from app.shared.types.manifest import DomainManifest

MODULE_MANIFEST = DomainManifest(
    name="staff",
    schema_name="platform",
    routers={"shop": router, "platform": platform_team_router},
    state_machine_rules=MEMBERSHIP_RULES,
    role_grants={  # 10 §6.1, DEC-131
        "OWNER": frozenset(
            {
                "staff.member.view",
                "staff.member.invite",
                "staff.member.edit_roles",
                "staff.member.disable",
                "staff.member.password_reset",
                "staff.task.view",
                "staff.task.assign",
            }
        ),
        "MANAGER": frozenset({"staff.member.view", "staff.task.view", "staff.task.assign"}),
        "SALES": frozenset({"staff.task.view"}),
        "WAREHOUSE": frozenset({"staff.task.view"}),
    },
)
