"""設定排程、取消排程，以及已排程貼文修改目標時同步發佈紀錄（FR-16、FR-25、BR-10、BR-18、BR-24～BR-28）。"""

from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from app.core import clock, models
from app.core.enums import AuditAction, PostStatus
from tests.api.helpers import API, create_post_with_targets, login, seed_club
from tests.factories import make_image

# 現在是台灣時間 2026-10-06 11:00（UTC 03:00）
NOW = datetime(2026, 10, 6, 3, 0, tzinfo=UTC)
NOON_TW = "2026-10-06T12:00:00+08:00"
NOON_UTC = datetime(2026, 10, 6, 4, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def fixed_now():
    clock.set_fixed(NOW)


def schedule(client, headers, post_id, when=NOON_TW):
    return client.put(f"{API}/posts/{post_id}/schedule", json={"scheduled_at": when}, headers=headers)


def cancel(client, headers, post_id):
    return client.delete(f"{API}/posts/{post_id}/schedule", headers=headers)


def set_targets(client, headers, post_id, account_ids):
    return client.put(
        f"{API}/posts/{post_id}/targets", json={"platform_account_ids": account_ids}, headers=headers
    )


def records(db, post_id):
    """{平台帳號名稱: (紀錄 id, 狀態)}"""
    db.expire_all()
    rows = db.execute(
        select(models.PublishRecord.id, models.PlatformAccount.account_name, models.PublishRecord.status)
        .join(models.PlatformAccount)
        .where(models.PublishRecord.post_id == post_id)
    )
    return {name: (record_id, status) for record_id, name, status in rows}


def history(db, post_id):
    """[(平台帳號名稱, from, to, actor_type, reason)]，依寫入順序。"""
    rows = db.execute(
        select(models.PlatformAccount.account_name, models.PublishRecordHistory)
        .select_from(models.PublishRecordHistory)
        .join(models.PublishRecord)
        .join(models.PlatformAccount)
        .where(models.PublishRecord.post_id == post_id)
        .order_by(models.PublishRecordHistory.id)
    )
    return [(name, h.from_status, h.to_status, h.actor_type, h.reason) for name, h in rows]


def audits(db, action):
    db.expire_all()
    return list(db.scalars(select(models.AuditLog).where(models.AuditLog.action == action)))


def scheduled_at(body):
    return datetime.fromisoformat(body["scheduled_at"].replace("Z", "+00:00"))


def test_publisher_schedules_draft(client, db):
    users, accounts = seed_club(db)
    headers = login(client, "pr@club.tw")
    post_id = create_post_with_targets(client, headers, [accounts["threads"].id, accounts["discord"].id])

    response = schedule(client, headers, post_id)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "SCHEDULED"
    assert scheduled_at(body) == NOON_UTC
    assert body["scheduled_by"] == users["publisher"].id
    assert {name: status for name, (_, status) in records(db, post_id).items()} == {
        "ntu_guitar_threads": "PENDING",
        "公告": "PENDING",
    }
    assert sorted(history(db, post_id)) == [
        ("ntu_guitar_threads", None, "PENDING", "user", "SCHEDULE_SET"),
        ("公告", None, "PENDING", "user", "SCHEDULE_SET"),
    ]
    [audit] = audits(db, AuditAction.POST_SCHEDULE)
    assert (audit.actor_id, audit.target_id) == (users["publisher"].id, post_id)


def test_schedule_time_without_timezone_is_taiwan_time(client, db):
    _, accounts = seed_club(db)
    headers = login(client, "pr@club.tw")
    post_id = create_post_with_targets(client, headers, [accounts["discord"].id])

    response = schedule(client, headers, post_id, "2026-10-06T12:00:00")

    assert response.status_code == 200, response.text
    assert scheduled_at(response.json()) == NOON_UTC


@pytest.mark.parametrize(
    ("when", "code"),
    [
        ("2026-10-06T11:00:00+08:00", "SCHEDULE_TIME_NOT_FUTURE"),
        ("2026-10-06T10:55:00+08:00", "SCHEDULE_TIME_NOT_FUTURE"),
        ("2026-10-06T12:03:00+08:00", "SCHEDULE_TIME_NOT_ALIGNED"),
        ("2026-10-06T12:05:30+08:00", "SCHEDULE_TIME_NOT_ALIGNED"),
    ],
)
def test_schedule_time_must_be_future_and_aligned(client, db, when, code):
    users, accounts = seed_club(db)
    headers = login(client, "pr@club.tw")
    post_id = create_post_with_targets(client, headers, [accounts["discord"].id])

    response = schedule(client, headers, post_id, when)

    assert (response.status_code, response.json()["code"]) == (422, code)
    post = client.get(f"{API}/posts/{post_id}", headers=headers).json()
    assert (post["status"], post["scheduled_by"], post["scheduled_at"]) == ("DRAFT", None, None)
    assert records(db, post_id) == {}


def test_writer_schedule_permissions(client, db):
    users, accounts = seed_club(db)
    writer = login(client, "newbie@club.tw")
    publisher = login(client, "pr@club.tw")
    own = create_post_with_targets(client, writer, [accounts["discord"].id])
    others = create_post_with_targets(client, publisher, [accounts["discord"].id])

    assert schedule(client, writer, own).status_code == 403  # 撰稿者不能為草稿設定排程

    assert schedule(client, publisher, own).status_code == 200
    assert schedule(client, publisher, others).status_code == 200
    moved = schedule(client, writer, own, "2026-10-06T13:00:00+08:00")
    assert moved.status_code == 200, moved.text
    assert moved.json()["scheduled_by"] == users["writer"].id
    assert schedule(client, writer, others, "2026-10-06T13:00:00+08:00").status_code == 403
    assert len(audits(db, AuditAction.POST_SCHEDULE)) == 3


def test_only_draft_or_scheduled_can_be_scheduled(client, db):
    users, accounts = seed_club(db)
    headers = login(client, "pr@club.tw")
    post_id = create_post_with_targets(client, headers, [accounts["discord"].id])
    post = db.get(models.Post, post_id)
    post.status = PostStatus.PUBLISHED
    db.commit()

    response = schedule(client, headers, post_id)

    assert (response.status_code, response.json()["code"]) == (409, "POST_NOT_SCHEDULABLE")


def test_schedule_checks_publish_rules(client, db):
    _, accounts = seed_club(db)
    headers = login(client, "pr@club.tw")
    no_target = client.post(f"{API}/posts", json={"content": "社課公告"}, headers=headers).json()["id"]
    too_long = create_post_with_targets(client, headers, [accounts["threads"].id], content="字" * 501)

    assert schedule(client, headers, no_target).json()["code"] == "NO_TARGET"
    assert schedule(client, headers, too_long).json()["code"] == "CONTENT_TOO_LONG"
    assert records(db, too_long) == {}


def test_cancel_schedule(client, db):
    users, accounts = seed_club(db)
    publisher = login(client, "pr@club.tw")
    writer = login(client, "newbie@club.tw")
    post_id = create_post_with_targets(client, publisher, [accounts["threads"].id, accounts["discord"].id])
    draft_id = create_post_with_targets(client, publisher, [accounts["discord"].id])
    schedule(client, publisher, post_id)

    assert cancel(client, writer, post_id).status_code == 403
    assert cancel(client, publisher, draft_id).json()["code"] == "POST_NOT_SCHEDULED"

    response = cancel(client, publisher, post_id)

    assert response.status_code == 200, response.text
    assert (response.json()["status"], response.json()["scheduled_at"]) == ("DRAFT", None)
    assert {status for _, status in records(db, post_id).values()} == {"CANCELLED"}
    assert sorted(h for h in history(db, post_id) if h[4] == "SCHEDULE_CANCELLED") == [
        ("ntu_guitar_threads", "PENDING", "CANCELLED", "user", "SCHEDULE_CANCELLED"),
        ("公告", "PENDING", "CANCELLED", "user", "SCHEDULE_CANCELLED"),
    ]
    [audit] = audits(db, AuditAction.SCHEDULE_CANCEL)
    assert (audit.actor_id, audit.target_id) == (users["publisher"].id, post_id)


def test_reschedule_after_cancel_reuses_records(client, db):
    _, accounts = seed_club(db)
    headers = login(client, "pr@club.tw")
    post_id = create_post_with_targets(client, headers, [accounts["threads"].id, accounts["discord"].id])
    schedule(client, headers, post_id)
    cancel(client, headers, post_id)
    before = records(db, post_id)
    make_image(db, post_id)  # Instagram 需要圖片（BR-05）
    db.commit()
    set_targets(client, headers, post_id, [accounts["discord"].id, accounts["instagram"].id])

    response = schedule(client, headers, post_id, "2026-10-07T12:00:00+08:00")

    assert response.status_code == 200, response.text
    after = records(db, post_id)
    assert after["ntu_guitar_threads"] == (before["ntu_guitar_threads"][0], "CANCELLED")
    assert after["公告"] == (before["公告"][0], "PENDING")
    assert after["ntu_guitar_ig"][1] == "PENDING"
    latest = history(db, post_id)[-2:]
    assert sorted(latest) == [
        ("ntu_guitar_ig", None, "PENDING", "user", "SCHEDULE_SET"),
        ("公告", "CANCELLED", "PENDING", "user", "RESCHEDULED"),
    ]


def test_changing_targets_of_scheduled_post_syncs_records(client, db):
    _, accounts = seed_club(db)
    headers = login(client, "pr@club.tw")
    post_id = create_post_with_targets(client, headers, [accounts["threads"].id, accounts["discord"].id])
    schedule(client, headers, post_id)
    before = records(db, post_id)
    written = len(history(db, post_id))
    make_image(db, post_id)  # Instagram 需要圖片（BR-05）
    db.commit()

    response = set_targets(client, headers, post_id, [accounts["discord"].id, accounts["instagram"].id])

    assert response.status_code == 200, response.text
    after = records(db, post_id)
    assert after["ntu_guitar_threads"] == (before["ntu_guitar_threads"][0], "CANCELLED")
    assert after["公告"] == before["公告"]
    assert after["ntu_guitar_ig"][1] == "PENDING"
    assert sorted(history(db, post_id)[written:]) == [
        ("ntu_guitar_ig", None, "PENDING", "user", "TARGET_ADDED"),
        ("ntu_guitar_threads", "PENDING", "CANCELLED", "user", "TARGET_MODIFIED"),
    ]
    post = client.get(f"{API}/posts/{post_id}", headers=headers).json()
    assert (post["status"], scheduled_at(post)) == ("SCHEDULED", NOON_UTC)

    readded = set_targets(client, headers, post_id, [accounts["threads"].id, accounts["discord"].id])

    assert readded.status_code == 200, readded.text
    assert records(db, post_id)["ntu_guitar_threads"] == (before["ntu_guitar_threads"][0], "PENDING")
    assert sorted(history(db, post_id)[-2:]) == [
        ("ntu_guitar_ig", "PENDING", "CANCELLED", "user", "TARGET_MODIFIED"),
        ("ntu_guitar_threads", "CANCELLED", "PENDING", "user", "TARGET_MODIFIED"),
    ]


def test_scheduled_post_target_rules(client, db):
    _, accounts = seed_club(db)
    headers = login(client, "pr@club.tw")
    post_id = create_post_with_targets(client, headers, [accounts["discord"].id], content="字" * 501)
    schedule(client, headers, post_id)
    before = records(db, post_id)

    emptied = set_targets(client, headers, post_id, [])
    too_long = set_targets(client, headers, post_id, [accounts["discord"].id, accounts["threads"].id])

    assert (emptied.status_code, emptied.json()["code"]) == (422, "SCHEDULED_POST_REQUIRES_TARGET")
    assert (too_long.status_code, too_long.json()["code"]) == (422, "CONTENT_TOO_LONG")
    assert records(db, post_id) == before
    targets = client.get(f"{API}/posts/{post_id}", headers=headers).json()["targets"]
    assert [t["account_name"] for t in targets] == ["公告"]
