"""查詢稽核紀錄（FR-19、BR-44、BR-45、《API 設計》34）。"""

from datetime import UTC, datetime, timedelta

import pytest

from app.core import audit, clock
from app.core.enums import AuditAction, Platform, TargetType
from app.m1_accounts import repository as accounts_repository
from app.m2_platforms import repository as platforms_repository
from tests.api.helpers import API, login, seed_club

DAY = datetime(2026, 10, 5, 0, 0, tzinfo=UTC)
EVENTS = f"{API}/audit-events"


def at(hours: float) -> datetime:
    return DAY + timedelta(hours=hours)


@pytest.fixture
def history(db):
    """依時間建立：社長登入、公關設定排程、系統發佈、公關登入失敗、社長連結失敗、不存在的帳號登入失敗、
    社長停用新進幹部；第 2、3 筆時間相同。"""
    users, accounts = seed_club(db)
    admin, publisher, writer = users["admin"], users["publisher"], users["writer"]

    def write(hours, **fields):
        clock.set_fixed(at(hours))
        audit.write(db, **fields)

    write(1, action=AuditAction.LOGIN, actor=admin, target_type=TargetType.USER_ACCOUNT, target_id=admin.id)
    write(2, action=AuditAction.POST_SCHEDULE, actor=publisher, target_type=TargetType.POST, target_id=42)
    write(
        2,
        action=AuditAction.POST_PUBLISH,
        actor=None,
        target_type=TargetType.POST,
        target_id=42,
        result="PUBLISHED",
        scheduled_by=publisher.id,
        post_creator_id=publisher.id,
        target_results=[{"platform_account_id": accounts["discord"].id, "status": "SUCCEEDED"}],
    )
    accounts_repository.add_login_failure(
        db, reason="WRONG_PASSWORD", email="pr@club.tw", user_id=publisher.id, now=at(3)
    )
    clock.set_fixed(at(4))
    platforms_repository.add_auth_event(
        db,
        event_type="RELINK_FAILED",
        platform=Platform.DISCORD,
        account_name="公告",
        failure_reason="WEBHOOK_INVALID",
        actor_id=admin.id,
        platform_account_id=accounts["discord"].id,
    )
    accounts_repository.add_login_failure(
        db, reason="ACCOUNT_NOT_FOUND", email="nobody@club.tw", user_id=None, now=at(5)
    )
    write(
        6,
        action=AuditAction.USER_DISABLE,
        actor=admin,
        target_type=TargetType.USER_ACCOUNT,
        target_id=writer.id,
    )
    db.commit()
    clock.set_fixed(at(30))  # 之後的請求（登入）發生在隔天，不影響篩選結果
    return users, accounts


def query(client, **params):
    return client.get(EVENTS, params=params, headers=login(client, "president@club.tw"))


def summary(response):
    assert response.status_code == 200, response.text
    return [(item["kind"], item.get("action") or item.get("event_type")) for item in response.json()["items"]]


def day_only(**params):
    return {"from": DAY.isoformat(), "to": (DAY + timedelta(days=1)).isoformat()} | params


def test_only_admin_can_query(client, history):
    for email in ("pr@club.tw", "newbie@club.tw"):
        assert client.get(EVENTS, headers=login(client, email)).status_code == 403


def test_all_kinds_newest_first_and_same_time_by_event_seq(client, history):
    assert summary(query(client, **day_only())) == [
        ("audit", "USER_DISABLE"),
        ("login_security", "LOGIN_FAILED"),
        ("platform_auth", "RELINK_FAILED"),
        ("login_security", "LOGIN_FAILED"),
        ("audit", "POST_PUBLISH"),  # 與設定排程同一時間，事件序號較大者在前
        ("audit", "POST_SCHEDULE"),
        ("audit", "LOGIN"),
    ]


def test_item_shapes(client, history):
    users, accounts = history
    items = query(client, **day_only()).json()["items"]
    disable, not_found, relink_failed, wrong_password, published = items[:5]

    assert disable["actor"] == {"id": users["admin"].id, "email": "president@club.tw", "name": "社長"}
    assert disable["target"] == {"type": "user_account", "id": users["writer"].id}
    assert (not_found["account"], not_found["attempted_email"], not_found["failure_reason"]) == (
        None,
        "nobody@club.tw",
        "ACCOUNT_NOT_FOUND",
    )
    assert wrong_password["account"]["id"] == users["publisher"].id
    assert (relink_failed["platform"], relink_failed["platform_account_id"], relink_failed["actor_type"]) == (
        "discord",
        accounts["discord"].id,
        "user",
    )
    assert (published["actor_type"], published["actor"]) == ("system", None)
    assert published["details"] == {
        "scheduled_by": users["publisher"].id,
        "post_creator_id": users["publisher"].id,
        "result": "PUBLISHED",
    }
    assert published["target_results"] == [
        {
            "platform_account_id": accounts["discord"].id,
            "status": "SUCCEEDED",
            "failure_reason": None,
            "skip_reason": None,
        }
    ]


def test_filter_by_actor_excludes_login_security_events(client, history):
    users, _ = history

    assert summary(query(client, actor_id=users["publisher"].id, **day_only())) == [
        ("audit", "POST_SCHEDULE")
    ]
    assert summary(query(client, actor_id=users["admin"].id, **day_only())) == [
        ("audit", "USER_DISABLE"),
        ("platform_auth", "RELINK_FAILED"),
        ("audit", "LOGIN"),
    ]
    assert summary(query(client, actor_type="system", **day_only())) == [("audit", "POST_PUBLISH")]


def test_filter_by_account(client, history):
    users, _ = history

    assert summary(query(client, account_id=users["publisher"].id, **day_only())) == [
        ("login_security", "LOGIN_FAILED")
    ]
    writer = query(client, account_id=users["writer"].id, **day_only()).json()["items"]
    assert [(i["action"], i["actor"]["id"]) for i in writer] == [("USER_DISABLE", users["admin"].id)]


def test_filter_by_action(client, history):
    assert summary(query(client, action="POST_SCHEDULE")) == [("audit", "POST_SCHEDULE")]
    failures = query(client, action="LOGIN_FAILED", **day_only()).json()["items"]
    assert [i["attempted_email"] for i in failures] == ["nobody@club.tw", "pr@club.tw"]
    assert summary(query(client, action="RELINK_FAILED")) == [("platform_auth", "RELINK_FAILED")]
    assert summary(query(client, action="LINK_FAILED")) == []


def test_time_range_includes_start_and_excludes_end(client, history):
    response = query(client, **{"from": at(2).isoformat(), "to": at(4).isoformat()})

    assert summary(response) == [
        ("login_security", "LOGIN_FAILED"),
        ("audit", "POST_PUBLISH"),
        ("audit", "POST_SCHEDULE"),
    ]


def test_pagination(client, history):
    first = query(client, page_size=50, **day_only()).json()
    page = query(client, page_size=20, **day_only()).json()

    assert (first["page"], first["page_size"], first["has_prev"], first["total"]) == (1, 50, False, 7)
    assert (len(page["items"]), page["total_pages"], page["has_next"]) == (7, 1, False)
    assert query(client, page_size=30).status_code == 400
    assert query(client, page=0).status_code == 400
