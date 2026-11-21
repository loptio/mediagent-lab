"""重試發佈：只重送失敗、且平台帳號仍可用的目標（FR-18、BR-12、BR-16、BR-32、BR-34）。"""

from datetime import timedelta

from sqlalchemy import select

from app.core import clock, models
from app.core.enums import AuditAction, AuthStatus, FailureReason, Platform, PostStatus, RecordStatus
from tests.api.helpers import (
    API,
    create_post_with_targets,
    history_rows,
    login,
    publish,
    records_by_account,
    seed_club,
)


def retry(client, headers, post_id):
    return client.post(f"{API}/posts/{post_id}/publish-jobs", json={"type": "retry"}, headers=headers)


def outcome(client, post_id):
    records = records_by_account(client, login(client, "president@club.tw"), post_id)
    return {name: (r["status"], r["failure_reason"]) for name, r in records.items()}


def post_status(client, post_id):
    return client.get(f"{API}/posts/{post_id}", headers=login(client, "pr@club.tw")).json()["status"]


def audits(db, action):
    db.expire_all()
    return list(db.scalars(select(models.AuditLog).where(models.AuditLog.action == action)))


def target_results(audit, accounts):
    names = {account.id: name for name, account in accounts.items()}
    return {
        names[r.platform_account_id]: (r.status, r.failure_reason, r.skip_reason)
        for r in audit.target_results
    }


def partially_failed_post(client, db, mock_platforms):
    """三個平台立即發佈，Instagram 失敗 → 部分失敗。"""
    users, accounts = seed_club(db)
    headers = login(client, "pr@club.tw")
    post_id = create_post_with_targets(client, headers, [a.id for a in accounts.values()])
    mock_platforms[Platform.INSTAGRAM].fail("ntu_guitar_ig", FailureReason.PLATFORM_UNAVAILABLE)
    publish(client, headers, post_id)
    assert post_status(client, post_id) == "PARTIALLY_FAILED"
    mock_platforms[Platform.INSTAGRAM].reset()
    for adapter in mock_platforms.values():
        adapter.received.clear()
    return users, accounts, headers, post_id


def failed_post(db, users, records):
    """直接建立一則全部失敗的貼文；records 為 [(平台帳號, 失敗原因)]。"""
    post = models.Post(
        content="社課公告", creator_id=users["publisher"].id, status=PostStatus.FAILED,
        publishing_started_at=clock.now() - timedelta(minutes=5),
    )
    db.add(post)
    db.flush()
    for account, reason in records:
        db.add(models.PostTarget(post_id=post.id, platform_account_id=account.id))
        db.add(models.PublishRecord(
            post_id=post.id, platform_account_id=account.id, status=RecordStatus.FAILED,
            failure_reason=reason, attempt_started_at=clock.now() - timedelta(minutes=5),
        ))
    db.commit()
    return post.id


def test_retry_republishes_only_failed_targets(client, db, mock_platforms):
    users, accounts, headers, post_id = partially_failed_post(client, db, mock_platforms)

    response = retry(client, headers, post_id)

    assert response.status_code == 202, response.text
    assert [r["platform_account_id"] for r in response.json()["records"]] == [accounts["instagram"].id]
    assert [len(mock_platforms[p].received) for p in Platform] == [0, 1, 0]  # Threads, IG, Discord
    assert post_status(client, post_id) == "PUBLISHED"
    assert outcome(client, post_id)["ntu_guitar_ig"] == ("SUCCEEDED", None)
    assert history_rows(db, post_id)[-2:] == [
        ("FAILED", "PENDING", "user", "RETRY_STARTED"),
        ("PENDING", "SUCCEEDED", "system", "RETRY_SUCCEEDED"),
    ]
    [original] = audits(db, AuditAction.POST_PUBLISH)
    assert original.result == "PARTIALLY_FAILED"
    [audit] = audits(db, AuditAction.PUBLISH_RETRY)
    assert (audit.actor_id, audit.target_id, audit.result) == (users["publisher"].id, post_id, "PUBLISHED")
    assert target_results(audit, accounts) == {
        "threads": ("NOT_RETRIED", None, "ALREADY_SUCCEEDED"),
        "instagram": ("SUCCEEDED", None, None),
        "discord": ("NOT_RETRIED", None, "ALREADY_SUCCEEDED"),
    }


def test_retry_still_failing_is_partially_failed(client, db, mock_platforms):
    _, _, headers, post_id = partially_failed_post(client, db, mock_platforms)
    mock_platforms[Platform.INSTAGRAM].fail("ntu_guitar_ig", FailureReason.PLATFORM_UNAVAILABLE)

    retry(client, headers, post_id)

    assert post_status(client, post_id) == "PARTIALLY_FAILED"
    assert outcome(client, post_id)["ntu_guitar_ig"] == ("FAILED", "PLATFORM_UNAVAILABLE")
    assert history_rows(db, post_id)[-1] == ("PENDING", "FAILED", "system", "RETRY_FAILED")


