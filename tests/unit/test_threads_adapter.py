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
    OAuthFailed,
    PostContent,
    Published,
    Started,
)
from app.m2_platforms.adapters.threads import ThreadsAdapter

TOKEN = "THQVJ-long-lived-token"
SECRET = "app-secret-value"
CREDENTIAL = {"access_token": TOKEN, "user_id": "17841", "username": "ntu_guitar"}
REDIRECT = "https://localhost:8443/api/v1/platform-accounts/oauth/callback"


@pytest.fixture(autouse=True)
def app_configured(monkeypatch):
    monkeypatch.setattr(get_settings(), "threads_app_id", "9990001")
    monkeypatch.setattr(get_settings(), "threads_app_secret", SECRET)


def form(request: httpx.Request) -> dict[str, str]:
    return {key: values[0] for key, values in parse_qs(request.content.decode()).items()}


def run(handler, call):
    """用假的 HTTP 傳輸層執行一次 Adapter 呼叫，回傳（結果, 送出的請求）。"""
    requests: list[httpx.Request] = []

    def recording(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return handler(request, len(requests))

    adapter = ThreadsAdapter(transport=httpx.MockTransport(recording), retry_delay=0)
    return asyncio.run(call(adapter)), requests


def graph_error(status, message, code=100, subcode=None):
    error = {"message": message, "type": "OAuthException", "code": code}
    if subcode:
        error["error_subcode"] = subcode
    return httpx.Response(status, json={"error": error})


# ---------- 授權 ----------


def test_authorization_url_requests_only_publish_scopes():
    url = urlparse(ThreadsAdapter().authorization_url("state-123", REDIRECT))
    query = parse_qs(url.query)

    assert f"{url.scheme}://{url.netloc}{url.path}" == "https://threads.com/oauth/authorize"
    assert query == {
        "client_id": ["9990001"],
        "redirect_uri": [REDIRECT],
        "scope": ["threads_basic,threads_content_publish"],
        "response_type": ["code"],
        "state": ["state-123"],
    }
    assert SECRET not in url.geturl()


@pytest.mark.parametrize("missing", ["threads_app_id", "threads_app_secret"])
def test_authorization_requires_app_configuration(monkeypatch, missing):
    monkeypatch.setattr(get_settings(), missing, "")

    with pytest.raises(OAuthFailed):
        ThreadsAdapter().authorization_url("state-123", REDIRECT)


def test_exchange_code_returns_long_lived_account():
    def handler(request, n):
        if n == 1:
            return httpx.Response(200, json={"access_token": "short", "user_id": 17841})
        if n == 2:
            return httpx.Response(200, json={"access_token": TOKEN, "expires_in": 5183944})
        return httpx.Response(200, json={"id": "17841", "username": "ntu_guitar"})

    account, requests = run(handler, lambda a: a.exchange_code("the-code", REDIRECT))

    exchange, long_lived, profile = requests
    assert (exchange.method, str(exchange.url)) == ("POST", "https://graph.threads.com/oauth/access_token")
    assert form(exchange) == {
        "client_id": "9990001",
        "client_secret": SECRET,
        "grant_type": "authorization_code",
        "redirect_uri": REDIRECT,
        "code": "the-code",
    }
    assert long_lived.url.path == "/access_token"
    assert dict(long_lived.url.params) == {
        "grant_type": "th_exchange_token",
        "client_secret": SECRET,
        "access_token": "short",
    }
    assert profile.url.path == "/v1.0/me"
    assert profile.url.params["access_token"] == TOKEN
    assert (account.platform_user_id, account.account_name) == ("17841", "ntu_guitar")
    assert account.credential == CREDENTIAL
    assert abs(account.expires_at - (clock.now() + timedelta(seconds=5183944))) < timedelta(seconds=5)


def test_exchange_error_is_oauth_failed_without_leaking_secret():
    def handler(request, n):
        return httpx.Response(
            400,
            json={
                "error_type": "OAuthException",
                "code": 400,
                "error_message": f"Matching code was not found or was already used ({SECRET})",
            },
        )

    with pytest.raises(OAuthFailed) as error:
        run(handler, lambda a: a.exchange_code("used-code", REDIRECT))

    assert SECRET not in str(error.value) and "used-code" not in str(error.value)


# ---------- 三步發佈 ----------


def test_begin_creates_text_container():
    result, requests = run(
        lambda request, n: httpx.Response(200, json={"id": "container-1"}),
        lambda a: a.begin(CREDENTIAL, PostContent(text="本週三 19:00 社課")),
    )

    assert result == Started("container-1")
    assert (requests[0].method, str(requests[0].url)) == (
        "POST",
        "https://graph.threads.com/v1.0/17841/threads",
    )
    assert form(requests[0]) == {"media_type": "TEXT", "text": "本週三 19:00 社課", "access_token": TOKEN}


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        ("FINISHED", CheckStatus.READY),
        ("IN_PROGRESS", CheckStatus.PROCESSING),
        ("PUBLISHED", CheckStatus.PUBLISHED),
        ("ERROR", CheckStatus.FAILED),
        ("EXPIRED", CheckStatus.FAILED),
    ],
)
def test_check_maps_container_status(status, expected):
    result, requests = run(
        lambda request, n: httpx.Response(200, json={"status": status, "error_message": "UNKNOWN"}),
        lambda a: a.check(CREDENTIAL, "container-1"),
    )

    assert result.status == expected
    assert requests[0].url.path == "/v1.0/container-1"
    assert requests[0].url.params["fields"] == "status,error_message"


