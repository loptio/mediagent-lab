# Stage 1 Mainline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A locally runnable backend where a user logs in, writes a post, targets a linked Discord channel, publishes immediately, sees the message appear in Discord, and reads the per-platform publish result.

**Architecture:** Modular FastAPI monolith following `docs/architecture.md` §3.4 (`app/core` + `app/m1..m5`), each module layered router → service → repository. Publishing uses the three-step adapter contract from `docs/foundation-plan.md` D-01..D-03 (`begin` / `check` / `finalize`), with `platform_request_ref` persisted between steps; the engine runs in a FastAPI background task.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2.x (sync sessions, psycopg 3), Alembic, Pydantic v2 + pydantic-settings, httpx, PyJWT, pwdlib (Argon2), cryptography (MultiFernet), PostgreSQL 17, pytest, ruff, Docker Compose.

**Spec:** `docs/foundation-plan.md` (decisions D-01..D-13), `docs/requirements.md`, `docs/data-model.md`, `docs/api-design.md`, `docs/architecture.md`.

## Global Constraints

- Table names are singular and identical to `spec/erm.dbml` (`post`, `publish_record`, …); all 13 tables of `docs/data-model.md` §5 exist after the first migration.
- Enum values are the English codes of `docs/data-model.md` §2, enforced by `CHECK`.
- Every timestamp column is `TIMESTAMPTZ` stored in UTC; code obtains "now" only from `app.core.clock.now()`.
- All endpoints live under `/api/v1` except `/health`; JSON fields are snake_case.
- Every error response is `{"code", "message", "detail"?, "request_id"}` with codes from `docs/api-design.md` §4; request validation errors are `400 VALIDATION_ERROR`.
- `service.py` never imports `fastapi`; routers never call repositories.
- Credentials (tokens, webhook URLs) never appear in API responses, logs, or error messages; stored only as MultiFernet-encrypted JSON (D-13).
- Automated tests never call a real platform; real HTTP is replaced by `MockAdapter` or `httpx.MockTransport`.
- Platform call timeout is 30 s per call; per-record limit is 180 s from `attempt_started_at` (D-02). Both are settings so tests can shorten them.
- Posts are soft-deleted via `post.deleted_at`; `publish_record.post_id` is a real FK (D-04).
- Dependencies are pinned in `requirements.txt` / `requirements-dev.txt` (pip, no lock tool).

## Review Focus

1. One adapter raising an unexpected exception: the other targets still get results and the failing one is `FAILED / OTHER` (Task 4, `test_adapter_exception_does_not_block_other_targets`).
2. A record that is no longer `PENDING` when the engine writes back (cancelled meanwhile): the result is discarded, not overwritten (Task 3, `test_set_result_ignores_non_pending_record`).
3. A webhook URL that is not an official Discord webhook URL (other host, http, redirect): rejected with `422 WEBHOOK_INVALID` before any outbound request (Task 5, `test_link_rejects_non_discord_url_without_request`).
4. `CREDENTIAL_ENCRYPTION_KEYS` missing or malformed: encrypt/decrypt raise a clear configuration error; nothing is stored in plaintext (Task 3, `test_encrypt_requires_configured_key`).
5. Whitespace-only content, or text longer than a target's limit (Discord 2000): rejected at create (`422 CONTENT_EMPTY`) and at publish acceptance (`422 CONTENT_TOO_LONG`) with the post left in `DRAFT` (Task 4, `test_publish_rejects_text_over_target_limit`).

---

## File Structure

```
app/
  main.py                      app factory: routers, request-id middleware, error handlers, /health
  core/
    config.py                  Settings (env) — DATABASE_URL, JWT_SECRET, CREDENTIAL_ENCRYPTION_KEYS, DEV_MODE, timeouts
    db.py                      engine, SessionLocal, get_db, session_scope()
    clock.py                   now(), set_fixed()/reset() for tests
    enums.py                   all codes of data-model §2 as StrEnum
    errors.py                  DomainError(status, code, message, detail), handlers
    models.py                  all 13 ORM models
    crypto.py                  encrypt_credential(dict) -> (bytes, int), decrypt_credential(bytes) -> dict
    auth.py                    password hashing, JWT, get_current_user, require_role, ensure_owner_or_role
    audit.py                   write(db, action, actor, target_type, target_id, ..., target_results=None)
    posts.py                   transition_post(post, to_status)  (BR-12)
    publish_records.py         ensure_pending, set_result, cancel  (each writes publish_record_history)
    publish_rules.py           check(post, targets, now) -> None | raises DomainError
    platforms.py               Capabilities, result types, PlatformAdapter, registry, MockAdapter, effective_auth_status, mark_auth_invalid
  m1_accounts/                 router, service, repository, schemas  — login, me
  m2_platforms/                router, service, repository, schemas, adapters/discord.py — list, link Discord
  m3_posts/                    router, service, repository, schemas  — create, get, list
  m4_scheduling/               router, service, repository, schemas  — set targets, publish records
  m5_publishing/               router, service, engine.py            — publish-jobs, run_post
alembic/  alembic.ini          env + versions/0001_initial.py
seeds/seed_dev.py              three users (admin, publisher, writer)
tests/                         conftest.py, unit/, api/
Dockerfile  docker-compose.yml  scripts/entrypoint.sh  requirements*.txt  pyproject.toml  .env.example
.github/workflows/ci.yml
```

