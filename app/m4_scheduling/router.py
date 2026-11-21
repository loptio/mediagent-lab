from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.auth import get_current_user
from app.core.db import get_db
from app.core.models import UserAccount
from app.m3_posts.schemas import PostOut

from . import service
from .schemas import PublishRecordsOut, ScheduleUpdate, TargetsOut, TargetsUpdate

router = APIRouter(prefix="/posts", tags=["目標與排程"])


@router.put("/{post_id}/targets", response_model=TargetsOut, summary="設定目標平台帳號")
def set_targets(
    post_id: int,
    data: TargetsUpdate,
    db: Session = Depends(get_db),
    user: UserAccount = Depends(get_current_user),
):
    return service.set_targets(db, user, post_id, data.platform_account_ids)


@router.put("/{post_id}/schedule", response_model=PostOut, summary="設定排程")
def set_schedule(
    post_id: int,
    data: ScheduleUpdate,
    db: Session = Depends(get_db),
    user: UserAccount = Depends(get_current_user),
):
    """排程時間必須晚於現在，且是 5 分鐘整（例如 12:00、12:05）。時間到由系統自動發佈。"""
    return service.set_schedule(db, user, post_id, data.scheduled_at)


@router.delete("/{post_id}/schedule", response_model=PostOut, summary="取消排程")
def cancel_schedule(
    post_id: int,
    db: Session = Depends(get_db),
    user: UserAccount = Depends(get_current_user),
):
    return service.cancel_schedule(db, user, post_id)


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
