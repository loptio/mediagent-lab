from sqlalchemy import select

from app.core import models, platforms
from app.core.config import get_settings
from app.core.db import SessionLocal
from app.core.enums import AuditAction, FailureReason, Platform
from app.core.platforms import CheckResult, CheckStatus, MockAdapter
from tests.api.helpers import (
    API,
    create_post_with_targets,
    login,
    publish,
    records_by_account,
    seed_club,
)


def publish_to_all(client, db):
    _, accounts = seed_club(db)
    headers = login(client, "pr@club.tw")
    post_id = create_post_with_targets(client, headers, [a.id for a in accounts.values()])
    assert publish(client, headers, post_id).status_code == 202
    admin = login(client, "president@club.tw")
    status = client.get(f"{API}/posts/{post_id}", headers=headers).json()["status"]
    return post_id, status, records_by_account(client, admin, post_id)


def outcome(records):
    return {name: (r["status"], r["failure_reason"]) for name, r in records.items()}


def test_one_failure_gives_partially_failed(client, db, mock_platforms):
    mock_platforms[Platform.INSTAGRAM].fail(
        "ntu_guitar_ig", FailureReason.PLATFORM_UNAVAILABLE, "503 Service Unavailable"
    )

    post_id, status, records = publish_to_all(client, db)

    assert status == "PARTIALLY_FAILED"
    assert outcome(records) == {
        "ntu_guitar_threads": ("SUCCEEDED", None),
        "ntu_guitar_ig": ("FAILED", "PLATFORM_UNAVAILABLE"),
        "公告": ("SUCCEEDED", None),
    }
    assert records["ntu_guitar_ig"]["platform_error_message"] == "503 Service Unavailable"
    audit = db.scalars(
        select(models.AuditLog).where(models.AuditLog.action == AuditAction.POST_PUBLISH)
    ).one()
    assert audit.result == "PARTIALLY_FAILED"
    assert sorted((r.status, r.failure_reason) for r in audit.target_results) == [
        ("FAILED", "PLATFORM_UNAVAILABLE"), ("SUCCEEDED", None), ("SUCCEEDED", None),
    ]


def test_all_failures_give_failed(client, db, mock_platforms):
    mock_platforms[Platform.THREADS].fail("ntu_guitar_threads", FailureReason.CONTENT_REJECTED)
    mock_platforms[Platform.INSTAGRAM].fail("ntu_guitar_ig", FailureReason.PLATFORM_UNAVAILABLE)
    mock_platforms[Platform.DISCORD].fail("公告", FailureReason.OTHER)

    _, status, records = publish_to_all(client, db)

    assert status == "FAILED"
    assert {r["status"] for r in records.values()} == {"FAILED"}


def test_hanging_adapter_times_out_without_blocking_others(
    client, db, mock_platforms, monkeypatch
):
    monkeypatch.setattr(get_settings(), "platform_call_timeout_seconds", 0.05)
    mock_platforms[Platform.INSTAGRAM].hang("ntu_guitar_ig")

    _, status, records = publish_to_all(client, db)

    assert status == "PARTIALLY_FAILED"
    assert outcome(records) == {
        "ntu_guitar_threads": ("SUCCEEDED", None),
        "ntu_guitar_ig": ("FAILED", "TIMEOUT"),
        "公告": ("SUCCEEDED", None),
    }


def test_adapter_exception_does_not_block_other_targets(client, db, mock_platforms):
    mock_platforms[Platform.THREADS].raise_error(
        "ntu_guitar_threads", RuntimeError("token=super-secret-value")
    )

    _, status, records = publish_to_all(client, db)

    assert status == "PARTIALLY_FAILED"
    assert outcome(records)["ntu_guitar_threads"] == ("FAILED", "OTHER")
    assert outcome(records)["公告"] == ("SUCCEEDED", None)
    # 例外訊息可能含憑證，不得寫進發佈紀錄
    assert "super-secret-value" not in (records["ntu_guitar_threads"]["platform_error_message"] or "")


