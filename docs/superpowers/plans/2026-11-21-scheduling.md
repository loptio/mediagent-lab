# 排程發佈、重試與逾時恢復 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 貼文可以設定排程、取消排程，時間到由系統自動發佈；失敗的平台可以重試；服務中斷留下的「發佈中」貼文會被自動恢復。

**Architecture:** M4 負責排程的設定與取消、已排程貼文改目標時同步發佈紀錄。M5 的 `engine.run_post` 仍是唯一的執行入口，加上執行模式（立即、排程、重試）決定變更原因與稽核內容。排程掃描與逾時恢復各是一個模組，由三種方式觸發：服務內每分鐘的迴圈、服務啟動時、帶 `X-Cron-Secret` 的內部端點（foundation-plan D-07）。重複觸發靠 `FOR UPDATE SKIP LOCKED` 認領貼文、靠 `attempt_started_at` 認領發佈紀錄（D-01、D-02）。

**Tech Stack:** Python 3.12、FastAPI、SQLAlchemy 2（同步 session、psycopg 3）、PostgreSQL 17、pytest、MockAdapter。

**Spec:** `docs/requirements.md`（BR-10～BR-16、BR-18、BR-24～BR-34）、`docs/api-design.md` §3.4～3.5、`docs/architecture.md` §6、`docs/foundation-plan.md`（D-01、D-02、D-03、D-07）、`spec/features/` 的 `設定排程`、`取消排程`、`設定目標平台帳號`、`執行排程發佈`、`重試發佈`、`發佈逾時恢復`。

## Global Constraints

- 所有使用者看得到的文字用繁體中文（台灣用語）；欄位格式錯誤一律 `400 VALIDATION_ERROR`（不是 422）。
- 錯誤格式 `{code, message, detail?, request_id}`；新增的錯誤碼同步更新 `docs/api-design.md` §4。
- 排程時間以台灣時間輸入、以 UTC 儲存；沒有時區的輸入視為台灣時間（UTC+8，無日光節約）。
- 排程時間必須晚於現在，且分鐘為 5 的倍數、秒與微秒為 0（BR-10）。
- 單次平台呼叫 30 秒、單筆發佈總時限 180 秒、逾時恢復門檻 10 分鐘（D-02）；服務內排程迴圈每 60 秒一次。
- 內部端點只接受與 `CRON_SECRET` 相同的 `X-Cron-Secret`（固定時間比較）；`CRON_SECRET` 沒設定時一律 `401 UNAUTHENTICATED`。內部端點不列入公開文件。
- 服務啟動時的恢復檢查不得呼叫 `begin` 或 `finalize`（BR-33）。
- 只改變真正改變狀態的紀錄；變更歷程只在狀態改變時寫入。
- Log 不得含憑證、Token、Webhook 網址或 `X-Cron-Secret`。
- 不新增套件；ruff line-length 110。

## Review Focus

1. 服務內迴圈與外部定時任務在同一分鐘觸發：同一則到期貼文只能被發佈一次（Task 2，`test_two_triggers_publish_a_due_post_once`）。
2. 排程時間到的同時使用者取消排程或拿掉目標：已取消的紀錄不可被送出（Task 2，`test_cancelled_target_of_due_post_is_not_sent`）。
3. 發佈逾時後馬上按重試：上一次嘗試的時間戳記不可讓重試被當成「別人正在處理」而什麼都不做（Task 3，`test_timeout_failure_can_be_retried_right_away`）。
4. 服務在發佈途中重新啟動：啟動時的檢查絕不重新發文，只確認或記為逾時（Task 4，`test_startup_recovery_never_resends`）。
5. 另一個觸發正在處理的紀錄（`attempt_started_at` 未滿 180 秒）不可被恢復流程接手（Task 4，`test_record_in_progress_is_not_taken_over`）。

---

### Task 1: 設定排程、取消排程、已排程貼文改目標

**Files:**
- Modify: `app/core/publish_records.py`（`ensure_pending`）
- Modify: `app/m4_scheduling/service.py`、`router.py`、`schemas.py`、`repository.py`
- Modify: `docs/api-design.md`（§4 錯誤碼表，若有新增）
- Test: `tests/api/test_schedule.py`

