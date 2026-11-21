"""發佈引擎：三步發佈 begin → check → finalize（foundation-plan D-01、D-02）。

run_post 是立即發佈的執行入口（之後排程發佈、重試也共用）：
1. 讀取貼文所有待發佈紀錄，標記這一次嘗試的開始時間。
2. 各平台並行、各自計時；一個平台失敗、逾時或出錯，不影響其他平台（BR-14、NFR-03）。
3. begin 回傳 request_ref 後，立刻用一個短交易寫進資料庫，再繼續下一步。
4. 每筆結果各自用短交易寫回，寫回前確認紀錄仍是待發佈。
5. 全部結束後依 BR-15 判定貼文狀態，並寫入稽核紀錄。

資料庫操作是同步的，一律丟到執行緒執行，不阻塞事件迴圈。
"""

import asyncio
import logging
import time
from dataclasses import dataclass
from datetime import timedelta
from enum import StrEnum

from starlette.concurrency import run_in_threadpool

from app.core import audit, clock, publish_records
from app.core.config import get_settings
from app.core.crypto import decrypt_credential
from app.core.db import session_scope
from app.core.enums import (
    AuditAction,
    FailureReason,
    HistoryReason,
    Platform,
    PostStatus,
    RecordStatus,
    SkipReason,
    TargetResultStatus,
    TargetType,
)
from app.core.models import UserAccount
from app.core.platforms import (
    CheckResult,
    CheckStatus,
    Credential,
    Failed,
    ImageVersion,
    PlatformAdapter,
    PostContent,
    Published,
    get_adapter,
    mark_auth_invalid,
)
from app.core.posts import transition_post

from . import repository

logger = logging.getLogger("mediagent.publish")

Outcome = Published | Failed


class RunMode(StrEnum):
    """這次執行是怎麼開始的：決定變更歷程的原因與稽核內容。"""

    PUBLISH = "PUBLISH"  # 使用者立即發佈
    SCHEDULED = "SCHEDULED"  # 排程時間到，由系統發佈
    RETRY = "RETRY"  # 使用者重試


_RESULT_REASONS: dict[RunMode, tuple[HistoryReason, HistoryReason]] = {
    RunMode.PUBLISH: (HistoryReason.PUBLISH_SUCCEEDED, HistoryReason.PUBLISH_FAILED),
    RunMode.SCHEDULED: (HistoryReason.PUBLISH_SUCCEEDED, HistoryReason.PUBLISH_FAILED),
    RunMode.RETRY: (HistoryReason.RETRY_SUCCEEDED, HistoryReason.RETRY_FAILED),
}

# 發文動作以這些原因失敗時，平台其實可能已經把貼文發出去了（沒有回應、5xx、429 用完重試）
UNCERTAIN_FINALIZE_FAILURES = (FailureReason.TIMEOUT, FailureReason.PLATFORM_UNAVAILABLE)


@dataclass(frozen=True)
class Job:
    record_id: int
    account_id: int
    platform: str
    # 憑證在處理這一筆時才解密：解不開只影響這一個目標，不會連累其他目標
    credential_encrypted: bytes
    content: PostContent
    # 上一次嘗試保存的 container（重試時才會有）
    request_ref: str | None = None


async def run_post(post_id: int, actor_id: int | None = None, mode: RunMode = RunMode.PUBLISH) -> None:
    """發佈一則貼文所有待發佈的紀錄。actor_id 是觸發發佈的使用者；None 代表系統（排程）。"""
    jobs = await run_in_threadpool(_load_jobs, post_id)
    succeeded, failed = _RESULT_REASONS[mode]
    await asyncio.gather(*(_process(job, succeeded, failed) for job in jobs))
    await run_in_threadpool(_conclude, post_id, actor_id, mode, {job.record_id for job in jobs})


# ---------- 單一平台帳號 ----------


async def _process(job: Job, succeeded: HistoryReason, failed: HistoryReason) -> None:
    """處理一筆發佈紀錄。無論發生什麼事，這一筆最後一定要有結果，貼文才不會卡在發佈中。"""
    await record(job, await _resume_or_attempt(job), succeeded, failed)


