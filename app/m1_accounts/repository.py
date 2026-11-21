from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core.enums import Role, UserStatus
from app.core.models import UserAccount, UserSession


def get_by_email(db: Session, email: str) -> UserAccount | None:
    return db.scalar(select(UserAccount).where(UserAccount.email == email))


def list_all(db: Session) -> list[UserAccount]:
    return list(db.scalars(select(UserAccount).order_by(UserAccount.id)))


def get_for_update(db: Session, user_id: int) -> UserAccount | None:
    return db.scalar(select(UserAccount).where(UserAccount.id == user_id).with_for_update())


def lock_active_admins(db: Session) -> list[UserAccount]:
    """鎖定全部啟用中的管理員（依 id 排序，鎖定順序固定，兩個請求不會互相卡死）。"""
    stmt = (
        select(UserAccount)
        .where(UserAccount.role == Role.ADMIN, UserAccount.status == UserStatus.ACTIVE)
        .order_by(UserAccount.id)
        .with_for_update()
    )
    return list(db.scalars(stmt))


def revoke_session(db: Session, session_id: int, now: datetime) -> None:
    session = db.get(UserSession, session_id)
    if session is not None and session.revoked_at is None:
        session.revoked_at = now
        db.flush()


def revoke_all_sessions(db: Session, user_id: int, now: datetime) -> None:
    db.execute(
        update(UserSession)
        .where(UserSession.user_account_id == user_id, UserSession.revoked_at.is_(None))
        .values(revoked_at=now)
    )
