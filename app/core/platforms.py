"""平台串接介面（Adapter）：三步發佈 begin／check／finalize（foundation-plan D-01）。

- begin：建立平台的中途資源（例如 container），回傳 request_ref；
  一步就能發完的平台（Discord）直接回傳發佈結果。
- check：只查詢，不改變任何東西，可以放心重試。
- finalize：正式發佈；只在 check 回 READY 時呼叫，不自動重試。

Adapter 不向外拋出例外：平台的錯誤一律轉成 Failed（含失敗原因）。
逾時由發佈引擎處理。
"""

import asyncio
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any, Protocol

from pydantic import BaseModel
from sqlalchemy.orm import Session

from .enums import AuthStatus, FailureReason, Platform
from .models import PlatformAccount

Credential = dict[str, Any]


class Capabilities(BaseModel):
    """各平台的內容限制（需求 4.7）。"""

    max_text_length: int
    requires_image: bool = False
    min_aspect_ratio: float | None = None
    max_aspect_ratio: float | None = None
    auth_expires: bool = False


CAPABILITIES: dict[Platform, Capabilities] = {
    Platform.THREADS: Capabilities(max_text_length=500, auth_expires=True),
    Platform.INSTAGRAM: Capabilities(
        max_text_length=2200,
        requires_image=True,
        min_aspect_ratio=0.8,
        max_aspect_ratio=1.91,
        auth_expires=True,
    ),
    Platform.DISCORD: Capabilities(max_text_length=2000),
}


@dataclass(frozen=True)
class PostContent:
    text: str
    image_url: str | None = None


@dataclass(frozen=True)
class Started:
    """begin 的結果：平台已建立中途資源，之後用 request_ref 查詢與發佈。"""

    request_ref: str


@dataclass(frozen=True)
class Published:
    post_id: str | None = None
    post_url: str | None = None


@dataclass(frozen=True)
class Failed:
    reason: FailureReason
    # 平台原始錯誤訊息（只有管理員可看）；Adapter 必須先過濾憑證
    message: str | None = None


class CheckStatus(StrEnum):
    PROCESSING = "PROCESSING"  # 平台還在處理
    READY = "READY"  # 處理完成、尚未發佈，可以 finalize
    PUBLISHED = "PUBLISHED"  # 已經發出，不可再發
    FAILED = "FAILED"  # 平台處理失敗或已過期
    UNKNOWN = "UNKNOWN"  # 無法確認


@dataclass(frozen=True)
class CheckResult:
    status: CheckStatus
    published: Published | None = None
    failed: Failed | None = None


class PlatformAdapter(Protocol):
    platform: Platform
    capabilities: Capabilities

    def count_chars(self, text: str) -> int: ...

    async def begin(
        self, credential: Credential, content: PostContent
    ) -> Started | Published | Failed: ...

    async def check(self, credential: Credential, request_ref: str | None) -> CheckResult: ...

    async def finalize(self, credential: Credential, request_ref: str) -> Published | Failed: ...


class WebhookInvalid(Exception):
    """Webhook 網址格式不對，或平台明確回應這個 Webhook 不存在、不可用。"""


class VerificationUnavailable(Exception):
    """暫時無法向平台驗證（網路或平台暫時性錯誤）；不代表 Webhook 無效（BR-37）。"""


class UnavailableAdapter:
    """還沒有真實 Adapter 的平台：提供內容限制，但發佈一律失敗，不會假裝成功。"""

    def __init__(self, platform: Platform) -> None:
        self.platform = platform
        self.capabilities = CAPABILITIES[platform]

    def count_chars(self, text: str) -> int:
        return len(text)

    async def begin(self, credential: Credential, content: PostContent) -> Failed:
        return Failed(FailureReason.OTHER, f"{self.platform} adapter is not implemented yet")

    async def check(self, credential: Credential, request_ref: str | None) -> CheckResult:
        return CheckResult(CheckStatus.UNKNOWN)

    async def finalize(self, credential: Credential, request_ref: str) -> Failed:
        return Failed(FailureReason.OTHER, f"{self.platform} adapter is not implemented yet")


# ---------- 註冊表 ----------

_registry: dict[Platform, PlatformAdapter] = {}


