import pytest
from sqlalchemy import inspect, text
from sqlalchemy.exc import DBAPIError, IntegrityError

from app.core import models
from app.core.db import engine
from app.core.enums import ActorType, AuditAction, Platform, Role, TargetType

TABLES = {
    "user_account", "user_session", "login_security_event", "platform_account",
    "platform_auth_event", "media_file", "post", "post_image", "post_target",
    "publish_record", "publish_record_history", "audit_log", "audit_target_result",
}


def make_user(db, email="pr@club.tw", role=Role.PUBLISHER):
    user = models.UserAccount(email=email, name="公關", password_hash="x", role=role)
    db.add(user)
    db.flush()
    return user


def make_audit(db):
    row = models.AuditLog(
        actor_type=ActorType.SYSTEM, action=AuditAction.POST_PUBLISH,
        target_type=TargetType.POST, target_id=1,
    )
    db.add(row)
    db.flush()
    return row


def test_all_thirteen_tables_exist():
    assert TABLES <= set(inspect(engine).get_table_names())


def test_audit_log_rejects_update_and_delete(db):
    row = make_audit(db)
    db.commit()

    with pytest.raises(DBAPIError, match="append-only"):
        db.execute(text("UPDATE audit_log SET reason = 'x' WHERE id = :id"), {"id": row.id})
    db.rollback()
    with pytest.raises(DBAPIError, match="append-only"):
        db.execute(text("DELETE FROM audit_log WHERE id = :id"), {"id": row.id})
    db.rollback()
    with pytest.raises(DBAPIError, match="append-only"):
        db.execute(text("TRUNCATE audit_log CASCADE"))


def test_post_content_must_not_be_blank(db):
    user = make_user(db)
    db.add(models.Post(content="   ", creator_id=user.id))

    with pytest.raises(IntegrityError):
        db.flush()


def test_publish_record_unique_per_post_and_account(db):
    user = make_user(db)
    post = models.Post(content="社課公告", creator_id=user.id)
    account = models.PlatformAccount(
        platform=Platform.DISCORD, account_name="公告", credential_encrypted=b"x",
        credential_key_version=1, linked_by=user.id,
    )
    db.add_all([post, account])
    db.flush()
    db.add(models.PublishRecord(post_id=post.id, platform_account_id=account.id))
    db.flush()
    db.add(models.PublishRecord(post_id=post.id, platform_account_id=account.id))

    with pytest.raises(IntegrityError):
        db.flush()


def test_event_seq_is_shared_across_event_tables(db):
    audit = make_audit(db)
    event = models.LoginSecurityEvent(
        failure_reason="ACCOUNT_NOT_FOUND", attempted_email="nobody@club.tw",
    )
    db.add(event)
    db.flush()
    db.refresh(audit)
    db.refresh(event)

    assert event.event_seq == audit.event_seq + 1


def test_database_errors_do_not_include_query_parameters():
    """資料庫錯誤會被寫進 Log；參數（例如密碼雜湊、憑證）不可以出現在錯誤訊息中。"""
    from sqlalchemy.exc import DBAPIError

    from app.core.db import engine

    with pytest.raises(DBAPIError) as error, engine.connect() as conn:
        conn.execute(text("SELECT CAST(:secret AS text), 1 / 0"), {"secret": "s3cret-hash-value"})

    assert "s3cret-hash-value" not in str(error.value)
