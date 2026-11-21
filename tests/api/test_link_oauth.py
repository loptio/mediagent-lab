from datetime import timedelta
from urllib.parse import parse_qs, urlparse

from sqlalchemy import select

from app.core import clock, crypto, models
from app.core.enums import AuditAction, Platform
from app.core.platforms import OAuthAccount
from app.m2_platforms import oauth_state
from tests.api.helpers import API, create_post_with_targets, login, publish, records_by_account, seed_club

START = f"{API}/platform-accounts/oauth-authorizations"
CALLBACK = f"{API}/platform-accounts/oauth/callback"
RESULT = f"{API}/platform-accounts/oauth/result"


def start(client, headers, **body):
    return client.post(START, json={"platform": "threads", **body}, headers=headers)


def issue_state_via_api(client, db):
    seed_club(db)
    response = start(client, login(client, "president@club.tw"))
    assert response.status_code == 200, response.text
    return parse_qs(urlparse(response.json()["authorization_url"]).query)["state"][0]


def callback(client, **params):
    return client.get(CALLBACK, params=params, follow_redirects=False)


def result_of(response):
    assert response.status_code == 302, response.text
    return parse_qs(urlparse(response.headers["location"]).query)["result"][0]


def threads_accounts(db):
    rows = db.scalars(
        select(models.PlatformAccount).where(models.PlatformAccount.platform == Platform.THREADS)
    )
    return {account.account_name: account for account in rows}


def auth_events(db):
    rows = db.scalars(select(models.PlatformAuthEvent).order_by(models.PlatformAuthEvent.id))
    return [(e.event_type, e.platform, e.account_name, e.failure_reason, e.actor_id) for e in rows]


def test_start_returns_authorization_url_with_state(client, db):
    users, _ = seed_club(db)

    response = start(client, login(client, "president@club.tw"))

    assert response.status_code == 200
    url = urlparse(response.json()["authorization_url"])
    query = parse_qs(url.query)
    assert url.netloc == "threads.test"
    assert query["redirect_uri"] == [f"http://localhost:8000{CALLBACK}"]
    state = oauth_state.read_state(query["state"][0])
    assert (state.admin_id, state.platform) == (users["admin"].id, "threads")


def test_start_requires_admin(client, db, mock_platforms):
    seed_club(db)

    response = start(client, login(client, "pr@club.tw"))

    assert (response.status_code, response.json()["code"]) == (403, "FORBIDDEN")


def test_start_rejects_discord_instagram_and_relink(client, db):
    seed_club(db)
    admin = login(client, "president@club.tw")

    for body in ({"platform": "discord"}, {"platform": "instagram"}, {"platform_account_id": 1}):
        response = start(client, admin, **body)
        assert (response.status_code, response.json()["code"]) == (400, "VALIDATION_ERROR"), body


def test_callback_links_account(client, db, mock_platforms):
    state = issue_state_via_api(client, db)
    admin_id = db.scalar(select(models.UserAccount.id).where(models.UserAccount.role == "admin"))

    response = callback(client, code="auth-code-1", state=state)

    assert result_of(response) == "linked"
    assert mock_platforms[Platform.THREADS].exchanged == [
        ("auth-code-1", f"http://localhost:8000{CALLBACK}")
    ]
    account = threads_accounts(db)["mock_threads"]
    assert (account.platform_user_id, account.linked_by, account.auth_status) == ("1001", admin_id, "valid")
    assert account.auth_expires_at - clock.now() > timedelta(days=59)
    credential = crypto.decrypt_credential(account.credential_encrypted)
    assert credential["access_token"] == "mock-token-threads"
    assert b"mock-token-threads" not in bytes(account.credential_encrypted)

    listing = client.get(f"{API}/platform-accounts", headers=login(client, "pr@club.tw"))
    assert "mock_threads" in listing.text and "mock-token-threads" not in listing.text
    audit = db.scalars(
        select(models.AuditLog).where(models.AuditLog.action == AuditAction.PLATFORM_LINK)
    ).one()
    assert (audit.actor_id, audit.target_id) == (admin_id, account.id)


