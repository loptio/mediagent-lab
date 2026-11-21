"""共用步驟：跨多個 feature 使用的句型（architecture §13.2），各 test_<功能>.py 不重寫。"""

import asyncio
from datetime import datetime
from typing import Any

from pytest_bdd import given, parsers, then, when
from sqlalchemy import select

from app.core import auth, clock, crypto, models
from app.core.enums import FailureReason, Platform
from app.core.platforms import (
    CheckResult,
    CheckStatus,
    Failed,
    Published,
    VerificationUnavailable,
    WebhookInvalid,
)
from app.m5_publishing import engine
from tests.bdd import labels as L
from tests.bdd.labels import code, tw_time

DEFAULT_PASSWORD = "Default#2026"


class Result:
    """不是直接由 API 回應判斷成敗的操作（例如平台授權導回）用的簡化回應。"""

    def __init__(self, status_code: int, body: Any = None):
        self.status_code = status_code
        self._body = body if body is not None else {}
        self.text = str(self._body)

    def json(self):
        return self._body


def iso(value: str) -> str:
    """例子裡的台灣時間轉成 API 用的 ISO 8601 字串。"""
    return tw_time(value).isoformat()


def rows(datatable) -> list[dict[str, str]]:
    header, *body = datatable
    return [dict(zip([h.strip() for h in header], [c.strip() for c in row], strict=True)) for row in body]


def q(text: str) -> str:
    """把步驟裡的雙引號參數寫成正規表示式。"""
    return (
        text.replace('"X"', '"(?P<a>[^"]*)"', 1)
        .replace('"X"', '"(?P<b>[^"]*)"', 1)
        .replace('"X"', '"(?P<c>[^"]*)"', 1)
    )


def step(text: str):
    return parsers.re(q(text))


# ---------- 對照與比對 ----------


def account_platform(world, name: str) -> Platform:
    account = world.db.get(models.PlatformAccount, world.account_id(name))
    return Platform(account.platform)


def mock_of(world, name: str):
    return world.mocks[account_platform(world, name)]


def same_time(actual, expected: str) -> bool:
    expected_dt = tw_time(expected)
    if actual is None or actual == "":
        return expected_dt is None
    if isinstance(actual, str):
        actual = datetime.fromisoformat(actual.replace("Z", "+00:00"))
    return expected_dt is not None and actual == expected_dt


TIME_COLUMNS = {"scheduled_at", "published_at", "occurred_at", "auth_expires_at", "created_at", "changed_at"}
LABEL_COLUMNS = {
    "role": [L.ROLE],
    "platform": [L.PLATFORM],
    "auth_status": [L.AUTH_STATUS],
    "status": [L.RECORD_STATUS, L.POST_STATUS, L.USER_STATUS, L.TARGET_RESULT],
    "from_status": [L.RECORD_STATUS],
    "to_status": [L.RECORD_STATUS],
    "failure_reason": [L.FAILURE_REASON, L.LOGIN_FAILURE, L.AUTH_FAILURE],
    "action": [L.AUDIT_ACTION],
    "actor_type": [L.ACTOR_TYPE],
    "target_type": [L.TARGET_TYPE],
    "record_kind": [L.RECORD_KIND],
    "event_type": [L.EVENT_TYPE],
    "skip_reason": [L.SKIP_REASON],
    "reason": [L.HISTORY_REASON, L.AUDIT_REASON],
    "result": [L.POST_STATUS],
    "removed": [L.YES_NO],
}


def expected_value(column: str, raw: str) -> Any:
    raw = raw.strip()
    if raw == "":
        return None
    for mapping in LABEL_COLUMNS.get(column, []):
        if raw in mapping:
            return mapping[raw]
    return raw


def check(column: str, actual: Any, raw: str, describe: str) -> None:
    if column in TIME_COLUMNS:
        assert same_time(actual, raw), f"{describe} 的 {column}：實際 {actual!r}，預期 {raw!r}"
        return
    expected = expected_value(column, raw)
    if isinstance(expected, bool):
        assert bool(actual) == expected, f"{describe} 的 {column}：實際 {actual!r}，預期 {raw!r}"
        return
    if expected is not None and actual is not None and not isinstance(actual, str):
        actual = str(actual)
    assert actual == expected, f"{describe} 的 {column}：實際 {actual!r}，預期 {raw!r}"


