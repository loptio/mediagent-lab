def test_health_reports_database_ok(client):
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "ok"}


def test_unknown_path_uses_error_format(client):
    response = client.get("/api/v1/no-such-thing")

    assert response.status_code == 404
    body = response.json()
    assert body["code"] == "NOT_FOUND"
    assert body["message"]
    assert body["request_id"] == response.headers["X-Request-Id"]


def test_request_id_is_echoed(client):
    response = client.get("/health", headers={"X-Request-Id": "req-123"})

    assert response.headers["X-Request-Id"] == "req-123"
