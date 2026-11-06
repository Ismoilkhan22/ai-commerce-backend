"""Fayl ombori sozlamasi (S0-10, TD-03): qaysi adapter va uning parametrlari.

`Settings.storage_config()` yaratadi, `build_file_storage()` adapterni tanlaydi. Havolalar (ochiq manzil va
imzoli havola) adapterga bog'liq emas — ular `FileService` da (`public_files_url`, `UrlSigner`).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from app.platform.storage.ports import FileStorage

# Ochiq fayllar (PURPOSES dagi public=True): kalit `shops/{shop_id}/{purpose}/...` — purpose kichik harfda
PUBLIC_PURPOSE_SEGMENTS = frozenset({"product_image", "site_logo"})


@dataclass(frozen=True)
class S3Config:
    private_bucket: str
    # Bo'lmasa — hamma fayl bitta (yopiq) bucket'da; ochiq fayl baribir API orqali beriladi
    public_bucket: str | None = None
    endpoint_url: str | None = None  # S3-mos xizmat manzili; AWS'da bo'sh
    region: str = "us-east-1"
    access_key_id: str | None = None
    secret_access_key: str | None = None
    force_path_style: bool = True  # ko'p S3-mos xizmatlar (MinIO, Ceph) `endpoint/bucket/key` kutadi


@dataclass(frozen=True)
class StorageConfig:
    backend: Literal["local", "s3"]
    local_dir: Path
    s3: S3Config | None = None


def build_file_storage(config: StorageConfig) -> FileStorage:
    if config.backend == "s3":
        if config.s3 is None:
            raise ValueError("storage backend s3: S3 sozlamasi yo'q")
        from app.platform.storage.s3 import S3FileStorage  # boto3 faqat kerak bo'lganda yuklanadi

        return S3FileStorage.from_config(config.s3)
    from app.platform.storage.local import LocalDiskStorage

    return LocalDiskStorage(config.local_dir)
