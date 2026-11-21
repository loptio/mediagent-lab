from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session

from app.core.auth import get_current_user
from app.core.config import get_settings
from app.core.db import get_db
from app.core.models import UserAccount

from . import service
from .schemas import LoginRequest, LoginResponse, UserOut

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