def register_adapter(adapter: PlatformAdapter) -> None:
    _registry[Platform(adapter.platform)] = adapter


def get_adapter(platform: str) -> PlatformAdapter:
    return _registry[Platform(platform)]


# ---------- 授權狀態（BR-09） ----------


def effective_auth_status(account: PlatformAccount, now: datetime) -> AuthStatus:
    """計算有效授權狀態：平台曾明確回應失效，或授權到期時間已過，即為失效。"""
    expired = account.auth_expires_at is not None and account.auth_expires_at <= now
    if account.auth_status == AuthStatus.INVALID or expired:
        return AuthStatus.INVALID
    return AuthStatus.VALID


def mark_auth_invalid(db: Session, account_id: int) -> None:
    """發佈時平台明確回應授權無效：把平台帳號標為失效，等管理員重新連結。"""
    account = db.get(PlatformAccount, account_id)
    if account is not None:
        account.auth_status = AuthStatus.INVALID
        db.flush()


# ---------- MockAdapter（NFR-04：不連真實平台也能測試） ----------


class MockAdapter:
    """模擬平台。以憑證中的 account_name 辨認帳號，可設定每個帳號的行為。

    預設行為：begin 成功 → check 回 READY → finalize 成功。
    只有成功執行 finalize 的貼文才算「平台收到」（記錄在 received）。
    """

    def __init__(self, platform: Platform) -> None:
        self.platform = platform
        self.capabilities = CAPABILITIES[platform]
        self.reset()

    def reset(self) -> None:
        self._outcomes: dict[str, Published | Failed] = {}
        self._hanging: set[str] = set()
        self._errors: dict[str, Exception] = {}
        self._checks: dict[str, CheckResult] = {}
        self._pending: dict[str, tuple[str, PostContent]] = {}
        self._counter = 0
        self.received: list[tuple[str, PostContent]] = []

    # --- 測試用的設定 ---

    def succeed(self, account_name: str, post_url: str) -> None:
        self._outcomes[account_name] = Published(post_url=post_url)

    def fail(self, account_name: str, reason: FailureReason, message: str | None = None) -> None:
        self._outcomes[account_name] = Failed(reason, message)

    def hang(self, account_name: str) -> None:
        """begin 停住不回應，用來模擬逾時或尚未完成。"""
        self._hanging.add(account_name)

    def raise_error(self, account_name: str, error: Exception) -> None:
        """模擬 Adapter 的程式錯誤（真實 Adapter 不應該拋出例外，但引擎必須擋得住）。"""
        self._errors[account_name] = error

    def set_check(self, account_name: str, result: CheckResult) -> None:
        self._checks[account_name] = result

    # --- PlatformAdapter ---

    def count_chars(self, text: str) -> int:
        return len(text)

    async def verify_webhook(self, webhook_url: str) -> dict[str, Any]:
        """離線開發用：不連線，直接回傳假的識別資料。"""
        return {"webhook_id": "0", "guild_id": "0", "channel_id": "0"}

    async def begin(self, credential: Credential, content: PostContent) -> Started:
        name = credential["account_name"]
        if name in self._errors:
            raise self._errors[name]
        if name in self._hanging:
            await asyncio.Event().wait()
        self._counter += 1
        request_ref = f"mock-{self.platform}-{self._counter}"
        self._pending[request_ref] = (name, content)
        return Started(request_ref)

    async def check(self, credential: Credential, request_ref: str | None) -> CheckResult:
        return self._checks.get(credential["account_name"], CheckResult(CheckStatus.READY))

    async def finalize(self, credential: Credential, request_ref: str) -> Published | Failed:
        name, content = self._pending.pop(request_ref)
        outcome = self._outcomes.get(
            name, Published(post_url=f"https://{self.platform}.test/p/{request_ref}")
        )
        if isinstance(outcome, Failed):
            return outcome
        self.received.append((name, content))
        return Published(post_id=request_ref, post_url=outcome.post_url)


def register_mock_adapters() -> dict[Platform, MockAdapter]:
    """三個平台都註冊為 MockAdapter，但沿用各自真實的 Capabilities。"""
    mocks = {platform: MockAdapter(platform) for platform in Platform}
    for mock in mocks.values():
        register_adapter(mock)
    return mocks
