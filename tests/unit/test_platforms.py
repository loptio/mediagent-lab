import asyncio
from datetime import timedelta

import pytest

from app.core import clock, platforms
from app.core.enums import AuthStatus, FailureReason, Platform
from app.core.errors import DomainError
from app.core.platforms import CheckStatus, Failed, MockAdapter, PostContent, Published, Started
from app.core.publish_rules import check as check_publish_rules
from tests.factories import make_account, make_post, make_user


def test_expired_account_is_effectively_invalid(db):
    user = make_user(db)
    now = clock.now()
    fresh = make_account(db, user, Platform.THREADS, "t1", auth_expires_at=now + timedelta(days=1))
    expired = make_account(db, user, Platform.THREADS, "t2", auth_expires_at=now)
    no_expiry = make_account(db, user, Platform.DISCORD, "d1")
    revoked = make_account(db, user, Platform.DISCORD, "d2", auth_status=AuthStatus.INVALID)

    accounts = (fresh, expired, no_expiry, revoked)
    statuses = [platforms.effective_auth_status(account, now) for account in accounts]

    assert statuses == [AuthStatus.VALID, AuthStatus.INVALID, AuthStatus.VALID, AuthStatus.INVALID]


def test_mock_adapter_two_step_success_records_post():
    mock = MockAdapter(Platform.THREADS)
    mock.succeed("ntu_guitar_threads", "https://threads.test/p/1")
    credential = {"account_name": "ntu_guitar_threads"}

    async def publish():
        started = await mock.begin(credential, PostContent(text="社課公告"))
        check = await mock.check(credential, started.request_ref)
        return started, check, await mock.finalize(credential, started.request_ref)

    started, check, result = asyncio.run(publish())

    assert isinstance(started, Started)
    assert check.status == CheckStatus.READY
    assert result == Published(post_id=started.request_ref, post_url="https://threads.test/p/1")
    assert [(name, content.text) for name, content in mock.received] == [
        ("ntu_guitar_threads", "社課公告")
    ]


def test_mock_adapter_failure_is_reported_by_finalize_and_nothing_is_received():
    mock = MockAdapter(Platform.INSTAGRAM)
    mock.fail("ntu_guitar_ig", FailureReason.PLATFORM_UNAVAILABLE)
    credential = {"account_name": "ntu_guitar_ig"}

    async def publish():
        started = await mock.begin(credential, PostContent(text="x"))
        return await mock.finalize(credential, started.request_ref)

    assert asyncio.run(publish()) == Failed(FailureReason.PLATFORM_UNAVAILABLE)
    assert mock.received == []


def test_registered_capabilities_follow_requirements_4_7():
    limits = {p: platforms.get_adapter(p).capabilities.max_text_length for p in Platform}

    assert limits == {Platform.THREADS: 500, Platform.INSTAGRAM: 2200, Platform.DISCORD: 2000}
    assert platforms.get_adapter(Platform.INSTAGRAM).capabilities.requires_image is True


def test_publish_rules_require_a_target(db):
    post = make_post(db, make_user(db))

    with pytest.raises(DomainError) as error:
        check_publish_rules(post, [], clock.now())
    assert (error.value.status_code, error.value.code) == (422, "NO_TARGET")


def test_publish_rules_reject_text_over_the_strictest_limit(db):
    user = make_user(db)
    post = make_post(db, user, content="字" * 501)
    accounts = [make_account(db, user, Platform.DISCORD, "公告"),
                make_account(db, user, Platform.THREADS, "ntu_guitar_threads")]

    with pytest.raises(DomainError) as error:
        check_publish_rules(post, accounts, clock.now())
    assert error.value.code == "CONTENT_TOO_LONG"
    assert error.value.detail == {"platform": "threads", "limit": 500, "length": 501}


def test_publish_rules_reject_invalid_authorization(db):
    user = make_user(db)
    post = make_post(db, user)
    account = make_account(db, user, Platform.THREADS, "t", auth_expires_at=clock.now())

    with pytest.raises(DomainError) as error:
        check_publish_rules(post, [account], clock.now())
    assert (error.value.status_code, error.value.code) == (422, "TARGET_AUTH_INVALID")


def test_mock_fail_once_prefix_fails_first_attempt_then_succeeds():
    # E2E 例外情境用：這個字首的帳號第一次回報平台暫時無法連線，重試才成功；其他帳號不受影響
    mock = MockAdapter(Platform.INSTAGRAM)
    failing = {"account_name": f"{platforms.MOCK_FAIL_ONCE_PREFIX}ig"}
    normal = {"account_name": "guitar_club"}

    async def attempts():
        first = await mock.begin(failing, PostContent(text="社課公告"))
        second = await mock.begin(failing, PostContent(text="社課公告"))
        other = await mock.begin(normal, PostContent(text="社課公告"))
        return first, second, other

    first, second, other = asyncio.run(attempts())

    assert isinstance(first, Failed)
    assert first.reason == FailureReason.PLATFORM_UNAVAILABLE
    assert isinstance(second, Started)
    assert isinstance(other, Started)


def test_real_mode_registers_a_real_adapter_for_every_platform(monkeypatch):
    """正式模式下三個平台都有真實的 Adapter；Instagram 可以走授權流程連結。"""
    from app import main
    from app.core.config import get_settings
    from app.m2_platforms.adapters.discord import DiscordAdapter
    from app.m2_platforms.adapters.instagram import InstagramAdapter
    from app.m2_platforms.adapters.threads import ThreadsAdapter

    saved = dict(platforms._registry)
    monkeypatch.setattr(get_settings(), "platform_mode", "real")
    try:
        main._register_adapters()
        registered = {platform: type(platforms.get_adapter(platform)) for platform in Platform}
    finally:
        platforms._registry.clear()
        platforms._registry.update(saved)

    assert registered == {
        Platform.DISCORD: DiscordAdapter,
        Platform.THREADS: ThreadsAdapter,
        Platform.INSTAGRAM: InstagramAdapter,
    }
