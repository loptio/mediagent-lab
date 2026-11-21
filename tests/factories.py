"""測試資料工廠：直接寫入資料庫，建立測試需要的前置資料。"""

from app.core import auth, crypto, models
from app.core.enums import Platform, Role

DEFAULT_PASSWORD = "correct-horse-battery"


def make_user(db, email="pr@club.tw", role=Role.PUBLISHER, name="公關", password=DEFAULT_PASSWORD):
    user = models.UserAccount(
        email=email, name=name, password_hash=auth.hash_password(password), role=role
    )
    db.add(user)
    db.flush()
    return user


def make_account(db, linked_by, platform=Platform.DISCORD, name="公告", **fields):
    # MockAdapter 以憑證中的 account_name 辨認是哪一個帳號
    token, version = crypto.encrypt_credential({"account_name": name})
    account = models.PlatformAccount(
        platform=platform, account_name=name, credential_encrypted=token,
        credential_key_version=version, linked_by=linked_by.id, **fields,
    )
    db.add(account)
    db.flush()
    return account


def make_post(db, creator, content="本週三 19:00 社課在活動中心 201", **fields):
    post = models.Post(content=content, creator_id=creator.id, **fields)
    db.add(post)
    db.flush()
    return post


def make_image(db, post_id, width=1080, height=1350, ig_size=None, url="https://media.test/poster.jpg"):
    """直接建立貼文圖片（不產生實際檔案）：Instagram 版本預設與原圖相同。"""
    import hashlib
    import uuid

    def media(w, h, suffix):
        key = f"{uuid.uuid4().hex}.jpg"
        row = models.MediaFile(
            storage_key=key,
            public_url=url.replace(".jpg", f"{suffix}.jpg"),
            sha256=hashlib.sha256(f"{key}{suffix}".encode()).hexdigest(),
            size_bytes=300_000,
            width=w,
            height=h,
        )
        db.add(row)
        db.flush()
        return row

    original = media(width, height, "")
    instagram = media(*ig_size, "-ig") if ig_size and tuple(ig_size) != (width, height) else original
    image = models.PostImage(post_id=post_id, original_media_id=original.id, ig_media_id=instagram.id)
    db.add(image)
    db.flush()
    return image
