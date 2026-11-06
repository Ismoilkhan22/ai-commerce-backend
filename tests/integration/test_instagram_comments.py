# ruff: noqa: E501
"""Instagram izohlari (DEC-148) — haqiqiy PostgreSQL'da, Meta chaqiruvisiz.

Tashqi tarmoq yo'q: Instagram — `FakeInstagramClient`, kayfiyat — `FakeProvider` (`light` navbati). Flag testlar
uchun yoqiladi (umumiy `MessagingConfig` nusxasi) va tugagach qaytariladi. Webhook imzosi haqiqiy (HMAC).
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import asyncpg
import pytest

from app.domains.messaging.channels.base import ChannelSendError
from app.domains.messaging.channels.instagram import FakeInstagramClient, InstagramAccount, MediaInfo
from app.platform.llm.providers.fake import FakeFailure, FakeProvider, FakeText
from app.shared.events.envelope import EventEnvelope
from app.shared.events.models import OUTBOX_SCHEMAS
from app.workers.queue import RecordingQueue
from tests.integration.helpers import World, _bearer, _idem
from tests.integration.test_commerce import Shop, _admin_sql, _hdr, _ok, _post
from tests.integration.test_jobs_events import _drain_now, _run
from tests.integration.test_messaging import _drain_retrying, _outbox

pytestmark = pytest.mark.integration

SECRET = "ig-app-secret-for-tests"
SCOPE = ("instagram_manage_comments",)
PRICE_LINE = "4 800 000 so'm"


@pytest.fixture(autouse=True)
def clean_outbox(world: World) -> Iterator[None]:
    for schema in OUTBOX_SCHEMAS:
        _admin_sql(
            world,
            f"UPDATE {schema}.outbox_events SET status = 'PUBLISHED', published_at = now() "
            "WHERE status = 'PENDING'",
        )
    yield


@pytest.fixture
def flag(world: World) -> Iterator[None]:
    """Instagram flag'i yoqiladi (bitta umumiy konfiguratsiya obyekti), tugagach qaytariladi."""
    config = world.client.app.state.messaging.config
    saved = (config.instagram_enabled, config.instagram_app_secret, config.storefront_public_url)
    object.__setattr__(config, "instagram_enabled", True)
    object.__setattr__(config, "instagram_app_secret", SECRET)
    object.__setattr__(config, "storefront_public_url", "https://{slug}.platforma.uz")
    yield
    object.__setattr__(config, "instagram_enabled", saved[0])
    object.__setattr__(config, "instagram_app_secret", saved[1])
    object.__setattr__(config, "storefront_public_url", saved[2])


@pytest.fixture
def llm(world: World) -> Iterator[FakeProvider]:
    provider: FakeProvider = world.client.app.state.sales_ai.router.provider
    provider.light_script.clear()
    provider.light_requests.clear()
    yield provider
    provider.light_script.clear()


def _sentiment(label: str, confidence: float, language: str = "uz-Latn") -> FakeText:
    return FakeText(json.dumps({"sentiment": label, "confidence": confidence, "language": language}))


class Ig:
    """Shop + ulangan Instagram akkaunt (soxta klient, izohlar ruxsati bor) + webhook yordamchilari."""

    def __init__(self, world: World, shop: Shop | None = None, *, scopes: tuple[str, ...] = SCOPE) -> None:
        self.world = world
        self.shop = shop or Shop(world)
        self.account_id = str(int(uuid4().int % 10**12) + 10**12)
        self.token = f"IGQ{uuid4().hex}{uuid4().hex}"
        self.fake = FakeInstagramClient(
            accounts={self.token: InstagramAccount(self.account_id, "techpc_uz", scopes)}
        )
        world.client.app.state.messaging.adapters.instagram = self.fake
        created = _ok(_post(world, self.owner, "/channels/instagram", {"access_token": self.token}), 201)
        self.channel_id = UUID(created["id"])

    @property
    def owner(self) -> str:
        return self.shop.owner

    def get(self, path: str, token: str | None = None) -> Any:
        return self.world.client.get(f"/api/v1/shop/instagram{path}", headers=_bearer(token or self.owner))

    def write(
        self, method: str, path: str, body: Any = None, version: int | None = None, token: str | None = None
    ) -> Any:
        return self.world.client.request(
            method, f"/api/v1/shop/instagram{path}", json=body, headers=_hdr(token or self.owner, version)
        )

    # ---------------------------------------------------------------- webhook
    def webhook(self, *changes: dict[str, Any], secret: str = SECRET) -> Any:
        payload = {
            "object": "instagram",
            "entry": [{"id": self.account_id, "time": int(time.time()), "changes": list(changes)}],
        }
        raw = json.dumps(payload).encode()
        signature = "sha256=" + hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
        return self.world.client.post(
            "/api/v1/webhooks/instagram",
            content=raw,
            headers={"X-Hub-Signature-256": signature, "Content-Type": "application/json"},
        )

    def change(
        self,
        text: str | None,
        *,
        cid: str | None = None,
        author: str = "9001",
        username: str = "jasur_pc",
        media: str = "media-1",
        age_days: float = 0,
        **extra: Any,
    ) -> dict[str, Any]:
        value: dict[str, Any] = {
            "id": cid or f"c{uuid4().hex[:12]}",
            "from": {"id": author, "username": username},
            "media": {"id": media, "media_product_type": "REELS"},
            "created_time": int(time.time() - age_days * 86400),
            **extra,
        }
        if text is not None:
            value["text"] = text
        return {"field": "comments", "value": value}

    def comment(self, text: str | None, **kwargs: Any) -> dict[str, Any]:
        """Webhook yuboradi, outbox'ni bajaradi; izohning panel ko'rinishini qaytaradi."""
        change = self.change(text, **kwargs)
        response = self.webhook(change)
        assert response.status_code == 200, response.text
        _drain_retrying(self.world)
        return self.find(change["value"]["id"])

    def comments(self, query: str = "", token: str | None = None) -> list[dict[str, Any]]:
        return list(_ok(self.get(f"/comments?limit=100{query}", token))["items"])

    def find(self, external_id: str) -> dict[str, Any]:
        row = _admin_sql(
            self.world,
            "SELECT id FROM messaging.ig_comments WHERE shop_id = $1 AND external_comment_id = $2",
            self.shop.id,
            external_id,
        )[0]
        return next(c for c in self.comments() if c["id"] == str(row["id"]))

    def posts(self) -> list[dict[str, Any]]:
        return list(_ok(self.get("/posts?limit=100"))["items"])

    def post(self, external_media_id: str = "media-1") -> dict[str, Any]:
        return next(p for p in self.posts() if p["external_media_id"] == external_media_id)

    def link(self, post: dict[str, Any], *product_ids: str) -> dict[str, Any]:
        return _ok(
            self.write(
                "PUT", f"/posts/{post['id']}/products", {"product_ids": list(product_ids)}, post["version"]
            )
        )

    def product(self, *, stock: int = 0) -> str:
        """Saytda chiqarilgan mahsulot (narx 4 800 000 so'm) → product id."""
        sku = self.shop.sku()
        if stock:
            self.shop.receive(sku, stock)
        return str(
            _admin_sql(self.world, "SELECT product_id FROM catalog.skus WHERE id = $1", UUID(sku))[0][
                "product_id"
            ]
        )

    def replies(self, comment_id: str) -> list[asyncpg.Record]:
        return _admin_sql(
            self.world,
            "SELECT kind, status, skip_reason, template_key, body, locale, provider_message_id "
            "FROM messaging.ig_comment_replies WHERE shop_id = $1 AND comment_id = $2 ORDER BY created_at",
            self.shop.id,
            UUID(comment_id),
        )


