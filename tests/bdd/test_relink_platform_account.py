"""驗收：重新連結平台帳號（spec/features/重新連結平台帳號.feature）。"""

from datetime import timedelta  # noqa: F401

from pytest_bdd import given, scenarios, then, when  # noqa: F401
from sqlalchemy import select  # noqa: F401

from app.core import clock, models  # noqa: F401
from tests.bdd import labels as L  # noqa: F401
from tests.bdd.conftest import feature
from tests.bdd.labels import code, tw_time  # noqa: F401
from tests.bdd.steps.common import Result, iso, rows, step  # noqa: F401

# 尚未實作的功能：{"Rule 或 Rule — Example": "原因"}
PENDING: dict[str, str] = {
    "前置：Threads、Instagram 的平台授權必須成功；失敗時保留原有資料 — Instagram 重新授權失敗": "規格例子衝突：同樣是到期的 Instagram 帳號，此例預期授權狀態「有效」，識別碼不符等兩例預期「失效」；依 BR-09 採「到期即失效」，此例待小組確認",
}

scenarios(feature("重新連結平台帳號"))


@given(step('平台 "X" 授權完成後回傳以下資訊：'))
def given_oauth_account(world, a, datatable):
    from app.core.platforms import OAuthAccount

    [row] = rows(datatable)
    world.mocks[code(L.PLATFORM, a)].oauth_account(
        OAuthAccount(
            platform_user_id=row["platform_user_id"],
            account_name=row["account_name"],
            credential={"access_token": row["credential"]},
            expires_at=tw_time(row.get("auth_expires_at", "")),
        )
    )


@given(step('平台 "X" 授權失敗'))
def given_oauth_fails(world, a):
    world.mocks[code(L.PLATFORM, a)].oauth_fail()


def _oauth(world, email, platform, account_id=None):
    """開始授權 → 平台導回 callback；以導回的結果代碼判斷成敗。"""
    from urllib.parse import parse_qs, urlparse

    body = {"platform": code(L.PLATFORM, platform)}
    if account_id is not None:
        body["platform_account_id"] = account_id
    started = world.request(email, "POST", "/platform-accounts/oauth-authorizations", json=body)
    if started.status_code != 200:
        return
    state = parse_qs(urlparse(started.json()["authorization_url"]).query)["state"][0]
    callback = world.client.get(
        "/api/v1/platform-accounts/oauth/callback",
        params={"code": "test-code", "state": state},
        follow_redirects=False,
    )
    result = parse_qs(urlparse(callback.headers["location"]).query)["result"][0]
    status = {"linked": 200, "relinked": 200, "PLATFORM_ACCOUNT_NAME_TAKEN": 409, "PLATFORM_ID_MISMATCH": 409}
    world.response = Result(status.get(result, 422), {"code": result})


def _check_auth_event(world, event, row):
    from tests.bdd.steps.common import check

    for column, raw in row.items():
        if column == "actor":
            assert event.actor_id == world.user_id(raw)
        elif column == "event_type":
            assert event.event_type == code(L.EVENT_TYPE, raw)
        elif column == "failure_reason":
            assert event.failure_reason == code(L.AUTH_FAILURE, raw)
        elif column == "platform":
            assert event.platform == code(L.PLATFORM, raw)
        else:
            check(column, getattr(event, column), raw, "平台授權事件")


@then(step("系統新增一筆平台授權事件："))
def then_new_auth_event(world, datatable):
    new = world.new_rows("auth_event")
    [row] = rows(datatable)
    assert len(new) == 1, f"預期新增 1 筆平台授權事件，實際 {len(new)}"
    _check_auth_event(world, new[0], row)


@then(step('該筆平台授權事件不包含 "X"'))
def then_auth_event_without(world, a):
    [event] = world.new_rows("auth_event")
    values = [str(getattr(event, column.key)) for column in models.PlatformAuthEvent.__table__.columns]
    assert all(a not in value for value in values)


@when(step('"X" 透過平台授權重新連結平台帳號 "X"'))
def when_relink_oauth(world, a, b):
    _oauth(world, a, world.db.get(models.PlatformAccount, world.account_id(b)).platform, world.account_id(b))


@when(step('"X" 以 Webhook 網址 "X" 重新連結 Discord 頻道 "X"'))
def when_relink_discord(world, a, b, c):
    world.request(a, "PUT", f"/platform-accounts/{world.account_id(c)}/credential", json={"webhook_url": b})