---

### Task 1: Project skeleton, tooling, health and error format

**Files:** Create `requirements.txt`, `requirements-dev.txt`, `pyproject.toml`, `.env.example`, `app/__init__.py`, `app/main.py`, `app/core/{__init__,config,db,clock,errors}.py`, `Dockerfile`, `docker-compose.yml`, `scripts/entrypoint.sh`, `.github/workflows/ci.yml`, `tests/conftest.py`, `tests/api/test_health.py`. Modify `.gitignore`.

**Interfaces — Produces:**
- `app.core.config.get_settings() -> Settings` with `database_url`, `jwt_secret`, `credential_encryption_keys: list[str]`, `dev_mode: bool`, `platform_call_timeout_seconds: float = 30`, `publish_record_limit_seconds: float = 180`, `publish_poll_interval_seconds: float = 5`.
- `app.core.db`: `engine`, `SessionLocal`, `get_db()` (FastAPI dependency), `session_scope()` (context manager committing on success).
- `app.core.clock`: `now() -> datetime` (aware UTC), `set_fixed(dt)`, `reset()`.
- `app.core.errors.DomainError(status_code: int, code: str, message: str, detail: dict | None = None)`.
- `tests/conftest.py`: fixtures `client` (TestClient), `db` (Session); each test starts with empty tables.

- [ ] Write `tests/api/test_health.py`: `test_health_reports_database_ok` (GET `/health` → 200 `{"status": "ok", "database": "ok"}`), `test_unknown_path_uses_error_format` (404 body has `code == "NOT_FOUND"` and a `request_id` equal to the `X-Request-Id` response header), `test_request_id_is_echoed` (sent `X-Request-Id` comes back unchanged).
- [ ] Run `pytest tests/api/test_health.py -q` → fails (no app).
- [ ] Implement the files above. `conftest.py` creates database `mediagent_test`, runs `alembic upgrade head` once per session, and empties all tables before each test with `SET session_replication_role = replica; TRUNCATE … RESTART IDENTITY CASCADE` (the append-only triggers forbid a plain TRUNCATE).
- [ ] Run `pytest tests/api/test_health.py -q` → 3 passed; `ruff check .` → clean.
- [ ] Commit `chore(core): project skeleton, health check and error format`.

### Task 2: Data model and first migration

**Files:** Create `app/core/enums.py`, `app/core/models.py`, `alembic.ini`, `alembic/env.py`, `alembic/versions/0001_initial.py`, `tests/unit/test_schema.py`.

**Interfaces — Produces:** ORM classes `UserAccount`, `UserSession`, `LoginSecurityEvent`, `PlatformAccount`, `PlatformAuthEvent`, `MediaFile`, `Post`, `PostImage`, `PostTarget`, `PublishRecord`, `PublishRecordHistory`, `AuditLog`, `AuditTargetResult`; enums `Role`, `UserStatus`, `ActorType`, `Platform`, `AuthStatus`, `PostStatus`, `RecordStatus`, `FailureReason`, `HistoryReason`, `AuditAction`, `TargetType`. Columns and constraints exactly as `docs/data-model.md` §5, plus `post.deleted_at TIMESTAMPTZ NULL` and `publish_record.post_id` FK → `post.id`.

- [ ] Write `tests/unit/test_schema.py`: `test_all_thirteen_tables_exist`; `test_audit_log_rejects_update_and_delete` (both raise a database error); `test_post_content_must_not_be_blank`; `test_publish_record_unique_per_post_and_account`; `test_event_seq_is_shared_across_event_tables` (an `audit_log` row and a `login_security_event` row get consecutive `event_seq`).
- [ ] Run → fails.
- [ ] Implement models; write the migration: create sequence `global_event_seq`, all tables, indexes of §5, and for the five append-only tables a row-level `BEFORE UPDATE OR DELETE` and statement-level `BEFORE TRUNCATE` trigger that raises.
- [ ] Run `pytest tests/unit/test_schema.py -q` → 5 passed.
- [ ] Commit `feat(core): data model and initial migration`.

