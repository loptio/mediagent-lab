"""IP 登入限流（BR-42）：同一 IP 在任意連續 60 秒內最多 10 次登入嘗試。

計數存在記憶體，服務重啟後歸零；正式環境只有一個實例，因此可接受（architecture §11、決策 21）。
區間是「現在往前 60 秒、不含恰好 60 秒前那一刻」。被拒絕的請求沒有實際驗證密碼，不計入嘗試次數。
"""

import math
import threading
from collections import deque
from datetime import datetime, timedelta

WINDOW = timedelta(seconds=60)
# 記錄的 IP 太多時順便清掉已經離開區間的，避免記憶體一直長大
SWEEP_THRESHOLD = 10_000


class LoginRateLimiter:
    def __init__(self) -> None:
        self._attempts: dict[str, deque[datetime]] = {}
        self._lock = threading.Lock()

    def attempt(self, ip: str, now: datetime, limit: int) -> int | None:
        """記錄一次嘗試並回傳 None；超過上限時不記錄，回傳要等幾秒（Retry-After）。"""
        cutoff = now - WINDOW
        with self._lock:
            if len(self._attempts) > SWEEP_THRESHOLD:
                self._sweep(cutoff)
            attempts = self._attempts.setdefault(ip, deque())
            while attempts and attempts[0] <= cutoff:
                attempts.popleft()
            if len(attempts) >= limit:
                return max(1, math.ceil((attempts[0] + WINDOW - now).total_seconds()))
            attempts.append(now)
            return None

    def _sweep(self, cutoff: datetime) -> None:
        for ip in [ip for ip, attempts in self._attempts.items() if not attempts or attempts[-1] <= cutoff]:
            del self._attempts[ip]

    def reset(self) -> None:
        with self._lock:
            self._attempts.clear()


limiter = LoginRateLimiter()
