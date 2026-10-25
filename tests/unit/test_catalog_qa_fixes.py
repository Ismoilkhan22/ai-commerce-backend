"""2-modul QA tuzatishlari (progress/M02 §QA): bazasiz qismlar — so'rov qo'riqchisi, qayta urinish,
chegaralar, so'mga o'girish chegarasi, avtomatik bog'lashdagi variant qoidasi, fayl tuzilmasi, matn tipi."""

from __future__ import annotations

import asyncio
from decimal import Decimal
from typing import Any
from uuid import uuid4

import pytest
from pydantic import BaseModel, Field
from pydantic import ValidationError as PydanticValidationError
from sqlalchemy.exc import DBAPIError
from starlette.types import Message, Receive, Scope, Send

from app.domains.catalog.pc_specs.models.orm import ReferenceHardwareSpec
from app.domains.catalog.pc_specs.services.link_service import sizes_in, variant_agrees
from app.domains.catalog.products.models.orm import Product, Sku
from app.domains.catalog.products.schemas import PriceIn, SkuIn
from app.platform.storage.services.file_service import _clean_name
from app.platform.storage.sniff import sniff_mime
from app.shared.errors.handlers import validation_fields
from app.shared.money import MAX_RATE, MAX_SAFE_MINOR, MAX_USD_MINOR, to_uzs_minor
from app.shared.request_guard import (
    RequestGuardMiddleware,
    _json_problems,
    _query_problems,
    sqlstate_of,
)
from app.shared.text import Text
from tests import images

# ------------------------------------------------------------------ M1, L1: NUL va NaN


def test_query_with_nul_is_reported_by_parameter_name() -> None:
    assert _query_problems(b"q=%00&limit=5") == ["q"]
    assert _query_problems(b"q=rtx%204060") == []


def test_json_nul_and_non_finite_values_report_field_paths() -> None:
    import json

    from app.shared.request_guard import _NonFinite

    data = json.loads(
        '{"title": "a\\u0000", "skus": [{"variant_name": "ok"}, {"attributes": {"x\\u0000": 1, "y": NaN}}]}',
        parse_constant=_NonFinite,
    )
    assert sorted(_json_problems(data)) == ["skus[1].attributes", "skus[1].attributes.y", "title"]
    assert _json_problems({"title": "MSI RTX 4060", "skus": [{"qty": 1.5}]}) == []


def test_text_type_trims_before_length_and_rejects_nul() -> None:
    class Model(BaseModel):
        note: Text = Field(min_length=3)

    assert Model(note="  yaxshi  ").note == "yaxshi"
    with pytest.raises(PydanticValidationError) as blank:
        Model(note="    ")  # L5: faqat bo'shliq — bo'sh hisoblanadi
    assert blank.value.errors()[0]["type"] == "string_too_short"
    with pytest.raises(PydanticValidationError):
        Model(note="abc\x00")


def test_sku_attributes_reject_non_finite_and_unsafe_numbers() -> None:  # L1
    for bad in (float("nan"), float("inf"), 2**60):
        with pytest.raises(PydanticValidationError):
            SkuIn.model_validate({"sku_code": "A-1", "attributes": {"x": bad}})
    assert SkuIn.model_validate({"sku_code": " A-1 ", "attributes": {"vram_gb": 8}}).sku_code == "A-1"


# ------------------------------------------------------------------ L4: deadlock — qayta urinish


class _Deadlock(Exception):
    pgcode = "40P01"


def _deadlock() -> DBAPIError:
    return DBAPIError("UPDATE ...", {}, _Deadlock("deadlock detected"))


def test_sqlstate_is_found_through_the_exception_chain() -> None:
    assert sqlstate_of(_deadlock()) == "40P01"
    assert sqlstate_of(ValueError("x")) is None


