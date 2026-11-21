"""登入鎖定、IP 限流、登入安全事件、換發 Token、登出所有裝置、調整角色、解除鎖定
（FR-01、FR-23、FR-24、FR-26、BR-19、BR-39、BR-41～BR-43、NFR-07、NFR-10）。"""

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core import clock, models
from app.core.config import get_settings
from app.core.enums import AuditAction, Role
from tests.api.helpers import API, login, seed_club
from tests.factories import DEFAULT_PASSWORD

NOW = datetime(2026, 10, 5, 2, 0, tzinfo=UTC)  # 台灣 10:00
LOGIN = f"{API}/auth/login"


@pytest.fixture(autouse=True)
def fixed_now():
    clock.set_fixed(NOW)


def attempt(client, email, password=DEFAULT_PASSWORD):
    return client.post(LOGIN, json={"email": email, "password": password})


def user(db, email):
    db.expire_all()
    return db.scalar(select(models.UserAccount).where(models.UserAccount.email == email))


def events(db):
    db.expire_all()
    rows = db.scalars(select(models.LoginSecurityEvent).order_by(models.LoginSecurityEvent.id))
    return [(e.event_type, e.failure_reason, e.attempted_email, e.user_account_id) for e in rows]


def audit_actions(db):
    db.expire_all()
    return db.scalars(select(models.AuditLog.action).order_by(models.AuditLog.id)).all()


def refresh_cookie(response):
    return response.cookies.get("refresh_token")


def refresh(client, token):
    headers = {"Cookie": f"refresh_token={token}"} if token else {}
    return client.post(f"{API}/auth/refresh", headers=headers)


# ---------- IP 限流（BR-42） ----------


def test_eleventh_login_from_one_ip_is_refused(client, db, monkeypatch):
    seed_club(db)
    monkeypatch.setattr(get_settings(), "login_attempts_per_minute", 10)
    for _ in range(10):
        assert attempt(client, "pr@club.tw").status_code == 200

    refused = attempt(client, "pr@club.tw")

    assert (refused.status_code, refused.json()["code"]) == (429, "TOO_MANY_LOGIN_ATTEMPTS")
    assert int(refused.headers["Retry-After"]) == 60
    from app.main import app

    other_ip = TestClient(app, client=("198.51.100.7", 50000))
    assert attempt(other_ip, "pr@club.tw").status_code == 200


# ---------- 連續失敗鎖定（BR-41） ----------


def test_fifth_consecutive_failure_locks_for_fifteen_minutes(client, db):
    seed_club(db)
    for _ in range(4):
        attempt(client, "pr@club.tw", "wrong-password")
    assert user(db, "pr@club.tw").locked_until is None

    attempt(client, "pr@club.tw", "wrong-password")

    assert user(db, "pr@club.tw").locked_until == NOW + timedelta(minutes=15)
    assert attempt(client, "pr@club.tw").status_code == 401  # 鎖定期間密碼正確也不行
    clock.set_fixed(NOW + timedelta(minutes=14))
    assert attempt(client, "pr@club.tw").status_code == 401
    clock.set_fixed(NOW + timedelta(minutes=15))  # 到期那一刻即解除
    assert attempt(client, "pr@club.tw").status_code == 200
    assert user(db, "pr@club.tw").failed_login_count == 0


def test_success_resets_failure_count(client, db):
    seed_club(db)
    for _ in range(4):
        attempt(client, "pr@club.tw", "wrong-password")

    assert attempt(client, "pr@club.tw").status_code == 200

    assert user(db, "pr@club.tw").failed_login_count == 0


def test_every_login_failure_looks_the_same_and_is_recorded(client, db):
    users, _ = seed_club(db)
    users["writer"].status = "disabled"
    users["admin"].locked_until = NOW + timedelta(minutes=5)
    db.commit()

    responses = [
        attempt(client, "pr@club.tw", "wrong-password"),
        attempt(client, "newbie@club.tw"),
        attempt(client, "president@club.tw"),
        attempt(client, "  Nobody@Club.TW "),
    ]

    assert {(r.status_code, r.json()["code"], r.json()["message"]) for r in responses} == {
        (401, "LOGIN_FAILED", responses[0].json()["message"])
    }
    assert events(db) == [
        ("LOGIN_FAILED", "WRONG_PASSWORD", "pr@club.tw", users["publisher"].id),
        ("LOGIN_FAILED", "ACCOUNT_DISABLED", "newbie@club.tw", users["writer"].id),
        ("LOGIN_FAILED", "ACCOUNT_LOCKED", "president@club.tw", users["admin"].id),
        ("LOGIN_FAILED", "ACCOUNT_NOT_FOUND", "nobody@club.tw", None),
    ]
    assert not any("wrong-password" in str(field) for event in events(db) for field in event)
    assert audit_actions(db) == []  # 登入失敗不寫一般稽核


# ---------- 換發 Token、登出所有裝置（FR-01、FR-24、BR-43） ----------


def test_refresh_issues_a_new_access_token(client, db):
    seed_club(db)
    token = refresh_cookie(attempt(client, "pr@club.tw"))

    response = refresh(client, token)

    assert response.status_code == 200, response.text
    assert response.json()["expires_in"] == 900
    headers = {"Authorization": f"Bearer {response.json()['access_token']}"}
    assert client.get(f"{API}/auth/me", headers=headers).json()["email"] == "pr@club.tw"


