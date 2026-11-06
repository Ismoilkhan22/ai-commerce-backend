"""Domen xatolari ierarxiyasi (11 §7.1). Service va domen qatlamlari HTTP'ni bilmaydi."""

from __future__ import annotations

from typing import ClassVar


class DomainError(Exception):
    code: ClassVar[str] = "INTERNAL_ERROR"
    # Abstrakt klasslar to'g'ridan-to'g'ri tashlanmaydi va katalogda bo'lishi shart emas.
    abstract: ClassVar[bool] = False

    def __init__(self, message: str = "", **details: object) -> None:
        super().__init__(message or self.code)
        self.message = message or self.code
        self.details: dict[str, object] = details


class ValidationError(DomainError):
    code = "VALIDATION_FAILED"


class InvalidRequestError(DomainError):
    code = "INVALID_REQUEST"


class UnauthenticatedError(DomainError):
    code = "UNAUTHENTICATED"


class NotFoundError(DomainError):
    code = "NOT_FOUND"


class ForbiddenError(DomainError):
    code = "FORBIDDEN"


class SelfApprovalError(ForbiddenError):
    code = "SELF_APPROVAL_NOT_ALLOWED"


class ConflictError(DomainError):
    code = "CONFLICT"
    abstract = True


class VersionConflictError(ConflictError):
    code = "VERSION_CONFLICT"
    abstract = False


class IdempotencyKeyReusedError(ConflictError):
    code = "IDEMPOTENCY_KEY_REUSED"
    abstract = False


class RequestInProgressError(ConflictError):
    """Shu Idempotency-Key bilan birinchi so'rov hali bajarilmoqda — klient biroz kutib qayta yuboradi."""

    code = "REQUEST_IN_PROGRESS"
    abstract = False


class InvalidTransitionError(ConflictError):
    code = "INVALID_STATE_TRANSITION"
    abstract = False


class InsufficientStockError(ConflictError):
    code = "INSUFFICIENT_AVAILABLE_STOCK"
    abstract = False


class PriceChangedError(ConflictError):
    code = "PRICE_CHANGED"
    abstract = False


class QuoteExpiredError(ConflictError):
    code = "QUOTE_EXPIRED"
    abstract = False


class QuoteChangedError(ConflictError):
    """Qabulda narx yoki moslik o'zgargan: xodim yangi versiya yuboradi, xaridor qayta rozilik beradi."""

    code = "QUOTE_CHANGED"
    abstract = False


class ApprovalRequiredError(ConflictError):
    code = "APPROVAL_REQUIRED"
    abstract = False


class ExchangeRateStaleError(ConflictError):
    code = "EXCHANGE_RATE_STALE"
    abstract = False


class ProductNotAvailableError(ConflictError):
    code = "PRODUCT_NOT_AVAILABLE"
    abstract = False


class BranchClosedError(ConflictError):
    code = "BRANCH_CLOSED"
    abstract = False


class ShopNotActiveError(ConflictError):
    code = "SHOP_NOT_ACTIVE"
    abstract = False


class LastOwnerRequiredError(ConflictError):
    code = "LAST_OWNER_REQUIRED"
    abstract = False


class LastAdminRequiredError(ConflictError):
    """Platformada kamida bitta faol PLATFORM_ADMIN qolishi shart (business/15 §5)."""

    code = "LAST_ADMIN_REQUIRED"
    abstract = False


class FileInUseError(ConflictError):
    """Fayl allaqachon boshqa mahsulot rasmi: bitta fayl — bitta joy (birida o'chsa, boshqasi buzilmasin)."""

    code = "FILE_IN_USE"
    abstract = False


class OrderLinkedElsewhereError(ConflictError):
    """Buyurtma boshqa suhbatga bog'langan: jim ko'chirilmaydi — holat xabari boshqa xaridorga ketmasin
    (QA 5b M3). Qayta bog'lash — aniq `relink: true` va buyurtma versiyasi bilan."""

    code = "ORDER_LINKED_ELSEWHERE"
    abstract = False


class ShopHasOpenOrdersError(ConflictError):
    """Shopni yopib bo'lmaydi: ochiq buyurtmalar bor — avval yakunlanadi yoki bekor qilinadi (TC-023)."""

    code = "SHOP_HAS_OPEN_ORDERS"
    abstract = False


class SiteNotAvailableError(ConflictError):
    """Shop sayti xaridorga hozir ochiq emas: `details.state` — COMING_SOON yoki PAUSED (storefront.md §0)."""

    code = "SITE_NOT_AVAILABLE"
    abstract = False


class ImportAlreadyRunningError(ConflictError):
    """Shopda bitta faol import: sinov, yozish yoki qoldiq bosqichidagisi tugamaguncha yangisi boshlanmaydi
    (18 §3, 4-qoida)."""

    code = "IMPORT_ALREADY_RUNNING"
    abstract = False


class ImportBusyError(ConflictError):
    """Import fon bosqichi aynan shu daqiqada yozuvni yangilayapti (QA F5): qulf kutilmaydi, darhol 409 —
    bir zumdan keyin qayta urinish mumkin."""

    code = "IMPORT_BUSY"
    abstract = False


class SpeakerConflictError(ConflictError):
    code = "SPEAKER_CONFLICT"
    abstract = False


class ChannelUnavailableError(ConflictError):
    code = "CHANNEL_UNAVAILABLE"
    abstract = False


class PayloadTooLargeError(DomainError):
    code = "PAYLOAD_TOO_LARGE"


class UnsupportedMediaTypeError(DomainError):
    code = "UNSUPPORTED_MEDIA_TYPE"


class BusinessRuleError(DomainError):
    code = "RULE_BLOCK"


class DiscountLimitExceededError(BusinessRuleError):
    code = "DISCOUNT_LIMIT_EXCEEDED"


class WarrantyExpiredError(BusinessRuleError):
    """Kafolat muddati tugagan sotuvga murojaat ochilmaydi; menejer/ega sabab bilan ochadi (DEC-145)."""

    code = "WARRANTY_EXPIRED"


class ImportFileInvalidError(BusinessRuleError):
    code = "IMPORT_FILE_INVALID"


class ShopNotVerifiedError(BusinessRuleError):
    code = "SHOP_NOT_VERIFIED"  # Stage 2: ommaviy taklif faqat tekshirilgan (ACTIVE) shopdan


class RateLimitedError(DomainError):
    code = "RATE_LIMITED"


class AIQuotaExceededError(RateLimitedError):
    code = "AI_QUOTA_EXCEEDED"


class FeatureNotAvailableError(DomainError):
    code = "FEATURE_NOT_AVAILABLE"


class ProviderUnavailableError(DomainError):
    code = "PROVIDER_UNAVAILABLE"


class ServiceUnavailableError(DomainError):
    code = "SERVICE_UNAVAILABLE"
