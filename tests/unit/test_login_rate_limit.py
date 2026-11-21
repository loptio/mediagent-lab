"""IP 登入限流（BR-42）：任意連續 60 秒內最多 10 次，區間不含恰好 60 秒前那一刻。"""

from datetime import UTC, datetime, timedelta

from app.m1_accounts.rate_limit import LoginRateLimiter

T0 = datetime(2026, 10, 5, 2, 0, tzinfo=UTC)
IP = "203.0.113.5"


def at(seconds: float) -> datetime:
    return T0 + timedelta(seconds=seconds)


def limiter_with_ten_attempts() -> LoginRateLimiter:
    limiter = LoginRateLimiter()
    for second in range(0, 50, 5):  # 10:00:00、10:00:05 … 10:00:45
        assert limiter.attempt(IP, at(second), limit=10) is None
    return limiter


def test_eleventh_attempt_within_sixty_seconds_is_refused_with_retry_after():
    limiter = limiter_with_ten_attempts()

    assert limiter.attempt(IP, at(59), limit=10) == 1  # 最早一次 10:00:00 在 10:01:00 離開區間


def test_attempt_is_allowed_once_the_oldest_leaves_the_window():
    limiter = limiter_with_ten_attempts()

    assert limiter.attempt(IP, at(60), limit=10) is None  # 恰好 60 秒前那一次不算在區間內


def test_tenth_attempt_is_allowed():
    limiter = LoginRateLimiter()
    for second in range(9):
        limiter.attempt(IP, at(second), limit=10)

    assert limiter.attempt(IP, at(59), limit=10) is None


def test_other_ips_are_counted_separately():
    limiter = limiter_with_ten_attempts()

    assert limiter.attempt("198.51.100.7", at(59), limit=10) is None


def test_refused_attempts_do_not_extend_the_block():
    limiter = limiter_with_ten_attempts()
    for second in (50, 55, 59):
        assert limiter.attempt(IP, at(second), limit=10) is not None

    assert limiter.attempt(IP, at(60), limit=10) is None
