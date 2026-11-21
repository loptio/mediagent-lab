"""移除平台帳號（FR-08、BR-23）與 Discord 重新連結（FR-21、BR-37）。"""

from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from app.core import clock, crypto, models
from app.core.config import get_settings
from app.core.enums import AuditAction, Platform
from app.core.platforms import VerificationUnavailable, WebhookInvalid
from tests.api.helpers import API, create_post_with_targets, history_rows, login, seed_club

BEFORE = datetime(2026, 10, 6, 3, 0, tzinfo=UTC)  # 台灣 11:00
DUE = datetime(2026, 10, 6, 4, 0, tzinfo=UTC)
NEW_WEBHOOK = "https://discord.com/api/webhooks/999/new-secret-token"


@pytest.fixture(autouse=True)
def fixed_now(monkeypatch):
    clock.set_fixed(BEFORE)
    monkeypatch.setattr(get_settings(), "cron_secret", "test-cron-secret")


def remove(client, headers, account_id):
    return client.delete(f"{API}/platform-accounts/{account_id}", headers=headers)


def relink(client, headers, account_id, webhook_url=NEW_WEBHOOK):
    return client.put(
        f"{API}/platform-accounts/{account_id}/credential", json={"webhook_url": webhook_url}, headers=headers
    )


def schedule(client, headers, post_id):
    response = client.put(
        f"{API}/posts/{post_id}/schedule", json={"scheduled_at": "2026-10-06T12:00:00+08:00"}, headers=headers
    )
    assert response.status_code == 200, response.text


def post(client, headers, post_id):
    return client.get(f"{API}/posts/{post_id}", headers=headers).json()


def test_only_admin_can_remove(client, db):
    _, accounts = seed_club(db)

    for email in ("pr@club.tw", "newbie@club.tw"):
        assert remove(client, login(client, email), accounts["threads"].id).status_code == 403


def test_removed_account_is_kept_but_hidden(client, db):
    _, accounts = seed_club(db)
    admin = login(client, "president@club.tw")

    response = remove(client, admin, accounts["threads"].id)

    assert response.status_code == 204, response.text
    db.expire_all()
    account = db.get(models.PlatformAccount, accounts["threads"].id)
    assert (account.removed, account.removed_at) == (True, BEFORE)
    listed = [
        a["account_name"] for a in client.get(f"{API}/platform-accounts", headers=admin).json()["items"]
    ]
    assert "ntu_guitar_threads" not in listed
    assert remove(client, admin, accounts["threads"].id).status_code == 404
    [audit] = db.scalars(select(models.AuditLog).where(models.AuditLog.action == AuditAction.PLATFORM_REMOVE))
    assert audit.target_id == accounts["threads"].id


def test_removal_updates_drafts_and_scheduled_posts(client, db, mock_platforms):
    _, accounts = seed_club(db)
    publisher, admin = login(client, "pr@club.tw"), login(client, "president@club.tw")
    draft = create_post_with_targets(client, publisher, [accounts["threads"].id, accounts["discord"].id])
    keeps = create_post_with_targets(client, publisher, [accounts["threads"].id, accounts["discord"].id])
    only = create_post_with_targets(client, publisher, [accounts["threads"].id], content="新生茶會")
    schedule(client, publisher, keeps)
    schedule(client, publisher, only)

    remove(client, admin, accounts["threads"].id)

    assert [t["account_name"] for t in post(client, admin, draft)["targets"]] == ["公告"]
    kept = post(client, admin, keeps)
    assert (kept["status"], kept["scheduled_at"], [t["account_name"] for t in kept["targets"]]) == (
        "SCHEDULED",
        "2026-10-06T04:00:00Z",
        ["公告"],
    )
    assert history_rows(db, keeps)[-1] == ("PENDING", "CANCELLED", "user", "TARGET_ACCOUNT_REMOVED")
    reverted = post(client, admin, only)
    assert (reverted["status"], reverted["scheduled_at"], reverted["targets"], reverted["content"]) == (
        "DRAFT",
        None,
        [],
        "新生茶會",
    )
    assert history_rows(db, only)[-1] == ("PENDING", "CANCELLED", "user", "TARGET_ACCOUNT_REMOVED")

    clock.set_fixed(DUE)
    client.post(f"{API}/internal/publish-due", headers={"X-Cron-Secret": "test-cron-secret"})
    assert mock_platforms[Platform.THREADS].received == []
    assert len(mock_platforms[Platform.DISCORD].received) == 1  # 只有還有 Discord 目標的那一則


def test_publish_records_of_removed_account_remain(client, db):
    _, accounts = seed_club(db)
    publisher, admin = login(client, "pr@club.tw"), login(client, "president@club.tw")
    post_id = create_post_with_targets(client, publisher, [accounts["discord"].id])
    client.post(f"{API}/posts/{post_id}/publish-jobs", json={"type": "immediate"}, headers=publisher)

    remove(client, admin, accounts["discord"].id)

    [item] = client.get(f"{API}/posts/{post_id}/publish-records", headers=admin).json()["items"]
    assert (item["status"], item["platform_account"]["removed"]) == ("SUCCEEDED", True)


# ---------- Discord 重新連結 ----------


def auth_events(db):
    db.expire_all()
    rows = db.scalars(select(models.PlatformAuthEvent).order_by(models.PlatformAuthEvent.id))
    return [(e.event_type, e.platform, e.account_name, e.platform_account_id, e.failure_reason) for e in rows]


