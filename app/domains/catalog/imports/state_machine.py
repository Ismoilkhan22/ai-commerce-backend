"""Katalog importi holatlari (18 §10, db/catalog_import.md §1).

    PARSING ──(worker faylni o'qidi)──▶ UPLOADED;  PARSING ──(o'qib bo'lmadi)──▶ FAILED
    UPLOADED ──(moslash)──▶ MAPPED ──(sinov)──▶ VALIDATING ──▶ VALIDATED
    VALIDATED ──(qayta moslash)──▶ MAPPED
    VALIDATED ──(tasdiq)──▶ COMMITTING ──(katalog qismi tugadi)──▶ STOCK_PENDING
    STOCK_PENDING ──(commerce qo'lladi)──▶ COMPLETED
    COMMITTING ──(qoldiq yo'q)──▶ COMPLETED
    VALIDATING / COMMITTING / STOCK_PENDING ──(xato)──▶ FAILED
    PARSING / UPLOADED / MAPPED / VALIDATED ──(xodim bekor qildi)──▶ CANCELLED
    VALIDATED ──(24 soat tasdiqlanmadi)──▶ EXPIRED

Fon bosqichlari (sinov, yozish, qoldiq) xodim nomidan ham, tizim nomidan ham o'tadi.
"""

from __future__ import annotations

from app.shared.types.state import StateMachineRule

ENTITY = "catalog.import_batch"


def _rule(command: str, src: str, dst: str, *, system: bool = False) -> StateMachineRule:
    return StateMachineRule(
        entity_type=ENTITY,
        command=command,
        from_status=src,
        to_status=dst,
        actors=frozenset({"STAFF", "SYSTEM"} if system else {"STAFF"}),
        business_ref="18 §10",
    )


IMPORT_RULES = [
    _rule("PARSE", "PARSING", "UPLOADED", system=True),
    _rule("FAIL", "PARSING", "FAILED", system=True),
    _rule("CANCEL", "PARSING", "CANCELLED"),
    _rule("MAP", "UPLOADED", "MAPPED"),
    _rule("MAP", "MAPPED", "MAPPED"),
    _rule("MAP", "VALIDATED", "MAPPED"),
    _rule("VALIDATE", "MAPPED", "VALIDATING"),
    _rule("FINISH_VALIDATION", "VALIDATING", "VALIDATED", system=True),
    _rule("COMMIT", "VALIDATED", "COMMITTING"),
    _rule("AWAIT_STOCK", "COMMITTING", "STOCK_PENDING", system=True),
    _rule("COMPLETE", "COMMITTING", "COMPLETED", system=True),
    _rule("COMPLETE", "STOCK_PENDING", "COMPLETED", system=True),
    _rule("FAIL", "VALIDATING", "FAILED", system=True),
    _rule("FAIL", "COMMITTING", "FAILED", system=True),
    _rule("FAIL", "STOCK_PENDING", "FAILED", system=True),
    _rule("CANCEL", "UPLOADED", "CANCELLED"),
    _rule("CANCEL", "MAPPED", "CANCELLED"),
    _rule("CANCEL", "VALIDATED", "CANCELLED"),
    _rule("EXPIRE", "VALIDATED", "EXPIRED", system=True),
]
