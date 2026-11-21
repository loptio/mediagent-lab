"""錯誤處理：service 拋出 DomainError，由全域 handler 轉成《API 設計》1.3 的錯誤格式。"""

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger("mediagent")

REQUEST_ID_HEADER = "X-Request-Id"

_HTTP_STATUS_CODES = {
    401: "UNAUTHENTICATED",
    403: "FORBIDDEN",
    404: "NOT_FOUND",
}


class DomainError(Exception):
    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        detail: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.detail = detail
        self.headers = headers


def not_found(message: str = "找不到資源") -> DomainError:
    return DomainError(404, "NOT_FOUND", message)


def forbidden(message: str = "沒有權限執行此操作") -> DomainError:
    return DomainError(403, "FORBIDDEN", message)


def unauthenticated(message: str = "尚未登入或登入已失效") -> DomainError:
    return DomainError(401, "UNAUTHENTICATED", message)


def error_response(
    request: Request,
    status_code: int,
    code: str,
    message: str,
    detail: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    request_id = getattr(request.state, "request_id", "")
    body: dict[str, Any] = {"code": code, "message": message, "request_id": request_id}
    if detail is not None:
        body["detail"] = detail
    response = JSONResponse(status_code=status_code, content=body, headers=headers)
    response.headers[REQUEST_ID_HEADER] = request_id
    return response


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(DomainError)
    async def handle_domain_error(request: Request, exc: DomainError) -> JSONResponse:
        return error_response(
            request, exc.status_code, exc.code, exc.message, exc.detail, headers=exc.headers
        )

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        errors = [
            {"field": ".".join(str(part) for part in err["loc"][1:]), "message": err["msg"]}
            for err in exc.errors()
        ]
        return error_response(
            request, 400, "VALIDATION_ERROR", "請求的欄位缺漏或格式錯誤", {"errors": errors}
        )

    @app.exception_handler(StarletteHTTPException)
    async def handle_http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = _HTTP_STATUS_CODES.get(exc.status_code, "VALIDATION_ERROR")
        return error_response(
            request, exc.status_code, code, str(exc.detail), headers=getattr(exc, "headers", None)
        )

    @app.exception_handler(Exception)
    async def handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
        # 不把內部細節回給使用者；完整錯誤只寫進 Log
        request_id = getattr(request.state, "request_id", "")
        logger.exception("unhandled error", extra={"request_id": request_id})
        return error_response(request, 500, "INTERNAL_ERROR", "系統發生未預期的錯誤")