# ---------- Given：資料 ----------


@given(step("系統中有以下使用者帳號："))
def given_users(world, datatable):
    for row in rows(datatable):
        email = row["email"].lower()
        password = row.get("password") or DEFAULT_PASSWORD
        user = models.UserAccount(
            email=email,
            name=row["name"],
            role=code(L.ROLE, row["role"]),
            status=code(L.USER_STATUS, row.get("status", "啟用")),
            password_hash=auth.hash_password(password),
        )
        world.db.add(user)
        world.db.flush()
        world.users[email] = user.id
        world.passwords[email] = password
    world.db.commit()


@given(step('現在時間為 "X"'))
def given_now(a):
    clock.set_fixed(tw_time(a))


@given(step("系統中有以下平台帳號："))
def given_platform_accounts(world, datatable):
    for row in rows(datatable):
        name = row["account_name"]
        token, version = crypto.encrypt_credential({"account_name": name})
        account = models.PlatformAccount(
            platform=code(L.PLATFORM, row["platform"]),
            account_name=name,
            platform_user_id=row.get("platform_user_id") or None,
            auth_status=code(L.AUTH_STATUS, row.get("auth_status", "有效")),
            auth_expires_at=tw_time(row.get("auth_expires_at", "")),
            credential_encrypted=token,
            credential_key_version=version,
            linked_by=world.user_id(row["linked_by"]),
        )
        world.db.add(account)
        world.db.flush()
        world.accounts[name] = account.id
    world.db.commit()


@given(step("系統中有以下貼文："))
def given_posts(world, datatable):
    for row in rows(datatable):
        status = code(L.POST_STATUS, row["status"])
        creator = world.user_id(row["creator"])
        post = models.Post(
            content=row["content"],
            creator_id=creator,
            status=status,
            scheduled_at=tw_time(row.get("scheduled_at", "")),
            scheduled_by=creator if row.get("scheduled_at") else None,
            publishing_started_at=clock.now() if status == "PUBLISHING" else None,
        )
        if row.get("created_at"):
            post.created_at = tw_time(row["created_at"])
        world.db.add(post)
        world.db.flush()
        world.posts[row["id"]] = post.id
    world.db.commit()


@given(step('貼文 "X" 已選擇以下目標平台帳號：'))
def given_targets(world, a, datatable):
    post_id = world.post_id(a)
    world.db.query(models.PostTarget).filter(models.PostTarget.post_id == post_id).delete()
    for row in rows(datatable):
        world.db.add(
            models.PostTarget(post_id=post_id, platform_account_id=world.account_id(row["account_name"]))
        )
    world.db.commit()


@given(step('貼文 "X" 已有以下發佈紀錄：'))
def given_records(world, a, datatable):
    post_id = world.post_id(a)
    for row in rows(datatable):
        record = ensure_record(world, post_id, world.account_id(row["account_name"]))
        status = code(L.RECORD_STATUS, row["status"])
        published_at = tw_time(row.get("published_at", ""))
        record.status = status
        record.published_at = published_at
        record.platform_post_url = row.get("post_url") or None
        record.failure_reason = code(L.FAILURE_REASON, row.get("failure_reason", ""))
        record.attempt_started_at = (
            None if status in ("PENDING", "CANCELLED") else published_at or clock.now()
        )
    world.db.commit()


def ensure_record(world, post_id: int, account_id: int) -> models.PublishRecord:
    record = world.db.scalar(
        select(models.PublishRecord).where(
            models.PublishRecord.post_id == post_id, models.PublishRecord.platform_account_id == account_id
        )
    )
    if record is None:
        record = models.PublishRecord(post_id=post_id, platform_account_id=account_id, status="PENDING")
        world.db.add(record)
        world.db.flush()
    return record


@given(step('貼文 "X" 已附加以下圖片：'))
def given_image(world, a, datatable):
    # 圖片功能尚未實作：只記下來，需要圖片結果的例子標為待實作
    world.images[a] = rows(datatable)


@given(step('貼文 "X" 的內容長度為 (?P<n>\\d+) 字元'))
def given_content_length(world, a, n):
    post = world.db.get(models.Post, world.post_id(a))
    post.content = "字" * int(n)
    world.db.commit()


