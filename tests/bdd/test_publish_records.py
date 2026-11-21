"""驗收：查看發佈結果（spec/features/查看發佈結果.feature）。"""

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

scenarios(feature("查看發佈結果"))


@given(step('貼文 "X" 在平台帳號 "X" 的平台原始錯誤訊息為 "X"'))
def given_error_message(world, a, b, c):
    record = world.db.scalar(
        select(models.PublishRecord).where(
            models.PublishRecord.post_id == world.post_id(a),
            models.PublishRecord.platform_account_id == world.account_id(b),
        )
    )
    record.platform_error_message = c
    world.db.commit()


@when(step('"X" 查看貼文 "X" 的發佈結果'))
def when_view_records(world, a, b):
    world.request(a, "GET", f"/posts/{world.post_id(b)}/publish-records")
