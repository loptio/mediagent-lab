from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.models import UserAccount


def get_by_email(db: Session, email: str) -> UserAccount | None:
    return db.scalar(select(UserAccount).where(UserAccount.email == email))
