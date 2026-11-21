"""Threads、Instagram 以平台授權重新連結（FR-21、BR-37、BR-38）與 Instagram 授權連結。"""

from datetime import timedelta
from urllib.parse import parse_qs, urlparse

from sqlalchemy import select

from app.core import clock, crypto, models, platforms
from app.core.enums import AuditAction, Platform
from app.core.platforms import OAuthAccount
from tests.api.helpers import API, login, seed_club

START = f"{API}/platform-accounts/oauth-authorizations"
CALLBACK = f"{API}/platform-accounts/oauth/callback"


def start(client, headers, platform="threads", account_id=None):
    body = {"platform": platform} | ({"platform_account_id": account_id} if account_id else {})
    return client.post(START, json=body, headers=headers)


def authorize(client, headers, platform="threads", account_id=None, **callback_params):
    response = start(client, headers, platform, account_id)
    assert response.status_code == 200, response.text
    state = parse_qs(urlparse(response.json()["authorization_url"]).query)["state"][0]
    params = {"code": "test-code", "state": state} | callback_params
    redirect = client.get(CALLBACK, params=params, follow_redirects=False)
    assert redirect.status_code == 302, redirect.text
    return parse_qs(urlparse(redirect.headers["location"]).query)["result"][0]


def linked_threads(db, mock_platforms, users, accounts):
    """把 seed 的 Threads 帳號設成曾以授權連結（有平台識別碼與到期時間）。"""
    threads = accounts["threads"]
    threads.platform_user_id = "th-1001"
    threads.auth_expires_at = clock.now() - timedelta(days=1)  # 已過期，需要重新連結
    db.commit()
    return threads


def auth_events(db):
    db.expire_all()
    rows = db.scalars(select(models.PlatformAuthEvent).order_by(models.PlatformAuthEvent.id))
    return [(e.event_type, e.platform_account_id, e.account_name, e.failure_reason) for e in rows]


def test_relink_renews_credential_expiry_and_name(client, db, mock_platforms):
    users, accounts = seed_club(db)
    threads = linked_threads(db, mock_platforms, users, accounts)
    new_expiry = clock.now() + timedelta(days=60)
    mock_platforms[Platform.THREADS].oauth_account(
        OAuthAccount("th-1001", "ntu_guitar_threads_v2", {"access_token": "new-token"}, new_expiry)
    )

    result = authorize(client, login(client, "president@club.tw"), account_id=threads.id)

    assert result == "relinked"
    db.expire_all()
    account = db.get(models.PlatformAccount, threads.id)
    assert (account.account_name, account.auth_expires_at, account.auth_status) == (
        "ntu_guitar_threads_v2",
        new_expiry,
        "valid",
    )
    assert crypto.decrypt_credential(account.credential_encrypted)["access_token"] == "new-token"
    assert account.linked_by == users["admin"].id
    [audit] = db.scalars(select(models.AuditLog).where(models.AuditLog.action == AuditAction.PLATFORM_RELINK))
    assert audit.target_id == threads.id


def test_relink_to_a_different_platform_account_is_refused(client, db, mock_platforms):
    users, accounts = seed_club(db)
    threads = linked_threads(db, mock_platforms, users, accounts)
    before = bytes(threads.credential_encrypted)
    mock_platforms[Platform.THREADS].oauth_account(
        OAuthAccount("th-9999", "someone_else", {"access_token": "other"}, None)
    )

    result = authorize(client, login(client, "president@club.tw"), account_id=threads.id)

    assert result == "PLATFORM_ID_MISMATCH"
    db.expire_all()
    account = db.get(models.PlatformAccount, threads.id)
    assert (account.account_name, bytes(account.credential_encrypted)) == ("ntu_guitar_threads", before)
    assert auth_events(db) == [("RELINK_FAILED", threads.id, "ntu_guitar_threads", "PLATFORM_ID_MISMATCH")]


def test_relink_name_taken_by_another_account_records_no_event(client, db, mock_platforms):
    users, accounts = seed_club(db)
    threads = linked_threads(db, mock_platforms, users, accounts)
    other = models.PlatformAccount(
        platform="threads",
        account_name="taken_name",
        credential_encrypted=threads.credential_encrypted,
        credential_key_version=threads.credential_key_version,
        linked_by=users["admin"].id,
    )
    db.add(other)
    db.commit()
    mock_platforms[Platform.THREADS].oauth_account(
        OAuthAccount("th-1001", "taken_name", {"access_token": "x"}, None)
    )

    result = authorize(client, login(client, "president@club.tw"), account_id=threads.id)

    assert result == "PLATFORM_ACCOUNT_NAME_TAKEN"
    assert auth_events(db) == []


