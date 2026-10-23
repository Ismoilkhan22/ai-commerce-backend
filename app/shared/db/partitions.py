"""Oyma-oy RANGE partition'lar (transition_log, audit_entries — 07 §5.3).

Migratsiya boshlang'ich oylarni yaratadi; scheduler (S0-06) har oy 3 oy oldinga yaratib boradi,
shuning uchun DEFAULT partition bo'sh qolishi kerak.
"""

from __future__ import annotations

from datetime import date


def month_starts(first: date, count: int) -> list[date]:
    months, year, month = [], first.year, first.month
    for _ in range(count):
        months.append(date(year, month, 1))
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)
    return months


def monthly_partition_sql(
    schema: str, table: str, month: date, *, append_only_role: str | None = None
) -> list[str]:
    """Bitta oy partition'i. `append_only_role` berilsa — unga partition'da UPDATE/DELETE yo'q.

    Har buyruq alohida: asyncpg bitta so'rovda bir nechta SQL buyruqni bajarmaydi.
    """
    start = date(month.year, month.month, 1)
    end = date(start.year + (start.month == 12), start.month % 12 + 1, 1)
    child = f"{schema}.{table}_y{start.year}m{start.month:02d}"
    statements = [
        f"CREATE TABLE IF NOT EXISTS {child} PARTITION OF {schema}.{table} "
        f"FOR VALUES FROM ('{start.isoformat()}') TO ('{end.isoformat()}')"
    ]
    if append_only_role:
        statements.append(f"REVOKE UPDATE, DELETE, TRUNCATE ON {child} FROM {append_only_role}")
    return statements


def default_partition_sql(schema: str, table: str, *, append_only_role: str | None = None) -> list[str]:
    child = f"{schema}.{table}_default"
    statements = [f"CREATE TABLE IF NOT EXISTS {child} PARTITION OF {schema}.{table} DEFAULT"]
    if append_only_role:
        statements.append(f"REVOKE UPDATE, DELETE, TRUNCATE ON {child} FROM {append_only_role}")
    return statements
