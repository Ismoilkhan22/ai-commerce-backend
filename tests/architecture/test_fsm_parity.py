"""business/05 ↔ kod: holat qoidalari to'plami fsm_spec.yaml bilan aynan teng (04 §8)."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from app.main import discover_manifests

pytestmark = pytest.mark.architecture


def test_state_rules_match_business_spec() -> None:
    spec = yaml.safe_load((Path(__file__).parent / "fsm_spec.yaml").read_text(encoding="utf-8"))
    expected = {(entity, *arrow) for entity, arrows in spec.items() for arrow in arrows}
    actual = {
        (r.entity_type, r.command, r.from_status, r.to_status)
        for manifest in discover_manifests()
        for r in manifest.state_machine_rules
    }
    assert actual == expected, f"ortiqcha: {actual - expected}; yetishmaydi: {expected - actual}"