# ------------------------------------------------------------------ flag o'chiq
def test_flag_off_all_endpoints_return_404(world: World) -> None:
    shop = Shop(world)
    token, post_id = shop.owner, str(uuid4())
    calls = [
        ("GET", "/settings", None),
        ("PATCH", "/settings", {"auto_reply": False}),
        ("GET", "/templates", None),
        ("PUT", "/templates/customer.ig_comment_price_reply/uz", {"body": "{product_title} {price}"}),
        ("DELETE", "/templates/customer.ig_comment_price_reply/uz", None),
        ("GET", "/posts", None),
        ("PATCH", f"/posts/{post_id}", {"auto_reply_enabled": False}),
        ("PUT", f"/posts/{post_id}/products", {"product_ids": []}),
        ("GET", "/comments?filter=all", None),
        ("GET", "/sentiment-summary?period=7d", None),
    ]
    for method, path, body in calls:
        response = world.client.request(
            method, f"/api/v1/shop/instagram{path}", json=body, headers=_hdr(token, 1)
        )
        assert response.status_code == 404, (method, path, response.status_code)
        anonymous = world.client.request(method, f"/api/v1/shop/instagram{path}", json=body)
        assert anonymous.status_code == 404, (method, path)  # flag o'chiq: endpoint "yo'qdek", tokensiz ham


# ------------------------------------------------------------------ webhook: imzo va takror
def test_webhook_checks_signature_and_dedups_by_provider_events(
    world: World, flag: None, llm: FakeProvider
) -> None:
    ig = Ig(world)
    change = ig.change("+", cid="dup-1")
    assert ig.webhook(change, secret="wrong").status_code == 404
    assert ig.webhook(change).status_code == 200
    assert ig.webhook(change).status_code == 200  # Meta qayta yubordi
    assert ig.webhook(change).status_code == 200
    _drain_retrying(world)
    rows = _admin_sql(
        world,
        "SELECT count(*) AS n FROM messaging.ig_comments WHERE shop_id = $1 AND external_comment_id = 'dup-1'",
        ig.shop.id,
    )
    assert rows[0]["n"] == 1
    events = _admin_sql(
        world,
        "SELECT kind, ig_comment_id FROM messaging.provider_events WHERE shop_id = $1 AND provider_event_id = 'comment:dup-1'",
        ig.shop.id,
    )
    assert len(events) == 1 and events[0]["kind"] == "COMMENT" and events[0]["ig_comment_id"] is not None
    assert ig.post()["comment_count"] == 1
    assert len(ig.fake.private_replies) == 1  # bitta javob
    received = [e for e in _outbox(world, ig.shop.id) if e["type"] == "messaging.ig_comment.received"]
    assert len(received) == 1


# ------------------------------------------------------------------ «+»: umumiy javob va bir muallifga bitta
def test_plus_gets_generic_reply_once_per_author_per_post(
    world: World, flag: None, llm: FakeProvider
) -> None:
    ig = Ig(world)
    first = ig.comment("+", author="9001")
    assert first["trigger"] == "PLUS" and first["author_username"] == "jasur_pc"
    assert first["auto_reply"]["status"] == "SENT" and first["auto_reply"]["skip_reason"] is None
    assert len(ig.fake.private_replies) == 1
    account, comment_ref, text = ig.fake.private_replies[0]
    assert account == ig.account_id and comment_ref.startswith("c")
    assert (
        text == "Salom! Narx va mavjudlik bo'yicha shu yerga yozing, javob beramiz."
    )  # post bog'lanmagan: narxsiz
    assert not any(ch.isdigit() for ch in text)
    [reply] = ig.replies(first["id"])
    assert (reply["kind"], reply["template_key"], reply["provider_message_id"]) == (
        "PRIVATE_AUTO",
        "customer.ig_comment_generic_reply",
        "pr.1",
    )
    # Shu muallif o'sha postga yana "+" yozdi (5 marta) — Direct'ga yana xabar ketmaydi
    for _ in range(4):
        again = ig.comment("++", author="9001")
        assert again["auto_reply"]["status"] == "SKIPPED"
        assert again["auto_reply"]["skip_reason"] == "AUTHOR_ALREADY_REPLIED"
    assert len(ig.fake.private_replies) == 1
    # Boshqa muallif yoki boshqa post — javob ketadi
    assert ig.comment("+", author="9002")["auto_reply"]["status"] == "SENT"
    assert ig.comment("+", author="9001", media="media-2")["auto_reply"]["status"] == "SENT"
    assert len(ig.fake.private_replies) == 3
    assert {p["external_media_id"] for p in ig.posts()} == {"media-1", "media-2"}


def test_non_trigger_comment_gets_no_reply_and_own_comment_is_ignored(
    world: World, flag: None, llm: FakeProvider
) -> None:
    ig = Ig(world)
    plain = ig.comment("Zo'r video!")
    assert plain["trigger"] == "NONE" and plain["auto_reply"] is None
    own = ig.comment("+", author=ig.account_id, username="techpc_uz")  # shopning o'z izohi
    assert own["trigger"] == "NONE" and own["auto_reply"] is None and own["status"] == "CLASSIFY_SKIPPED"
    assert ig.fake.private_replies == []
    assert len(llm.light_requests) == 1  # faqat oddiy izoh baholandi; shopning o'zi emas


