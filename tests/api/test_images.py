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


def mpo(width, height) -> bytes:
    buffer = io.BytesIO()
    first, second = Image.new("RGB", (width, height)), Image.new("RGB", (320, 240))
    first.save(buffer, format="MPO", save_all=True, append_images=[second])
    return buffer.getvalue()


def rotated_jpeg(stored_width, stored_height) -> bytes:
    """手機直拍：像素以橫向儲存，EXIF 記錄要順時針轉 90 度顯示。"""
    exif = Image.Exif()
    exif[0x0112] = 6
    buffer = io.BytesIO()
    Image.new("RGB", (stored_width, stored_height)).save(buffer, format="JPEG", exif=exif)
    return buffer.getvalue()


@pytest.mark.parametrize(
    ("data", "size"),
    [(mpo(1080, 1080), (1080, 1080)), (rotated_jpeg(1200, 1000), (1000, 1200))],
    ids=["multi-picture", "exif-rotated"],
)
def test_instagram_gets_a_plain_upright_jpeg_even_when_no_crop_is_needed(client, db, data, size):
    """Instagram 不接受 MPO，也不保證依 EXIF 轉正：比例已符合時仍另存一份重新編碼的版本，但不算裁切。"""
    seed_club(db)
    headers = login(client, "pr@club.tw")
    post_id = draft(client, headers)

    image = upload(client, headers, post_id, data).json()

    assert (image["width"], image["height"]) == size
    assert (image["ig_width"], image["ig_height"], image["ig_cropped"]) == (*size, False)
    assert image["ig_public_url"] != image["public_url"]
    instagram = Image.open(io.BytesIO(served(client, image["ig_public_url"]).content))
    assert (instagram.format, instagram.size) == ("JPEG", size)
    assert instagram.getexif().get(0x0112) in (None, 1)
    assert served(client, image["public_url"]).content == data  # 原圖照上傳的檔案保存


def test_upload_still_works_when_the_plain_copy_would_be_too_large(client, db, monkeypatch):
    """不需要裁切、只是為了 Instagram 重新編碼的版本超過大小上限時，退回用原圖，
    不讓只發 Threads、Discord 的貼文因此無法附圖。"""
    from app.m3_posts import images

    seed_club(db)
    headers = login(client, "pr@club.tw")
    post_id = draft(client, headers)
    monkeypatch.setattr(images, "MAX_OUTPUT_BYTES", 100)

    response = upload(client, headers, post_id, rotated_jpeg(1200, 1000))

    assert response.status_code == 201, response.text
    image = response.json()
    assert (image["ig_public_url"], image["ig_cropped"]) == (image["public_url"], False)


def test_upload_is_refused_when_a_needed_crop_is_too_large(client, db, monkeypatch):
    from app.m3_posts import images

    seed_club(db)
    headers = login(client, "pr@club.tw")
    post_id = draft(client, headers)
    monkeypatch.setattr(images, "MAX_OUTPUT_BYTES", 100)

    response = upload(client, headers, post_id, jpeg(1080, 1920))

    assert (response.status_code, response.json()["code"]) == (422, "IMAGE_TOO_LARGE")


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


def test_post_list_does_not_query_once_per_post(client, db):
    from sqlalchemy import event

    from app.core.db import engine
    from tests.factories import make_image

    seed_club(db)
    headers = login(client, "pr@club.tw")
    for _ in range(20):
        make_image(db, draft(client, headers))
    db.commit()
    statements = []
    listener = lambda *args: statements.append(args[2])  # noqa: E731
    event.listen(engine, "before_cursor_execute", listener)
    try:
        response = client.get(f"{API}/posts", headers=headers)
    finally:
        event.remove(engine, "before_cursor_execute", listener)

    assert response.status_code == 200 and all(item["has_image"] for item in response.json()["items"])
    assert len(statements) <= 10, f"{len(statements)} 次查詢"


