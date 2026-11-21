import os

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import create_engine, text

ADMIN_URL = os.environ.get(
    "TEST_ADMIN_DATABASE_URL", "postgresql+psycopg://mediagent:mediagent@localhost:5432/mediagent"
)
TEST_DB = "mediagent_test"
TEST_URL = ADMIN_URL.rsplit("/", 1)[0] + f"/{TEST_DB}"

# 必須在匯入 app 之前設定，Settings 只讀一次
os.environ["DATABASE_URL"] = TEST_URL
os.environ["JWT_SECRET"] = "test-only-jwt-secret-0123456789abcdef"
os.environ["CREDENTIAL_ENCRYPTION_KEYS"] = Fernet.generate_key().decode()
os.environ["DEV_MODE"] = "0"
os.environ["PLATFORM_MODE"] = "mock"


@pytest.fixture(scope="session", autouse=True)
def test_database():
    """每次測試執行都重建測試資料庫，再用 Alembic 建立結構：migration 本身也因此被驗證。"""
    admin = create_engine(ADMIN_URL, isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text(f'DROP DATABASE IF EXISTS "{TEST_DB}" WITH (FORCE)'))
        conn.execute(text(f'CREATE DATABASE "{TEST_DB}"'))
    admin.dispose()

    from alembic.config import Config

    from alembic import command

    command.upgrade(Config("alembic.ini"), "head")


@pytest.fixture(autouse=True)
def clean_tables(test_database):
    """每個測試從空的資料表開始。

    稽核等只能新增的表有觸發器禁止 TRUNCATE，測試清理時暫時以 replica 角色略過觸發器。
    """
    from app.core import clock
    from app.core.db import Base, engine

    tables = ", ".join(f'"{name}"' for name in Base.metadata.tables)
    with engine.begin() as conn:
        conn.execute(text("SET session_replication_role = replica"))
        conn.execute(text(f"TRUNCATE TABLE {tables} RESTART IDENTITY CASCADE"))
        conn.execute(text("ALTER SEQUENCE global_event_seq RESTART WITH 1"))
        conn.execute(text("SET session_replication_role = DEFAULT"))
    clock.reset()
    yield
    clock.reset()


@pytest.fixture
def db(clean_tables):
    from app.core.db import SessionLocal

    with SessionLocal() as session:
        yield session


@pytest.fixture
def client(clean_tables):
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture(autouse=True)
def mock_platforms():
    """每個測試都使用全新的 MockAdapter，不會連到任何真實平台。"""
    from app.core import platforms

    return platforms.register_mock_adapters()
