"""Migratsiya tekshiruvlari (07 §11.2, TC-DB-05): schemalar orasida FK yo'q."""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.db.schemas import SCHEMAS

_CROSS_SCHEMA_FK = text(
    """
    SELECT con.conname, src_ns.nspname AS src_schema, dst_ns.nspname AS dst_schema
    FROM pg_constraint con
    JOIN pg_class src ON src.oid = con.conrelid
    JOIN pg_namespace src_ns ON src_ns.oid = src.relnamespace
    JOIN pg_class dst ON dst.oid = con.confrelid
    JOIN pg_namespace dst_ns ON dst_ns.oid = dst.relnamespace
    WHERE con.contype = 'f'
      AND src_ns.nspname = ANY(:schemas)
      AND src_ns.nspname <> dst_ns.nspname
    """
)


async def cross_schema_foreign_keys(conn: AsyncConnection) -> list[tuple[str, str, str]]:
    rows = await conn.execute(_CROSS_SCHEMA_FK, {"schemas": list(SCHEMAS)})
    return [(r.conname, r.src_schema, r.dst_schema) for r in rows]
