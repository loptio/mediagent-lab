"""排程時間到由系統自動發佈（FR-16、BR-25、BR-31、NFR-01、foundation-plan D-07）。"""

import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.core import clock, models
from app.core.config import get_settings
from app.core.enums import AuditAction, AuthStatus, Platform, UserStatus
from app.m5_publishing import engine, scheduler
from tests.api.helpers import (
    API,
    create_post_with_targets,
    history_rows,
    login,
    records_by_account,
    seed_club,
)

BEFORE = datetime(2026, 10, 6, 3, 0, tzinfo=UTC)  # 台灣 11:00
DUE = datetime(2026, 10, 6, 4, 0, tzinfo=UTC)  # 台灣 12:00
PUBLISH_DUE = f"{API}/internal/publish-due"
CRON = {"X-Cron-Secret": "test-cron-secret"}


@pytest.fixture(autouse=True)
def cron_secret(monkeypatch):
    monkeypatch.setattr(get_settings(), "cron_secret", "test-cron-secret")


def scheduled_post(client, db, account_keys=("threads", "instagram", "discord"), creator="pr@club.tw"):
    """在台灣 11:00 建立一則排程於 12:00 的貼文，回傳 (users, accounts, post_id)。"""
    clock.set_fixed(BEFORE)
    users, accounts = seed_club(db)
    author = login(client, creator)
    post_id = create_post_with_targets(client, author, [accounts[k].id for k in account_keys])
    response = client.put(
        f"{API}/posts/{post_id}/schedule",
        json={"scheduled_at": "2026-10-06T12:00:00+08:00"},
        headers=login(client, "pr@club.tw"),
    )
    assert response.status_code == 200, response.text
    return users, accounts, post_id


def publish_due(client, headers=CRON):
    return client.post(PUBLISH_DUE, headers=headers)


def post_of(client, post_id):
    return client.get(f"{API}/posts/{post_id}", headers=login(client, "president@club.tw")).json()


def outcome(client, post_id):
    records = records_by_account(client, login(client, "president@club.tw"), post_id)
    return {name: (r["status"], r["failure_reason"]) for name, r in records.items()}


def test_due_post_is_published_by_the_system(client, db, mock_platforms):
    users, _, post_id = scheduled_post(client, db)
    clock.set_fixed(DUE)

    response = publish_due(client)

    assert response.status_code == 200, response.text
    assert response.json() == {"started": 1}
    post = post_of(client, post_id)
    assert post["status"] == "PUBLISHED"
    assert post["scheduled_at"] is not None  # 排程發佈保留原本的排程時間
    assert set(outcome(client, post_id).values()) == {("SUCCEEDED", None)}
    assert [h for h in history_rows(db, post_id) if h[3] == "PUBLISH_SUCCEEDED"] == [
        ("PENDING", "SUCCEEDED", "system", "PUBLISH_SUCCEEDED")
    ] * 3
    db.expire_all()
    [audit] = db.scalars(select(models.AuditLog).where(models.AuditLog.action == AuditAction.POST_PUBLISH))
    assert (audit.actor_type, audit.actor_id, audit.result) == ("system", None, "PUBLISHED")
    assert (audit.scheduled_by, audit.post_creator_id) == (users["publisher"].id, users["publisher"].id)
    assert [r.status for r in audit.target_results] == ["SUCCEEDED"] * 3
    summaries = db.scalars(select(models.PublishRecord.content_summary)).all()
    assert summaries == ["本週三 19:00 社課"] * 3


def test_post_not_yet_due_and_drafts_are_not_published(client, db, mock_platforms):
    _, accounts, post_id = scheduled_post(client, db)
    draft_id = create_post_with_targets(client, login(client, "pr@club.tw"), [accounts["discord"].id])
    clock.set_fixed(DUE - timedelta(minutes=1))

    assert publish_due(client).json() == {"started": 0}

    assert post_of(client, post_id)["status"] == "SCHEDULED"
    assert post_of(client, draft_id)["status"] == "DRAFT"
    assert all(adapter.received == [] for adapter in mock_platforms.values())


