"""登入安全事件、平台授權事件的索引：稽核查詢依時間排序、依帳號篩選。

Revision ID: 8d2b6c4e1f90
Revises: 3c1f0a7e9b21
Create Date: 2026-11-22 03:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "8d2b6c4e1f90"
down_revision: str | Sequence[str] | None = "3c1f0a7e9b21"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(
        "ix_login_security_event_occurred",
        "login_security_event",
        [sa.text("occurred_at DESC"), sa.text("event_seq DESC")],
    )
    op.create_index("ix_login_security_event_account", "login_security_event", ["user_account_id"])
    op.create_index(
        "ix_platform_auth_event_occurred",
        "platform_auth_event",
        [sa.text("occurred_at DESC"), sa.text("event_seq DESC")],
    )
    op.create_index("ix_platform_auth_event_actor", "platform_auth_event", ["actor_id"])


def downgrade() -> None:
    op.drop_index("ix_platform_auth_event_actor", "platform_auth_event")
    op.drop_index("ix_platform_auth_event_occurred", "platform_auth_event")
    op.drop_index("ix_login_security_event_account", "login_security_event")
    op.drop_index("ix_login_security_event_occurred", "login_security_event")
