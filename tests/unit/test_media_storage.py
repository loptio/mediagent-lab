"""圖片儲存：本機檔案（開發、測試）與 PostgreSQL（正式環境，Neon）兩種實作，介面相同。"""

import pytest
from sqlalchemy import select

from app.core import media, models
from app.core.config import get_settings


def test_database_storage_round_trip(db, monkeypatch):
    monkeypatch.setattr(get_settings(), "media_storage_backend", "db")
    monkeypatch.setattr(get_settings(), "media_base_url", "https://club.onrender.com/media")
    storage = media.get_storage()

    key = storage.save(b"\xff\xd8jpeg\xff\xd9")

    assert storage.read(key) == b"\xff\xd8jpeg\xff\xd9"
    assert storage.url(key) == f"https://club.onrender.com/media/{key}"
    db.expire_all()
    assert db.scalar(select(models.MediaBlob.storage_key)) == key
    storage.delete(key)
    with pytest.raises(FileNotFoundError):
        storage.read(key)


def test_database_storage_rejects_keys_it_did_not_create(monkeypatch):
    monkeypatch.setattr(get_settings(), "media_storage_backend", "db")
    storage = media.get_storage()

    with pytest.raises(FileNotFoundError):
        storage.read("../../etc/passwd")


def test_local_storage_is_the_default(tmp_path, monkeypatch):
    monkeypatch.setattr(get_settings(), "media_dir", str(tmp_path))
    storage = media.get_storage()

    key = storage.save(b"data")

    assert isinstance(storage, media.LocalMediaStorage)
    assert (tmp_path / key).read_bytes() == b"data"


# ---------- S3 相容的物件儲存（正式環境：Neon Object Storage） ----------

BUCKET = "mediagent-images"
PUBLIC_BASE = "https://br-test.storage.c-1.ap-southeast-1.aws.neon.tech/mediagent-images"


@pytest.fixture
def s3(monkeypatch):
    """moto 模擬的 S3；不連任何真實服務。"""
    import boto3
    from moto import mock_aws

    settings = get_settings()
    for name, value in {
        "media_storage_backend": "s3",
        "s3_endpoint_url": "",  # 空白時使用 AWS 預設端點，moto 會攔截
        "s3_region": "us-east-1",
        "s3_bucket": BUCKET,
        "s3_access_key_id": "testing",
        "s3_secret_access_key": "testing",
        "media_base_url": PUBLIC_BASE,
    }.items():
        monkeypatch.setattr(settings, name, value)
    with mock_aws():
        client = boto3.client("s3", region_name="us-east-1")
        client.create_bucket(Bucket=BUCKET)
        yield client


def test_object_storage_round_trip(s3):
    storage = media.get_storage()

    key = storage.save(b"\xff\xd8jpeg\xff\xd9")

    assert storage.read(key) == b"\xff\xd8jpeg\xff\xd9"
    head = s3.head_object(Bucket=BUCKET, Key=key)
    assert head["ContentType"] == "image/jpeg"
    assert "immutable" in head["CacheControl"]
    assert storage.url(key) == f"{PUBLIC_BASE}/{key}"
    storage.delete(key)
    with pytest.raises(FileNotFoundError):
        storage.read(key)


def test_object_storage_client_uses_path_style_and_sigv4(s3):
    """Neon Object Storage 只支援 path-style 與 SigV4。"""
    client = media.get_storage().client

    assert client.meta.config.s3["addressing_style"] == "path"
    assert client.meta.config.signature_version == "s3v4"


def test_object_storage_rejects_keys_it_did_not_create(s3):
    with pytest.raises(FileNotFoundError):
        media.get_storage().read("../secret")
