from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload, selectinload

from app.core.models import PlatformAccount, Post, PostTarget


def create(db: Session, creator_id: int, content: str) -> Post:
    post = Post(content=content, creator_id=creator_id)
    db.add(post)
    db.flush()
    return post


def get_active(db: Session, post_id: int) -> Post | None:
    """取得未刪除的貼文（軟刪除的貼文視為不存在）。"""
    stmt = (
        select(Post)
        .options(joinedload(Post.creator))
        .where(Post.id == post_id, Post.deleted_at.is_(None))
    )
    return db.scalar(stmt)


def get_active_for_update(db: Session, post_id: int) -> Post | None:
    """鎖定未刪除的貼文；修改、刪除前都要先鎖定，與排程發佈的認領互斥（NFR-11）。"""
    stmt = select(Post).where(Post.id == post_id, Post.deleted_at.is_(None)).with_for_update()
    return db.scalar(stmt)


def count(db: Session, status: str | None) -> int:
    stmt = select(func.count()).select_from(Post).where(Post.deleted_at.is_(None))
    if status:
        stmt = stmt.where(Post.status == status)
    return db.scalar(stmt) or 0


def list_page(db: Session, status: str | None, offset: int, limit: int) -> list[Post]:
    # BR-44：建立時間由新到舊，相同時依 ID 由大到小
    stmt = (
        select(Post)
        # 列表要顯示 has_image：一次載入所有貼文的圖片關聯，不要每則貼文各查一次
        .options(joinedload(Post.creator), selectinload(Post.image))
        .where(Post.deleted_at.is_(None))
        .order_by(Post.created_at.desc(), Post.id.desc())
        .offset(offset)
        .limit(limit)
    )
    if status:
        stmt = stmt.where(Post.status == status)
    return list(db.scalars(stmt))


def targets_of(db: Session, post_ids: list[int]) -> dict[int, list[PlatformAccount]]:
    """各貼文目前選擇的目標平台帳號（只讀 M4 的 post_target）。"""
    result: dict[int, list[PlatformAccount]] = {post_id: [] for post_id in post_ids}
    if not post_ids:
        return result
    rows = db.execute(
        select(PostTarget.post_id, PlatformAccount)
        .join(PlatformAccount, PlatformAccount.id == PostTarget.platform_account_id)
        .where(PostTarget.post_id.in_(post_ids))
        .order_by(PlatformAccount.id)
    )
    for post_id, account in rows:
        result[post_id].append(account)
    return result