**Interfaces:**
- Produces: `publish_records.ensure_pending(db, *, post_id, platform_account_id, actor, reason, revived_reason=None) -> PublishRecord`。已取消或失敗的紀錄改回待發佈時，變更歷程用 `revived_reason or reason`，並清空 `failure_reason`、`platform_error_message`、`attempt_started_at`、`platform_request_ref`。
- Produces: `PUT /api/v1/posts/{id}/schedule`，body `{"scheduled_at": datetime}` → 200 貼文（與 `GET /posts/{id}` 相同的 `PostOut`）。
- Produces: `DELETE /api/v1/posts/{id}/schedule` → 200 貼文。
- Produces: `m4_scheduling.service.to_utc_schedule_time(value: datetime) -> datetime`（沒有時區 → 台灣時間；結果為 UTC）。
- 變更原因：新建紀錄 `SCHEDULE_SET`；重新排程救回的紀錄 `RESCHEDULED`；取消排程 `SCHEDULE_CANCELLED`；已排程貼文改目標時新增 `TARGET_ADDED`、拿掉與加回 `TARGET_MODIFIED`。稽核：`POST_SCHEDULE`（設定與修改時間都寫）、`SCHEDULE_CANCEL`。

- [ ] **Step 1: 寫失敗的測試** `tests/api/test_schedule.py`，固定時鐘為台灣時間 2026-10-06 11:00：
  - `test_publisher_schedules_draft`：排程 `"2026-10-06T12:00:00+08:00"` → 200；`status == "SCHEDULED"`、`scheduled_at == "2026-10-06T04:00:00Z"`、`scheduled_by` 為發佈者；每個目標一筆 `PENDING`；歷程 `(None, "PENDING", "user", "SCHEDULE_SET")`；一筆 `POST_SCHEDULE` 稽核。
  - `test_schedule_time_without_timezone_is_taiwan_time`：`"2026-10-06T12:00:00"` 存成 04:00Z。
  - `test_schedule_time_must_be_future_and_aligned`（參數化）：等於現在、早於現在 → `422 SCHEDULE_TIME_NOT_FUTURE`；12:03、12:05:30 → `422 SCHEDULE_TIME_NOT_ALIGNED`；失敗時 `scheduled_by` 與狀態不變。
  - `test_writer_schedule_permissions`：撰稿者為草稿排程 → 403；改自己已排程貼文的時間 → 200 且 `scheduled_by` 變成撰稿者；改他人已排程貼文 → 403。
  - `test_only_draft_or_scheduled_can_be_scheduled`：已發佈貼文 → `409 POST_NOT_SCHEDULABLE`。
  - `test_schedule_checks_publish_rules`：沒有目標 → `422 NO_TARGET`；目標含 Threads 且 501 字 → `422 CONTENT_TOO_LONG`。
  - `test_cancel_schedule`：狀態回 `DRAFT`、`scheduled_at` 為 null、紀錄 `CANCELLED`、歷程 `SCHEDULE_CANCELLED`、稽核 `SCHEDULE_CANCEL`；撰稿者取消他人貼文 → 403；取消草稿 → `409 POST_NOT_SCHEDULED`。
  - `test_reschedule_after_cancel_reuses_records`：取消後把目標從 Threads＋Discord 改成 Discord＋Instagram 再排程 → Threads 維持 `CANCELLED`、Discord 同一筆紀錄 `PENDING`（歷程 `RESCHEDULED`）、Instagram 新紀錄（歷程 `SCHEDULE_SET`）。
  - `test_changing_targets_of_scheduled_post_syncs_records`：新增 → `PENDING`（`TARGET_ADDED`）；拿掉 → `CANCELLED`（`TARGET_MODIFIED`）；保留的不變、沒有新歷程；再加回 → 同一筆改回 `PENDING`（`TARGET_MODIFIED`）；狀態與排程時間不變。
  - `test_scheduled_post_target_rules`：已排程貼文清空目標 → `422 SCHEDULED_POST_REQUIRES_TARGET`；新目標字數上限不足 → `422 CONTENT_TOO_LONG`；失敗時目標與紀錄不變。
- [ ] **Step 2: 執行，確認失敗** `.venv/bin/python -m pytest -q tests/api/test_schedule.py` → Expected: FAIL（405／404，端點不存在）。
- [ ] **Step 3: 實作** `ensure_pending` 的 `revived_reason`；`set_schedule`、`cancel_schedule`；`set_targets` 對已排程貼文先跑 `publish_rules.check`（以新目標），再同步紀錄。檢查順序：找不到 → 權限 → 狀態 → 時間 → 發佈限制。
- [ ] **Step 4: 執行，確認通過** 同上 → Expected: PASS；全部測試通過。
- [ ] **Step 5: Commit** `feat: 設定排程、取消排程，已排程貼文改目標時同步發佈紀錄`

