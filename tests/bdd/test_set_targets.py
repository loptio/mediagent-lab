"""驗收：設定目標平台帳號（spec/features/設定目標平台帳號.feature）。"""

from pytest_bdd import scenarios

from tests.bdd.conftest import feature

# 尚未實作的功能：{"Rule 或 Rule — Example": "原因"}
PENDING: dict[str, str] = {}

scenarios(feature("設定目標平台帳號"))
