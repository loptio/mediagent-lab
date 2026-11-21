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
