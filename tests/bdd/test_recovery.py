"""驗收：發佈逾時恢復（spec/features/發佈逾時恢復.feature）。"""

from datetime import timedelta  # noqa: F401

from pytest_bdd import given, scenarios, then, when  # noqa: F401
from sqlalchemy import select  # noqa: F401

from app.core import clock, models  # noqa: F401
from tests.bdd import labels as L  # noqa: F401
from tests.bdd.conftest import feature
from tests.bdd.labels import code, tw_time  # noqa: F401
from tests.bdd.steps.common import Result, iso, rows, step  # noqa: F401

# 尚未實作的功能：{"Rule 或 Rule — Example": "原因"}
# 無法有效驗證、直接略過的例子（原因寫在值裡）
SKIP: dict[str, str] = {
    "後置：平台明確確認未發佈時，系統自動重新發佈到該平台帳號，結果出來前發佈紀錄維持待發佈 — 自動重新發佈尚未完成時，紀錄維持待發佈": "「發佈尚未完成」的測試替身會擋下這個帳號的所有寫回，即使沒有自動重送也會通過（不是有效的測試）；重送進行中的狀態要在非同步測試中觀察",
}

PENDING: dict[str, str] = {}

scenarios(feature("發佈逾時恢復"))


@given(step('貼文 "X" 於 "X" 進入發佈中'))
def given_publishing_started(world, a, b):
    post = world.db.get(models.Post, world.post_id(a))
    post.publishing_started_at = tw_time(b)
    world.db.commit()


@given(step('貼文 "X" 在平台帳號 "X" 已自動重新發佈 (?P<n>\\d+) 次'))
def given_auto_retried(world, a, b, n):
    record = world.db.scalar(
        select(models.PublishRecord).where(
            models.PublishRecord.post_id == world.post_id(a),
            models.PublishRecord.platform_account_id == world.account_id(b),
        )
    )
    record.auto_retry_count = int(n)
    world.db.commit()


@then(step('貼文 "X" 在平台帳號 "X" 的變更歷程為：'))
def then_history_of(world, a, b, datatable):
    from tests.bdd.steps.common import check

    world.db.expire_all()
    history = list(
        world.db.scalars(
            select(models.PublishRecordHistory)
            .join(models.PublishRecord)
            .where(
                models.PublishRecord.post_id == world.post_id(a),
                models.PublishRecord.platform_account_id == world.account_id(b),
            )
            .order_by(models.PublishRecordHistory.id)
        )
    )
    new = [h for h in history if h.id > world.baseline.get("history", 0)]
    expected = rows(datatable)
    assert len(new) == len(expected), [(h.from_status, h.to_status, h.reason) for h in new]
    for h, row in zip(new, expected, strict=True):
        for column, raw in row.items():
            check(column, getattr(h, column), raw, "變更歷程")
