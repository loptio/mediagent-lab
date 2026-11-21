"""M2 平台帳號與串接。"""

from sqlalchemy.orm import Session

from app.core import clock
from app.core.models import PlatformAccount
from app.core.platforms import effective_auth_status

from . import repository
from .schemas import PlatformAccountOut


def to_out(account: PlatformAccount) -> PlatformAccountOut:
    return PlatformAccountOut(
        id=account.id,
        platform=account.platform,
        account_name=account.account_name,
        auth_status=effective_auth_status(account, clock.now()),
        auth_expires_at=account.auth_expires_at,
    )


def list_accounts(db: Session) -> list[PlatformAccountOut]:
    return [to_out(account) for account in repository.list_active(db)]
