"""Fayl yuklash, havola berish va ochiq manzildan berish (S0-08, catalog.md §12).

Tartib: hajm va tur (fayl ichidan) → sha256 → omborga yozish → yozuv + audit (bitta tranzaksiyada).
Tranzaksiya bekor bo'lsa omborda yetim fayl qolishi mumkin — keyin tozalash fon ishi o'chiradi (S0-06).
"""

from __future__ import annotations

import hashlib
import re
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.platform.audit.services.audit_service import AuditService
from app.platform.storage.models.orm import StoredFile
from app.platform.storage.ports import FileStorage
from app.platform.storage.schemas import StoredFileOut
from app.platform.storage.signing import UrlSigner
from app.platform.storage.sniff import EXTENSIONS, IMAGE_TYPES, sniff_mime
from app.shared.clock import utcnow
from app.shared.db.ids import uuid7
from app.shared.errors.base import (
    ForbiddenError,
    NotFoundError,
    PayloadTooLargeError,
    UnsupportedMediaTypeError,
    ValidationError,
)
from app.shared.text import strip_invisible
from app.shared.types.actor import ActorContext

ENTITY = "platform.stored_file"
MAX_IMAGE_BYTES = 5 * 1024 * 1024
MAX_LOGO_BYTES = 2 * 1024 * 1024  # storefront.md §8
MAX_IMPORT_BYTES = 10 * 1024 * 1024  # 18 §4
XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
DOCUMENT_TYPES = frozenset({XLSX_MIME, "text/csv"})
_DOCUMENT_EXTENSIONS = {XLSX_MIME: ".xlsx", "text/csv": ".csv"}


def _document_mime(data: bytes) -> str | None:
    """Jadval fayli: ZIP (XLSX), BOM'li UTF-16 matn yoki NUL'siz matn (UTF-8 yoki Windows-1251) — CSV."""
    if data[:4] == b"PK\x03\x04":
        return XLSX_MIME
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):  # UTF-16 BOM — Excel "Unicode text" (5c QA F17)
        try:
            data[: 65536 - 65536 % 2].decode("utf-16", errors="strict")
        except UnicodeDecodeError:
            return None
        return "text/csv"
    if b"\x00" in data[:65536]:
        return None
    sample = data[:65536]
    for encoding in ("utf-8", "cp1251"):
        try:
            sample.decode(encoding)
            return "text/csv"
        except UnicodeDecodeError:
            continue
    return None


# Boshqaruv belgilari; ko'rinmas va yo'nalish almashtiruvchi belgilar — `strip_invisible` (shared/text.py):
# "rasm\u202egnp.exe" ekranda "rasmexe.png" bo'lib ko'rinmasin
_NAME_UNSAFE = re.compile(r"[\x00-\x1f\x7f]")


@dataclass(frozen=True)
class PurposeRule:
    permission: str  # yuklash uchun kerakli ruxsat (shu fayl qaysi amal uchun)
    public: bool
    max_bytes: int
    mime_types: frozenset[str]


# Mahsulot rasmi va sayt logotipi ochiq (DEC-133, storefront.md §1); qolganlari yopiq. Import/eksport
# fayllari o'z modullarida yaratiladi. SVG logotip qabul qilinmaydi: tozalovchisiz u skript tashiy oladi.
PURPOSES: dict[str, PurposeRule] = {
    "PRODUCT_IMAGE": PurposeRule("catalog.product.edit", True, MAX_IMAGE_BYTES, IMAGE_TYPES),
    "STOCK_EVIDENCE": PurposeRule("commerce.stock.adjust_request", False, MAX_IMAGE_BYTES, IMAGE_TYPES),
    "SITE_LOGO": PurposeRule("storefront.site.edit", True, MAX_LOGO_BYTES, IMAGE_TYPES),
    # Suhbat rasmi (5b): operator biriktiradi; xaridor yuborgani worker orqali (`store_system`)
    "CHAT_ATTACHMENT": PurposeRule("messaging.conversation.reply", False, MAX_IMAGE_BYTES, IMAGE_TYPES),
    # Katalog importi (5c): XLSX yoki CSV, 10 MB (18 §4). Jadval ekanini import moduli to'liq tekshiradi
    "IMPORT_FILE": PurposeRule("catalog.import.run", False, MAX_IMPORT_BYTES, DOCUMENT_TYPES),
}


def purpose_rule(purpose: str) -> PurposeRule:
    rule = PURPOSES.get(purpose)
    if rule is None:
        raise ValidationError(
            "Unknown purpose", fields=[{"field": "purpose", "code": "invalid_choice", "params": {}}]
        )
    return rule