async def _call(
    app: Any, method: str = "POST", body: bytes = b"{}", path: str = "/x"
) -> tuple[int, list[Message]]:
    sent: list[Message] = []
    delivered = False

    async def receive() -> Message:
        nonlocal delivered
        if not delivered:
            delivered = True
            return {"type": "http.request", "body": body, "more_body": False}
        await asyncio.sleep(3600)
        return {"type": "http.disconnect"}

    async def send(message: Message) -> None:
        sent.append(message)

    headers = [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())]
    scope = {"type": "http", "method": method, "path": path, "query_string": b"", "headers": headers}
    await RequestGuardMiddleware(app)(scope, receive, send)
    return sent[0]["status"], sent


def _app(fail_times: int, seen: list[bytes]) -> Any:
    async def app(scope: Scope, receive: Receive, send: Send) -> None:
        message = await receive()
        seen.append(message["body"])  # har urinish tanani to'liq oladi
        if len(seen) <= fail_times:
            raise _deadlock()
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    return app


def test_deadlock_retries_whole_request_with_same_body() -> None:  # 12 §3
    seen: list[bytes] = []
    status, _ = asyncio.run(_call(_app(2, seen), body=b'{"a": 1}'))
    assert status == 200 and seen == [b'{"a": 1}'] * 3


def test_deadlock_after_three_attempts_is_409_not_500() -> None:
    seen: list[bytes] = []
    status, sent = asyncio.run(_call(_app(5, seen)))
    assert status == 409 and len(seen) == 3
    assert b"VERSION_CONFLICT" in sent[1]["body"]


def test_auth_routes_are_not_retried_so_rate_limits_count_once() -> None:
    # Login rate limit hisoblagichi tranzaksiyadan tashqarida: qayta urinish uni ikki marta oshirardi
    seen: list[bytes] = []
    status, sent = asyncio.run(_call(_app(1, seen), path="/api/v1/auth/login"))
    assert status == 409 and len(seen) == 1
    assert b"VERSION_CONFLICT" in sent[1]["body"]


def test_other_database_errors_are_not_retried() -> None:
    class _Unique(Exception):
        pgcode = "23505"

    calls: list[int] = []

    async def app(scope: Scope, receive: Receive, send: Send) -> None:
        calls.append(1)
        raise DBAPIError("INSERT ...", {}, _Unique("duplicate"))

    with pytest.raises(DBAPIError):
        asyncio.run(_call(app))
    assert calls == [1]


# ------------------------------------------------------------------ L16: qat'iy chegara


def test_exclusive_bounds_report_the_allowed_value() -> None:
    fields = validation_fields(
        [
            {"type": "greater_than", "loc": ("body", "amount_minor"), "ctx": {"gt": 0}},
            {"type": "greater_than", "loc": ("body", "rate"), "ctx": {"gt": Decimal("0")}},
            {"type": "less_than", "loc": ("query", "limit"), "ctx": {"lt": 101}},
        ]
    )
    assert fields[0] == {"field": "amount_minor", "code": "min_value", "params": {"min": 1}}
    assert fields[1] == {
        "field": "rate",
        "code": "min_value",
        "params": {"min": Decimal("0"), "exclusive": True},
    }
    assert fields[2] == {"field": "limit", "code": "max_value", "params": {"max": 100}}


# ------------------------------------------------------------------ L17 va so'mga o'girish


def test_usd_cap_keeps_any_rate_inside_safe_integer() -> None:
    assert to_uzs_minor(MAX_USD_MINOR, "USD", Decimal(MAX_RATE)) is not None
    assert (to_uzs_minor(MAX_USD_MINOR, "USD", Decimal(MAX_RATE)) or 0) <= MAX_SAFE_MINOR
    assert to_uzs_minor(10**15, "USD", Decimal("12850")) is None  # eski, chegaradan katta yozuv
    assert to_uzs_minor(1, "USD", Decimal("12850")) == 12_900  # 128.5 so'm → 129 so'm (yarmi yuqoriga)
    with pytest.raises(PydanticValidationError) as too_big:
        PriceIn(currency="USD", amount_minor=MAX_USD_MINOR + 1)
    error = too_big.value.errors()[0]
    assert (error["loc"], error["type"]) == (("amount_minor",), "less_than_equal")
    assert PriceIn(currency="UZS", amount_minor=10**15).amount_minor == 10**15


# ------------------------------------------------------------------ M3: variant qoidasi


