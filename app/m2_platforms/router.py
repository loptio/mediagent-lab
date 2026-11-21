from fastapi import APIRouter, Depends
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.core.auth import get_current_user, require_role
from app.core.db import get_db
from app.core.enums import Role
from app.core.models import UserAccount

from . import service
from .schemas import (
    OAuthStart,
    OAuthStarted,
    PlatformAccountCreate,
    PlatformAccountList,
    PlatformAccountOut,
)

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


@router.post(
    "/oauth-authorizations",
    response_model=OAuthStarted,
    summary="開始平台授權流程（Threads）",
)
def start_oauth(
    data: OAuthStart,
    db: Session = Depends(get_db),
    admin: UserAccount = Depends(require_role(Role.ADMIN)),
):
    """回傳平台的授權網址：用瀏覽器打開它，在平台上同意後會自動導回並完成連結。"""
    url = service.start_oauth(db, admin, data.platform, data.platform_account_id)
    return OAuthStarted(authorization_url=url)


@router.get("/oauth/callback", include_in_schema=False)
def oauth_callback(
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    db: Session = Depends(get_db),
):
    """平台把瀏覽器導回這裡（不需要登入標頭，身分由簽章的 state 確認）。"""
    result = service.complete_oauth(db, code=code, state=state, error=error)
    return RedirectResponse(service.oauth_result_url(result), status_code=302)


_RESULT_MESSAGES = {
    service.RESULT_LINKED: ("連結成功", "平台帳號已經連結，可以關閉這個分頁。"),
    service.RESULT_AUTH_FAILED: ("授權失敗", "沒有完成平台授權，帳號沒有被連結。請回到系統重新操作一次。"),
    service.RESULT_UNAVAILABLE: ("暫時無法驗證", "目前連不上平台，帳號沒有被連結。請稍後再試一次。"),
    service.RESULT_NAME_TAKEN: ("帳號已經連結過", "系統中已有相同名稱的平台帳號，沒有重複建立。"),
}


@router.get("/oauth/result", response_class=HTMLResponse, include_in_schema=False)
def oauth_result(result: str = ""):
    """前端完成前的暫時結果頁；只顯示固定文字，不把網址上的內容原樣放進頁面。"""
    title, message = _RESULT_MESSAGES.get(result, ("無法判斷結果", "請回到系統確認平台帳號是否已連結。"))
    return HTMLResponse(
        "<!doctype html><html lang=\"zh-Hant\"><head><meta charset=\"utf-8\">"
        f"<title>{title}</title></head>"
        "<body style=\"font-family: sans-serif; max-width: 32rem; margin: 4rem auto;\">"
        f"<h1>{title}</h1><p>{message}</p></body></html>"
    )
