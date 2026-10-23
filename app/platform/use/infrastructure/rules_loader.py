"""DomainManifest'lardan holat qoidalarini boot vaqtida yig'adi (04 §3)."""

from __future__ import annotations

from collections.abc import Iterable, Mapping

import structlog

from app.shared.types.manifest import DomainManifest
from app.shared.types.state import StateMachineRule

logger = structlog.get_logger(__name__)

RuleKey = tuple[str, str, str]  # (entity_type, from_status, command)


class DuplicateRuleError(RuntimeError):
    """Bitta (entity_type, from_status, command) uchun ikki xil qoida — boot xatosi."""


class RulesRegistry:
    def __init__(
        self,
        rules: Iterable[StateMachineRule],
        non_forceable: Mapping[str, frozenset[str]] | None = None,
    ) -> None:
        self._rules: dict[RuleKey, StateMachineRule] = {}
        for rule in rules:
            key = (rule.entity_type, rule.from_status, rule.command)
            existing = self._rules.get(key)
            if existing is not None and existing != rule:
                raise DuplicateRuleError(f"{key}: {existing.to_status} va {rule.to_status}")
            self._rules[key] = rule
        self.non_forceable: dict[str, frozenset[str]] = dict(non_forceable or {})

    @classmethod
    def from_manifests(cls, manifests: Iterable[DomainManifest]) -> RulesRegistry:
        manifests = list(manifests)
        rules = [rule for m in manifests for rule in m.state_machine_rules]
        non_forceable: dict[str, frozenset[str]] = {}
        for manifest in manifests:
            for entity_type, states in manifest.non_forceable_states.items():
                non_forceable[entity_type] = non_forceable.get(entity_type, frozenset()) | states
        registry = cls(rules, non_forceable)
        logger.info("use.rules_loaded", entity_types=len(registry.entity_types()), rules=len(registry))
        return registry

    def find(self, entity_type: str, from_status: str, command: str) -> StateMachineRule | None:
        return self._rules.get((entity_type, from_status, command))

    def entity_types(self) -> set[str]:
        return {entity_type for entity_type, _, _ in self._rules}

    def all(self) -> list[StateMachineRule]:
        return list(self._rules.values())

    def __len__(self) -> int:
        return len(self._rules)
