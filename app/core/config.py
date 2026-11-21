"""設定（Settings）：全部來自環境變數，密鑰不寫在程式碼中。"""

from functools import lru_cache
from typing import Annotated

from pydantic import field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

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
