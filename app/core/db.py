"""資料庫連線與交易工具。

交易由 service 負責：一個使用情境結束時呼叫 db.commit()。
get_db 只負責開關 Session；沒有 commit 的變更會在關閉時回復。
"""

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import get_settings

# hide_parameters：資料庫錯誤會被寫進 Log，參數裡可能有密碼雜湊或加密憑證，不可以一起印出（NFR-02）
engine = create_engine(get_settings().database_url, pool_pre_ping=True, hide_parameters=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


def get_db() -> Iterator[Session]:
    with SessionLocal() as db:
        yield db


@contextmanager
def session_scope() -> Iterator[Session]:
    """短交易：正常結束時 commit，例外時 rollback。給背景工作（發佈引擎）使用。"""
    with SessionLocal() as db:
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
