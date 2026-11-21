from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.auth import get_current_user, require_role
from app.core.db import get_db
from app.core.enums import Role
from app.core.models import UserAccount

from . import service
from .schemas import PlatformAccountCreate, PlatformAccountList, PlatformAccountOut

router = APIRouter(prefix="/platform-accounts", tags=["平台帳號"])


@router.get("", response_model=PlatformAccountList, summary="查看已連結的平台帳號")
def list_accounts(db: Session = Depends(get_db), _: UserAccount = Depends(get_current_user)):
    return PlatformAccountList(items=service.list_accounts(db))


@router.post(
    "",
    response_model=PlatformAccountOut,
    status_code=201,
    summary="連結平台帳號（Discord Webhook）",
)
def link_account(
    data: PlatformAccountCreate,
    db: Session = Depends(get_db),
    admin: UserAccount = Depends(require_role(Role.ADMIN)),
):
    """Webhook 網址等同密碼：只會加密保存，不會出現在任何回應中。"""
    return service.link_webhook_account(db, admin, data.platform, data.account_name, data.webhook_url)