@given(step('平台帳號 "X" 已被移除'))
def given_account_removed(world, a):
    account = world.db.get(models.PlatformAccount, world.account_id(a))
    account.removed, account.removed_at = True, clock.now()
    world.db.commit()


@given(step('使用者帳號 "X" 的角色已設為 "X"'))
def given_role(world, a, b):
    world.db.get(models.UserAccount, world.user_id(a)).role = code(L.ROLE, b)
    world.db.commit()


@given(step('使用者帳號 "X" 鎖定至 "X"'))
def given_locked(world, a, b):
    world.db.get(models.UserAccount, world.user_id(a)).locked_until = tw_time(b)
    world.db.commit()


@given(step('"X" 已登入，登入憑證為 "X"'))
def given_logged_in(world, a, b):
    user = world.db.get(models.UserAccount, world.user_id(a))
    session, _ = auth.create_session(world.db, user)
    world.db.commit()
    world.extra.setdefault("tokens", {})[b] = auth.issue_access_token(user.id, session.id)


@given(step("系統中有以下稽核紀錄："))
def given_audit_logs(world, datatable):
    for row in rows(datatable):
        actor_email = row.get("actor") or ""
        actor_type = code(L.ACTOR_TYPE, row.get("actor_type", "")) or ("user" if actor_email else "system")
        target_type = code(L.TARGET_TYPE, row["target_type"])
        log = models.AuditLog(
            actor_type=actor_type,
            actor_id=world.user_id(actor_email) if actor_email else None,
            action=code(L.AUDIT_ACTION, row["action"]),
            target_type=target_type,
            target_id=resolve_target(world, target_type, row["target"]),
            result=code(L.POST_STATUS, row.get("result", "")),
            occurred_at=tw_time(row["occurred_at"]),
        )
        if row.get("event_seq"):
            log.event_seq = int(row["event_seq"])
        world.db.add(log)
        world.db.flush()
    world.db.commit()


def resolve_target(world, target_type: str, raw: str) -> int:
    raw = raw.strip()
    if target_type == "post":
        if raw not in world.posts and not raw.isdigit():
            world.posts[raw] = 900_000 + len(world.posts)  # 只出現在稽核紀錄裡的貼文
        return world.post_id(raw)
    if target_type == "user_account":
        return world.user_id(raw)
    return world.account_id(raw)


# ---------- Given：模擬平台 ----------


@given(step('平台帳號 "X" 的發佈結果為成功，平台貼文連結為 "X"'))
def given_publish_succeeds(world, a, b):
    mock_of(world, a).succeed(a, b)


@given(step('平台帳號 "X" 的發佈結果為失敗，失敗原因為 "X"'))
def given_publish_fails(world, a, b):
    mock_of(world, a).fail(a, FailureReason(code(L.FAILURE_REASON, b)))


@given(step('平台帳號 "X" 的發佈結果為授權失效'))
def given_publish_auth_invalid(world, a):
    mock_of(world, a).fail(a, FailureReason.AUTH_INVALID)


@given(step('平台帳號 "X" 的發佈逾時'))
def given_publish_timeout(world, a):
    mock_of(world, a).raise_error(a, TimeoutError())


@given(step('平台帳號 "X" 的發佈尚未完成'))
def given_publish_pending(world, a, monkeypatch):
    """背景發佈還在進行：這個平台帳號的紀錄停在待發佈，其他平台照常完成。"""
    if not world.hanging:
        original_attempt, original_record = engine.attempt, engine.record

        def name_of(job) -> str:
            return crypto.decrypt_credential(job.credential_encrypted)["account_name"]

        async def attempt(job, request_ref=None):
            if name_of(job) in world.hanging:
                return Failed(FailureReason.OTHER, "still running")
            return await original_attempt(job, request_ref)

        async def record(job, outcome, succeeded, failed):
            if name_of(job) in world.hanging:
                return
            await original_record(job, outcome, succeeded, failed)

        monkeypatch.setattr(engine, "attempt", attempt)
        monkeypatch.setattr(engine, "record", record)
    world.hanging.add(a)


@given(step('平台帳號 "X" 查詢發佈結果為已發佈，平台貼文連結為 "X"'))
def given_check_published(world, a, b):
    mock_of(world, a).set_check(a, CheckResult(CheckStatus.PUBLISHED, published=Published(post_url=b)))


