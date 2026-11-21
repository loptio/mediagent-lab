"""發佈限制檢查：設定排程、立即發佈、修改已排程貼文時共用（BR-01、02、05、07、08、09）。

各平台的圖片寬高限制（4.3.1）數值尚待查證，查證後加入。
"""

from datetime import datetime

from .enums import AuthStatus, Platform
from .errors import DomainError
from .models import PlatformAccount, Post
from .platforms import effective_auth_status, get_adapter


def check(post: Post, accounts: list[PlatformAccount], now: datetime) -> None:
    """不符合發佈限制時拋出 DomainError；全部符合則沒有回傳值。"""
    if not post.content.strip():
        raise DomainError(422, "CONTENT_EMPTY", "貼文文字不可為空白")
    if not accounts:
        raise DomainError(422, "NO_TARGET", "請至少選擇一個目標平台帳號")

    unavailable = [a.account_name for a in accounts if a.removed]
    if unavailable:
        raise DomainError(
            422, "TARGET_NOT_AVAILABLE", "目標平台帳號已被移除", {"accounts": unavailable}
        )

    require_image_for_instagram(post, accounts)
    require_public_image_url(post, accounts)

    invalid = [
        a.account_name for a in accounts if effective_auth_status(a, now) == AuthStatus.INVALID
    ]
    if invalid:
        raise DomainError(
            422,
            "TARGET_AUTH_INVALID",
            "目標平台帳號的授權已失效，請管理員重新連結",
            {"accounts": invalid},
        )

    check_text(post, accounts)


def require_image_for_instagram(post: Post, accounts: list[PlatformAccount]) -> None:
    """BR-05：目標含 Instagram 時，貼文必須附加圖片。"""
    if post.image is None and any(account.platform == Platform.INSTAGRAM for account in accounts):
        raise DomainError(422, "IMAGE_REQUIRED_FOR_INSTAGRAM", "選擇 Instagram 時，貼文必須附加一張圖片")


# 由平台主動下載圖片的平台：圖片網址必須是它連得到的公開 https 網址（Discord 以附件上傳，不需要）
DOWNLOADS_IMAGES = (Platform.THREADS, Platform.INSTAGRAM)


def require_public_image_url(post: Post, accounts: list[PlatformAccount]) -> None:
    """有圖片且目標含 Threads 或 Instagram 時，圖片網址必須是公開 https，不要等到發文那一刻才失敗。"""
    if post.image is None:
        return
    for account in accounts:
        if account.platform not in DOWNLOADS_IMAGES:
            continue
        media = post.image.instagram if account.platform == Platform.INSTAGRAM else post.image.original
        if not media.public_url.startswith("https://"):
            raise DomainError(
                422,
                "IMAGE_URL_NOT_PUBLIC",
                f"{account.platform} 需要從公開網址下載圖片；請先設定 MEDIA_BASE_URL 並重新附加圖片",
                {"platform": str(account.platform)},
            )


def check_text(post: Post, accounts: list[PlatformAccount]) -> None:
    """只檢查文字（BR-01、BR-02）：修改已排程貼文的內容時用，不因目標的授權狀態擋住改字。"""
    if not post.content.strip():
        raise DomainError(422, "CONTENT_EMPTY", "貼文文字不可為空白")

    # 各平台依自己的定義計算字數；先回報上限最嚴格的平台
    def text_limit(account: PlatformAccount) -> int:
        return get_adapter(account.platform).capabilities.max_text_length

    for account in sorted(accounts, key=text_limit):
        adapter = get_adapter(account.platform)
        length = adapter.count_chars(post.content)
        limit = adapter.capabilities.max_text_length
        if length > limit:
            raise DomainError(
                422,
                "CONTENT_TOO_LONG",
                f"貼文超過 {account.platform} 的字數上限",
                {"platform": str(account.platform), "limit": limit, "length": length},
            )
