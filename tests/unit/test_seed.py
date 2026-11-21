from sqlalchemy import select

from app.core import auth, models
from seeds import seed_dev


def test_seed_creates_one_user_per_role_and_is_idempotent(db):
    seed_dev.run()
    seed_dev.run()

    users = db.scalars(select(models.UserAccount).order_by(models.UserAccount.id)).all()
    assert [(u.email, u.role, u.status) for u in users] == [
        ("admin@club.test", "admin", "active"),
        ("publisher@club.test", "publisher", "active"),
        ("writer@club.test", "writer", "active"),
    ]
    assert all(auth.verify_password(seed_dev.DEV_PASSWORD, u.password_hash) for u in users)