def test_callback_when_user_denies_records_auth_event(client, db, mock_platforms):
    state = issue_state_via_api(client, db)
    admin_id = db.scalar(select(models.UserAccount.id).where(models.UserAccount.role == "admin"))

    response = callback(
        client, state=state, error="access_denied", error_reason="user_denied",
        error_description="The user denied your request.",
    )

    assert result_of(response) == "PLATFORM_AUTH_FAILED"
    assert mock_platforms[Platform.THREADS].exchanged == []
    assert "mock_threads" not in threads_accounts(db)
    assert auth_events(db) == [("LINK_FAILED", "threads", None, "PLATFORM_AUTH_FAILED", admin_id)]


def test_callback_when_exchange_fails_records_auth_event(client, db, mock_platforms):
    state = issue_state_via_api(client, db)
    mock_platforms[Platform.THREADS].oauth_fail()

    response = callback(client, code="used-code", state=state)

    assert result_of(response) == "PLATFORM_AUTH_FAILED"
    assert "mock_threads" not in threads_accounts(db)
    assert [event[:4] for event in auth_events(db)] == [
        ("LINK_FAILED", "threads", None, "PLATFORM_AUTH_FAILED")
    ]


def test_callback_rejects_tampered_or_expired_state(client, db, mock_platforms):
    state = issue_state_via_api(client, db)

    tampered = callback(client, code="c", state=state[:-3] + "abc")
    missing = callback(client, code="c")
    clock.set_fixed(clock.now() + timedelta(minutes=11))
    expired = callback(client, code="c", state=state)

    assert [result_of(r) for r in (tampered, missing, expired)] == ["PLATFORM_AUTH_FAILED"] * 3
    assert mock_platforms[Platform.THREADS].exchanged == []
    assert "mock_threads" not in threads_accounts(db)


def test_callback_duplicate_name_is_reported_without_auth_event(client, db, mock_platforms):
    state = issue_state_via_api(client, db)  # seed 已有 Threads 帳號 ntu_guitar_threads
    mock_platforms[Platform.THREADS].oauth_account(
        OAuthAccount("2002", "ntu_guitar_threads", {"access_token": "t"}, None)
    )

    response = callback(client, code="c", state=state)

    assert result_of(response) == "PLATFORM_ACCOUNT_NAME_TAKEN"
    assert auth_events(db) == []
    assert len(threads_accounts(db)) == 1


def test_callback_result_page_explains_the_outcome(client):
    linked = client.get(RESULT, params={"result": "linked"})
    failed = client.get(RESULT, params={"result": "PLATFORM_AUTH_FAILED"})
    unknown = client.get(RESULT, params={"result": "<script>alert(1)</script>"})

    assert linked.status_code == 200 and "text/html" in linked.headers["content-type"]
    assert "連結成功" in linked.text
    assert "授權失敗" in failed.text
    assert "<script>" not in unknown.text


def test_linked_oauth_account_can_publish(client, db, mock_platforms):
    state = issue_state_via_api(client, db)
    callback(client, code="c", state=state)
    account_id = threads_accounts(db)["mock_threads"].id
    headers = login(client, "pr@club.tw")
    post_id = create_post_with_targets(client, headers, [account_id])

    assert publish(client, headers, post_id).status_code == 202

    assert records_by_account(client, headers, post_id)["mock_threads"]["status"] == "SUCCEEDED"
    assert [name for name, _ in mock_platforms[Platform.THREADS].received] == ["mock_threads"]