# ------------------------------------------------------------------ narx: bog'langan mahsulot yoki umumiy
def test_price_question_uses_linked_product_price_else_generic(
    world: World, flag: None, llm: FakeProvider
) -> None:
    ig = Ig(world)
    product = ig.product(stock=5)
    ig.comment("Zo'r!", media="media-1")  # post yaratiladi
    ig.comment("narxi qancha?", author="1", media="media-3")  # media-3 hech narsaga bog'lanmagan
    unlinked = ig.fake.private_replies[-1][2]
    assert "so'm" not in unlinked and unlinked.startswith("Salom! Narx va mavjudlik")
    linked = ig.link(ig.post("media-1"), product)
    assert linked["products"][0]["product_id"] == product and linked["products"][0]["title"].startswith(
        "Test GPU"
    )
    reply = ig.comment("narxi qancha?", author="2", media="media-1")["auto_reply"]
    assert reply["status"] == "SENT"
    text = ig.fake.private_replies[-1][2]
    assert PRICE_LINE in text and "Test GPU" in text and "bor" in text  # narx katalogdan, qoldiq bor
    slug = _admin_sql(world, "SELECT slug FROM platform.shops WHERE id = $1", ig.shop.id)[0]["slug"]
    assert f"https://{slug}.platforma.uz/p/{product}" in text
    [row] = ig.replies(ig.comments("&post_id=" + linked["id"])[0]["id"])
    assert row["template_key"] == "customer.ig_comment_price_reply" and row["locale"] == "uz"
    # Rus tilidagi savol — rus shabloni
    ig.comment("Сколько стоит?", author="3", media="media-1")
    assert (
        ig.fake.private_replies[-1][2].startswith("Здравствуйте!") and "сум" in ig.fake.private_replies[-1][2]
    )


def test_catalog_price_change_is_used_at_reply_time_and_hidden_product_falls_back(
    world: World, flag: None, llm: FakeProvider
) -> None:
    ig = Ig(world)
    product = ig.product()
    ig.comment("Zo'r!")
    ig.link(ig.post(), product)
    _ok(_post(world, ig.owner, f"/products/{product}/hide"))
    ig.comment("+", author="5")
    assert "so'm" not in ig.fake.private_replies[-1][2]  # yashirilgan mahsulot: narx aytilmaydi, umumiy javob


# ------------------------------------------------------------------ post va shop sozlamalari, 7 kun
def test_post_toggle_shop_setting_and_reply_window(world: World, flag: None, llm: FakeProvider) -> None:
    ig = Ig(world)
    ig.comment("Zo'r!")
    post = ig.post()
    stale = ig.write("PATCH", f"/posts/{post['id']}", {"auto_reply_enabled": False}, post["version"] + 5)
    assert stale.status_code == 409
    no_header = world.client.patch(
        f"/api/v1/shop/instagram/posts/{post['id']}",
        json={"auto_reply_enabled": False},
        headers=_bearer(ig.owner),
    )
    assert no_header.status_code in (400, 428)
    off = _ok(ig.write("PATCH", f"/posts/{post['id']}", {"auto_reply_enabled": False}, post["version"]))
    assert off["auto_reply_enabled"] is False and off["version"] == post["version"] + 1
    skipped = ig.comment("+", author="1")
    assert skipped["auto_reply"] == {
        **skipped["auto_reply"],
        "status": "SKIPPED",
        "skip_reason": "POST_AUTO_REPLY_OFF",
    }
    _ok(ig.write("PATCH", f"/posts/{post['id']}", {"auto_reply_enabled": True}, off["version"]))
    settings = _ok(ig.get("/settings"))
    assert (
        settings["feature_enabled"]
        and settings["permission_granted"]
        and settings["auto_reply"]
        and settings["sentiment"]
    )
    updated = _ok(ig.write("PATCH", "/settings", {"auto_reply": False}, settings["version"]))
    assert (
        updated["auto_reply"] is False
        and updated["sentiment"] is True
        and updated["version"] == settings["version"] + 1
    )
    assert ig.comment("+", author="2")["auto_reply"]["skip_reason"] == "AUTO_REPLY_OFF"
    _ok(ig.write("PATCH", "/settings", {"auto_reply": True}, updated["version"]))
    old = ig.comment("+", author="3", age_days=8)  # Private Reply oynasi (7 kun) o'tgan
    assert old["auto_reply"]["skip_reason"] == "WINDOW_EXPIRED"
    assert ig.fake.private_replies == []


def test_settings_cannot_be_enabled_without_meta_comments_permission(
    world: World, flag: None, llm: FakeProvider
) -> None:
    ig = Ig(world, scopes=())
    settings = _ok(ig.get("/settings"))
    assert settings["permission_granted"] is False
    denied = ig.write("PATCH", "/settings", {"auto_reply": True}, settings["version"])
    assert (
        denied.status_code == 422
        and denied.json()["error"]["details"]["fields"][0]["code"] == "permission_missing"
    )
    assert (
        _ok(ig.write("PATCH", "/settings", {"auto_reply": False, "sentiment": False}, settings["version"]))[
            "auto_reply"
        ]
        is False
    )


def test_reply_is_idempotent_and_send_retries_then_finishes(
    world: World, flag: None, llm: FakeProvider
) -> None:
    ig = Ig(world)
    ig.fake.private_reply_errors = [ChannelSendError("RATE_LIMITED", retryable=True, retry_after=1)]
    first = ig.comment("+", author="1")
    assert (
        first["auto_reply"]["status"] == "SENT" and len(ig.fake.private_replies) == 1
    )  # qayta urinishdan keyin
    # Xuddi shu `received` event'i ikkinchi marta qayta ishlansa ham yangi javob yaratilmaydi
    envelope = EventEnvelope.model_validate(
        next(e for e in _outbox(world, ig.shop.id) if e["type"] == "messaging.ig_comment.received")[
            "envelope"
        ]
    )

    reply_id = _admin_sql(
        world, "SELECT id FROM messaging.ig_comment_replies WHERE shop_id = $1", ig.shop.id
    )[0]["id"]

    async def again(rt: Any) -> list[str]:
        out = []
        for _ in range(2):
            async with rt.database.transaction(ig.shop.id) as db:
                out.append(await rt.services.messaging.ig.reply.decide(db, envelope))
        out.append(await rt.services.messaging.ig.reply.send(rt.database, ig.shop.id, reply_id))
        return out

    assert _run(world, RecordingQueue(), again) == ["exists", "exists", "skipped"]
    assert len(ig.fake.private_replies) == 1
    n = _admin_sql(
        world, "SELECT count(*) AS n FROM messaging.ig_comment_replies WHERE shop_id = $1", ig.shop.id
    )
    assert n[0]["n"] == 1


