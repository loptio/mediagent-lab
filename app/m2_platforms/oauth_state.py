"""OAuth state：後端簽章的短效 Token，用來確認平台導回的請求確實是某位管理員發起的。

回呼端點沒有登入標頭（是平台把瀏覽器導回來的），身分只能靠這個 state 確認，
所以必須簽章、必須短效，內容只放管理員 ID、平台，以及重新連結時的平台帳號 ID。
"""

import secrets
from dataclasses import dataclass
from datetime import timedelta

import jwt

from app.core import clock
from app.core.config import get_settings
from app.core.platforms import OAuthFailed

_ALGORITHM = "HS256"
_PURPOSE = "oauth-link"


@dataclass(frozen=True)
class OAuthState:
    admin_id: int
    platform: str
    platform_account_id: int | None = None  # 有值時是重新連結這個平台帳號


def _secret() -> str:
    settings = get_settings()
    return settings.oauth_state_secret or settings.jwt_secret


def issue_state(admin_id: int, platform: str, platform_account_id: int | None = None) -> str:
    expires_at = clock.now() + timedelta(minutes=get_settings().oauth_state_minutes)
    payload = {
        "sub": str(admin_id),
        "platform": str(platform),
        "account": platform_account_id,
        "purpose": _PURPOSE,
        "nonce": secrets.token_urlsafe(8),
        "exp": int(expires_at.timestamp()),
    }
    return jwt.encode(payload, _secret(), algorithm=_ALGORITHM)


def read_state(token: str) -> OAuthState:
    try:
        payload = jwt.decode(
            token,
            _secret(),
            algorithms=[_ALGORITHM],
            options={"verify_exp": False, "require": ["sub", "platform", "exp"]},
        )
        if payload.get("purpose") != _PURPOSE:
            raise OAuthFailed("state was not issued for linking")
        account = payload.get("account")
        state = OAuthState(
            admin_id=int(payload["sub"]),
            platform=str(payload["platform"]),
            platform_account_id=int(account) if account is not None else None,
        )
        expires_at = int(payload["exp"])
    except (jwt.InvalidTokenError, ValueError, TypeError) as exc:
        raise OAuthFailed("state is invalid") from exc
    # 到期時間以系統時鐘判斷
    if expires_at <= clock.now().timestamp():
        raise OAuthFailed("state has expired")
    return state
