"""S0-01 qabul mezoni: domen boshqa domenni import qilsa CI yiqiladi."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.architecture.boundaries import check_boundaries

REPO_ROOT = Path(__file__).resolve().parents[2]

pytestmark = pytest.mark.architecture


def test_real_codebase_respects_boundaries() -> None:
    violations = check_boundaries(REPO_ROOT)
    assert not violations, "\n".join(str(v) for v in violations)


def _write(root: Path, rel: str, body: str = "") -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")


@pytest.fixture
def fake_repo(tmp_path: Path) -> Path:
    for pkg in (
        "app",
        "app/shared",
        "app/platform",
        "app/platform/audit",
        "app/domains",
        "app/domains/catalog",
        "app/domains/commerce",
        "app/workers",
    ):
        _write(tmp_path, f"{pkg}/__init__.py")
    return tmp_path


def test_domain_importing_other_domain_is_rejected(fake_repo: Path) -> None:
    _write(fake_repo, "app/domains/commerce/service.py", "from app.domains.catalog import models\n")
    [violation] = check_boundaries(fake_repo)
    assert "boshqa domenni" in violation.rule


def test_relative_import_into_other_domain_is_rejected(fake_repo: Path) -> None:
    _write(fake_repo, "app/domains/commerce/service.py", "from ..catalog import models\n")
    [violation] = check_boundaries(fake_repo)
    assert violation.imported.startswith("app.domains.catalog")


def test_domain_may_import_itself_platform_and_shared(fake_repo: Path) -> None:
    _write(
        fake_repo,
        "app/domains/commerce/service.py",
        "from app.domains.commerce import x\nfrom app.platform.audit import y\nfrom app.shared import z\n"
        "from . import sibling\n",
    )
    assert check_boundaries(fake_repo) == []


def test_platform_importing_domain_is_rejected(fake_repo: Path) -> None:
    _write(fake_repo, "app/platform/audit/service.py", "import app.domains.commerce\n")
    [violation] = check_boundaries(fake_repo)
    assert "platform" in violation.rule


def test_shared_importing_platform_is_rejected(fake_repo: Path) -> None:
    _write(fake_repo, "app/shared/db.py", "from app.platform.audit import service\n")
    [violation] = check_boundaries(fake_repo)
    assert "shared" in violation.rule


def test_workers_may_import_domains(fake_repo: Path) -> None:
    _write(fake_repo, "app/workers/tasks.py", "from app.domains.commerce import service\n")
    assert check_boundaries(fake_repo) == []


def test_domain_importing_composition_root_is_rejected(fake_repo: Path) -> None:
    _write(fake_repo, "app/domains/catalog/api.py", "from app.dependencies import get_x\n")
    [violation] = check_boundaries(fake_repo)
    assert "composition root" in violation.rule


def test_domain_importing_db_registry_is_rejected(fake_repo: Path) -> None:
    # app.db barcha domen modellarini import qiladi — u ham composition root
    _write(fake_repo, "app/domains/catalog/service.py", "from app.db.models import load_metadata\n")
    [violation] = check_boundaries(fake_repo)
    assert "composition root" in violation.rule
