from fastapi import APIRouter, Depends, File, Response, UploadFile
from sqlalchemy.orm import Session

from app.core.auth import get_current_user
from app.core.db import get_db
from app.core.models import UserAccount

from . import service
from .schemas import ImageOut, PostCreate, PostOut, PostPage, PostUpdate, PreviewOut

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


@router.post("/{post_id}/copies", response_model=PostOut, status_code=201, summary="複製為新草稿")
def copy_post(
    post_id: int,
    db: Session = Depends(get_db),
    user: UserAccount = Depends(get_current_user),
):
    """任何狀態的貼文都可以複製；新草稿沒有目標平台帳號，需要重新選擇。"""
    return service.copy_post(db, user, post_id)


@router.get("/{post_id}/preview", response_model=PreviewOut, summary="預覽貼文")
def preview(
    post_id: int,
    db: Session = Depends(get_db),
    _: UserAccount = Depends(get_current_user),
):
    """各目標平台的文字、字數與上限；超過上限或授權失效會出現在 warnings。"""
    return service.preview(db, post_id)


@router.post("/{post_id}/image", response_model=ImageOut, status_code=201, summary="附加圖片")
def attach_image(
    post_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: UserAccount = Depends(get_current_user),
):
    """一則貼文一張 JPEG，最多 8,000,000 位元組。比例超出 4:5～1.91:1 時自動從中間裁出 Instagram 版本。"""
    # 多讀 1 個位元組就知道是否超過上限，不必把超大檔案整個讀進記憶體
    data = file.file.read(service.MAX_IMAGE_BYTES + 1)
    return service.attach_image(db, user, post_id, data)


@router.delete("/{post_id}/image", status_code=204, summary="移除圖片")
def remove_image(
    post_id: int,
    db: Session = Depends(get_db),
    user: UserAccount = Depends(get_current_user),
):
    """目標含 Instagram 時不能移除圖片，需先取消選擇 Instagram。"""
    service.remove_image(db, user, post_id)
    return Response(status_code=204)
