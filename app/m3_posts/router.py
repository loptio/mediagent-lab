from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session

from app.core.auth import get_current_user
from app.core.db import get_db
from app.core.models import UserAccount

from . import service
from .schemas import PostCreate, PostOut, PostPage, PostUpdate

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


@router.patch("/{post_id}", response_model=PostOut, summary="修改貼文")
def update_post(
    post_id: int,
    data: PostUpdate,
    db: Session = Depends(get_db),
    user: UserAccount = Depends(get_current_user),
):
    """只有草稿與已排程的貼文可以修改；撰稿者只能修改自己的貼文。已排程貼文修改後維持原排程。"""
    return service.update_post(db, user, post_id, data.content)


@router.delete("/{post_id}", status_code=204, summary="刪除貼文")
def delete_post(
    post_id: int,
    db: Session = Depends(get_db),
    user: UserAccount = Depends(get_current_user),
):
    """刪除後不再出現在列表，但仍可用原 ID 查看發佈結果；已排程的排程一併取消。"""
    service.delete_post(db, user, post_id)
    return Response(status_code=204)
