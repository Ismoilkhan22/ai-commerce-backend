"""DEC-149, 2-qism: Telegram ovozli xabari → matn. Audio saqlanmaydi (DEC-117), xarajat AI limitiga kiradi.

Tashqi tarmoq yo'q: Telegram — `FakeTelegramClient`, transkripsiya — `FakeProvider` (`light` navbati).
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from app.platform.llm.providers.fake import FakeFailure, FakeProvider, FakeText
from app.shared.contracts.messaging import ContextMessage
from tests.integration.helpers import World
from tests.integration.test_commerce import _admin_sql
from tests.integration.test_jobs_events import _drain_now
from tests.integration.test_messaging import Inbox

pytestmark = pytest.mark.integration


@pytest.fixture
def llm(world: World) -> Iterator[FakeProvider]:
    provider: FakeProvider = world.client.app.state.sales_ai.router.provider
    provider.light_script.clear()
    provider.light_requests.clear()
    yield provider
    provider.light_script.clear()


def test_voice_message_is_transcribed_and_audio_is_not_stored(world: World, llm: FakeProvider) -> None:
    inbox = Inbox(world)
    inbox.fake.files["voice-ok"] = (b"OggS" + b"\x00" * 200, "audio/ogg")
    llm.push_light(FakeText("  Assalomu alaykum, RTX 4060 bormi?  "))
    inbox.send({"voice": {"file_id": "voice-ok", "duration": 6, "mime_type": "audio/ogg", "file_size": 204}})
    conversation_id = inbox.conversations()[0]["id"]
    _drain_now(world)
    voice = inbox.messages(conversation_id)[-1]
    assert voice["kind"] == "VOICE" and voice["body"] == "Assalomu alaykum, RTX 4060 bormi?"
    attachment = voice["attachments"][0]
    assert attachment["status"] == "PURGED" and not attachment.get("url")  # audio saqlanmadi
    assert llm.light_requests[-1].messages[0].parts[0].mime == "audio/ogg"  # type: ignore[union-attr]
    usage = _admin_sql(
        world,
        "SELECT count(*) AS n FROM platform.ai_usage WHERE shop_id = $1 AND purpose = 'VOICE_TRANSCRIBE'",
        inbox.shop.id,
    )
    assert usage[0]["n"] == 1
    files = _admin_sql(
        world,
        "SELECT count(*) AS n FROM platform.stored_files WHERE shop_id = $1 AND purpose = 'CHAT_ATTACHMENT'",
        inbox.shop.id,
    )
    assert files[0]["n"] == 0


def test_voice_too_long_or_failed_falls_back_to_operator(world: World, llm: FakeProvider) -> None:
    inbox = Inbox(world)
    inbox.fake.files["voice-long"] = (b"OggS" + b"\x00" * 200, "audio/ogg")
    inbox.fake.files["voice-bad"] = (b"OggS" + b"\x00" * 200, "audio/ogg")
    inbox.send({"voice": {"file_id": "voice-long", "duration": 600, "mime_type": "audio/ogg"}})
    llm.push_light(FakeFailure("unsupported_media", retryable=False))
    inbox.send({"voice": {"file_id": "voice-bad", "duration": 5, "mime_type": "audio/ogg"}})
    conversation_id = inbox.conversations()[0]["id"]
    _drain_now(world)
    long_voice, bad_voice = inbox.messages(conversation_id)[-2:]
    assert long_voice["attachments"][0]["status"] == "FAILED" and long_voice["body"] is None
    assert bad_voice["attachments"][0]["status"] == "FAILED" and bad_voice["body"] is None
    assert len(llm.light_requests) == 1  # uzun ovoz AI'ga yuborilmadi


def test_context_message_pending_media_defaults_false() -> None:
    assert ContextMessage(1, "IN", "CUSTOMER", "TEXT", "x", "RECEIVED").pending_media is False
