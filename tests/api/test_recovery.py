"""發佈逾時恢復：服務中斷留下的「發佈中」貼文（FR-28、BR-33、foundation-plan D-03）。"""

import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.core import clock, models
from app.core.config import get_settings
from app.core.enums import AuditAction, FailureReason, Platform, PostStatus, RecordStatus
from app.core.platforms import CheckResult, CheckStatus, Failed, Published
from app.m5_publishing import recovery
from tests.api.helpers import API, seed_club

STARTED = datetime(2026, 10, 6, 4, 0, tzinfo=UTC)  # 台灣 12:00 進入發佈中
THREADS = "ntu_guitar_threads"


@pytest.fixture(autouse=True)
def cron_secret(monkeypatch):
    monkeypatch.setattr(get_settings(), "cron_secret", "test-cron-secret")


@pytest.fixture
def stale(db):
    """貼文 12:00 進入發佈中：Threads 仍是待發佈，Discord 已成功。回傳 (users, accounts, post_id)。"""
    users, accounts = seed_club(db)
    post = models.Post(
        content="社課公告", creator_id=users["publisher"].id,
        status=PostStatus.PUBLISHING, publishing_started_at=STARTED,
    )
    db.add(post)
    db.flush()
    for key in ("threads", "discord"):
        db.add(models.PostTarget(post_id=post.id, platform_account_id=accounts[key].id))
    db.add(models.PublishRecord(
        post_id=post.id, platform_account_id=accounts["threads"].id,
        status=RecordStatus.PENDING, attempt_started_at=STARTED,
    ))
    db.add(models.PublishRecord(
        post_id=post.id, platform_account_id=accounts["discord"].id, status=RecordStatus.SUCCEEDED,
        published_at=STARTED, platform_post_url="https://discord.test/m/1", attempt_started_at=STARTED,
    ))
    db.commit()
    clock.set_fixed(STARTED + timedelta(minutes=11))
    return users, accounts, post.id


def recover(allow_auto_retry=True):
    return asyncio.run(recovery.recover_stale(allow_auto_retry))


def state(db, post_id):
    """(貼文狀態, Threads 紀錄)"""
    db.expire_all()
    post = db.get(models.Post, post_id)
    record = db.scalar(
        select(models.PublishRecord)
        .join(models.PlatformAccount)
        .where(models.PublishRecord.post_id == post_id, models.PlatformAccount.account_name == THREADS)
    )
    return post.status, record


def threads_history(db, record):
    rows = db.scalars(
        select(models.PublishRecordHistory)
        .where(models.PublishRecordHistory.publish_record_id == record.id)
        .order_by(models.PublishRecordHistory.id)
    )
    return [(h.from_status, h.to_status, h.actor_type, h.reason) for h in rows]


def audits(db):
    db.expire_all()
    return list(db.scalars(select(models.AuditLog).order_by(models.AuditLog.id)))


def test_post_publishing_under_ten_minutes_is_left_alone(db, stale, mock_platforms):
    _, _, post_id = stale
    mock_platforms[Platform.THREADS].set_check(THREADS, CheckResult(CheckStatus.UNKNOWN))

    clock.set_fixed(STARTED + timedelta(minutes=9, seconds=59))
    early = recover()
    status, record = state(db, post_id)
    assert (early.checked, status, record.status) == (0, "PUBLISHING", "PENDING")

    clock.set_fixed(STARTED + timedelta(minutes=10))
    on_time = recover()
    assert (on_time.checked, on_time.recovered) == (1, 1)
    assert state(db, post_id)[0] == "PARTIALLY_FAILED"


def test_confirmed_published_is_recorded_without_resending(db, stale, mock_platforms):
    _, _, post_id = stale
    published = CheckResult(CheckStatus.PUBLISHED, published=Published(post_url="https://threads.test/p/1"))
    mock_platforms[Platform.THREADS].set_check(THREADS, published)

    recover()

    status, record = state(db, post_id)
    assert (status, record.status, record.platform_post_url) == (
        "PUBLISHED", "SUCCEEDED", "https://threads.test/p/1"
    )
    assert mock_platforms[Platform.THREADS].received == []
    assert threads_history(db, record) == [
        ("PENDING", "SUCCEEDED", "system", "RECOVERY_CONFIRMED_PUBLISHED")
    ]


def test_unconfirmed_is_timeout_without_resending(db, stale, mock_platforms):
    users, accounts, post_id = stale
    mock_platforms[Platform.THREADS].set_check(THREADS, CheckResult(CheckStatus.UNKNOWN))

    recover()

    status, record = state(db, post_id)
    assert (status, record.status, record.failure_reason) == ("PARTIALLY_FAILED", "FAILED", "TIMEOUT")
    assert mock_platforms[Platform.THREADS].received == []
    assert threads_history(db, record) == [("PENDING", "FAILED", "system", "RECOVERY_UNCONFIRMED")]
    [audit] = audits(db)
    assert (audit.action, audit.actor_type, audit.result) == ("POST_PUBLISH", "system", "PARTIALLY_FAILED")
    assert audit.post_creator_id == users["publisher"].id
    assert sorted((r.platform_account_id, r.status) for r in audit.target_results) == sorted([
        (accounts["threads"].id, "FAILED"), (accounts["discord"].id, "SUCCEEDED"),
    ])