async def _resume_or_attempt(job: Job) -> Outcome:
    """D-01 手動重試：紀錄上有保存的 container 時先查詢。

    已發出 → 直接記為成功，不再發文；READY → 從 finalize 接續；其他 → 從 begin 重新開始。
    Threads、Instagram 逾時或 5xx 之後重試，因此不會重複發文。
    """
    if job.request_ref is None:
        return await attempt(job)
    try:
        adapter = get_adapter(job.platform)
        credential = decrypt_credential(job.credential_encrypted)
        timeout = get_settings().platform_call_timeout_seconds
        check = await _safe_check(adapter, credential, job.request_ref, timeout)
    except Exception:
        check = CheckResult(CheckStatus.UNKNOWN)
    if check.status == CheckStatus.PUBLISHED:
        return check.published or Published()
    if check.status == CheckStatus.READY:
        return await attempt(job, job.request_ref)
    return await attempt(job)  # 新的 container 會取代舊的參照


async def attempt(job: Job, request_ref: str | None = None) -> Outcome:
    """發佈一筆，一定回傳結果。有 request_ref 時從保存的 container 接續，不重新建立（D-03）。"""
    try:
        outcome = await _attempt(job, request_ref)
    except Exception as exc:  # 憑證解不開、引擎自己的錯誤：只影響這一個目標
        logger.error("publish attempt for record %s raised %s", job.record_id, type(exc).__name__)
        outcome = Failed(FailureReason.OTHER, type(exc).__name__)
    if not isinstance(outcome, Published | Failed):
        outcome = Failed(FailureReason.OTHER, "adapter returned an invalid result")
    return outcome


async def record(job: Job, outcome: Outcome, succeeded: HistoryReason, failed: HistoryReason) -> None:
    """寫回一筆結果；寫不進去時改記為「其他」失敗，紀錄不會一直停在待發佈。"""
    if isinstance(outcome, Failed) and outcome.message:
        outcome = Failed(outcome.reason, _without_secrets(job, outcome.message))
    reason = succeeded if isinstance(outcome, Published) else failed
    try:
        await run_in_threadpool(_write_back, job, outcome, reason)
    except Exception as exc:
        # 結果寫不進去（例如 Adapter 回報了不存在的失敗原因）：改記為「其他」失敗
        logger.error("result of record %s could not be stored: %s", job.record_id, type(exc).__name__)
        fallback = Failed(FailureReason.OTHER, "result could not be recorded")
        try:
            await run_in_threadpool(_write_back, job, fallback, failed)
        except Exception:
            logger.exception("could not record any result for record %s", job.record_id)


MIN_SECRET_LENGTH = 8


def _without_secrets(job: Job, message: str) -> str:
    """平台的原始錯誤訊息只給管理員看，但仍不可夾帶這個帳號的存取憑證（NFR-02）。

    各 Adapter 已經自己濾過；這裡再以憑證裡的每個字串值過濾一次，Adapter 漏掉也不會存進資料庫。
    """
    try:
        credential = decrypt_credential(job.credential_encrypted)
    except Exception:
        return message
    account_name = credential.get("account_name")
    for value in credential.values():
        if isinstance(value, str) and len(value) >= MIN_SECRET_LENGTH and value != account_name:
            message = message.replace(value, "[redacted]")
    return message