@given(step('平台帳號 "X" 查詢發佈結果為未發佈'))
def given_check_ready(world, a):
    mock_of(world, a).set_check(a, CheckResult(CheckStatus.READY))


@given(step('平台帳號 "X" 無法查詢發佈結果'))
def given_check_unknown(world, a):
    mock_of(world, a).set_check(a, CheckResult(CheckStatus.UNKNOWN))


@given(step('Discord Webhook "X" 的驗證結果為(?P<result>有效|無效|暫時無法驗證)'))
def given_webhook(world, a, result):
    outcomes = world.extra.setdefault("webhooks", {})
    outcomes[a] = result
    discord = world.mocks[Platform.DISCORD]

    async def verify(url):
        outcome = outcomes.get(url, "有效")
        if outcome == "無效":
            raise WebhookInvalid()
        if outcome == "暫時無法驗證":
            raise VerificationUnavailable()
        return {"webhook_id": "1", "guild_id": "1", "channel_id": "1"}

    discord.verify_webhook = verify


# ---------- When：系統 ----------


@when(step("系統執行排程發佈"))
def when_publish_due(world):
    world.request(None, "POST", "/internal/publish-due", headers={"X-Cron-Secret": "bdd-cron-secret"})


@when(step("系統執行發佈逾時恢復檢查"))
def when_recovery(world):
    from app.m5_publishing import recovery

    world.mark()
    asyncio.run(recovery.recover_stale(allow_auto_retry=True))


@when(step("系統重新啟動"))
def when_restart(world):
    from app.m5_publishing import recovery

    world.mark()
    asyncio.run(recovery.recover_stale(allow_auto_retry=False))


@when(step('"X" 將貼文 "X" 的目標平台帳號設定為：'))
def when_set_targets(world, a, b, datatable):
    def account_or_missing(name):
        try:
            return world.account_id(name)
        except KeyError:
            return 999_999  # 例子裡「未連結的平台帳號」

    ids = [account_or_missing(row["account_name"]) for row in rows(datatable)]
    world.request(a, "PUT", f"/posts/{world.post_id(b)}/targets", json={"platform_account_ids": ids})


@when(step('"X" 以密碼 "X" 登入'))
def when_login(world, a, b):
    world.request(None, "POST", "/auth/login", json={"email": a, "password": b})


@when(step('"X" 查看平台帳號列表'))
def when_list_accounts(world, a):
    world.request(a, "GET", "/platform-accounts")


@when(step('"X" 查詢貼文列表'))
def when_list_posts(world, a):
    world.request(a, "GET", "/posts")


@when(step('以登入憑證 "X" 查詢貼文列表'))
def when_list_posts_with_token(world, a):
    token = world.extra["tokens"][a]
    world.request(None, "GET", "/posts", headers={"Authorization": f"Bearer {token}"})


# ---------- Then：結果 ----------


@then(step("操作成功"))
def then_success(world):
    response = world.response
    assert response is not None and 200 <= response.status_code < 300, (
        f"預期成功，實際 {response.status_code}：{response.text[:300]}"
    )


@then(step("操作失敗"))
def then_failure(world):
    response = world.response
    # 操作失敗＝API 回傳規格定義的錯誤：4xx，或 503 VERIFICATION_UNAVAILABLE（暫時無法驗證）；500 不算
    assert response is not None and (400 <= response.status_code < 500 or response.status_code == 503), (
        f"預期失敗，實際 {response.status_code}：{response.text[:300]}"
    )


@then(step('貼文 "X" 的狀態為 "X"'))
def then_post_status(world, a, b):
    world.db.expire_all()
    assert world.db.get(models.Post, world.post_id(a)).status == code(L.POST_STATUS, b)


@then(step('貼文 "X" 的排程時間為 "X"'))
def then_scheduled_at(world, a, b):
    world.db.expire_all()
    assert world.db.get(models.Post, world.post_id(a)).scheduled_at == tw_time(b)


@then(step('貼文 "X" 的排程時間為空'))
def then_scheduled_at_empty(world, a):
    world.db.expire_all()
    assert world.db.get(models.Post, world.post_id(a)).scheduled_at is None


