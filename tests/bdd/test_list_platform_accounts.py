"""驗收：查看平台帳號（spec/features/查看平台帳號.feature）。"""

from pytest_bdd import scenarios

from tests.bdd.conftest import feature

# 尚未實作的功能：{"Rule 或 Rule — Example": "原因"}
PENDING: dict[str, str] = {}

scenarios(feature("查看平台帳號"))
