"""開發用種子資料：三種角色各一位使用者。可重複執行，已存在的帳號不會被改動。

    python -m seeds.seed_dev

只限本機開發使用；正式環境的管理員帳號另行建立，不使用這裡的密碼。
"""

import os

from sqlalchemy import select

from app.core import auth
from app.core.db import session_scope
from app.core.enums import Role
from app.core.models import UserAccount

# 開發環境專用的密碼，可用環境變數 SEED_PASSWORD 覆寫
DEV_PASSWORD = os.environ.get("SEED_PASSWORD", "mediagent-dev")

USERS = [
    ("admin@club.test", "社長", Role.ADMIN),
    ("publisher@club.test", "公關", Role.PUBLISHER),
    ("writer@club.test", "新進幹部", Role.WRITER),
]


def run() -> list[str]:
    """建立還不存在的種子使用者，回傳這次新建的 Email。"""
    created = []
    with session_scope() as db:
        for email, name, role in USERS:
            if db.scalar(select(UserAccount.id).where(UserAccount.email == email)):
                continue
            db.add(
                UserAccount(
                    email=email, name=name, role=role, password_hash=auth.hash_password(DEV_PASSWORD)
                )
            )
            created.append(email)
    return created


if __name__ == "__main__":
    new_users = run()
    print(f"建立了 {len(new_users)} 位使用者：{', '.join(new_users) or '（都已存在）'}")
    print(f"開發用密碼：{DEV_PASSWORD}")
