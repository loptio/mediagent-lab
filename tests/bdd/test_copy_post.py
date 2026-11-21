"""驗收：複製為新草稿（spec/features/複製為新草稿.feature）。"""

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

scenarios(feature("複製為新草稿"))


@when(step('"X" 將貼文 "X" 複製為新草稿'))
def when_copy(world, a, b):
    response = world.request(a, "POST", f"/posts/{world.post_id(b)}/copies")
    if response.status_code == 201:
        world.posts["新草稿"] = response.json()["id"]
