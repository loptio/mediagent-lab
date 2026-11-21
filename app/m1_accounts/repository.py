from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core.enums import Role, UserStatus
from app.core.models import LoginSecurityEvent, UserAccount, UserSession


def get_by_email(db: Session, email: str) -> UserAccount | None:
    return db.scalar(select(UserAccount).where(UserAccount.email == email))


def get_by_email_for_update(db: Session, email: str) -> UserAccount | None:
    """登入時鎖定帳號：同時多次輸錯密碼時，失敗次數才不會少算。"""
    stmt = select(UserAccount).where(UserAccount.email == email).with_for_update(key_share=True)
    return db.scalar(stmt)


def get_session_by_refresh_hash(db: Session, token_hash: str) -> UserSession | None:
    stmt = select(UserSession).where(UserSession.refresh_token_hash == token_hash).with_for_update()
    return db.scalar(stmt)


def add_login_failure(
    db: Session, *, reason: str, email: str, user_id: int | None, now: datetime
) -> None:
    """登入安全事件只記錄原因與嘗試的 Email，不保存密碼。"""
    db.add(
        LoginSecurityEvent(
            failure_reason=reason, attempted_email=email, user_account_id=user_id, occurred_at=now
        )
    )
    db.flush()


def list_all(db: Session) -> list[UserAccount]:
    return list(db.scalars(select(UserAccount).order_by(UserAccount.id)))


# 鎖定帳號一律用 FOR NO KEY UPDATE（key_share=True）：其他交易寫稽核時，外鍵會對操作者那一列取
# FOR KEY SHARE；一般的 FOR UPDATE 會擋住它，啟用與停用同時進行時就會互相卡死。


def get_for_update(db: Session, user_id: int) -> UserAccount | None:
    stmt = select(UserAccount).where(UserAccount.id == user_id).with_for_update(key_share=True)
    return db.scalar(stmt)


def lock_active_admins(db: Session) -> list[UserAccount]:
    """鎖定全部啟用中的管理員（依 id 排序）；兩位管理員同時停用對方時，第二個會看到第一個的結果。"""
    stmt = (
        select(UserAccount)
        .where(UserAccount.role == Role.ADMIN, UserAccount.status == UserStatus.ACTIVE)
        .order_by(UserAccount.id)
        .with_for_update(key_share=True)
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