def test_failed_record_still_shows_which_image_was_sent(client, db, mock_platforms):
    from app.core.enums import FailureReason

    _, accounts = seed_club(db)
    headers = login(client, "pr@club.tw")
    post_id = draft(client, headers, [accounts["discord"].id])
    upload(client, headers, post_id)
    mock_platforms[Platform.DISCORD].fail("公告", FailureReason.PLATFORM_UNAVAILABLE)

    publish(client, headers, post_id)

    db.expire_all()
    record = db.scalar(select(models.PublishRecord).where(models.PublishRecord.post_id == post_id))
    assert (record.status, record.image_variant) == ("FAILED", "original")
    assert record.image_sha256


def test_file_cleanup_failure_does_not_undo_a_committed_removal(client, db, monkeypatch):
    from app.core import media

    seed_club(db)
    headers = login(client, "pr@club.tw")
    post_id = draft(client, headers)
    upload(client, headers, post_id)

    def broken_delete(self, key):
        raise OSError("disk unavailable")

    monkeypatch.setattr(media.LocalMediaStorage, "delete", broken_delete)

    assert client.delete(f"{API}/posts/{post_id}/image", headers=headers).status_code == 204
    assert client.get(f"{API}/posts/{post_id}", headers=headers).json()["image"] is None


def test_removing_a_shared_image_from_both_posts_at_once_deletes_it(db, media_dir):
    """原貼文與複本同時移除圖片：兩邊都看到對方還在用時，不可以留下沒人用的圖片。"""
    import threading

    from app.core.db import SessionLocal
    from app.m3_posts import service
    from tests.factories import make_image

    users, _ = seed_club(db)
    first = models.Post(content="原貼文", creator_id=users["publisher"].id)
    second = models.Post(content="複本", creator_id=users["publisher"].id)
    db.add_all([first, second])
    db.flush()
    image = make_image(db, first.id)
    db.add(
        models.PostImage(
            post_id=second.id, original_media_id=image.original_media_id, ig_media_id=image.ig_media_id
        )
    )
    db.commit()
    post_ids, media_id = (first.id, second.id), image.original_media_id
    barrier = threading.Barrier(2)
    errors = []

    def remove(post_id):
        with SessionLocal() as session:
            try:
                post = session.get(models.Post, post_id)
                barrier.wait(timeout=5)
                service._detach_image(session, post)
                session.commit()
            except Exception as exc:  # 記錄下來讓測試失敗，而不是讓執行緒默默結束
                errors.append(exc)

    threads = [threading.Thread(target=remove, args=(post_id,)) for post_id in post_ids]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(15)

    db.expire_all()
    assert errors == []
    assert db.get(models.MediaFile, media_id) is None


def test_images_can_live_in_object_storage(client, db, monkeypatch, media_dir):
    """正式環境（Neon Object Storage）：圖片放在公開讀取的 bucket，平台直接從 bucket 的網址下載。"""
    import boto3
    from moto import mock_aws

    settings = get_settings()
    base = "https://br-test.storage.c-1.ap-southeast-1.aws.neon.tech/mediagent-images"
    for name, value in {
        "media_storage_backend": "s3",
        "s3_endpoint_url": "",
        "s3_region": "us-east-1",
        "s3_bucket": "mediagent-images",
        "s3_access_key_id": "testing",
        "s3_secret_access_key": "testing",
        "media_base_url": base,
    }.items():
        monkeypatch.setattr(settings, name, value)
    with mock_aws():
        s3 = boto3.client("s3", region_name="us-east-1")
        s3.create_bucket(Bucket="mediagent-images")
        seed_club(db)
        headers = login(client, "pr@club.tw")
        post_id = draft(client, headers)

        image = upload(client, headers, post_id, jpeg(1080, 1920)).json()

        assert image["public_url"].startswith(f"{base}/") and image["ig_public_url"].startswith(f"{base}/")
        keys = {obj["Key"] for obj in s3.list_objects_v2(Bucket="mediagent-images")["Contents"]}
        assert len(keys) == 2 and list(media_dir.rglob("*.jpg")) == []
        key = image["public_url"].rsplit("/", 1)[1]
        redirect = client.get(f"/media/{key}", follow_redirects=False)
        assert (redirect.status_code, redirect.headers["location"]) == (307, image["public_url"])
        client.delete(f"{API}/posts/{post_id}/image", headers=headers)
        assert s3.list_objects_v2(Bucket="mediagent-images").get("KeyCount") == 0
