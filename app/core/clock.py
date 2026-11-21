"""時鐘：全系統取得「現在」的唯一來源，一律是帶時區的 UTC 時間；測試可以固定時間。"""

from datetime import UTC, datetime

_fixed: datetime | None = None


def now() -> datetime:
    return _fixed if _fixed is not None else datetime.now(UTC)


def set_fixed(moment: datetime) -> None:
    global _fixed
    if moment.tzinfo is None:
        raise ValueError("clock.set_fixed() requires a timezone-aware datetime")
    _fixed = moment.astimezone(UTC)


def reset() -> None:
    global _fixed
    _fixed = None
