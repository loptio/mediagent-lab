# 單一映像檔（foundation-plan D-06）：先建置前端，再把靜態檔放進後端映像檔，由 FastAPI 在 / 提供
# 本機 Docker Compose 與正式環境共用

# ---------- 第一階段：建置前端 ----------
FROM node:24-alpine AS frontend

ENV COREPACK_ENABLE_DOWNLOAD_PROMPT=0
WORKDIR /web
RUN corepack enable

# 先複製依賴清單，程式碼變動時可沿用快取層
COPY frontend/package.json frontend/pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile

COPY frontend/ ./
RUN pnpm build

# ---------- 第二階段：後端 ----------
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /srv

# 先複製依賴清單，程式碼變動時可沿用快取層
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY app/ app/
COPY alembic/ alembic/
COPY alembic.ini .
COPY seeds/ seeds/
COPY scripts/entrypoint.sh scripts/entrypoint.sh
# app/main.py 預設從 /srv/frontend/dist 提供前端
COPY --from=frontend /web/dist frontend/dist

# 以非 root 使用者執行
RUN useradd --create-home --uid 1000 appuser \
    && chmod +x scripts/entrypoint.sh
USER appuser

EXPOSE 8000
ENTRYPOINT ["scripts/entrypoint.sh"]
# 部署平台會提供 PORT；本機預設 8000
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