def test_check_without_a_reference_or_with_an_error_is_unknown():
    no_ref, requests = run(lambda request, n: httpx.Response(200), lambda a: a.check(CREDENTIAL, None))
    errored, _ = run(lambda request, n: httpx.Response(500), lambda a: a.check(CREDENTIAL, "container-1"))

    assert no_ref.status == CheckStatus.UNKNOWN and requests == []
    assert errored.status == CheckStatus.UNKNOWN


def test_finalize_publishes_and_returns_permalink():
    def handler(request, n):
        if n == 1:
            return httpx.Response(200, json={"id": "media-9"})
        return httpx.Response(
            200, json={"id": "media-9", "permalink": "https://www.threads.com/@ntu_guitar/post/abc"}
        )

    result, requests = run(handler, lambda a: a.finalize(CREDENTIAL, "container-1"))

    assert result == Published(post_id="media-9", post_url="https://www.threads.com/@ntu_guitar/post/abc")
    assert requests[0].url.path == "/v1.0/17841/threads_publish"
    assert form(requests[0]) == {"creation_id": "container-1", "access_token": TOKEN}
    assert requests[1].url.path == "/v1.0/media-9"


def test_finalize_without_permalink_is_still_published():
    def handler(request, n):
        return httpx.Response(200, json={"id": "media-9"}) if n == 1 else httpx.Response(500)

    result, _ = run(handler, lambda a: a.finalize(CREDENTIAL, "container-1"))

    assert result == Published(post_id="media-9", post_url=None)


# ---------- 失敗原因與重試 ----------


def test_invalid_token_is_auth_invalid():
    result, requests = run(
        lambda request, n: graph_error(400, "Error validating access token: Session has expired", code=190),
        lambda a: a.begin(CREDENTIAL, PostContent(text="x")),
    )

    assert isinstance(result, Failed) and result.reason == FailureReason.AUTH_INVALID
    assert len(requests) == 1


def test_begin_retries_server_errors_twice():
    result, requests = run(
        lambda request, n: httpx.Response(503, text="upstream"),
        lambda a: a.begin(CREDENTIAL, PostContent(text="x")),
    )

    assert result.reason == FailureReason.PLATFORM_UNAVAILABLE
    assert len(requests) == 3


def test_begin_recovers_when_a_retry_succeeds():
    def handler(request, n):
        return httpx.Response(503) if n == 1 else httpx.Response(200, json={"id": "container-2"})

    result, requests = run(handler, lambda a: a.begin(CREDENTIAL, PostContent(text="x")))

    assert result == Started("container-2") and len(requests) == 2


def test_finalize_does_not_retry_server_errors():
    result, requests = run(
        lambda request, n: httpx.Response(500, text="oops"),
        lambda a: a.finalize(CREDENTIAL, "container-1"),
    )

    assert result.reason == FailureReason.PLATFORM_UNAVAILABLE
    assert len(requests) == 1


def test_finalize_without_a_response_is_timeout():
    def handler(request, n):
        raise httpx.ReadTimeout("no response")

    result, requests = run(handler, lambda a: a.finalize(CREDENTIAL, "container-1"))

    assert result.reason == FailureReason.TIMEOUT and len(requests) == 1


def test_rejected_content_is_content_rejected():
    result, _ = run(
        lambda request, n: graph_error(400, "Param text must be at most 500 characters long."),
        lambda a: a.begin(CREDENTIAL, PostContent(text="x" * 501)),
    )

    assert result.reason == FailureReason.CONTENT_REJECTED
    assert "500 characters" in result.message


def test_failure_message_never_contains_token():
    result, _ = run(
        lambda request, n: graph_error(400, f"Bad request for access_token={TOKEN} secret {SECRET}"),
        lambda a: a.begin(CREDENTIAL, PostContent(text="x")),
    )

    assert TOKEN not in result.message and SECRET not in result.message


def test_count_chars_counts_emoji_as_utf8_bytes():
    adapter = ThreadsAdapter()

    assert adapter.count_chars("社課公告 abc") == 8
    assert adapter.count_chars("社課🎸") == 2 + 4
    assert adapter.count_chars("👍🏽") == 8


def image_version(url):
    from app.core.platforms import ImageVersion

    return ImageVersion(url=url, storage_key="k.jpg", sha256="s", width=1080, height=1350, variant="original")


def test_begin_creates_image_container_from_the_public_url():
    result, requests = run(
        lambda request, n: httpx.Response(200, json={"id": "container-2"}),
        lambda a: a.begin(
            CREDENTIAL, PostContent(text="社課公告", image=image_version("https://media.club.tw/poster.jpg"))
        ),
    )

    assert result == Started("container-2")
    assert form(requests[0]) == {
        "media_type": "IMAGE",
        "image_url": "https://media.club.tw/poster.jpg",
        "text": "社課公告",
        "access_token": TOKEN,
    }


def test_image_without_a_public_https_url_is_not_sent():
    """Threads 由平台主動下載圖片；本機的 /media 網址它連不到，不送出並說明原因。"""
    result, requests = run(
        lambda request, n: httpx.Response(200, json={"id": "container-3"}),
        lambda a: a.begin(CREDENTIAL, PostContent(text="社課公告", image=image_version("/media/poster.jpg"))),
    )

    assert requests == []
    assert result.reason == FailureReason.OTHER and "MEDIA_BASE_URL" in result.message