def test_confirmed_not_published_is_retried_once(db, stale, mock_platforms):
    _, accounts, post_id = stale  # check 預設回 READY：平台確認還沒發出

    recover()

    status, record = state(db, post_id)
    assert (status, record.status, record.auto_retry_count) == ("PUBLISHED", "SUCCEEDED", 1)
    assert len(mock_platforms[Platform.THREADS].received) == 1
    assert threads_history(db, record) == [("PENDING", "SUCCEEDED", "system", "AUTO_RETRY_SUCCEEDED")]
    [audit] = audits(db)
    assert (audit.action, audit.actor_type, audit.result, audit.reason) == (
        AuditAction.PUBLISH_AUTO_RETRY, "system", "PUBLISHED", "PLATFORM_CONFIRMED_NOT_PUBLISHED"
    )
    assert [(r.platform_account_id, r.status) for r in audit.target_results] == [
        (accounts["threads"].id, "SUCCEEDED")
    ]


def test_auto_retry_failure_is_recorded_as_reported(db, stale, mock_platforms):
    _, _, post_id = stale
    mock_platforms[Platform.THREADS].fail(THREADS, FailureReason.PLATFORM_UNAVAILABLE)

    recover()

    status, record = state(db, post_id)
    assert (status, record.status, record.failure_reason) == (
        "PARTIALLY_FAILED", "FAILED", "PLATFORM_UNAVAILABLE"
    )
    assert threads_history(db, record) == [("PENDING", "FAILED", "system", "AUTO_RETRY_FAILED")]


def test_record_already_auto_retried_is_not_sent_again(db, stale, mock_platforms):
    _, _, post_id = stale
    _, record = state(db, post_id)
    record.auto_retry_count = 1
    db.commit()

    recover()

    status, record = state(db, post_id)
    assert (record.status, record.failure_reason) == ("FAILED", "TIMEOUT")
    assert mock_platforms[Platform.THREADS].received == []
    assert threads_history(db, record) == [
        ("PENDING", "FAILED", "system", "RECOVERY_CONFIRMED_NOT_PUBLISHED")
    ]


def test_container_failure_is_recorded_with_platform_reason(db, stale, mock_platforms):
    _, _, post_id = stale
    failed = CheckResult(CheckStatus.FAILED, failed=Failed(FailureReason.CONTENT_REJECTED, "container error"))
    mock_platforms[Platform.THREADS].set_check(THREADS, failed)

    recover()

    _, record = state(db, post_id)
    assert (record.status, record.failure_reason) == ("FAILED", "CONTENT_REJECTED")
    assert mock_platforms[Platform.THREADS].received == []


def test_startup_recovery_never_resends(db, stale, mock_platforms):
    _, _, post_id = stale  # check 回 READY，但服務啟動時的檢查不重新發佈

    recover(allow_auto_retry=False)

    status, record = state(db, post_id)
    assert (status, record.status, record.failure_reason) == ("PARTIALLY_FAILED", "FAILED", "TIMEOUT")
    assert mock_platforms[Platform.THREADS].received == []
    assert record.auto_retry_count == 0


def test_record_in_progress_is_not_taken_over(db, stale, mock_platforms):
    _, _, post_id = stale
    _, record = state(db, post_id)
    record.attempt_started_at = clock.now() - timedelta(seconds=30)  # 另一個執行者 30 秒前開始處理
    db.commit()
    published = CheckResult(CheckStatus.PUBLISHED, published=Published(post_url="https://threads.test/p/1"))
    mock_platforms[Platform.THREADS].set_check(THREADS, published)

    result = recover()

    status, record = state(db, post_id)
    assert (result.checked, status, record.status) == (0, "PUBLISHING", "PENDING")
    assert audits(db) == []


def test_orphan_publishing_post_is_concluded(db, stale):
    _, _, post_id = stale
    _, record = state(db, post_id)
    record.status, record.failure_reason = RecordStatus.FAILED, FailureReason.PLATFORM_UNAVAILABLE
    db.commit()

    result = recover()

    assert (result.checked, result.recovered) == (1, 1)
    assert state(db, post_id)[0] == "PARTIALLY_FAILED"
    [audit] = audits(db)
    assert (audit.action, audit.actor_type) == ("POST_PUBLISH", "system")


def test_recovery_endpoint_requires_secret_and_reports_counts(client, db, stale, mock_platforms):
    _, _, post_id = stale
    mock_platforms[Platform.THREADS].set_check(THREADS, CheckResult(CheckStatus.UNKNOWN))

    denied = client.post(f"{API}/internal/publish-recovery")
    response = client.post(f"{API}/internal/publish-recovery", headers={"X-Cron-Secret": "test-cron-secret"})

    assert (denied.status_code, denied.json()["code"]) == (401, "UNAUTHENTICATED")
    assert response.status_code == 200, response.text
    assert response.json() == {"checked": 1, "recovered": 1}
    assert state(db, post_id)[0] == "PARTIALLY_FAILED"
