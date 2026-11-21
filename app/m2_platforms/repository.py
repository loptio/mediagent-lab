from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.models import PlatformAccount


def list_active(db: Session) -> list[PlatformAccount]:
    stmt = select(PlatformAccount).where(PlatformAccount.removed.is_(False)).order_by(
        PlatformAccount.id
    )
    return list(db.scalars(stmt))
