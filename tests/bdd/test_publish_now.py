"""驗收：立即發佈（spec/features/立即發佈.feature）。"""

from datetime import timedelta  # noqa: F401

from pytest_bdd import given, scenarios, then, when  # noqa: F401
from sqlalchemy import select  # noqa: F401

from app.core import clock, models  # noqa: F401
from tests.bdd import labels as L  # noqa: F401
from tests.bdd.conftest import feature
from tests.bdd.labels import code, tw_time  # noqa: F401
from tests.bdd.steps.common import Result, iso, rows, step  # noqa: F401

# 尚未實作的功能：{"Rule 或 Rule — Example": "原因"}
PENDING: dict[str, str] = {}

scenarios(feature("立即發佈"))


@when(step('"X" 立即發佈貼文 "X"'))
def when_publish_now(world, a, b):
    world.request(a, "POST", f"/posts/{world.post_id(b)}/publish-jobs", json={"type": "immediate"})


@given(step('平台帳號 "X" 的存取憑證為 "X"'))
def given_credential(world, a, b):
    from app.core import crypto

    account = world.db.get(models.PlatformAccount, world.account_id(a))
    token, version = crypto.encrypt_credential({"account_name": a, "access_token": b})
    account.credential_encrypted, account.credential_key_version = token, version
    world.db.commit()