def test_auth_invalid_target_fails_without_sending(client, db, mock_platforms):
    _, accounts, post_id = scheduled_post(client, db)
    # 排程之後：Instagram 的授權到期、Threads 被標示為失效
    db.get(models.PlatformAccount, accounts["instagram"].id).auth_expires_at = DUE
    db.get(models.PlatformAccount, accounts["threads"].id).auth_status = AuthStatus.INVALID
    db.commit()
    clock.set_fixed(DUE)

    publish_due(client)

    assert outcome(client, post_id) == {
        "ntu_guitar_threads": ("FAILED", "AUTH_EXPIRED"),
        "ntu_guitar_ig": ("FAILED", "AUTH_EXPIRED"),
        "公告": ("SUCCEEDED", None),
    }
    assert mock_platforms[Platform.THREADS].received == []
    assert mock_platforms[Platform.INSTAGRAM].received == []
    assert post_of(client, post_id)["status"] == "PARTIALLY_FAILED"
    db.expire_all()
    assert db.get(models.PlatformAccount, accounts["instagram"].id).auth_status == AuthStatus.VALID


def test_disabled_creator_post_still_publishes(client, db, mock_platforms):
    users, _, post_id = scheduled_post(client, db, ("discord",), creator="newbie@club.tw")
    db.get(models.UserAccount, users["writer"].id).status = UserStatus.DISABLED
    db.commit()
    clock.set_fixed(DUE)

    publish_due(client)

    assert post_of(client, post_id)["status"] == "PUBLISHED"
    assert len(mock_platforms[Platform.DISCORD].received) == 1


def test_cancelled_target_of_due_post_is_not_sent(client, db, mock_platforms):
    _, accounts, post_id = scheduled_post(client, db, ("threads", "discord"))
    response = client.put(
        f"{API}/posts/{post_id}/targets",
        json={"platform_account_ids": [accounts["discord"].id]},
        headers=login(client, "pr@club.tw"),
    )
    assert response.status_code == 200, response.text
    clock.set_fixed(DUE)

    publish_due(client)

    assert outcome(client, post_id) == {
        "ntu_guitar_threads": ("CANCELLED", None),
        "公告": ("SUCCEEDED", None),
    }
    assert mock_platforms[Platform.THREADS].received == []
    assert post_of(client, post_id)["status"] == "PUBLISHED"


def test_two_triggers_publish_a_due_post_once(client, db, mock_platforms):
    _, _, post_id = scheduled_post(client, db)
    clock.set_fixed(DUE)

    first = publish_due(client)
    second = publish_due(client)

    assert (first.json(), second.json()) == ({"started": 1}, {"started": 0})
    assert scheduler.claim_due_posts() == []
    assert [len(adapter.received) for adapter in mock_platforms.values()] == [1, 1, 1]


def test_publish_due_requires_cron_secret(client, db, monkeypatch):
    missing = client.post(PUBLISH_DUE)
    wrong = publish_due(client, {"X-Cron-Secret": "guess"})
    monkeypatch.setattr(get_settings(), "cron_secret", "")
    unset = publish_due(client, {"X-Cron-Secret": ""})

    for response in (missing, wrong, unset):
        assert (response.status_code, response.json()["code"]) == (401, "UNAUTHENTICATED")


def test_scheduler_tick_publishes_due_posts(client, db, mock_platforms):
    _, _, post_id = scheduled_post(client, db)
    clock.set_fixed(DUE)

    async def tick_and_wait():
        await asyncio.gather(*await scheduler.tick())

    asyncio.run(tick_and_wait())

    assert post_of(client, post_id)["status"] == "PUBLISHED"
    assert [len(adapter.received) for adapter in mock_platforms.values()] == [1, 1, 1]


def test_due_posts_are_published_concurrently(client, db, monkeypatch):
    """同一時間到期的多則貼文同時發佈：一則很慢，不可以拖住其他貼文。"""
    _, accounts, first = scheduled_post(client, db, ("discord",))
    second = create_post_with_targets(client, login(client, "pr@club.tw"), [accounts["threads"].id])
    client.put(
        f"{API}/posts/{second}/schedule",
        json={"scheduled_at": "2026-10-06T12:00:00+08:00"},
        headers=login(client, "pr@club.tw"),
    )
    clock.set_fixed(DUE)
    events = []

    async def slow_run_post(post_id, actor_id=None, mode=None):
        events.append(("start", post_id))
        await asyncio.sleep(0.05)
        events.append(("end", post_id))

    monkeypatch.setattr(engine, "run_post", slow_run_post)

    assert publish_due(client).json() == {"started": 2}
    assert [kind for kind, _ in events] == ["start", "start", "end", "end"]
    assert {post_id for _, post_id in events} == {first, second}
