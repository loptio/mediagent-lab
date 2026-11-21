"""圖片儲存（architecture §5：MediaStorage 介面）。實作的介面相同，以 MEDIA_STORAGE_BACKEND 切換：

- local：存成 MEDIA_DIR 裡的檔案（本機開發、測試），由後端 /media/{key} 提供。
- s3：S3 相容的物件儲存（正式環境：Neon Object Storage，bucket 設為公開讀取）。
  平台直接從 bucket 的公開網址下載，MEDIA_BASE_URL 設為 bucket 的公開網址前綴。
- db：存在 PostgreSQL 的 media_blob 表，由後端 /media/{key} 提供（沒有物件儲存時的備案）。

Threads、Instagram 由平台主動下載圖片，所以圖片網址必須是平台連得到的公開 https 網址。
"""

import re
import uuid
from functools import lru_cache
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


CACHE_CONTROL = "public, max-age=31536000, immutable"  # 換圖會產生新的 key，內容永遠不變


@lru_cache(maxsize=4)
def _s3_client(endpoint_url: str, region: str, access_key_id: str, secret_access_key: str):
    import boto3
    from botocore.config import Config

    return boto3.client(
        "s3",
        endpoint_url=endpoint_url or None,
        region_name=region or None,
        aws_access_key_id=access_key_id or None,
        aws_secret_access_key=secret_access_key or None,
        config=Config(
            signature_version="s3v4",  # Neon Object Storage 只支援 SigV4
            s3={"addressing_style": "path"},  # 也只支援 path-style
            retries={"max_attempts": 5, "mode": "standard"},  # 503 SlowDown 時退避重試
            connect_timeout=10,
            read_timeout=30,
        ),
    )


class S3MediaStorage:
    """S3 相容的物件儲存（Neon Object Storage）。bucket 是公開讀取，網址直接給平台下載。"""

    def __init__(self, bucket: str, base_url: str, client) -> None:
        self.bucket = bucket
        self.base_url = base_url.rstrip("/")
        self.client = client

    def save(self, data: bytes) -> str:
        key = f"{uuid.uuid4().hex}.jpg"
        self.client.put_object(
            Bucket=self.bucket, Key=key, Body=data, ContentType="image/jpeg", CacheControl=CACHE_CONTROL
        )
        return key

    def read(self, key: str) -> bytes:
        from botocore.exceptions import ClientError

        if not KEY_PATTERN.fullmatch(key):
            raise FileNotFoundError(key)
        try:
            return self.client.get_object(Bucket=self.bucket, Key=key)["Body"].read()
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") in ("NoSuchKey", "404"):
                raise FileNotFoundError(key) from None
            raise

    def delete(self, key: str) -> None:
        if KEY_PATTERN.fullmatch(key):
            self.client.delete_object(Bucket=self.bucket, Key=key)

    def url(self, key: str) -> str:
        return f"{self.base_url}/{key}"


def get_storage() -> LocalMediaStorage | DatabaseMediaStorage | S3MediaStorage:
    settings = get_settings()
    if settings.media_storage_backend == "s3":
        client = _s3_client(
            settings.s3_endpoint_url,
            settings.s3_region,
            settings.s3_access_key_id,
            settings.s3_secret_access_key,
        )
        return S3MediaStorage(settings.s3_bucket, settings.media_base_url, client)
    if settings.media_storage_backend == "db":
        return DatabaseMediaStorage(settings.media_base_url)
    return LocalMediaStorage(settings.media_dir, settings.media_base_url)
