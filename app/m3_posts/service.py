"""M3 貼文編輯：建立、取得、列表。

修改、刪除、圖片、預覽、複製為新草稿尚未實作。
"""

from sqlalchemy.orm import Session

from app.core import clock
from app.core.enums import PostStatus
from app.core.errors import DomainError, not_found
from app.core.models import PlatformAccount, Post, UserAccount
from app.core.platforms import effective_auth_status

from . import repository
from .schemas import PostListItem, PostOut, PostPage, TargetOut, UserRef

PAGE_SIZES = (20, 50, 100)


def _targets(accounts: list[PlatformAccount]) -> list[TargetOut]:
    now = clock.now()
    return [
        TargetOut(
            id=account.id,
            platform=account.platform,
            account_name=account.account_name,
            auth_status=effective_auth_status(account, now),
        )
        for account in accounts
    ]


def _to_out(db: Session, post: Post) -> PostOut:
    return PostOut(
        id=post.id,
        content=post.content,
        status=post.status,
        scheduled_at=post.scheduled_at,
        scheduled_by=post.scheduled_by,
        creator=UserRef(id=post.creator.id, name=post.creator.name),
        created_at=post.created_at,
        targets=_targets(repository.targets_of(db, [post.id])[post.id]),
    )


def create_post(db: Session, user: UserAccount, content: str) -> PostOut:
    if not content.strip():
        raise DomainError(422, "CONTENT_EMPTY", "貼文文字不可為空白")
    post = repository.create(db, user.id, content)
    db.commit()
    return get_post(db, post.id)


def get_post(db: Session, post_id: int) -> PostOut:
    post = repository.get_active(db, post_id)
    if post is None:
        raise not_found("找不到貼文")
    return _to_out(db, post)


def list_posts(db: Session, status: str | None, page: int, page_size: int) -> PostPage:
    if page < 1 or page_size not in PAGE_SIZES:
        raise DomainError(400, "VALIDATION_ERROR", "page 必須大於 0，page_size 只能是 20、50、100")
    if status is not None and status not in PostStatus.__members__:
        raise DomainError(400, "VALIDATION_ERROR", "status 不是有效的貼文狀態")

    total = repository.count(db, status)
    posts = repository.list_page(db, status, (page - 1) * page_size, page_size)
    targets = repository.targets_of(db, [post.id for post in posts])
    total_pages = (total + page_size - 1) // page_size
    return PostPage(
        items=[
            PostListItem(
                id=post.id,
                content=post.content,
                status=post.status,
                scheduled_at=post.scheduled_at,
                created_at=post.created_at,
                creator=UserRef(id=post.creator.id, name=post.creator.name),
                targets=_targets(targets[post.id]),
            )
            for post in posts
        ],
        page=page,
        page_size=page_size,
        total=total,
        total_pages=total_pages,
        has_prev=page > 1,
        has_next=page < total_pages,
    )
