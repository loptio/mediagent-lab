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
PENDING: dict[str, str] = {
    "前置：目標平台帳號含 Instagram 時，貼文必須附加圖片": "BR-05（Instagram 必須附圖）尚未強制：圖片功能完成前無法附圖，強制會讓 Instagram 完全無法使用；圖片完成時一併實作",
    "後置：Instagram 使用 Instagram 版本的圖片，Threads 與 Discord 使用原圖": "圖片功能（上傳、裁切、物件儲存）尚未實作",
    "後置：實際發佈時，發佈紀錄保存送出圖片的識別資訊（雜湊值、格式、尺寸、版本），不保存圖片檔案": "圖片功能（上傳、裁切、物件儲存）尚未實作",
}

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
