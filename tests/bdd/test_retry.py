"""驗收：重試發佈（spec/features/重試發佈.feature）。"""

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

scenarios(feature("重試發佈"))


@when(step('"X" 重試發佈貼文 "X"'))
def when_retry(world, a, b):
    world.request(a, "POST", f"/posts/{world.post_id(b)}/publish-jobs", json={"type": "retry"})
