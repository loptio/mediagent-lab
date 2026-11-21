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
PENDING: dict[str, str] = {}

scenarios(feature("修改貼文"))


@when(step('"X" 將貼文 "X" 的內容修改為 "X"'))
def when_edit(world, a, b, c):
    world.request(a, "PATCH", f"/posts/{world.post_id(b)}", json={"content": c})


@when(step('"X" 將貼文 "X" 的內容修改為長度 (?P<n>\\d+) 字元的文字'))
def when_edit_length(world, a, b, n):
    world.request(a, "PATCH", f"/posts/{world.post_id(b)}", json={"content": "字" * int(n)})
