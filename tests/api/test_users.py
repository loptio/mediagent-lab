"""登出與幹部帳號管理（FR-01～FR-05、BR-17、BR-19～BR-21、BR-40、需求 4.1）。"""

import pytest
from sqlalchemy import select

from app.core import models
from app.core.enums import AuditAction, Role
from tests.api.helpers import API, create_post_with_targets, login, seed_club
from tests.factories import DEFAULT_PASSWORD

USERS = f"{API}/users"


def audit_actions(db):
    db.expire_all()
    return db.scalars(select(models.AuditLog.action).order_by(models.AuditLog.id)).all()


def new_user(**fields):
    return {"email": "bob@club.tw", "name": "Bob", "role": "writer", "initial_password": "abcd1234"} | fields


def set_status(client, headers, user_id, status):
    return client.put(f"{USERS}/{user_id}/status", json={"status": status}, headers=headers)


def test_logout_revokes_only_current_session(client, db):
    seed_club(db)
    s1 = login(client, "pr@club.tw")
    s2 = login(client, "pr@club.tw")

    response = client.post(f"{API}/auth/logout", headers=s1)

    assert response.status_code == 204, response.text
    assert client.get(f"{API}/auth/me", headers=s1).status_code == 401
    assert client.get(f"{API}/auth/me", headers=s2).status_code == 200
    assert client.get(f"{API}/auth/me", headers=login(client, "pr@club.tw")).status_code == 200
    assert AuditAction.LOGOUT in audit_actions(db)


def test_only_admin_can_list_and_create_users(client, db):
    seed_club(db)
    for email in ("pr@club.tw", "newbie@club.tw"):
        headers = login(client, email)
        assert client.get(USERS, headers=headers).status_code == 403
        assert client.post(USERS, json=new_user(), headers=headers).status_code == 403


def test_list_users_includes_disabled(client, db):
    users, _ = seed_club(db)
    users["writer"].status = "disabled"
    db.commit()

    response = client.get(USERS, headers=login(client, "president@club.tw"))

    assert response.status_code == 200, response.text
    items = response.json()["items"]
    assert [(u["email"], u["role"], u["status"]) for u in items] == [
        ("president@club.tw", "admin", "active"),
        ("pr@club.tw", "publisher", "active"),
        ("newbie@club.tw", "writer", "disabled"),
    ]
    assert {"locked_until", "is_locked"} <= items[0].keys()
    assert all("password" not in key for item in items for key in item)


def test_create_user(client, db):
    seed_club(db)
    admin = login(client, "president@club.tw")

    created = [
        client.post(USERS, json=new_user(email=f"  {role.title()}@Club.TW ", role=role), headers=admin)
        for role in ("admin", "publisher", "writer")
    ]

    assert [r.status_code for r in created] == [201, 201, 201]
    body = created[2].json()
    assert (body["email"], body["name"], body["role"], body["status"]) == (
        "writer@club.tw", "Bob", "writer", "active"
    )
    assert not any("password" in key for key in body)
    stored = db.scalar(select(models.UserAccount).where(models.UserAccount.email == "writer@club.tw"))
    assert stored.password_hash != "abcd1234" and "abcd1234" not in stored.password_hash
    assert client.post(
        f"{API}/auth/login", json={"email": "writer@club.tw", "password": "abcd1234"}
    ).status_code == 200
    assert audit_actions(db).count(AuditAction.USER_CREATE) == 3


@pytest.mark.parametrize(
    ("fields", "status", "code"),
    [
        ({"role": "president"}, 400, "VALIDATION_ERROR"),
        ({"email": "not-an-email"}, 400, "VALIDATION_ERROR"),
        ({"initial_password": "abc1234"}, 422, "PASSWORD_TOO_SHORT"),
        ({"initial_password": ""}, 422, "PASSWORD_TOO_SHORT"),
        ({"initial_password": "        "}, 422, "PASSWORD_TOO_SHORT"),
        ({"email": "PR@club.tw"}, 409, "EMAIL_TAKEN"),
    ],
)
def test_create_user_validation(client, db, fields, status, code):
    seed_club(db)

    response = client.post(USERS, json=new_user(**fields), headers=login(client, "president@club.tw"))

    assert (response.status_code, response.json()["code"]) == (status, code)


def test_letters_only_password_of_eight_characters_is_accepted(client, db):
    seed_club(db)

    response = client.post(
        USERS, json=new_user(initial_password="abcdefgh"), headers=login(client, "president@club.tw")
    )

    assert response.status_code == 201, response.text


def test_duplicate_email_from_database_constraint_is_409(client, db, monkeypatch):
    """檢查 Email 之後、寫入之前被別人搶先建立：由資料庫的唯一限制擋下，仍回 409。"""
    from app.m1_accounts import repository

    seed_club(db)
    admin = login(client, "president@club.tw")
    monkeypatch.setattr(repository, "get_by_email", lambda db, email: None)

    response = client.post(USERS, json=new_user(email="pr@club.tw"), headers=admin)

    assert (response.status_code, response.json()["code"]) == (409, "EMAIL_TAKEN")


def test_disable_revokes_sessions_and_blocks_login(client, db):
    users, accounts = seed_club(db)
    writer = login(client, "newbie@club.tw")
    post_id = create_post_with_targets(client, writer, [accounts["discord"].id])
    admin = login(client, "president@club.tw")

    response = set_status(client, admin, users["writer"].id, "disabled")

    assert response.status_code == 200, response.text
    assert response.json()["status"] == "disabled"
    assert client.get(f"{API}/auth/me", headers=writer).status_code == 401
    assert client.post(
        f"{API}/auth/login", json={"email": "newbie@club.tw", "password": DEFAULT_PASSWORD}
    ).status_code == 401
    assert client.get(f"{API}/posts/{post_id}", headers=admin).json()["creator"]["id"] == users["writer"].id
    assert [a["id"] for a in client.get(f"{API}/platform-accounts", headers=admin).json()["items"]] == [
        a.id for a in accounts.values()
    ]
    assert AuditAction.USER_DISABLE in audit_actions(db)


def test_last_active_admin_cannot_be_disabled(client, db):
    users, _ = seed_club(db)
    admin = login(client, "president@club.tw")

    refused = set_status(client, admin, users["admin"].id, "disabled")

    assert (refused.status_code, refused.json()["code"]) == (409, "LAST_ACTIVE_ADMIN")
    users["publisher"].role = Role.ADMIN
    db.commit()
    assert set_status(client, admin, users["admin"].id, "disabled").status_code == 200


def test_enable_and_status_conflicts(client, db):
    users, _ = seed_club(db)
    admin = login(client, "president@club.tw")
    set_status(client, admin, users["writer"].id, "disabled")

    again = set_status(client, admin, users["writer"].id, "disabled")
    enabled = set_status(client, admin, users["writer"].id, "active")
    not_disabled = set_status(client, admin, users["writer"].id, "active")

    assert (again.status_code, again.json()["code"]) == (409, "USER_ALREADY_DISABLED")
    assert (enabled.status_code, enabled.json()["status"]) == (200, "active")
    assert (not_disabled.status_code, not_disabled.json()["code"]) == (409, "USER_NOT_DISABLED")
    assert client.get(f"{API}/auth/me", headers=login(client, "newbie@club.tw")).status_code == 200
    assert AuditAction.USER_ENABLE in audit_actions(db)
    assert set_status(client, admin, 9999, "active").status_code == 404
