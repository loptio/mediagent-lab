from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.auth import get_current_user
from app.core.db import get_db
from app.core.models import UserAccount

from . import service
from .schemas import PublishRecordsOut, TargetsOut, TargetsUpdate

router = APIRouter(prefix="/posts", tags=["目標與排程"])


@router.put("/{post_id}/targets", response_model=TargetsOut, summary="設定目標平台帳號")
def set_targets(
    post_id: int,
    data: TargetsUpdate,
    db: Session = Depends(get_db),
    user: UserAccount = Depends(get_current_user),
):
    return service.set_targets(db, user, post_id, data.platform_account_ids)


@router.get(
    "/{post_id}/publish-records",
    response_model=PublishRecordsOut,
    # 非管理員的回應不含 platform_error_message 欄位
    response_model_exclude_unset=True,
    summary="查看發佈結果",
)
def get_publish_records(
    post_id: int,
    db: Session = Depends(get_db),
    user: UserAccount = Depends(get_current_user),
):
    return service.get_publish_records(db, user, post_id)
