"""附加與移除圖片、Instagram 必須附圖、圖片隨發佈送出（FR-11、BR-03～BR-06、4.3.1）。"""

import io

import pytest
from PIL import Image
from sqlalchemy import select

from app.core import models
from app.core.config import get_settings
from app.core.enums import Platform, PostStatus
from tests.api.helpers import API, create_post_with_targets, login, publish, records_by_account, seed_club

MAX_BYTES = 8_000_000


@pytest.fixture(autouse=True)
def media_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(get_settings(), "media_dir", str(tmp_path))
    monkeypatch.setattr(get_settings(), "media_base_url", "https://media.test/media")
    return tmp_path


def served(client, url):
    """圖片網址的最後一段是 storage key，由後端的 /media/{key} 提供。"""
    return client.get(f"/media/{url.rsplit('/', 1)[1]}")


def jpeg(width=1080, height=1920, fmt="JPEG", size=None) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (width, height), (10, 120, 200)).save(buffer, format=fmt)
    data = buffer.getvalue()
    if size is not None:
        assert len(data) <= size
        data += b"\0" * (size - len(data))  # JPEG 結束標記之後的資料不影響讀取
    return data


def upload(client, headers, post_id, data=None, filename="poster.jpg"):
    files = {"file": (filename, data if data is not None else jpeg(), "image/jpeg")}
    return client.post(f"{API}/posts/{post_id}/image", files=files, headers=headers)


def draft(client, headers, account_ids=()):
    return create_post_with_targets(client, headers, list(account_ids), content="社課公告", image=False)


def test_upload_creates_original_and_instagram_version(client, db, media_dir):
    _, accounts = seed_club(db)
    headers = login(client, "pr@club.tw")
    post_id = draft(client, headers, [accounts["discord"].id])

    response = upload(client, headers, post_id, jpeg(1080, 1920))

    assert response.status_code == 201, response.text
    image = response.json()
    assert (image["format"], image["width"], image["height"]) == ("jpeg", 1080, 1920)
    assert (image["ig_width"], image["ig_height"], image["ig_cropped"]) == (1080, 1350, True)
    assert image["public_url"] != image["ig_public_url"]
    assert client.get(f"{API}/posts/{post_id}", headers=headers).json()["image"] == image
    listed = client.get(f"{API}/posts", headers=headers).json()["items"]
    assert [item["has_image"] for item in listed] == [True]
    assert len(list(media_dir.rglob("*.jpg"))) == 2
    response = served(client, image["ig_public_url"])
    assert response.status_code == 200 and Image.open(io.BytesIO(response.content)).size == (1080, 1350)


def test_image_within_instagram_ratio_is_not_cropped(client, db, media_dir):
    _, accounts = seed_club(db)
    headers = login(client, "pr@club.tw")
    post_id = draft(client, headers)

    image = upload(client, headers, post_id, jpeg(1080, 1080)).json()

    assert (image["ig_cropped"], image["ig_public_url"]) == (False, image["public_url"])
    assert len(list(media_dir.rglob("*.jpg"))) == 1


@pytest.mark.parametrize(
    ("data", "status", "code"),
    [
        (jpeg(100, 100, fmt="PNG"), 422, "IMAGE_FORMAT_INVALID"),
        (jpeg(100, 100, size=MAX_BYTES + 1), 422, "IMAGE_TOO_LARGE"),
        (b"", 422, "IMAGE_FORMAT_INVALID"),
    ],
)
def test_upload_validation(client, db, data, status, code):
    seed_club(db)
    headers = login(client, "pr@club.tw")
    post_id = draft(client, headers)

    response = upload(client, headers, post_id, data)

    assert (response.status_code, response.json()["code"]) == (status, code)
    assert db.scalar(select(models.PostImage)) is None


def test_exactly_eight_million_bytes_is_accepted(client, db):
    seed_club(db)
    headers = login(client, "pr@club.tw")

    assert upload(client, headers, draft(client, headers), jpeg(100, 100, size=MAX_BYTES)).status_code == 201


def test_upload_rules(client, db):
    _, accounts = seed_club(db)
    writer, publisher = login(client, "newbie@club.tw"), login(client, "pr@club.tw")
    others = draft(client, publisher)
    published = draft(client, publisher)
    db.get(models.Post, published).status = PostStatus.PUBLISHED
    db.commit()

    assert upload(client, writer, others).status_code == 403
    assert upload(client, publisher, published).json()["code"] == "POST_NOT_EDITABLE"
    assert upload(client, publisher, others).status_code == 201
    second = upload(client, publisher, others)
    assert (second.status_code, second.json()["code"]) == (409, "IMAGE_ALREADY_ATTACHED")


def test_instagram_requires_an_image(client, db):
    _, accounts = seed_club(db)
    headers = login(client, "pr@club.tw")
    post_id = draft(client, headers)

    targets = client.put(
        f"{API}/posts/{post_id}/targets",
        json={"platform_account_ids": [accounts["instagram"].id]},
        headers=headers,
    )

    assert (targets.status_code, targets.json()["code"]) == (422, "IMAGE_REQUIRED_FOR_INSTAGRAM")
    upload(client, headers, post_id)
    assert (
        client.put(
            f"{API}/posts/{post_id}/targets",
            json={"platform_account_ids": [accounts["instagram"].id]},
            headers=headers,
        ).status_code
        == 200
    )