@then(step('貼文 "X" 的資料為：'))
def then_post_data(world, a, datatable):
    world.db.expire_all()
    post = world.db.get(models.Post, world.post_id(a))
    [row] = rows(datatable)
    for column, raw in row.items():
        if column == "id":
            assert post.id == world.post_id(raw)
        elif column == "creator":
            assert post.creator_id == world.user_id(raw)
        else:
            check(column, getattr(post, column), raw, f"貼文 {a}")


@then(step('貼文 "X" 的目標平台帳號為：'))
def then_targets(world, a, datatable):
    world.db.expire_all()
    actual = {
        (account.platform, account.account_name)
        for account in world.db.scalars(
            select(models.PlatformAccount)
            .join(models.PostTarget)
            .where(models.PostTarget.post_id == world.post_id(a))
        )
    }
    expected = {(code(L.PLATFORM, r.get("platform", "")) or "", r["account_name"]) for r in rows(datatable)}
    if all(platform == "" for platform, _ in expected):
        actual = {("", name) for _, name in actual}
    assert actual == expected


def record_rows(world, alias: str) -> dict[str, models.PublishRecord]:
    world.db.expire_all()
    records = world.db.scalars(
        select(models.PublishRecord).where(models.PublishRecord.post_id == world.post_id(alias))
    )
    names = {account_id: name for name, account_id in world.accounts.items()}
    return {names.get(r.platform_account_id, str(r.platform_account_id)): r for r in records}


RECORD_FIELDS = {"post_url": "platform_post_url"}


def check_record(record: models.PublishRecord, row: dict[str, str], name: str) -> None:
    for column, raw in row.items():
        if column == "account_name":
            continue
        check(column, getattr(record, RECORD_FIELDS.get(column, column)), raw, f"{name} 的發佈紀錄")


@then(step('貼文 "X" 的發佈紀錄為：'))
def then_records_exactly(world, a, datatable):
    records = record_rows(world, a)
    expected = rows(datatable)
    assert sorted(records) == sorted(row["account_name"] for row in expected), f"發佈紀錄：{sorted(records)}"
    for row in expected:
        check_record(records[row["account_name"]], row, row["account_name"])


@then(step('貼文 "X" 的發佈紀錄包含：'))
def then_records_include(world, a, datatable):
    records = record_rows(world, a)
    for row in rows(datatable):
        assert row["account_name"] in records, f"沒有 {row['account_name']} 的發佈紀錄"
        check_record(records[row["account_name"]], row, row["account_name"])


@then(step('平台帳號 "X" 收到 (?P<n>\\d+) 則貼文'))
def then_received(world, a, n):
    received = [name for name, _ in mock_of(world, a).received if name == a]
    assert len(received) == int(n), f"{a} 收到 {len(received)} 則"


def history_matches(world, history, account_name: str, post_alias: str | None, row: dict[str, str]) -> bool:
    try:
        for column, raw in row.items():
            if column == "post":
                continue
            if column == "account_name":
                assert account_name == raw
            elif column == "actor":
                assert history.actor_id == (world.user_id(raw) if raw else None)
            else:
                check(column, getattr(history, column), raw, "變更歷程")
        return True
    except AssertionError:
        return False


def all_history(world):
    world.db.expire_all()
    names = {account_id: name for name, account_id in world.accounts.items()}
    posts = {post_id: alias for alias, post_id in world.posts.items()}
    rows_ = world.db.execute(
        select(models.PublishRecordHistory, models.PublishRecord)
        .join(models.PublishRecord)
        .order_by(models.PublishRecordHistory.id)
    )
    return [(h, names.get(r.platform_account_id), posts.get(r.post_id, str(r.post_id))) for h, r in rows_]


@then(step("發佈紀錄變更歷程(?:包含|中有以下紀錄)："))
def then_history_includes(world, datatable):
    history = all_history(world)
    for row in rows(datatable):
        candidates = [
            h
            for h, name, alias in history
            if (not row.get("post") or alias == row["post"]) and history_matches(world, h, name, alias, row)
        ]
        existing = [(alias, name, h.from_status, h.to_status, h.reason) for h, name, alias in history]
        assert candidates, f"變更歷程沒有 {row}；現有：{existing}"


