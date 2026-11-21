"""修改與刪除貼文（FR-12、FR-13、BR-11、BR-13、BR-18、BR-24、BR-27、BR-35）。"""

from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from app.core import clock, models
from app.core.config import get_settings
from app.core.enums import Platform, PostStatus
from tests.api.helpers import API, create_post_with_targets, history_rows, login, seed_club

BEFORE = datetime(2026, 10, 6, 3, 0, tzinfo=UTC)  # 台灣 11:00
DUE = datetime(2026, 10, 6, 4, 0, tzinfo=UTC)  # 台灣 12:00


@pytest.fixture(autouse=True)
def fixed_now(monkeypatch):
    clock.set_fixed(BEFORE)
    monkeypatch.setattr(get_settings(), "cron_secret", "test-cron-secret")


def edit(client, headers, post_id, content):
    return client.patch(f"{API}/posts/{post_id}", json={"content": content}, headers=headers)


def delete(client, headers, post_id):
    return client.delete(f"{API}/posts/{post_id}", headers=headers)


def schedule(client, headers, post_id):
    response = client.put(
        f"{API}/posts/{post_id}/schedule", json={"scheduled_at": "2026-10-06T12:00:00+08:00"}, headers=headers
    )
    assert response.status_code == 200, response.text


def content_of(db, post_id):
    db.expire_all()
    return db.get(models.Post, post_id).content


def test_edit_permissions(client, db):
    _, accounts = seed_club(db)
    emails = ("newbie@club.tw", "pr@club.tw", "president@club.tw")
    writer, publisher, admin = (login(client, email) for email in emails)
    own = create_post_with_targets(client, writer, [accounts["discord"].id], content="新生茶會")
    others = create_post_with_targets(client, publisher, [accounts["discord"].id], content="期末成發宣傳")

    assert edit(client, writer, own, "新生茶會改到週五").status_code == 200
    refused = edit(client, writer, others, "期末成發延期")
    assert refused.status_code == 403
    assert content_of(db, others) == "期末成發宣傳"
    assert edit(client, publisher, own, "發佈者修改").status_code == 200
    response = edit(client, admin, others, "管理員修改")
    assert (response.status_code, response.json()["content"]) == (200, "管理員修改")


@pytest.mark.parametrize(
    "status",
    [PostStatus.PUBLISHING, PostStatus.PUBLISHED, PostStatus.PARTIALLY_FAILED, PostStatus.FAILED],
)
def test_only_draft_or_scheduled_can_be_edited(client, db, status):
    _, accounts = seed_club(db)
    headers = login(client, "pr@club.tw")
    post_id = create_post_with_targets(client, headers, [accounts["discord"].id])
    db.get(models.Post, post_id).status = status
    db.commit()

    response = edit(client, headers, post_id, "修改")

    assert (response.status_code, response.json()["code"]) == (409, "POST_NOT_EDITABLE")


@pytest.mark.parametrize("content", ["", "   "])
def test_edit_rejects_blank_content(client, db, content):
    _, accounts = seed_club(db)
    headers = login(client, "pr@club.tw")
    post_id = create_post_with_targets(client, headers, [accounts["discord"].id])

    response = edit(client, headers, post_id, content)

    assert (response.status_code, response.json()["code"]) == (422, "CONTENT_EMPTY")


def test_editing_scheduled_post_checks_limits_and_keeps_schedule(client, db):
    _, accounts = seed_club(db)
    headers = login(client, "pr@club.tw")
    post_id = create_post_with_targets(client, headers, [accounts["threads"].id, accounts["discord"].id])
    schedule(client, headers, post_id)

    ok = edit(client, headers, post_id, "字" * 500)
    too_long = edit(client, headers, post_id, "字" * 501)

    assert ok.status_code == 200, ok.text
    assert (ok.json()["status"], ok.json()["scheduled_at"]) == ("SCHEDULED", "2026-10-06T04:00:00Z")
    assert (too_long.status_code, too_long.json()["code"]) == (422, "CONTENT_TOO_LONG")
    assert content_of(db, post_id) == "字" * 500


