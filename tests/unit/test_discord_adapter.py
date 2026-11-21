import asyncio
import json

import httpx

from app.core.enums import FailureReason
from app.core.platforms import CheckStatus, Failed, PostContent, Published
from app.m2_platforms.adapters.discord import DiscordAdapter

TOKEN = "s3cr3t-Token_value"
URL = f"https://discord.com/api/webhooks/123456/{TOKEN}"
CREDENTIAL = {"webhook_url": URL, "webhook_id": "123456", "guild_id": "111", "channel_id": "222"}


def run_begin(handler, text="本週三 19:00 社課"):
    calls = []

    def recording(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return handler(request, len(calls))

    adapter = DiscordAdapter(transport=httpx.MockTransport(recording))
    result = asyncio.run(adapter.begin(CREDENTIAL, PostContent(text=text)))
    return result, calls


def test_begin_returns_message_url():
    result, calls = run_begin(
        lambda request, n: httpx.Response(200, json={"id": "555", "channel_id": "222"})
    )

    assert result == Published(post_id="555", post_url="https://discord.com/channels/111/222/555")
    request = calls[0]
    assert request.method == "POST"
    assert str(request.url) == f"{URL}?wait=true"
    assert json.loads(request.content) == {"content": "本週三 19:00 社課"}


def test_unknown_webhook_is_auth_invalid():
    result, calls = run_begin(
        lambda request, n: httpx.Response(404, json={"message": "Unknown Webhook", "code": 10015})
    )

    assert isinstance(result, Failed) and result.reason == FailureReason.AUTH_INVALID
    assert "Unknown Webhook" in result.message
    assert len(calls) == 1


def test_error_message_never_contains_the_webhook_token():
    result, _ = run_begin(
        lambda request, n: httpx.Response(400, json={"message": f"bad request to {URL}"})
    )

    assert result.reason == FailureReason.CONTENT_REJECTED
    assert TOKEN not in result.message


def test_rate_limit_retries_then_succeeds():
    def handler(request, n):
        if n == 1:
            return httpx.Response(429, json={"retry_after": 0.01})
        return httpx.Response(200, json={"id": "555", "channel_id": "222"})

    result, calls = run_begin(handler)

    assert isinstance(result, Published)
    assert len(calls) == 2


def test_rate_limited_every_time_gives_up_after_two_retries():
    result, calls = run_begin(lambda request, n: httpx.Response(429, json={"retry_after": 0.01}))

    assert result.reason == FailureReason.PLATFORM_UNAVAILABLE
    assert len(calls) == 3


def test_server_error_is_platform_unavailable_and_is_not_retried():
    # 會發文的呼叫遇到 5xx 不自動重試：無法確定訊息有沒有發出（foundation-plan D-11）
    result, calls = run_begin(lambda request, n: httpx.Response(503, text="upstream down"))

    assert result.reason == FailureReason.PLATFORM_UNAVAILABLE
    assert len(calls) == 1


def test_connection_error_is_platform_unavailable():
    def handler(request, n):
        raise httpx.ConnectError("connection refused")

    result, _ = run_begin(handler)

    assert result.reason == FailureReason.PLATFORM_UNAVAILABLE


def test_read_timeout_is_timeout_because_the_outcome_is_unknown():
    def handler(request, n):
        raise httpx.ReadTimeout("no response")

    result, calls = run_begin(handler)

    assert result.reason == FailureReason.TIMEOUT
    assert len(calls) == 1


def test_redirect_is_not_followed():
    result, calls = run_begin(
        lambda request, n: httpx.Response(302, headers={"Location": "http://169.254.169.254/"})
    )

    assert isinstance(result, Failed)
    assert len(calls) == 1


def test_check_cannot_confirm_anything():
    adapter = DiscordAdapter(transport=httpx.MockTransport(lambda request: httpx.Response(500)))

    assert asyncio.run(adapter.check(CREDENTIAL, None)).status == CheckStatus.UNKNOWN