### Task 2: 排程時間到自動發佈

**Files:**
- Modify: `app/m5_publishing/engine.py`（執行模式、紀錄認領）
- Create: `app/m5_publishing/scheduler.py`、`app/m5_publishing/internal_router.py`
- Modify: `app/main.py`（lifespan 啟動排程迴圈、掛上內部 router）、`app/core/config.py`、`.env.example`、`tests/conftest.py`
- Test: `tests/api/test_scheduled_publish.py`

**Interfaces:**
- Produces: `engine.RunMode`（`PUBLISH`、`SCHEDULED`、`RETRY`）；`engine.run_post(post_id: int, actor_id: int | None = None, mode: RunMode = RunMode.PUBLISH) -> None`。
- `SCHEDULED`：歷程 `PUBLISH_SUCCEEDED/FAILED`、操作者系統；稽核 `POST_PUBLISH` 操作者系統，`scheduled_by`、`post_creator_id` 填入；`scheduled_at` 保留。`PUBLISH` 行為不變（完成後清空 `scheduled_at`，BR-29）。
- 紀錄認領：`_load_jobs` 只取 `PENDING` 且 `attempt_started_at` 為空或早於 `publish_record_limit_seconds` 的紀錄，並更新 `attempt_started_at`。
- Produces: `scheduler.claim_due_posts() -> list[int]`：`SKIP LOCKED` 認領 `SCHEDULED`、`scheduled_at <= now`、未刪除的貼文 → `PUBLISHING`、`publishing_started_at = now`；授權失效（含已過期）目標的待發佈紀錄直接記為 `FAILED / AUTH_EXPIRED`（歷程 `PUBLISH_FAILED`，系統），不送出（BR-31）。
- Produces: `async scheduler.tick(allow_auto_retry: bool = True) -> list[asyncio.Task]`（Task 4 加入恢復）；`async scheduler.run_loop() -> None`。
- Produces: `POST /api/v1/internal/publish-due`（`X-Cron-Secret`）→ `{"started": n}`，背景執行。
- Settings：`cron_secret: str = ""`、`scheduler_enabled: bool = True`、`scheduler_interval_seconds: int = 60`、`publish_recovery_minutes: int = 10`。測試環境 `SCHEDULER_ENABLED=0`。

- [ ] **Step 1: 寫失敗的測試**：
  - `test_due_post_is_published_by_the_system`：排程貼文、時鐘到排程時間、呼叫端點 → `{"started": 1}`；`PUBLISHED`；紀錄 `SUCCEEDED`；歷程 `(PENDING, SUCCEEDED, "system", "PUBLISH_SUCCEEDED")`；稽核 `POST_PUBLISH` 的 `actor_type == "system"`、`actor_id is None`、`scheduled_by`、`post_creator_id`、`result`、各目標結果；`content_summary` 是發佈當下的文字；`scheduled_at` 保留。
  - `test_post_not_yet_due_and_drafts_are_not_published`：早一分鐘、草稿 → `{"started": 0}`，沒有任何平台收到貼文。
  - `test_auth_invalid_target_fails_without_sending`：排程後 Instagram 授權到期、Threads 標示失效 → 兩筆 `FAILED / AUTH_EXPIRED`、平台收到 0 則；Discord 成功；`PARTIALLY_FAILED`；授權狀態不變。
  - `test_disabled_creator_post_still_publishes`。
  - `test_cancelled_target_of_due_post_is_not_sent`：排程後拿掉 Threads → 到期只送 Discord。
  - `test_two_triggers_publish_a_due_post_once`：連續呼叫端點兩次，第二次 `{"started": 0}`，每個平台只收到 1 則；直接呼叫 `claim_due_posts()` 第二次回傳 `[]`。
  - `test_publish_due_requires_cron_secret`：沒帶、錯的 → `401 UNAUTHENTICATED`；`CRON_SECRET` 未設定時連空字串也 401。
  - `test_scheduler_tick_publishes_due_posts`：`asyncio.run` 執行 `tick()` 並等待回傳的工作 → `PUBLISHED`。