def test_auth_invalid_marks_account_invalid(client, db, mock_platforms):
    mock_platforms[Platform.THREADS].fail("ntu_guitar_threads", FailureReason.AUTH_INVALID)

    _, _, records = publish_to_all(client, db)

    assert outcome(records)["ntu_guitar_threads"] == ("FAILED", "AUTH_INVALID")
    accounts = client.get(
        f"{API}/platform-accounts", headers=login(client, "pr@club.tw")
    ).json()["items"]
    assert {a["account_name"]: a["auth_status"] for a in accounts}["ntu_guitar_threads"] == "invalid"


def test_request_ref_is_persisted_before_finalize(client, db):
    seen = {}

    class RecordingAdapter(MockAdapter):
        async def finalize(self, credential, request_ref):
            # finalize 執行時，另一條資料庫連線必須已經看得到 request_ref
            with SessionLocal() as other:
                seen["stored"] = other.scalars(
                    select(models.PublishRecord.platform_request_ref)
                ).all()
            seen["ref"] = request_ref
            return await super().finalize(credential, request_ref)

    platforms.register_adapter(RecordingAdapter(Platform.DISCORD))
    _, accounts = seed_club(db)
    headers = login(client, "pr@club.tw")
    post_id = create_post_with_targets(client, headers, [accounts["discord"].id])

    publish(client, headers, post_id)

    assert seen["stored"] == [seen["ref"]]


def test_container_that_needs_processing_is_polled_until_ready(client, db, monkeypatch):
    monkeypatch.setattr(get_settings(), "publish_poll_interval_seconds", 0)

    class SlowAdapter(MockAdapter):
        checks = 0

        async def check(self, credential, request_ref):
            SlowAdapter.checks += 1
            ready = SlowAdapter.checks >= 3
            return CheckResult(CheckStatus.READY if ready else CheckStatus.PROCESSING)

    platforms.register_adapter(SlowAdapter(Platform.THREADS))
    _, accounts = seed_club(db)
    headers = login(client, "pr@club.tw")
    post_id = create_post_with_targets(client, headers, [accounts["threads"].id])

    publish(client, headers, post_id)

    assert SlowAdapter.checks == 3
    assert records_by_account(client, headers, post_id)["ntu_guitar_threads"]["status"] == "SUCCEEDED"


def test_container_still_processing_at_the_record_limit_times_out(client, db, monkeypatch):
    monkeypatch.setattr(get_settings(), "publish_poll_interval_seconds", 0.01)
    monkeypatch.setattr(get_settings(), "publish_record_limit_seconds", 0.05)
    mock = platforms.get_adapter(Platform.THREADS)
    mock.set_check("ntu_guitar_threads", CheckResult(CheckStatus.PROCESSING))
    _, accounts = seed_club(db)
    headers = login(client, "pr@club.tw")
    post_id = create_post_with_targets(client, headers, [accounts["threads"].id])

    publish(client, headers, post_id)

    record = records_by_account(client, headers, post_id)["ntu_guitar_threads"]
    assert (record["status"], record["failure_reason"]) == ("FAILED", "TIMEOUT")
    assert mock.received == []
    # 保留 request_ref，之後重試或恢復時可以先查平台狀態（foundation-plan D-01）
    assert db.scalars(select(models.PublishRecord.platform_request_ref)).one() is not None


def test_platform_error_message_is_visible_to_admin_only(client, db, mock_platforms):
    mock_platforms[Platform.DISCORD].fail("公告", FailureReason.OTHER, "raw platform message")
    _, accounts = seed_club(db)
    headers = login(client, "pr@club.tw")
    post_id = create_post_with_targets(client, headers, [accounts["discord"].id])
    publish(client, headers, post_id)

    as_publisher = records_by_account(client, headers, post_id)["公告"]
    as_admin = records_by_account(client, login(client, "president@club.tw"), post_id)["公告"]

    assert "platform_error_message" not in as_publisher
    assert as_admin["platform_error_message"] == "raw platform message"


