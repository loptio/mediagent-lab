from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.auth import require_role
from app.core.db import get_db
from app.core.enums import Role
from app.core.models import UserAccount

from . import service
from .schemas import EventPage

router = APIRouter(prefix="/audit-events", tags=["稽核"])


@router.get("", response_model=EventPage, summary="查詢稽核紀錄")
def search(
    actor_type: Literal["user", "system"] | None = None,
    actor_id: int | None = None,
    account_id: int | None = None,
    action: str | None = None,
    start: datetime | None = Query(default=None, alias="from"),
    end: datetime | None = Query(default=None, alias="to"),
    page: int = 1,
    page_size: int = 20,
    db: Session = Depends(get_db),
    _: UserAccount = Depends(require_role(Role.ADMIN)),
):
    """一般稽核、登入失敗、平台帳號連結失敗合在一起，依時間由新到舊。依操作者篩選時不含登入失敗事件。

    時間區間含開始、不含結束；沒有時區的時間視為台灣時間。
    """
    return service.search(
        db,
        actor_type=actor_type,
        actor_id=actor_id,
        account_id=account_id,
        action=action,
        start=start,
        end=end,
        page=page,
        page_size=page_size,
    )
