"""Discord Adapter：以 Webhook 發佈，一步完成（begin 直接回傳結果）。

- Webhook 網址等同密碼：只接受官方網址格式、不跟隨轉址，錯誤訊息一律先濾掉網址與 token。
- 送出時加上 ?wait=true，回應才會包含訊息 ID，用來組出訊息連結。
- 重試規則（foundation-plan D-11）：發文是「會發文的呼叫」，只有 429（平台明確拒收）才自動重試；
  5xx、逾時或結果不明都不重試，避免重複發文。
"""

import asyncio
import re
from typing import Any

import httpx

from app.core.config import get_settings
from app.core.enums import FailureReason, Platform
from app.core.platforms import (
    CAPABILITIES,
    CheckResult,
    CheckStatus,
    Credential,
    Failed,
    PostContent,
    Published,
    VerificationUnavailable,
    WebhookInvalid,
)

# 只接受官方 Discord Webhook 網址；主機固定，因此不會被導向內網或其他服務（SSRF）
WEBHOOK_URL_PATTERN = re.compile(
    r"https://(?:discord\.com|discordapp\.com)/api/webhooks/(?P<id>\d+)/(?P<token>[A-Za-z0-9_-]+)"
)
MAX_RATE_LIMIT_RETRIES = 2
MAX_RETRY_AFTER_SECONDS = 5.0
MAX_ERROR_MESSAGE_LENGTH = 300


def is_webhook_url(url: str) -> bool:
    return WEBHOOK_URL_PATTERN.fullmatch(url) is not None


def _scrub(text: str, webhook_url: str) -> str:
    """移除訊息中可能出現的 Webhook 網址與 token（NFR-02）。"""
    match = WEBHOOK_URL_PATTERN.fullmatch(webhook_url)
    for secret in filter(None, [webhook_url, match.group("token") if match else None]):
        text = text.replace(secret, "[redacted]")
    return text[:MAX_ERROR_MESSAGE_LENGTH]


def _describe(response: httpx.Response, webhook_url: str) -> str:
    try:
        detail = str(response.json().get("message", ""))
    except ValueError:
        detail = response.text
    return _scrub(f"HTTP {response.status_code}: {detail}".strip(": "), webhook_url)


def _retry_after(response: httpx.Response) -> float:
    try:
        seconds = float(response.json().get("retry_after", 1))
    except (ValueError, TypeError, AttributeError):
        seconds = 1.0
    return max(0.0, min(seconds, MAX_RETRY_AFTER_SECONDS))


class DiscordAdapter:
    platform = Platform.DISCORD
    capabilities = CAPABILITIES[Platform.DISCORD]

    def __init__(self, transport: httpx.AsyncBaseTransport | None = None) -> None:
        # transport 只在測試時傳入，用假的 HTTP 傳輸層取代真實連線
        self._transport = transport

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            transport=self._transport,
            timeout=get_settings().platform_call_timeout_seconds,
            follow_redirects=False,
        )

    def count_chars(self, text: str) -> int:
        # 待平台實測確認 Discord 的實際算法（foundation-plan 第 10 節），目前以 Unicode 字元數計算
        return len(text)

    async def verify_webhook(self, webhook_url: str) -> dict[str, Any]:
        """向 Discord 確認 Webhook 存在且可用，回傳要存進憑證的識別資料。"""
        if not is_webhook_url(webhook_url):
            raise WebhookInvalid()
        try:
            async with self._client() as client:
                response = await client.get(webhook_url)
        except httpx.HTTPError as exc:
            raise VerificationUnavailable() from exc

        if response.status_code == 200:
            try:
                info = response.json()
                return {
                    "webhook_id": str(info["id"]),
                    "guild_id": str(info["guild_id"]),
                    "channel_id": str(info["channel_id"]),
                }
            except (ValueError, KeyError, TypeError) as exc:
                raise VerificationUnavailable() from exc
        if response.status_code == 429 or response.status_code >= 500:
            raise VerificationUnavailable()  # 暫時無法驗證，不判定 Webhook 無效（BR-37）
        raise WebhookInvalid()

    async def begin(self, credential: Credential, content: PostContent) -> Published | Failed:
        webhook_url = credential["webhook_url"]
        try:
            async with self._client() as client:
                for _ in range(MAX_RATE_LIMIT_RETRIES + 1):
                    response = await client.post(
                        webhook_url, params={"wait": "true"}, json={"content": content.text}
                    )
                    if response.status_code != 429:
                        break
                    await asyncio.sleep(_retry_after(response))
        except (httpx.ConnectError, httpx.ConnectTimeout):
            # 連線沒有建立，確定沒有送出
            return Failed(FailureReason.PLATFORM_UNAVAILABLE, "could not connect to Discord")
        except httpx.HTTPError as exc:
            # 請求已送出但沒有拿到回應：結果不明，不可重試
            return Failed(FailureReason.TIMEOUT, type(exc).__name__)

        status = response.status_code
        if status in (200, 204):
            return self._published(response, credential)
        message = _describe(response, webhook_url)
        if status in (401, 403, 404):
            return Failed(FailureReason.AUTH_INVALID, message)  # Webhook 已被刪除或失效
        if status == 400:
            return Failed(FailureReason.CONTENT_REJECTED, message)
        if status == 429 or status >= 500:
            return Failed(FailureReason.PLATFORM_UNAVAILABLE, message)
        return Failed(FailureReason.OTHER, message)

    @staticmethod
    def _published(response: httpx.Response, credential: Credential) -> Published:
        try:
            message = response.json()
            message_id = str(message["id"])
            channel_id = str(message.get("channel_id") or credential["channel_id"])
            guild_id = credential["guild_id"]
        except (ValueError, KeyError, TypeError):
            # 訊息已經發出，只是組不出連結：仍然是成功，連結留空
            return Published()
        return Published(
            post_id=message_id,
            post_url=f"https://discord.com/channels/{guild_id}/{channel_id}/{message_id}",
        )

    async def check(self, credential: Credential, request_ref: str | None) -> CheckResult:
        # Webhook 發佈沒有可以事後查詢的識別碼，一律無法確認
        return CheckResult(CheckStatus.UNKNOWN)

    async def finalize(self, credential: Credential, request_ref: str) -> Published | Failed:
        return Failed(FailureReason.OTHER, "Discord publishes in one step")
