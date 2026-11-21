"""驗收：執行排程發佈（spec/features/執行排程發佈.feature）。"""

from datetime import timedelta  # noqa: F401

from pytest_bdd import given, scenarios, then, when  # noqa: F401
from sqlalchemy import select  # noqa: F401

from app.core import clock, models  # noqa: F401
from tests.bdd import labels as L  # noqa: F401
from tests.bdd.conftest import feature
from tests.bdd.labels import code, tw_time  # noqa: F401
from tests.bdd.steps.common import Result, iso, rows, step  # noqa: F401

# 尚未實作的功能：{"Rule 或 Rule — Example": "原因"}
PENDING: dict[str, str] = {
    "前置：跳過已取消的發佈紀錄，不發佈到該平台帳號 — Threads 帳號已被移除，排程時只發佈到其餘平台帳號": "規格例子與 Background 衝突：Background 的 P1 同一時間到期也會發到 Threads，但例子預期 Threads 收到 0 則；待小組確認",
}

scenarios(feature("執行排程發佈"))


@given(step('貼文 "X" 由 "X" 設定排程'))
def given_scheduled_by(world, a, b):
    world.db.get(models.Post, world.post_id(a)).scheduled_by = world.user_id(b)
    world.db.commit()
