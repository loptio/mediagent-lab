import json

import httpx
import pytest
from sqlalchemy import select

from app.core import crypto, models, platforms
from app.core.enums import AuditAction
from app.m2_platforms.adapters.discord import DiscordAdapter
from tests.api.helpers import API, create_post_with_targets, login, publish, records_by_account, seed_club

TOKEN = "s3cr3t-Token_value"
WEBHOOK = f"https://discord.com/api/webhooks/123456/{TOKEN}"
WEBHOOK_INFO = {"id": "123456", "guild_id": "111", "channel_id": "222", "name": "Captain Hook"}


@pytest.fixture
def discord(db):
    """註冊使用假 HTTP 傳輸層的 DiscordAdapter；測試可替換 handler，並檢查送出了哪些請求。"""

    class FakeDiscord:
        def __init__(self):
            self.requests: list[httpx.Request] = []
            self.handler = self.default

        def default(self, request: httpx.Request) -> httpx.Response:
            if request.method == "GET":
                return httpx.Response(200, json=WEBHOOK_INFO)
            return httpx.Response(200, json={"id": "555", "channel_id": "222"})

        def __call__(self, request: httpx.Request) -> httpx.Response:
            self.requests.append(request)
            return self.handler(request)

    fake = FakeDiscord()
    platforms.register_adapter(DiscordAdapter(transport=httpx.MockTransport(fake)))
    seed_club(db)
    return fake


def link(client, headers, webhook_url=WEBHOOK, account_name="社團公告", platform="discord"):
    return client.post(
        f"{API}/platform-accounts",
        json={"platform": platform, "account_name": account_name, "webhook_url": webhook_url},
        headers=headers,
    )


def auth_events(db):
    rows = db.scalars(select(models.PlatformAuthEvent).order_by(models.PlatformAuthEvent.id))
    return [(e.event_type, e.platform, e.account_name, e.failure_reason) for e in rows]


def test_link_stores_encrypted_credential_and_hides_it(client, db, discord):
    admin = login(client, "president@club.tw")

    response = link(client, admin)

    assert response.status_code == 201
    body = response.json()
    assert body == {
        "id": body["id"], "platform": "discord", "account_name": "社團公告",
        "auth_status": "valid", "auth_expires_at": None,
    }
    listing = client.get(f"{API}/platform-accounts", headers=admin).text
    assert TOKEN not in response.text and TOKEN not in listing

    account = db.get(models.PlatformAccount, body["id"])
    assert TOKEN.encode() not in bytes(account.credential_encrypted)
    credential = crypto.decrypt_credential(account.credential_encrypted)
    assert (credential["webhook_url"], credential["guild_id"], credential["channel_id"]) == (
        WEBHOOK, "111", "222",
    )
    audit = db.scalars(
        select(models.AuditLog).where(models.AuditLog.action == AuditAction.PLATFORM_LINK)
    ).one()
    assert (audit.target_type, audit.target_id) == ("platform_account", body["id"])


@pytest.mark.parametrize(
    "bad_url",
    [
        "http://discord.com/api/webhooks/123456/token",
        "https://discord.com.evil.example/api/webhooks/123456/token",
        "https://evil.example/api/webhooks/123456/token",
        "https://discord.com/api/webhooks/123456/token/../../users/@me",
        "https://discord.com/api/webhooks/abc/token",
        "https://user@discord.com/api/webhooks/123456/token",
        "not a url",
    ],
)
def test_link_rejects_non_discord_url_without_request(client, db, discord, bad_url):
    response = link(client, login(client, "president@club.tw"), webhook_url=bad_url)

    assert (response.status_code, response.json()["code"]) == (422, "WEBHOOK_INVALID")
    assert discord.requests == []
    assert auth_events(db) == [("LINK_FAILED", "discord", "社團公告", "WEBHOOK_INVALID")]
    assert db.scalars(select(models.PlatformAccount.account_name)).all().count("社團公告") == 0


def test_link_invalid_webhook_records_auth_event(client, db, discord):
    discord.handler = lambda request: httpx.Response(404, json={"message": "Unknown Webhook"})

    response = link(client, login(client, "president@club.tw"))

    assert (response.status_code, response.json()["code"]) == (422, "WEBHOOK_INVALID")
    assert TOKEN not in response.text
    assert auth_events(db) == [("LINK_FAILED", "discord", "社團公告", "WEBHOOK_INVALID")]
    assert len(db.scalars(select(models.PlatformAccount)).all()) == 3  # 只有 seed 的三個


def test_link_when_discord_is_down_is_verification_unavailable(client, db, discord):
    discord.handler = lambda request: httpx.Response(503)

    response = link(client, login(client, "president@club.tw"))

    assert (response.status_code, response.json()["code"]) == (503, "VERIFICATION_UNAVAILABLE")
    assert auth_events(db) == [("LINK_FAILED", "discord", "社團公告", "VERIFICATION_UNAVAILABLE")]


def test_link_requires_admin(client, db, discord):
    response = link(client, login(client, "pr@club.tw"))

    assert (response.status_code, response.json()["code"]) == (403, "FORBIDDEN")
    assert discord.requests == []


def test_link_rejects_duplicate_name_without_auth_event(client, db, discord):
    # seed 已有名為「公告」的 Discord 帳號
    response = link(client, login(client, "president@club.tw"), account_name="公告")

    assert (response.status_code, response.json()["code"]) == (409, "PLATFORM_ACCOUNT_NAME_TAKEN")
    assert discord.requests == []
    assert auth_events(db) == []


def test_link_oauth_platform_is_rejected(client, db, discord):
    response = link(client, login(client, "president@club.tw"), platform="threads")

    assert (response.status_code, response.json()["code"]) == (400, "PLATFORM_REQUIRES_OAUTH")


def test_linked_discord_account_can_publish(client, db, discord):
    account_id = link(client, login(client, "president@club.tw")).json()["id"]
    headers = login(client, "pr@club.tw")
    post_id = create_post_with_targets(client, headers, [account_id], content="本週三社課")

    assert publish(client, headers, post_id).status_code == 202

    record = records_by_account(client, headers, post_id)["社團公告"]
    assert record["status"] == "SUCCEEDED"
    assert record["platform_post_url"] == "https://discord.com/channels/111/222/555"
    sent = [r for r in discord.requests if r.method == "POST"]
    assert [json.loads(request.content)["content"] for request in sent] == ["本週三社課"]


def test_webhook_token_is_never_logged(client, db, discord, caplog):
    caplog.set_level("DEBUG")
    account_id = link(client, login(client, "president@club.tw")).json()["id"]
    headers = login(client, "pr@club.tw")
    post_id = create_post_with_targets(client, headers, [account_id])

    publish(client, headers, post_id)

    assert len([r for r in discord.requests if r.method == "POST"]) == 1
    assert TOKEN not in caplog.text


def test_link_rejects_bad_url_whichever_adapter_is_registered(client, db):
    # 沒有使用 discord fixture：此時註冊的是 MockAdapter（離線模式），網址檢查仍然必須生效
    seed_club(db)

    response = link(
        client, login(client, "president@club.tw"), webhook_url="http://169.254.169.254/latest"
    )

    assert (response.status_code, response.json()["code"]) == (422, "WEBHOOK_INVALID")
    assert "社團公告" not in db.scalars(select(models.PlatformAccount.account_name)).all()
