"""驗收：登入（spec/features/登入.feature）。"""

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

scenarios(feature("登入"))


@given(step('使用者帳號 "X" 已連續登入失敗 (?P<n>\\d+) 次'))
def given_failures(world, a, n):
    world.db.get(models.UserAccount, world.user_id(a)).failed_login_count = int(n)
    world.db.commit()


@given(step('IP "X" 已於以下時間嘗試登入：'))
def given_ip_attempts(world, a, datatable):
    from app.m1_accounts.rate_limit import limiter

    for row in rows(datatable):
        limiter.attempt(a, tw_time(row["occurred_at"]), limit=10**6)


@given(step('IP "X" 在過去 1 分鐘內已嘗試登入 (?P<n>\\d+) 次'))
def given_recent_attempts(world, a, n):
    from app.m1_accounts.rate_limit import limiter

    for index in range(int(n)):
        limiter.attempt(a, clock.now() - timedelta(seconds=50 - index), limit=10**6)


@when(step('"X" 從 IP "X" 以密碼 "X" 登入'))
def when_login_from_ip(world, a, b, c):
    from fastapi.testclient import TestClient

    from app.main import app

    world.mark()
    with TestClient(app, client=(b, 50000)) as client:
        world.response = client.post("/api/v1/auth/login", json={"email": a, "password": c})


def _check_event(world, event, row):
    from tests.bdd.steps.common import check

    for column, raw in row.items():
        if column == "user":
            assert event.user_account_id == (world.user_id(raw) if raw else None)
        elif column == "event_type":
            assert event.event_type == code(L.EVENT_TYPE, raw)
        elif column == "failure_reason":
            assert event.failure_reason == code(L.LOGIN_FAILURE, raw)
        else:
            check(column, getattr(event, column), raw, "登入安全事件")


@then(step("系統新增一筆登入安全事件："))
def then_new_login_event(world, datatable):
    new = world.new_rows("login_event")
    [row] = rows(datatable)
    assert len(new) == 1, f"預期新增 1 筆登入安全事件，實際 {len(new)}"
    _check_event(world, new[0], row)


@then(step('該筆登入安全事件不包含 "X"'))
def then_event_without(world, a):
    [event] = world.new_rows("login_event")
    values = [str(getattr(event, column.key)) for column in models.LoginSecurityEvent.__table__.columns]
    assert all(a not in value for value in values)
