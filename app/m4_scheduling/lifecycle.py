"""M4 提供給其他模組的生命週期函式（跨模組呼叫只經過這裡）。

- on_post_deleting：M3 刪除貼文前呼叫，把待發佈紀錄改為已取消（BR-27、BR-35）。
- on_platform_account_removed：M2 移除平台帳號時呼叫，處理所有受影響的貼文（BR-23）。
"""

from sqlalchemy.orm import Session

from app.core import publish_records
from app.core.enums import HistoryReason, PostStatus, RecordStatus
from app.core.models import Post, UserAccount
from app.core.posts import transition_post

from . import repository


def on_post_deleting(db: Session, post: Post, actor: UserAccount) -> None:
    """呼叫前貼文必須已鎖定。紀錄只改為已取消、不刪除，刪除後仍可用原 ID 查看發佈結果。"""
    for record in repository.list_records(db, post.id):
        if record.status == RecordStatus.PENDING:
            publish_records.cancel(db, record, actor=actor, reason=HistoryReason.POST_DELETED)


def on_platform_account_removed(db: Session, account_id: int, actor: UserAccount) -> None:
    """從草稿與已排程貼文的目標中拿掉這個平台帳號（BR-23）。

    已排程貼文對它的待發佈紀錄改為已取消；它是唯一的目標時，貼文改回草稿、清空排程時間
    （排程掃描只找已排程貼文，原排程時間到時就不會被發佈）。內容、圖片、建立者保留。
    已進入發佈中或已結束的貼文不受影響。
    """
    for post in repository.lock_editable_posts_targeting(db, account_id):
        repository.remove_target(db, post.id, account_id)
        if post.status != PostStatus.SCHEDULED:
            continue
        for record in repository.list_records(db, post.id):
            if record.platform_account_id == account_id and record.status == RecordStatus.PENDING:
                publish_records.cancel(
                    db, record, actor=actor, reason=HistoryReason.TARGET_ACCOUNT_REMOVED
                )
        if not repository.target_accounts(db, post.id):
            transition_post(post, PostStatus.DRAFT)
            post.scheduled_at = None
