"""驗收：刪除貼文（spec/features/刪除貼文.feature）。"""

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

scenarios(feature("刪除貼文"))


@when(step('"X" 刪除貼文 "X"'))
def when_delete(world, a, b):
    world.request(a, "DELETE", f"/posts/{world.post_id(b)}")


@given(step("發佈紀錄變更歷程中有以下紀錄："))
def given_history(world, datatable):
    from tests.bdd.steps.common import ensure_record

    for row in rows(datatable):
        record = ensure_record(world, world.post_id(row["post"]), world.account_id(row["account_name"]))
        actor = row.get("actor")
        world.db.add(
            models.PublishRecordHistory(
                publish_record_id=record.id,
                from_status=code(L.RECORD_STATUS, row["from_status"]),
                to_status=code(L.RECORD_STATUS, row["to_status"]),
                actor_type=code(L.ACTOR_TYPE, row["actor_type"]),
                actor_id=world.user_id(actor) if actor else None,
                reason=code(L.HISTORY_REASON, row["reason"]),
                changed_at=clock.now(),
            )
        )
    world.db.commit()