def test_relink_discord_replaces_the_credential(client, db):
    users, accounts = seed_club(db)
    admin = login(client, "president@club.tw")
    discord = accounts["discord"]
    discord.auth_status = "invalid"
    db.commit()

    response = relink(client, admin, discord.id)

    assert response.status_code == 200, response.text
    assert (response.json()["auth_status"], response.json()["account_name"]) == ("valid", "公告")
    assert NEW_WEBHOOK not in response.text
    db.expire_all()
    account = db.get(models.PlatformAccount, discord.id)
    assert crypto.decrypt_credential(account.credential_encrypted)["webhook_url"] == NEW_WEBHOOK
    assert account.linked_by == users["admin"].id
    [audit] = db.scalars(select(models.AuditLog).where(models.AuditLog.action == AuditAction.PLATFORM_RELINK))
    assert (audit.actor_id, audit.target_id) == (users["admin"].id, discord.id)


@pytest.mark.parametrize(
    ("verify_error", "webhook_url", "status", "code", "reason"),
    [
        (None, "https://example.com/not-a-webhook", 422, "WEBHOOK_INVALID", "WEBHOOK_INVALID"),
        (WebhookInvalid(), NEW_WEBHOOK, 422, "WEBHOOK_INVALID", "WEBHOOK_INVALID"),
        (VerificationUnavailable(), NEW_WEBHOOK, 503, "VERIFICATION_UNAVAILABLE", "VERIFICATION_UNAVAILABLE"),
    ],
)
def test_failed_relink_keeps_the_old_credential(
    client, db, mock_platforms, verify_error, webhook_url, status, code, reason
):
    _, accounts = seed_club(db)
    discord = accounts["discord"]
    before = bytes(discord.credential_encrypted)
    if verify_error is not None:

        async def failing_verify(url):
            raise verify_error

        mock_platforms[Platform.DISCORD].verify_webhook = failing_verify

    response = relink(client, login(client, "president@club.tw"), discord.id, webhook_url)

    assert (response.status_code, response.json()["code"]) == (status, code)
    db.expire_all()
    assert bytes(db.get(models.PlatformAccount, discord.id).credential_encrypted) == before
    assert auth_events(db) == [("RELINK_FAILED", "discord", "公告", discord.id, reason)]
    assert webhook_url not in str(auth_events(db))


def test_relink_rules(client, db):
    _, accounts = seed_club(db)
    admin = login(client, "president@club.tw")

    assert relink(client, login(client, "pr@club.tw"), accounts["discord"].id).status_code == 403
    oauth = relink(client, admin, accounts["threads"].id)
    assert (oauth.status_code, oauth.json()["code"]) == (400, "PLATFORM_REQUIRES_OAUTH")
    remove(client, admin, accounts["discord"].id)
    assert relink(client, admin, accounts["discord"].id).status_code == 404


def test_record_of_a_removed_account_is_never_sent(client, db, mock_platforms):
    """移除剛好發生在設定目標或排程的檢查之後：發佈時仍不可送到已移除的平台帳號。"""
    _, accounts = seed_club(db)
    publisher = login(client, "pr@club.tw")
    post_id = create_post_with_targets(client, publisher, [accounts["threads"].id, accounts["discord"].id])
    schedule(client, publisher, post_id)
    threads = db.get(models.PlatformAccount, accounts["threads"].id)
    threads.removed, threads.removed_at = True, BEFORE  # 模擬：移除在排程檢查之後才提交
    db.commit()
    clock.set_fixed(DUE)

    client.post(f"{API}/internal/publish-due", headers={"X-Cron-Secret": "test-cron-secret"})

    assert mock_platforms[Platform.THREADS].received == []
    records = client.get(
        f"{API}/posts/{post_id}/publish-records", headers=login(client, "pr@club.tw")
    ).json()
    by_name = {
        r["platform_account"]["account_name"]: (r["status"], r["failure_reason"]) for r in records["items"]
    }
    assert by_name == {"ntu_guitar_threads": ("FAILED", "OTHER"), "公告": ("SUCCEEDED", None)}
    assert records["post_status"] == "PARTIALLY_FAILED"


def test_removing_an_account_while_a_target_is_added_does_not_deadlock(db):
    """設定目標鎖住貼文、正要新增指向該帳號的目標；同時移除鎖住了帳號、正要鎖定貼文。"""
    import threading
    import time

    from app.core.db import SessionLocal
    from app.m2_platforms import repository as platforms_repository
    from app.m4_scheduling import repository as scheduling_repository

    users, accounts = seed_club(db)
    post = models.Post(content="社課", creator_id=users["publisher"].id)
    db.add(post)
    db.flush()
    db.add(models.PostTarget(post_id=post.id, platform_account_id=accounts["threads"].id))
    db.commit()
    post_id, account_id = post.id, accounts["threads"].id
    editing, removing = SessionLocal(), SessionLocal()
    result = {}
    try:
        scheduling_repository.get_post_for_update(editing, post_id)
        platforms_repository.get_active(removing, account_id, for_update=True)

        def removal_waits_for_post():
            try:
                scheduling_repository.lock_editable_posts_targeting(removing, account_id)
                removing.commit()
                result["remove"] = "ok"
            except Exception as exc:
                removing.rollback()
                result["remove"] = type(exc).__name__

        waiter = threading.Thread(target=removal_waits_for_post)
        waiter.start()
        time.sleep(0.3)
        try:
            editing.add(models.PostTarget(post_id=post_id, platform_account_id=accounts["discord"].id))
            editing.add(
                models.PublishRecord(post_id=post_id, platform_account_id=account_id, status="PENDING")
            )
            editing.commit()
            result["edit"] = "ok"
        except Exception as exc:
            editing.rollback()
            result["edit"] = type(exc).__name__
        waiter.join(10)
    finally:
        editing.close()
        removing.close()

    assert result == {"edit": "ok", "remove": "ok"}
