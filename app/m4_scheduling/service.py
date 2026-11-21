"""M4 目標與排程：設定目標平台帳號、查看發佈結果。

設定排程、取消排程、已排程貼文修改目標時同步發佈紀錄、變更歷程查詢尚未實作。
"""

from sqlalchemy.orm import Session

from app.core import auth, clock
from app.core.enums import AuthStatus, PostStatus, Role
from app.core.errors import DomainError, not_found
from app.core.models import PlatformAccount, UserAccount
from app.core.platforms import effective_auth_status

from . import repository
from .schemas import PublishRecordOut, PublishRecordsOut, RecordAccount, TargetOut, TargetsOut

EDITABLE_STATUSES = (PostStatus.DRAFT, PostStatus.SCHEDULED)


def _target_out(account: PlatformAccount) -> TargetOut:
    return TargetOut(
        id=account.id,
        platform=account.platform,
        account_name=account.account_name,
        auth_status=effective_auth_status(account, clock.now()),
    )


def set_targets(db: Session, user: UserAccount, post_id: int, account_ids: list[int]) -> TargetsOut:
    """以整組取代貼文的目標平台帳號（FR-10、BR-08）。"""
    if len(set(account_ids)) != len(account_ids):
        raise DomainError(400, "TARGET_DUPLICATE", "同一個平台帳號不可重複選擇")

    post = repository.get_post_for_update(db, post_id)
    if post is None:
        raise not_found("找不到貼文")
    auth.ensure_owner_or_role(user, post.creator_id, Role.PUBLISHER)
    if post.status not in EDITABLE_STATUSES:
        raise DomainError(409, "POST_NOT_EDITABLE", "只有草稿與已排程的貼文可以修改")

    accounts = repository.get_accounts(db, account_ids)
    usable = {account.id for account in accounts if not account.removed}
    missing = [aid for aid in account_ids if aid not in usable]
    if missing:
        raise DomainError(
            422, "TARGET_NOT_AVAILABLE", "平台帳號不存在或已被移除", {"account_ids": missing}
        )
    now = clock.now()
    invalid = [a.account_name for a in accounts if effective_auth_status(a, now) == AuthStatus.INVALID]
    if invalid:
        raise DomainError(
            422, "TARGET_AUTH_INVALID", "平台帳號的授權已失效，請管理員重新連結", {"accounts": invalid}
        )

    repository.replace_targets(db, post.id, account_ids)
    db.commit()
    return TargetsOut(post_id=post.id, targets=[_target_out(account) for account in accounts])


def get_publish_records(db: Session, user: UserAccount, post_id: int) -> PublishRecordsOut:
    """查看發佈結果；貼文刪除後仍可用原 ID 查詢（BR-35）。"""
    post = repository.get_post_including_deleted(db, post_id)
    if post is None:
        raise not_found("找不到貼文")
    deleted = post.deleted_at is not None
    is_admin = auth.has_role(user.role, Role.ADMIN)

    items = []
    for record in repository.list_records(db, post_id):
        account = record.platform_account
        item = PublishRecordOut(
            id=record.id,
            platform_account=RecordAccount(
                id=account.id,
                platform=account.platform,
                account_name=account.account_name,
                removed=account.removed,
            ),
            status=record.status,
            published_at=record.published_at,
            platform_post_url=record.platform_post_url,
            failure_reason=record.failure_reason,
        )
        if is_admin:
            item.platform_error_message = record.platform_error_message
        items.append(item)
    return PublishRecordsOut(
        post_id=post.id,
        post_deleted=deleted,
        post_status=None if deleted else post.status,
        items=items,
    )
