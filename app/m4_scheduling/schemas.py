from datetime import datetime

from pydantic import BaseModel


class TargetsUpdate(BaseModel):
    platform_account_ids: list[int]


class ScheduleUpdate(BaseModel):
    """排程時間以台灣時間輸入；沒有時區時視為台灣時間，以 UTC 儲存。"""

    model_config = {"json_schema_extra": {"examples": [{"scheduled_at": "2026-12-01T12:00:00+08:00"}]}}

    scheduled_at: datetime


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


class HistoryActor(BaseModel):
    id: int
    name: str


class HistoryItem(BaseModel):
    publish_record_id: int
    from_status: str | None
    to_status: str
    changed_at: datetime
    actor_type: str
    actor: HistoryActor | None
    reason: str


class HistoryOut(BaseModel):
    post_id: int
    items: list[HistoryItem]


class PublishRecordsOut(BaseModel):
    post_id: int
    post_deleted: bool
    post_status: str | None
    items: list[PublishRecordOut]
