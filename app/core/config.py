"""設定（Settings）：全部來自環境變數，密鑰不寫在程式碼中。"""

import os
from functools import lru_cache
from typing import Annotated

from pydantic import field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    # 預設讀取專案根目錄的 .env；測試會把 MEDIAGENT_ENV_FILE 指到不存在的檔案，
    # 讓測試結果不受開發者本機 .env 內容影響
    model_config = SettingsConfigDict(
        env_file=os.environ.get("MEDIAGENT_ENV_FILE", ".env"), extra="ignore"
    )

    database_url: str
    jwt_secret: str
    # 平台憑證加密金鑰（Fernet），逗號分隔；第一把用來加密，其餘只用來解密舊資料
    credential_encryption_keys: Annotated[list[str], NoDecode] = []
    dev_mode: bool = False

    access_token_minutes: int = 15
    session_days: int = 7

    # foundation-plan D-02：單次平台呼叫逾時、單筆發佈總時限、查詢 container 狀態的間隔
    platform_call_timeout_seconds: float = 30
    publish_record_limit_seconds: float = 180
    publish_poll_interval_seconds: float = 5

    # 平台授權（OAuth）：Meta 開發者網站上 Threads 使用情境的 App ID 與密鑰
    threads_app_id: str = ""
    threads_app_secret: str = ""
    # 平台導回時使用的後端網址（必須與 Meta 後台登記的 redirect URI 相同的來源）
    oauth_redirect_base_url: str = "http://localhost:8000"
    # 簽章 OAuth state 用；沒有設定時沿用 JWT_SECRET
    oauth_state_secret: str = ""
    oauth_state_minutes: int = 10
    # 有前端時，授權完成後導回這個來源的 /platform-accounts；沒有設定時顯示後端內建的結果頁
    frontend_origin: str = ""

    # real：使用真實平台 Adapter；mock：三個平台都用 MockAdapter（測試與離線開發）
    platform_mode: str = "real"
    log_level: str = "INFO"

    @field_validator("credential_encryption_keys", mode="before")
    @classmethod
    def split_keys(cls, value: object) -> object:
        if isinstance(value, str):
            return [key.strip() for key in value.split(",") if key.strip()]
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
