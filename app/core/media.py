"""圖片儲存（architecture §5：MediaStorage 介面與 LocalMediaStorage）。

本機開發把檔案放在 MEDIA_DIR，由後端在 /media/{key} 提供。正式環境要讓 Threads、Instagram 讀得到圖片，
MEDIA_BASE_URL 必須是平台連得到的公開網址（例如物件儲存的網域）；換成物件儲存時只需要換掉這個類別。
"""

import re
import uuid
from pathlib import Path

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


def get_storage() -> LocalMediaStorage:
    settings = get_settings()
    return LocalMediaStorage(settings.media_dir, settings.media_base_url)