def test_denied_relink_keeps_data_and_records_event(client, db, mock_platforms):
    users, accounts = seed_club(db)
    threads = linked_threads(db, mock_platforms, users, accounts)

    result = authorize(
        client, login(client, "president@club.tw"), account_id=threads.id, error="access_denied", code=""
    )

    assert result == "PLATFORM_AUTH_FAILED"
    assert auth_events(db) == [("RELINK_FAILED", threads.id, "ntu_guitar_threads", "PLATFORM_AUTH_FAILED")]
    db.expire_all()
    assert db.get(models.PlatformAccount, threads.id).auth_expires_at < clock.now()


def test_relink_rules(client, db):
    _, accounts = seed_club(db)
    admin = login(client, "president@club.tw")

    wrong_platform = start(client, admin, "instagram", accounts["threads"].id)
    discord = start(client, admin, "discord", accounts["discord"].id)
    missing = start(client, admin, "threads", 9999)

    assert (wrong_platform.status_code, discord.status_code, missing.status_code) == (400, 400, 404)


def test_instagram_can_link_when_its_adapter_supports_oauth(client, db, mock_platforms):
    seed_club(db)
    admin = login(client, "president@club.tw")
    mock_platforms[Platform.INSTAGRAM].oauth_account(
        OAuthAccount("ig-2001", "club_ig_new", {"access_token": "ig"}, clock.now() + timedelta(days=60))
    )

    assert authorize(client, admin, "instagram") == "linked"

    platforms.register_adapter(platforms.UnavailableAdapter(Platform.INSTAGRAM))
    refused = start(client, admin, "instagram")
    assert (refused.status_code, refused.json()["code"]) == (400, "VALIDATION_ERROR")


def test_callback_rejects_an_admin_disabled_after_starting(client, db, mock_platforms):
    """回呼沒有登入標頭：開始授權之後才被停用或降級的管理員，導回時不可完成連結。"""
    users, accounts = seed_club(db)
    threads = linked_threads(db, mock_platforms, users, accounts)
    before = (threads.account_name, bytes(threads.credential_encrypted), threads.auth_expires_at)
    mock_platforms[Platform.THREADS].oauth_account(
        OAuthAccount("th-1001", "renamed", {"access_token": "t"}, None)
    )
    response = start(client, login(client, "president@club.tw"), account_id=threads.id)
    state = parse_qs(urlparse(response.json()["authorization_url"]).query)["state"][0]
    db.get(models.UserAccount, users["admin"].id).role = "publisher"
    db.commit()

    redirect = client.get(CALLBACK, params={"code": "c", "state": state}, follow_redirects=False)

    assert parse_qs(urlparse(redirect.headers["location"]).query)["result"] == ["PLATFORM_AUTH_FAILED"]
    db.expire_all()
    account = db.get(models.PlatformAccount, threads.id)
    assert (account.account_name, bytes(account.credential_encrypted), account.auth_expires_at) == before
    assert auth_events(db) == []


def test_relink_restores_an_account_marked_invalid(client, db, mock_platforms):
    """平台撤銷 Token 後帳號被標示失效（BR-09）；重新連結成功要改回有效。"""
    users, accounts = seed_club(db)
    threads = linked_threads(db, mock_platforms, users, accounts)
    threads.auth_status = "invalid"
    threads.auth_expires_at = clock.now() + timedelta(days=30)  # 還沒到期，是被撤銷
    db.commit()
    mock_platforms[Platform.THREADS].oauth_account(
        OAuthAccount(
            "th-1001", "ntu_guitar_threads", {"access_token": "new"}, clock.now() + timedelta(days=60)
        )
    )

    assert authorize(client, login(client, "president@club.tw"), account_id=threads.id) == "relinked"

    db.expire_all()
    assert db.get(models.PlatformAccount, threads.id).auth_status == "valid"


def test_relink_refuses_an_account_without_a_platform_id(client, db, mock_platforms):
    """沒有平台識別碼就無法確認是不是同一個帳號：一律拒絕，不接受任何登入的帳號。"""
    users, accounts = seed_club(db)
    threads = accounts["threads"]
    threads.platform_user_id = None
    db.commit()
    mock_platforms[Platform.THREADS].oauth_account(
        OAuthAccount("th-anyone", "someone", {"access_token": "t"}, None)
    )

    assert (
        authorize(client, login(client, "president@club.tw"), account_id=threads.id) == "PLATFORM_ID_MISMATCH"
    )
    db.expire_all()
    assert db.get(models.PlatformAccount, threads.id).account_name == "ntu_guitar_threads"