# ---------- 貼文不可以卡在「發佈中」 ----------


def test_undecryptable_credential_fails_only_that_target(client, db, mock_platforms):
    _, accounts = seed_club(db)
    accounts["instagram"].credential_encrypted = b"not-a-valid-ciphertext"
    db.commit()
    headers = login(client, "pr@club.tw")
    post_id = create_post_with_targets(client, headers, [a.id for a in accounts.values()])

    assert publish(client, headers, post_id).status_code == 202

    assert client.get(f"{API}/posts/{post_id}", headers=headers).json()["status"] == "PARTIALLY_FAILED"
    assert outcome(records_by_account(client, headers, post_id)) == {
        "ntu_guitar_threads": ("SUCCEEDED", None),
        "ntu_guitar_ig": ("FAILED", "OTHER"),
        "公告": ("SUCCEEDED", None),
    }
    assert mock_platforms[Platform.INSTAGRAM].received == []


def test_adapter_returning_an_invalid_result_is_recorded_as_failed(client, db):
    class BrokenAdapter(MockAdapter):
        async def finalize(self, credential, request_ref):
            return None

    platforms.register_adapter(BrokenAdapter(Platform.DISCORD))
    _, accounts = seed_club(db)
    headers = login(client, "pr@club.tw")
    post_id = create_post_with_targets(client, headers, [accounts["discord"].id])

    publish(client, headers, post_id)

    assert client.get(f"{API}/posts/{post_id}", headers=headers).json()["status"] == "FAILED"
    assert outcome(records_by_account(client, headers, post_id))["公告"] == ("FAILED", "OTHER")


def test_result_that_cannot_be_stored_still_ends_the_publish(client, db):
    from app.core.platforms import Failed

    class OddAdapter(MockAdapter):
        async def finalize(self, credential, request_ref):
            return Failed("NOT_A_KNOWN_REASON")  # 違反資料庫的 CHECK，寫回會失敗

    platforms.register_adapter(OddAdapter(Platform.DISCORD))
    _, accounts = seed_club(db)
    headers = login(client, "pr@club.tw")
    post_id = create_post_with_targets(
        client, headers, [accounts["discord"].id, accounts["threads"].id]
    )

    publish(client, headers, post_id)

    assert client.get(f"{API}/posts/{post_id}", headers=headers).json()["status"] == "PARTIALLY_FAILED"
    assert outcome(records_by_account(client, headers, post_id)) == {
        "ntu_guitar_threads": ("SUCCEEDED", None),
        "公告": ("FAILED", "OTHER"),
    }


def test_finalize_reported_as_timeout_is_checked_once(client, db, monkeypatch):
    """發文動作沒有回應，但平台其實發出去了：再查一次狀態，確認已發出就記為成功。"""
    from app.core.platforms import Failed, Published

    monkeypatch.setattr(get_settings(), "publish_poll_interval_seconds", 0)

    class SilentAdapter(MockAdapter):
        checks = 0
        finalized = False

        async def check(self, credential, request_ref):
            SilentAdapter.checks += 1
            if SilentAdapter.finalized:
                return CheckResult(
                    CheckStatus.PUBLISHED, published=Published(post_url="https://threads.test/p/9")
                )
            return CheckResult(CheckStatus.READY)

        async def finalize(self, credential, request_ref):
            SilentAdapter.finalized = True
            return Failed(FailureReason.TIMEOUT, "ReadTimeout")

    platforms.register_adapter(SilentAdapter(Platform.THREADS))
    _, accounts = seed_club(db)
    headers = login(client, "pr@club.tw")
    post_id = create_post_with_targets(client, headers, [accounts["threads"].id])

    publish(client, headers, post_id)

    record = records_by_account(client, headers, post_id)["ntu_guitar_threads"]
    assert (record["status"], record["platform_post_url"]) == ("SUCCEEDED", "https://threads.test/p/9")
    assert SilentAdapter.checks == 2
