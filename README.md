# MediAgent

> 社團多平台貼文同步發佈服務 · Multi-platform Post Sync & Scheduling Service for Student Clubs

社團幹部寫一次貼文，就能立即或依排程同步發佈到 Threads、Instagram、Discord，並查看每個平台的發佈結果。

這個 repo 是小組專案的原型，用來驗證 [`docs/`](docs/) 與 [`spec/`](spec/) 的設計，設計決策見 [foundation-plan](docs/foundation-plan.md)。

- **正式環境：** <https://mediagent-lab.onrender.com>（Render + Neon 免費方案）
- **狀態：** 規格的 452 個驗收例子通過 447 個；2026-11-22 已在正式環境實測三個平台的連結、帶圖發文與排程

## 功能

- **帳號與權限：** 管理員建立幹部帳號，分為管理員、發佈者、撰稿者；連續登入失敗鎖定、IP 限流
- **平台帳號：** Discord 以 Webhook 連結；Threads、Instagram 以平台授權連結
- **貼文：** 草稿、附一張 JPEG、預覽各平台的樣子（Instagram 比例不符時自動裁切）、複製為新草稿
- **發佈：** 立即發佈、排程、只重送失敗平台的重試、逾時恢復，設計上避免重複發文
- **紀錄：** 每個平台的發佈結果與變更歷程、稽核紀錄

| 部分 | 技術 |
|---|---|
| 後端 | Python、FastAPI、SQLAlchemy、Alembic、PostgreSQL |
| 前端 | Vue 3、Vite、TypeScript、Element Plus、TanStack Query |
| 測試 | pytest、pytest-bdd、Vitest、Playwright |
| 部署 | Docker、Render、Neon（PostgreSQL 與 Object Storage）、GitHub Actions |

## 本機啟動

需要 Docker Desktop。

```bash
docker compose up --build -d
```

```bash
docker compose exec api python -m seeds.seed_dev
```

第二個指令建立管理員、發佈者、撰稿者三個開發用帳號，並印出密碼。接著打開 <http://localhost:8000/>，用 `admin@club.test` 登入；API 文件在 <http://localhost:8000/docs>。

要連結平台帳號時，把 `.env.example` 複製成 `.env`，填入 `CREDENTIAL_ENCRYPTION_KEYS`（產生方式寫在檔案裡），再重新啟動。

| 平台 | 本機怎麼連結 |
|---|---|
| Discord | 在「平台帳號」頁貼上頻道的 Webhook 網址 |
| Threads | `.env` 填 `THREADS_APP_ID`、`THREADS_APP_SECRET`、`OAUTH_REDIRECT_BASE_URL=https://localhost:8443`，用 `docker compose --profile oauth up -d` 一起啟動本機 HTTPS 代理，再到「平台帳號」頁連結 |
| Instagram | Meta 不接受 localhost 回呼網址，只能在正式環境連結；本機用 `PLATFORM_MODE=mock` 模擬 |

Threads、Instagram 由平台自己下載圖片，所以帶圖發文需要公開的 https 圖片網址；正式環境把圖片放在 Neon Object Storage。

## 測試

**後端**（需要 `docker compose up -d db`，不會連到真實平台）：

```bash
python -m pip install -r requirements-dev.txt && python -m pytest -q
```

`tests/bdd/` 以 pytest-bdd 執行 `spec/features/` 的 452 個例子：447 個通過；4 個是規格例子互相衝突，標為預期失敗（見 [spec-issues](docs/spec-issues.md)）；1 個需要非同步測試才能觀察，先略過。

**前端**（Node 24）：

```bash
cd frontend && corepack enable && pnpm install && pnpm typecheck && pnpm test
```

開發時在 `frontend/` 執行 `pnpm dev`，打開 <http://localhost:5173/>。後端 API 改了之後，用 `pnpm gen:api` 重新產生前端型別。

**E2E**：Playwright 跑需求的三個使用情境，使用獨立的 Docker Compose 環境與模擬平台。

```bash
cd e2e && corepack enable && pnpm install && pnpm exec playwright install chromium
```

```bash
pnpm stack:up && pnpm test
```

CI（GitHub Actions）會跑 lint、後端測試、前端檢查與 Docker 建置；指向 `main` 的 PR 另外跑 E2E。

## 部署

