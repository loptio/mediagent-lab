"""驗收：設定排程（spec/features/設定排程.feature）。"""

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
    "前置：目標平台帳號含 Instagram 時，貼文必須附加圖片": "BR-05（Instagram 必須附圖）尚未強制：圖片功能完成前無法附圖，強制會讓 Instagram 完全無法使用；圖片完成時一併實作",
}

scenarios(feature("設定排程"))


@when(step('"X" 將貼文 "X" 的排程時間設定為 "X"'))
def when_schedule(world, a, b, c):
    world.request(a, "PUT", f"/posts/{world.post_id(b)}/schedule", json={"scheduled_at": iso(c)})
