from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.enums import RecordStatus
from app.core.models import PlatformAccount, Post, PostTarget, PublishRecord


def get_post_for_update(db: Session, post_id: int) -> Post | None:
    stmt = select(Post).where(Post.id == post_id, Post.deleted_at.is_(None)).with_for_update()
    return db.scalar(stmt)


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
