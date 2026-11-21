"""M1 帳號與安全：登入（含鎖定、IP 限流、登入安全事件）、換發 Token、登出、登出所有裝置，
以及幹部帳號的查看／建立／調整角色／停用／啟用／解除鎖定。
"""

from dataclasses import dataclass
from datetime import timedelta
from functools import cache

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core import audit, auth, clock
from app.core.config import get_settings
from app.core.enums import AuditAction, LoginFailureReason, Role, TargetType, UserStatus
from app.core.errors import DomainError, not_found, unauthenticated
from app.core.models import UserAccount

from . import rate_limit, repository
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


@cache
def _dummy_hash() -> str:
    """帳號不存在時也做一次同樣成本的密碼比對，回應時間不會透露帳號是否存在。"""
    return auth.hash_password("not-a-real-password-for-timing")


def _login_failed(db: Session, reason: LoginFailureReason, email: str, user: UserAccount | None):
    """記錄登入安全事件後回傳一律相同的失敗（NFR-10）；登入失敗不寫一般稽核。"""
    repository.add_login_failure(
        db, reason=reason, email=email, user_id=user.id if user else None, now=clock.now()
    )
    db.commit()
    return DomainError(401, "LOGIN_FAILED", "Email 或密碼錯誤")


def login(db: Session, email: str, password: str, ip: str) -> LoginResult:
    settings = get_settings()
    now = clock.now()
    retry_after = rate_limit.limiter.attempt(ip, now, settings.login_attempts_per_minute)
    if retry_after is not None:
        raise DomainError(
            429,
            "TOO_MANY_LOGIN_ATTEMPTS",
            "登入嘗試次數過多，請稍後再試",
            headers={"Retry-After": str(retry_after)},
        )

    email = normalize_email(email)
    user = repository.get_by_email_for_update(db, email)
    if user is None:
        auth.verify_password(password, _dummy_hash())
        raise _login_failed(db, LoginFailureReason.ACCOUNT_NOT_FOUND, email, None)
    if user.status != UserStatus.ACTIVE:
        raise _login_failed(db, LoginFailureReason.ACCOUNT_DISABLED, email, user)
    if user.locked_until is not None and now < user.locked_until:
        raise _login_failed(db, LoginFailureReason.ACCOUNT_LOCKED, email, user)  # 到期那一刻即解除
    if not auth.verify_password(password, user.password_hash):
        user.failed_login_count += 1
        if user.failed_login_count >= settings.login_failures_before_lock:
            user.locked_until = now + timedelta(minutes=settings.login_lock_minutes)  # BR-41
        raise _login_failed(db, LoginFailureReason.WRONG_PASSWORD, email, user)

    user.failed_login_count = 0
    user.locked_until = None
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


def refresh(db: Session, refresh_token: str | None) -> tuple[str, int]:
    """以 Refresh Token 換發新的 Access Token（同一個 session）。回傳（access_token, expires_in）。"""
    if not refresh_token:
        raise unauthenticated()
    session = repository.get_session_by_refresh_hash(db, auth.hash_refresh_token(refresh_token))
    now = clock.now()
    if session is None or session.revoked_at is not None or session.expires_at <= now:
        raise unauthenticated()
    user = db.get(UserAccount, session.user_account_id)
    if user is None or user.status != UserStatus.ACTIVE:
        raise unauthenticated()
    session.last_used_at = now
    db.commit()
    return auth.issue_access_token(user.id, session.id), get_settings().access_token_minutes * 60


def logout_all(db: Session, user: UserAccount) -> None:
    """撤銷這個使用者全部的登入（BR-43）；其他使用者不受影響。"""
    repository.revoke_all_sessions(db, user.id, clock.now())
    audit.write(
        db, action=AuditAction.LOGOUT_ALL, actor=user, target_type=TargetType.USER_ACCOUNT, target_id=user.id
    )
    db.commit()


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
        if target.role == Role.ADMIN and _is_last_active_admin(target, active_admins):
            raise _last_active_admin()
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


def _is_last_active_admin(target: UserAccount, active_admins: list[UserAccount]) -> bool:
    return not any(admin.id != target.id for admin in active_admins)


def _last_active_admin() -> DomainError:
    return DomainError(409, "LAST_ACTIVE_ADMIN", "系統至少要保留一位啟用中的管理員")


def change_role(db: Session, admin: UserAccount, user_id: int, role: str) -> UserDetail:
    """調整角色（FR-04、BR-19）：立即生效；停用的帳號也可以調整，帳號維持停用。"""
    active_admins = repository.lock_active_admins(db)  # 與停用相同的鎖定順序：先管理員、再目標
    target = repository.get_for_update(db, user_id)
    if target is None:
        raise not_found("找不到帳號")
    if target.role == role:
        return to_detail(target)  # 沒有改變：不寫稽核
    if (
        target.role == Role.ADMIN
        and target.status == UserStatus.ACTIVE
        and _is_last_active_admin(target, active_admins)
    ):
        raise _last_active_admin()

    target.role = role
    audit.write(
        db,
        action=AuditAction.USER_ROLE_CHANGE,
        actor=admin,
        target_type=TargetType.USER_ACCOUNT,
        target_id=target.id,
    )
    db.commit()
    return to_detail(target)


def unlock(db: Session, admin: UserAccount, user_id: int) -> UserDetail:
    """解除鎖定（FR-26、BR-39）：清除鎖定到期時間並歸零失敗次數，不改變啟用或停用狀態。"""
    target = repository.get_for_update(db, user_id)
    if target is None:
        raise not_found("找不到帳號")
    if target.locked_until is None or target.locked_until <= clock.now():
        raise DomainError(409, "USER_NOT_LOCKED", "這個帳號目前沒有被鎖定")
    target.locked_until = None
    target.failed_login_count = 0
    audit.write(
        db,
        action=AuditAction.USER_UNLOCK,
        actor=admin,
        target_type=TargetType.USER_ACCOUNT,
        target_id=target.id,
    )
    db.commit()
    return to_detail(target)
