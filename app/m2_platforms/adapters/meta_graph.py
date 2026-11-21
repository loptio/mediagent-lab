"""Threads 與 Instagram 共用的 Meta Graph API 工具：錯誤解析、過濾憑證、有限重試（foundation-plan D-11）。"""

import asyncio
from typing import Any, NamedTuple

import httpx

MAX_RETRIES = 2
MAX_ERROR_MESSAGE_LENGTH = 300
GRAPH_INVALID_TOKEN_CODE = 190


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
