from datetime import datetime

from pydantic import BaseModel


class PostCreate(BaseModel):
    content: str


class PostUpdate(BaseModel):
    content: str


class ImageOut(BaseModel):
    """原圖與 Instagram 版本（《API 設計》19）。比例已符合時兩者相同，ig_cropped 為 false。"""

    format: str
    size_bytes: int
    width: int
    height: int
    public_url: str
    ig_public_url: str
    ig_width: int
    ig_height: int
    ig_cropped: bool


class PreviewImage(BaseModel):
    url: str
    width: int
    height: int
    variant: str  # original／instagram


class PreviewItem(BaseModel):
    platform_account: "TargetOut"
    text: str
    char_count: int
    char_limit: int
    image: PreviewImage | None
    warnings: list[str]


class PreviewOut(BaseModel):
    items: list[PreviewItem]


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
    image: ImageOut | None
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
