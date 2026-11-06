"""S3-mos FileStorage adapteri (S0-10, TD-03) — moto bilan, tarmoqsiz."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import boto3
import pytest
from moto import mock_aws

from app.config.settings import Settings
from app.platform.storage.config import S3Config, StorageConfig, build_file_storage
from app.platform.storage.local import LocalDiskStorage
from app.platform.storage.s3 import S3FileStorage

SHOP = "0192a3b4-0000-7000-8000-000000000001"
PRIVATE_KEY = f"shops/{SHOP}/stock_evidence/0192-abc.png"
PUBLIC_KEY = f"shops/{SHOP}/product_image/0192-def.webp"


@pytest.fixture
def s3_client(monkeypatch: pytest.MonkeyPatch) -> Iterator[Any]:
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    with mock_aws():
        client = boto3.client("s3", region_name="us-east-1")
        client.create_bucket(Bucket="cos-private")
        client.create_bucket(Bucket="cos-public")
        yield client


async def test_put_get_delete_roundtrip_private(s3_client: Any) -> None:
    storage = S3FileStorage(s3_client, "cos-private", "cos-public")
    await storage.put(PRIVATE_KEY, b"\x89PNG data", "image/png")
    assert await storage.get(PRIVATE_KEY) == b"\x89PNG data"
    head = s3_client.head_object(Bucket="cos-private", Key=PRIVATE_KEY)
    assert head["ContentType"] == "image/png"
    assert head["CacheControl"] == "private, no-store"
    await storage.delete(PRIVATE_KEY)
    assert await storage.get(PRIVATE_KEY) is None


async def test_public_purpose_goes_to_public_bucket(s3_client: Any) -> None:
    storage = S3FileStorage(s3_client, "cos-private", "cos-public")
    await storage.put(PUBLIC_KEY, b"img", "image/webp")
    head = s3_client.head_object(Bucket="cos-public", Key=PUBLIC_KEY)
    assert head["CacheControl"].startswith("public")
    assert s3_client.list_objects_v2(Bucket="cos-private").get("KeyCount") == 0
    assert await storage.get(PUBLIC_KEY) == b"img"


async def test_without_public_bucket_everything_is_private(s3_client: Any) -> None:
    storage = S3FileStorage(s3_client, "cos-private")
    await storage.put(PUBLIC_KEY, b"img", "image/webp")
    assert s3_client.head_object(Bucket="cos-private", Key=PUBLIC_KEY)["ContentLength"] == 3


async def test_missing_key_and_double_delete_are_not_errors(s3_client: Any) -> None:
    storage = S3FileStorage(s3_client, "cos-private")
    assert await storage.get(PRIVATE_KEY) is None
    await storage.delete(PRIVATE_KEY)  # yo'q kalit — xato emas (port talabi)


@pytest.mark.parametrize("key", ["../etc/passwd", "/abs", "shops/../x", "a\\b", ""])
async def test_invalid_keys_rejected_like_local_adapter(s3_client: Any, key: str) -> None:
    storage = S3FileStorage(s3_client, "cos-private")
    assert await storage.get(key) is None
    with pytest.raises(ValueError, match="invalid storage key"):
        await storage.put(key, b"x", "text/plain")
    with pytest.raises(ValueError, match="invalid storage key"):
        await storage.delete(key)


async def test_other_s3_errors_propagate(s3_client: Any) -> None:
    from botocore.exceptions import ClientError

    storage = S3FileStorage(s3_client, "no-such-bucket")
    with pytest.raises(ClientError):
        await storage.get(PRIVATE_KEY)
    with pytest.raises(ClientError):
        await storage.check()


async def test_from_config_builds_working_client(s3_client: Any) -> None:
    storage = build_file_storage(
        StorageConfig(
            backend="s3",
            local_dir=Path("unused"),
            s3=S3Config(private_bucket="cos-private", access_key_id="testing", secret_access_key="testing"),
        )
    )
    assert isinstance(storage, S3FileStorage)
    await storage.put(PRIVATE_KEY, b"x", "image/png")
    assert await storage.get(PRIVATE_KEY) == b"x"
    await storage.check()


def test_settings_select_backend(tmp_path: Path) -> None:
    local = Settings(storage_local_dir=str(tmp_path))
    assert isinstance(build_file_storage(local.storage_config()), LocalDiskStorage)

    s3 = Settings(
        storage_backend="s3",
        s3_private_bucket="cos-private",
        s3_public_bucket="cos-public",
        s3_endpoint_url="https://s3.example.uz",
        s3_access_key_id="key",
        s3_secret_access_key="secret",
    )
    config = s3.storage_config()
    assert config.s3 is not None
    assert config.s3.public_bucket == "cos-public" and config.s3.endpoint_url == "https://s3.example.uz"
    assert config.s3.secret_access_key == "secret"


def test_settings_reject_incomplete_s3() -> None:
    with pytest.raises(ValueError, match="S3_PRIVATE_BUCKET"):
        Settings(storage_backend="s3")
    with pytest.raises(ValueError, match="birga"):
        Settings(storage_backend="s3", s3_private_bucket="b", s3_access_key_id="only-key")
