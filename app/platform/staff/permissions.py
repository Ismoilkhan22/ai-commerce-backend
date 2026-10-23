"""Rol → ruxsatlar (10 §6, DEC-131). Ro'yxat kodda, bazada emas: rollar hamma shop uchun bir xil.

Har modul o'z kodlarini `DomainManifest.role_grants` da e'lon qiladi; `PermissionRegistry`
ilova ishga tushganda ularni birlashtiradi.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping

from app.shared.types.manifest import DomainManifest

PLATFORM_ROLE_PERMISSIONS: Mapping[str, frozenset[str]] = {
    "PLATFORM_ADMIN": frozenset(
        {
            "platform.shop.view_meta",
            "platform.shop.create",
            "platform.shop.activate",
            "platform.shop.suspend",
            "platform.shop.close",
            "platform.member.password_reset",
            "platform.state.force",
            "platform.spec.edit",
        }
    ),
    "PLATFORM_SUPPORT": frozenset({"platform.shop.view_meta"}),
    "SPEC_EDITOR": frozenset({"platform.spec.edit"}),
}


class PermissionRegistry:
    def __init__(self, grants: Iterable[Mapping[str, frozenset[str]]]) -> None:
        merged: dict[str, set[str]] = {}
        for grant in grants:
            for role, codes in grant.items():
                merged.setdefault(role, set()).update(codes)
        self._by_role = {role: frozenset(codes) for role, codes in merged.items()}

    @classmethod
    def from_manifests(cls, manifests: Iterable[DomainManifest]) -> PermissionRegistry:
        return cls(m.role_grants for m in manifests)

    def for_role(self, role: str) -> frozenset[str]:
        return self._by_role.get(role, frozenset())

    def all_codes(self) -> frozenset[str]:
        return frozenset().union(*self._by_role.values()) if self._by_role else frozenset()
