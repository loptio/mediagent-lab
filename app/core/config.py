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
    # BR-41：連續失敗 5 次鎖定 15 分鐘；BR-42：同一 IP 任意 60 秒內最多 10 次登入嘗試
    login_failures_before_lock: int = 5
    login_lock_minutes: int = 15
    login_attempts_per_minute: int = 10
    # 前面有幾層受信任的反向代理（本機直接連為 0；Render 為 1）；用來從 X-Forwarded-For 取出真正的用戶端 IP
    trusted_proxy_hops: int = 0

    # foundation-plan D-02：單次平台呼叫逾時、單筆發佈總時限、查詢 container 狀態的間隔
    platform_call_timeout_seconds: float = 30
    publish_record_limit_seconds: float = 180
    publish_poll_interval_seconds: float = 5
    # 進入發佈中滿這麼久仍有待發佈紀錄，就由逾時恢復接手（BR-33）
    publish_recovery_minutes: float = 10

    # 排程（foundation-plan D-07）：服務內每分鐘檢查一次；外部定時任務以 X-Cron-Secret 呼叫內部端點
    scheduler_enabled: bool = True
    scheduler_interval_seconds: float = 60
    # 沒有設定時，內部端點一律拒絕
    cron_secret: str = ""

    # 平台授權（OAuth）：Meta 開發者網站上 Threads 使用情境的 App ID 與密鑰
    threads_app_id: str = ""
    threads_app_secret: str = ""
    # Instagram（Facebook 企業版登入）：Meta App 本身的 ID 與密鑰，加上登入設定（configuration）的 ID
    instagram_app_id: str = ""
    instagram_app_secret: str = ""
    instagram_login_config_id: str = ""
    # 平台導回時使用的後端網址（必須與 Meta 後台登記的 redirect URI 相同的來源）
    oauth_redirect_base_url: str = "http://localhost:8000"
    # 簽章 OAuth state 用；沒有設定時沿用 JWT_SECRET
    oauth_state_secret: str = ""
    oauth_state_minutes: int = 10
    # 有前端時，授權完成後導回這個來源的 /platform-accounts；沒有設定時顯示後端內建的結果頁
    frontend_origin: str = ""

    # 圖片：本機存放目錄，以及平台用來讀取圖片的網址前綴（s3 時是 bucket 的公開網址）。
    # Threads、Instagram 由平台主動下載圖片，正式環境必須是公開 https 網址
    # local：存成檔案（本機、測試）；s3：S3 相容的物件儲存（正式環境：Neon Object Storage）；
    # db：存在 PostgreSQL 的 media_blob 表（沒有物件儲存時的備案）
    media_storage_backend: str = "local"
    # 物件儲存（MEDIA_STORAGE_BACKEND=s3）：端點、區域、bucket 與憑證；端點空白時使用 AWS 預設
    s3_endpoint_url: str = ""
    s3_region: str = ""
    s3_bucket: str = ""
    s3_access_key_id: str = ""
    s3_secret_access_key: str = ""
    media_dir: str = "media"
    media_base_url: str = "/media"

    # real：使用真實平台 Adapter；mock：三個平台都用 MockAdapter（測試與離線開發）
    platform_mode: str = "real"
    log_level: str = "INFO"

    @field_validator("database_url")
    @classmethod
    def use_psycopg_driver(cls, value: str) -> str:
        """Neon、Render 給的連線字串是 postgresql:// 或 postgres://；改成 SQLAlchemy 要的 psycopg 3 驅動。"""
        for prefix in ("postgresql://", "postgres://"):
            if value.startswith(prefix):
                return "postgresql+psycopg://" + value[len(prefix):]
        return value

    @field_validator("credential_encryption_keys", mode="before")
    @classmethod
    def split_keys(cls, value: object) -> object:
        if isinstance(value, str):
            return [key.strip() for key in value.split(",") if key.strip()]
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