用 Render Blueprint（`render.yaml`）＋ Neon 部署，步驟與日後維運見 [deploy](docs/deploy.md)。

## 專案結構

```text
app/          後端：core 共用、m1_accounts～m5_publishing 五個模組、f_audit 稽核
frontend/     前端單頁應用，與後端同源部署
alembic/      資料庫 migration
seeds/        開發用資料、建立第一位管理員
tests/        unit、api、bdd（驗收例子）
e2e/          Playwright 端對端測試
spec/         ERD（DBML）與 30 個功能的驗收規格（Gherkin）
docs/         需求、架構、資料模型、API 等設計文件
```

## 文件

| 文件 | 內容 |
|---|---|
| [requirements.md](docs/requirements.md) | 需求規格：角色、情境、FR、BR、NFR、MVP 範圍 |
| [architecture.md](docs/architecture.md) | 系統架構：模組分工、發佈引擎、平台串接、安全、測試 |
| [data-model.md](docs/data-model.md) | 資料表欄位、交易與併發 |
| [api-design.md](docs/api-design.md) | API 端點與錯誤碼 |
| [foundation-plan.md](docs/foundation-plan.md) | 原型的設計決策與待查證事項 |
| [spec-issues.md](docs/spec-issues.md) | 規格衝突與原型先做的決定（待小組確認） |
| [deploy.md](docs/deploy.md) | 部署與維運 |
| [team-rules.md](docs/team-rules.md) | 團隊協作規範 |
| [issue-workflow.md](docs/issue-workflow.md) | Issue 撰寫規範 |

FR、BR、NFR 的編號以 `docs/requirements.md` 為準。規格有疑問時開 `spec-question` issue 討論，決定後再更新文件。

---

## Project Info

| 項目 | 內容 |
|---|---|
| Project Title | MediAgent |
| Group Number | G01 |
| Course | 網際服務軟體工程（Web Service Software Engineering） |

## Members

| 姓名 | 主要負責 |
|---|---|
| 趙徊智 | 平台串接（Threads、Instagram、Discord Adapter）、發佈與重試流程 |
| 傅資涵 | 需求與提案文件、RESTful API Design、OpenAPI Contract |
| 蘇文伶 | 軟體架構、Data Model／ERD、資料庫設計 |
| 詹皓宇 | 貼文管理與排程核心邏輯 |
| 陳亭妤 | 帳號與權限（Authentication／Authorization） |
| 陳冠斌 | 自動化測試、GitHub Actions CI |
| 陳薏安 | Docker、部署、Logging 與 Health Check |

## Problem Statement

學生社團通常同時經營 Threads、Instagram、Discord 等多個平台帳號。同一則公告要由幹部逐一登入各平台重複貼上，不但耗時，也容易漏發、內容不一致或錯過預定時間。MediAgent 讓幹部在同一個地方寫一次貼文，立即或依排程同步發佈，並記錄每個平台的結果。

## Target Users

只開放給管理員授權的社團幹部，一般社員沒有帳號。

| 角色 | 通常是 | 可以做的事 |
|---|---|---|
| 管理員 | 社長、公關長 | 管理平台帳號與幹部帳號，並有發佈者的所有權限 |
| 發佈者 | 公關、文書 | 撰寫、發佈與排程貼文 |
| 撰稿者 | 新進幹部、美宣 | 撰寫自己的貼文，不能發佈或為草稿設定排程 |

## MVP Scope

依 [requirements.md](docs/requirements.md) 第 8 節：

1. 支援 Threads、Instagram、Discord，以 Adapter 架構保留擴充性
2. 文字貼文可附一張 JPEG；Instagram 必須附圖，比例不符時自動從中間裁切
3. 發佈前可預覽各平台的樣子
4. 帳號由管理員建立，不開放自行註冊
5. Threads、Instagram 以平台授權連結，Discord 以 Webhook 連結；授權到期由管理員重新連結
6. 立即發佈、排程、重試都在背景執行，並有逾時恢復
7. 稽核紀錄、登入安全事件、平台授權事件、發佈紀錄變更歷程

## Extension Features

不在 MVP 範圍（需求第 9 節）：多張圖片與影片、各平台客製內容、送審流程、授權自動刷新、管理員雙重驗證、AI 改寫與留言回覆、Bluesky 等更多平台、發佈成效統計。
