from sqlalchemy import select

from app.core import clock, models, publish_records
from app.core.enums import ActorType, FailureReason, HistoryReason, RecordStatus
from app.core.platforms import Failed, Published
from tests.factories import make_account, make_post, make_user


def history_of(db, record):
    rows = db.scalars(
        select(models.PublishRecordHistory)
        .where(models.PublishRecordHistory.publish_record_id == record.id)
        .order_by(models.PublishRecordHistory.id)
    )
    return [(h.from_status, h.to_status, h.actor_type, h.reason) for h in rows]


def setup_record(db):
    user = make_user(db)
    post = make_post(db, user)
    account = make_account(db, user)
    record = publish_records.ensure_pending(
        db, post_id=post.id, platform_account_id=account.id, actor=user,
        reason=HistoryReason.PUBLISH_NOW,
    )
    return user, record


def test_ensure_pending_writes_history_with_null_from_status(db):
    user, record = setup_record(db)

    assert record.status == RecordStatus.PENDING
    assert history_of(db, record) == [
        (None, RecordStatus.PENDING, ActorType.USER, HistoryReason.PUBLISH_NOW)
    ]


def test_ensure_pending_reuses_cancelled_record(db):
    user, record = setup_record(db)
    publish_records.cancel(db, record, actor=user, reason=HistoryReason.SCHEDULE_CANCELLED)

    again = publish_records.ensure_pending(
        db, post_id=record.post_id, platform_account_id=record.platform_account_id,
        actor=user, reason=HistoryReason.RESCHEDULED,
    )

    assert again.id == record.id
    assert again.status == RecordStatus.PENDING
    assert [h[:2] for h in history_of(db, record)] == [
        (None, "PENDING"), ("PENDING", "CANCELLED"), ("CANCELLED", "PENDING")
    ]


def test_set_result_success_sets_published_at_and_history(db):
    _, record = setup_record(db)
    now = clock.now()

    changed = publish_records.set_result(
        db, record.id, Published(post_id="m1", post_url="https://discord.test/m/1"),
        reason=HistoryReason.PUBLISH_SUCCEEDED,
    )
    db.refresh(record)

    assert changed is True
    assert record.status == RecordStatus.SUCCEEDED
    assert record.platform_post_url == "https://discord.test/m/1"
    assert record.published_at >= now
    assert history_of(db, record)[-1] == (
        "PENDING", "SUCCEEDED", ActorType.SYSTEM, HistoryReason.PUBLISH_SUCCEEDED
    )


def test_set_result_failure_records_reason(db):
    _, record = setup_record(db)

    publish_records.set_result(
        db, record.id, Failed(FailureReason.PLATFORM_UNAVAILABLE, "503 from platform"),
        reason=HistoryReason.PUBLISH_FAILED,
    )
    db.refresh(record)

    assert (record.status, record.failure_reason) == ("FAILED", "PLATFORM_UNAVAILABLE")
    assert record.platform_error_message == "503 from platform"
    assert record.published_at is None


def test_set_result_ignores_non_pending_record(db):
    user, record = setup_record(db)
    publish_records.cancel(db, record, actor=user, reason=HistoryReason.SCHEDULE_CANCELLED)
    before = history_of(db, record)

    changed = publish_records.set_result(
        db, record.id, Published(post_url="https://discord.test/m/1"),
        reason=HistoryReason.PUBLISH_SUCCEEDED,
    )
    db.refresh(record)

    assert changed is False
    assert record.status == RecordStatus.CANCELLED
    assert record.platform_post_url is None
    assert history_of(db, record) == before
