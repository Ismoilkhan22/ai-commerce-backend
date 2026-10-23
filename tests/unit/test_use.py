"""Slim USE: qoidalar reyestri, validate, reason, force (04, ADR-034). DB'siz."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest

from app.platform.use.infrastructure.rules_loader import DuplicateRuleError, RulesRegistry
from app.platform.use.services.use_service import UseService
from app.shared.errors.base import ForbiddenError, InvalidTransitionError, ValidationError
from app.shared.types.actor import ActorContext
from app.shared.types.manifest import DomainManifest
from app.shared.types.state import StateMachineRule

SHOP = uuid4()
STAFF = ActorContext(actor_type="STAFF", actor_id=uuid4(), shop_id=SHOP, surface="shop")
AI = ActorContext(actor_type="AI_AGENT", actor_id=uuid4(), shop_id=SHOP, surface="worker")
ADMIN = ActorContext(
    actor_type="PLATFORM",
    actor_id=uuid4(),
    shop_id=SHOP,
    surface="platform",
    permissions=frozenset({"platform.state.force"}),
)


def rule(command: str, src: str, dst: str, **kw: Any) -> StateMachineRule:
    kw.setdefault("actors", frozenset({"STAFF"}))
    return StateMachineRule(
        entity_type="commerce.order",
        command=command,
        from_status=src,
        to_status=dst,
        business_ref="FSM-08",
        **kw,
    )


ORDER_RULES = [
    rule("SUBMIT", "DRAFT", "PENDING_CONFIRMATION", actors=frozenset({"STAFF", "CUSTOMER"})),
    rule("CONFIRM", "PENDING_CONFIRMATION", "CONFIRMED"),
    rule("CANCEL", "CONFIRMED", "CANCELLED", requires_reason=True),
]


class FakeSession:
    def __init__(self) -> None:
        self.added: list[Any] = []

    def add(self, obj: Any) -> None:
        self.added.append(obj)

    async def flush(self) -> None:
        return None


@pytest.fixture
def use() -> UseService:
    manifest = DomainManifest(
        name="commerce",
        state_machine_rules=ORDER_RULES,
        non_forceable_states={"commerce.order": frozenset({"CONFIRMED", "COMPLETED"})},
    )
    return UseService(RulesRegistry.from_manifests([manifest]))


def test_allowed_transition_returns_rule(use: UseService) -> None:
    found = use.validate_transition("commerce.order", "PENDING_CONFIRMATION", "CONFIRMED", "CONFIRM", STAFF)
    assert found.to_status == "CONFIRMED"


@pytest.mark.parametrize(
    ("src", "dst", "command"),
    [
        ("DRAFT", "COMPLETED", "COMPLETE"),  # qoida yo'q
        ("DRAFT", "CONFIRMED", "SUBMIT"),  # buyruq bor, maqsad boshqa
        ("CONFIRMED", "CONFIRMED", "CONFIRM"),  # takroriy tasdiq
    ],
)
def test_disallowed_transition_is_409(use: UseService, src: str, dst: str, command: str) -> None:
    with pytest.raises(InvalidTransitionError) as exc:
        use.validate_transition("commerce.order", src, dst, command, STAFF)
    assert exc.value.details == {"entity": "commerce.order", "from": src, "command": command}


def test_ai_cannot_execute_staff_command(use: UseService) -> None:  # TC-028
    with pytest.raises(InvalidTransitionError):
        use.validate_transition("commerce.order", "PENDING_CONFIRMATION", "CONFIRMED", "CONFIRM", AI)


async def test_reason_required(use: UseService) -> None:
    cancel = use.validate_transition("commerce.order", "CONFIRMED", "CANCELLED", "CANCEL", STAFF)
    with pytest.raises(ValidationError):
        await use.log_transition(FakeSession(), entity_id=uuid4(), rule=cancel, actor=STAFF, reason="  ")  # type: ignore[arg-type]


async def test_log_transition_records_actor_and_shop(use: UseService) -> None:
    session = FakeSession()
    confirm = use.validate_transition("commerce.order", "PENDING_CONFIRMATION", "CONFIRMED", "CONFIRM", STAFF)
    entity_id = uuid4()
    await use.log_transition(session, entity_id=entity_id, rule=confirm, actor=STAFF)  # type: ignore[arg-type]
    [log] = session.added
    assert (log.shop_id, log.entity_id, log.command, log.actor_type, log.forced) == (
        SHOP,
        entity_id,
        "CONFIRM",
        "STAFF",
        False,
    )


async def test_force_requires_platform_permission(use: UseService) -> None:
    with pytest.raises(ForbiddenError):
        await use.force_transition(
            FakeSession(),  # type: ignore[arg-type]
            entity_type="commerce.order",
            entity_id=uuid4(),
            from_status="EXCEPTION",
            to_status="PROCESSING",
            actor=STAFF,
            reason="x" * 30,
        )


async def test_force_rejects_short_reason_and_money_states(use: UseService) -> None:
    common: dict[str, Any] = {"entity_type": "commerce.order", "entity_id": uuid4(), "actor": ADMIN}
    with pytest.raises(ValidationError):
        await use.force_transition(
            FakeSession(), from_status="EXCEPTION", to_status="PROCESSING", reason="qisqa", **common
        )  # type: ignore[arg-type]
    with pytest.raises(InvalidTransitionError):
        await use.force_transition(
            FakeSession(),  # type: ignore[arg-type]
            from_status="EXCEPTION",
            to_status="COMPLETED",
            reason="Runbook RB-05: buyurtma xato bilan qotib qolgan",
            **common,
        )


async def test_force_is_logged_as_forced(use: UseService) -> None:
    session = FakeSession()
    await use.force_transition(
        session,  # type: ignore[arg-type]
        entity_type="commerce.order",
        entity_id=uuid4(),
        from_status="EXCEPTION",
        to_status="PROCESSING",
        actor=ADMIN,
        reason="Runbook RB-05: buyurtma xato bilan qotib qolgan",
    )
    [log] = session.added
    assert (log.command, log.forced, log.actor_type) == ("FORCE", True, "PLATFORM")


def test_conflicting_rules_fail_on_boot() -> None:
    with pytest.raises(DuplicateRuleError):
        RulesRegistry([rule("CONFIRM", "DRAFT", "CONFIRMED"), rule("CONFIRM", "DRAFT", "CANCELLED")])


def test_rule_format_is_validated() -> None:
    with pytest.raises(ValueError, match="pattern"):
        rule("confirm", "DRAFT", "CONFIRMED")  # buyruq UPPER_SNAKE bo'lishi kerak (K-02)
