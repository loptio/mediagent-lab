from datetime import datetime

from pydantic import BaseModel


class TargetsUpdate(BaseModel):
    platform_account_ids: list[int]


class TargetOut(BaseModel):
    id: int
    platform: str
    account_name: str
    auth_status: str


class TargetsOut(BaseModel):
    post_id: int
    targets: list[TargetOut]


class RecordAccount(BaseModel):
    id: int
    platform: str
    account_name: str
    removed: bool


class PublishRecordOut(BaseModel):
    id: int
    platform_account: RecordAccount
    status: str
    published_at: datetime | None
    platform_post_url: str | None
    failure_reason: str | None
    # 平台原始錯誤訊息：只有管理員的回應才會包含這個欄位
    platform_error_message: str | None = None


class PublishRecordsOut(BaseModel):
    post_id: int
    post_deleted: bool
    post_status: str | None
    items: list[PublishRecordOut]
