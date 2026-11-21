"""正式環境建立第一位管理員（之後的帳號由管理員在系統裡建立）。

開發用的 seeds.seed_dev 帳號密碼是固定的，不能用在正式環境。Render 免費方案沒有主機的命令列，
所以在自己的電腦上執行，DATABASE_URL 指向正式環境的資料庫（Neon）：

    DATABASE_URL='postgresql://…neon.tech/neondb?sslmode=require' python -m seeds.create_admin

密碼以隱藏輸入的方式詢問，不會出現在畫面、指令紀錄或 Log。
"""

import getpass
import re

from sqlalchemy import select

from app.core import audit, auth
from app.core.db import session_scope
from app.core.enums import AuditAction, Role, TargetType
from app.core.models import UserAccount

EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
MIN_PASSWORD_LENGTH = 8


def create_admin(email: str, name: str, password: str) -> int:
    """建立一位啟用中的管理員，回傳使用者 ID；寫入一筆系統執行的「建立幹部帳號」稽核紀錄。"""
    email = email.strip().lower()
    if not EMAIL_PATTERN.match(email):
        raise ValueError("Email 格式錯誤")
    if not name.strip():
        raise ValueError("名稱不可空白")
    if not password.strip() or len(password) < MIN_PASSWORD_LENGTH:
        raise ValueError(f"密碼至少要 {MIN_PASSWORD_LENGTH} 個字元")
    with session_scope() as db:
        if db.scalar(select(UserAccount.id).where(UserAccount.email == email)) is not None:
            raise ValueError(f"{email} 已經存在")
        user = UserAccount(
            email=email, name=name.strip(), role=Role.ADMIN, password_hash=auth.hash_password(password)
        )
        db.add(user)
        db.flush()
        audit.write(
            db,
            action=AuditAction.USER_CREATE,
            actor=None,
            target_type=TargetType.USER_ACCOUNT,
            target_id=user.id,
        )
        return user.id


def main() -> None:
    email = input("管理員 Email：")
    name = input("顯示名稱：")
    password = getpass.getpass("密碼（至少 8 個字元，輸入時不會顯示）：")
    if password != getpass.getpass("再輸入一次密碼："):
        raise SystemExit("兩次輸入的密碼不同，沒有建立帳號")
    try:
        user_id = create_admin(email, name, password)
    except ValueError as exc:
        raise SystemExit(f"沒有建立帳號：{exc}") from None
    print(f"已建立管理員（ID {user_id}）：{email.strip().lower()}")


if __name__ == "__main__":
    main()