def _spec(variant_key: str = "", **attributes: Any) -> ReferenceHardwareSpec:
    return ReferenceHardwareSpec(
        id=uuid4(),
        category="GPU",
        brand="MSI",
        model_name="RTX 9970",
        variant_key=variant_key,
        attributes=attributes,
    )


def _sku(variant: str | None = None, **attributes: Any) -> Sku:
    return Sku(variant_name=variant, attributes=attributes)


def test_sizes_are_read_from_text() -> None:
    assert sizes_in("RTX 4060 8 GB GDDR6 17Gbps", "16GB (2x8GB)", "1TB") == {"8GB", "16GB", "1000GB"}


def test_variant_spec_needs_the_same_size_on_the_sku() -> None:
    product = Product(title="MSI RTX 9970")
    eight = _spec("8GB", memory_gb=8)
    assert variant_agrees(eight, _sku("8 GB"), product)
    assert not variant_agrees(eight, _sku("16GB"), product)  # 8GB ↔ 16GB hech qachon
    assert not variant_agrees(eight, _sku(None), product)  # hajm aytilmagan — shubhali
    assert not variant_agrees(eight, _sku("8GB", vram_gb=16), product)  # atribut boshqa hajm aytadi
    assert variant_agrees(_spec("OC"), _sku("OC Edition"), product)  # hajmsiz variant — nom bo'yicha


def test_single_variant_spec_rejects_contradicting_size() -> None:
    product = Product(title="MSI RTX 9970")
    plain = _spec("", memory_gb=8)
    assert variant_agrees(plain, _sku(None), product)
    assert variant_agrees(plain, _sku("8GB"), product)
    assert not variant_agrees(plain, _sku("16GB"), product)
    ram = ReferenceHardwareSpec(
        category="RAM",
        brand="Kingston",
        model_name="Fury Beast",
        variant_key="",
        attributes={"module_count": 2, "capacity_per_module_gb": 8},
    )
    assert variant_agrees(ram, _sku("16GB (2x8GB)"), Product(title="Kingston Fury Beast"))
    assert not variant_agrees(ram, _sku("32GB"), Product(title="Kingston Fury Beast"))
    ssd = ReferenceHardwareSpec(
        category="STORAGE",
        brand="Samsung",
        model_name="990 PRO",
        variant_key="",
        attributes={"capacity_gb": 1000},
    )
    assert variant_agrees(ssd, _sku(None), Product(title="Samsung 990 PRO 1TB NVMe"))
    assert not variant_agrees(ssd, _sku(None), Product(title="Samsung 990 PRO 2TB NVMe"))


# ------------------------------------------------------------------ L12 va fayl nomi


def test_sniff_rejects_truncated_or_disguised_images() -> None:
    assert sniff_mime(b"\xff\xd8\xff") is None  # 3 bayt "JPEG"
    assert sniff_mime(b"RIFF\x00\x00\x00\x00WEBP") is None
    assert sniff_mime(b"\x89PNG\r\n\x1a\n<html><script>alert(1)</script></html>") is None
    assert sniff_mime(images.png()[:-12]) is None  # IEND'siz — kesilgan
    assert sniff_mime(images.png()[:-20]) is None  # IDAT o'rtasida kesilgan
    assert sniff_mime(images.png(width=0)) is None
    assert sniff_mime(b"\xff\xd8\xff\xda\x00\x02" + b"\x00" * 16) is None  # SOF'siz
    oversized = bytearray(images.webp())
    oversized[4:8] = (10_000).to_bytes(4, "little")  # RIFF hajmi fayldan katta
    assert sniff_mime(bytes(oversized)) is None


def test_png_with_bytes_after_iend_is_accepted() -> None:  # B2: ba'zi dasturlar oxiriga qo'shadi
    assert sniff_mime(images.png() + b"\x00" * 8) == "image/png"
    assert sniff_mime(images.png() + b"trailing metadata") == "image/png"


def test_file_names_drop_bidi_controls() -> None:
    assert _clean_name("rasm\u202egnp.exe") == "rasmgnp.exe"
    assert _clean_name("C:\\fakes\\a\u2066b\u2069.png") == "ab.png"
