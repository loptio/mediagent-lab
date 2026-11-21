from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.enums import PostStatus
from app.core.models import (
    PlatformAccount,
    Post,
    PostTarget,
    PublishRecord,
    PublishRecordHistory,
    UserAccount,
)


def get_post_for_update(db: Session, post_id: int) -> Post | None:
    """鎖定未刪除的貼文；改變目標、排程或發佈紀錄之前都要先鎖定（NFR-11）。"""
    stmt = select(Post).where(Post.id == post_id, Post.deleted_at.is_(None)).with_for_update()
    return db.scalar(stmt)


def get_post_including_deleted(db: Session, post_id: int) -> Post | None:
    return db.get(Post, post_id)


def get_accounts(db: Session, account_ids: list[int]) -> list[PlatformAccount]:
    if not account_ids:
        return []
    stmt = select(PlatformAccount).where(PlatformAccount.id.in_(account_ids)).order_by(
        PlatformAccount.id
    )
    return list(db.scalars(stmt))


def target_accounts(db: Session, post_id: int) -> list[PlatformAccount]:
    stmt = (
        select(PlatformAccount)
        .join(PostTarget, PostTarget.platform_account_id == PlatformAccount.id)
        .where(PostTarget.post_id == post_id)
        .order_by(PlatformAccount.id)
    )
    return list(db.scalars(stmt))


def replace_targets(db: Session, post_id: int, account_ids: list[int]) -> None:
    db.execute(delete(PostTarget).where(PostTarget.post_id == post_id))
    db.add_all(PostTarget(post_id=post_id, platform_account_id=aid) for aid in account_ids)
    db.flush()


def list_records(db: Session, post_id: int) -> list[PublishRecord]:
    stmt = (
        select(PublishRecord)
        .where(PublishRecord.post_id == post_id)
        .order_by(PublishRecord.id)
    )
    return list(db.scalars(stmt))


def lock_editable_posts_targeting(db: Session, account_id: int) -> list[Post]:
    """以這個平台帳號為目標的草稿與已排程貼文（依 id 鎖定，與排程認領互斥）。"""
    stmt = (
        select(Post)
        .join(PostTarget, PostTarget.post_id == Post.id)
        .where(
            PostTarget.platform_account_id == account_id,
            Post.deleted_at.is_(None),
            Post.status.in_((PostStatus.DRAFT, PostStatus.SCHEDULED)),
        )
        .order_by(Post.id)
        .with_for_update(of=Post)
    )
    return list(db.scalars(stmt))


def remove_target(db: Session, post_id: int, account_id: int) -> None:
    db.execute(
        delete(PostTarget).where(PostTarget.post_id == post_id, PostTarget.platform_account_id == account_id)
    )
    db.flush()


def history_of(db: Session, post_id: int) -> list[tuple[PublishRecordHistory, UserAccount | None]]:
    stmt = (
        select(PublishRecordHistory, UserAccount)
        .join(PublishRecord, PublishRecord.id == PublishRecordHistory.publish_record_id)
        .outerjoin(UserAccount, UserAccount.id == PublishRecordHistory.actor_id)
        .where(PublishRecord.post_id == post_id)
        .order_by(PublishRecordHistory.changed_at, PublishRecordHistory.id)
    )
    return [(history, actor) for history, actor in db.execute(stmt)]
