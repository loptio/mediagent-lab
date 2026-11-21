"""uvicorn 的存取紀錄會寫出完整網址；OAuth 回呼的查詢字串含授權碼與 state，不可進 Log（NFR-02）。"""

import logging

import app.main  # noqa: F401  匯入時安裝存取紀錄的過濾器


def access_record(path: str) -> logging.LogRecord:
    # 與 uvicorn 寫存取紀錄時使用的格式和參數相同
    return logging.LogRecord(
        "uvicorn.access", logging.INFO, __file__, 0,
        '%s - "%s %s HTTP/%s" %d', ("127.0.0.1:50000", "GET", path, "1.1", 302), None,
    )


def test_oauth_callback_query_is_not_written_to_the_access_log():
    record = access_record("/api/v1/platform-accounts/oauth/callback?code=SECRET-CODE&state=SECRET-STATE")

    assert logging.getLogger("uvicorn.access").filter(record)  # 這一行紀錄仍然要寫出
    message = record.getMessage()

    assert "SECRET-CODE" not in message and "SECRET-STATE" not in message
    assert '"GET /api/v1/platform-accounts/oauth/callback?[redacted] HTTP/1.1" 302' in message


def test_other_requests_keep_their_query_in_the_access_log():
    record = access_record("/api/v1/posts?page=2")

    logging.getLogger("uvicorn.access").filter(record)

    assert "/api/v1/posts?page=2" in record.getMessage()
