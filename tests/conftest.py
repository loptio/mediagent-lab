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


@pytest.fixture(scope="session", autouse=True)
def test_database():
    admin = create_engine(ADMIN_URL, isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        exists = conn.execute(
            text("SELECT 1 FROM pg_database WHERE datname = :name"), {"name": TEST_DB}
        ).scalar()
        if not exists:
            conn.execute(text(f'CREATE DATABASE "{TEST_DB}"'))
    admin.dispose()


@pytest.fixture
def client(test_database):
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as test_client:
        yield test_client
