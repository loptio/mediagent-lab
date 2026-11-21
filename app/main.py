"""mediagent 後端：組裝 router、Request ID、錯誤處理與健康檢查。"""

import logging
import uuid

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text

from .core.config import get_settings
from .core.db import engine
from .core.errors import REQUEST_ID_HEADER, install_error_handlers

API_PREFIX = "/api/v1"

logging.basicConfig(
    level=get_settings().log_level,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)

app = FastAPI(
    title="mediagent API",
    version="0.1.0",
    description="社團多平台貼文同步發佈服務（原型）",
)
install_error_handlers(app)


@app.middleware("http")
async def request_id_middleware(request: Request, call_next):
    # 前端有帶 X-Request-Id 就沿用，沒有就自行產生；回應標頭一律回傳（《API 設計》1.1）
    request.state.request_id = request.headers.get(REQUEST_ID_HEADER) or str(uuid.uuid4())
    response = await call_next(request)
    response.headers[REQUEST_ID_HEADER] = request.state.request_id
    return response


@app.get("/health", tags=["維運"])
def health() -> JSONResponse:
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception:
        return JSONResponse(status_code=503, content={"status": "degraded", "database": "error"})
    return JSONResponse(content={"status": "ok", "database": "ok"})


def _include_routers() -> None:
    from .m1_accounts.router import router as accounts_router
    from .m2_platforms.router import router as platforms_router
    from .m3_posts.router import router as posts_router
    from .m4_scheduling.router import router as scheduling_router
    from .m5_publishing.router import router as publishing_router

    for router in (
        accounts_router,
        platforms_router,
        posts_router,
        scheduling_router,
        publishing_router,
    ):
        app.include_router(router, prefix=API_PREFIX)


def _register_adapters() -> None:
    from .core import platforms

    if get_settings().platform_mode == "mock":
        platforms.register_mock_adapters()


_include_routers()
_register_adapters()
