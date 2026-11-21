"""驗收：設定目標平台帳號（spec/features/設定目標平台帳號.feature）。"""

from pytest_bdd import scenarios

from tests.bdd.conftest import feature

# 尚未實作的功能：{"Rule 或 Rule — Example": "原因"}
PENDING: dict[str, str] = {
    "前置：貼文沒有附加圖片時，Instagram 平台帳號不能被選為目標平台帳號": "BR-05（Instagram 必須附圖）尚未強制：圖片功能完成前無法附圖，強制會讓 Instagram 完全無法使用；圖片完成時一併實作",
}

scenarios(feature("設定目標平台帳號"))
