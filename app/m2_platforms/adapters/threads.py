"""Threads Adapter：平台授權（OAuth）與三步發佈。

發佈：建立 container（begin）→ 查詢 container 狀態（check）→ 正式發佈（finalize）。
container ID 就是 request_ref：逾時或中斷後，可以用它向 Threads 確認貼文到底發出去了沒有。

重試規則（foundation-plan D-11）：
- begin、check 不會讓貼文出現在平台上，遇到 429 或 5xx 自動重試，最多 2 次。
- finalize 會真的發文，只在 429（平台明確拒收）時重試；5xx、沒有回應都不重試。

存取 Token 依官方文件放在表單欄位（POST）或查詢參數（GET）；
因此錯誤訊息一律先濾掉 Token 與 App 密鑰，httpx 的請求紀錄也已在 app/main.py 關閉。
"""

from typing import Any
from urllib.parse import urlencode

import httpx

from app.core.config import get_settings
from app.core.enums import FailureReason, Platform
from app.core.platforms import (
    CAPABILITIES,
    CheckResult,
    CheckStatus,
    Credential,
    Failed,
    OAuthAccount,
    OAuthFailed,
    PostContent,
    Published,
    Started,
    VerificationUnavailable,
)

from .meta_graph import (
    APP_BLOCKED_HINT,
    GRAPH_INVALID_TOKEN_CODE,
    app_blocked,
    error_details,
    expires_at,
    scrub,
    send,
)

AUTHORIZE_URL = "https://threads.com/oauth/authorize"
GRAPH_URL = "https://graph.threads.com"
API_URL = f"{GRAPH_URL}/v1.0"
# 只申請發文需要的最小權限（NFR-06）
SCOPES = ("threads_basic", "threads_content_publish")

_CONTAINER_STATUS = {
    "FINISHED": CheckStatus.READY,
    "IN_PROGRESS": CheckStatus.PROCESSING,
    "PUBLISHED": CheckStatus.PUBLISHED,
}


def _is_emoji(char: str) -> bool:
    code = ord(char)
    return (
        0x1F000 <= code <= 0x1FAFF  # 表情符號、旗幟、膚色修飾
        or 0x2600 <= code <= 0x27BF  # 雜項符號、裝飾符號
        or 0x2B00 <= code <= 0x2BFF
        or code in (0x200D, 0xFE0F)  # 組合 emoji 用的連接符號與變體選擇符號
    )


