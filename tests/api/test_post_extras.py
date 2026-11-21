"""複製為新草稿（FR-27、BR-36）、預覽貼文（FR-20、BR-46）、發佈紀錄變更歷程（FR-17）。"""

from datetime import timedelta

from sqlalchemy import select

from app.core import clock, models
from app.core.enums import AuditAction, AuthStatus, FailureReason, Platform, PostStatus
from tests.api.helpers import API, create_post_with_targets, login, publish, seed_club


def copy(client, headers, post_id):
    return client.post(f"{API}/posts/{post_id}/copies", headers=headers)


def preview(client, headers, post_id):
    return client.get(f"{API}/posts/{post_id}/preview", headers=headers)


def test_copy_creates_a_new_draft_without_targets(client, db, mock_platforms):
    users, accounts = seed_club(db)
    publisher, admin = login(client, "pr@club.tw"), login(client, "president@club.tw")
    source = create_post_with_targets(client, publisher, [accounts["discord"].id], content="社課公告")
    mock_platforms[Platform.DISCORD].fail("公告", FailureReason.PLATFORM_UNAVAILABLE)
    publish(client, publisher, source)

    response = copy(client, admin, source)

    assert response.status_code == 201, response.text
    body = response.json()
    assert (body["status"], body["content"], body["creator"]["id"], body["targets"]) == (
        "DRAFT",
        "社課公告",
        users["admin"].id,
        [],
    )
    assert client.get(f"{API}/posts/{body['id']}/publish-records", headers=admin).json()["items"] == []
    original = client.get(f"{API}/posts/{source}", headers=admin).json()
    assert (original["status"], len(original["targets"])) == ("FAILED", 1)
    [audit] = db.scalars(select(models.AuditLog).where(models.AuditLog.action == AuditAction.POST_COPY))
    assert (audit.actor_id, audit.target_id, audit.related_post_id) == (users["admin"].id, body["id"], source)


def test_copy_permissions_and_any_status(client, db):
    _, accounts = seed_club(db)
    writer, publisher = login(client, "newbie@club.tw"), login(client, "pr@club.tw")
    own = create_post_with_targets(client, writer, [accounts["discord"].id])
    others = create_post_with_targets(client, publisher, [accounts["discord"].id])
    for status in (PostStatus.PUBLISHED, PostStatus.SCHEDULED, PostStatus.FAILED):
        post = db.get(models.Post, others)
        post.status = status
        post.scheduled_at = clock.now() + timedelta(hours=1) if status == PostStatus.SCHEDULED else None
        db.commit()
        assert copy(client, publisher, others).status_code == 201

    assert copy(client, writer, own).status_code == 201
    assert copy(client, writer, others).status_code == 403
    assert copy(client, publisher, 9999).status_code == 404


def test_preview_shows_each_selected_target(client, db):
    _, accounts = seed_club(db)
    writer = login(client, "newbie@club.tw")
    text = "社課公告"
    post_id = create_post_with_targets(
        client, writer, [accounts["threads"].id, accounts["discord"].id], content=text
    )
    accounts["threads"].auth_expires_at = clock.now() - timedelta(minutes=1)
    db.commit()

    response = preview(client, writer, post_id)

    assert response.status_code == 200, response.text
    items = {item["platform_account"]["account_name"]: item for item in response.json()["items"]}
    assert set(items) == {"ntu_guitar_threads", "公告"}
    threads = items["ntu_guitar_threads"]
    assert (threads["text"], threads["char_limit"], threads["platform_account"]["auth_status"]) == (
        text,
        500,
        AuthStatus.INVALID,
    )
    assert threads["char_count"] == 4  # 由各平台的 Adapter 計算（Threads 的 emoji 規則見 ThreadsAdapter）
    assert threads["warnings"] == ["AUTH_INVALID"]
    assert (items["公告"]["char_limit"], items["公告"]["warnings"], items["公告"]["image"]) == (
        2000,
        [],
        None,
    )


def test_preview_warns_about_text_over_the_limit(client, db):
    _, accounts = seed_club(db)
    headers = login(client, "pr@club.tw")
    post_id = create_post_with_targets(client, headers, [accounts["threads"].id], content="字" * 501)

    [item] = preview(client, headers, post_id).json()["items"]

    assert item["warnings"] == ["CONTENT_TOO_LONG"]


def test_preview_requires_a_target(client, db):
    seed_club(db)
    headers = login(client, "pr@club.tw")
    post_id = client.post(f"{API}/posts", json={"content": "社課"}, headers=headers).json()["id"]

    response = preview(client, headers, post_id)

    assert (response.status_code, response.json()["code"]) == (422, "NO_TARGET")


def test_history_lists_every_record_change_oldest_first(client, db, mock_platforms):
    users, accounts = seed_club(db)
    publisher = login(client, "pr@club.tw")
    post_id = create_post_with_targets(client, publisher, [accounts["discord"].id])
    publish(client, publisher, post_id)
    db.get(models.Post, post_id).deleted_at = clock.now()  # 刪除後仍可查
    db.commit()

    response = client.get(
        f"{API}/posts/{post_id}/publish-records/history", headers=login(client, "newbie@club.tw")
    )

    assert response.status_code == 200, response.text
    items = response.json()["items"]
    assert [(i["from_status"], i["to_status"], i["actor_type"], i["reason"]) for i in items] == [
        (None, "PENDING", "user", "PUBLISH_NOW"),
        ("PENDING", "SUCCEEDED", "system", "PUBLISH_SUCCEEDED"),
    ]
    assert items[0]["actor"] == {"id": users["publisher"].id, "name": "公關"}
    assert items[1]["actor"] is None
    assert {i["publish_record_id"] for i in items} == {
        db.scalar(select(models.PublishRecord.id).where(models.PublishRecord.post_id == post_id))
    }
