"""DEC-149: javobsiz taklifga BITTA eslatma — faqat suhbatga bog'langan, amaldagi taklifda (BL-061)."""

from __future__ import annotations

from uuid import UUID

import pytest

from tests.integration.helpers import World, _bearer, _idem
from tests.integration.test_commerce import Shop, _admin_sql
from tests.integration.test_jobs_events import _drain_now, _job
from tests.integration.test_messaging import Inbox, clean_outbox  # noqa: F401 (autouse)
from tests.integration.test_quotes import Pc

pytestmark = pytest.mark.integration


def test_single_reminder_for_unanswered_quote(world: World) -> None:
    pc = Pc(world)
    shop = Shop.__new__(Shop)
    shop.world, shop.id, shop.owner = world, UUID(pc.shop_id), pc.owner
    inbox = Inbox(world, shop)
    inbox.text("PC yig'ib bering")
    conversation_id = inbox.conversations()[0]["id"]
    approved = pc.step(pc.owner, pc.step(pc.sales, pc.quote(pc.sales), "submit"), "approve", {})
    sent = world.client.post(
        f"/api/v1/shop/quotes/{approved['id']}/send",
        headers={**_bearer(pc.sales), **_idem(), "If-Match": f'"v{approved["version"]}"'},
    )
    assert sent.status_code == 200, sent.text
    _admin_sql(
        world,
        "UPDATE commerce.quotes SET conversation_id = $2, sent_at = now() - interval '13 hours' "
        "WHERE id = $1",
        UUID(approved["id"]),
        UUID(conversation_id),
    )
    _job(world, "quote_reminder")
    _drain_now(world)
    _job(world, "quote_reminder")  # ikkinchi marta — yo'q
    _drain_now(world)
    notices = [m for m in inbox.messages(conversation_id) if m["origin"] == "NOTIFICATION"]
    number = _admin_sql(world, "SELECT number FROM commerce.quotes WHERE id = $1", UUID(approved["id"]))[0]
    assert len(notices) == 1 and f"#{number['number']}" in notices[0]["body"]
