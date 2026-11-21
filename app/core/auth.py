"""身分驗證與角色檢查（JWT + session 表）。

每次請求：驗證 JWT → 確認 session 未撤銷、未過期 → 確認帳號啟用 → 角色以資料庫為準。
登出、停用帳號因此可以立即生效（BR-43、NFR-07）。
"""

import hashlib
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta

import jwt
from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pwdlib import PasswordHash
from sqlalchemy.orm import Session

from . import clock
from .config import get_settings
from .db import get_db
from .enums import Role, UserStatus
from .errors import forbidden, unauthenticated
from .models import UserAccount, UserSession

JWT_ALGORITHM = "HS256"
DEV_USER_HEADER = "X-Dev-User"
_ROLE_RANK = {Role.WRITER: 1, Role.PUBLISHER: 2, Role.ADMIN: 3}

_password_hash = PasswordHash.recommended()  # Argon2
_bearer = HTTPBearer(auto_error=False, scheme_name="BearerAuth")


# ---------- 密碼 ----------


def hash_password(password: str) -> str:
    return _password_hash.hash(password)


def verify_password(password: str, hashed: str) -> bool:
    return _password_hash.verify(password, hashed)


# ---------- Access Token 與 session ----------


@dataclass(frozen=True)
class TokenClaims:
    user_id: int
    session_id: int
    expires_at: datetime


def issue_access_token(user_id: int, session_id: int) -> str:
    settings = get_settings()
    expires_at = clock.now() + timedelta(minutes=settings.access_token_minutes)
    payload = {"sub": str(user_id), "sid": session_id, "exp": int(expires_at.timestamp())}
    return jwt.encode(payload, settings.jwt_secret, algorithm=JWT_ALGORITHM)


def decode_access_token(token: str) -> TokenClaims:
    try:
        # 到期時間以系統時鐘（clock.now()）判斷，不用函式庫內建的系統時間
        payload = jwt.decode(
            token,
            get_settings().jwt_secret,
            algorithms=[JWT_ALGORITHM],
            options={"verify_exp": False, "require": ["sub", "sid", "exp"]},
        )
        claims = TokenClaims(
            user_id=int(payload["sub"]),
            session_id=int(payload["sid"]),
            expires_at=datetime.fromtimestamp(int(payload["exp"]), tz=clock.now().tzinfo),
        )
    except (jwt.InvalidTokenError, ValueError, TypeError) as exc:
        raise unauthenticated() from exc
    if claims.expires_at <= clock.now():
        raise unauthenticated()
    return claims


def hash_refresh_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def create_session(db: Session, user: UserAccount) -> tuple[UserSession, str]:
    """建立登入工作階段，回傳（session, Refresh Token 原文）。資料庫只保存雜湊。"""
    refresh_token = secrets.token_urlsafe(48)
    now = clock.now()
    session = UserSession(
        user_account_id=user.id,
        refresh_token_hash=hash_refresh_token(refresh_token),
        created_at=now,
        last_used_at=now,
        expires_at=now + timedelta(days=get_settings().session_days),
    )
    db.add(session)
    db.flush()
    return session, refresh_token


# ---------- 角色 ----------


def has_role(role: str, min_role: Role) -> bool:
    return _ROLE_RANK[Role(role)] >= _ROLE_RANK[min_role]


def ensure_owner_or_role(user: UserAccount, owner_id: int, min_role: Role) -> None:
    """建立者本人，或角色達到 min_role 才可操作（BR-18：撰稿者只能操作自己的貼文）。"""
    if user.id != owner_id and not has_role(user.role, min_role):
        raise forbidden()


# ---------- FastAPI 依賴 ----------


def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: Session = Depends(get_db),
) -> UserAccount:
    dev_user_id = request.headers.get(DEV_USER_HEADER)
    if get_settings().dev_mode and dev_user_id and dev_user_id.isdigit():
        user = db.get(UserAccount, int(dev_user_id))
    else:
        if credentials is None:
            raise unauthenticated()
        claims = decode_access_token(credentials.credentials)
        session = db.get(UserSession, claims.session_id)
        if (
            session is None
            or session.user_account_id != claims.user_id
            or session.revoked_at is not None
            or session.expires_at <= clock.now()
        ):
            raise unauthenticated()
        request.state.session_id = session.id
        user = db.get(UserAccount, claims.user_id)

    if user is None or user.status != UserStatus.ACTIVE:
        raise unauthenticated()
    return user


def require_role(min_role: Role):
    def dependency(user: UserAccount = Depends(get_current_user)) -> UserAccount:
        if not has_role(user.role, min_role):
            raise forbidden()
        return user

    return dependency
