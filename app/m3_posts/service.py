"""M3 貼文編輯：建立、取得、列表、修改、刪除。

圖片、預覽、複製為新草稿尚未實作。
"""

from sqlalchemy.orm import Session

from app.core import auth, clock, publish_rules
from app.core.enums import PostStatus, Role
from app.core.errors import DomainError, not_found
from app.core.models import PlatformAccount, Post, UserAccount
from app.core.platforms import effective_auth_status
from app.m4_scheduling import lifecycle

from . import repository
from .schemas import PostListItem, PostOut, PostPage, TargetOut, UserRef

PAGE_SIZES = (20, 50, 100)
EDITABLE_STATUSES = (PostStatus.DRAFT, PostStatus.SCHEDULED)


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


def _editable_post(db: Session, user: UserAccount, post_id: int) -> Post:
    """鎖定並取得可以修改或刪除的貼文（BR-13、BR-18）。"""
    post = repository.get_active_for_update(db, post_id)
    if post is None:
        raise not_found("找不到貼文")
    auth.ensure_owner_or_role(user, post.creator_id, Role.PUBLISHER)
    if post.status not in EDITABLE_STATUSES:
        raise DomainError(409, "POST_NOT_EDITABLE", "只有草稿與已排程的貼文可以修改或刪除")
    return post


def update_post(db: Session, user: UserAccount, post_id: int, content: str) -> PostOut:
    """修改貼文內容（FR-12）。已排程貼文以新內容檢查發佈限制，成功後維持已排程、時間不變（BR-24）。"""
    post = _editable_post(db, user, post_id)
    if not content.strip():
        raise DomainError(422, "CONTENT_EMPTY", "貼文文字不可為空白")
    post.content = content
    if post.status == PostStatus.SCHEDULED:
        # 不符合時拋出錯誤，交易不會 commit，內容維持原樣
        publish_rules.check(post, repository.targets_of(db, [post.id])[post.id], clock.now())
    db.commit()
    return get_post(db, post.id)


def delete_post(db: Session, user: UserAccount, post_id: int) -> None:
    """刪除貼文（FR-13）：軟刪除，發佈紀錄、變更歷程與稽核都保留，仍可用原 ID 查看發佈結果（BR-35）。"""
    post = _editable_post(db, user, post_id)
    if post.status == PostStatus.SCHEDULED:
        lifecycle.on_post_deleting(db, post, user)  # 待發佈紀錄改為已取消
    post.deleted_at = clock.now()
    db.commit()