def test_remove_image(client, db, media_dir):
    _, accounts = seed_club(db)
    headers = login(client, "pr@club.tw")
    post_id = draft(client, headers)
    assert client.delete(f"{API}/posts/{post_id}/image", headers=headers).status_code == 404
    upload(client, headers, post_id)
    client.put(
        f"{API}/posts/{post_id}/targets",
        json={"platform_account_ids": [accounts["instagram"].id]},
        headers=headers,
    )

    refused = client.delete(f"{API}/posts/{post_id}/image", headers=headers)
    assert (refused.status_code, refused.json()["code"]) == (409, "IMAGE_REQUIRED_BY_INSTAGRAM")

    client.put(
        f"{API}/posts/{post_id}/targets",
        json={"platform_account_ids": [accounts["discord"].id]},
        headers=headers,
    )
    assert client.delete(f"{API}/posts/{post_id}/image", headers=headers).status_code == 204
    assert client.get(f"{API}/posts/{post_id}", headers=headers).json()["image"] is None
    assert list(media_dir.rglob("*.jpg")) == []


def test_copies_share_the_image_until_the_last_one_goes(client, db, media_dir):
    seed_club(db)
    headers = login(client, "pr@club.tw")
    post_id = draft(client, headers)
    original = upload(client, headers, post_id).json()

    copy = client.post(f"{API}/posts/{post_id}/copies", headers=headers).json()
    assert copy["image"] == original
    client.delete(f"{API}/posts/{post_id}", headers=headers)
    assert len(list(media_dir.rglob("*.jpg"))) == 2  # 複本還在用

    client.delete(f"{API}/posts/{copy['id']}/image", headers=headers)
    assert list(media_dir.rglob("*.jpg")) == []


def test_publishing_sends_the_right_version_and_records_it(client, db, mock_platforms):
    _, accounts = seed_club(db)
    headers = login(client, "pr@club.tw")
    post_id = draft(client, headers)
    image = upload(client, headers, post_id, jpeg(1080, 1920)).json()
    client.put(
        f"{API}/posts/{post_id}/targets",
        json={"platform_account_ids": [accounts["instagram"].id, accounts["discord"].id]},
        headers=headers,
    )

    publish(client, headers, post_id)

    [(_, ig_content)] = mock_platforms[Platform.INSTAGRAM].received
    [(_, discord_content)] = mock_platforms[Platform.DISCORD].received
    assert (ig_content.image.width, ig_content.image.height, ig_content.image.variant) == (
        1080,
        1350,
        "instagram",
    )
    assert (discord_content.image.url, discord_content.image.variant) == (image["public_url"], "original")
    db.expire_all()
    records = {
        r.platform_account_id: r
        for r in db.scalars(select(models.PublishRecord).where(models.PublishRecord.post_id == post_id))
    }
    ig = records[accounts["instagram"].id]
    assert (ig.image_format, ig.image_width, ig.image_height, ig.image_variant) == (
        "jpeg",
        1080,
        1350,
        "instagram",
    )
    assert ig.image_sha256 and ig.image_sha256 != records[accounts["discord"].id].image_sha256
    assert records_by_account(client, headers, post_id)["ntu_guitar_ig"]["status"] == "SUCCEEDED"


def test_preview_shows_the_version_each_platform_gets(client, db):
    _, accounts = seed_club(db)
    headers = login(client, "pr@club.tw")
    post_id = draft(client, headers)
    image = upload(client, headers, post_id, jpeg(1080, 1920)).json()
    client.put(
        f"{API}/posts/{post_id}/targets",
        json={"platform_account_ids": [accounts["instagram"].id, accounts["threads"].id]},
        headers=headers,
    )

    items = client.get(f"{API}/posts/{post_id}/preview", headers=headers).json()["items"]

    by_platform = {item["platform_account"]["platform"]: item for item in items}
    assert by_platform["instagram"]["image"] == {
        "url": image["ig_public_url"],
        "width": 1080,
        "height": 1350,
        "variant": "instagram",
    }
    assert by_platform["instagram"]["warnings"] == ["IMAGE_CROPPED"]
    assert by_platform["threads"]["image"]["url"] == image["public_url"]


def test_platforms_that_download_images_need_a_public_https_url(client, db, monkeypatch):
    """Threads、Instagram 由平台下載圖片：圖片網址不是公開 https 時，
    排程或發佈當下就拒絕，不等到發文那一刻才失敗。"""
    monkeypatch.setattr(get_settings(), "media_base_url", "/media")  # 本機預設值：平台連不到
    _, accounts = seed_club(db)
    headers = login(client, "pr@club.tw")
    post_id = draft(client, headers)
    upload(client, headers, post_id)
    client.put(
        f"{API}/posts/{post_id}/targets",
        json={"platform_account_ids": [accounts["threads"].id]},
        headers=headers,
    )

    refused = publish(client, headers, post_id)

    assert (refused.status_code, refused.json()["code"]) == (422, "IMAGE_URL_NOT_PUBLIC")
    discord_only = draft(client, headers, [accounts["discord"].id])
    upload(client, headers, discord_only)
    assert publish(client, headers, discord_only).status_code == 202  # Discord 以附件上傳，不需要公開網址


def test_images_can_live_in_the_database(client, db, monkeypatch, media_dir):
    """正式環境（Neon）把圖片存在資料表，由後端的 /media/{key} 提供；不寫任何檔案。"""
    monkeypatch.setattr(get_settings(), "media_storage_backend", "db")
    seed_club(db)
    headers = login(client, "pr@club.tw")
    post_id = draft(client, headers)

    image = upload(client, headers, post_id, jpeg(1080, 1920)).json()

    response = served(client, image["ig_public_url"])
    assert response.status_code == 200 and response.headers["content-type"] == "image/jpeg"
    assert Image.open(io.BytesIO(response.content)).size == (1080, 1350)
    assert list(media_dir.rglob("*.jpg")) == []
    client.delete(f"{API}/posts/{post_id}/image", headers=headers)
    db.expire_all()
    assert db.scalars(select(models.MediaBlob)).all() == []
