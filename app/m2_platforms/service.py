"""M2 平台帳號與串接：查看平台帳號、以 Webhook 連結 Discord。

Threads 與 Instagram 的 OAuth 連結、重新連結、移除平台帳號尚未實作。
"""

from anyio import from_thread
from sqlalchemy.orm import Session

from app.core import audit, clock
from app.core.crypto import encrypt_credential
from app.core.enums import (
    AuditAction,
    Platform,
    PlatformAuthEventType,
    PlatformAuthFailureReason,
    TargetType,
)
from app.core.errors import DomainError
from app.core.models import PlatformAccount, UserAccount
from app.core.platforms import (
    VerificationUnavailable,
    WebhookInvalid,
    effective_auth_status,
    get_adapter,
)

from . import repository
from .adapters.discord import is_webhook_url
from .schemas import PlatformAccountOut

OAUTH_PLATFORMS = (Platform.THREADS, Platform.INSTAGRAM)


def to_out(account: PlatformAccount) -> PlatformAccountOut:
    return PlatformAccountOut(
        id=account.id,
        platform=account.platform,
        account_name=account.account_name,
        auth_status=effective_auth_status(account, clock.now()),
        auth_expires_at=account.auth_expires_at,
    )


def list_accounts(db: Session) -> list[PlatformAccountOut]:
    return [to_out(account) for account in repository.list_active(db)]


def _link_failed(
    db: Session, admin: UserAccount, account_name: str, reason: PlatformAuthFailureReason
) -> None:
    repository.add_auth_event(
        db,
        event_type=PlatformAuthEventType.LINK_FAILED,
        platform=Platform.DISCORD,
        account_name=account_name,
        failure_reason=reason,
        actor_id=admin.id,
    )
    db.commit()


def link_webhook_account(
    db: Session, admin: UserAccount, platform: str, account_name: str, webhook_url: str
) -> PlatformAccountOut:
    """連結 Discord 頻道：Webhook 經 Discord 驗證存在且可用後才建立（FR-06、BR-37）。"""
    if platform in OAUTH_PLATFORMS:
        raise DomainError(400, "PLATFORM_REQUIRES_OAUTH", "Threads 與 Instagram 需透過平台授權流程連結")
    name = account_name.strip()
    if platform != Platform.DISCORD or not name:
        raise DomainError(400, "VALIDATION_ERROR", "platform 必須是 discord，account_name 不可空白")
    # 網址格式在這裡就檢查，不依賴註冊的是哪一個 Adapter；不合格的網址不會送出任何請求
    if not is_webhook_url(webhook_url):
        _link_failed(db, admin, name, PlatformAuthFailureReason.WEBHOOK_INVALID)
        raise DomainError(422, "WEBHOOK_INVALID", "Webhook 網址無效，請確認後重新貼上")
    if repository.name_taken(db, Platform.DISCORD, name):
        raise DomainError(409, "PLATFORM_ACCOUNT_NAME_TAKEN", "已有相同名稱的 Discord 平台帳號")

    adapter = get_adapter(Platform.DISCORD)
    try:
        # 這個函式在執行緒中執行（同步端點），向平台驗證時回到事件迴圈送出請求
        webhook_info = from_thread.run(adapter.verify_webhook, webhook_url)
    except WebhookInvalid:
        _link_failed(db, admin, name, PlatformAuthFailureReason.WEBHOOK_INVALID)
        raise DomainError(422, "WEBHOOK_INVALID", "Webhook 網址無效，請確認後重新貼上") from None
    except VerificationUnavailable:
        _link_failed(db, admin, name, PlatformAuthFailureReason.VERIFICATION_UNAVAILABLE)
        raise DomainError(503, "VERIFICATION_UNAVAILABLE", "暫時無法向 Discord 驗證，請稍後再試") from None

    token, key_version = encrypt_credential(
        {"account_name": name, "webhook_url": webhook_url, **webhook_info}
    )
    account = repository.create(
        db,
        platform=Platform.DISCORD,
        account_name=name,
        credential_encrypted=token,
        credential_key_version=key_version,
        linked_by=admin.id,
    )
    audit.write(
        db,
        action=AuditAction.PLATFORM_LINK,
        actor=admin,
        target_type=TargetType.PLATFORM_ACCOUNT,
        target_id=account.id,
    )
    db.commit()
    return to_out(account)
