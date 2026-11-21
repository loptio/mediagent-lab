"""前端靜態檔（foundation-plan D-06）：/ 提供前端，/api 的行為與錯誤格式維持不變。"""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.errors import install_error_handlers
from app.main import mount_frontend


@pytest.fixture
def frontend_client(tmp_path):
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<!doctype html><div id=app></div>", encoding="utf-8")
    (dist / "assets" / "app.js").write_text("console.log(1)", encoding="utf-8")

    application = FastAPI()
    install_error_handlers(application)

    @application.get("/api/v1/ping")
    def ping():
        return {"ok": True}

    mount_frontend(application, dist)
    return TestClient(application)


def test_root_and_frontend_routes_serve_index(frontend_client):
    for path in ("/", "/posts", "/posts/12", "/platform-accounts?result=linked"):
        response = frontend_client.get(path)
        assert response.status_code == 200, path
        assert "<div id=app>" in response.text


def test_index_is_always_revalidated(frontend_client):
    assert frontend_client.get("/posts/12").headers["Cache-Control"] == "no-cache"


def test_built_assets_are_served(frontend_client):
    response = frontend_client.get("/assets/app.js")

    assert response.status_code == 200
    assert response.text == "console.log(1)"
    assert "Cache-Control" not in response.headers


def test_missing_asset_is_404_not_index(frontend_client):
    assert frontend_client.get("/assets/old-build.js").status_code == 404


def test_api_routes_take_priority(frontend_client):
    assert frontend_client.get("/api/v1/ping").json() == {"ok": True}


def test_unknown_api_path_keeps_json_error_format(frontend_client):
    response = frontend_client.get("/api/v1/no-such-thing")

    assert response.status_code == 404
    assert response.json()["code"] == "NOT_FOUND"


def test_wrong_method_on_api_path_is_still_405(frontend_client):
    assert frontend_client.post("/api/v1/ping").status_code == 405


def test_nothing_is_mounted_without_a_build(tmp_path):
    application = FastAPI()
    mount_frontend(application, tmp_path / "missing")

    assert TestClient(application).get("/").status_code == 404
