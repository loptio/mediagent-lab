"""驗收測試（pytest-bdd）：執行 `spec/features/` 的 452 個例子（architecture §13）。

- 載入：把每個 Example 的名稱改成「{Rule} — {Example}」後寫到 `tests/bdd/_generated/` 再載入，
  不同 Rule 底下同名的 Example 才不會互相覆蓋；`spec/features/` 本身不修改。
- 待實作：各 `test_<功能>.py` 用 `PENDING = {"Rule 或 Rule — Example": "原因"}` 宣告，
  收集時轉成 skip（團隊規範 §8.1）。
- 身分：以 `X-Dev-User` 代替登入（只在測試中開啟 DEV_MODE），不會產生登入的稽核紀錄干擾比對。
"""

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest
from pytest_bdd.scenario import scenario_wrapper_template_registry
from sqlalchemy import func, select

from app.core import models
from app.core.config import get_settings

FEATURES = Path(__file__).resolve().parents[2] / "spec" / "features"
GENERATED = Path(__file__).resolve().parent / "_generated"
API = "/api/v1"

_RULE = re.compile(r"^(\s*)Rule:\s*(.+?)\s*$")
_EXAMPLE = re.compile(r"^(\s*)(Example|Scenario):\s*(.+?)\s*$")


def _generate_features() -> None:
    GENERATED.mkdir(exist_ok=True)
    for source in FEATURES.glob("*.feature"):
        rule = None
        lines = []
        for line in source.read_text(encoding="utf-8").splitlines():
            if match := _RULE.match(line):
                rule = match.group(2)
            elif (match := _EXAMPLE.match(line)) and rule:
                line = f"{match.group(1)}{match.group(2)}: {rule} — {match.group(3)}"
            lines.append(line)
        target = GENERATED / source.name
        content = "\n".join(lines) + "\n"
        if not target.exists() or target.read_text(encoding="utf-8") != content:
            target.write_text(content, encoding="utf-8")


_generate_features()


def feature(name: str) -> str:
    """test_<功能>.py 用：`scenarios(feature("立即發佈"))`。"""
    return str(GENERATED / f"{name}.feature")


def pytest_collection_modifyitems(config, items):
    """PENDING：預期失敗（xfail strict）——哪天其實通過了，測試會失敗，提醒把宣告拿掉。
    SKIP：這個例子在目前的測試方式下無法有效驗證（跑了也只會空泛地通過），直接略過。
    宣告的鍵對不到任何例子時報錯，避免 Rule 改名後宣告默默失效。"""
    used: dict[object, set[str]] = {}
    for item in items:
        template = scenario_wrapper_template_registry.get(getattr(item, "obj", None))
        if template is None:
            continue
        rule = template.name.split(" — ", 1)[0]
        for attribute, marker in (("PENDING", "xfail"), ("SKIP", "skip")):
            declared: dict[str, str] = getattr(item.module, attribute, {})
            for key in (template.name, rule, "*"):
                if key in declared:
                    used.setdefault((item.module, attribute), set()).add(key)
                    reason = declared[key]
                    if marker == "xfail":
                        item.add_marker(pytest.mark.xfail(strict=True, reason=f"pending：{reason}"))
                    else:
                        item.add_marker(pytest.mark.skip(reason=f"無法有效驗證：{reason}"))
                    break
    modules = {
        item.module for item in items if scenario_wrapper_template_registry.get(getattr(item, "obj", None))
    }
    for module in modules:
        for attribute in ("PENDING", "SKIP"):
            unused = set(getattr(module, attribute, {})) - used.get((module, attribute), set())
            if unused:
                raise pytest.UsageError(f"{module.__name__}.{attribute} 對不到任何例子：{sorted(unused)}")


# ---------- 每個例子共用的狀態 ----------

_BASELINE_MODELS = {
    "audit": models.AuditLog,
    "login_event": models.LoginSecurityEvent,
    "auth_event": models.PlatformAuthEvent,
    "history": models.PublishRecordHistory,
    "post": models.Post,
}


