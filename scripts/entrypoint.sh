#!/bin/sh
# 容器啟動時先把資料庫升級到最新版本，再啟動服務
set -e
alembic upgrade head
exec "$@"
