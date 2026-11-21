"""貼文狀態轉換：所有改變 post.status 的地方都必須經過這裡（BR-12）。"""

from .enums import PostStatus
from .errors import DomainError
from .models import Post

_ALLOWED: dict[str, set[str]] = {
    PostStatus.DRAFT: {PostStatus.SCHEDULED, PostStatus.PUBLISHING},
    PostStatus.SCHEDULED: {PostStatus.DRAFT, PostStatus.PUBLISHING},
    PostStatus.PUBLISHING: {
        PostStatus.PUBLISHED,
        PostStatus.PARTIALLY_FAILED,
        PostStatus.FAILED,
    },
    PostStatus.PARTIALLY_FAILED: {PostStatus.PUBLISHING},
    PostStatus.FAILED: {PostStatus.PUBLISHING},
    PostStatus.PUBLISHED: set(),
}


def transition_post(post: Post, to_status: PostStatus) -> None:
    """檢查並執行狀態轉換。呼叫前必須已經鎖定貼文（SELECT ... FOR UPDATE）。

    各功能應先自行檢查並回報自己的錯誤碼（例如 POST_NOT_PUBLISHABLE）；
    這裡是最後一道防線，擋下不在 BR-12 內的轉換。
    """
    if to_status not in _ALLOWED[post.status]:
        raise DomainError(
            409,
            "POST_INVALID_TRANSITION",
            f"貼文狀態不能從 {post.status} 改為 {to_status}",
            {"from": post.status, "to": str(to_status)},
        )
    post.status = to_status
