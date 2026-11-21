"""E2E 測試資料：直接在資料庫建立 Threads、Instagram、Discord 平台帳號（模擬已完成平台授權）。

在 api 容器內執行，憑證用服務本身的金鑰加密（由 e2e/support/stack.ts 的 seedAccounts 呼叫）：
    docker compose ... exec -T -e E2E_ACCOUNTS='[{"platform": "threads", "name": "x"}]' \
        api python - < seed_accounts.py
輸出建立好的帳號（JSON）。只用於 PLATFORM_MODE=mock 的測試環境。
"""

import json
import os
from datetime import timedelta

from sqlalchemy import select

from app.core import clock
from app.core.config import get_settings
from app.core.crypto import encrypt_credential
from app.core.db import session_scope
from app.core.models import UserAccount
from app.m2_platforms import repository

if get_settings().platform_mode != "mock":
    raise SystemExit("E2E 測試資料只能建立在 PLATFORM_MODE=mock 的環境")

specs = json.loads(os.environ["E2E_ACCOUNTS"])
created = []
with session_scope() as db:
    admin = db.scalar(select(UserAccount).where(UserAccount.email == "admin@club.test"))
    if admin is None:
        raise SystemExit("找不到種子管理員，請先執行 python -m seeds.seed_dev")
    for spec in specs:
        platform, name = spec["platform"], spec["name"]
        credential = {"account_name": name, "access_token": "e2e-mock-token"}
        token, key_version = encrypt_credential(credential)
        account = repository.create(
            db,
            platform=platform,
            account_name=name,
            credential_encrypted=token,
            credential_key_version=key_version,
            linked_by=admin.id,
            platform_user_id=f"e2e-{name}",
            # Threads、Instagram 的授權會到期；Discord Webhook 不會
            auth_expires_at=None if platform == "discord" else clock.now() + timedelta(days=60),
        )
        created.append({"id": account.id, "platform": platform, "name": name})

print(json.dumps(created, ensure_ascii=False))