def test_retry_requires_failed_post_and_publisher(client, db):
    _, accounts = seed_club(db)
    publisher = login(client, "pr@club.tw")
    writer = login(client, "newbie@club.tw")
    draft = create_post_with_targets(client, publisher, [accounts["discord"].id])
    own = create_post_with_targets(client, writer, [accounts["discord"].id])

    not_retryable = retry(client, publisher, draft)

    assert (not_retryable.status_code, not_retryable.json()["code"]) == (409, "POST_NOT_RETRYABLE")
    assert retry(client, writer, own).status_code == 403


def test_nothing_to_retry_explains_why(client, db, mock_platforms):
    users, accounts = seed_club(db)
    expired = accounts["instagram"]
    expired.auth_expires_at = clock.now() - timedelta(hours=1)
    accounts["discord"].removed, accounts["discord"].removed_at = True, clock.now()
    post_id = failed_post(
        db, users, [(expired, "AUTH_EXPIRED"), (accounts["discord"], "PLATFORM_UNAVAILABLE")]
    )

    response = retry(client, login(client, "pr@club.tw"), post_id)

    assert (response.status_code, response.json()["code"]) == (422, "NOTHING_TO_RETRY")
    hints = {h["platform_account_id"]: h["reason"] for h in response.json()["detail"]["hints"]}
    assert hints == {expired.id: "AUTH_INVALID_SKIPPED", accounts["discord"].id: "REMOVED_SKIPPED"}
    assert post_status(client, post_id) == "FAILED"
    assert audits(db, AuditAction.PUBLISH_RETRY) == []
    assert all(adapter.received == [] for adapter in mock_platforms.values())


def test_retry_skips_auth_invalid_and_removed_targets(client, db, mock_platforms):
    users, accounts = seed_club(db)
    accounts["instagram"].auth_status = AuthStatus.INVALID
    accounts["discord"].removed, accounts["discord"].removed_at = True, clock.now()
    post_id = failed_post(db, users, [
        (accounts["threads"], "PLATFORM_UNAVAILABLE"),
        (accounts["instagram"], "AUTH_INVALID"),
        (accounts["discord"], "PLATFORM_UNAVAILABLE"),
    ])
    mock_platforms[Platform.THREADS].fail("ntu_guitar_threads", FailureReason.PLATFORM_UNAVAILABLE)

    response = retry(client, login(client, "pr@club.tw"), post_id)

    assert response.status_code == 202, response.text
    [audit] = audits(db, AuditAction.PUBLISH_RETRY)
    assert (audit.result, target_results(audit, accounts)) == ("FAILED", {
        "threads": ("FAILED", "PLATFORM_UNAVAILABLE", None),
        "instagram": ("NOT_RETRIED", None, "AUTH_INVALID_SKIPPED"),
        "discord": ("NOT_RETRIED", None, "REMOVED_SKIPPED"),
    })
    assert mock_platforms[Platform.INSTAGRAM].received == []
    assert mock_platforms[Platform.DISCORD].received == []


def test_timeout_failure_can_be_retried_right_away(client, db, mock_platforms):
    users, accounts = seed_club(db)
    post_id = failed_post(db, users, [(accounts["threads"], "TIMEOUT")])
    # 上一次嘗試 5 秒前才開始（逾時後馬上按重試），不可以被當成還有人在處理
    record = db.scalar(select(models.PublishRecord).where(models.PublishRecord.post_id == post_id))
    record.attempt_started_at = clock.now() - timedelta(seconds=5)
    db.commit()

    response = retry(client, login(client, "pr@club.tw"), post_id)

    assert response.status_code == 202, response.text
    assert len(mock_platforms[Platform.THREADS].received) == 1
    assert post_status(client, post_id) == "PUBLISHED"


def test_retry_auth_invalid_marks_account_invalid(client, db, mock_platforms):
    _, accounts, headers, post_id = partially_failed_post(client, db, mock_platforms)
    mock_platforms[Platform.INSTAGRAM].fail("ntu_guitar_ig", FailureReason.AUTH_INVALID)

    retry(client, headers, post_id)

    db.expire_all()
    assert db.get(models.PlatformAccount, accounts["instagram"].id).auth_status == AuthStatus.INVALID
    assert db.get(models.PlatformAccount, accounts["threads"].id).auth_status == AuthStatus.VALID
