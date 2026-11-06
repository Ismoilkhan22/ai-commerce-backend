"""Instagram izohi: «+» va narx so'rovi qoidasi, til aniqlash, kayfiyat javobini o'qish (DEC-148)."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest

from app.domains.messaging.channels.instagram import COMMENT_TEXT_MAX, parse_comment_events, parse_webhook
from app.domains.messaging.ig_rules import classify_trigger, detect_locale
from app.domains.messaging.services.ig_classify import CONFIDENCE_THRESHOLD, parse_verdict


@pytest.mark.parametrize("text", ["+", "++", "+1", " + ", "+ +", "+👍", "＋", "+​", "+1️⃣", "+++ 🔥🔥", "+2"])
def test_plus_variants(text: str) -> None:
    assert classify_trigger(text) == "PLUS"


@pytest.mark.parametrize(
    "text",
    [
        "narxi qancha?",
        "Narx?",
        "Qancha turadi",
        "necha pul",
        "канча туради",
        "Нарх қанча?",
        "цена?",
        "Сколько стоит",
        "Почем",
        "price?",
        "How much is it",
        "+ narxi",
    ],
)
def test_price_questions(text: str) -> None:
    assert classify_trigger(text) == ("PLUS" if text == "+" else "PRICE_QUESTION")


@pytest.mark.parametrize(
    "text",
    [
        "",
        "   ",
        None,
        "Zo'r video!",
        "🔥🔥🔥",
        "+998901234567",
        "o'tgan safar olgan blokim kuydi",
        "narxlar",
        "ценный",
    ],
)
def test_no_trigger(text: str | None) -> None:
    # "narxlar" narx\w* ga mos kelgani uchun alohida tekshiriladi, qolganlari — qoidaga tushmaydi
    expected = "PRICE_QUESTION" if text == "narxlar" else "NONE"
    assert classify_trigger(text) == expected


def test_locale_from_comment() -> None:
    assert detect_locale("Сколько стоит?") == "ru"
    assert detect_locale("нарх қанча? ўзбек") == "uz"
    assert detect_locale("how much?") == "en"
    assert detect_locale("narxi?") is None
    assert detect_locale(None) is None


def test_verdict_threshold_is_070() -> None:
    assert CONFIDENCE_THRESHOLD == Decimal("0.70")
    sure = parse_verdict('{"sentiment": "NEGATIVE", "confidence": 0.93, "language": "uz-Latn"}')
    assert (sure.sentiment, sure.label, sure.confidence, sure.language) == (
        "NEGATIVE",
        "NEGATIVE",
        Decimal("0.930"),
        "uz-Latn",
    )
    edge = parse_verdict('{"sentiment": "POSITIVE", "confidence": 0.70}')
    assert edge.sentiment == "POSITIVE"  # chegaraning o'zi o'tadi
    low = parse_verdict('{"sentiment": "POSITIVE", "confidence": 0.69}')
    assert (low.sentiment, low.label) == ("UNDETERMINED", "POSITIVE")  # asl taxmin saqlanadi


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "yaxshi",
        "[]",
        '{"sentiment": "HAPPY", "confidence": 0.99}',
        '{"sentiment": "POSITIVE"}',
        '{"confidence": 0.9}',
    ],
)
def test_bad_model_output_is_undetermined(raw: str) -> None:
    assert parse_verdict(raw).sentiment == "UNDETERMINED"


def test_verdict_clamps_and_extracts_json() -> None:
    verdict = parse_verdict('Mana: {"sentiment": "spam", "confidence": 7, "language": "xx"} tamom')
    assert (verdict.sentiment, verdict.confidence, verdict.language) == ("SPAM", Decimal("1.000"), None)


# ------------------------------------------------------------------ QA7 F7: webhook chidamliligi
def _comment_payload(*values: dict[str, Any]) -> dict[str, Any]:
    base = {"id": "c1", "from": {"id": "u1", "username": "ali"}, "media": {"id": "m1"}, "text": "narxi?"}
    changes = [{"field": "comments", "value": {**base, **v}} for v in values]
    return {"entry": [{"id": "acc", "time": 1_700_000_000, "changes": changes}]}


def test_huge_created_time_is_ignored_not_a_500() -> None:
    payload = _comment_payload({"created_time": 10**30}, {"id": "c2", "created_time": 1_700_000_001})
    parsed = parse_comment_events(payload)
    assert [c.external_comment_id for _, c in parsed] == ["c2"]
    messaging = {
        "entry": [
            {
                "id": "acc",
                "messaging": [
                    {"sender": {"id": "u"}, "message": {"mid": "m", "text": "x"}, "timestamp": 10**30}
                ],
            }
        ]
    }
    assert parse_webhook(messaging) == []


def test_nul_comment_drops_only_that_comment_and_text_is_capped() -> None:
    payload = _comment_payload(
        {"id": "bad", "text": "salom\x00dunyo"},
        {"id": "long", "text": "a" * 5000},
        {"id": "ok", "text": "narxi?"},
    )
    parsed = {c.external_comment_id: c for _, c in parse_comment_events(payload)}
    assert set(parsed) == {"long", "ok"}
    assert parsed["long"].body is not None and len(parsed["long"].body) == COMMENT_TEXT_MAX == 2200


def test_confidence_is_clamped_and_threshold_uses_unrounded_value() -> None:
    assert parse_verdict('{"sentiment": "POSITIVE", "confidence": 0.6996}').sentiment == "UNDETERMINED"
    assert parse_verdict('{"sentiment": "POSITIVE", "confidence": 0.6996}').confidence == Decimal("0.700")
    assert parse_verdict('{"sentiment": "POSITIVE", "confidence": 7}').confidence == Decimal("1.000")
    assert parse_verdict('{"sentiment": "POSITIVE", "confidence": -3}').sentiment == "UNDETERMINED"
    for junk in ('"NaN"', '"Infinity"', '"-Infinity"'):
        verdict = parse_verdict('{"sentiment": "POSITIVE", "confidence": ' + junk + "}")
        assert verdict.confidence is None and verdict.sentiment == "UNDETERMINED", junk
