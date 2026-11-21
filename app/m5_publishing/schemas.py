from typing import Literal

from pydantic import BaseModel


class PublishJobCreate(BaseModel):
    """immediate：立即發佈草稿或已排程貼文；retry：重試部分失敗或全部失敗的貼文。"""

    model_config = {"json_schema_extra": {"examples": [{"type": "immediate"}, {"type": "retry"}]}}

    type: Literal["immediate", "retry"]


class JobRecord(BaseModel):
    id: int
    platform_account_id: int
    status: str


class PublishJobAccepted(BaseModel):
    post_id: int
    post_status: str
    records: list[JobRecord]
