"""驗收：啟用帳號（spec/features/啟用帳號.feature）。"""

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

scenarios(feature("啟用帳號"))


@when(step('"X" 啟用 "X" 的帳號'))
def when_enable(world, a, b):
    world.request(a, "PUT", f"/users/{world.user_id(b)}/status", json={"status": "active"})