def shop_id_from_key(object_key: str) -> UUID | None:
    """`shops/{shop_id}/...` — ochiq manzildan shop kontekstini olish uchun (RLS)."""
    parts = object_key.split("/")
    if len(parts) < 4 or parts[0] != "shops":
        return None
    try:
        return UUID(parts[1])
    except ValueError:
        return None


def _clean_name(name: str | None) -> str | None:
    if not name:
        return None
    base = str(strip_invisible(_NAME_UNSAFE.sub("", name.replace("\\", "/").rsplit("/", 1)[-1]))).strip()
    return base[:200] or None


@dataclass(frozen=True)
class ServedFile:
    data: bytes
    mime_type: str
    is_public: bool


class FileService:
    def __init__(
        self,
        storage: FileStorage,
        signer: UrlSigner,
        audit: AuditService,
        public_base_url: str,
        signed_ttl: timedelta,
    ) -> None:
        self.storage = storage
        self.signer = signer
        self.audit = audit
        self.public_base_url = public_base_url.rstrip("/")
        self.signed_ttl = signed_ttl

    # ------------------------------------------------------------------ yuklash
    async def upload(
        self, db: AsyncSession, actor: ActorContext, purpose: str, data: bytes, original_name: str | None
    ) -> StoredFileOut:
        rule = purpose_rule(purpose)
        if rule.permission not in actor.permissions:
            raise ForbiddenError("Permission denied", permission=rule.permission)
        assert actor.shop_id is not None
        row = await self._store(db, actor.shop_id, purpose, rule, data, original_name, actor.membership_id)
        await self.audit.record(
            db, action="storage.file.uploaded", entity_type=ENTITY, entity_id=row.id, actor=actor
        )
        return self.to_out(row)

    async def store_system(
        self, db: AsyncSession, shop_id: UUID, purpose: str, data: bytes, original_name: str | None
    ) -> StoredFile:
        """Tizim yuklashi (xaridor Telegram'da yuborgan rasm, 5b): ruxsat tekshiruvi yo'q, qolgani — hajm,
        tur (fayl ichidan) va tasodifiy kalit — `upload` bilan bir xil. Audit yozilmaydi: xodim amali emas."""
        return await self._store(db, shop_id, purpose, purpose_rule(purpose), data, original_name, None)

    async def store_document(
        self,
        db: AsyncSession,
        shop_id: UUID,
        purpose: str,
        data: bytes,
        *,
        mime_type: str,
        extension: str,
        original_name: str | None,
        uploaded_by: UUID | None,
    ) -> StoredFile:
        """Import fayli va hisobot (IMPORT_FILE, EXPORT_FILE — 5c): doim yopiq. Turi va hajmi chaqiruvchi
        modulda tekshiriladi (jadval fayli rasm emas); yo'lda nom yo'q, tasodifiy qism bor."""
        if purpose not in ("IMPORT_FILE", "EXPORT_FILE"):
            raise ValueError(f"store_document: {purpose}")
        file_id = uuid7()
        key = f"shops/{shop_id}/{purpose.lower()}/{file_id}-{secrets.token_urlsafe(9)}{extension}"
        await self.storage.put(key, data, mime_type)
        row = StoredFile(
            id=file_id,
            shop_id=shop_id,
            purpose=purpose,
            object_key=key,
            is_public=False,
            mime_type=mime_type,
            size_bytes=len(data),
            sha256=hashlib.sha256(data).hexdigest(),
            original_name=_clean_name(original_name),
            uploaded_by=uploaded_by,
        )
        db.add(row)
        await db.flush()
        await db.refresh(row)
        return row

    async def _store(
        self,
        db: AsyncSession,
        shop_id: UUID,
        purpose: str,
        rule: PurposeRule,
        data: bytes,
        original_name: str | None,
        uploaded_by: UUID | None,
    ) -> StoredFile:
        if not data:
            raise ValidationError("Empty file", fields=[{"field": "file", "code": "required", "params": {}}])
        if len(data) > rule.max_bytes:
            raise PayloadTooLargeError("File too large", max_bytes=rule.max_bytes)
        mime = _document_mime(data) if rule.mime_types == DOCUMENT_TYPES else sniff_mime(data)
        if mime is None or mime not in rule.mime_types:
            raise UnsupportedMediaTypeError("File type not allowed", allowed=sorted(rule.mime_types))
        file_id = uuid7()
        # Yo'lda fayl nomi yo'q va tasodifiy qism bor — manzilni taxmin qilib bo'lmaydi
        extension = EXTENSIONS.get(mime) or _DOCUMENT_EXTENSIONS[mime]
        key = f"shops/{shop_id}/{purpose.lower()}/{file_id}-{secrets.token_urlsafe(9)}{extension}"
        await self.storage.put(key, data, mime)
        row = StoredFile(
            id=file_id,
            shop_id=shop_id,
            purpose=purpose,
            object_key=key,
            is_public=rule.public,
            mime_type=mime,
            size_bytes=len(data),
            sha256=hashlib.sha256(data).hexdigest(),
            original_name=_clean_name(original_name),
            uploaded_by=uploaded_by,
        )
        db.add(row)
        await db.flush()
        await db.refresh(row)
        return row

    async def read_bytes(self, row: StoredFile) -> bytes | None:
        """Fayl baytlari (suhbatga biriktirilgan rasmni kanalga yuborish uchun, 5b)."""
        return await self.storage.get(row.object_key)

    # ------------------------------------------------------------------ o'qish
    async def get(self, db: AsyncSession, actor: ActorContext, file_id: UUID) -> StoredFileOut:
        row = await self._shop_file(db, actor.shop_id, file_id)
        if row is None or row.status != "ACTIVE":
            raise NotFoundError("File not found")
        rule = PURPOSES.get(row.purpose)
        if not row.is_public and (rule is None or rule.permission not in actor.permissions):
            raise NotFoundError("File not found")  # yopiq faylni faqat shu amal ruxsati borlar ko'radi
        return self.to_out(row)

    async def usable(self, db: AsyncSession, shop_id: UUID, file_id: UUID, purpose: str) -> StoredFile:
        """Boshqa modul faylni o'z obyektiga ulashdan oldin: shu shopniki, faol va to'g'ri turdagi
        (TC-ISO-05 — birovning fayl ID'sini taxmin qilib ulab bo'lmaydi)."""
        row = await self._shop_file(db, shop_id, file_id)
        if row is None or row.status != "ACTIVE" or row.purpose != purpose:
            raise ValidationError(
                "File not usable", fields=[{"field": "file_id", "code": "invalid", "params": {}}]
            )
        return row

    async def by_ids(self, db: AsyncSession, shop_id: UUID, file_ids: list[UUID]) -> dict[UUID, StoredFile]:
        """Faqat faol fayllar — o'chirilgan faylga havola (404 beradigan) ko'rsatilmaydi."""
        if not file_ids:
            return {}
        rows = await db.execute(
            select(StoredFile).where(
                StoredFile.shop_id == shop_id, StoredFile.id.in_(file_ids), StoredFile.status == "ACTIVE"
            )
        )
        return {row.id: row for row in rows.scalars()}

    async def mark_deleted(self, db: AsyncSession, shop_id: UUID, file_id: UUID) -> None:
        """Yozuv DELETED bo'ladi; baytlar keyin fon ishida o'chiriladi (havola keshda qolishi mumkin)."""
        row = await self._shop_file(db, shop_id, file_id)
        if row is not None and row.status == "ACTIVE":
            row.status = "DELETED"
            await db.flush()

    # ------------------------------------------------------------------ havolalar
    def url_for(self, row: StoredFile, now: datetime | None = None) -> tuple[str, datetime | None]:
        base = f"{self.public_base_url}/{row.object_key}"
        if row.is_public:
            return base, None
        expires_at = (now or utcnow()) + self.signed_ttl
        exp = int(expires_at.timestamp())
        return f"{base}?exp={exp}&sig={self.signer.sign(row.object_key, exp)}", expires_at

    def to_out(self, row: StoredFile) -> StoredFileOut:
        url, expires_at = self.url_for(row)
        return StoredFileOut(
            id=row.id,
            purpose=row.purpose,
            mime_type=row.mime_type,
            size_bytes=row.size_bytes,
            sha256=row.sha256,
            original_name=row.original_name,
            is_public=row.is_public,
            url=url,
            url_expires_at=expires_at,
            created_at=row.created_at,
        )

    async def serve(
        self, db: AsyncSession, object_key: str, exp: int | None, sig: str | None
    ) -> ServedFile | None:
        """Ochiq fayl — har kimga; yopiq — faqat amal qilayotgan imzo bilan. Aks holda None (404)."""
        row = (
            await db.execute(select(StoredFile).where(StoredFile.object_key == object_key))
        ).scalar_one_or_none()
        if row is None or row.status != "ACTIVE":
            return None
        if not row.is_public:
            now = int(utcnow().timestamp())
            if exp is None or sig is None or not self.signer.verify(object_key, exp, sig, now):
                return None
        data = await self.storage.get(object_key)
        if data is None:
            return None
        return ServedFile(data=data, mime_type=row.mime_type, is_public=row.is_public)

    async def _shop_file(self, db: AsyncSession, shop_id: UUID | None, file_id: UUID) -> StoredFile | None:
        if shop_id is None:
            return None
        return (
            await db.execute(
                select(StoredFile).where(StoredFile.id == file_id, StoredFile.shop_id == shop_id)
            )
        ).scalar_one_or_none()
