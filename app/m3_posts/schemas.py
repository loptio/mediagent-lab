from datetime import datetime

from pydantic import BaseModel


class PostCreate(BaseModel):
    content: str


class PostUpdate(BaseModel):
    content: str


class UserRef(BaseModel):
    id: int
    name: str


class TargetOut(BaseModel):
    id: int
    platform: str
    account_name: str
    auth_status: str


class PostOut(BaseModel):
    id: int
    content: str
    status: str
    scheduled_at: datetime | None
    scheduled_by: int | None
    creator: UserRef
    created_at: datetime
    # 圖片功能尚未實作，目前一律為 null
    image: None = None
    targets: list[TargetOut]


class PostListItem(BaseModel):
    id: int
    content: str
    status: str
    scheduled_at: datetime | None
    created_at: datetime
    creator: UserRef
    has_image: bool = False
    targets: list[TargetOut]


class PostPage(BaseModel):
    items: list[PostListItem]
    page: int
    page_size: int
    total: int
    total_pages: int
    has_prev: bool
    has_next: bool