- [ ] **Step 2: 執行，確認失敗** → Expected: FAIL（404、匯入錯誤）。
- [ ] **Step 3: 實作** 引擎模式、認領、排程模組、內部端點、lifespan（`scheduler_enabled` 為真才啟動；迴圈中的例外記錄類別名稱後繼續）。
- [ ] **Step 4: 執行，確認通過** → Expected: PASS；全部測試通過。
- [ ] **Step 5: Commit** `feat: 排程時間到由系統自動發佈（服務內迴圈與內部端點）`

### Task 3: 重試發佈

**Files:**
- Modify: `app/m5_publishing/service.py`、`router.py`、`schemas.py`、`engine.py`
- Test: `tests/api/test_retry.py`

**Interfaces:**
- Consumes: Task 1 的 `ensure_pending`（救回時清空 `attempt_started_at`），Task 2 的 `RunMode.RETRY`。
- Produces: `POST /posts/{id}/publish-jobs` 接受 `{"type": "retry"}` → 202，`records` 只列這次重試的紀錄。
- `service.accept_retry(db, user, post_id) -> PublishJobAccepted`：狀態不是 `PARTIALLY_FAILED`／`FAILED` → `409 POST_NOT_RETRYABLE`；可重試 = `FAILED` 且平台帳號未移除、授權有效；沒有 → `422 NOTHING_TO_RETRY`，`detail.hints` 為 `[{platform_account_id, account_name, reason}]`，`reason` 是 `AUTH_INVALID_SKIPPED` 或 `REMOVED_SKIPPED`，不寫稽核、狀態不變。受理時歷程 `RETRY_STARTED`（使用者），貼文 `PUBLISHING`、`publishing_started_at = now`。
- `RETRY` 模式：歷程 `RETRY_SUCCEEDED/FAILED`（系統）；稽核 `PUBLISH_RETRY`（使用者）列出全部未取消的紀錄，這次沒有執行的標 `NOT_RETRIED` 與 `skip_reason`（`ALREADY_SUCCEEDED`、`AUTH_INVALID_SKIPPED`、`REMOVED_SKIPPED`）。

- [ ] **Step 1: 寫失敗的測試**：
  - `test_retry_republishes_only_failed_targets`：先立即發佈且 Instagram 失敗 → 重試 → 只有 Instagram 再收到 1 則；`PUBLISHED`；歷程 `(FAILED, PENDING, "user", "RETRY_STARTED")`、`(PENDING, SUCCEEDED, "system", "RETRY_SUCCEEDED")`；新增 `PUBLISH_RETRY` 稽核，其他兩個 `NOT_RETRIED / ALREADY_SUCCEEDED`；原本的 `POST_PUBLISH` 稽核不變。
  - `test_retry_still_failing_is_partially_failed`。
  - `test_retry_requires_failed_post_and_publisher`：草稿 → 409；撰稿者 → 403。
  - `test_nothing_to_retry_explains_why`：失敗目標一個授權到期、一個已移除 → 422 與兩筆提示；狀態 `FAILED`；沒有新稽核。
  - `test_retry_skips_auth_invalid_and_removed_targets`：稽核各目標結果與 `skip_reason`。
  - `test_timeout_failure_can_be_retried_right_away`：紀錄 `FAILED / TIMEOUT` 且 `attempt_started_at` 為 5 秒前 → 重試後平台收到 1 則。
  - `test_retry_auth_invalid_marks_account_invalid`。
- [ ] **Step 2: 執行，確認失敗** → Expected: FAIL（400 VALIDATION_ERROR，type 不接受 retry）。
- [ ] **Step 3: 實作**。
- [ ] **Step 4: 執行，確認通過** → Expected: PASS；全部測試通過。
- [ ] **Step 5: Commit** `feat: 重試發佈，只重送失敗且仍可用的平台帳號`

### Task 4: 逾時恢復

**Files:**
- Create: `app/m5_publishing/recovery.py`
- Modify: `app/m5_publishing/engine.py`（`_attempt` 可從保存的 `request_ref` 接續；結算時可指定稽核內容）、`scheduler.py`（啟動檢查、`tick` 加入恢復）、`internal_router.py`
- Modify: `README.md`（排程、重試、恢復的操作方式）
- Test: `tests/api/test_recovery.py`

