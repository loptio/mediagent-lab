"""驗收：解除鎖定（spec/features/解除鎖定.feature）。"""

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

scenarios(feature("解除鎖定"))


@given(step('使用者帳號 "X" 已連續登入失敗 (?P<n>\\d+) 次'))
def given_failures(world, a, n):
    world.db.get(models.UserAccount, world.user_id(a)).failed_login_count = int(n)
    world.db.commit()


@when(step('"X" 解除 "X" 的鎖定'))
def when_unlock(world, a, b):
    world.request(a, "DELETE", f"/users/{world.user_id(b)}/lock")
