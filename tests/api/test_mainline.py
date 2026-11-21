from sqlalchemy import select

from app.core import models
from app.core.enums import AuditAction, AuthStatus, Platform, Role
from tests.api.helpers import (
    API,
    create_post_with_targets,
    history_rows,
    login,
    publish,
    records_by_account,
    seed_club,
)
from tests.factories import make_account, make_post, make_user

# ---------- 登入 ----------


def test_login_and_me(client, db):
    make_user(db, "pr@club.tw", Role.PUBLISHER, "公關")
    db.commit()

    response = client.post(
        f"{API}/auth/login", json={"email": "  PR@Club.tw ", "password": "correct-horse-battery"}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["token_type"] == "Bearer" and body["expires_in"] == 900
    assert body["user"] == {"id": 1, "email": "pr@club.tw", "name": "公關", "role": "publisher"}
    assert "HttpOnly" in response.headers["set-cookie"]

    me = client.get(f"{API}/auth/me", headers={"Authorization": f"Bearer {body['access_token']}"})
    assert me.status_code == 200
    assert me.json() == body["user"]
    assert db.scalars(select(models.AuditLog.action)).all() == [AuditAction.LOGIN]


def test_wrong_password_and_unknown_email_get_the_same_answer(client, db):
    make_user(db, "pr@club.tw")
    db.commit()

    wrong = client.post(f"{API}/auth/login", json={"email": "pr@club.tw", "password": "nope-nope"})
    unknown = client.post(f"{API}/auth/login", json={"email": "x@club.tw", "password": "nope-nope"})

    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json()["code"] == unknown.json()["code"] == "LOGIN_FAILED"
    assert wrong.json()["message"] == unknown.json()["message"]


def test_requests_without_token_are_unauthenticated(client):
    response = client.get(f"{API}/posts")

    assert response.status_code == 401
    assert response.json()["code"] == "UNAUTHENTICATED"


def test_disabled_account_token_stops_working_immediately(client, db):
    user = make_user(db, "pr@club.tw")
    db.commit()
    headers = login(client, "pr@club.tw")

    user.status = "disabled"
    db.commit()

    assert client.get(f"{API}/auth/me", headers=headers).status_code == 401


# ---------- 貼文與目標 ----------


def test_create_post_rejects_blank_content(client, db):
    seed_club(db)
    headers = login(client, "newbie@club.tw")

    response = client.post(f"{API}/posts", json={"content": "   "}, headers=headers)

    assert response.status_code == 422
    assert response.json()["code"] == "CONTENT_EMPTY"


def test_created_post_is_a_draft_owned_by_its_creator(client, db):
    seed_club(db)
    headers = login(client, "newbie@club.tw")

    created = client.post(f"{API}/posts", json={"content": "社課公告"}, headers=headers)

    assert created.status_code == 201
    body = created.json()
    assert (body["status"], body["content"], body["targets"]) == ("DRAFT", "社課公告", [])
    assert body["creator"]["name"] == "新進幹部"
    assert client.get(f"{API}/posts/{body['id']}", headers=headers).json() == body


def test_set_targets_replaces_the_whole_set(client, db):
    _, accounts = seed_club(db)
    headers = login(client, "pr@club.tw")
    post_id = create_post_with_targets(
        client, headers, [accounts["threads"].id, accounts["discord"].id]
    )

    client.put(
        f"{API}/posts/{post_id}/targets",
        json={"platform_account_ids": [accounts["discord"].id]},
        headers=headers,
    )

    targets = client.get(f"{API}/posts/{post_id}", headers=headers).json()["targets"]
    assert [t["account_name"] for t in targets] == ["公告"]


def test_set_targets_rules(client, db):
    users, accounts = seed_club(db)
    removed = make_account(db, users["admin"], Platform.DISCORD, "舊頻道", removed=True)
    invalid = make_account(
        db, users["admin"], Platform.THREADS, "revoked", auth_status=AuthStatus.INVALID
    )
    others_post = make_post(db, users["publisher"])
    db.commit()
    headers = login(client, "pr@club.tw")
    post_id = client.post(f"{API}/posts", json={"content": "x"}, headers=headers).json()["id"]
    url = f"{API}/posts/{post_id}/targets"

    def put(ids, target_url=url, with_headers=headers):
        response = client.put(target_url, json={"platform_account_ids": ids}, headers=with_headers)
        return response.status_code, response.json().get("code")

    discord = accounts["discord"].id
    assert put([discord, discord]) == (400, "TARGET_DUPLICATE")
    assert put([removed.id]) == (422, "TARGET_NOT_AVAILABLE")
    assert put([99999]) == (422, "TARGET_NOT_AVAILABLE")
    assert put([invalid.id]) == (422, "TARGET_AUTH_INVALID")
    writer = login(client, "newbie@club.tw")
    assert put([discord], f"{API}/posts/{others_post.id}/targets", writer) == (403, "FORBIDDEN")
    assert put([discord], f"{API}/posts/99999/targets") == (404, "NOT_FOUND")


def test_list_posts_is_paginated_newest_first(client, db):
    users, _ = seed_club(db)
    for index in range(25):
        make_post(db, users["publisher"], content=f"公告 {index}")
    db.commit()
    headers = login(client, "newbie@club.tw")

    first = client.get(f"{API}/posts", headers=headers).json()
    second = client.get(f"{API}/posts?page=2", headers=headers).json()
    bad_size = client.get(f"{API}/posts?page_size=30", headers=headers)

    assert [item["content"] for item in first["items"][:2]] == ["公告 24", "公告 23"]
    assert (first["total"], first["total_pages"], first["has_next"], first["has_prev"]) == (
        25, 2, True, False,
    )
    assert len(second["items"]) == 5 and second["has_prev"] is True
    assert (bad_size.status_code, bad_size.json()["code"]) == (400, "VALIDATION_ERROR")


def test_platform_accounts_list_hides_credentials_and_removed_accounts(client, db):
    users, _ = seed_club(db)
    make_account(db, users["admin"], Platform.DISCORD, "舊頻道", removed=True)
    db.commit()

    response = client.get(f"{API}/platform-accounts", headers=login(client, "newbie@club.tw"))

    assert response.status_code == 200
    items = response.json()["items"]
    assert sorted(item["account_name"] for item in items) == sorted(
        ["ntu_guitar_threads", "ntu_guitar_ig", "公告"]
    )
    assert set(items[0]) == {"id", "platform", "account_name", "auth_status", "auth_expires_at"}


# ---------- 立即發佈（主線） ----------


def test_publish_to_three_targets_succeeds(client, db, mock_platforms):
    users, accounts = seed_club(db)
    mock_platforms[Platform.DISCORD].succeed("公告", "https://discord.test/m/1")
    headers = login(client, "pr@club.tw")
    post_id = create_post_with_targets(client, headers, [a.id for a in accounts.values()])

    accepted = publish(client, headers, post_id)

    assert accepted.status_code == 202
    body = accepted.json()
    assert (body["post_id"], body["post_status"]) == (post_id, "PUBLISHING")
    assert [record["status"] for record in body["records"]] == ["PENDING"] * 3

    assert client.get(f"{API}/posts/{post_id}", headers=headers).json()["status"] == "PUBLISHED"
    records = records_by_account(client, headers, post_id)
    assert {name: r["status"] for name, r in records.items()} == {
        "ntu_guitar_threads": "SUCCEEDED", "ntu_guitar_ig": "SUCCEEDED", "公告": "SUCCEEDED",
    }
    assert records["公告"]["platform_post_url"] == "https://discord.test/m/1"
    assert all(r["published_at"] and r["failure_reason"] is None for r in records.values())
    for platform in Platform:
        assert [content.text for _, content in mock_platforms[platform].received] == [
            "本週三 19:00 社課"
        ]

    history = history_rows(db, post_id)
    assert history.count((None, "PENDING", "user", "PUBLISH_NOW")) == 3
    assert history.count(("PENDING", "SUCCEEDED", "system", "PUBLISH_SUCCEEDED")) == 3

    audit = db.scalars(
        select(models.AuditLog).where(models.AuditLog.action == AuditAction.POST_PUBLISH)
    ).one()
    assert (audit.actor_id, audit.target_id, audit.result) == (
        users["publisher"].id, post_id, "PUBLISHED",
    )
    assert [r.status for r in audit.target_results] == ["SUCCEEDED"] * 3


def test_writer_cannot_publish(client, db, mock_platforms):
    _, accounts = seed_club(db)
    headers = login(client, "newbie@club.tw")
    post_id = create_post_with_targets(client, headers, [accounts["discord"].id])

    response = publish(client, headers, post_id)

    assert (response.status_code, response.json()["code"]) == (403, "FORBIDDEN")
    assert client.get(f"{API}/posts/{post_id}", headers=headers).json()["status"] == "DRAFT"
    assert records_by_account(client, headers, post_id) == {}
    assert mock_platforms[Platform.DISCORD].received == []


def test_publish_without_target_is_rejected(client, db):
    seed_club(db)
    headers = login(client, "pr@club.tw")
    post_id = client.post(f"{API}/posts", json={"content": "x"}, headers=headers).json()["id"]

    response = publish(client, headers, post_id)

    assert (response.status_code, response.json()["code"]) == (422, "NO_TARGET")
    assert client.get(f"{API}/posts/{post_id}", headers=headers).json()["status"] == "DRAFT"


def test_publish_rejects_text_over_target_limit(client, db, mock_platforms):
    _, accounts = seed_club(db)
    headers = login(client, "pr@club.tw")
    post_id = create_post_with_targets(
        client, headers, [accounts["discord"].id], content="字" * 2001
    )

    response = publish(client, headers, post_id)

    assert (response.status_code, response.json()["code"]) == (422, "CONTENT_TOO_LONG")
    assert response.json()["detail"] == {"platform": "discord", "limit": 2000, "length": 2001}
    assert client.get(f"{API}/posts/{post_id}", headers=headers).json()["status"] == "DRAFT"
    assert records_by_account(client, headers, post_id) == {}
    assert mock_platforms[Platform.DISCORD].received == []


def test_published_post_cannot_be_published_again(client, db, mock_platforms):
    _, accounts = seed_club(db)
    headers = login(client, "pr@club.tw")
    post_id = create_post_with_targets(client, headers, [accounts["discord"].id])
    publish(client, headers, post_id)

    again = publish(client, headers, post_id)

    assert (again.status_code, again.json()["code"]) == (409, "POST_NOT_PUBLISHABLE")
    assert len(mock_platforms[Platform.DISCORD].received) == 1
