"""mediagent 後端：組裝 router、Request ID、錯誤處理與健康檢查，並提供前端建置後的靜態檔。"""

import asyncio
import contextlib
import logging
import os
import uuid
from collections.abc import AsyncIterator
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.routing import Match, Mount
from starlette.types import Scope

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


class RedactOAuthQuery(logging.Filter):
    """uvicorn 的存取紀錄會寫出完整網址；OAuth 回呼的查詢字串含授權碼與 state，一律濾掉（NFR-02）。"""

    def filter(self, record: logging.LogRecord) -> bool:
        args = record.args
        # uvicorn 存取紀錄的參數：(來源位址, 方法, 含查詢字串的路徑, HTTP 版本, 狀態碼)
        if isinstance(args, tuple) and len(args) >= 3 and isinstance(args[2], str):
            path, has_query, _ = args[2].partition("?")
            if has_query and "/oauth/" in path:
                record.args = (*args[:2], f"{path}?[redacted]", *args[3:])
        return True


logging.getLogger("uvicorn.access").addFilter(RedactOAuthQuery())

@contextlib.asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    """服務啟動時開始排程迴圈（SCHEDULER_ENABLED=0 時不啟動），關閉時停止。"""
    task = None
    if get_settings().scheduler_enabled:
        from .m5_publishing import scheduler

        task = asyncio.create_task(scheduler.run_loop())
    yield
    if task is not None:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task


app = FastAPI(
    title="mediagent API",
    version="0.1.0",
    description="社團多平台貼文同步發佈服務（原型）",
    lifespan=lifespan,
)
install_error_handlers(app)


@app.middleware("http")
async def request_id_middleware(request: Request, call_next):
    # 前端有帶 X-Request-Id 就沿用，沒有就自行產生；回應標頭一律回傳（《API 設計》1.1）
    request.state.request_id = request.headers.get(REQUEST_ID_HEADER) or str(uuid.uuid4())
    response = await call_next(request)
    response.headers[REQUEST_ID_HEADER] = request.state.request_id
    return response


@app.get("/media/{key}", include_in_schema=False)
def media(key: str):
    """貼文圖片（本機檔案或資料庫）。網址是隨機的 storage key，平台發文時從這裡下載。"""
    from fastapi.responses import FileResponse, RedirectResponse, Response

    from .core.media import KEY_PATTERN, LocalMediaStorage, S3MediaStorage, get_storage

    not_found = JSONResponse(status_code=404, content={"code": "NOT_FOUND", "message": "找不到圖片"})
    storage = get_storage()
    if isinstance(storage, S3MediaStorage):
        # 物件儲存是公開讀取：轉到 bucket 的網址，不經過後端傳送圖片
        if not KEY_PATTERN.fullmatch(key):
            return not_found
        return RedirectResponse(storage.url(key), status_code=307)
    if isinstance(storage, LocalMediaStorage):
        path = storage.path(key)
        if path is None or not path.is_file():
            return not_found
        return FileResponse(path, media_type="image/jpeg")
    try:
        data = storage.read(key)
    except FileNotFoundError:
        return not_found
    # 圖片內容不會變（換圖會產生新的 key），可以讓瀏覽器與平台長時間快取
    cache = {"Cache-Control": "public, max-age=31536000, immutable"}
    return Response(data, media_type="image/jpeg", headers=cache)


@app.get("/health", tags=["維運"])
def health() -> JSONResponse:
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception:
        return JSONResponse(status_code=503, content={"status": "degraded", "database": "error"})
    return JSONResponse(content={"status": "ok", "database": "ok"})


def _include_routers() -> None:
    from .f_audit.router import router as audit_router
    from .m1_accounts.router import router as accounts_router
    from .m1_accounts.router import users_router
    from .m2_platforms.router import router as platforms_router
    from .m3_posts.router import router as posts_router
    from .m4_scheduling.router import router as scheduling_router
    from .m5_publishing.internal_router import router as internal_router
    from .m5_publishing.router import router as publishing_router

    for router in (
        accounts_router,
        users_router,
        platforms_router,
        posts_router,
        scheduling_router,
        publishing_router,
        audit_router,
        internal_router,
    ):
        app.include_router(router, prefix=API_PREFIX)


def _register_adapters() -> None:
    from .core import platforms

    if get_settings().platform_mode == "mock":
        platforms.register_mock_adapters()
        return

    from .m2_platforms.adapters.discord import DiscordAdapter
    from .m2_platforms.adapters.instagram import InstagramAdapter
    from .m2_platforms.adapters.threads import ThreadsAdapter

    platforms.register_adapter(DiscordAdapter())
    platforms.register_adapter(ThreadsAdapter())
    platforms.register_adapter(InstagramAdapter())


_include_routers()
_register_adapters()


# ---------- 前端靜態檔（foundation-plan D-06 同源部署） ----------
# Docker 映像檔把 frontend/dist 複製到 /srv/frontend/dist；本機沒有建置過前端時不掛載
FRONTEND_DIST = Path(
    os.environ.get("FRONTEND_DIST", Path(__file__).resolve().parents[1] / "frontend" / "dist")
)


class SPAStaticFiles(StaticFiles):
    """找不到的頁面路徑（例如 /posts/12）回傳 index.html，交給前端路由；找不到的檔案（有副檔名）維持 404。"""

    async def get_response(self, path: str, scope: Scope):
        try:
            response = await super().get_response(path, scope)
        except StarletteHTTPException as exc:
            if exc.status_code != 404 or "." in path.rsplit("/", 1)[-1]:
                raise
            response = await super().get_response("index.html", scope)
        # index.html 每次都向伺服器確認，重新部署後才不會引用已不存在的舊檔名
        if response.headers.get("content-type", "").startswith("text/html"):
            response.headers["Cache-Control"] = "no-cache"
        return response


class FrontendMount(Mount):
    """掛在 / 但不接手 /api：API 路徑的 404、405 維持原本的 JSON 錯誤格式。"""

    def matches(self, scope: Scope) -> tuple[Match, Scope]:
        path = scope.get("path", "")
        if path == "/api" or path.startswith("/api/"):
            return Match.NONE, {}
        return super().matches(scope)


def mount_frontend(application: FastAPI, dist_dir: Path) -> None:
    # 必須在所有 API router 之後加入，路由才會優先比對 API
    if (dist_dir / "index.html").is_file():
        application.router.routes.append(
            FrontendMount("/", app=SPAStaticFiles(directory=dist_dir, html=True), name="frontend")
        )


mount_frontend(app, FRONTEND_DIST)
