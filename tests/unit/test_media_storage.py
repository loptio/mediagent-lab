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