@dataclass
class World:
    client: Any
    db: Any
    mocks: dict
    users: dict[str, int] = field(default_factory=dict)  # email → id
    passwords: dict[str, str] = field(default_factory=dict)
    accounts: dict[str, int] = field(default_factory=dict)  # 平台帳號名稱 → id
    posts: dict[str, int] = field(default_factory=dict)  # 例子裡的貼文代號（P1）→ id
    response: Any = None
    baseline: dict[str, int] = field(default_factory=dict)
    images: dict[str, list[dict]] = field(default_factory=dict)  # 圖片功能完成前只記下來
    hanging: set[str] = field(default_factory=set)  # 「發佈尚未完成」的平台帳號
    extra: dict[str, Any] = field(default_factory=dict)

    def headers(self, email: str) -> dict[str, str]:
        user_id = self.users.get(email.strip().lower())
        return {"X-Dev-User": str(user_id)} if user_id else {}

    def mark(self) -> None:
        """記下目前各表的最大 id：之後比對「系統新增一筆…」只看這之後的資料。"""
        self.db.expire_all()
        self.baseline = {
            name: self.db.scalar(select(func.coalesce(func.max(model.id), 0))) or 0
            for name, model in _BASELINE_MODELS.items()
        }

    def request(self, email: str | None, method: str, path: str, **kwargs):
        self.mark()
        headers = self.headers(email) if email else {}
        headers |= kwargs.pop("headers", {})
        self.response = self.client.request(method, f"{API}{path}", headers=headers, **kwargs)
        return self.response

    def new_rows(self, name: str):
        model = _BASELINE_MODELS[name]
        self.db.expire_all()
        return list(
            self.db.scalars(select(model).where(model.id > self.baseline.get(name, 0)).order_by(model.id))
        )

    def post_id(self, alias: str) -> int:
        alias = alias.strip()
        if alias in self.posts:
            return self.posts[alias]
        if alias.isdigit():
            return int(alias)
        raise KeyError(f"例子裡沒有定義貼文 {alias!r}")

    def account_id(self, name: str) -> int:
        """例子裡建立的平台帳號；流程中新連結的帳號依名稱查詢（優先未移除的那一個）。"""
        name = name.strip()
        if name in self.accounts:
            return self.accounts[name]
        self.db.expire_all()
        account_id = self.db.scalar(
            select(models.PlatformAccount.id)
            .where(models.PlatformAccount.account_name == name)
            .order_by(models.PlatformAccount.removed, models.PlatformAccount.id.desc())
        )
        if account_id is None:
            raise KeyError(f"沒有平台帳號 {name!r}")
        return account_id

    def user_id(self, email: str) -> int:
        email = email.strip().lower()
        if email not in self.users:  # 流程中新建立的帳號
            self.db.expire_all()
            user_id = self.db.scalar(select(models.UserAccount.id).where(models.UserAccount.email == email))
            if user_id is None:
                raise KeyError(f"沒有使用者帳號 {email!r}")
            self.users[email] = user_id
        return self.users[email]


@pytest.fixture
def world(client, db, mock_platforms, monkeypatch, tmp_path):
    settings = get_settings()
    monkeypatch.setattr(settings, "media_dir", str(tmp_path / "media"))
    monkeypatch.setattr(settings, "media_base_url", "https://media.test/media")
    monkeypatch.setattr(settings, "dev_mode", True)
    monkeypatch.setattr(settings, "cron_secret", "bdd-cron-secret")
    # 「發佈逾時」以 Adapter 拋出逾時表示，不需要真的等 30 秒
    monkeypatch.setattr(settings, "publish_poll_interval_seconds", 0)
    # 驗收例子依規格的 IP 限流（BR-42）：每分鐘 10 次
    monkeypatch.setattr(settings, "login_attempts_per_minute", 10)
    # 例子用 https://discord.test/api/webhooks/… 當 Webhook 網址：
    # 測試環境視為格式正確，實際驗證結果由 MockAdapter 決定
    from app.m2_platforms import service as platforms_service

    real_is_webhook_url = platforms_service.is_webhook_url
    monkeypatch.setattr(
        platforms_service,
        "is_webhook_url",
        lambda url: url.startswith("https://discord.test/api/webhooks/") or real_is_webhook_url(url),
    )
    return World(client=client, db=db, mocks=mock_platforms)


from tests.bdd.steps.common import *  # noqa: E402,F403  共用步驟（architecture §13.2）
