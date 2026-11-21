"""驗收：移除平台帳號（spec/features/移除平台帳號.feature）。"""

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
    "後置：改回草稿的貼文保留建立者、內容與圖片": "圖片功能（上傳、裁切、物件儲存）尚未實作",
}

scenarios(feature("移除平台帳號"))


@when(step('"X" 移除平台帳號 "X"'))
def when_remove(world, a, b):
    world.request(a, "DELETE", f"/platform-accounts/{world.account_id(b)}")
