from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.orm import Session

from app.core.auth import get_current_user, require_role
from app.core.config import get_settings
from app.core.db import get_db
from app.core.enums import Role
from app.core.models import UserAccount

from . import service
from .schemas import (
    LoginRequest,
    LoginResponse,
    UserCreate,
    UserDetail,
    UserList,
    UserOut,
    UserStatusUpdate,
)

router = APIRouter(prefix="/auth", tags=["帳號與安全"])

REFRESH_COOKIE = "refresh_token"


@router.post("/login", response_model=LoginResponse, summary="登入")
def login(data: LoginRequest, response: Response, db: Session = Depends(get_db)):
    result = service.login(db, data.email, data.password)
    settings = get_settings()
    # Refresh Token 只放在 HttpOnly Cookie；前後端同源部署，使用 SameSite=Lax（foundation-plan D-06）
    response.set_cookie(
        REFRESH_COOKIE,
        result.refresh_token,
        max_age=settings.session_days * 24 * 3600,
        httponly=True,
        secure=not settings.dev_mode,
        samesite="lax",
        path="/api/v1/auth",
    )
    return LoginResponse(
        access_token=result.access_token,
        expires_in=result.expires_in,
        user=UserOut.model_validate(result.user, from_attributes=True),
    )


@router.get("/me", response_model=UserOut, summary="目前登入的使用者")
def me(user: UserAccount = Depends(get_current_user)):
    return user


@router.post("/logout", status_code=204, summary="登出")
def logout(
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
    user: UserAccount = Depends(get_current_user),
):
    """只讓目前這個登入失效；其他裝置的登入仍然有效。"""
    service.logout(db, user, getattr(request.state, "session_id", None))
    response.delete_cookie(REFRESH_COOKIE, path="/api/v1/auth")
    response.status_code = 204
    return response


users_router = APIRouter(prefix="/users", tags=["幹部帳號"])


@users_router.get("", response_model=UserList, summary="查看幹部帳號")
def list_users(db: Session = Depends(get_db), _: UserAccount = Depends(require_role(Role.ADMIN))):
    return UserList(items=service.list_users(db))


@users_router.post("", response_model=UserDetail, status_code=201, summary="建立幹部帳號")
def create_user(
    data: UserCreate,
    db: Session = Depends(get_db),
    admin: UserAccount = Depends(require_role(Role.ADMIN)),
):
    """Email 會去掉前後空白並轉成小寫；初始密碼至少 8 個字元，只保存雜湊。"""
    return service.create_user(
        db, admin, email=data.email, name=data.name, role=data.role, initial_password=data.initial_password
    )


@users_router.put("/{user_id}/status", response_model=UserDetail, summary="停用、啟用帳號")
def set_status(
    user_id: int,
    data: UserStatusUpdate,
    db: Session = Depends(get_db),
    admin: UserAccount = Depends(require_role(Role.ADMIN)),
):
    """停用後該帳號立即無法登入，手上的登入也全部失效；建立的貼文與已連結的平台帳號都保留。"""
    return service.set_status(db, admin, user_id, data.status)
