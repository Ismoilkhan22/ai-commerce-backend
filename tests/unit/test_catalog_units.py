"""2-modul yordamchilari: so'mga o'girish, normallashtirish, fayl turi, imzo, disk, atributlar."""

from __future__ import annotations

import asyncio
from decimal import Decimal
from pathlib import Path

import pytest

from app.domains.catalog.pc_specs.attributes import validate_attributes
from app.domains.catalog.pc_specs.normalize import normalize_code
from app.platform.storage.local import LocalDiskStorage
from app.platform.storage.services.file_service import shop_id_from_key
from app.platform.storage.signing import UrlSigner
from app.platform.storage.sniff import sniff_mime
from app.shared.errors.base import ValidationError
from app.shared.money import to_uzs_minor
from app.shared.pagination import decode_cursor, encode_cursor
from tests import images


@pytest.mark.parametrize(
    ("amount", "currency", "rate", "expected"),
    [
        (450_000_000, "UZS", None, 450_000_000),  # so'm narxi kursga bog'liq emas
        (30_000, "USD", Decimal("12800"), 384_000_000),  # UAT-M05: 300 $ → 3 840 000 so'm
        (30_000, "USD", Decimal("12835"), 385_050_000),  # yaxlitlanmaydi: 3 850 500 so'm (DEC-133)
        (30_000, "USD", Decimal("12835.5"), 385_065_000),
        (30_000, "USD", Decimal("12800.123456"), 384_003_700),  # kasr tiyin → eng yaqin so'm
        (1, "USD", Decimal("12850.50"), 12_900),  # 128.505 so'm → 129 so'm (yarmi yuqoriga)
        (30_000, "USD", None, None),  # kurs yo'q — ko'rsatib bo'lmaydi
    ],
)
def test_to_uzs_minor(amount: int, currency: str, rate: Decimal | None, expected: int | None) -> None:
    assert to_uzs_minor(amount, currency, rate) == expected  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("raw", "normalized"),
    [
        ("V516-012R", "V516012R"),
        ("  geforce rtx 4060 ti ", "GEFORCERTX4060TI"),
        ("B650M-A_WIFI", "B650MAWIFI"),
        ("---", None),
        (None, None),
    ],
)
def test_normalize_code(raw: str | None, normalized: str | None) -> None:
    assert normalize_code(raw) == normalized


def test_rtx_ti_and_variants_never_normalize_to_the_same_code() -> None:  # engineering/17 §5
    assert normalize_code("RTX 5060") != normalize_code("RTX 5060 Ti")
    assert normalize_code("B650M") != normalize_code("B650")


def test_sniff_uses_content_not_name() -> None:
    assert sniff_mime(images.jpeg()) == "image/jpeg"
    assert sniff_mime(images.png()) == "image/png"
    assert sniff_mime(images.webp()) == "image/webp"
    assert sniff_mime(b"GIF89a....") is None
    assert (
        sniff_mime(b"<svg xmlns='http://www.w3.org/2000/svg'/>") is None
    )  # SVG ichida skript bo'lishi mumkin
    assert sniff_mime(b"MZ\x90\x00") is None


def test_signed_url_binds_key_and_expiry() -> None:
    signer = UrlSigner("secret")
    sig = signer.sign("shops/a/b/c.png", 2_000)
    assert signer.verify("shops/a/b/c.png", 2_000, sig, now=1_000)
    assert not signer.verify("shops/a/b/other.png", 2_000, sig, now=1_000)
    assert not signer.verify("shops/a/b/c.png", 2_001, sig, now=1_000)
    assert not signer.verify("shops/a/b/c.png", 2_000, sig, now=2_001)  # muddati o'tdi
    assert not UrlSigner("other").verify("shops/a/b/c.png", 2_000, sig, now=1_000)


def test_local_storage_round_trip_and_rejects_traversal(tmp_path: Path) -> None:
    storage = LocalDiskStorage(tmp_path / "files")

    async def scenario() -> None:
        await storage.put("shops/1/product_image/x.png", b"data", "image/png")
        assert await storage.get("shops/1/product_image/x.png") == b"data"
        await storage.delete("shops/1/product_image/x.png")
        assert await storage.get("shops/1/product_image/x.png") is None
        for bad in ("../outside.png", "/etc/passwd", "shops/../../x", "shops\\x"):
            with pytest.raises(ValueError):
                await storage.put(bad, b"x", "image/png")
            assert await storage.get(bad) is None

    asyncio.run(scenario())
    assert not (tmp_path / "outside.png").exists()


def test_shop_id_is_taken_from_object_key() -> None:
    key = "shops/0192b6f0-0000-7000-8000-000000000001/product_image/f.png"
    assert str(shop_id_from_key(key)) == "0192b6f0-0000-7000-8000-000000000001"
    assert shop_id_from_key("other/x/y/z") is None
    assert shop_id_from_key("shops/not-uuid/a/b") is None


def test_spec_attributes_follow_category_schema() -> None:  # engineering/17 §4.1
    gpu = validate_attributes(
        "GPU", {"length_mm": 199, "power_connectors": [{"type": "PCIE_8PIN", "count": 1}], "slot_width": None}
    )
    assert gpu == {
        "length_mm": 199,
        "power_connectors": [{"type": "PCIE_8PIN", "count": 1}],
    }  # None — noma'lum
    with pytest.raises(ValidationError) as unknown:
        validate_attributes("GPU", {"colour": "black"})
    assert unknown.value.details["fields"][0]["field"] == "attributes.colour"  # type: ignore[index]
    with pytest.raises(ValidationError) as wrong:
        validate_attributes("RAM", {"type": "DDR6"})
    assert wrong.value.details["fields"][0]["code"] == "invalid_choice"  # type: ignore[index]


def test_cursor_round_trip_and_garbage() -> None:
    assert decode_cursor(encode_cursor({"s": "title", "v": "A", "id": "x"})) == {
        "s": "title",
        "v": "A",
        "id": "x",
    }
    for garbage in ("%%%", "bm90LWpzb24", "WzFd"):  # "not-json", "[1]"
        with pytest.raises(ValidationError):
            decode_cursor(garbage)
