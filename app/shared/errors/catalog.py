"""Xato kodlari katalogi — yagona manba (11-api-conventions-errors-i18n §6.2, K-07).

Yangi kod: shu jadval + `base.py` dagi klass + `uz/ru/en` tarjimasi, bitta PR'da (TC-CONV-04).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ErrorSpec:
    status: int
    retryable: bool = False


ERROR_CATALOG: dict[str, ErrorSpec] = {
    "VALIDATION_FAILED": ErrorSpec(422),
    "INVALID_REQUEST": ErrorSpec(400),
    "UNAUTHENTICATED": ErrorSpec(401),
    "FORBIDDEN": ErrorSpec(403),
    "SELF_APPROVAL_NOT_ALLOWED": ErrorSpec(403),
    "NOT_FOUND": ErrorSpec(404),
    "METHOD_NOT_ALLOWED": ErrorSpec(405),
    "VERSION_CONFLICT": ErrorSpec(409),
    "IDEMPOTENCY_KEY_REUSED": ErrorSpec(409),
    "REQUEST_IN_PROGRESS": ErrorSpec(409, retryable=True),
    "INVALID_STATE_TRANSITION": ErrorSpec(409),
    "INSUFFICIENT_AVAILABLE_STOCK": ErrorSpec(409),
    "PRICE_CHANGED": ErrorSpec(409),
    "QUOTE_EXPIRED": ErrorSpec(409),
    "APPROVAL_REQUIRED": ErrorSpec(409),
    "EXCHANGE_RATE_STALE": ErrorSpec(409),
    "PRODUCT_NOT_AVAILABLE": ErrorSpec(409),
    "BRANCH_CLOSED": ErrorSpec(409),
    "SHOP_NOT_ACTIVE": ErrorSpec(409),
    "LAST_OWNER_REQUIRED": ErrorSpec(409),
    "LAST_ADMIN_REQUIRED": ErrorSpec(409),
    "FILE_IN_USE": ErrorSpec(409),
    "SHOP_HAS_OPEN_ORDERS": ErrorSpec(409),
    "SPEAKER_CONFLICT": ErrorSpec(409),
    "CHANNEL_UNAVAILABLE": ErrorSpec(409),
    "PAYLOAD_TOO_LARGE": ErrorSpec(413),
    "UNSUPPORTED_MEDIA_TYPE": ErrorSpec(415),
    "RULE_BLOCK": ErrorSpec(422),
    "DISCOUNT_LIMIT_EXCEEDED": ErrorSpec(422),
    "IMPORT_FILE_INVALID": ErrorSpec(422),
    "RATE_LIMITED": ErrorSpec(429, retryable=True),
    "AI_QUOTA_EXCEEDED": ErrorSpec(429),
    "INTERNAL_ERROR": ErrorSpec(500, retryable=True),
    "FEATURE_NOT_AVAILABLE": ErrorSpec(501),
    "PROVIDER_UNAVAILABLE": ErrorSpec(503, retryable=True),
    "SERVICE_UNAVAILABLE": ErrorSpec(503, retryable=True),
}

# Faqat framework (Starlette) chiqaradigan kodlar — ularga DomainError klassi shart emas.
FRAMEWORK_ONLY_CODES = frozenset({"METHOD_NOT_ALLOWED"})


def status_for(code: str) -> int:
    spec = ERROR_CATALOG.get(code)
    return spec.status if spec else 500