def test_meta_window_error_is_skipped_not_failed(world: World, flag: None, llm: FakeProvider) -> None:
    ig = Ig(world)
    ig.fake.private_reply_errors = [ChannelSendError("REPLY_WINDOW_EXPIRED")]
    reply = ig.comment("+", author="1")["auto_reply"]
    assert (reply["status"], reply["skip_reason"]) == ("SKIPPED", "WINDOW_EXPIRED")
    ig.fake.private_reply_errors = [ChannelSendError("TIMEOUT", unknown=True)]
    failed = ig.comment("+", author="2")["auto_reply"]
    assert (failed["status"], failed["last_error_code"]) == (
        "FAILED",
        "TIMEOUT",
    )  # yuborildimi noma'lum: qayta yuborilmaydi
    assert ig.fake.private_replies == []


# ------------------------------------------------------------------ kayfiyat: chegara, PII, xarajat
def test_sentiment_threshold_pii_and_usage(world: World, flag: None, llm: FakeProvider) -> None:
    ig = Ig(world)
    llm.push_light(
        _sentiment("NEGATIVE", 0.93),
        _sentiment("POSITIVE", 0.55),
        _sentiment("POSITIVE", 0.70),
        FakeText("yaxshi"),
    )
    negative = ig.comment("Xizmat yomon, 998901234567 ga qo'ng'iroq qiling", author="1")
    assert (negative["sentiment"], negative["sentiment_source"], negative["status"]) == (
        "NEGATIVE",
        "AI",
        "CLASSIFIED",
    )
    assert not any(
        "998901234567" in json.dumps(r.messages[0].parts[0].text) for r in llm.light_requests
    )  # PII tashqi AI'ga ketmaydi
    assert all(r.model_alias == "light" for r in llm.light_requests)
    unsure = ig.comment("Ha albatta 😏", author="2")
    assert unsure["sentiment"] == "UNDETERMINED" and unsure["sentiment_source"] == "AI"  # 0.55 < 0.70
    edge = ig.comment("zo'r", author="3")
    assert edge["sentiment"] == "POSITIVE"  # aynan 0.70 — o'tadi
    garbage = ig.comment("???", author="4")
    assert garbage["sentiment"] == "UNDETERMINED"  # buzuq javob hech qachon taxmin qilinmaydi
    rows = _admin_sql(
        world,
        "SELECT s.sentiment, s.raw_label, s.confidence::float AS conf, s.model_id, s.prompt_version, u.purpose, u.ref_id, u.shop_id "
        "FROM messaging.ig_comment_sentiments s JOIN platform.ai_usage u ON u.id = s.ai_usage_id "
        "WHERE s.shop_id = $1 ORDER BY s.created_at",
        ig.shop.id,
    )
    assert [(r["sentiment"], r["raw_label"], r["conf"]) for r in rows] == [
        ("NEGATIVE", "NEGATIVE", 0.93),
        ("UNDETERMINED", "POSITIVE", 0.55),
        ("POSITIVE", "POSITIVE", 0.7),
        ("UNDETERMINED", None, None),
    ]
    assert {r["purpose"] for r in rows} == {"COMMENT_CLASSIFY"} and all(
        r["shop_id"] == ig.shop.id for r in rows
    )
    assert rows[0]["prompt_version"] == "ig-sentiment-v1"
    summary = _ok(ig.get("/sentiment-summary?period=7d"))
    assert summary == {
        "period": "7d",
        "positive": 1,
        "neutral": 0,
        "negative": 1,
        "spam": 0,
        "undetermined": 2,
    }
    classified = [e for e in _outbox(world, ig.shop.id) if e["type"] == "messaging.ig_comment.classified"]
    assert {e["envelope"]["payload"]["confidence_bucket"] for e in classified} == {"HIGH", "LOW"}


def test_sentiment_setting_off_and_provider_outage_do_not_block_replies(
    world: World, flag: None, llm: FakeProvider
) -> None:
    ig = Ig(world)
    settings = _ok(ig.get("/settings"))
    _ok(ig.write("PATCH", "/settings", {"sentiment": False}, settings["version"]))
    off = ig.comment("+", author="1")
    assert off["status"] == "CLASSIFY_SKIPPED" and off["sentiment"] is None and llm.light_requests == []
    assert off["auto_reply"]["status"] == "SENT"
    _ok(ig.write("PATCH", "/settings", {"sentiment": True}, settings["version"] + 1))
    llm.push_light(FakeFailure("invalid_request", retryable=False))
    down = ig.comment("+", author="2")
    assert down["status"] == "CLASSIFY_SKIPPED" and down["auto_reply"]["status"] == "SENT"


def test_ai_cap_reached_skips_sentiment_but_plus_replies_continue(
    world: World, flag: None, llm: FakeProvider
) -> None:
    ig = Ig(world)
    _ok(
        world.client.patch(
            "/api/v1/shop/ai/settings",
            json={"mode": "OFF", "daily_cost_cap_minor": 0},
            headers=_hdr(
                ig.owner,
                _ok(world.client.get("/api/v1/shop/ai/settings", headers=_bearer(ig.owner)))["version"],
            ),
        )
    )
    llm.push_light(_sentiment("NEGATIVE", 0.99))
    plus = ig.comment("+", author="1")
    assert plus["auto_reply"]["status"] == "SENT" and len(ig.fake.private_replies) == 1  # «+» AI emas
    assert plus["status"] == "CLASSIFY_SKIPPED" and plus["sentiment"] is None
    text = ig.comment("Narxi qimmat ekan", author="2")
    assert text["status"] == "CLASSIFY_SKIPPED" and text["sentiment"] is None
    assert llm.light_requests == []  # limit tugagan: model chaqirilmadi
    unclassified = [c["id"] for c in ig.comments("&filter=unclassified")]
    assert plus["id"] in unclassified and text["id"] in unclassified
    spent = _admin_sql(
        world,
        "SELECT count(*) AS n FROM platform.ai_usage WHERE shop_id = $1 AND purpose = 'COMMENT_CLASSIFY'",
        ig.shop.id,
    )
    assert spent[0]["n"] == 0


