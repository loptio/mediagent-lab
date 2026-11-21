"""M4 目標與排程：設定目標平台帳號、設定與取消排程、查看發佈結果。

已排程貼文修改目標時，同一個交易內同步發佈紀錄（BR-28）。變更歷程查詢尚未實作。
"""

from datetime import UTC, datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.core import audit, auth, clock, publish_records, publish_rules
from app.core.enums import (
    AuditAction,
    AuthStatus,
    HistoryReason,
    PostStatus,
    RecordStatus,
    Role,
    TargetType,
)
from app.core.errors import DomainError, forbidden, not_found
from app.core.models import PlatformAccount, Post, UserAccount
from app.core.platforms import effective_auth_status
from app.core.posts import transition_post
from app.m3_posts import service as posts_service
from app.m3_posts.schemas import PostOut

from . import repository
from .schemas import (
    HistoryActor,
    HistoryItem,
    HistoryOut,
    PublishRecordOut,
    PublishRecordsOut,
    RecordAccount,
    TargetOut,
    TargetsOut,
)

EDITABLE_STATUSES = (PostStatus.DRAFT, PostStatus.SCHEDULED)
# 台灣沒有日光節約時間，固定 UTC+8
TAIPEI = timezone(timedelta(hours=8), "Asia/Taipei")
SCHEDULE_STEP_MINUTES = 5


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

    # 先鎖定要選的平台帳號、再鎖定貼文（與移除平台帳號的順序一致），檢查完到提交前帳號不會被移除
    accounts = repository.get_accounts(db, account_ids, lock=True)
    post = repository.get_post_for_update(db, post_id)
    if post is None:
        raise not_found("找不到貼文")
    auth.ensure_owner_or_role(user, post.creator_id, Role.PUBLISHER)
    if post.status not in EDITABLE_STATUSES:
        raise DomainError(409, "POST_NOT_EDITABLE", "只有草稿與已排程的貼文可以修改")

    scheduled = post.status == PostStatus.SCHEDULED
    if scheduled and not account_ids:
        raise DomainError(
            422, "SCHEDULED_POST_REQUIRES_TARGET", "已排程的貼文至少要保留一個目標平台帳號"
        )

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

    if scheduled:
        # 已排程貼文的新目標也必須符合發佈限制（BR-24），例如字數上限
        publish_rules.check(post, accounts, now)

    repository.replace_targets(db, post.id, account_ids)
    if scheduled:
        _sync_scheduled_records(db, user, post, set(account_ids))
    db.commit()
    return TargetsOut(post_id=post.id, targets=[_target_out(account) for account in accounts])


def _sync_scheduled_records(db: Session, user: UserAccount, post: Post, account_ids: set[int]) -> None:
    """只更新受影響的紀錄（BR-28）：新目標建立待發佈、拿掉的改已取消、加回的同一筆改回待發佈。"""
    for record in repository.list_records(db, post.id):
        if record.platform_account_id not in account_ids:
            publish_records.cancel(db, record, actor=user, reason=HistoryReason.TARGET_MODIFIED)
    for account_id in sorted(account_ids):
        publish_records.ensure_pending(
            db,
            post_id=post.id,
            platform_account_id=account_id,
            actor=user,
            reason=HistoryReason.TARGET_ADDED,
            revived_reason=HistoryReason.TARGET_MODIFIED,
        )


# ---------- 排程 ----------


def to_utc_schedule_time(value: datetime) -> datetime:
    """排程時間以台灣時間輸入：沒有時區的時間視為台灣時間；一律換算成 UTC 儲存。"""
    if value.tzinfo is None:
        value = value.replace(tzinfo=TAIPEI)
    return value.astimezone(UTC)


def _check_schedule_time(when: datetime, now: datetime) -> None:
    if when <= now:
        raise DomainError(422, "SCHEDULE_TIME_NOT_FUTURE", "排程時間必須晚於現在")
    if when.minute % SCHEDULE_STEP_MINUTES or when.second or when.microsecond:
        raise DomainError(422, "SCHEDULE_TIME_NOT_ALIGNED", "排程時間必須是 5 分鐘整，例如 12:00、12:05")


