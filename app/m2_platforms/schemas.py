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


class PlatformAccountCreate(BaseModel):
    """以 Webhook 連結 Discord。Threads、Instagram 走 OAuth 流程（尚未實作）。"""

    platform: str
    account_name: str
    webhook_url: str


class OAuthStart(BaseModel):
    """開始平台授權流程。重新連結（帶 platform_account_id）尚未實作。"""

    platform: str
    platform_account_id: int | None = None


class OAuthStarted(BaseModel):
    authorization_url: str