# ------------------------------------------------------------------ panel: filtrlar, sahifalash, o'chirish
def test_comment_filters_pagination_and_delete(world: World, flag: None, llm: FakeProvider) -> None:
    ig = Ig(world)
    llm.push_light(
        _sentiment("NEGATIVE", 0.9),
        _sentiment("POSITIVE", 0.9),
        _sentiment("NEUTRAL", 0.9),
        _sentiment("SPAM", 0.9),
    )
    a = ig.comment("+", author="1")
    b = ig.comment("narxi qancha?", author="2")
    c = ig.comment("juda yomon xizmat", author="3")
    d = ig.comment("zo'r", author="4", media="media-2")
    ids = lambda query: {x["id"] for x in ig.comments(query)}  # noqa: E731
    assert ids("&filter=all") == {a["id"], b["id"], c["id"], d["id"]}
    assert ids("&filter=plus") == {a["id"]} and ids("&filter=PLUS") == {a["id"]}
    assert ids("&filter=price") == {b["id"]} and ids("&filter=PRICE_QUESTION") == {b["id"]}
    assert ids("&filter=negative") == {a["id"]}  # birinchi javob NEGATIVE edi
    assert ids("&filter=all&post_id=" + d["post_id"]) == {d["id"]}
    assert _ok(ig.get("/sentiment-summary?period=30d"))["spam"] == 1
    assert ig.get("/comments?filter=bogus").status_code == 422
    assert ig.get("/sentiment-summary?period=1y").status_code == 422
    page = _ok(ig.get("/comments?limit=3"))
    assert len(page["items"]) == 3 and page["has_more"] and page["next_cursor"]
    rest = _ok(ig.get(f"/comments?limit=3&cursor={page['next_cursor']}"))
    assert len(rest["items"]) == 1 and not rest["has_more"] and rest["next_cursor"] is None
    assert {x["id"] for x in page["items"] + rest["items"]} == ids("")
    # Izoh o'chirildi (webhook verb=remove): matn va username darhol tozalanadi
    victim = _admin_sql(
        world, "SELECT external_comment_id FROM messaging.ig_comments WHERE id = $1", UUID(c["id"])
    )[0]
    assert ig.webhook(ig.change(None, cid=victim["external_comment_id"], verb="remove")).status_code == 200
    _drain_retrying(world)
    gone = next(x for x in ig.comments() if x["id"] == c["id"])
    assert (gone["status"], gone["body"], gone["author_username"]) == ("DELETED", None, None)
    assert any(e["type"] == "messaging.ig_comment.deleted" for e in _outbox(world, ig.shop.id))


def test_templates_list_override_validate_and_reset(world: World, flag: None, llm: FakeProvider) -> None:
    ig = Ig(world)
    listed = _ok(ig.get("/templates"))["items"]
    assert {i["template_key"] for i in listed} == {
        "customer.ig_comment_price_reply",
        "customer.ig_comment_generic_reply",
    }
    assert len(listed) == 6 and all(not i["overridden"] and i["body"] == i["default_body"] for i in listed)
    price_uz = next(i for i in listed if i["template_key"].endswith("price_reply") and i["locale"] == "uz")
    assert (
        set(price_uz["required_variables"]) == {"product_title", "price"}
        and "product_url" in price_uz["allowed_variables"]
    )
    path = "/templates/customer.ig_comment_price_reply/uz"
    assert ig.write("PUT", path, {"body": "Narx bor"}).status_code == 422  # majburiy o'zgaruvchi yo'q
    assert (
        ig.write("PUT", "/templates/customer.order_confirmed/uz", {"body": "{order_number}"}).status_code
        == 404
    )
    assert ig.write("DELETE", "/templates/customer.order_confirmed/uz").status_code == 404
    saved = _ok(ig.write("PUT", path, {"body": "{product_title}: {price}!"}))
    assert saved["overridden"] and saved["body"] == "{product_title}: {price}!"
    product = ig.product()
    ig.comment("Zo'r!")
    ig.link(ig.post(), product)
    ig.comment("narxi?", author="7")
    assert ig.fake.private_replies[-1][2].endswith(f": {PRICE_LINE}!")
    reset = _ok(ig.write("DELETE", path))
    assert reset["overridden"] is False and reset["body"] == reset["default_body"]


def test_post_products_validation(world: World, flag: None, llm: FakeProvider) -> None:
    ig = Ig(world)
    ig.comment("Zo'r!")
    post = ig.post()
    other = Shop(world)  # boshqa shop mahsuloti
    other_sku = other.sku()
    other_shop_product = str(
        _admin_sql(world, "SELECT product_id FROM catalog.skus WHERE id = $1", UUID(other_sku))[0][
            "product_id"
        ]
    )
    bad = ig.write(
        "PUT", f"/posts/{post['id']}/products", {"product_ids": [other_shop_product]}, post["version"]
    )
    assert (
        bad.status_code == 422 and bad.json()["error"]["details"]["fields"][0]["code"] == "product_not_found"
    )
    six = ig.write(
        "PUT",
        f"/posts/{post['id']}/products",
        {"product_ids": [str(uuid4()) for _ in range(6)]},
        post["version"],
    )
    assert six.status_code == 422
    products = [ig.product() for _ in range(5)]
    linked = ig.link(post, *products)
    assert [p["product_id"] for p in linked["products"]] == products and linked["version"] == post[
        "version"
    ] + 1
    dup = ig.write(
        "PUT", f"/posts/{post['id']}/products", {"product_ids": [products[0], products[0]]}, linked["version"]
    )
    assert dup.status_code == 422
    # Karusel: birinchi mahsulot shablonda, qolganlari qisqa ro'yxat
    ig.comment("narxi?", author="8")
    text = ig.fake.private_replies[-1][2]
    assert text.count("•") == 4 and text.count(PRICE_LINE) == 5
    cleared = ig.link(
        _ok(ig.get("/posts?limit=1"))["items"][0],
    )
    assert cleared["products"] == []


# ------------------------------------------------------------------ ruxsatlar, RLS, PII
def test_permissions(world: World, flag: None, llm: FakeProvider) -> None:
    ig = Ig(world)
    ig.comment("+", author="1")
    manager, _ = ig.shop.staff("MANAGER")
    sales, _ = ig.shop.staff("SALES")
    warehouse, _ = ig.shop.staff("WAREHOUSE")
    post = ig.post()
    for token in (ig.owner, manager, sales):  # ko'rish
        for path in ("/settings", "/templates", "/posts", "/comments", "/sentiment-summary"):
            assert ig.get(path, token).status_code == 200, (path, token == sales)
    assert (
        ig.get("/comments", warehouse).status_code == 403
        and ig.get("/settings", warehouse).status_code == 403
    )
    assert world.client.get("/api/v1/shop/instagram/comments").status_code == 401
    writes = [
        ("PATCH", "/settings", {"sentiment": True}, _ok(ig.get("/settings"))["version"]),
        ("PUT", "/templates/customer.ig_comment_generic_reply/uz", {"body": "Salom"}, None),
        ("DELETE", "/templates/customer.ig_comment_generic_reply/uz", None, None),
        ("PATCH", f"/posts/{post['id']}", {"auto_reply_enabled": True}, post["version"]),
        ("PUT", f"/posts/{post['id']}/products", {"product_ids": []}, post["version"]),
    ]
    for method, path, body, version in writes:
        for token in (sales, warehouse):
            assert ig.write(method, path, body, version, token).status_code == 403, (method, path)
        assert ig.write(method, path, body, version, manager).status_code == 200, (
            method,
            path,
        )  # menejer boshqaradi
        version = None if method == "PATCH" and path == "/settings" else version


