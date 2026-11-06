"""FileStorage — S3-mos ombor adapteri (production, S0-10, TD-03).

- Ikki bucket: yopiq (chek rasmi, import fayli, suhbat rasmi) va ixtiyoriy ochiq (mahsulot rasmi, logotip).
  Qaysi biriga — kalitdagi purpose bo'lagidan (`shops/{shop_id}/{purpose}/...`), port o'zgarmaydi.
- Havolalar adapterda emas: ochiq fayl `public_files_url` dan, yopiq — `UrlSigner` imzosi bilan API orqali
  (lokal adapter bilan bir xil xatti-harakat). Bucket'ning o'zi ommaga ochilishi shart emas.
- boto3 sinxron — har chaqiruv `asyncio.to_thread` da (lokal adapterdagi disk kabi), event loop to'xtamaydi.
- Kalit tekshiruvi lokal adapter bilan bir xil: `..`, boshidagi `/` va `\\` rad etiladi.
"""

from __future__ import annotations

import asyncio
from typing import Any

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

from app.platform.storage.config import PUBLIC_PURPOSE_SEGMENTS, S3Config

_PUBLIC_CACHE = "public, max-age=31536000, immutable"  # kalit o'zgarmaydi — fayl almashsa, yangi kalit
_PRIVATE_CACHE = "private, no-store"
_NOT_FOUND = frozenset({"NoSuchKey", "404", "NotFound"})


def _check_key(key: str) -> str:
    if not key or key.startswith("/") or "\\" in key or ".." in key.split("/"):
        raise ValueError("invalid storage key")
    return key


class S3FileStorage:
    def __init__(self, client: Any, private_bucket: str, public_bucket: str | None = None) -> None:
        self._client = client
        self.private_bucket = private_bucket
        self.public_bucket = public_bucket

    @classmethod
    def from_config(cls, config: S3Config) -> S3FileStorage:
        client = boto3.client(
            "s3",
            endpoint_url=config.endpoint_url or None,
            region_name=config.region,
            aws_access_key_id=config.access_key_id,
            aws_secret_access_key=config.secret_access_key,
            config=Config(
                signature_version="s3v4",
                connect_timeout=5,
                read_timeout=30,
                retries={"max_attempts": 3, "mode": "standard"},
                s3={"addressing_style": "path" if config.force_path_style else "auto"},
            ),
        )
        return cls(client, config.private_bucket, config.public_bucket)

    def is_public_key(self, key: str) -> bool:
        parts = key.split("/")
        return len(parts) >= 4 and parts[0] == "shops" and parts[2] in PUBLIC_PURPOSE_SEGMENTS

    def bucket_for(self, key: str) -> str:
        if self.public_bucket and self.is_public_key(key):
            return self.public_bucket
        return self.private_bucket

    async def put(self, key: str, data: bytes, content_type: str) -> None:
        _check_key(key)
        await asyncio.to_thread(
            self._client.put_object,
            Bucket=self.bucket_for(key),
            Key=key,
            Body=data,
            ContentType=content_type,
            CacheControl=_PUBLIC_CACHE if self.is_public_key(key) else _PRIVATE_CACHE,
        )

    async def get(self, key: str) -> bytes | None:
        try:
            _check_key(key)
        except ValueError:
            return None
        return await asyncio.to_thread(self._get_sync, self.bucket_for(key), key)

    async def delete(self, key: str) -> None:
        _check_key(key)
        # S3 DeleteObject yo'q kalitga ham muvaffaqiyat qaytaradi — port talabi bilan mos
        await asyncio.to_thread(self._client.delete_object, Bucket=self.bucket_for(key), Key=key)

    def _get_sync(self, bucket: str, key: str) -> bytes | None:
        try:
            response = self._client.get_object(Bucket=bucket, Key=key)
        except ClientError as exc:
            if str(exc.response.get("Error", {}).get("Code")) in _NOT_FOUND:
                return None
            raise
        body = response["Body"]
        try:
            data: bytes = body.read()
        finally:
            body.close()
        return data

    async def check(self) -> None:
        """Readiness tekshiruvi uchun: yopiq bucket mavjud va kalitlar to'g'ri."""
        await asyncio.to_thread(self._client.head_bucket, Bucket=self.private_bucket)