### Task 3: Shared core services

**Files:** Create `app/core/{crypto,auth,audit,posts,publish_records,publish_rules,platforms}.py`, `tests/unit/test_{crypto,auth,posts,publish_records,platforms}.py`, `tests/factories.py`.

**Interfaces — Produces:**
- `crypto.encrypt_credential(data: dict) -> tuple[bytes, int]`, `crypto.decrypt_credential(token: bytes) -> dict`; raise `CredentialKeyError` when no valid key is configured.
- `auth.hash_password(str) -> str`, `auth.verify_password(str, str) -> bool`, `auth.issue_access_token(user_id: int, session_id: int) -> str`, dependencies `get_current_user`, `require_role(min_role: Role)`, function `ensure_owner_or_role(user, owner_id: int, min_role: Role)` raising `403 FORBIDDEN`. Role order: `admin > publisher > writer`. With `DEV_MODE`, header `X-Dev-User: <id>` authenticates.
- `audit.write(db, *, action: AuditAction, actor: UserAccount | None, target_type: TargetType, target_id: int, result: str | None = None, target_results: list[dict] | None = None, **details) -> AuditLog`.
- `posts.transition_post(post: Post, to_status: PostStatus) -> None` raising `DomainError(409, …)` for transitions outside BR-12.
- `publish_records.ensure_pending(db, post, account_id, *, actor, reason) -> PublishRecord`, `set_result(db, record_id, outcome, *, reason) -> bool` (False and no write if the record is not `PENDING`), `cancel(db, record, *, actor, reason)`.
- `platforms`: `Capabilities`, `PostContent(text, image_url=None)`, `Started(request_ref)`, `Published(post_id, post_url)`, `Failed(reason, message=None)`, `CheckStatus {PROCESSING, READY, PUBLISHED, FAILED, UNKNOWN}`, `CheckResult(status, published=None, failed=None)`, `PlatformAdapter` protocol (`platform`, `capabilities`, `count_chars`, `async begin`, `async check`, `async finalize`), `register_adapter`, `get_adapter(platform)`, `MockAdapter` (configurable per account name: success URL, failure reason, hang, raise; records received posts), `effective_auth_status(account, now)`, `mark_auth_invalid(db, account_id)`.
- `publish_rules.check(post, accounts, now)` raising `422 NO_TARGET`, `422 CONTENT_TOO_LONG` (detail: platform, limit, length), `422 TARGET_AUTH_INVALID`.

- [ ] Write unit tests, including `test_encrypt_requires_configured_key`, `test_credential_round_trip_and_key_rotation`, `test_transition_rejects_draft_to_published`, `test_ensure_pending_writes_history_with_null_from_status`, `test_set_result_ignores_non_pending_record`, `test_expired_account_is_effectively_invalid`.
- [ ] Run → fails; implement; run `pytest tests/unit -q` → all pass.
- [ ] Commit `feat(core): auth, audit, credential encryption, publish records, adapter contract`.

### Task 4: Mainline API and publish engine

**Files:** Create routers/services/repositories/schemas under `app/m1_accounts`, `app/m2_platforms`, `app/m3_posts`, `app/m4_scheduling`, `app/m5_publishing` (+ `engine.py`); `tests/api/test_mainline.py`, `tests/api/test_publish_engine.py`. Modify `app/main.py`.

**Interfaces — Consumes:** everything from Task 3. **Produces** (paths under `/api/v1`, shapes per `docs/api-design.md`): `POST /auth/login`, `GET /auth/me`, `GET /platform-accounts`, `POST /posts`, `GET /posts`, `GET /posts/{id}`, `PUT /posts/{id}/targets`, `POST /posts/{id}/publish-jobs` (`{"type": "immediate"}` → 202), `GET /posts/{id}/publish-records`; `engine.run_post(post_id: int) -> None` (async).

Engine per `PENDING` record, all records in parallel: set `attempt_started_at` → `begin` (30 s) → on `Started` persist `platform_request_ref` in its own transaction → poll `check` until `READY` or the record limit → `finalize` (30 s); a timed-out `finalize` gets one `check`. Outcomes: `Published` → `SUCCEEDED` with `published_at`, URL; `Failed` → `FAILED` with reason (and `mark_auth_invalid` for `AUTH_INVALID`); limit or timeout → `FAILED / TIMEOUT`; unexpected exception → `FAILED / OTHER`. Then set the post to `PUBLISHED` / `PARTIALLY_FAILED` / `FAILED` (BR-15) and write a `POST_PUBLISH` audit row with one target result per record.