def check_audit(world, log: models.AuditLog, row: dict[str, str]) -> None:
    for column, raw in row.items():
        if column == "actor":
            assert log.actor_id == (world.user_id(raw) if raw else None), f"稽核的操作者：{log.actor_id}"
        elif column == "target":
            assert log.target_id == resolve_target(world, log.target_type, raw), (
                f"稽核的對象：{log.target_id}"
            )
        elif column in ("scheduled_by", "post_creator"):
            attr = "scheduled_by" if column == "scheduled_by" else "post_creator_id"
            assert getattr(log, attr) == (world.user_id(raw) if raw else None)
        elif column == "related_post":
            assert log.related_post_id == (world.post_id(raw) if raw else None)
        else:
            check(column, getattr(log, column), raw, "稽核紀錄")


@then(step("系統新增一筆稽核紀錄："))
def then_new_audit(world, datatable):
    new = world.new_rows("audit")
    [row] = rows(datatable)
    assert len(new) == 1, f"預期新增 1 筆稽核紀錄，實際 {[log.action for log in new]}"
    check_audit(world, new[0], row)
    world.extra["last_audit"] = new[0].id


@then(step("系統沒有新增稽核紀錄"))
def then_no_new_audit(world):
    assert [log.action for log in world.new_rows("audit")] == []


@then(step("稽核紀錄包含："))
def then_audits_include(world, datatable):
    world.db.expire_all()
    logs = list(world.db.scalars(select(models.AuditLog).order_by(models.AuditLog.id)))

    def ok(log, row):
        try:
            check_audit(world, log, row)
            return True
        except (AssertionError, KeyError):
            return False

    for row in rows(datatable):
        assert any(ok(log, row) for log in logs), f"稽核紀錄沒有 {row}"


@then(step("該筆稽核紀錄的各目標執行結果為："))
def then_audit_target_results(world, datatable):
    world.db.expire_all()
    log_id = world.extra.get("last_audit") or max(log.id for log in world.new_rows("audit"))
    log = world.db.get(models.AuditLog, log_id)
    names = {account_id: name for name, account_id in world.accounts.items()}
    actual = {names[r.platform_account_id]: r for r in log.target_results}
    expected = rows(datatable)
    assert sorted(actual) == sorted(row["account_name"] for row in expected)
    for row in expected:
        result = actual[row["account_name"]]
        for column, raw in row.items():
            if column != "account_name":
                check(column, getattr(result, column), raw, f"{row['account_name']} 的執行結果")


@then(step('平台帳號 "X" 的資料為：'))
def then_account_data(world, a, datatable):
    world.db.expire_all()
    account = world.db.get(models.PlatformAccount, world.account_id(a))
    [row] = rows(datatable)
    for column, raw in row.items():
        if column == "linked_by":
            assert account.linked_by == world.user_id(raw)
        elif column == "auth_status":
            # 授權狀態採有效狀態：到期時間已過即視為失效（BR-09），與 API 顯示一致
            from app.core.platforms import effective_auth_status

            check(column, effective_auth_status(account, clock.now()), raw, f"平台帳號 {a}")
        else:
            check(column, getattr(account, column), raw, f"平台帳號 {a}")


@then(step('使用者帳號 "X" 的資料為：'))
def then_user_data(world, a, datatable):
    world.db.expire_all()
    user = world.db.scalar(select(models.UserAccount).where(models.UserAccount.email == a.strip().lower()))
    assert user is not None, f"沒有使用者帳號 {a}"
    [row] = rows(datatable)
    for column, raw in row.items():
        expected = raw.strip().lower() if column == "email" else raw
        check(column, getattr(user, column), expected, f"使用者帳號 {a}")


@then(step('使用者帳號 "X" 的狀態為 "X"'))
def then_user_status(world, a, b):
    world.db.expire_all()
    assert world.db.get(models.UserAccount, world.user_id(a)).status == code(L.USER_STATUS, b)


@then(step('使用者帳號 "X" 的連續登入失敗次數為 (?P<n>\\d+)'))
def then_failed_count(world, a, n):
    world.db.expire_all()
    assert world.db.get(models.UserAccount, world.user_id(a)).failed_login_count == int(n)


@then(step('使用者帳號 "X" 的鎖定到期時間為 "X"'))
def then_locked_until(world, a, b):
    world.db.expire_all()
    assert world.db.get(models.UserAccount, world.user_id(a)).locked_until == tw_time(b)


