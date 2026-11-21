"""稽核寫入：audit_log 與 audit_target_result 只能經由這裡新增（NFR-08）。"""

from typing import Any

from sqlalchemy.orm import Session

from . import clock
from .enums import ActorType, AuditAction, TargetType
from .models import AuditLog, AuditTargetResult, UserAccount


def write(
    db: Session,
    *,
    action: AuditAction,
    actor: UserAccount | None,
    target_type: TargetType,
    target_id: int,
    result: str | None = None,
    reason: str | None = None,
    related_post_id: int | None = None,
    scheduled_by: int | None = None,
    post_creator_id: int | None = None,
    target_results: list[dict[str, Any]] | None = None,
) -> AuditLog:
    """新增一筆稽核紀錄；actor 為 None 代表系統身分。只 flush，不 commit，交易由呼叫者決定。

    target_results：發佈與重試時各目標平台帳號的結果，
    每筆為 {platform_account_id, status, failure_reason?, skip_reason?}。
    """
    row = AuditLog(
        actor_type=ActorType.USER if actor else ActorType.SYSTEM,
        actor_id=actor.id if actor else None,
        action=action,
        target_type=target_type,
        target_id=target_id,
        occurred_at=clock.now(),
        result=result,
        reason=reason,
        related_post_id=related_post_id,
        scheduled_by=scheduled_by,
        post_creator_id=post_creator_id,
    )
    db.add(row)
    db.flush()
    for item in target_results or []:
        db.add(
            AuditTargetResult(
                audit_log_id=row.id,
                platform_account_id=item["platform_account_id"],
                status=item["status"],
                failure_reason=item.get("failure_reason"),
                skip_reason=item.get("skip_reason"),
            )
        )
    db.flush()
    return row
