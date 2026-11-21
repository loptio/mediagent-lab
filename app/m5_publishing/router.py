from fastapi import APIRouter, BackgroundTasks, Depends
from sqlalchemy.orm import Session

from app.core.auth import require_role
from app.core.db import get_db
from app.core.enums import Role
from app.core.models import UserAccount

from . import engine, service
from .engine import RunMode
from .schemas import PublishJobAccepted, PublishJobCreate

router = APIRouter(prefix="/posts", tags=["發佈"])


@router.post(
    "/{post_id}/publish-jobs",
    response_model=PublishJobAccepted,
    status_code=202,
    summary="立即發佈、重試發佈",
)
def create_publish_job(
    post_id: int,
    data: PublishJobCreate,
    background: BackgroundTasks,
    db: Session = Depends(get_db),
    user: UserAccount = Depends(require_role(Role.PUBLISHER)),
):
    """受理後立即回應 202，各平台在背景發佈；用 GET /posts/{id}/publish-records 查看結果。

    重試只會重送失敗的平台帳號。Threads 會先向平台確認上一次是否其實已經發出；
    Discord 無法事後查詢，失敗原因是「發佈逾時」或「平台暫時無法連線」時，請先到頻道確認訊息是否已經發出。
    """
    if data.type == "retry":
        accepted = service.accept_retry(db, user, post_id)
        mode = RunMode.RETRY
    else:
        accepted = service.accept_immediate(db, user, post_id)
        mode = RunMode.PUBLISH
    background.add_task(engine.run_post, post_id, user.id, mode)
    return accepted
