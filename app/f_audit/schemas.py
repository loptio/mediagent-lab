from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field


class Person(BaseModel):
    id: int
    email: str
    name: str


class Target(BaseModel):
    type: str
    id: int


class TargetResult(BaseModel):
    platform_account_id: int
    status: str
    failure_reason: str | None
    skip_reason: str | None


class AuditItem(BaseModel):
    kind: Literal["audit"] = "audit"
    id: int
    event_seq: int
    occurred_at: datetime
    actor_type: str
    actor: Person | None
    action: str
    target: Target
    # 只放有值的欄位：reason、related_post_id、scheduled_by、post_creator_id、result
    details: dict[str, Any]
    target_results: list[TargetResult]


class LoginSecurityItem(BaseModel):
    kind: Literal["login_security"] = "login_security"
    id: int
    event_seq: int
    occurred_at: datetime
    event_type: str
    failure_reason: str
    attempted_email: str
    account: Person | None  # 帳號不存在時為 null


class PlatformAuthItem(BaseModel):
    kind: Literal["platform_auth"] = "platform_auth"
    id: int
    event_seq: int
    occurred_at: datetime
    actor_type: Literal["user"] = "user"
    actor: Person
    event_type: str
    platform: str
    account_name: str | None
    platform_account_id: int | None
    failure_reason: str


EventItem = Annotated[AuditItem | LoginSecurityItem | PlatformAuthItem, Field(discriminator="kind")]


class EventPage(BaseModel):
    items: list[EventItem]
    page: int
    page_size: int
    total: int
    total_pages: int
    has_prev: bool
    has_next: bool