def test_rls_other_shop_sees_nothing_and_tables_force_rls(
    world: World, flag: None, llm: FakeProvider
) -> None:
    a = Ig(world)
    a.comment("+", author="1")
    b = Shop(world)
    ig_b = Ig(world, b)
    assert ig_b.comments() == [] and ig_b.posts() == []
    post_a = a.post()
    assert (
        ig_b.write(
            "PATCH", f"/posts/{post_a['id']}", {"auto_reply_enabled": False}, post_a["version"]
        ).status_code
        == 404
    )
    assert ig_b.get(f"/comments?post_id={post_a['id']}").json()["items"] == []
    tables = ("ig_posts", "ig_post_products", "ig_comments", "ig_comment_sentiments", "ig_comment_replies")
    flags = _admin_sql(
        world,
        "SELECT relname, relrowsecurity, relforcerowsecurity FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
        "WHERE n.nspname = 'messaging' AND relname = ANY($1)",
        list(tables),
    )
    assert {r["relname"] for r in flags} == set(tables) and all(
        r["relrowsecurity"] and r["relforcerowsecurity"] for r in flags
    )

    async def as_runtime() -> dict[str, int]:
        conn = await asyncpg.connect(world.urls.runtime.replace("postgresql+asyncpg://", "postgresql://"))
        try:
            counts = {
                t: await conn.fetchval(f"SELECT count(*) FROM messaging.{t}") for t in tables
            }  # shop konteksti yo'q
            await conn.execute("SELECT set_config('app.shop_id', $1, false)", str(b.id))
            counts["as_b"] = await conn.fetchval("SELECT count(*) FROM messaging.ig_comments")
            return counts
        finally:
            await conn.close()

    import asyncio

    counts = asyncio.run(as_runtime())
    assert (
        counts["ig_posts"] == 0
        and counts["ig_comments"] == 0
        and counts["ig_comment_replies"] == 0
        and counts["as_b"] == 0
    )


def test_events_carry_no_pii_or_comment_text(world: World, flag: None, llm: FakeProvider) -> None:
    ig = Ig(world)
    llm.push_light(_sentiment("NEGATIVE", 0.95))
    secret_text = "Maxfiy-matn-12345 menga narxini ayting"
    ig.comment(secret_text, author="1", username="maxfiy_username")
    events = [e for e in _outbox(world, ig.shop.id) if e["type"].startswith("messaging.ig_comment")]
    assert {e["type"] for e in events} >= {
        "messaging.ig_comment.received",
        "messaging.ig_comment.classified",
        "messaging.ig_comment.reply_queued",
        "messaging.ig_comment.reply_finished",
    }
    blob = json.dumps(events)
    assert (
        "Maxfiy" not in blob
        and "maxfiy_username" not in blob
        and PRICE_LINE not in blob
        and "so'm" not in blob
    )
    from app.shared.events.pii import forbidden_keys

    for event in events:
        assert forbidden_keys(event["envelope"]["payload"]) == []
    received = next(e for e in events if e["type"].endswith("received"))["envelope"]["payload"]
    assert set(received) == {"item_id", "post_id", "trigger", "has_content", "posted_at"}
    # Audit'ga ham izoh matni tushmaydi
    audit = _admin_sql(
        world, "SELECT diff::text AS diff FROM audit.audit_entries WHERE shop_id = $1", ig.shop.id
    )
    assert all("Maxfiy" not in (r["diff"] or "") for r in audit)


def test_post_media_is_fetched_in_background_without_bumping_version(
    world: World, flag: None, llm: FakeProvider
) -> None:
    ig = Ig(world)
    ig.fake.media["media-1"] = MediaInfo(
        "REELS",
        "https://instagram.com/reel/abc",
        "RTX 4060 " * 40,
        "https://cdn/x.jpg",
        datetime(2026, 10, 20, tzinfo=UTC),
    )
    ig.comment("Zo'r!")
    first = ig.post()
    assert first["permalink"] == "https://instagram.com/reel/abc" and first["media_type"] == "REELS"
    assert first["thumbnail_url"] == "https://cdn/x.jpg" and len(first["caption_excerpt"]) == 200
    ig.comment(
        "+", author="2"
    )  # yangi izoh va media ma'lumoti post versiyasini oshirmaydi (If-Match buzilmaydi)
    again = ig.post()
    assert again["version"] == first["version"] and again["comment_count"] == 2


# ------------------------------------------------------------------ ruxsat bekor qilindi (UAT-M09, TC-011)
def test_instagram_revoked_token_degrades_channel_and_blocks_further_sends(world: World, flag: None) -> None:
    ig = Ig(world)
    ig.fake.sent.clear()
    payload = {
        "object": "instagram",
        "entry": [
            {
                "id": ig.account_id,
                "messaging": [
                    {
                        "sender": {"id": "9001"},
                        "recipient": {"id": ig.account_id},
                        "timestamp": int(time.time() * 1000),
                        "message": {"mid": f"m.{uuid4().hex}", "text": "Salom, narxi qancha?"},
                    }
                ],
            }
        ],
    }
    raw = json.dumps(payload).encode()
    signature = "sha256=" + hmac.new(SECRET.encode(), raw, hashlib.sha256).hexdigest()
    delivered = world.client.post(
        "/api/v1/webhooks/instagram",
        content=raw,
        headers={"X-Hub-Signature-256": signature, "Content-Type": "application/json"},
    )
    assert delivered.status_code == 200, delivered.text
    _drain_now(world)
    listed = _ok(world.client.get("/api/v1/shop/conversations", headers=_bearer(ig.owner)))["items"]
    [conversation] = [c for c in listed if c["channel"] == "INSTAGRAM"]
    ig.fake.send_errors = [ChannelSendError("AUTH_REVOKED")]
    reply = world.client.post(
        f"/api/v1/shop/conversations/{conversation['id']}/messages",
        json={"body": "Ha, bor!"},
        headers=_bearer(ig.owner, **_idem()),
    )
    assert reply.status_code == 201, reply.text
    _drain_retrying(world)

    channel = _ok(world.client.get(f"/api/v1/shop/channels/{ig.channel_id}", headers=_bearer(ig.owner)))
    assert channel["status"] == "DEGRADED"
    tasks = _ok(world.client.get("/api/v1/shop/tasks?status=OPEN", headers=_bearer(ig.owner)))["items"]
    assert [t for t in tasks if t["type"] == "CHANNEL_DEGRADED"]
    # DEGRADED kanal hali "yuborish mumkin" (tiklanishi mumkin); keyingi yuborish toza FAILED bo'ladi
    ig.fake.send_errors = [ChannelSendError("AUTH_REVOKED")]
    again = world.client.post(
        f"/api/v1/shop/conversations/{conversation['id']}/messages",
        json={"body": "Yana"},
        headers=_bearer(ig.owner, **_idem()),
    )
    assert again.status_code == 201, again.text
    _drain_retrying(world)
    messages = _ok(
        world.client.get(
            f"/api/v1/shop/conversations/{conversation['id']}/messages", headers=_bearer(ig.owner)
        )
    )["items"]
    assert [m["delivery_status"] for m in messages if m["direction"] == "OUT"] == ["FAILED", "FAILED"]
    assert messages[-1]["last_error_code"] == "AUTH_REVOKED"
    channel = _ok(world.client.get(f"/api/v1/shop/channels/{ig.channel_id}", headers=_bearer(ig.owner)))
    assert channel["status"] == "DEGRADED"
    tasks = _ok(world.client.get("/api/v1/shop/tasks?status=OPEN", headers=_bearer(ig.owner)))["items"]
    assert len([t for t in tasks if t["type"] == "CHANNEL_DEGRADED"]) == 1
    assert ig.fake.sent == []