- [ ] Write `tests/api/test_mainline.py`: `test_login_and_me`; `test_wrong_password_is_login_failed`; `test_create_post_rejects_blank_content`; `test_publish_to_three_targets_succeeds` (post ends `PUBLISHED`, three `SUCCEEDED` records with URLs, history `null→PENDING` then `PENDING→SUCCEEDED`, one audit row with three target results); `test_writer_cannot_publish` (403, post stays `DRAFT`); `test_publish_without_target_is_rejected` (422 `NO_TARGET`); `test_publish_rejects_text_over_target_limit`.
- [ ] Write `tests/api/test_publish_engine.py`: `test_one_failure_gives_partially_failed`; `test_all_failures_give_failed`; `test_hanging_adapter_times_out_without_blocking_others` (limit shortened via settings; record `FAILED / TIMEOUT`); `test_adapter_exception_does_not_block_other_targets`; `test_request_ref_is_persisted_before_finalize`; `test_auth_invalid_marks_account_invalid`.
- [ ] Run → fails; implement; run `pytest -q` → all pass; `ruff check .` clean.
- [ ] Commit `feat: mainline API and three-step publish engine`.

### Task 5: Discord adapter and account linking

**Files:** Create `app/m2_platforms/adapters/__init__.py`, `app/m2_platforms/adapters/discord.py`, `tests/unit/test_discord_adapter.py`, `tests/api/test_link_discord.py`. Modify `app/m2_platforms/{router,service,schemas}.py`, `app/main.py` (register the real adapter unless `PLATFORM_MODE=mock`).

**Interfaces — Produces:** `DiscordAdapter(transport: httpx.AsyncBaseTransport | None = None)` implementing `PlatformAdapter` (capabilities: 2000 chars, image optional); `async verify_webhook(url) -> dict` returning `{webhook_id, guild_id, channel_id}`; `POST /platform-accounts` `{platform: "discord", account_name, webhook_url}` → 201; errors `400 PLATFORM_REQUIRES_OAUTH`, `409 PLATFORM_ACCOUNT_NAME_TAKEN`, `422 WEBHOOK_INVALID`, `503 VERIFICATION_UNAVAILABLE` (admin only).

`begin` posts `{"content": text}` to `<webhook_url>?wait=true` with `follow_redirects=False`: 200 → `Published` with `https://discord.com/channels/{guild_id}/{channel_id}/{message_id}`; 401/403/404 → `Failed(AUTH_INVALID)`; 400 → `Failed(CONTENT_REJECTED)`; 429 → wait `retry_after` and retry (max 2), then `PLATFORM_UNAVAILABLE`; 5xx or connection error → `Failed(PLATFORM_UNAVAILABLE)`. `check` → `UNKNOWN`. Accepted URL pattern: `https://discord.com/api/webhooks/<digits>/<token>` or the `discordapp.com` equivalent.

- [ ] Write tests with `httpx.MockTransport`: `test_begin_returns_message_url`, `test_unknown_webhook_is_auth_invalid`, `test_rate_limit_retries_then_succeeds`, `test_server_error_is_platform_unavailable`, `test_link_stores_encrypted_credential_and_hides_it` (response and `GET /platform-accounts` contain no URL; DB value decrypts to the URL), `test_link_rejects_non_discord_url_without_request`, `test_link_invalid_webhook_records_auth_event`, `test_link_requires_admin`.
- [ ] Run → fails; implement; run `pytest -q` → all pass.
- [ ] Commit `feat(M2): Discord adapter and webhook linking`.

### Task 6: Seed data, run instructions, real run

**Files:** Create `seeds/__init__.py`, `seeds/seed_dev.py`. Modify `README.md` (add a "原型：本機啟動" section).

- [ ] Implement `python -m seeds.seed_dev`: creates `admin@club.test`, `publisher@club.test`, `writer@club.test` (idempotent), printing the dev password it used.
- [ ] `docker compose up --build -d`; `docker compose exec api python -m seeds.seed_dev`; `curl localhost:8000/health` → `{"status":"ok","database":"ok"}`.
- [ ] Manual check through `/docs`: log in as admin, link a real Discord webhook, create a post as publisher, set the target, publish, confirm the message in Discord and the URL in `GET /posts/{id}/publish-records`.
- [ ] Commit `chore: dev seed and local run instructions`; push.
