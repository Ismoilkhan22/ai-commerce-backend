"""Qatlam va domen chegaralarini AST orqali tekshirish (ADR-031, ADR-032).

import-linter qatlamlarni tekshiradi; domenlar soni o'zgaruvchan bo'lgani uchun
"domen boshqa domenni import qilmaydi" qoidasi shu yerda tekshiriladi.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path

# Composition root: domenlarni import qila oladigan yagona joylar (02 §2).
COMPOSITION_ROOTS = (
    "app.dependencies",
    "app.workers",
    "app.main",
    "app.db",
)  # app.db.models domenlarni yuklaydi


@dataclass(frozen=True)
class Violation:
    file: Path
    line: int
    imported: str
    rule: str

    def __str__(self) -> str:
        return f"{self.file}:{self.line}: imports {self.imported!r} — {self.rule}"


def module_name(file: Path, root: Path) -> str:
    rel = file.relative_to(root).with_suffix("")
    parts = list(rel.parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def imported_modules(file: Path, module: str) -> list[tuple[int, str]]:
    """Fayldagi barcha importlarni to'liq nom bilan qaytaradi (nisbiy importlar ham)."""
    tree = ast.parse(file.read_text(encoding="utf-8"), filename=str(file))
    is_package = file.name == "__init__.py"
    package_parts = module.split(".") if is_package else module.split(".")[:-1]
    result: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            result.extend((node.lineno, alias.name) for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                base_parts = package_parts[: len(package_parts) - (node.level - 1)]
                base = ".".join(base_parts)
                target = f"{base}.{node.module}" if node.module else base
            else:
                target = node.module or ""
            result.append((node.lineno, target))
            # `from app.domains import catalog` — catalog ham modul bo'lishi mumkin
            result.extend((node.lineno, f"{target}.{alias.name}") for alias in node.names)
    return result


def _is_within(name: str, prefix: str) -> bool:
    return name == prefix or name.startswith(prefix + ".")


def check_boundaries(root: Path, package: str = "app") -> list[Violation]:
    """`root` — `app` paketi joylashgan papka (repo ildizi)."""
    violations: list[Violation] = []
    seen: set[tuple[Path, int, str]] = set()
    for file in sorted((root / package).rglob("*.py")):
        module = module_name(file, root)
        rel = file.relative_to(root)
        for line, imported in imported_modules(file, module):
            if not _is_within(imported, package):
                continue
            rule = _rule_for(module, imported, package)
            # `from a.b import c` ikki yozuv beradi (a.b va a.b.c) — bitta qatorga bitta xato
            if rule and (rel, line, rule) not in seen:
                seen.add((rel, line, rule))
                violations.append(Violation(rel, line, imported, rule))
    return violations


def _rule_for(module: str, imported: str, package: str) -> str | None:
    shared, platform, domains = f"{package}.shared", f"{package}.platform", f"{package}.domains"
    roots = tuple(r.replace("app", package, 1) for r in COMPOSITION_ROOTS)

    if _is_within(module, shared):
        if not _is_within(imported, shared):
            return "shared hech kimni import qilmaydi (prinsip 1)"
    elif _is_within(module, platform):
        if _is_within(imported, domains) or any(_is_within(imported, r) for r in roots):
            return "platform domains va composition root'ni import qilmaydi (prinsip 2)"
    elif _is_within(module, domains):
        own = ".".join(module.split(".")[:3])  # app.domains.<x>
        if any(_is_within(imported, r) for r in roots):
            return "domen composition root'ni import qilmaydi (prinsip 3)"
        if _is_within(imported, domains) and imported != domains and not _is_within(imported, own):
            return "domen boshqa domenni import qilmaydi — event yoki Query Port (prinsip 3-4, ADR-032)"
    return None
