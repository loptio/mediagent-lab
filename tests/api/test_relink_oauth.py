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
