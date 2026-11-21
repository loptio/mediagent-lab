"""驗收：建立幹部帳號（spec/features/建立幹部帳號.feature）。"""

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

scenarios(feature("建立幹部帳號"))


@when(step('"X" 建立以下幹部帳號：'))
def when_create_user(world, a, datatable):
    [row] = rows(datatable)
    # 例子用雙引號包住需要保留前後空白的值（DataTable 會自動去掉空白）
    row = {k: v[1:-1] if len(v) >= 2 and v[0] == v[-1] == '"' else v for k, v in row.items()}
    body = {
        "email": row["email"],
        "name": row["name"],
        "role": code(L.ROLE, row["role"]) or "",
        "initial_password": row.get("password", ""),
    }
    world.request(a, "POST", "/users", json=body)
