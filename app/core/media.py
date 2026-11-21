"""圖片儲存（architecture §5：MediaStorage 介面）。兩種實作，介面相同，以 MEDIA_STORAGE_BACKEND 切換：

- local：存成 MEDIA_DIR 裡的檔案（本機開發、測試）。
- db：存在 PostgreSQL 的 media_blob 表（正式環境；Neon 免費方案，不需要另外申請付費的物件儲存）。

兩種都由後端在 /media/{key} 提供。Threads、Instagram 由平台主動下載圖片，
所以 MEDIA_BASE_URL 必須是平台連得到的公開 https 網址（例如 https://<服務>.onrender.com/media）。
平台來下載時一定是在發文，服務醒著，免費方案的休眠不影響。
"""

import re
import uuid
from pathlib import Path

from sqlalchemy import delete, select

from .config import get_settings

KEY_PATTERN = re.compile(r"^[0-9a-f]{32}\.jpg$")


class LocalMediaStorage:
    def __init__(self, directory: str, base_url: str) -> None:
        self.directory = Path(directory)
        self.base_url = base_url.rstrip("/")

    def save(self, data: bytes) -> str:
        """存成新檔案，回傳 storage key（隨機名稱，不使用上傳時的檔名）。"""
        self.directory.mkdir(parents=True, exist_ok=True)
        key = f"{uuid.uuid4().hex}.jpg"
        (self.directory / key).write_bytes(data)
        return key

    def path(self, key: str) -> Path | None:
        """只接受系統產生的 key，避免路徑穿越。"""
        if not KEY_PATTERN.fullmatch(key):
            return None
        return self.directory / key

    def read(self, key: str) -> bytes:
        path = self.path(key)
        if path is None:
            raise FileNotFoundError(key)
        return path.read_bytes()

    def delete(self, key: str) -> None:
        path = self.path(key)
        if path is not None:
            path.unlink(missing_ok=True)

    def url(self, key: str) -> str:
        return f"{self.base_url}/{key}"


class DatabaseMediaStorage:
    """圖片內容存在 media_blob 表；每個操作各用一個短交易，和檔案儲存的行為一致。"""

    def __init__(self, base_url: str) -> None:
        self.base_url = base_url.rstrip("/")

    def save(self, data: bytes) -> str:
        from .db import session_scope
        from .models import MediaBlob

        key = f"{uuid.uuid4().hex}.jpg"
        with session_scope() as db:
            db.add(MediaBlob(storage_key=key, data=data))
        return key

    def read(self, key: str) -> bytes:
        from .db import session_scope
        from .models import MediaBlob

        if not KEY_PATTERN.fullmatch(key):
            raise FileNotFoundError(key)
        with session_scope() as db:
            data = db.scalar(select(MediaBlob.data).where(MediaBlob.storage_key == key))
        if data is None:
            raise FileNotFoundError(key)
        return bytes(data)

    def delete(self, key: str) -> None:
        from .db import session_scope
        from .models import MediaBlob

        with session_scope() as db:
            db.execute(delete(MediaBlob).where(MediaBlob.storage_key == key))

    def url(self, key: str) -> str:
        return f"{self.base_url}/{key}"


def get_storage() -> LocalMediaStorage | DatabaseMediaStorage:
    settings = get_settings()
    if settings.media_storage_backend == "db":
        return DatabaseMediaStorage(settings.media_base_url)
    return LocalMediaStorage(settings.media_dir, settings.media_base_url)
