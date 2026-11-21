from datetime import datetime

from pydantic import BaseModel


class PlatformAccountOut(BaseModel):
    """不含任何憑證；auth_status 是計算後的有效狀態（BR-09）。"""

    id: int
    platform: str
    account_name: str
    auth_status: str
    auth_expires_at: datetime | None


class PlatformAccountList(BaseModel):
    items: list[PlatformAccountOut]
