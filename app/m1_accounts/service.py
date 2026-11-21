"""M1 帳號與安全：登入、登出、幹部帳號的查看／建立／停用／啟用。

登入失敗鎖定、IP 限流、登入安全事件、換發 Token、調整角色、解除鎖定、登出所有裝置尚未實作。
"""

from dataclasses import dataclass

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core import audit, auth, clock
from app.core.config import get_settings
from app.core.enums import AuditAction, Role, TargetType, UserStatus
from app.core.errors import DomainError, not_found
from app.core.models import UserAccount

from . import repository
from .schemas import UserDetail

MIN_PASSWORD_LENGTH = 8


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


def logout(db: Session, user: UserAccount, session_id: int | None) -> None:
    """只撤銷目前這個 session；其他裝置的登入不受影響（FR-01、NFR-07）。"""
    if session_id is not None:
        repository.revoke_session(db, session_id, clock.now())
    audit.write(
        db, action=AuditAction.LOGOUT, actor=user, target_type=TargetType.USER_ACCOUNT, target_id=user.id
    )
    db.commit()


# ---------- 幹部帳號（管理員） ----------


def to_detail(user: UserAccount) -> UserDetail:
    now = clock.now()
    return UserDetail(
        id=user.id,
        email=user.email,
        name=user.name,
        role=user.role,
        status=user.status,
        locked_until=user.locked_until,
        is_locked=user.locked_until is not None and user.locked_until > now,
    )


def list_users(db: Session) -> list[UserDetail]:
    """全部帳號（含停用），不分頁（FR-03）。"""
    return [to_detail(user) for user in repository.list_all(db)]


def _email_taken() -> DomainError:
    return DomainError(409, "EMAIL_TAKEN", "這個 Email 已經有帳號了")


def create_user(
    db: Session, admin: UserAccount, *, email: str, name: str, role: str, initial_password: str
) -> UserDetail:
    """建立幹部帳號（FR-02、需求 4.1）。email 已在 schema 標準化。密碼只保存雜湊。"""
    if not initial_password.strip() or len(initial_password) < MIN_PASSWORD_LENGTH:
        raise DomainError(422, "PASSWORD_TOO_SHORT", "初始密碼至少要 8 個字元")
    if repository.get_by_email(db, email) is not None:
        raise _email_taken()

    user = UserAccount(
        email=email, name=name, role=role, password_hash=auth.hash_password(initial_password)
    )
    db.add(user)
    try:
        db.flush()
    except IntegrityError:
        # 檢查之後、寫入之前被別人搶先建立：由資料庫的唯一限制擋下
        db.rollback()
        raise _email_taken() from None
    audit.write(
        db,
        action=AuditAction.USER_CREATE,
        actor=admin,
        target_type=TargetType.USER_ACCOUNT,
        target_id=user.id,
    )
    db.commit()
    return to_detail(user)


def set_status(db: Session, admin: UserAccount, user_id: int, status: str) -> UserDetail:
    """停用或啟用帳號（FR-04、FR-05、BR-19、BR-20、BR-39）。停用時同時撤銷該帳號所有登入。"""
    if status == UserStatus.DISABLED:
        # 先鎖定全部啟用中的管理員，再鎖定目標：兩位管理員同時停用對方時，第二個會看到第一個的結果
        active_admins = repository.lock_active_admins(db)
    target = repository.get_for_update(db, user_id)
    if target is None:
        raise not_found("找不到帳號")

    now = clock.now()
    if status == UserStatus.DISABLED:
        if target.status == UserStatus.DISABLED:
            raise DomainError(409, "USER_ALREADY_DISABLED", "這個帳號已經是停用狀態")
        if target.role == Role.ADMIN and [a.id for a in active_admins] == [target.id]:
            raise DomainError(409, "LAST_ACTIVE_ADMIN", "系統至少要保留一位啟用中的管理員")
        target.status = UserStatus.DISABLED
        repository.revoke_all_sessions(db, target.id, now)
        action = AuditAction.USER_DISABLE
    else:
        if target.status != UserStatus.DISABLED:
            raise DomainError(409, "USER_NOT_DISABLED", "這個帳號不是停用狀態")
        target.status = UserStatus.ACTIVE
        action = AuditAction.USER_ENABLE
    audit.write(db, action=action, actor=admin, target_type=TargetType.USER_ACCOUNT, target_id=target.id)
    db.commit()
    return to_detail(target)
