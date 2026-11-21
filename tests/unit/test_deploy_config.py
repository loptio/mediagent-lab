"""部署相關的設定：Neon 給的連線字串、正式環境建立第一位管理員。"""

import pytest
from sqlalchemy import select

from app.core import auth, models
from app.core.config import Settings
from app.core.enums import AuditAction


@pytest.mark.parametrize(
    "given",
    [
        "postgresql://user:pw@ep-cool.ap-southeast-1.aws.neon.tech/neondb?sslmode=require",
        "postgres://user:pw@ep-cool.ap-southeast-1.aws.neon.tech/neondb?sslmode=require",
        "postgresql+psycopg://user:pw@ep-cool.ap-southeast-1.aws.neon.tech/neondb?sslmode=require",
    ],
)
def test_neon_connection_string_works_as_is(given):
    settings = Settings(database_url=given, jwt_secret="x" * 40)

    assert settings.database_url == (
        "postgresql+psycopg://user:pw@ep-cool.ap-southeast-1.aws.neon.tech/neondb?sslmode=require"
    )


def test_create_admin_for_a_new_deployment(db):
    from seeds.create_admin import create_admin

    user = create_admin("  Owner@Club.TW ", "社長", "a-long-password")

    db.expire_all()
    stored = db.scalar(select(models.UserAccount).where(models.UserAccount.email == "owner@club.tw"))
    assert (stored.id, stored.role, stored.status, stored.name) == (user, "admin", "active", "社長")
    assert auth.verify_password("a-long-password", stored.password_hash)
    [audit] = db.scalars(select(models.AuditLog).where(models.AuditLog.action == AuditAction.USER_CREATE))
    assert (audit.actor_type, audit.target_id) == ("system", stored.id)


@pytest.mark.parametrize(
    ("email", "password", "message"),
    [("owner@club.tw", "short", "8"), ("not-an-email", "a-long-password", "Email")],
)
def test_create_admin_validates_input(db, email, password, message):
    from seeds.create_admin import create_admin

    with pytest.raises(ValueError, match=message):
        create_admin(email, "社長", password)


def test_create_admin_refuses_an_existing_email(db):
    from seeds.create_admin import create_admin

    create_admin("owner@club.tw", "社長", "a-long-password")

    with pytest.raises(ValueError, match="已經存在"):
        create_admin("OWNER@club.tw", "另一位", "a-long-password")
