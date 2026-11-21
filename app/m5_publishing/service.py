"""M5 發佈執行：立即發佈與重試的受理。

受理在這個請求的交易內完成並立刻回應（BR-30）；實際發佈由 engine.run_post 在背景執行。
排程發佈見 scheduler.py，逾時恢復見 recovery.py。
"""

from sqlalchemy.orm import Session

from app.core import clock, publish_records, publish_rules
from app.core.enums import AuthStatus, HistoryReason, PostStatus, RecordStatus, SkipReason
from app.core.errors import DomainError, not_found
from app.core.models import UserAccount
from app.core.platforms import effective_auth_status
from app.core.posts import transition_post

from . import repository
from .schemas import JobRecord, PublishJobAccepted

PUBLISHABLE_STATUSES = (PostStatus.DRAFT, PostStatus.SCHEDULED)
RETRYABLE_STATUSES = (PostStatus.PARTIALLY_FAILED, PostStatus.FAILED)


def accept_immediate(db: Session, user: UserAccount, post_id: int) -> PublishJobAccepted:
    post = repository.get_post_for_update(db, post_id)
    if post is None:
        raise not_found("找不到貼文")
    if post.status not in PUBLISHABLE_STATUSES:
        raise DomainError(409, "POST_NOT_PUBLISHABLE", "只有草稿與已排程的貼文可以立即發佈")

    accounts = repository.target_accounts(db, post.id)
    now = clock.now()
    publish_rules.check(post, accounts, now)

    # 草稿：為每個目標建立待發佈紀錄；已排程：沿用既有的待發佈紀錄（BR-26、BR-29）
    records = [
        publish_records.ensure_pending(
            db,
            post_id=post.id,
            platform_account_id=account.id,
            actor=user,
            reason=HistoryReason.PUBLISH_NOW,
        )
        for account in accounts
    ]
    transition_post(post, PostStatus.PUBLISHING)
    post.publishing_started_at = now
    db.commit()

    return PublishJobAccepted(
        post_id=post.id,
        post_status=post.status,
        records=[
            JobRecord(id=r.id, platform_account_id=r.platform_account_id, status=r.status)
            for r in records
        ],
    )


def accept_retry(db: Session, user: UserAccount, post_id: int) -> PublishJobAccepted:
    """重試只重送失敗、且平台帳號未移除並授權有效的紀錄；已成功的不重送（BR-16、BR-34）。"""
    post = repository.get_post_for_update(db, post_id)
    if post is None:
        raise not_found("找不到貼文")
    if post.status not in RETRYABLE_STATUSES:
        raise DomainError(409, "POST_NOT_RETRYABLE", "只有部分失敗或全部失敗的貼文可以重試")

    now = clock.now()
    retryable, hints = [], []
    for record in repository.result_records(db, post.id):
        if record.status != RecordStatus.FAILED:
            continue
        account = record.platform_account
        if account.removed:
            skip = SkipReason.REMOVED_SKIPPED
        elif effective_auth_status(account, now) == AuthStatus.INVALID:
            skip = SkipReason.AUTH_INVALID_SKIPPED
        else:
            retryable.append(record)
            continue
        hints.append(
            {"platform_account_id": account.id, "account_name": account.account_name, "reason": skip}
        )
    if not retryable:
        raise DomainError(
            422,
            "NOTHING_TO_RETRY",
            "沒有可以重試的平台帳號：授權失效的請先重新連結，已移除的請改用「複製為新草稿」",
            {"hints": hints},
        )

    for record in retryable:
        publish_records.ensure_pending(
            db,
            post_id=post.id,
            platform_account_id=record.platform_account_id,
            actor=user,
            reason=HistoryReason.RETRY_STARTED,
        )
    transition_post(post, PostStatus.PUBLISHING)
    post.publishing_started_at = now
    db.commit()

    return PublishJobAccepted(
        post_id=post.id,
        post_status=post.status,
        records=[
            JobRecord(id=r.id, platform_account_id=r.platform_account_id, status=r.status)
            for r in retryable
        ],
    )