# ------------------------------------------------------------------ Direct echo: Instagram ilovasidan javob
def _dm(ig: Ig, *items: dict[str, Any]) -> Any:
    payload = {
        "object": "instagram",
        "entry": [{"id": ig.account_id, "time": int(time.time()), "messaging": list(items)}],
    }
    raw = json.dumps(payload).encode()
    signature = "sha256=" + hmac.new(SECRET.encode(), raw, hashlib.sha256).hexdigest()
    return ig.world.client.post(
        "/api/v1/webhooks/instagram",
        content=raw,
        headers={"X-Hub-Signature-256": signature, "Content-Type": "application/json"},
    )


def test_echo_from_instagram_app_is_recorded_as_staff_and_own_echo_is_ignored(
    world: World, flag: None
) -> None:
    ig = Ig(world)
    stamp = int(time.time() * 1000)
    customer = {"sender": {"id": "IGSID-7"}, "recipient": {"id": ig.account_id}, "timestamp": stamp}
    assert _dm(ig, {**customer, "message": {"mid": "mid-in-1", "text": "Narxi qancha?"}}).status_code == 200
    echo = {"sender": {"id": ig.account_id}, "recipient": {"id": "IGSID-7"}, "timestamp": stamp + 1000}
    # xodim Instagram ilovasining o'zidan javob yozdi
    assert (
        _dm(
            ig, {**echo, "message": {"mid": "mid-echo-1", "is_echo": True, "text": "4 800 000 so'm"}}
        ).status_code
        == 200
    )
    # Meta qayta yubordi — takrorlanmaydi
    assert (
        _dm(
            ig, {**echo, "message": {"mid": "mid-echo-1", "is_echo": True, "text": "4 800 000 so'm"}}
        ).status_code
        == 200
    )
    rows = _admin_sql(
        world,
        "SELECT m.direction, m.author_type, m.origin, m.delivery_status, m.body FROM messaging.messages m "
        "JOIN messaging.conversations c ON c.id = m.conversation_id WHERE c.shop_id = $1 ORDER BY m.seq",
        ig.shop.id,
    )
    assert [(r["direction"], r["author_type"], r["delivery_status"], r["body"]) for r in rows] == [
        ("IN", "CUSTOMER", "RECEIVED", "Narxi qancha?"),
        ("OUT", "STAFF", "SENT", "4 800 000 so'm"),
    ]
    # bizdan ketgan xabarning echo'si (provider_message_id bir xil) qayta yozilmaydi
    _admin_sql(
        world,
        "UPDATE messaging.messages SET provider_message_id = 'mid-ours-1' WHERE shop_id = $1 AND direction = 'OUT'",
        ig.shop.id,
    )
    assert (
        _dm(ig, {**echo, "message": {"mid": "mid-ours-1", "is_echo": True, "text": "boshqa"}}).status_code
        == 200
    )
    # xaridor hali yozmagan suhbatdoshga echo — suhbat ochilmaydi
    stranger = {"sender": {"id": ig.account_id}, "recipient": {"id": "IGSID-NEW"}, "timestamp": stamp}
    assert (
        _dm(ig, {**stranger, "message": {"mid": "mid-echo-2", "is_echo": True, "text": "salom"}}).status_code
        == 200
    )
    count = _admin_sql(
        world,
        "SELECT count(*) AS n FROM messaging.messages m JOIN messaging.conversations c ON c.id = m.conversation_id "
        "WHERE c.shop_id = $1",
        ig.shop.id,
    )
    assert count[0]["n"] == 2


# ------------------------------------------------------------------ "Instagram bilan ulash" (OAuth)
@pytest.fixture
def oauth(world: World, flag: None) -> Iterator[None]:
    config = world.client.app.state.messaging.config
    saved = config.instagram_app_id
    object.__setattr__(config, "instagram_app_id", "1096504406590111")
    yield
    object.__setattr__(config, "instagram_app_id", saved)


def test_oauth_start_and_callback_connect_account(world: World, oauth: None) -> None:
    from urllib.parse import parse_qs, urlsplit

    shop = Shop(world)
    account_id = str(int(uuid4().int % 10**12) + 10**12)
    page_token = f"EAApage{uuid4().hex}{uuid4().hex}"
    fake = FakeInstagramClient(accounts={page_token: InstagramAccount(account_id, "noutbuk_uz", SCOPE)})
    fake.codes["good-code"] = page_token
    world.client.app.state.messaging.adapters.instagram = fake

    listed = _ok(world.client.get("/api/v1/shop/channels", headers=_bearer(shop.owner)))
    assert listed["instagram_oauth_available"] is True
    started = _ok(
        _post(world, shop.owner, "/channels/instagram/oauth", {"return_path": "/noutbukuz/channels"})
    )
    url = urlsplit(started["url"])
    query = parse_qs(url.query)
    assert url.netloc == "www.facebook.com" and query["client_id"] == ["1096504406590111"]
    assert query["redirect_uri"][0].endswith("/api/v1/webhooks/instagram/oauth")
    state = query["state"][0]

    # Foydalanuvchi rad etdi — code yo'q
    denied = world.client.get(f"/api/v1/webhooks/instagram/oauth?state={state}", follow_redirects=False)
    assert denied.status_code == 303 and "instagram=error" in denied.headers["location"]
    # Soxta state
    forged = world.client.get(
        "/api/v1/webhooks/instagram/oauth?code=good-code&state=x.y", follow_redirects=False
    )
    assert "reason=state" in forged.headers["location"]
    # Muvaffaqiyat
    ok = world.client.get(
        f"/api/v1/webhooks/instagram/oauth?code=good-code&state={state}", follow_redirects=False
    )
    assert ok.status_code == 303
    assert ok.headers["location"].endswith("/noutbukuz/channels?instagram=connected")
    channels = _ok(world.client.get("/api/v1/shop/channels", headers=_bearer(shop.owner)))["items"]
    ig = [c for c in channels if c["channel"] == "INSTAGRAM"]
    assert ig and ig[0]["status"] == "CONNECTED" and ig[0]["display_name"] == "@noutbuk_uz"
    assert fake.subscribed == [account_id]


