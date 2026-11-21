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
# httpx 會在 INFO 記錄每個請求的完整網址；Discord Webhook 網址等同密碼，不可進 Log（NFR-02）
for _noisy_logger in ("httpx", "httpcore"):
    logging.getLogger(_noisy_logger).setLevel(logging.WARNING)

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
        return

    from .core.enums import Platform
    from .m2_platforms.adapters.discord import DiscordAdapter
    from .m2_platforms.adapters.threads import ThreadsAdapter

    platforms.register_adapter(DiscordAdapter())
    platforms.register_adapter(ThreadsAdapter())
    # Instagram 的真實 Adapter 尚未實作：先提供內容限制，發佈時一律回報失敗
    platforms.register_adapter(platforms.UnavailableAdapter(Platform.INSTAGRAM))


_include_routers()
_register_adapters()
