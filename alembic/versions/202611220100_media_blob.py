"""media_blob：正式環境把圖片內容存在 PostgreSQL（MEDIA_STORAGE_BACKEND=db）。

Revision ID: 3c1f0a7e9b21
Revises: ab45c307dc33
Create Date: 2026-11-22 01:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "3c1f0a7e9b21"
down_revision: str | Sequence[str] | None = "ab45c307dc33"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "media_blob",
        sa.Column("storage_key", sa.Text(), primary_key=True),
        sa.Column("data", sa.LargeBinary(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("media_blob")
