"""Birinchi platforma adminini yaratish (shopsiz — hech kim taklif qila olmaydi).

    uv run python -m app.platform.staff.cli create-platform-admin --phone +998901234567 --name "Ism Familiya"

Parol `PLATFORM_ADMIN_PASSWORD` dan yoki so'rab olinadi (ekranda ko'rinmaydi).
"""

from __future__ import annotations

import argparse
import asyncio
import getpass
import os
import sys

from sqlalchemy import select

from app.config.settings import Settings
from app.platform.audit.services.audit_service import AuditService
from app.platform.auth.passwords import PasswordHasher, validate_new_password
from app.platform.staff.models.orm import PLATFORM_ROLES, PlatformStaff, Principal
from app.shared.clock import utcnow
from app.shared.db.session import Database
from app.shared.errors.base import DomainError
from app.shared.phone import normalize_phone
from app.shared.types.actor import ActorContext


async def create_platform_admin(
    settings: Settings, phone: str, full_name: str, password: str, role: str
) -> None:
    config = settings.auth_config()
    normalized = normalize_phone(phone)
    validate_new_password(password, normalized)
    hasher = PasswordHasher(config.argon2_time_cost, config.argon2_memory_kib, config.argon2_parallelism)
    database = Database(settings.database_config())
    try:
        async with database.transaction() as db:
            if (await db.execute(select(Principal.id).where(Principal.phone == normalized))).first():
                raise SystemExit(f"{normalized} allaqachon ro'yxatdan o'tgan")
            principal = Principal(
                phone=normalized,
                full_name=full_name,
                password_hash=await hasher.hash(password),
                phone_verified_at=utcnow(),
            )
            db.add(principal)
            await db.flush()
            db.add(PlatformStaff(principal_id=principal.id, role=role))
            await AuditService().record(
                db,
                action="platform.staff.created",
                entity_type="platform.principal",
                entity_id=principal.id,
                actor=ActorContext.system(),
                diff={"role": {"old": None, "new": role}},
            )
    finally:
        await database.dispose()


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="app.platform.staff.cli")
    sub = parser.add_subparsers(dest="command", required=True)
    create = sub.add_parser("create-platform-admin")
    create.add_argument("--phone", required=True)
    create.add_argument("--name", required=True)
    create.add_argument("--role", default="PLATFORM_ADMIN", choices=PLATFORM_ROLES)
    args = parser.parse_args(argv)

    password = os.environ.get("PLATFORM_ADMIN_PASSWORD") or getpass.getpass("Parol: ")
    if "PLATFORM_ADMIN_PASSWORD" not in os.environ and getpass.getpass("Parol (yana): ") != password:
        sys.exit("Parollar mos emas")
    try:
        asyncio.run(create_platform_admin(Settings(), args.phone, args.name, password, args.role))
    except DomainError as exc:
        sys.exit(f"Xato: {exc.code} {exc.details}")
    print("Platforma admini yaratildi")  # noqa: T201 — CLI chiqishi


if __name__ == "__main__":
    main()
