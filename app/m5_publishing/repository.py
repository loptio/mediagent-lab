from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.enums import PostStatus, RecordStatus
from app.core.models import PlatformAccount, Post, PostTarget, PublishRecord


def get_post_for_update(db: Session, post_id: int) -> Post | None:
    stmt = select(Post).where(Post.id == post_id, Post.deleted_at.is_(None)).with_for_update()
    return db.scalar(stmt)


def lock_due_posts(db: Session, now: datetime) -> list[Post]:
    """排程時間已到的已排程貼文；被其他執行者鎖住的跳過（NFR-11）。"""
    stmt = (
        select(Post)
        .where(
            Post.status == PostStatus.SCHEDULED,
            Post.scheduled_at <= now,
            Post.deleted_at.is_(None),
        )
        .order_by(Post.scheduled_at, Post.id)
        .with_for_update(skip_locked=True)
    )
    return list(db.scalars(stmt))


def lock_stale_posts(db: Session, started_before: datetime) -> list[Post]:
    """進入發佈中的時間不晚於 started_before 的貼文（BR-33）；被其他執行者鎖住的跳過。"""
    stmt = (
        select(Post)
        .where(
            Post.status == PostStatus.PUBLISHING,
            Post.publishing_started_at <= started_before,
            Post.deleted_at.is_(None),
        )
        .order_by(Post.publishing_started_at, Post.id)
        .with_for_update(skip_locked=True)
    )
    return list(db.scalars(stmt))


def count_auto_retry(db: Session, record_id: int) -> None:
    record = db.get(PublishRecord, record_id)
    if record is not None:
        record.auto_retry_count += 1
        db.flush()


def target_accounts(db: Session, post_id: int) -> list[PlatformAccount]:
    stmt = (
        select(PlatformAccount)
        .join(PostTarget, PostTarget.platform_account_id == PlatformAccount.id)
        .where(PostTarget.post_id == post_id)
        .order_by(PlatformAccount.id)
    )
    return list(db.scalars(stmt))


def pending_records(db: Session, post_id: int) -> list[PublishRecord]:
    stmt = (
        select(PublishRecord)
        .where(PublishRecord.post_id == post_id, PublishRecord.status == RecordStatus.PENDING)
        .order_by(PublishRecord.id)
    )
    return list(db.scalars(stmt))


def result_records(db: Session, post_id: int) -> list[PublishRecord]:
    """參與本次結果判定的紀錄：已取消的不算。"""
    stmt = (
        select(PublishRecord)
        .where(PublishRecord.post_id == post_id, PublishRecord.status != RecordStatus.CANCELLED)
        .order_by(PublishRecord.id)
    )
    return list(db.scalars(stmt))


def start_attempt(db: Session, record: PublishRecord, now: datetime) -> None:
    record.attempt_started_at = now
    db.flush()


def save_request_ref(db: Session, record_id: int, request_ref: str) -> None:
    record = db.get(PublishRecord, record_id)
    if record is not None:
        record.platform_request_ref = request_ref
        db.flush()