def test_refresh_is_refused_for_ended_sessions(client, db):
    users, _ = seed_club(db)
    logged_out = attempt(client, "pr@club.tw")
    client.post(
        f"{API}/auth/logout", headers={"Authorization": f"Bearer {logged_out.json()['access_token']}"}
    )
    disabled = refresh_cookie(attempt(client, "newbie@club.tw"))
    users["writer"].status = "disabled"
    db.commit()
    expiring = refresh_cookie(attempt(client, "president@club.tw"))

    assert refresh(client, refresh_cookie(logged_out)).status_code == 401
    assert refresh(client, disabled).status_code == 401
    assert refresh(client, None).status_code == 401
    assert refresh(client, "not-a-real-token").status_code == 401
    clock.set_fixed(NOW + timedelta(days=7))
    assert refresh(client, expiring).status_code == 401


def test_logout_all_revokes_every_session_of_that_user(client, db):
    seed_club(db)
    s1, s2 = login(client, "pr@club.tw"), login(client, "pr@club.tw")
    s2_refresh = refresh_cookie(attempt(client, "pr@club.tw"))
    other = login(client, "newbie@club.tw")

    response = client.post(f"{API}/auth/logout-all", headers=s1)

    assert response.status_code == 204, response.text
    assert client.get(f"{API}/auth/me", headers=s1).status_code == 401
    assert client.get(f"{API}/auth/me", headers=s2).status_code == 401
    assert refresh(client, s2_refresh).status_code == 401
    assert client.get(f"{API}/auth/me", headers=other).status_code == 200
    assert client.get(f"{API}/auth/me", headers=login(client, "pr@club.tw")).status_code == 200
    assert AuditAction.LOGOUT_ALL in audit_actions(db)


# ---------- 調整角色（FR-04、BR-19） ----------


def change_role(client, headers, user_id, role):
    return client.patch(f"{API}/users/{user_id}", json={"role": role}, headers=headers)


def test_change_role(client, db):
    users, accounts = seed_club(db)
    admin = login(client, "president@club.tw")
    writer = login(client, "newbie@club.tw")

    assert change_role(client, login(client, "pr@club.tw"), users["writer"].id, "admin").status_code == 403
    assert change_role(client, admin, users["writer"].id, "president").status_code == 400
    response = change_role(client, admin, users["writer"].id, "publisher")

    assert (response.status_code, response.json()["role"]) == (200, "publisher")
    assert client.get(f"{API}/auth/me", headers=writer).json()["role"] == "publisher"  # 立即生效
    assert AuditAction.USER_ROLE_CHANGE in audit_actions(db)
    assert len(client.get(f"{API}/platform-accounts", headers=admin).json()["items"]) == len(accounts)


def test_last_active_admin_keeps_admin_role(client, db):
    users, _ = seed_club(db)
    admin = login(client, "president@club.tw")

    refused = change_role(client, admin, users["admin"].id, "publisher")

    assert (refused.status_code, refused.json()["code"]) == (409, "LAST_ACTIVE_ADMIN")
    change_role(client, admin, users["publisher"].id, "admin")
    assert change_role(client, admin, users["admin"].id, "publisher").status_code == 200


def test_disabled_account_role_can_change_and_stays_disabled(client, db):
    users, _ = seed_club(db)
    users["writer"].status = "disabled"
    db.commit()

    response = change_role(client, login(client, "president@club.tw"), users["writer"].id, "publisher")

    assert (response.status_code, response.json()["role"], response.json()["status"]) == (
        200, "publisher", "disabled"
    )


# ---------- 解除鎖定（FR-26、BR-39） ----------


def unlock(client, headers, user_id):
    return client.delete(f"{API}/users/{user_id}/lock", headers=headers)


def test_unlock(client, db):
    users, _ = seed_club(db)
    admin = login(client, "president@club.tw")
    for _ in range(5):
        attempt(client, "pr@club.tw", "wrong-password")
    assert user(db, "pr@club.tw").locked_until is not None

    assert unlock(client, login(client, "newbie@club.tw"), users["publisher"].id).status_code == 403
    response = unlock(client, admin, users["publisher"].id)

    assert response.status_code == 200, response.text
    assert (response.json()["locked_until"], response.json()["is_locked"]) == (None, False)
    assert user(db, "pr@club.tw").failed_login_count == 0
    attempt(client, "pr@club.tw", "wrong-password")
    assert user(db, "pr@club.tw").locked_until is None  # 輸錯一次不會立刻再被鎖定
    assert attempt(client, "pr@club.tw").status_code == 200
    assert AuditAction.USER_UNLOCK in audit_actions(db)


def test_unlock_requires_a_locked_account(client, db):
    users, _ = seed_club(db)

    response = unlock(client, login(client, "president@club.tw"), users["writer"].id)

    assert (response.status_code, response.json()["code"]) == (409, "USER_NOT_LOCKED")
    assert AuditAction.USER_UNLOCK not in audit_actions(db)


def test_unlocking_a_disabled_account_keeps_it_disabled(client, db):
    users, _ = seed_club(db)
    users["writer"].status = "disabled"
    users["writer"].locked_until = NOW + timedelta(minutes=10)
    db.commit()

    response = unlock(client, login(client, "president@club.tw"), users["writer"].id)

    assert (response.status_code, response.json()["status"]) == (200, "disabled")
    assert attempt(client, "newbie@club.tw").status_code == 401
    assert Role.WRITER == user(db, "newbie@club.tw").role
