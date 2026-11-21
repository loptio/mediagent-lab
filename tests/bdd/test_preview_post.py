"""驗收：預覽貼文（spec/features/預覽貼文.feature）。"""

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
    "後置：Instagram 預覽顯示 Instagram 版本（裁切後）的圖片": "圖片功能（上傳、裁切、物件儲存）尚未實作",
    "後置：Threads 與 Discord 預覽顯示原圖": "圖片功能（上傳、裁切、物件儲存）尚未實作",
}

scenarios(feature("預覽貼文"))


@when(step('"X" 預覽貼文 "X"'))
def when_preview(world, a, b):
    world.request(a, "GET", f"/posts/{world.post_id(b)}/preview")
