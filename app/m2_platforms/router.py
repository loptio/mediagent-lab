from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.auth import get_current_user
from app.core.db import get_db
from app.core.models import UserAccount

from . import service
from .schemas import PlatformAccountList

router = APIRouter(prefix="/platform-accounts", tags=["平台帳號"])


@router.get("", response_model=PlatformAccountList, summary="查看已連結的平台帳號")
def list_accounts(db: Session = Depends(get_db), _: UserAccount = Depends(get_current_user)):
    return PlatformAccountList(items=service.list_accounts(db))
