"""Instagram Adapter：Facebook 企業版登入（Instagram API with Unified Login）與三步發佈。

官方文件：developers.facebook.com/documentation/instagram-platform/instagram-api-with-unified-login
"""

import asyncio
from datetime import timedelta
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from app.core import clock
from app.core.config import get_settings
from app.core.enums import FailureReason
from app.core.platforms import (
    CheckStatus,
    Failed,
    ImageVersion,
    OAuthFailed,
    PostContent,
    Published,
    Started,
    VerificationUnavailable,
)
from app.m2_platforms.adapters.instagram import InstagramAdapter

TOKEN = "EAAB-system-user-token"
SECRET = "meta-app-secret-value"
APP_ID = "1810251873520696"
CONFIG_ID = "991299824049209"
IG_ID = "17841409672144767"
CREDENTIAL = {"access_token": TOKEN, "ig_user_id": IG_ID, "username": "mediagentlab"}
REDIRECT = "https://mediagent-lab.onrender.com/api/v1/platform-accounts/oauth/callback"
GRAPH = "https://graph.facebook.com/v27.0"
IMAGE = ImageVersion(
    url="https://storage.test/mediagent-media/abc.jpg",
    storage_key="abc.jpg",
    sha256="0" * 64,
    width=1080,
    height=1350,
    variant="instagram",
)
CONTENT = PostContent(text="社課海報 #吉他社", image=IMAGE)


@pytest.fixture(autouse=True)
def app_configured(monkeypatch):
    monkeypatch.setattr(get_settings(), "instagram_app_id", APP_ID)
    monkeypatch.setattr(get_settings(), "instagram_app_secret", SECRET)
    monkeypatch.setattr(get_settings(), "instagram_login_config_id", CONFIG_ID)


def form(request: httpx.Request) -> dict[str, str]:
    return {key: values[0] for key, values in parse_qs(request.content.decode()).items()}