def test_scheduled_publish_uses_edited_content(client, db, mock_platforms):
    _, accounts = seed_club(db)
    headers = login(client, "pr@club.tw")
    post_id = create_post_with_targets(client, headers, [accounts["discord"].id], content="社課在 201 教室")
    schedule(client, headers, post_id)
    edit(client, headers, post_id, "社課改到 202 教室")
    clock.set_fixed(DUE)

    client.post(f"{API}/internal/publish-due", headers={"X-Cron-Secret": "test-cron-secret"})

    [(_, content)] = mock_platforms[Platform.DISCORD].received
    assert content.text == "社課改到 202 教室"
    assert db.scalar(select(models.PublishRecord.content_summary)) == "社課改到 202 教室"


def test_delete_permissions_and_status(client, db):
    _, accounts = seed_club(db)
    writer, publisher = login(client, "newbie@club.tw"), login(client, "pr@club.tw")
    others = create_post_with_targets(client, publisher, [accounts["discord"].id])
    published = create_post_with_targets(client, publisher, [accounts["discord"].id])
    db.get(models.Post, published).status = PostStatus.PUBLISHED
    db.commit()

    assert delete(client, writer, others).status_code == 403
    refused = delete(client, publisher, published)
    assert (refused.status_code, refused.json()["code"]) == (409, "POST_NOT_EDITABLE")
    assert delete(client, publisher, 9999).status_code == 404


def test_deleted_post_disappears_but_records_remain(client, db):
    _, accounts = seed_club(db)
    headers = login(client, "pr@club.tw")
    post_id = create_post_with_targets(client, headers, [accounts["discord"].id])
    schedule(client, headers, post_id)
    client.delete(f"{API}/posts/{post_id}/schedule", headers=headers)

    response = delete(client, headers, post_id)

    assert response.status_code == 204, response.text
    assert client.get(f"{API}/posts/{post_id}", headers=headers).status_code == 404
    assert post_id not in [p["id"] for p in client.get(f"{API}/posts", headers=headers).json()["items"]]
    assert delete(client, headers, post_id).status_code == 404
    records = client.get(f"{API}/posts/{post_id}/publish-records", headers=headers).json()
    assert (records["post_deleted"], records["post_status"]) == (True, None)
    assert [item["status"] for item in records["items"]] == ["CANCELLED"]


def test_deleting_scheduled_post_cancels_pending_records(client, db):
    _, accounts = seed_club(db)
    headers = login(client, "pr@club.tw")
    post_id = create_post_with_targets(client, headers, [accounts["discord"].id])
    schedule(client, headers, post_id)

    assert delete(client, headers, post_id).status_code == 204

    assert history_rows(db, post_id)[-1] == ("PENDING", "CANCELLED", "user", "POST_DELETED")


def test_deleted_scheduled_post_is_not_published(client, db, mock_platforms):
    _, accounts = seed_club(db)
    headers = login(client, "pr@club.tw")
    post_id = create_post_with_targets(client, headers, [accounts["discord"].id])
    schedule(client, headers, post_id)
    delete(client, headers, post_id)
    clock.set_fixed(DUE)

    response = client.post(f"{API}/internal/publish-due", headers={"X-Cron-Secret": "test-cron-secret"})

    assert response.json() == {"started": 0}
    assert mock_platforms[Platform.DISCORD].received == []


def test_editing_scheduled_post_rechecks_targets(client, db):
    """BR-24：修改已排程貼文的內容時檢查 BR-02、05、07、08；目標授權在排程後到期時拒絕這次修改。"""
    _, accounts = seed_club(db)
    headers = login(client, "pr@club.tw")
    post_id = create_post_with_targets(client, headers, [accounts["discord"].id, accounts["threads"].id])
    schedule(client, headers, post_id)
    db.get(models.PlatformAccount, accounts["threads"].id).auth_expires_at = BEFORE
    db.commit()

    response = edit(client, headers, post_id, "社課改到 202 教室")

    assert (response.status_code, response.json()["code"]) == (422, "TARGET_AUTH_INVALID")
    db.expire_all()
    assert db.get(models.Post, post_id).content != "社課改到 202 教室"