def test_threads_link_and_publish_end_to_end(client, db, monkeypatch):
    """用假的 HTTP 傳輸層走完真實的 ThreadsAdapter：授權連結 → 建立 container → 查狀態 → 發佈。"""
    import httpx

    from app.core import platforms
    from app.core.config import get_settings
    from app.m2_platforms.adapters.threads import ThreadsAdapter

    monkeypatch.setattr(get_settings(), "threads_app_id", "9990001")
    monkeypatch.setattr(get_settings(), "threads_app_secret", "app-secret-value")
    monkeypatch.setattr(get_settings(), "publish_poll_interval_seconds", 0)
    calls = []

    def fake_threads(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        calls.append(f"{request.method} {path}")
        if path == "/oauth/access_token":
            return httpx.Response(200, json={"access_token": "short", "user_id": 17841})
        if path == "/access_token":
            return httpx.Response(200, json={"access_token": "long-lived", "expires_in": 5183944})
        if path == "/v1.0/me":
            return httpx.Response(200, json={"id": "17841", "username": "ntu_guitar"})
        if path == "/v1.0/17841/threads":
            return httpx.Response(200, json={"id": "container-1"})
        if path == "/v1.0/container-1":
            return httpx.Response(200, json={"status": "FINISHED"})
        if path == "/v1.0/17841/threads_publish":
            return httpx.Response(200, json={"id": "media-9"})
        if path == "/v1.0/media-9":
            return httpx.Response(200, json={"id": "media-9", "permalink": "https://www.threads.com/@ntu_guitar/post/abc"})
        return httpx.Response(404)

    platforms.register_adapter(ThreadsAdapter(transport=httpx.MockTransport(fake_threads), retry_delay=0))
    state = issue_state_via_api(client, db)

    assert result_of(callback(client, code="the-code", state=state)) == "linked"
    account = threads_accounts(db)["ntu_guitar"]
    assert account.platform_user_id == "17841"
    headers = login(client, "pr@club.tw")
    post_id = create_post_with_targets(client, headers, [account.id], content="本週三社課")
    assert publish(client, headers, post_id).status_code == 202

    record = records_by_account(client, headers, post_id)["ntu_guitar"]
    assert (record["status"], record["platform_post_url"]) == (
        "SUCCEEDED", "https://www.threads.com/@ntu_guitar/post/abc",
    )
    assert db.scalars(
        select(models.PublishRecord.platform_request_ref).where(models.PublishRecord.post_id == post_id)
    ).one() == "container-1"
    assert calls == [
        "POST /oauth/access_token", "GET /access_token", "GET /v1.0/me",
        "POST /v1.0/17841/threads", "GET /v1.0/container-1",
        "POST /v1.0/17841/threads_publish", "GET /v1.0/media-9",
    ]


def test_callback_when_platform_is_unreachable_reports_temporary_failure(client, db, mock_platforms):
    """平台連不上或回 5xx：不是「授權失敗」，而是「暫時無法驗證」（需求 4.5.2、BR-37）。"""
    state = issue_state_via_api(client, db)
    admin_id = db.scalar(select(models.UserAccount.id).where(models.UserAccount.role == "admin"))
    mock_platforms[Platform.THREADS].oauth_unavailable()

    response = callback(client, code="some-code", state=state)

    assert result_of(response) == "VERIFICATION_UNAVAILABLE"
    assert "mock_threads" not in threads_accounts(db)
    assert auth_events(db) == [("LINK_FAILED", "threads", None, "VERIFICATION_UNAVAILABLE", admin_id)]
    assert "暫時無法驗證" in client.get(RESULT, params={"result": "VERIFICATION_UNAVAILABLE"}).text


def test_exchange_failure_reason_is_logged_without_the_code(client, db, mock_platforms, caplog):
    """換不到憑證時，平台回覆的原因要留在 Log 供排查；授權碼本身不可以出現。"""
    state = issue_state_via_api(client, db)
    mock_platforms[Platform.THREADS].oauth_fail("redirect_uri does not match (code SECRET-CODE-123)")

    with caplog.at_level("WARNING", logger="mediagent.platforms"):
        response = callback(client, code="SECRET-CODE-123", state=state)

    assert result_of(response) == "PLATFORM_AUTH_FAILED"
    assert "redirect_uri does not match" in caplog.text
    assert "SECRET-CODE-123" not in caplog.text
    assert state not in caplog.text


def test_denied_authorization_is_logged_with_the_platform_reason(client, db, mock_platforms, caplog):
    state = issue_state_via_api(client, db)

    with caplog.at_level("WARNING", logger="mediagent.platforms"):
        callback(client, state=state, error="access_denied", error_reason="user_denied")

    assert "access_denied" in caplog.text
    assert state not in caplog.text


def test_docs_prefill_a_request_body_that_works(client):
    """Swagger 的「Try it out」會預填範例內容：預填的內容必須能直接送出，不可以帶重新連結的欄位。"""
    schemas = client.get("/openapi.json").json()["components"]["schemas"]

    assert schemas["OAuthStart"]["examples"] == [{"platform": "threads"}]
