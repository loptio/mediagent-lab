from typing import Literal

from pydantic import BaseModel


class PublishJobCreate(BaseModel):
    # 重試（"retry"）尚未實作
    type: Literal["immediate"]


class JobRecord(BaseModel):
    id: int
    platform_account_id: int
    status: str


class PublishJobAccepted(BaseModel):
    post_id: int
    post_status: str
    records: list[JobRecord]
