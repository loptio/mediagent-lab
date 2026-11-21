"""Threads 與 Instagram 共用的 Meta Graph API 工具：錯誤解析、過濾憑證、有限重試（foundation-plan D-11）。"""

import asyncio
from datetime import datetime, timedelta
from typing import Any, NamedTuple

import httpx

from app.core import clock

MAX_RETRIES = 2
MAX_ERROR_MESSAGE_LENGTH = 300
GRAPH_INVALID_TOKEN_CODE = 190
# Token 有效期的合理上限；超過的值視為平台回傳異常
MAX_TOKEN_SECONDS = 10 * 365 * 24 * 3600


class GraphError(NamedTuple):
    message: str
    code: Any = None
    subcode: Any = None
    transient: bool = False


def scrub(text: str, *secrets: str | None) -> str:
    """錯誤訊息可能夾帶 Token 或 App 密鑰（例如平台把請求參數寫回訊息）：先濾掉再截短。"""
    for secret in secrets:
        if secret:
            text = text.replace(secret, "[redacted]")
    return text[:MAX_ERROR_MESSAGE_LENGTH]


def expires_at(expires_in: Any) -> datetime | None:
    """平台回傳的有效秒數 → 授權到期時間。授權已經成功，看不懂的值一律視為未知（需求 4.2），不讓導回失敗。"""
    if isinstance(expires_in, bool):
        return None
    try:
        seconds = int(expires_in)
    except (TypeError, ValueError, OverflowError):
        return None
    if not 0 < seconds <= MAX_TOKEN_SECONDS:
        return None
    return clock.now() + timedelta(seconds=seconds)


def error_details(response: httpx.Response) -> GraphError:
    """取出平台回應中的錯誤訊息與代碼。Graph API 與 Threads OAuth 端點的格式不同，兩種都處理。"""
    try:
        body = response.json()
    except ValueError:
        return GraphError(response.text)
    if isinstance(body, dict):
        error = body.get("error")
        if isinstance(error, dict):
            return GraphError(
                str(error.get("message", "")),
                error.get("code"),
                error.get("error_subcode"),
                error.get("is_transient") is True,
            )
        if "error_message" in body:
            return GraphError(str(body["error_message"]), body.get("code"))
    return GraphError(response.text)


async def send(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    *,
    retry_server_errors: bool,
    retry_delay: float,
    **kwargs: Any,
) -> httpx.Response:
    """送出請求；429 一律可重試，5xx 只有不會發文的呼叫才重試，最多重試 MAX_RETRIES 次。"""
    for attempt in range(MAX_RETRIES + 1):
        response = await client.request(method, url, **kwargs)
        status = response.status_code
        retryable = status == 429 or (retry_server_errors and status >= 500)
        if not retryable or attempt == MAX_RETRIES:
            break
        await asyncio.sleep(retry_delay)
    return response