@then(step('使用者帳號 "X" 的鎖定到期時間為空'))
def then_not_locked(world, a):
    world.db.expire_all()
    assert world.db.get(models.UserAccount, world.user_id(a)).locked_until is None


# ---------- Then：查詢結果（回應內容） ----------


def items(world) -> list[dict]:
    body = world.response.json()
    if isinstance(body, dict) and "items" in body:
        return body["items"]
    return body if isinstance(body, list) else [body]


def item_value(world, item: dict, column: str) -> Any:
    account = item.get("platform_account") or {}
    getters = {
        "platform": lambda: item.get("platform") or account.get("platform"),
        "account_name": lambda: item.get("account_name") or account.get("account_name"),
        "auth_status": lambda: item.get("auth_status") or account.get("auth_status"),
        "post_url": lambda: item.get("platform_post_url"),
        "content": lambda: item.get("content", item.get("text")),
        "actor": lambda: (item.get("actor") or {}).get("email"),
        "user": lambda: (item.get("account") or {}).get("email"),
        "record_kind": lambda: item.get("kind"),
        "action": lambda: item.get("action") or item.get("event_type"),
        "target_type": lambda: (item.get("target") or {}).get("type"),
        "total_count": lambda: item.get("total"),
    }
    return getters[column]() if column in getters else item.get(column)


def item_matches(world, item: dict, row: dict[str, str]) -> bool:
    try:
        for column, raw in row.items():
            actual = item_value(world, item, column)
            if column == "id":
                assert item["id"] == world.post_id(raw)
            elif column == "creator":
                assert item["creator"]["id"] == world.user_id(raw)
            elif column == "target":
                target = item.get("target") or {}
                if not raw:
                    assert not target  # 登入安全事件等沒有操作對象
                else:
                    assert target.get("id") == resolve_target(world, target.get("type"), raw)
            elif column in ("actor", "user"):
                assert (actual or "") == raw.strip().lower()
            else:
                check(column, actual, raw, "查詢結果")
        return True
    except (AssertionError, KeyError, TypeError):
        return False


@then(step("查詢結果為："))
def then_result_exactly(world, datatable):
    actual, expected = items(world), rows(datatable)
    assert len(actual) == len(expected), f"查詢結果 {len(actual)} 筆，預期 {len(expected)} 筆：{actual}"
    for row in expected:
        assert any(item_matches(world, item, row) for item in actual), f"查詢結果沒有 {row}：{actual}"


@then(step("查詢結果包含："))
def then_result_includes(world, datatable):
    actual = items(world)
    for row in rows(datatable):
        assert any(item_matches(world, item, row) for item in actual), f"查詢結果沒有 {row}：{actual}"


@then(step("查詢結果依序為："))
def then_result_in_order(world, datatable):
    actual, expected = items(world), rows(datatable)
    assert len(actual) == len(expected), f"查詢結果 {len(actual)} 筆，預期 {len(expected)} 筆"
    for index, (item, row) in enumerate(zip(actual, expected, strict=True)):
        assert item_matches(world, item, row), f"第 {index + 1} 筆不符：{item} ≠ {row}"


@then(step('查詢結果不包含欄位 "X"'))
def then_result_without_field(world, a):
    assert all(a not in item for item in items(world))
    # 不只欄位名稱：任何平台帳號解密後的憑證值都不可以出現在回應裡（NFR-02）
    world.db.expire_all()
    for account in world.db.scalars(select(models.PlatformAccount)):
        for value in crypto.decrypt_credential(account.credential_encrypted).values():
            if isinstance(value, str) and value != account.account_name:
                assert value not in world.response.text, f"回應中出現 {account.account_name} 的憑證"


@then(step("查詢結果共 (?P<n>\\d+) 筆"))
def then_result_count(world, n):
    assert len(items(world)) == int(n)


@then(step("查詢結果的分頁資訊為："))
def then_page_info(world, datatable):
    body = world.response.json()
    [row] = rows(datatable)
    for column, raw in row.items():
        actual = body["total"] if column == "total_count" else body[column]
        expected = {"true": True, "false": False}.get(raw.lower(), raw)
        assert (actual == int(expected)) if isinstance(expected, str) else actual is expected, (
            f"分頁 {column}：實際 {actual}，預期 {raw}"
        )


