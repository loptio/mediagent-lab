"""排程：找出排程時間已到的貼文並開始發佈（FR-16、BR-25、BR-31、foundation-plan D-07）。

三種觸發方式共用這裡的函式，任何一種成功就會發佈：
1. 服務內的迴圈（run_loop），每分鐘一次。
2. 外部監控定時呼叫 /health，讓免費方案的服務不休眠（部署時設定）。
3. 外部定時任務呼叫 POST /api/v1/internal/publish-due（備援）。

重複觸發是安全的：貼文以 FOR UPDATE SKIP LOCKED 認領，認領後立刻改為發佈中，
第二個觸發看不到它；發佈紀錄另有 attempt_started_at 租約（engine.lease_is_free）。
"""

import asyncio
import logging

from starlette.concurrency import run_in_threadpool

from app.core import clock, publish_records
from app.core.config import get_settings
from app.core.db import session_scope
from app.core.enums import AuthStatus, FailureReason, HistoryReason, PostStatus
from app.core.platforms import Failed, effective_auth_status
from app.core.posts import transition_post

from . import engine, recovery, repository
from .engine import RunMode

logger = logging.getLogger("mediagent.scheduler")

# 背景工作要留著參照，否則可能在執行中被回收
_running: set[asyncio.Task] = set()


def claim_due_posts() -> list[int]:
    """認領排程時間已到的貼文：改為發佈中，授權失效的目標直接記為失敗。回傳認領到的貼文 ID。"""
    now = clock.now()
    with session_scope() as db:
        posts = repository.lock_due_posts(db, now)
        for post in posts:
            transition_post(post, PostStatus.PUBLISHING)
            post.publishing_started_at = now
            for record in repository.pending_records(db, post.id):
                # BR-31：授權失效或已過期的目標不送出，記為「帳號授權過期」
                if effective_auth_status(record.platform_account, now) == AuthStatus.INVALID:
                    publish_records.set_result(
                        db,
                        record.id,
                        Failed(FailureReason.AUTH_EXPIRED),
                        reason=HistoryReason.PUBLISH_FAILED,
                        content_summary=post.content,
                    )
        return [post.id for post in posts]


def start(post_id: int, mode: RunMode) -> asyncio.Task:
    task = asyncio.create_task(engine.run_post(post_id, None, mode))
    _running.add(task)
    task.add_done_callback(_running.discard)
    return task


async def tick() -> list[asyncio.Task]:
    """檢查一次：開始發佈到期的貼文，再處理逾時的發佈。回傳開始的背景工作（測試用來等待完成）。"""
    post_ids = await run_in_threadpool(claim_due_posts)
    if post_ids:
        logger.info("scheduled publishing started for %d post(s)", len(post_ids))
    tasks = [start(post_id, RunMode.SCHEDULED) for post_id in post_ids]
    await recovery.recover_stale(allow_auto_retry=True)
    return tasks


async def run_loop() -> None:
    """服務內的排程迴圈；任何一次失敗只記錄下來，下一分鐘照常檢查。

    服務啟動時先做一次恢復檢查，但不重新發文（BR-33）：只確認結果，或記為發佈逾時。
    """
    interval = get_settings().scheduler_interval_seconds
    try:
        await recovery.recover_stale(allow_auto_retry=False)
    except Exception as exc:
        logger.error("startup recovery failed: %s", type(exc).__name__)
    while True:
        try:
            await tick()
        except Exception as exc:
            logger.error("scheduler tick failed: %s", type(exc).__name__)
        await asyncio.sleep(interval)