class ThreadsAdapter:
    platform = Platform.THREADS
    capabilities = CAPABILITIES[Platform.THREADS]

    def __init__(
        self, transport: httpx.AsyncBaseTransport | None = None, retry_delay: float = 1.0
    ) -> None:
        # transport 只在測試時傳入，用假的 HTTP 傳輸層取代真實連線
        self._transport = transport
        self._retry_delay = retry_delay

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            transport=self._transport,
            timeout=get_settings().platform_call_timeout_seconds,
            follow_redirects=False,
        )

    @staticmethod
    def _app() -> tuple[str, str]:
        settings = get_settings()
        if not settings.threads_app_id or not settings.threads_app_secret:
            raise OAuthFailed("THREADS_APP_ID and THREADS_APP_SECRET are not configured")
        return settings.threads_app_id, settings.threads_app_secret

    def count_chars(self, text: str) -> int:
        """Threads 官方文件：emoji 以 UTF-8 位元組數計算，其餘每個字元算 1。待以真實 API 確認。"""
        return sum(len(char.encode("utf-8")) if _is_emoji(char) else 1 for char in text)

    # ---------- 平台授權（OAuthProvider） ----------

    def authorization_url(self, state: str, redirect_uri: str) -> str:
        app_id, _ = self._app()
        query = urlencode(
            {
                "client_id": app_id,
                "redirect_uri": redirect_uri,
                "scope": ",".join(SCOPES),
                "response_type": "code",
                "state": state,
            }
        )
        return f"{AUTHORIZE_URL}?{query}"

    async def exchange_code(self, code: str, redirect_uri: str) -> OAuthAccount:
        """授權碼 → 短效 Token → 長效 Token（約 60 天），再取得帳號名稱。"""
        app_id, app_secret = self._app()
        secrets = [app_secret, code]

        def parse(response: httpx.Response) -> dict[str, Any]:
            if response.status_code == 429 or response.status_code >= 500:
                raise VerificationUnavailable()
            message = error_details(response).message
            if response.status_code != 200:
                raise OAuthFailed(scrub(f"HTTP {response.status_code}: {message}", *secrets))
            try:
                body = response.json()
            except ValueError as exc:
                raise OAuthFailed("unexpected response from Threads") from exc
            if not isinstance(body, dict):
                raise OAuthFailed("unexpected response from Threads")
            return body

        try:
            async with self._client() as client:
                short = parse(
                    await client.post(
                        f"{GRAPH_URL}/oauth/access_token",
                        data={
                            "client_id": app_id,
                            "client_secret": app_secret,
                            "grant_type": "authorization_code",
                            "redirect_uri": redirect_uri,
                            "code": code,
                        },
                    )
                )
                secrets.append(str(short.get("access_token", "")))
                long_lived = parse(
                    await client.get(
                        f"{GRAPH_URL}/access_token",
                        params={
                            "grant_type": "th_exchange_token",
                            "client_secret": app_secret,
                            "access_token": short["access_token"],
                        },
                    )
                )
                token = str(long_lived["access_token"])
                secrets.append(token)
                profile = parse(
                    await client.get(
                        f"{API_URL}/me", params={"fields": "id,username", "access_token": token}
                    )
                )
                user_id = str(profile.get("id") or short["user_id"])
                username = str(profile["username"])
        except httpx.HTTPError as exc:
            raise VerificationUnavailable() from exc
        except KeyError as exc:
            raise OAuthFailed("unexpected response from Threads") from exc

        return OAuthAccount(
            platform_user_id=user_id,
            account_name=username,
            credential={"access_token": token, "user_id": user_id, "username": username},
            expires_at=expires_at(long_lived.get("expires_in")),
        )

    # ---------- 三步發佈（PlatformAdapter） ----------

    def _failure(self, response: httpx.Response, credential: Credential) -> Failed:
        message, code, _, _ = error_details(response)
        status = response.status_code
        if app_blocked(message):
            reason = FailureReason.OTHER
            message = f"{message}（{APP_BLOCKED_HINT}）"
        elif status == 401 or code == GRAPH_INVALID_TOKEN_CODE or "access token" in message.lower():
            reason = FailureReason.AUTH_INVALID
        elif status == 429 or status >= 500:
            reason = FailureReason.PLATFORM_UNAVAILABLE
        elif 400 <= status < 500:
            reason = FailureReason.CONTENT_REJECTED
        else:
            reason = FailureReason.OTHER
        scrubbed = scrub(
            f"HTTP {status}: {message}".strip(": "),
            credential.get("access_token"),
            get_settings().threads_app_secret,
        )
        return Failed(reason, scrubbed)

    async def begin(self, credential: Credential, content: PostContent) -> Started | Failed:
        data = {"media_type": "TEXT", "text": content.text, "access_token": credential["access_token"]}
        if content.image is not None:
            # Threads 由平台主動下載圖片，必須是它連得到的公開 https 網址
            if not content.image.url.startswith("https://"):
                return Failed(
                    FailureReason.OTHER,
                    "image needs a public https URL that Threads can download; set MEDIA_BASE_URL",
                )
            data = {
                "media_type": "IMAGE",
                "image_url": content.image.url,
                "text": content.text,
                "access_token": credential["access_token"],
            }
        try:
            async with self._client() as client:
                response = await send(
                    client,
                    "POST",
                    f"{API_URL}/{credential['user_id']}/threads",
                    retry_server_errors=True,
                    retry_delay=self._retry_delay,
                    data=data,
                )
        except httpx.HTTPError:
            # 還沒發佈的 container 別人看不到，建立失敗或結果不明都不會造成重複貼文
            return Failed(FailureReason.PLATFORM_UNAVAILABLE, "could not reach Threads")

        if response.status_code != 200:
            return self._failure(response, credential)
        try:
            return Started(str(response.json()["id"]))
        except (ValueError, KeyError, TypeError):
            return Failed(FailureReason.OTHER, "unexpected response from Threads")

    async def check(self, credential: Credential, request_ref: str | None) -> CheckResult:
        if not request_ref:
            return CheckResult(CheckStatus.UNKNOWN)
        try:
            async with self._client() as client:
                response = await send(
                    client,
                    "GET",
                    f"{API_URL}/{request_ref}",
                    retry_server_errors=True,
                    retry_delay=self._retry_delay,
                    params={
                        "fields": "status,error_message",
                        "access_token": credential["access_token"],
                    },
                )
            if response.status_code != 200:
                return CheckResult(CheckStatus.UNKNOWN)
            body = response.json()
            status = str(body["status"])
        except (httpx.HTTPError, ValueError, KeyError, TypeError):
            return CheckResult(CheckStatus.UNKNOWN)

        if status in _CONTAINER_STATUS:
            mapped = _CONTAINER_STATUS[status]
            # 已經發出，但從 container 查不到貼文連結：仍然算成功，連結留空
            return CheckResult(mapped, published=Published() if status == "PUBLISHED" else None)
        if status == "ERROR":
            detail = scrub(f"container error: {body.get('error_message', 'UNKNOWN')}")
            return CheckResult(
                CheckStatus.FAILED, failed=Failed(FailureReason.CONTENT_REJECTED, detail)
            )
        if status == "EXPIRED":
            return CheckResult(
                CheckStatus.FAILED,
                failed=Failed(FailureReason.OTHER, "container expired before it was published"),
            )
        return CheckResult(CheckStatus.UNKNOWN)

    async def finalize(self, credential: Credential, request_ref: str) -> Published | Failed:
        token = credential["access_token"]
        try:
            async with self._client() as client:
                response = await send(
                    client,
                    "POST",
                    f"{API_URL}/{credential['user_id']}/threads_publish",
                    retry_server_errors=False,
                    retry_delay=self._retry_delay,
                    data={"creation_id": request_ref, "access_token": token},
                )
                if response.status_code != 200:
                    return self._failure(response, credential)
                try:
                    media_id = str(response.json()["id"])
                except (ValueError, KeyError, TypeError):
                    return Published()  # 已經發出，只是讀不到貼文 ID
                return Published(post_id=media_id, post_url=await self._permalink(client, media_id, token))
        except (httpx.ConnectError, httpx.ConnectTimeout):
            return Failed(FailureReason.PLATFORM_UNAVAILABLE, "could not reach Threads")
        except httpx.HTTPError as exc:
            # 請求已送出但沒有拿到回應：結果不明，交給引擎用 check 確認
            return Failed(FailureReason.TIMEOUT, type(exc).__name__)

    async def _permalink(self, client: httpx.AsyncClient, media_id: str, token: str) -> str | None:
        """貼文已經發出，連結只是附帶資訊：查不到也不算失敗。"""
        try:
            response = await client.get(
                f"{API_URL}/{media_id}", params={"fields": "id,permalink", "access_token": token}
            )
            if response.status_code == 200:
                permalink = response.json().get("permalink")
                return str(permalink) if permalink else None
        except (httpx.HTTPError, ValueError, AttributeError):
            pass
        return None