# ---------- 其他共用句型 ----------


@given(step('平台帳號 "X" 的發佈結果為失敗，平台原始錯誤訊息為 "X"'))
def given_publish_fails_with_message(world, a, b):
    mock_of(world, a).fail(a, FailureReason.PLATFORM_UNAVAILABLE, b)


@given(step('貼文 "X" 已被刪除'))
def given_post_deleted(world, a):
    world.db.get(models.Post, world.post_id(a)).deleted_at = clock.now()
    world.db.commit()


@then(step('使用者帳號 "X" 的角色為 "X"'))
def then_user_role(world, a, b):
    world.db.expire_all()
    assert world.db.get(models.UserAccount, world.user_id(a)).role == code(L.ROLE, b)


@then(step('使用者帳號 "X" 保存的密碼值不為 "X"'))
def then_password_not_plain(world, a, b):
    world.db.expire_all()
    stored = world.db.get(models.UserAccount, world.user_id(a)).password_hash
    assert stored != b and b not in stored


@then(step('貼文 "X" 的內容為 "X"'))
def then_post_content(world, a, b):
    world.db.expire_all()
    assert world.db.get(models.Post, world.post_id(a)).content == b


@then(step('貼文 "X" 的排程設定者為 "X"'))
def then_scheduled_by(world, a, b):
    world.db.expire_all()
    assert world.db.get(models.Post, world.post_id(a)).scheduled_by == world.user_id(b)


@then(step('貼文 "X" 排程時間的儲存值為 "X"'))
def then_scheduled_at_stored(world, a, b):
    world.db.expire_all()
    stored = world.db.get(models.Post, world.post_id(a)).scheduled_at
    assert stored == datetime.fromisoformat(b.replace("Z", "+00:00"))


@then(step('貼文 "X" 存在'))
def then_post_exists(world, a):
    world.db.expire_all()
    post = world.db.get(models.Post, world.post_id(a))
    assert post is not None and post.deleted_at is None


@then(step('貼文 "X" 不存在'))
def then_post_missing(world, a):
    world.db.expire_all()
    post = world.db.get(models.Post, world.post_id(a))
    assert post is None or post.deleted_at is not None


@then(step("系統新增一則貼文："))
def then_new_post(world, datatable):
    new = world.new_rows("post")
    [row] = rows(datatable)
    assert len(new) == 1, f"預期新增 1 則貼文，實際 {len(new)}"
    post = new[0]
    for column, raw in row.items():
        if column == "creator":
            assert post.creator_id == world.user_id(raw)
        else:
            check(column, getattr(post, column), raw, "新貼文")


@then(step("新草稿沒有目標平台帳號"))
def then_new_draft_without_targets(world):
    world.db.expire_all()
    targets = world.db.scalars(
        select(models.PostTarget).where(models.PostTarget.post_id == world.post_id("新草稿"))
    ).all()
    assert targets == []


@then(step('貼文 "X" 在平台帳號 "X" 的平台原始錯誤訊息不包含 "X"'))
def then_error_message_without(world, a, b, c):
    record = record_rows(world, a)[b]
    assert record.platform_error_message is not None and c not in record.platform_error_message


@then(step("查詢結果為空"))
def then_result_empty(world):
    assert items(world) == []


@then(step('系統中沒有帳號名稱為 "X" 的平台帳號'))
def then_no_account_named(world, a):
    world.db.expire_all()
    assert (
        world.db.scalar(select(models.PlatformAccount.id).where(models.PlatformAccount.account_name == a))
        is None
    )


@then(step("系統沒有新增平台授權事件"))
def then_no_auth_event(world):
    assert world.new_rows("auth_event") == []


@then(step("新草稿沒有發佈紀錄"))
def then_new_draft_without_records(world):
    world.db.expire_all()
    records = world.db.scalars(
        select(models.PublishRecord).where(models.PublishRecord.post_id == world.post_id("新草稿"))
    ).all()
    assert records == []


@then(step("查詢結果的貼文已刪除標示為 (?P<flag>true|false)"))
def then_post_deleted_flag(world, flag):
    assert world.response.json()["post_deleted"] is (flag == "true")