def run(handler, call):
    """用假的 HTTP 傳輸層執行一次 Adapter 呼叫，回傳（結果, 送出的請求）。"""
    requests: list[httpx.Request] = []

    def recording(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return handler(request, len(requests))

    adapter = InstagramAdapter(transport=httpx.MockTransport(recording), retry_delay=0)
    return asyncio.run(call(adapter)), requests


def graph_error(status, message, code=100, subcode=None, transient=None):
    error = {"message": message, "type": "OAuthException", "code": code}
    if subcode:
        error["error_subcode"] = subcode
    if transient is not None:
        error["is_transient"] = transient
    return httpx.Response(status, json={"error": error})


def assigned(*accounts):
    return httpx.Response(200, json={"data": [{"id": i, "username": u} for i, u in accounts]})


# ---------- 授權 ----------


def test_authorization_url_uses_the_login_configuration_instead_of_scopes():
    url = urlparse(InstagramAdapter().authorization_url("state-123", REDIRECT))
    query = parse_qs(url.query)

    assert f"{url.scheme}://{url.netloc}{url.path}" == "https://www.facebook.com/v27.0/dialog/oauth"
    assert query == {
        "client_id": [APP_ID],
        "config_id": [CONFIG_ID],
        "redirect_uri": [REDIRECT],
        "response_type": ["code"],
        "override_default_response_type": ["true"],
        "state": ["state-123"],
    }
    assert SECRET not in url.geturl()


@pytest.mark.parametrize(
    "missing", ["instagram_app_id", "instagram_app_secret", "instagram_login_config_id"]
)
def test_authorization_requires_app_configuration(monkeypatch, missing):
    monkeypatch.setattr(get_settings(), missing, "")

    with pytest.raises(OAuthFailed):
        InstagramAdapter().authorization_url("state-123", REDIRECT)


def test_exchange_code_links_the_shared_instagram_account():
    def handler(request, n):
        if n == 1:
            return httpx.Response(200, json={"access_token": TOKEN, "token_type": "bearer"})
        return assigned((IG_ID, "mediagentlab"))

    account, requests = run(handler, lambda a: a.exchange_code("the-code", REDIRECT))

    exchange, accounts = requests
    assert (exchange.method, exchange.url.path) == ("GET", "/v27.0/oauth/access_token")
    assert dict(exchange.url.params) == {
        "client_id": APP_ID,
        "client_secret": SECRET,
        "redirect_uri": REDIRECT,
        "code": "the-code",
    }
    assert accounts.url.path == "/v27.0/me/assigned_instagram_accounts"
    assert accounts.url.params["fields"] == "id,username"
    # Token 放在標頭，不放在網址
    assert accounts.headers["authorization"] == f"Bearer {TOKEN}"
    assert TOKEN not in str(accounts.url)
    assert (account.platform_user_id, account.account_name) == (IG_ID, "mediagentlab")
    assert account.credential == CREDENTIAL
    assert account.expires_at is None  # 系統使用者 Token 預設不會過期


def test_exchange_code_records_expiry_when_the_configuration_sets_one():
    def handler(request, n):
        if n == 1:
            return httpx.Response(200, json={"access_token": TOKEN, "expires_in": 5183944})
        return assigned((IG_ID, "mediagentlab"))

    account, _ = run(handler, lambda a: a.exchange_code("the-code", REDIRECT))

    assert abs(account.expires_at - (clock.now() + timedelta(seconds=5183944))) < timedelta(seconds=5)


def test_exchange_code_falls_back_to_the_token_grants_when_no_account_is_listed():
    """Meta App 與 Instagram 帳號在同一個企業管理平台時，assigned_instagram_accounts 可能是空的；
    改看 Token 實際被授權的 Instagram 帳號（debug_token 的 granular_scopes）。"""

    def handler(request, n):
        if n == 1:
            return httpx.Response(200, json={"access_token": TOKEN})
        if n == 2:
            return assigned()
        if n == 3:
            return httpx.Response(
                200,
                json={
                    "data": {
                        "is_valid": True,
                        "granular_scopes": [
                            {"scope": "instagram_basic", "target_ids": [IG_ID]},
                            {"scope": "instagram_content_publish", "target_ids": [IG_ID]},
                            {"scope": "ads_read", "target_ids": ["act_1"]},
                        ],
                    }
                },
            )
        return httpx.Response(200, json={"id": IG_ID, "username": "mediagentlab"})

    account, requests = run(handler, lambda a: a.exchange_code("the-code", REDIRECT))

    debug, profile = requests[2], requests[3]
    assert debug.url.path == "/v27.0/debug_token"
    assert debug.url.params["input_token"] == TOKEN
    assert profile.url.path == f"/v27.0/{IG_ID}"
    assert len(requests) == 4  # 同一個帳號只查一次
    assert (account.platform_user_id, account.account_name) == (IG_ID, "mediagentlab")


def test_exchange_code_without_any_shared_account_fails():
    def handler(request, n):
        if n == 1:
            return httpx.Response(200, json={"access_token": TOKEN})
        if n == 2:
            return assigned()
        return httpx.Response(200, json={"data": {"is_valid": True, "granular_scopes": []}})

    with pytest.raises(OAuthFailed, match="no Instagram"):
        run(handler, lambda a: a.exchange_code("the-code", REDIRECT))


def test_exchange_code_with_several_shared_accounts_asks_for_one():
    """一次連結只對應一個平台帳號（重新連結時以識別碼比對），不猜要用哪一個。"""

    def handler(request, n):
        if n == 1:
            return httpx.Response(200, json={"access_token": TOKEN})
        return assigned((IG_ID, "mediagentlab"), ("17841400000000001", "other_club"))

    with pytest.raises(OAuthFailed, match="exactly one"):
        run(handler, lambda a: a.exchange_code("the-code", REDIRECT))


def test_exchange_error_is_oauth_failed_without_leaking_secrets():
    def handler(request, n):
        return graph_error(400, f"Invalid verification code format. secret={SECRET} code=the-code")

    with pytest.raises(OAuthFailed) as error:
        run(handler, lambda a: a.exchange_code("the-code", REDIRECT))
    assert SECRET not in str(error.value)
    assert "the-code" not in str(error.value)


@pytest.mark.parametrize("status", [429, 500, 503])
def test_exchange_when_meta_is_unavailable_is_not_an_authorization_failure(status):
    with pytest.raises(VerificationUnavailable):
        run(lambda request, n: httpx.Response(status), lambda a: a.exchange_code("c", REDIRECT))


def test_exchange_when_meta_cannot_be_reached_is_not_an_authorization_failure():
    def handler(request, n):
        raise httpx.ConnectError("boom")

    with pytest.raises(VerificationUnavailable):
        run(handler, lambda a: a.exchange_code("c", REDIRECT))


# ---------- 三步發佈 ----------


def test_begin_creates_an_image_container_with_the_caption():
    result, (request,) = run(
        lambda request, n: httpx.Response(200, json={"id": "c-1"}),
        lambda a: a.begin(CREDENTIAL, CONTENT),
    )

    assert result == Started("c-1")
    assert (request.method, str(request.url)) == ("POST", f"{GRAPH}/{IG_ID}/media")
    assert form(request) == {"image_url": IMAGE.url, "caption": CONTENT.text}
    assert request.headers["authorization"] == f"Bearer {TOKEN}"


def test_begin_without_an_image_is_rejected_without_calling_instagram():
    result, requests = run(lambda r, n: httpx.Response(200), lambda a: a.begin(CREDENTIAL, PostContent("hi")))

    assert requests == []
    assert isinstance(result, Failed) and result.reason == FailureReason.CONTENT_REJECTED


def test_image_without_a_public_https_url_is_not_sent():
    local = PostContent(text="x", image=ImageVersion(**{**IMAGE.__dict__, "url": "/media/abc.jpg"}))

    result, requests = run(lambda r, n: httpx.Response(200), lambda a: a.begin(CREDENTIAL, local))

    assert requests == []
    assert isinstance(result, Failed) and "https" in result.message


@pytest.mark.parametrize(
    ("status_code", "expected"),
    [
        ("FINISHED", CheckStatus.READY),
        ("IN_PROGRESS", CheckStatus.PROCESSING),
        ("PUBLISHED", CheckStatus.PUBLISHED),
        ("ERROR", CheckStatus.FAILED),
        ("EXPIRED", CheckStatus.FAILED),
        ("SOMETHING_NEW", CheckStatus.UNKNOWN),
    ],
)
def test_check_maps_container_status(status_code, expected):
    result, (request,) = run(
        lambda r, n: httpx.Response(200, json={"id": "c-1", "status_code": status_code, "status": "x"}),
        lambda a: a.check(CREDENTIAL, "c-1"),
    )

    assert result.status == expected
    assert request.url.path == "/v27.0/c-1"
    assert request.url.params["fields"] == "status_code,status"
    if expected == CheckStatus.PUBLISHED:
        assert result.published == Published()


def test_check_error_reports_the_platform_reason():
    result, _ = run(
        lambda r, n: httpx.Response(200, json={"status_code": "ERROR", "status": "2207052"}),
        lambda a: a.check(CREDENTIAL, "c-1"),
    )

    assert result.failed.reason == FailureReason.CONTENT_REJECTED
    assert "2207052" in result.failed.message


def test_check_without_a_reference_or_with_an_error_is_unknown():
    result, requests = run(lambda r, n: httpx.Response(500), lambda a: a.check(CREDENTIAL, None))
    assert (result.status, requests) == (CheckStatus.UNKNOWN, [])

    result, _ = run(lambda r, n: httpx.Response(400, json={}), lambda a: a.check(CREDENTIAL, "c-1"))
    assert result.status == CheckStatus.UNKNOWN


def test_finalize_publishes_and_returns_permalink():
    def handler(request, n):
        if n == 1:
            return httpx.Response(200, json={"id": "m-9"})
        return httpx.Response(200, json={"id": "m-9", "permalink": "https://www.instagram.com/p/XYZ/"})

    result, (publish, permalink) = run(handler, lambda a: a.finalize(CREDENTIAL, "c-1"))

    assert result == Published(post_id="m-9", post_url="https://www.instagram.com/p/XYZ/")
    assert (publish.method, str(publish.url)) == ("POST", f"{GRAPH}/{IG_ID}/media_publish")
    assert form(publish) == {"creation_id": "c-1"}
    assert permalink.url.path == "/v27.0/m-9"


def test_finalize_without_permalink_is_still_published():
    def handler(request, n):
        return httpx.Response(200, json={"id": "m-9"}) if n == 1 else httpx.Response(500)

    result, _ = run(handler, lambda a: a.finalize(CREDENTIAL, "c-1"))

    assert result == Published(post_id="m-9", post_url=None)


UNAVAILABLE, REJECTED = FailureReason.PLATFORM_UNAVAILABLE, FailureReason.CONTENT_REJECTED


@pytest.mark.parametrize(
    ("response", "reason"),
    [
        (graph_error(400, "Error validating access token", code=190), FailureReason.AUTH_INVALID),
        (graph_error(401, "unauthorized"), FailureReason.AUTH_INVALID),
        (graph_error(400, "Instagram server error", code=-1, subcode=2207001), UNAVAILABLE),
        (graph_error(400, "download timed out", code=-2, subcode=2207003), UNAVAILABLE),
        (graph_error(400, "try again later", transient=True), UNAVAILABLE),
        (graph_error(400, "daily limit reached", code=9, subcode=2207042), UNAVAILABLE),
        (graph_error(400, "media could not be fetched", code=9004, subcode=2207052), REJECTED),
        (graph_error(400, "caption too long", code=36004, subcode=2207010), REJECTED),
        (httpx.Response(503), UNAVAILABLE),
    ],
)
def test_platform_errors_are_classified(response, reason):
    result, _ = run(lambda r, n: response, lambda a: a.begin(CREDENTIAL, CONTENT))

    assert isinstance(result, Failed)
    assert result.reason == reason


def test_begin_retries_server_errors_twice():
    result, requests = run(lambda r, n: httpx.Response(500), lambda a: a.begin(CREDENTIAL, CONTENT))

    assert len(requests) == 3
    assert result.reason == FailureReason.PLATFORM_UNAVAILABLE


def test_finalize_does_not_retry_server_errors():
    """media_publish 回 5xx 時貼文可能已經發出：不重送，交給引擎查 container 狀態。"""
    result, requests = run(lambda r, n: httpx.Response(500), lambda a: a.finalize(CREDENTIAL, "c-1"))

    assert len(requests) == 1
    assert result.reason == FailureReason.PLATFORM_UNAVAILABLE


def test_finalize_without_a_response_is_timeout():
    def handler(request, n):
        raise httpx.ReadTimeout("no response")

    result, _ = run(handler, lambda a: a.finalize(CREDENTIAL, "c-1"))

    assert result.reason == FailureReason.TIMEOUT


def test_failure_message_never_contains_token_or_secret():
    response = graph_error(400, f"bad request access_token={TOKEN} appsecret={SECRET}")

    result, _ = run(lambda r, n: response, lambda a: a.begin(CREDENTIAL, CONTENT))

    assert TOKEN not in result.message
    assert SECRET not in result.message


def test_caption_length_counts_characters():
    assert InstagramAdapter().count_chars("社課🎸") == 3


@pytest.mark.parametrize("debug_data", [[], "oops", {"granular_scopes": ["instagram_basic"]}])
def test_unexpected_response_shapes_are_authorization_failures(debug_data):
    def handler(request, n):
        if n == 1:
            return httpx.Response(200, json={"access_token": TOKEN})
        if n == 2:
            return assigned()
        return httpx.Response(200, json={"data": debug_data})

    with pytest.raises(OAuthFailed):
        run(handler, lambda a: a.exchange_code("the-code", REDIRECT))


@pytest.mark.parametrize("expires_in", ["never", 10**20, [1], -5, 0])
def test_odd_expiry_values_count_as_unknown(expires_in):
    """授權已經成功：到期時間看不懂時視為未知（需求 4.2），不讓導回變成 500。"""

    def handler(request, n):
        if n == 1:
            return httpx.Response(200, json={"access_token": TOKEN, "expires_in": expires_in})
        return assigned((IG_ID, "mediagentlab"))

    account, _ = run(handler, lambda a: a.exchange_code("the-code", REDIRECT))

    assert account.expires_at is None


def _fallback_handler(*profiles):
    def handler(request, n):
        if n == 1:
            return httpx.Response(200, json={"access_token": TOKEN})
        if n == 2:
            return assigned()
        if n == 3:
            ids = [IG_ID, "17841400000000001"][: len(profiles)]
            return httpx.Response(
                200, json={"data": {"granular_scopes": [{"scope": "instagram_basic", "target_ids": ids}]}}
            )
        return profiles[n - 4]

    return handler


def test_fallback_lookup_when_meta_is_unavailable_is_not_an_authorization_failure():
    """兩個帳號其中一個查詢遇到 503：不能只連結另一個（會繞過「只能分享一個」），也不能說沒有分享帳號。"""
    handler = _fallback_handler(
        httpx.Response(503), httpx.Response(200, json={"id": "17841400000000001", "username": "x"})
    )

    with pytest.raises(VerificationUnavailable):
        run(handler, lambda a: a.exchange_code("the-code", REDIRECT))


def test_fallback_skips_accounts_the_token_cannot_read():
    handler = _fallback_handler(
        graph_error(400, "Unsupported get request", code=100),
        httpx.Response(200, json={"id": "17841400000000001", "username": "other_club"}),
    )

    account, _ = run(handler, lambda a: a.exchange_code("the-code", REDIRECT))

    assert account.account_name == "other_club"


@pytest.mark.parametrize(
    ("response", "reason"),
    [
        (graph_error(403, "missing permission", code=10), FailureReason.AUTH_INVALID),
        (graph_error(403, "permission denied", code=200), FailureReason.AUTH_INVALID),
        (graph_error(400, "Application request limit reached", code=4), UNAVAILABLE),
        (graph_error(400, "User request limit reached", code=17), UNAVAILABLE),
        (graph_error(400, "suspected spam", code=4, subcode=2207051), REJECTED),
    ],
)
def test_permission_and_rate_limit_errors_are_classified(response, reason):
    result, _ = run(lambda r, n: response, lambda a: a.begin(CREDENTIAL, CONTENT))

    assert result.reason == reason


def test_api_access_blocked_does_not_mark_the_account_invalid():
    """code 200 一般是權限不足（要重新授權），但「API access blocked」是 Meta 封鎖整個 App：
    帳號授權本身沒問題，不標示失效，歸為其他並提示到 Meta 後台處理。"""
    response = graph_error(400, "API access blocked.", code=200)

    result, _ = run(lambda r, n: response, lambda a: a.begin(CREDENTIAL, CONTENT))

    assert result.reason == FailureReason.OTHER
    assert "API access blocked" in result.message
    assert "Meta" in result.message and "後台" in result.message
