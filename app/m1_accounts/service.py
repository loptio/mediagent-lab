"""M1 帳號與安全：登入。

目前只有主線需要的部分；登入失敗鎖定、IP 限流、登入安全事件、換發 Token、
帳號管理（建立、停用、調整角色…）尚未實作。
"""

from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.core import audit, auth
from app.core.config import get_settings
from app.core.enums import AuditAction, TargetType, UserStatus
from app.core.errors import DomainError
from app.core.models import UserAccount

from . import repository


@dataclass(frozen=True)
class LoginResult:
    user: UserAccount
    access_token: str
    refresh_token: str
    expires_in: int


def normalize_email(email: str) -> str:
    """BR-40：移除前後空白並轉為小寫。"""
    return email.strip().lower()


def login(db: Session, email: str, password: str) -> LoginResult:
    user = repository.get_by_email(db, normalize_email(email))
    # NFR-10：帳號不存在、停用、密碼錯誤，一律回傳相同的失敗結果
    if (
        user is None
        or user.status != UserStatus.ACTIVE
        or not auth.verify_password(password, user.password_hash)
    ):
        raise DomainError(401, "LOGIN_FAILED", "Email 或密碼錯誤")

    session, refresh_token = auth.create_session(db, user)
    audit.write(
        db,
        action=AuditAction.LOGIN,
        actor=user,
        target_type=TargetType.USER_ACCOUNT,
        target_id=user.id,
    )
    db.commit()
    return LoginResult(
        user=user,
        access_token=auth.issue_access_token(user.id, session.id),
        refresh_token=refresh_token,
        expires_in=get_settings().access_token_minutes * 60,
    )
