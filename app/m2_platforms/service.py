"""M2 平台帳號與串接：查看、以 Webhook 連結與重新連結 Discord、以平台授權（OAuth）連結 Threads、
移除平台帳號。

Instagram 的串接、Threads 與 Instagram 的重新連結尚未實作。
"""

import logging

from anyio import from_thread
from sqlalchemy.orm import Session

from app.core import audit, clock
from app.core import auth as core_auth
from app.core.config import get_settings
from app.core.crypto import encrypt_credential
from app.core.enums import (
    AuditAction,
    AuthStatus,
    Platform,
    PlatformAuthEventType,
    PlatformAuthFailureReason,
    Role,
    TargetType,
    UserStatus,
)
from app.core.errors import DomainError, not_found
from app.core.models import PlatformAccount, UserAccount
from app.core.platforms import (
    OAuthAccount,
    OAuthFailed,
    VerificationUnavailable,
    WebhookInvalid,
    effective_auth_status,
    get_adapter,
)
from app.m4_scheduling import lifecycle

from . import oauth_state, repository
from .adapters.discord import is_webhook_url
from .schemas import PlatformAccountOut

logger = logging.getLogger("mediagent.platforms")

OAUTH_PLATFORMS = (Platform.THREADS, Platform.INSTAGRAM)
# 目前已經可以用授權流程連結的平台；Instagram 的串接完成後再加入
OAUTH_ENABLED_PLATFORMS = (Platform.THREADS,)
OAUTH_CALLBACK_PATH = "/api/v1/platform-accounts/oauth/callback"

# 授權流程結束後的結果代碼（《API 設計》3.2）
RESULT_LINKED = "linked"
RESULT_AUTH_FAILED = "PLATFORM_AUTH_FAILED"
RESULT_UNAVAILABLE = "VERIFICATION_UNAVAILABLE"
RESULT_NAME_TAKEN = "PLATFORM_ACCOUNT_NAME_TAKEN"

