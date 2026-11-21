"""驗收：查詢稽核紀錄（spec/features/查詢稽核紀錄.feature）。"""

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

scenarios(feature("查詢稽核紀錄"))


@given(step("系統中有以下登入安全事件："))
def given_login_events(world, datatable):
    for row in rows(datatable):
        event = models.LoginSecurityEvent(
            failure_reason=code(L.LOGIN_FAILURE, row["failure_reason"]),
            attempted_email=row["attempted_email"],
            user_account_id=world.user_id(row["user"]) if row.get("user") else None,
            occurred_at=tw_time(row["occurred_at"]),
        )
        if row.get("event_seq"):
            event.event_seq = int(row["event_seq"])
        world.db.add(event)
        world.db.flush()
    world.db.commit()


@given(step("系統中有以下平台授權事件："))
def given_auth_events(world, datatable):
    for row in rows(datatable):
        event_type = code(L.EVENT_TYPE, row["event_type"])
        name = row.get("account_name") or None
        # 重新連結失敗一定對應某個平台帳號（資料庫限制）；首次連結失敗沒有
        account_id = world.account_id(name) if event_type == "RELINK_FAILED" and name else None
        world.db.add(
            models.PlatformAuthEvent(
                event_type=event_type,
                platform_account_id=account_id,
                platform=code(L.PLATFORM, row.get("platform") or "Instagram"),
                account_name=name,
                failure_reason=code(L.AUTH_FAILURE, row["failure_reason"]),
                actor_id=world.user_id(row["actor"]),
                occurred_at=tw_time(row["occurred_at"]),
            )
        )
        world.db.flush()
    world.db.commit()


@when(step('"X" 查詢稽核紀錄'))
def when_query(world, a):
    world.request(a, "GET", "/audit-events")


@when(step('"X" 以下列條件查詢稽核紀錄：'))
def when_query_filtered(world, a, datatable):
    [row] = rows(datatable)
    params = {}
    for column, raw in row.items():
        if not raw:
            continue
        if column == "action":
            params["action"] = code(L.AUDIT_ACTION, raw)
        elif column in ("from", "to"):
            params[column] = iso(raw)
        elif column == "actor":
            if raw == "系統":
                params["actor_type"] = "system"
            else:
                params["actor_id"] = world.user_id(raw)
        elif column == "related_account":
            params["account_id"] = world.user_id(raw)
        elif column == "page_size":
            params["page_size"] = raw
        elif column == "page":
            params["page"] = raw
    world.request(a, "GET", "/audit-events", params=params)


@given(step('系統中另有 (?P<n>\\d+) 筆由 "X" 執行的「(?P<action>[^」]+)」稽核紀錄'))
def given_more_audits(world, n, a, action):
    user_id = world.user_id(a)
    for index in range(int(n)):
        world.db.add(
            models.AuditLog(
                actor_type="user",
                actor_id=user_id,
                action=code(L.AUDIT_ACTION, action),
                target_type="user_account",
                target_id=user_id,
                occurred_at=tw_time("2026-09-15 09:00") + timedelta(minutes=index),
            )
        )
    world.db.commit()


@when(step('"X" 查詢稽核紀錄，第 (?P<page>\\d+) 頁，每頁 (?P<size>\\d+) 筆'))
def when_query_page(world, a, page, size):
    world.request(a, "GET", "/audit-events", params={"page": page, "page_size": size})
