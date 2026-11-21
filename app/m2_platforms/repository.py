from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import clock
from app.core.models import PlatformAccount, PlatformAuthEvent


def list_active(db: Session) -> list[PlatformAccount]:
    stmt = select(PlatformAccount).where(PlatformAccount.removed.is_(False)).order_by(PlatformAccount.id)
    return list(db.scalars(stmt))


def name_taken(db: Session, platform: str, account_name: str) -> bool:
    """未移除的平台帳號中，「平台＋帳號名稱」不可重複（需求 4.2）。"""
    stmt = select(PlatformAccount.id).where(
        PlatformAccount.platform == platform,
        PlatformAccount.account_name == account_name,
        PlatformAccount.removed.is_(False),
    )
    return db.scalar(stmt) is not None


def create(
    db: Session,
    *,
    platform: str,
    account_name: str,
    credential_encrypted: bytes,
    credential_key_version: int,
    linked_by: int,
) -> PlatformAccount:
    account = PlatformAccount(
        platform=platform,
        account_name=account_name,
        credential_encrypted=credential_encrypted,
        credential_key_version=credential_key_version,
        linked_by=linked_by,
    )
    db.add(account)
    db.flush()
    return account


def add_auth_event(
    db: Session,
    *,
    event_type: str,
    platform: str,
    account_name: str | None,
    failure_reason: str,
    actor_id: int,
    platform_account_id: int | None = None,
) -> None:
    """平台授權事件：不得包含任何憑證、Token 或 Webhook 網址。"""
    db.add(
        PlatformAuthEvent(
            event_type=event_type,
            platform=platform,
            account_name=account_name,
            failure_reason=failure_reason,
            platform_account_id=platform_account_id,
            actor_id=actor_id,
            occurred_at=clock.now(),
        )
    )
    db.flush()
