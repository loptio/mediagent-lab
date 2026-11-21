"""本機開發環境不可以對區域網路開放，也不可以預設開啟免密碼的開發模式。"""

from pathlib import Path

from app.core.config import get_settings
from tests.factories import make_user

COMPOSE = (Path(__file__).resolve().parents[2] / "docker-compose.yml").read_text(encoding="utf-8")


def test_compose_ports_are_bound_to_localhost_only():
    assert '"127.0.0.1:5432:5432"' in COMPOSE
    assert '"127.0.0.1:8000:8000"' in COMPOSE
    assert '- "5432:5432"' not in COMPOSE
    assert '- "8000:8000"' not in COMPOSE


def test_compose_does_not_force_dev_mode_on():
    assert 'DEV_MODE: "1"' not in COMPOSE
    assert "DEV_MODE: ${DEV_MODE:-0}" in COMPOSE


def test_dev_user_header_is_ignored_unless_dev_mode_is_on(client, db):
    user = make_user(db)
    db.commit()

    response = client.get("/api/v1/auth/me", headers={"X-Dev-User": str(user.id)})

    assert response.status_code == 401


def test_dev_user_header_authenticates_only_in_dev_mode(client, db, monkeypatch):
    user = make_user(db)
    db.commit()
    monkeypatch.setattr(get_settings(), "dev_mode", True)

    response = client.get("/api/v1/auth/me", headers={"X-Dev-User": str(user.id)})

    assert response.status_code == 200
    assert response.json()["email"] == user.email


def test_https_proxy_is_local_only_and_opt_in():
    # OAuth 回呼用的 HTTPS 代理：只在需要時啟動（profile），而且只綁定本機
    assert "  https:" in COMPOSE
    assert 'profiles: ["oauth"]' in COMPOSE
    assert '"127.0.0.1:8443:8443"' in COMPOSE
    assert '- "8443:8443"' not in COMPOSE
