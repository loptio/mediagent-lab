"""發佈紀錄：建立與每次狀態改變都在這裡完成，並同時寫入變更歷程（BR-26～BR-29）。

只 flush，不 commit；交易由呼叫者（service 或發佈引擎）決定。
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import clock
from .enums import ActorType, HistoryReason, RecordStatus
from .models import PublishRecord, PublishRecordHistory, UserAccount
from .platforms import Failed, ImageVersion, Published


def _record_history(
    db: Session,
    record: PublishRecord,
    from_status: str | None,
    actor: UserAccount | None,
    reason: HistoryReason,
) -> None:
    db.add(
        PublishRecordHistory(
            publish_record_id=record.id,
            from_status=from_status,
            to_status=record.status,
            changed_at=clock.now(),
            actor_type=ActorType.USER if actor else ActorType.SYSTEM,
            actor_id=actor.id if actor else None,
            reason=reason,
        )
    )
    db.flush()


def ensure_pending(
    db: Session,
    *,
    post_id: int,
    platform_account_id: int,
    actor: UserAccount | None,
    reason: HistoryReason,
    revived_reason: HistoryReason | None = None,
) -> PublishRecord:
    """確保（貼文, 平台帳號）有一筆待發佈紀錄。

    沒有紀錄就建立（變更原因 reason）；已取消或失敗的同一筆改回待發佈（不新增，BR-27、BR-16），
    變更原因為 revived_reason（沒給就用 reason）；已是待發佈或已成功的維持原狀，不寫變更歷程。

    改回待發佈時清掉上一次嘗試的開始時間：那次嘗試已經結束，留著會讓發佈引擎以為還有人在處理這一筆
    （D-01 的租約）。平台參照（container）保留：重試時引擎會先查詢它，已發出就不再發文（D-01）。
    """
    record = db.scalar(
        select(PublishRecord).where(
            PublishRecord.post_id == post_id,
            PublishRecord.platform_account_id == platform_account_id,
        )
    )
    if record is None:
        record = PublishRecord(
            post_id=post_id, platform_account_id=platform_account_id, status=RecordStatus.PENDING
        )
        db.add(record)
        db.flush()
        _record_history(db, record, None, actor, reason)
    elif record.status in (RecordStatus.CANCELLED, RecordStatus.FAILED):
        previous = record.status
        record.status = RecordStatus.PENDING
        record.failure_reason = None
        record.platform_error_message = None
        record.attempt_started_at = None
        db.flush()
        _record_history(db, record, previous, actor, revived_reason or reason)
    return record


def cancel(
    db: Session, record: PublishRecord, *, actor: UserAccount | None, reason: HistoryReason
) -> None:
    """待發佈改為已取消（不刪除）；其他狀態不變。"""
    if record.status != RecordStatus.PENDING:
        return
    record.status = RecordStatus.CANCELLED
    db.flush()
    _record_history(db, record, RecordStatus.PENDING, actor, reason)


def set_result(
    db: Session,
    record_id: int,
    outcome: Published | Failed,
    *,
    reason: HistoryReason,
    content_summary: str | None = None,
    image: ImageVersion | None = None,
) -> bool:
    """寫回發佈結果。只有紀錄仍是待發佈時才寫入，否則回傳 False 且不做任何變更。

    保存送出圖片的識別資訊（雜湊值、格式、尺寸、版本），不保存圖片本身。

    背景發佈期間紀錄可能已被取消或被其他執行者處理；這個檢查避免覆蓋別人的結果。
    """
    record = db.scalar(
        select(PublishRecord).where(PublishRecord.id == record_id).with_for_update()
    )
    if record is None or record.status != RecordStatus.PENDING:
        return False

    if isinstance(outcome, Published):
        record.status = RecordStatus.SUCCEEDED
        record.published_at = clock.now()
        record.platform_post_id = outcome.post_id
        record.platform_post_url = outcome.post_url
        record.failure_reason = None
        record.platform_error_message = None
    else:
        record.status = RecordStatus.FAILED
        record.failure_reason = outcome.reason
        record.platform_error_message = outcome.message
    if content_summary is not None:
        record.content_summary = content_summary
    if image is not None:
        # 成功與失敗都記下這次送出（或嘗試送出）的是哪一張圖
        record.image_sha256 = image.sha256
        record.image_format = image.format
        record.image_width = image.width
        record.image_height = image.height
        record.image_variant = image.variant
    db.flush()
    _record_history(db, record, RecordStatus.PENDING, None, reason)
    return True