**Interfaces:**
- Produces: `async recovery.recover_stale(allow_auto_retry: bool) -> RecoveryResult`（`checked`：檢查的貼文數；`recovered`：離開發佈中的貼文數）。
- 掃描：`PUBLISHING` 且 `publishing_started_at <= now - 10 分鐘`、未刪除，`SKIP LOCKED`；只接手租約已過期的待發佈紀錄（同 Task 2 的認領規則）；沒有待發佈紀錄的貼文直接結算。
- 每筆先 `check`（D-03）：`PUBLISHED` → 成功（`RECOVERY_CONFIRMED_PUBLISHED`）；`READY` 且允許自動重試且 `auto_retry_count == 0` → `auto_retry_count + 1` 後重新發佈一次（有 `request_ref` 從 `finalize` 接續，沒有則從 `begin` 開始），結果 `AUTO_RETRY_SUCCEEDED/FAILED`；其他 `READY` → `FAILED / TIMEOUT`（`RECOVERY_CONFIRMED_NOT_PUBLISHED`）；`FAILED` → Adapter 回報的原因（`RECOVERY_CONFIRMED_NOT_PUBLISHED`）；`PROCESSING`、`UNKNOWN` → `FAILED / TIMEOUT`（`RECOVERY_UNCONFIRMED`）。
- 結算後稽核：有自動重試 → `PUBLISH_AUTO_RETRY`（系統，`reason = "PLATFORM_CONFIRMED_NOT_PUBLISHED"`，只列自動重試的紀錄）；沒有 → 補一筆 `POST_PUBLISH`（系統，列出全部紀錄）。
- Produces: `POST /api/v1/internal/publish-recovery` → `{"checked": n, "recovered": n}`；`scheduler.run_loop` 啟動時先 `recover_stale(False)`，之後每次 `tick` 以 `True` 執行。

- [ ] **Step 1: 寫失敗的測試**（前置：貼文 `PUBLISHING`、`publishing_started_at` 為 12:00；Threads 紀錄 `PENDING`、Discord `SUCCEEDED`）：
  - `test_post_publishing_under_ten_minutes_is_left_alone`：12:09:59 → 不處理；12:10:00 → 處理。
  - `test_confirmed_published_is_recorded_without_resending`：`check` 回 `PUBLISHED` 與連結 → `SUCCEEDED`、平台收到 0 則、`PUBLISHED`、歷程 `RECOVERY_CONFIRMED_PUBLISHED`。
  - `test_unconfirmed_is_timeout_without_resending`：`UNKNOWN` → `FAILED / TIMEOUT`、收到 0 則、`PARTIALLY_FAILED`、歷程 `RECOVERY_UNCONFIRMED`、補一筆系統 `POST_PUBLISH`。
  - `test_confirmed_not_published_is_retried_once`：`READY` → 收到 1 則、`SUCCEEDED`、歷程只有一筆 `(PENDING, SUCCEEDED, "system", "AUTO_RETRY_SUCCEEDED")`、`auto_retry_count == 1`、稽核 `PUBLISH_AUTO_RETRY`（只有 Threads）。
  - `test_auto_retry_failure_is_recorded_as_reported`：重新發佈回 `PLATFORM_UNAVAILABLE` → 原因照記、`AUTO_RETRY_FAILED`。
  - `test_record_already_auto_retried_is_not_sent_again`：`auto_retry_count = 1`、`READY` → 收到 0 則、`FAILED / TIMEOUT`。
  - `test_container_failure_is_recorded_with_platform_reason`：`check` 回 `FAILED / CONTENT_REJECTED`。
  - `test_startup_recovery_never_resends`：`allow_auto_retry=False`、`READY` → 收到 0 則、`FAILED / TIMEOUT`。
  - `test_record_in_progress_is_not_taken_over`：`attempt_started_at` 為 30 秒前 → 紀錄仍 `PENDING`、`check` 沒被呼叫。
  - `test_orphan_publishing_post_is_concluded`：沒有待發佈紀錄的發佈中貼文 → 依 BR-15 結算。
  - `test_recovery_endpoint_requires_secret_and_reports_counts`。
- [ ] **Step 2: 執行，確認失敗** → Expected: FAIL（匯入錯誤）。
- [ ] **Step 3: 實作**；README 加上「排程與重試」小節（設定排程、定時任務端點、重啟後的恢復）。
- [ ] **Step 4: 執行，確認通過** → Expected: PASS；全部測試通過；ruff 通過。
- [ ] **Step 5: Commit** `feat: 逾時恢復：確認平台結果、每筆最多自動重發一次，重啟時不重發`