async def _attempt(job: Job, request_ref: str | None = None) -> Outcome:
    settings = get_settings()
    adapter = get_adapter(job.platform)
    credential = decrypt_credential(job.credential_encrypted)
    deadline = time.monotonic() + settings.publish_record_limit_seconds
    call_timeout = settings.platform_call_timeout_seconds

    if request_ref is None:
        try:
            started = await asyncio.wait_for(adapter.begin(credential, job.content), call_timeout)
        except TimeoutError:
            return Failed(FailureReason.TIMEOUT)
        except Exception as exc:
            # Adapter 不應拋出例外；例外訊息可能含憑證，只記錄類別名稱
            logger.error("adapter %s raised %s in begin", job.platform, type(exc).__name__)
            return Failed(FailureReason.OTHER, type(exc).__name__)
        if isinstance(started, Published | Failed):
            return started  # 一步完成的平台（例如 Discord）

        # 先保存 request_ref 再繼續：之後逾時或中斷，都還能向平台查詢這個 container
        request_ref = started.request_ref
        await run_in_threadpool(_save_request_ref, job.record_id, request_ref)

    while True:
        check = await _safe_check(adapter, credential, request_ref, call_timeout)
        if check.status == CheckStatus.READY:
            break
        if check.status == CheckStatus.PUBLISHED:
            return check.published or Published()
        if check.status == CheckStatus.FAILED:
            return check.failed or Failed(FailureReason.OTHER)
        # PROCESSING 或 UNKNOWN：等一下再查，直到單筆總時限
        if time.monotonic() + settings.publish_poll_interval_seconds >= deadline:
            return Failed(FailureReason.TIMEOUT)
        await asyncio.sleep(settings.publish_poll_interval_seconds)

    try:
        result = await asyncio.wait_for(adapter.finalize(credential, request_ref), call_timeout)
    except TimeoutError:
        result = Failed(FailureReason.TIMEOUT)
    except Exception as exc:
        logger.error("adapter %s raised %s in finalize", job.platform, type(exc).__name__)
        return Failed(FailureReason.OTHER, type(exc).__name__)

    if isinstance(result, Failed) and result.reason in UNCERTAIN_FINALIZE_FAILURES:
        # 發文動作結果不明（引擎逾時、沒有拿到回應，或平台回了 5xx）：
        # 不重試，只再查一次；確認已發出才記為成功，否則維持原本的失敗原因
        check = await _safe_check(adapter, credential, request_ref, call_timeout)
        if check.status == CheckStatus.PUBLISHED:
            return check.published or Published()
    return result


async def _safe_check(
    adapter: PlatformAdapter, credential: Credential, request_ref: str | None, timeout: float
) -> CheckResult:
    """check 只查詢；逾時或出錯一律當成無法確認。"""
    try:
        return await asyncio.wait_for(adapter.check(credential, request_ref), timeout)
    except Exception:
        return CheckResult(CheckStatus.UNKNOWN)


# ---------- 資料庫（同步，短交易） ----------


def lease_seconds() -> float:
    """一次嘗試最久會持續多久（D-01 的租約長度）。

    單筆總時限（180 秒）只管建立與等待 container；時限到之前開始的發文動作與之後的確認各還要一次呼叫，
    再留一次呼叫的餘裕：180 + 3 × 30 = 270 秒，仍小於逾時恢復的 10 分鐘門檻。
    """
    settings = get_settings()
    return settings.publish_record_limit_seconds + 3 * settings.platform_call_timeout_seconds


def lease_is_free(attempt_started_at, now) -> bool:
    """這一筆是否沒有人在處理：從沒開始過，或上一次嘗試一定已經結束（D-01、D-02）。"""
    return attempt_started_at is None or attempt_started_at <= now - timedelta(seconds=lease_seconds())


def _load_jobs(post_id: int) -> list[Job]:
    with session_scope() as db:
        post = repository.get_post_for_update(db, post_id)
        if post is None or post.status != PostStatus.PUBLISHING:
            return []
        now = clock.now()
        jobs = []
        for record in repository.pending_records(db, post_id):
            if not lease_is_free(record.attempt_started_at, now):
                continue  # 另一個執行者正在處理這一筆，不重複送出
            if record.platform_account.removed:
                # 移除剛好發生在設定目標或排程的檢查之後：不送出，記為失敗（重試時會跳過已移除的帳號）
                publish_records.set_result(
                    db,
                    record.id,
                    Failed(FailureReason.OTHER, "platform account was removed"),
                    reason=HistoryReason.TARGET_ACCOUNT_REMOVED,
                    content_summary=post.content,
                )
                continue
            repository.start_attempt(db, record, now)
            jobs.append(job_for(record, post))
        return jobs


