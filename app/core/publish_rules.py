"""發佈限制檢查：設定排程、立即發佈、修改已排程貼文時共用（BR-01、02、07、08、09）。

圖片相關規則（BR-05、圖片寬高）在圖片功能完成時加入。
"""

from datetime import datetime

from .enums import AuthStatus
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