MAX_LOGGED_REASON_LENGTH = 300


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
    db: Session,
    admin: UserAccount,
    account_name: str | None,
    reason: PlatformAuthFailureReason,
    platform: str = Platform.DISCORD,
) -> None:
    """記錄一筆「連結平台帳號失敗」的平台授權事件。不得包含任何憑證或授權碼。"""
    repository.add_auth_event(
        db,
        event_type=PlatformAuthEventType.LINK_FAILED,
        platform=platform,
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


def relink_webhook(db: Session, admin: UserAccount, account_id: int, webhook_url: str) -> PlatformAccountOut:
    """Discord 重新連結：換成新的 Webhook（FR-21、BR-37）。驗證失敗時保留原有資料並記錄平台授權事件。"""
    account = repository.get_active(db, account_id)
    if account is None:
        raise not_found("找不到平台帳號")
    if account.platform != Platform.DISCORD:
        raise DomainError(400, "PLATFORM_REQUIRES_OAUTH", "Threads 與 Instagram 需透過平台授權流程重新連結")

    def relink_failed(reason: PlatformAuthFailureReason) -> None:
        repository.add_auth_event(
            db,
            event_type=PlatformAuthEventType.RELINK_FAILED,
            platform=account.platform,
            account_name=account.account_name,
            failure_reason=reason,
            actor_id=admin.id,
            platform_account_id=account.id,
        )
        db.commit()

    if not is_webhook_url(webhook_url):
        relink_failed(PlatformAuthFailureReason.WEBHOOK_INVALID)
        raise DomainError(422, "WEBHOOK_INVALID", "Webhook 網址無效，請確認後重新貼上")
    try:
        webhook_info = from_thread.run(get_adapter(Platform.DISCORD).verify_webhook, webhook_url)
    except WebhookInvalid:
        relink_failed(PlatformAuthFailureReason.WEBHOOK_INVALID)
        raise DomainError(422, "WEBHOOK_INVALID", "Webhook 網址無效，請確認後重新貼上") from None
    except VerificationUnavailable:
        relink_failed(PlatformAuthFailureReason.VERIFICATION_UNAVAILABLE)
        raise DomainError(503, "VERIFICATION_UNAVAILABLE", "暫時無法向 Discord 驗證，請稍後再試") from None

    account = repository.get_active(db, account_id, for_update=True)
    if account is None:  # 驗證期間被移除
        raise not_found("找不到平台帳號")
    token, key_version = encrypt_credential(
        {"account_name": account.account_name, "webhook_url": webhook_url, **webhook_info}
    )
    account.credential_encrypted = token
    account.credential_key_version = key_version
    account.auth_status = AuthStatus.VALID
    # 連結者維持原本的人；這次重新連結的管理員記在稽核紀錄
    audit.write(
        db,
        action=AuditAction.PLATFORM_RELINK,
        actor=admin,
        target_type=TargetType.PLATFORM_ACCOUNT,
        target_id=account.id,
    )
    db.commit()
    return to_out(account)


def remove_account(db: Session, admin: UserAccount, account_id: int) -> None:
    """移除平台帳號（FR-08、BR-23）：標記為已移除、資料與發佈紀錄保留，並處理受影響的貼文。"""
    account = repository.get_active(db, account_id, for_update=True)
    if account is None:
        raise not_found("找不到平台帳號")
    account.removed = True
    account.removed_at = clock.now()
    lifecycle.on_platform_account_removed(db, account.id, admin)
    audit.write(
        db,
        action=AuditAction.PLATFORM_REMOVE,
        actor=admin,
        target_type=TargetType.PLATFORM_ACCOUNT,
        target_id=account.id,
    )
    db.commit()


# ---------- 平台授權（OAuth）連結：Threads ----------


def oauth_redirect_uri() -> str:
    return get_settings().oauth_redirect_base_url.rstrip("/") + OAUTH_CALLBACK_PATH


def start_oauth(
    db: Session, admin: UserAccount, platform: str, platform_account_id: int | None
) -> str:
    """產生平台的授權網址；前端把瀏覽器導向它，使用者在平台上同意後會被導回 callback。"""
    if platform_account_id is not None:
        raise DomainError(400, "VALIDATION_ERROR", "重新連結平台帳號尚未實作")
    if platform not in OAUTH_ENABLED_PLATFORMS:
        raise DomainError(400, "VALIDATION_ERROR", "目前只有 Threads 可以用平台授權流程連結")

    adapter = get_adapter(platform)
    state = oauth_state.issue_state(admin.id, platform)
    try:
        return adapter.authorization_url(state, oauth_redirect_uri())
    except OAuthFailed:
        raise DomainError(
            503, "VERIFICATION_UNAVAILABLE", "尚未設定這個平台的 App ID 與密鑰，請先完成設定"
        ) from None


def complete_oauth(db: Session, *, code: str | None, state: str | None, error: str | None) -> str:
    """平台把瀏覽器導回來之後完成連結，回傳結果代碼。

    這個請求沒有登入標頭，身分只能由簽章的 state 確認。
    向平台換取憑證的呼叫在碰資料庫之前完成，不會讓資料庫交易開著等平台回應。
    """
    try:
        issued = oauth_state.read_state(state or "")
    except OAuthFailed:
        return RESULT_AUTH_FAILED  # 無法確認是誰發起的，不記錄事件，也不呼叫平台

    # 失敗原因要留在 Log 供排查（第一次串接最常見的就是設定錯誤）；授權碼與 state 不可寫入
    account: OAuthAccount | None = None
    failure = PlatformAuthFailureReason.PLATFORM_AUTH_FAILED
    if error or not code:
        logger.warning(
            "oauth authorization for %s was not granted: %r",
            issued.platform,
            (error or "no authorization code")[:MAX_LOGGED_REASON_LENGTH],
        )
    else:
        try:
            adapter = get_adapter(issued.platform)
            account = from_thread.run(adapter.exchange_code, code, oauth_redirect_uri())
        except OAuthFailed as exc:
            reason = str(exc).replace(code, "[redacted]")[:MAX_LOGGED_REASON_LENGTH]
            logger.warning("oauth code exchange for %s was rejected: %s", issued.platform, reason)
        except VerificationUnavailable:
            logger.warning("oauth code exchange for %s could not reach the platform", issued.platform)
            failure = PlatformAuthFailureReason.VERIFICATION_UNAVAILABLE

    admin = db.get(UserAccount, issued.admin_id)
    if (
        admin is None
        or admin.status != UserStatus.ACTIVE
        or not core_auth.has_role(admin.role, Role.ADMIN)
    ):
        return RESULT_AUTH_FAILED
    if account is None:
        # 使用者拒絕授權、授權碼換不到憑證，或暫時連不上平台（BR-37）
        _link_failed(db, admin, None, failure, issued.platform)
        if failure == PlatformAuthFailureReason.VERIFICATION_UNAVAILABLE:
            return RESULT_UNAVAILABLE
        return RESULT_AUTH_FAILED
    if repository.name_taken(db, issued.platform, account.account_name):
        return RESULT_NAME_TAKEN  # 資料衝突，不記錄為平台授權事件（需求 4.5.2）

    token, key_version = encrypt_credential(
        {"account_name": account.account_name, **account.credential}
    )
    created = repository.create(
        db,
        platform=issued.platform,
        account_name=account.account_name,
        credential_encrypted=token,
        credential_key_version=key_version,
        linked_by=admin.id,
        platform_user_id=account.platform_user_id,
        auth_expires_at=account.expires_at,
    )
    audit.write(
        db,
        action=AuditAction.PLATFORM_LINK,
        actor=admin,
        target_type=TargetType.PLATFORM_ACCOUNT,
        target_id=created.id,
    )
    db.commit()
    return RESULT_LINKED


def oauth_result_url(result: str) -> str:
    """授權流程結束後要把瀏覽器導去哪裡：有前端就導回前端，否則用後端內建的結果頁。"""
    frontend = get_settings().frontend_origin.rstrip("/")
    if frontend:
        return f"{frontend}/platform-accounts?result={result}"
    return f"/api/v1/platform-accounts/oauth/result?result={result}"
