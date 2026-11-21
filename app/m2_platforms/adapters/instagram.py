"""Instagram Adapter：Facebook 企業版登入（Instagram API with Unified Login）與三步發佈。

授權（foundation-plan D-05，2026-11 起新的 Meta App 只能用這種方式）：
- 登入視窗帶 Meta 後台建立的登入設定 config_id，不帶 scope；權限與可分享的資產由設定決定。
- 授權碼換到的是「企業整合系統使用者」Token，屬於社團的企業管理平台，預設不會過期。
- 這個 Token 的 /me 是系統使用者，不是 Instagram 帳號；帳號由 /me/assigned_instagram_accounts 取得。

發佈：建立 container（begin）→ 查詢 status_code（check）→ media_publish（finalize）。
container ID 就是 request_ref；重試規則與 Threads 相同（D-11）。
呼叫 API 時 Token 放在 Authorization 標頭；只有換 Token 與 debug_token 依官方文件放在查詢參數，
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

from .meta_graph import GRAPH_INVALID_TOKEN_CODE, error_details, expires_at, scrub, send

API_VERSION = "v27.0"
DIALOG_URL = f"https://www.facebook.com/{API_VERSION}/dialog/oauth"
API_URL = f"https://graph.facebook.com/{API_VERSION}"
# 帳號查詢時，Token 被授權到哪些 Instagram 帳號（debug_token 的 granular_scopes）
INSTAGRAM_SCOPES = ("instagram_content_publish", "instagram_basic")

_CONTAINER_STATUS = {
    "FINISHED": CheckStatus.READY,
    "IN_PROGRESS": CheckStatus.PROCESSING,
    "PUBLISHED": CheckStatus.PUBLISHED,
}
# 錯誤碼（Graph API 與 Instagram 錯誤碼文件）：
# - 授權失效：190 Token 無效、102 工作階段失效、10 與 200～299 權限不足（要重新授權才能恢復）
# - 平台暫時問題：-1／-2 平台內部錯誤或下載圖片逾時、9 當日發文上限、4／17／32／613 呼叫頻率上限
# - 2207051 是被判定為垃圾內容（錯誤碼也是 4），屬於內容被拒
_AUTH_CODES = {GRAPH_INVALID_TOKEN_CODE, 102, 10}
_UNAVAILABLE_CODES = {-1, -2, 9, 4, 17, 32, 613}
_SPAM_SUBCODE = 2207051


def _auth_invalid(code: Any) -> bool:
    return isinstance(code, int) and (code in _AUTH_CODES or 200 <= code < 300)


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


class InstagramAdapter:
    platform = Platform.INSTAGRAM
    capabilities = CAPABILITIES[Platform.INSTAGRAM]

    def __init__(self, transport: httpx.AsyncBaseTransport | None = None, retry_delay: float = 1.0) -> None:
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
    def _app() -> tuple[str, str, str]:
        settings = get_settings()
        app = (settings.instagram_app_id, settings.instagram_app_secret, settings.instagram_login_config_id)
        if not all(app):
            raise OAuthFailed(
                "INSTAGRAM_APP_ID, INSTAGRAM_APP_SECRET and INSTAGRAM_LOGIN_CONFIG_ID are not configured"
            )
        return app

    def count_chars(self, text: str) -> int:
        return len(text)

    # ---------- 平台授權（OAuthProvider） ----------

    def authorization_url(self, state: str, redirect_uri: str) -> str:
        app_id, _, config_id = self._app()
        query = urlencode(
            {
                "client_id": app_id,
                "config_id": config_id,
                "redirect_uri": redirect_uri,
                "response_type": "code",
                # 系統使用者 Token 只能用授權碼流程：要求以 response_type 為準
                "override_default_response_type": "true",
                "state": state,
            }
        )
        return f"{DIALOG_URL}?{query}"

    async def exchange_code(self, code: str, redirect_uri: str) -> OAuthAccount:
        """授權碼 → 系統使用者 Token → 社團分享的 Instagram 專業帳號（必須剛好一個）。"""
        app_id, app_secret, _ = self._app()
        secrets = [app_secret, code]

        def parse(response: httpx.Response) -> dict[str, Any]:
            if response.status_code == 429 or response.status_code >= 500:
                raise VerificationUnavailable()
            if response.status_code != 200:
                message = error_details(response).message
                raise OAuthFailed(scrub(f"HTTP {response.status_code}: {message}", *secrets))
            try:
                body = response.json()
            except ValueError as exc:
                raise OAuthFailed("unexpected response from Meta") from exc
            if not isinstance(body, dict):
                raise OAuthFailed("unexpected response from Meta")
            return body

        try:
            async with self._client() as client:
                exchanged = parse(
                    await client.get(
                        f"{API_URL}/oauth/access_token",
                        params={
                            "client_id": app_id,
                            "client_secret": app_secret,
                            "redirect_uri": redirect_uri,
                            "code": code,
                        },
                    )
                )
                token = str(exchanged["access_token"])
                secrets.append(token)
                listed = parse(
                    await client.get(
                        f"{API_URL}/me/assigned_instagram_accounts",
                        params={"fields": "id,username"},
                        headers=_bearer(token),
                    )
                )
                accounts = [(str(item["id"]), str(item["username"])) for item in listed.get("data") or []]
                if not accounts:
                    accounts = await self._granted_accounts(client, token, parse, app_id, app_secret)
        except httpx.HTTPError as exc:
            raise VerificationUnavailable() from exc
        except (KeyError, TypeError, AttributeError) as exc:
            raise OAuthFailed("unexpected response from Meta") from exc

        if not accounts:
            raise OAuthFailed(
                "no Instagram professional account was shared; choose one Instagram account when authorizing"
            )
        if len(accounts) > 1:
            raise OAuthFailed("several Instagram accounts were shared; share exactly one per link")
        ig_user_id, username = accounts[0]
        return OAuthAccount(
            platform_user_id=ig_user_id,
            account_name=username,
            credential={"access_token": token, "ig_user_id": ig_user_id, "username": username},
            expires_at=expires_at(exchanged.get("expires_in")),
        )

    async def _granted_accounts(
        self, client: httpx.AsyncClient, token: str, parse, app_id: str, app_secret: str
    ) -> list[tuple[str, str]]:
        """Meta App 與 Instagram 帳號屬於同一個企業管理平台時，assigned_instagram_accounts 可能是空的：
        改從 Token 的授權範圍找出 Instagram 帳號，再逐一確認讀得到帳號名稱。"""
        debug = parse(
            await client.get(
                f"{API_URL}/debug_token",
                params={"input_token": token},
                headers=_bearer(f"{app_id}|{app_secret}"),
            )
        )
        ids: list[str] = []
        for grant in (debug.get("data") or {}).get("granular_scopes") or []:
            if grant.get("scope") in INSTAGRAM_SCOPES:
                ids += [str(i) for i in grant.get("target_ids") or [] if str(i) not in ids]
        accounts = []
        for ig_user_id in ids:
            response = await client.get(
                f"{API_URL}/{ig_user_id}", params={"fields": "id,username"}, headers=_bearer(token)
            )
            if 400 <= response.status_code < 500 and response.status_code != 429:
                continue  # Token 讀不到這個帳號：不算分享給我們
            profile = parse(response)  # 429、5xx：暫時無法確認，不能只連結查得到的那幾個
            accounts.append((str(profile["id"]), str(profile["username"])))
        return accounts

    # ---------- 三步發佈（PlatformAdapter） ----------

    def _failure(self, response: httpx.Response, credential: Credential) -> Failed:
        message, code, subcode, transient = error_details(response)
        status = response.status_code
        rate_limited = code in _UNAVAILABLE_CODES and subcode != _SPAM_SUBCODE
        if status == 401 or _auth_invalid(code):
            reason = FailureReason.AUTH_INVALID
        elif status == 429 or status >= 500 or transient or rate_limited:
            reason = FailureReason.PLATFORM_UNAVAILABLE
        elif 400 <= status < 500:
            reason = FailureReason.CONTENT_REJECTED
        else:
            reason = FailureReason.OTHER
        scrubbed = scrub(
            f"HTTP {status}: {message}".strip(": "),
            credential.get("access_token"),
            get_settings().instagram_app_secret,
        )
        return Failed(reason, scrubbed)

    async def begin(self, credential: Credential, content: PostContent) -> Started | Failed:
        if content.image is None:
            return Failed(FailureReason.CONTENT_REJECTED, "Instagram posts need an image")
        # Instagram 由平台主動下載圖片，必須是它連得到的公開 https 網址
        if not content.image.url.startswith("https://"):
            return Failed(
                FailureReason.OTHER,
                "image needs a public https URL that Instagram can download; set MEDIA_BASE_URL",
            )
        try:
            async with self._client() as client:
                response = await send(
                    client,
                    "POST",
                    f"{API_URL}/{credential['ig_user_id']}/media",
                    retry_server_errors=True,
                    retry_delay=self._retry_delay,
                    data={"image_url": content.image.url, "caption": content.text},
                    headers=_bearer(credential["access_token"]),
                )
        except httpx.HTTPError:
            # 還沒發佈的 container 別人看不到，建立失敗或結果不明都不會造成重複貼文
            return Failed(FailureReason.PLATFORM_UNAVAILABLE, "could not reach Instagram")

        if response.status_code != 200:
            return self._failure(response, credential)
        try:
            return Started(str(response.json()["id"]))
        except (ValueError, KeyError, TypeError):
            return Failed(FailureReason.OTHER, "unexpected response from Instagram")

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
                    params={"fields": "status_code,status"},
                    headers=_bearer(credential["access_token"]),
                )
            if response.status_code != 200:
                return CheckResult(CheckStatus.UNKNOWN)
            body = response.json()
            status = str(body["status_code"])
        except (httpx.HTTPError, ValueError, KeyError, TypeError):
            return CheckResult(CheckStatus.UNKNOWN)

        if status in _CONTAINER_STATUS:
            mapped = _CONTAINER_STATUS[status]
            # 已經發出，但從 container 查不到貼文連結：仍然算成功，連結留空
            return CheckResult(mapped, published=Published() if status == "PUBLISHED" else None)
        if status == "ERROR":
            # status 欄位是 Instagram 的錯誤子代碼，例如 2207052（圖片網址下載不到）
            detail = scrub(f"container error: {body.get('status', 'UNKNOWN')}")
            return CheckResult(CheckStatus.FAILED, failed=Failed(FailureReason.CONTENT_REJECTED, detail))
        if status == "EXPIRED":
            return CheckResult(
                CheckStatus.FAILED,
                failed=Failed(FailureReason.OTHER, "container expired before it was published"),
            )
        return CheckResult(CheckStatus.UNKNOWN)

    async def finalize(self, credential: Credential, request_ref: str) -> Published | Failed:
        headers = _bearer(credential["access_token"])
        try:
            async with self._client() as client:
                response = await send(
                    client,
                    "POST",
                    f"{API_URL}/{credential['ig_user_id']}/media_publish",
                    retry_server_errors=False,
                    retry_delay=self._retry_delay,
                    data={"creation_id": request_ref},
                    headers=headers,
                )
                if response.status_code != 200:
                    return self._failure(response, credential)
                try:
                    media_id = str(response.json()["id"])
                except (ValueError, KeyError, TypeError):
                    return Published()  # 已經發出，只是讀不到貼文 ID
                return Published(post_id=media_id, post_url=await self._permalink(client, media_id, headers))
        except (httpx.ConnectError, httpx.ConnectTimeout):
            return Failed(FailureReason.PLATFORM_UNAVAILABLE, "could not reach Instagram")
        except httpx.HTTPError as exc:
            # 請求已送出但沒有拿到回應：結果不明，交給引擎用 check 確認
            return Failed(FailureReason.TIMEOUT, type(exc).__name__)

    async def _permalink(
        self, client: httpx.AsyncClient, media_id: str, headers: dict[str, str]
    ) -> str | None:
        """貼文已經發出，連結只是附帶資訊：查不到也不算失敗。"""
        try:
            params = {"fields": "permalink"}
            response = await client.get(f"{API_URL}/{media_id}", params=params, headers=headers)
            if response.status_code == 200:
                permalink = response.json().get("permalink")
                return str(permalink) if permalink else None
        except (httpx.HTTPError, ValueError, AttributeError):
            pass
        return None
