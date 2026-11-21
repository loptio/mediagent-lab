"""M4 提供給其他模組的生命週期函式（跨模組呼叫只經過這裡）。

- on_post_deleting：M3 刪除貼文前呼叫，把待發佈紀錄改為已取消（BR-27、BR-35）。
- 移除平台帳號（BR-23）的對應函式在該功能實作時加入。
"""

from sqlalchemy.orm import Session

from app.core import publish_records
from app.core.enums import HistoryReason, RecordStatus
from app.core.models import Post, UserAccount

from . import repository


def on_post_deleting(db: Session, post: Post, actor: UserAccount) -> None:
    """呼叫前貼文必須已鎖定。紀錄只改為已取消、不刪除，刪除後仍可用原 ID 查看發佈結果。"""
    for record in repository.list_records(db, post.id):
        if record.status == RecordStatus.PENDING:
            publish_records.cancel(db, record, actor=actor, reason=HistoryReason.POST_DELETED)
