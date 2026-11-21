"""驗收：修改貼文（spec/features/修改貼文.feature）。"""

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
    "前置：只有草稿與已排程狀態的貼文可以修改 — 修改已排程的貼文": "規格例子衝突：Background 的 P3 是「已排程但沒有任何目標」，BR-07 不允許這種狀態；依 BR-24 修改已排程貼文會檢查 BR-07 而回 NO_TARGET。待小組確認（修正 Background 或 BR-24）",
    "後置：已排程貼文修改成功後維持已排程，排程時間不變 — 修改已排程貼文的內容": "規格例子衝突：Background 的 P3 是「已排程但沒有任何目標」，BR-07 不允許這種狀態；依 BR-24 修改已排程貼文會檢查 BR-07 而回 NO_TARGET。待小組確認（修正 Background 或 BR-24）",
}

scenarios(feature("修改貼文"))


@when(step('"X" 將貼文 "X" 的內容修改為 "X"'))
def when_edit(world, a, b, c):
    world.request(a, "PATCH", f"/posts/{world.post_id(b)}", json={"content": c})


@when(step('"X" 將貼文 "X" 的內容修改為長度 (?P<n>\\d+) 字元的文字'))
def when_edit_length(world, a, b, n):
    world.request(a, "PATCH", f"/posts/{world.post_id(b)}", json={"content": "字" * int(n)})