def test_oauth_rejects_open_redirect_and_unknown_code(world: World, oauth: None) -> None:
    shop = Shop(world)
    world.client.app.state.messaging.adapters.instagram = FakeInstagramClient()
    started = _ok(_post(world, shop.owner, "/channels/instagram/oauth", {"return_path": "//evil.example/x"}))
    from urllib.parse import parse_qs, urlsplit

    state = parse_qs(urlsplit(started["url"]).query)["state"][0]
    bad = world.client.get(
        f"/api/v1/webhooks/instagram/oauth?code=nope&state={state}", follow_redirects=False
    )
    location = bad.headers["location"]
    assert location.startswith("http://localhost:3000/?") and "reason=code" in location  # yo'l "/" ga tushdi


def test_oauth_hidden_without_app_id(world: World, flag: None) -> None:
    shop = Shop(world)
    listed = _ok(world.client.get("/api/v1/shop/channels", headers=_bearer(shop.owner)))
    assert listed["instagram_oauth_available"] is False
    assert _post(world, shop.owner, "/channels/instagram/oauth", {}).status_code == 422


def _signed_request(user_id: str, secret: str = SECRET) -> str:
    import base64
    import hashlib
    import hmac
    import json

    def b64(data: bytes) -> str:
        return base64.urlsafe_b64encode(data).decode().rstrip("=")

    payload = b64(json.dumps({"algorithm": "HMAC-SHA256", "user_id": user_id}).encode())
    return f"{b64(hmac.new(secret.encode(), payload.encode(), hashlib.sha256).digest())}.{payload}"


def test_meta_data_deletion_disconnects_accounts_of_that_facebook_user(world: World, oauth: None) -> None:
    from urllib.parse import parse_qs, urlsplit

    shop = Shop(world)
    account_id = str(int(uuid4().int % 10**12) + 10**12)
    user_token, meta_user = f"EAAuser{uuid4().hex}", str(uuid4().int % 10**15)
    fake = FakeInstagramClient(accounts={user_token: InstagramAccount(account_id, "noutbuk_uz", SCOPE)})
    fake.codes["code-1"], fake.user_ids[user_token] = user_token, meta_user
    world.client.app.state.messaging.adapters.instagram = fake
    started = _ok(_post(world, shop.owner, "/channels/instagram/oauth", {"return_path": "/x/channels"}))
    state = parse_qs(urlsplit(started["url"]).query)["state"][0]
    world.client.get(f"/api/v1/webhooks/instagram/oauth?code=code-1&state={state}", follow_redirects=False)

    form = {"content-type": "application/x-www-form-urlencoded"}
    # Soxta imzo — 404, hech narsa o'zgarmaydi
    forged = world.client.post(
        "/api/v1/webhooks/instagram/data-deletion",
        content=f"signed_request={_signed_request(meta_user, 'wrong')}",
        headers=form,
    )
    assert forged.status_code == 404
    # Boshqa Facebook foydalanuvchisi — kod qaytadi, lekin bu shop ulangan qoladi
    other = world.client.post(
        "/api/v1/webhooks/instagram/deauthorize",
        content=f"signed_request={_signed_request('999')}",
        headers=form,
    )
    assert other.status_code == 200
    channels = _ok(world.client.get("/api/v1/shop/channels", headers=_bearer(shop.owner)))["items"]
    assert [c["status"] for c in channels if c["channel"] == "INSTAGRAM"] == ["CONNECTED"]

    deleted = world.client.post(
        "/api/v1/webhooks/instagram/data-deletion",
        content=f"signed_request={_signed_request(meta_user)}",
        headers=form,
    )
    body = _ok(deleted)
    code = body["confirmation_code"]
    assert body["url"].endswith(f"/api/v1/webhooks/instagram/data-deletion/{code}")
    channels = _ok(world.client.get("/api/v1/shop/channels", headers=_bearer(shop.owner)))["items"]
    assert [c["status"] for c in channels if c["channel"] == "INSTAGRAM"] == ["DISCONNECTED"]
    status = world.client.get(f"/api/v1/webhooks/instagram/data-deletion/{code}")
    assert status.status_code == 200 and code in status.text


def test_direct_image_is_stored_and_voice_is_transcribed(world: World, flag: None, llm: FakeProvider) -> None:
    """DEC-149 (pilot paytida): Direct rasmi yopiq omborga, ovozi matnga; begona host — yuklanmaydi."""
    from tests.images import png

    ig = Ig(world)
    stamp = int(time.time() * 1000)
    image_url = "https://scontent.cdninstagram.com/v/img-1.png"
    voice_url = "https://lookaside.fbsbx.com/ig_messaging_cdn/?asset_id=1"
    ig.fake.dm_media[image_url] = png()
    ig.fake.dm_media[voice_url] = b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 200
    llm.push_light(FakeText("RTX 4060 bormi?"))
    base = {"sender": {"id": "IGSID-9"}, "recipient": {"id": ig.account_id}}
    image = {"type": "image", "payload": {"url": image_url}}
    voice = {"type": "audio", "payload": {"url": voice_url}}
    evil = {"type": "image", "payload": {"url": "https://evil.example.com/x.png"}}
    assert (
        _dm(
            ig, {**base, "timestamp": stamp, "message": {"mid": "mid-img", "attachments": [image, evil]}}
        ).status_code
        == 200
    )
    assert (
        _dm(
            ig, {**base, "timestamp": stamp + 1, "message": {"mid": "mid-voice", "attachments": [voice]}}
        ).status_code
        == 200
    )
    _drain_now(world)
    rows = _admin_sql(
        world,
        "SELECT m.kind, m.body, a.status, a.error_code FROM messaging.messages m "
        "JOIN messaging.attachments a ON a.message_id = m.id WHERE m.shop_id = $1 ORDER BY m.seq",
        ig.shop.id,
    )
    assert [(r["kind"], r["status"]) for r in rows] == [("IMAGE", "STORED"), ("VOICE", "PURGED")]  # evil yo'q
    assert rows[1]["body"] == "RTX 4060 bormi?" and rows[1]["error_code"] == "TRANSCRIBED"
