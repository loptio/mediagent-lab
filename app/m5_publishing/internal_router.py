"""給外部定時任務呼叫的內部端點（《API 設計》32～33）。不列入公開文件。"""

import hmac

from fastapi import APIRouter, BackgroundTasks, Depends, Header
from starlette.concurrency import run_in_threadpool

from app.core.config import get_settings
from app.core.errors import DomainError

from . import engine, scheduler
from .engine import RunMode


def require_cron_secret(x_cron_secret: str | None = Header(default=None)) -> None:
    """X-Cron-Secret 必須與設定相同；沒有設定 CRON_SECRET 時一律拒絕。"""
    expected = get_settings().cron_secret
    if not expected or not x_cron_secret or not hmac.compare_digest(
        x_cron_secret.encode(), expected.encode()
    ):
        raise DomainError(401, "UNAUTHENTICATED", "缺少或錯誤的 X-Cron-Secret")


router = APIRouter(
    prefix="/internal", include_in_schema=False, dependencies=[Depends(require_cron_secret)]
)


@router.post("/publish-due")
async def publish_due(background: BackgroundTasks) -> dict[str, int]:
    """發佈排程時間已到的貼文；認領後立即回應，實際發佈在背景進行。"""
    post_ids = await run_in_threadpool(scheduler.claim_due_posts)
    for post_id in post_ids:
        background.add_task(engine.run_post, post_id, None, RunMode.SCHEDULED)
    return {"started": len(post_ids)}
