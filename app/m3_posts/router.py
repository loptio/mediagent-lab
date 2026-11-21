from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.auth import get_current_user
from app.core.db import get_db
from app.core.models import UserAccount

from . import service
from .schemas import PostCreate, PostOut, PostPage

router = APIRouter(prefix="/posts", tags=["貼文"])


@router.get("", response_model=PostPage, summary="查詢貼文列表")
def list_posts(
    status: str | None = None,
    page: int = 1,
    page_size: int = 20,
    db: Session = Depends(get_db),
    _: UserAccount = Depends(get_current_user),
):
    return service.list_posts(db, status, page, page_size)


@router.post("", response_model=PostOut, status_code=201, summary="建立貼文草稿")
def create_post(
    data: PostCreate,
    db: Session = Depends(get_db),
    user: UserAccount = Depends(get_current_user),
):
    return service.create_post(db, user, data.content)


@router.get("/{post_id}", response_model=PostOut, summary="取得貼文")
def get_post(
    post_id: int,
    db: Session = Depends(get_db),
    _: UserAccount = Depends(get_current_user),
):
    return service.get_post(db, post_id)