def job_for(record, post) -> Job:
    account = record.platform_account
    return Job(
        record_id=record.id,
        account_id=account.id,
        platform=account.platform,
        credential_encrypted=bytes(account.credential_encrypted),
        content=PostContent(text=post.content, image=image_for(post, account.platform)),
        request_ref=record.platform_request_ref,
    )


def image_for(post, platform: str) -> ImageVersion | None:
    """Instagram 送裁切後的版本，Threads 與 Discord 送原圖（BR-06）。"""
    if post.image is None:
        return None
    on_instagram = platform == Platform.INSTAGRAM
    media = post.image.instagram if on_instagram else post.image.original
    return ImageVersion(
        url=media.public_url,
        storage_key=media.storage_key,
        sha256=media.sha256,
        width=media.width,
        height=media.height,
        variant="instagram" if on_instagram else "original",
        format=media.format,
    )


def _save_request_ref(record_id: int, request_ref: str) -> None:
    with session_scope() as db:
        repository.save_request_ref(db, record_id, request_ref)


def _write_back(job: Job, outcome: Outcome, reason: HistoryReason) -> None:
    succeeded = isinstance(outcome, Published)
    with session_scope() as db:
        publish_records.set_result(
            db,
            job.record_id,
            outcome,
            reason=reason,
            content_summary=job.content.text,
            image=job.content.image,
        )
        if not succeeded and outcome.reason == FailureReason.AUTH_INVALID:
            mark_auth_invalid(db, job.account_id)  # BR-09


def _conclude(post_id: int, actor_id: int | None, mode: RunMode, ran_ids: set[int]) -> None:
    """所有紀錄都有結果後，判定貼文狀態（BR-15）並寫入稽核紀錄。"""
    with session_scope() as db:
        post = repository.get_post_for_update(db, post_id)
        if post is None or post.status != PostStatus.PUBLISHING:
            return
        records = repository.result_records(db, post_id)
        if not records or any(r.status == RecordStatus.PENDING for r in records):
            return  # 還有紀錄沒結果，留給逾時恢復處理

        final = final_status(records)
        transition_post(post, final)
        by_system = mode == RunMode.SCHEDULED
        if mode == RunMode.PUBLISH:
            post.scheduled_at = None  # BR-29：已排程改立即發佈，完成後清空排程時間

        audit.write(
            db,
            action=AuditAction.PUBLISH_RETRY if mode == RunMode.RETRY else AuditAction.POST_PUBLISH,
            actor=db.get(UserAccount, actor_id) if actor_id and not by_system else None,
            target_type=TargetType.POST,
            target_id=post.id,
            result=final,
            # 系統發佈時記錄是誰設定排程、誰建立貼文
            scheduled_by=post.scheduled_by if by_system else None,
            post_creator_id=post.creator_id if by_system else None,
            target_results=[
                _not_retried(r) if mode == RunMode.RETRY and r.id not in ran_ids else target_result(r)
                for r in records
            ],
        )


def final_status(records) -> PostStatus:
    """BR-15：全部成功為發佈完成，部分成功為部分失敗，全部失敗為全部失敗。"""
    succeeded = sum(r.status == RecordStatus.SUCCEEDED for r in records)
    if succeeded == len(records):
        return PostStatus.PUBLISHED
    if succeeded == 0:
        return PostStatus.FAILED
    return PostStatus.PARTIALLY_FAILED


def target_result(record) -> dict:
    succeeded = record.status == RecordStatus.SUCCEEDED
    return {
        "platform_account_id": record.platform_account_id,
        "status": TargetResultStatus.SUCCEEDED if succeeded else TargetResultStatus.FAILED,
        "failure_reason": record.failure_reason,
    }


def _not_retried(record) -> dict:
    """重試的稽核列出全部目標；這次沒有重送的標示原因（BR-34）。"""
    if record.status == RecordStatus.SUCCEEDED:
        skip = SkipReason.ALREADY_SUCCEEDED
    elif record.platform_account.removed:
        skip = SkipReason.REMOVED_SKIPPED
    else:
        skip = SkipReason.AUTH_INVALID_SKIPPED
    return {
        "platform_account_id": record.platform_account_id,
        "status": TargetResultStatus.NOT_RETRIED,
        "skip_reason": skip,
    }