def set_schedule(db: Session, user: UserAccount, post_id: int, scheduled_at: datetime) -> PostOut:
    """設定排程（草稿 → 已排程）或修改已排程貼文的時間（FR-16、BR-10、BR-18、BR-26、BR-27）。"""
    post = repository.get_post_for_update(db, post_id)
    if post is None:
        raise not_found("找不到貼文")
    # 撰稿者只能修改自己已排程貼文的時間，不能為草稿設定排程（BR-18）
    if not auth.has_role(user.role, Role.PUBLISHER) and (
        post.creator_id != user.id or post.status != PostStatus.SCHEDULED
    ):
        raise forbidden()
    if post.status not in EDITABLE_STATUSES:
        raise DomainError(409, "POST_NOT_SCHEDULABLE", "只有草稿與已排程的貼文可以設定排程")

    now = clock.now()
    when = to_utc_schedule_time(scheduled_at)
    _check_schedule_time(when, now)
    accounts = repository.target_accounts(db, post.id)
    publish_rules.check(post, accounts, now)

    # 每個目標一筆待發佈紀錄；先前取消排程留下的同一筆改回待發佈（BR-26、BR-27）
    for account in accounts:
        publish_records.ensure_pending(
            db,
            post_id=post.id,
            platform_account_id=account.id,
            actor=user,
            reason=HistoryReason.SCHEDULE_SET,
            revived_reason=HistoryReason.RESCHEDULED,
        )
    if post.status == PostStatus.DRAFT:
        transition_post(post, PostStatus.SCHEDULED)
    post.scheduled_at = when
    post.scheduled_by = user.id  # 排程設定者是最後一次成功設定排程的人
    audit.write(
        db, action=AuditAction.POST_SCHEDULE, actor=user, target_type=TargetType.POST, target_id=post.id
    )
    db.commit()
    return posts_service.get_post(db, post.id)


def cancel_schedule(db: Session, user: UserAccount, post_id: int) -> PostOut:
    """取消排程：貼文改回草稿、清空排程時間，待發佈紀錄改為已取消（FR-25、BR-27）。"""
    post = repository.get_post_for_update(db, post_id)
    if post is None:
        raise not_found("找不到貼文")
    auth.ensure_owner_or_role(user, post.creator_id, Role.PUBLISHER)
    if post.status != PostStatus.SCHEDULED:
        raise DomainError(409, "POST_NOT_SCHEDULED", "這則貼文沒有排程")

    for record in repository.list_records(db, post.id):
        if record.status == RecordStatus.PENDING:
            publish_records.cancel(db, record, actor=user, reason=HistoryReason.SCHEDULE_CANCELLED)
    transition_post(post, PostStatus.DRAFT)
    post.scheduled_at = None
    audit.write(
        db, action=AuditAction.SCHEDULE_CANCEL, actor=user, target_type=TargetType.POST, target_id=post.id
    )
    db.commit()
    return posts_service.get_post(db, post.id)


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


def get_history(db: Session, post_id: int) -> HistoryOut:
    """發佈紀錄的變更歷程，由舊到新；貼文刪除後仍可查詢（FR-17、BR-35）。"""
    if repository.get_post_including_deleted(db, post_id) is None:
        raise not_found("找不到貼文")
    return HistoryOut(
        post_id=post_id,
        items=[
            HistoryItem(
                publish_record_id=history.publish_record_id,
                from_status=history.from_status,
                to_status=history.to_status,
                changed_at=history.changed_at,
                actor_type=history.actor_type,
                actor=HistoryActor(id=actor.id, name=actor.name) if actor else None,
                reason=history.reason,
            )
            for history, actor in repository.history_of(db, post_id)
        ],
    )
