"""發佈逾時恢復（FR-28、BR-33、foundation-plan D-03）。

背景發佈中途服務被重新啟動或中斷，貼文會一直停在「發佈中」。進入發佈中滿 10 分鐘仍有待發佈紀錄時，
這裡向平台查詢每一筆的實際結果，再依結果記錄並重新判定貼文狀態：

| 平台查詢（check）的結果 | 處理 | 變更原因 |
|---|---|---|
| 已發佈 | 記為成功，不重送 | RECOVERY_CONFIRMED_PUBLISHED |
| 確認未發佈，定時檢查且還沒重送過 | 重送一次（有 container 就接續） | AUTO_RETRY_SUCCEEDED／FAILED |
| 確認未發佈，已重送過或服務啟動時的檢查 | 記為失敗「發佈逾時」，不重送 | RECOVERY_CONFIRMED_NOT_PUBLISHED |
| 平台回報處理失敗 | 依平台回報的原因記為失敗 | RECOVERY_CONFIRMED_NOT_PUBLISHED |
| 處理中或無法確認 | 記為失敗「發佈逾時」，不重送 | RECOVERY_UNCONFIRMED |

單筆發佈的總時限（180 秒）小於恢復門檻（10 分鐘），所以接手時原本的背景工作一定已經結束；
另一個觸發剛接手、租約還沒過期的紀錄不會被重複處理（engine.lease_is_free）。
"""

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta

from starlette.concurrency import run_in_threadpool

from app.core import audit, clock
from app.core.config import get_settings
from app.core.crypto import decrypt_credential
from app.core.db import session_scope
from app.core.enums import AuditAction, FailureReason, HistoryReason, PostStatus, RecordStatus, TargetType
from app.core.platforms import CheckStatus, Failed, Published, get_adapter
from app.core.posts import transition_post

from . import engine, repository

logger = logging.getLogger("mediagent.recovery")

AUTO_RETRY_REASON = "PLATFORM_CONFIRMED_NOT_PUBLISHED"


@dataclass(frozen=True)
class RecoveryResult:
    checked: int  # 檢查的貼文數
    recovered: int  # 離開「發佈中」的貼文數


@dataclass(frozen=True)
class StaleRecord:
    job: engine.Job
    request_ref: str | None
    auto_retry_count: int


async def recover_stale(allow_auto_retry: bool) -> RecoveryResult:
    """allow_auto_retry：定時檢查為 True；服務啟動時為 False，絕不重新發文（BR-33）。"""
    post_ids, stale = await run_in_threadpool(_claim, clock.now())
    retried = await asyncio.gather(*(_recover(item, allow_auto_retry) for item in stale))
    auto_retried = {item.job.record_id for item, did in zip(stale, retried, strict=True) if did}

    recovered = 0
    for post_id in post_ids:
        if await run_in_threadpool(_conclude, post_id, auto_retried):
            recovered += 1
    if post_ids:
        logger.info("publish recovery checked %d post(s), recovered %d", len(post_ids), recovered)
    return RecoveryResult(checked=len(post_ids), recovered=recovered)


def _claim(now: datetime) -> tuple[list[int], list[StaleRecord]]:
    threshold = now - timedelta(minutes=get_settings().publish_recovery_minutes)
    with session_scope() as db:
        post_ids, stale = [], []
        for post in repository.lock_stale_posts(db, threshold):
            pending = repository.pending_records(db, post.id)
            free = [r for r in pending if engine.lease_is_free(r.attempt_started_at, now)]
            if pending and not free:
                continue  # 全部都有別的執行者正在處理
            post_ids.append(post.id)
            for record in free:
                repository.start_attempt(db, record, now)
                stale.append(
                    StaleRecord(
                        engine.job_for(record, post), record.platform_request_ref, record.auto_retry_count
                    )
                )
        return post_ids, stale


async def _recover(item: StaleRecord, allow_auto_retry: bool) -> bool:
    """查詢並記錄一筆的結果。回傳這一筆是否自動重送了。"""
    job = item.job
    settings = get_settings()
    try:
        adapter = get_adapter(job.platform)
        credential = decrypt_credential(job.credential_encrypted)
        check = await engine._safe_check(
            adapter, credential, item.request_ref, settings.platform_call_timeout_seconds
        )
    except Exception as exc:  # 憑證解不開等：無法確認
        logger.error("recovery check for record %s raised %s", job.record_id, type(exc).__name__)
        check = None

    status = check.status if check else CheckStatus.UNKNOWN
    if status == CheckStatus.PUBLISHED:
        outcome = check.published or Published()
        await engine.record(
            job, outcome, HistoryReason.RECOVERY_CONFIRMED_PUBLISHED, HistoryReason.RECOVERY_UNCONFIRMED
        )
        return False
    if status == CheckStatus.READY and allow_auto_retry and item.auto_retry_count == 0:
        await run_in_threadpool(_count_auto_retry, job.record_id)
        outcome = await engine.attempt(job, item.request_ref)
        await engine.record(
            job, outcome, HistoryReason.AUTO_RETRY_SUCCEEDED, HistoryReason.AUTO_RETRY_FAILED
        )
        return True
    if status == CheckStatus.READY:
        outcome, reason = Failed(FailureReason.TIMEOUT), HistoryReason.RECOVERY_CONFIRMED_NOT_PUBLISHED
    elif status == CheckStatus.FAILED:
        outcome = check.failed or Failed(FailureReason.OTHER)
        reason = HistoryReason.RECOVERY_CONFIRMED_NOT_PUBLISHED
    else:  # 處理中或無法確認
        outcome, reason = Failed(FailureReason.TIMEOUT), HistoryReason.RECOVERY_UNCONFIRMED
    await engine.record(job, outcome, reason, reason)
    return False


def _count_auto_retry(record_id: int) -> None:
    with session_scope() as db:
        repository.count_auto_retry(db, record_id)


def _conclude(post_id: int, auto_retried: set[int]) -> bool:
    """所有紀錄都有結果後重新判定貼文狀態並寫稽核。回傳貼文是否離開了發佈中。"""
    with session_scope() as db:
        post = repository.get_post_for_update(db, post_id)
        if post is None or post.status != PostStatus.PUBLISHING:
            return False
        records = repository.result_records(db, post_id)
        if not records or any(r.status == RecordStatus.PENDING for r in records):
            return False

        final = engine.final_status(records)
        transition_post(post, final)
        retried = [r for r in records if r.id in auto_retried]
        if retried:
            # 自動重試發佈：記錄觸發原因與這次重送的結果
            audit.write(
                db,
                action=AuditAction.PUBLISH_AUTO_RETRY,
                actor=None,
                target_type=TargetType.POST,
                target_id=post.id,
                result=final,
                reason=AUTO_RETRY_REASON,
                target_results=[engine.target_result(r) for r in retried],
            )
        else:
            # 中斷的那次發佈沒有寫到稽核：由系統補上這一筆
            audit.write(
                db,
                action=AuditAction.POST_PUBLISH,
                actor=None,
                target_type=TargetType.POST,
                target_id=post.id,
                result=final,
                scheduled_by=post.scheduled_by,
                post_creator_id=post.creator_id,
                target_results=[engine.target_result(r) for r in records],
            )
        return True
