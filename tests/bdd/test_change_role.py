"""驗收：調整角色（spec/features/調整角色.feature）。"""

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

scenarios(feature("調整角色"))


@when(step('"X" 將 "X" 的角色調整為 "X"'))
def when_change_role(world, a, b, c):
    world.request(a, "PATCH", f"/users/{world.user_id(b)}", json={"role": code(L.ROLE, c)})
