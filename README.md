# MediAgent：社團多平台貼文同步發佈服務

> Multi-platform Post Sync & Scheduling Service for Student Clubs

## 原型：本機啟動（mediagent-lab）

這個 repo 是驗證設計用的原型，依 [docs/foundation-plan.md](docs/foundation-plan.md) 的決策實作。目前完成的是**主線**：登入 → 寫貼文 → 選目標 → 立即發佈 → 查看發佈結果，以及以 Webhook 連結 Discord 並真實發文。

### 啟動

需要 Docker Desktop。

```bash
docker compose up --build -d
```

```bash
docker compose exec api python -m seeds.seed_dev
```

- 第二個指令建立三位開發用使用者（管理員、發佈者、撰稿者），並印出開發用密碼。
- 前端：<http://localhost:8000/>，用上面的帳號登入（見下方「前端」）。
- API 文件（Swagger UI）：<http://localhost:8000/docs>
- 健康檢查：<http://localhost:8000/health>

平台憑證會加密保存，所以要先在 `.env` 設定 `CREDENTIAL_ENCRYPTION_KEYS`（格式與產生方式見 [.env.example](.env.example)）；沒有設定時，連結平台帳號會失敗。

### 走一次主線

在 Swagger UI 依序操作（登入後把 `access_token` 貼到右上角的 **Authorize**）：

1. `POST /api/v1/auth/login`：用 `admin@club.test` 登入。
2. `POST /api/v1/platform-accounts`：`{"platform": "discord", "account_name": "公告", "webhook_url": "<你的 Discord Webhook 網址>"}`。Webhook 網址等同密碼，只會加密保存，不會出現在任何回應或 Log 中。
3. 改用 `publisher@club.test` 登入並重新 Authorize。
4. `POST /api/v1/posts`：`{"content": "本週三 19:00 社課"}`，記下回傳的 `id`。
5. `PUT /api/v1/posts/{id}/targets`：`{"platform_account_ids": [<第 2 步回傳的 id>]}`。
6. `POST /api/v1/posts/{id}/publish-jobs`：`{"type": "immediate"}`，回應 202。
7. `GET /api/v1/posts/{id}/publish-records`：狀態為 `SUCCEEDED`，並附上 Discord 訊息連結。

### 連結 Threads

Threads 用平台授權（OAuth）連結，需要先在 [Meta 開發者網站](https://developers.facebook.com/) 建立 App（Threads 使用情境，加上 `threads_content_publish` 權限），並把要連結的 Threads 帳號加成 App 的測試者。

1. 在 Meta 後台的 redirect URIs 登記 `https://localhost:8443/api/v1/platform-accounts/oauth/callback`。
2. 在 `.env` 填入 `THREADS_APP_ID`、`THREADS_APP_SECRET`，以及 `OAUTH_REDIRECT_BASE_URL=https://localhost:8443`。
3. 連同本機的 HTTPS 代理一起啟動：

```bash
docker compose --profile oauth up -d
```

4. 以管理員登入後呼叫 `POST /api/v1/platform-accounts/oauth-authorizations`，內容 `{"platform": "threads"}`。
5. 用瀏覽器打開回傳的 `authorization_url`，在 Threads 上同意授權。
6. 瀏覽器會被導回 `https://localhost:8443`。憑證是本機自己簽發的，瀏覽器會顯示警告，選擇繼續前往即可；之後會看到「連結成功」。
7. 之後就和 Discord 一樣：建立貼文、把目標設為這個 Threads 帳號、立即發佈。

### 連結 Instagram

Instagram 用 Facebook 企業版登入，登入設定的導回網址只登記了正式環境（Meta 不接受 `https://localhost`），所以授權要在正式環境做，步驟見 [docs/deploy.md](docs/deploy.md) 第 6 步。本機開發 Instagram 相關功能用 `PLATFORM_MODE=mock`。

### 排程與重試

1. `PUT /api/v1/posts/{id}/schedule`：`{"scheduled_at": "2026-12-01T12:00:00+08:00"}`。時間以台灣時間輸入，必須晚於現在，且是 5 分鐘整（12:00、12:05…）。撰稿者不能為草稿設定排程。
2. 時間到後一分鐘內，服務會自動發佈（不需要做任何事）；`GET /api/v1/posts/{id}/publish-records` 會看到結果，稽核紀錄的操作者是「系統」。
3. 想改回草稿：`DELETE /api/v1/posts/{id}/schedule`。已排程的貼文也可以改目標，發佈紀錄會一起同步。
4. 有平台失敗時：`POST /api/v1/posts/{id}/publish-jobs`，內容 `{"type": "retry"}`，只會重送失敗的平台。Threads 會先向平台確認上一次是否其實已經發出，已發出就不再發；Discord 無法事後查詢，失敗原因是「發佈逾時」或「平台暫時無法連線」時，請先到頻道確認訊息是否已經發出，避免重複。

服務在發佈途中被重新啟動時，貼文會停在「發佈中」。進入發佈中滿 10 分鐘後，服務會向平台確認實際結果：已發出的記為成功、確認沒發出的自動重送一次、無法確認的記為「發佈逾時」，之後就能用重試處理。服務剛啟動時的檢查只確認結果，絕不重新發文。

部署到會休眠的免費方案時，另外設定外部定時任務每 5 分鐘呼叫下面兩個端點（標頭 `X-Cron-Secret` 填 `.env` 的 `CRON_SECRET`）：`POST /api/v1/internal/publish-due`、`POST /api/v1/internal/publish-recovery`。

### 部署

Render（`render.yaml`）＋ Neon 的免費方案，步驟見 [docs/deploy.md](docs/deploy.md)：建立資料庫、產生加密金鑰、用 Blueprint 建立服務、以 `python -m seeds.create_admin` 建立第一位管理員、在 Meta 登記回呼網址、設定外部定時觸發。

### 前端

`frontend/` 是 Vue 3 + Vite + TypeScript 的單頁應用，技術依《團隊協作規範》§3.2（Element Plus、TanStack Query、Pinia、Axios）。依 [foundation-plan D-06](docs/foundation-plan.md) 同源部署：`docker compose up --build` 會把前端建置進同一個映像檔，由 FastAPI 在 `/` 提供，API 仍在 `/api/v1`。

| 畫面 | 誰看得到 | 內容 |
|---|---|---|
| 貼文列表 `/posts` | 全部 | 狀態篩選，每頁 20／50／100 筆 |
| 貼文編輯 `/posts/:id` | 全部 | 內容與各平台字數上限、圖片（原圖與 Instagram 裁切版本）、目標平台帳號、預覽各平台、排程（台灣時間、5 分鐘整）、立即發佈與重試、發佈結果（發佈中每 3 秒更新）與變更歷程、複製為新草稿 |
| 平台帳號 `/platform-accounts` | 全部；操作限管理員 | 連結 Discord Webhook、更換 Webhook、連結或重新連結 Threads 與 Instagram、移除 |
| 幹部帳號 `/users` | 管理員 | 建立、調整角色、停用、啟用、解除鎖定 |
| 稽核紀錄 `/audit` | 管理員 | 一般操作、登入失敗、平台帳號連結失敗；依操作者、對應帳號、操作類型、日期篩選，每頁 20／50／100 筆 |

撰稿者看不到「立即發佈」與「重試」，也不能為草稿設定排程；右上角的選單可以「登出所有裝置」。真正的權限檢查在後端。

Access Token 只放在記憶體，Refresh Token 由後端放在 HttpOnly Cookie。Access Token 15 分鐘到期時，前端會自動換發並重送原本的請求；重新整理頁面或從 Threads 授權頁回來時，也會用 Cookie 自動恢復登入。登出、帳號被停用或登入超過 7 天後，才需要重新登入。

**開發**：需要 Node 24（版本見 `frontend/.nvmrc`）。後端照上面用 Docker 啟動，再開 Vite 開發伺服器，它會把 `/api` 轉給 `http://localhost:8000`，改程式會立即更新畫面：

```bash
cd frontend && corepack enable && pnpm install
```

```bash
pnpm dev
```

打開 <http://localhost:5173/>。

**檢查與建置**（CI 也跑同樣的指令）：

```bash
pnpm typecheck && pnpm test && pnpm build
```

**API 型別**：`src/shared/api/schema.d.ts` 由 openapi-typescript 依後端的 `/openapi.json` 產生，不要手改。後端 API 有變動時，啟動後端再執行：

```bash
pnpm gen:api
```

### 圖片

- `POST /api/v1/posts/{id}/image`（`multipart/form-data`，欄位 `file`）：一則貼文一張 JPEG，最多 8,000,000 位元組。比例超出 4:5～1.91:1 時自動從中間裁出 Instagram 版本（BR-06）。
- 選 Instagram 為目標時必須先附圖；目標含 Instagram 時不能移除圖片（BR-05）。
- Discord 以附件上傳圖片，本機就能發；Threads、Instagram 由平台下載圖片，`.env` 的 `MEDIA_BASE_URL` 必須是平台連得到的公開 https 網址，否則排程或發佈時回 `422 IMAGE_URL_NOT_PUBLIC`。
- 圖片儲存以 `MEDIA_STORAGE_BACKEND` 切換：本機 `local` 存成檔案，由後端 `/media/{key}` 提供；正式環境 `s3` 放在 Neon Object Storage 公開讀取的 bucket，平台直接從 bucket 網址下載；`db`（存在 PostgreSQL）保留為備案。

### E2E 測試

`e2e/` 用 Playwright 跑 [docs/requirements.md](docs/requirements.md) 第 3 節的三個使用情境：

- 情境一：管理員連結 Discord、Threads 與 Instagram，建立幹部帳號，換屆調整角色
- 情境二：發佈者寫貼文、附 9:16 海報，選 Threads、Instagram、Discord，在預覽確認裁切，設定排程，時間到後看到三個貼文連結
- 例外情境：Instagram 暫時無法連線 → 部分失敗 → 重試只重送 Instagram；失敗的帳號已移除 → 複製為新草稿再發佈

測試環境是獨立的 Docker Compose 專案（`mediagent-e2e`，連接埠 18100 與 18443），平台一律使用 MockAdapter（`PLATFORM_MODE=mock`），就算本機有 `.env` 也不會連到真實平台。

測試資料的做法：
- Threads、Instagram 平台帳號直接寫進資料庫（`e2e/support/seed_accounts.py`）。
- 排程到期：把 `scheduled_at` 改成過去，再帶 `X-Cron-Secret` 呼叫 `/internal/publish-due`。
- 例外情境：帳號名稱以 `e2e-fail-once-` 開頭時，mock 平台第一次會回報「平台暫時無法連線」，之後才成功。

需要 Docker 與 Node 24：

```bash
cd e2e && corepack enable && pnpm install && pnpm exec playwright install chromium
```

```bash
pnpm stack:up && pnpm test
```

```bash
pnpm stack:down
```

`stack:down` 會刪除測試資料；重跑前不一定要刪，測試用的名稱每次都不同。CI 只在指向 `main` 的 Pull Request 執行 E2E。

### 測試

測試需要 PostgreSQL（`docker compose up -d db`），不會連到任何真實平台。

`spec/features/` 的 452 個驗收例子由 `tests/bdd/` 以 pytest-bdd 執行（architecture §13）：目前 447 個通過、5 個標為待確認。原因寫在各 `tests/bdd/test_<功能>.py` 的 `PENDING`：

- 4 個是規格例子本身互相衝突（標為預期失敗；規格修好後測試會提醒拿掉標記），細節與建議見 [docs/spec-issues.md](docs/spec-issues.md)。
- 1 個是背景重送進行到一半的中間狀態，需要非同步的測試才能觀察（略過）。

原型在規格沒有寫到的地方先做的決定，也列在 [docs/spec-issues.md](docs/spec-issues.md)，請小組確認。

```bash
python -m pip install -r requirements-dev.txt
```

```bash
python -m pytest -q
```

### 目前的範圍

| 已完成 | 尚未實作 |
|---|---|
| 14 張資料表與 migration、只能新增的稽核表 | Instagram 真實發文的實測（授權只能在正式環境完成） |
| 登入、登出、登出所有裝置、換發 Token；連續失敗鎖定、IP 限流、登入安全事件 | |
| 幹部帳號：查看、建立、調整角色、停用、啟用、解除鎖定 | |
| 貼文：建立、列表、修改、刪除、複製為新草稿、預覽、附加與移除圖片 | |
| 目標、排程與取消、排程時間到自動發佈、重試、逾時恢復 | |
| 三步發佈引擎、發佈紀錄與變更歷程、稽核查詢 | |
| Discord：連結、重新連結、真實發文（含圖片附件）；Threads：授權連結、重新連結、真實發文 | |
| Instagram：Facebook 企業版登入連結、重新連結、container 三步發文 | |
| 部署：Render + Neon（資料庫與 Object Storage），https://mediagent-lab.onrender.com | |
| 452 個驗收例子：447 通過、5 待確認 | |
| 前端：登入、貼文列表與編輯（圖片、預覽、排程、發佈與結果、變更歷程、複製）、平台帳號、幹部帳號、稽核紀錄 | |
| E2E：三個使用情境（Playwright，mock 平台） | |
| 圖片：本機檔案、Neon Object Storage（S3）或 PostgreSQL 三種儲存 | |

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

學生社團通常同時經營多個社群平台帳號，例如 Threads、Instagram、Discord，用來發佈活動公告、招生資訊與成果分享。同一則公告必須由幹部逐一登入各平台、重複貼上相同內容，不但耗時，也容易漏發某個平台、各平台內容版本不一致，或錯過預定的發佈時間。

MediAgent 讓社團幹部在同一個地方撰寫一次貼文，選擇要發佈的平台，系統即可立即或依排程時間同步發佈到各平台，並記錄每個平台的發佈結果。

## Target Users

只開放給經管理員授權、負責社團對外宣傳的幹部；一般社員沒有帳號（需求 2）。

| 角色 | 通常是 | 可以做的事 |
|---|---|---|
| 管理員 | 社長或公關長 | 管理平台帳號與幹部帳號，並擁有發佈者的所有權限 |
| 發佈者 | 負責發文的幹部，例如公關、文書 | 撰寫、發佈與排程貼文 |
| 撰稿者 | 協助撰寫內容的幹部，例如新進幹部、美宣 | 撰寫自己的貼文；不能發佈，也不能為草稿設定排程 |

## MVP Scope

依 [docs/requirements.md](docs/requirements.md) 第 8 節：

1. 支援平台：Threads、Instagram、Discord，以 Adapter 架構保留擴充性
2. 貼文內容：文字，可附加一張 JPEG 圖片；Instagram 必須附加圖片，比例不符時自動從中間裁切
3. 發佈前可預覽各平台呈現的樣子
4. 帳號由管理員建立，不開放自行註冊；角色為管理員、發佈者、撰稿者
5. Threads、Instagram 透過平台授權流程連結；Discord 以 Webhook 連結並驗證；授權到期後由管理員手動重新連結
6. 立即發佈、排程發佈、重試都在背景執行，並有發佈逾時恢復機制
7. 稽核紀錄、登入安全事件、平台授權事件、發佈紀錄變更歷程

## Extension Features（延伸功能，視進度實作）

依需求文件第 9 節，下列項目不在 MVP 範圍：

1. 多張圖片、影片；各平台客製不同版本的內容
2. 撰稿者送審、發佈者核准的審核流程
3. 平台授權自動刷新、管理員雙重驗證（2FA）
4. AI 貼文改寫、AI 留言自動回覆
5. 更多平台：Bluesky、Facebook 粉專、Telegram 等
6. 發佈成效統計

---

## 系統規格文件導讀

本專案之詳細需求規格、系統架構、資料庫模型、API 合約與驗收測試規格已完整定義於 `docs/` 與 `spec/` 目錄中：

| 檔案 | 內容 |
|---|---|
| `docs/requirements.md` | 需求規格：角色權限、資料、功能需求（FR）、商業規則（BR）、非功能需求（NFR）、MVP 範圍、待確認事項 |
| `docs/architecture.md` | 系統架構：部署與開發環境、模組分工（M1～M5、F、D）、發佈引擎、平台串接、安全、測試架構、架構決策紀錄 |
| `docs/data-model.md` | 資料模型：13 張資料表的完整欄位、英文代碼對照、各表由哪個模組寫入、交易與併發 |
| `docs/api-design.md` | API 設計：35 個端點、錯誤碼、前後端共同遵守的合約 |
| `docs/team-rules.md` | 團隊協作規範：模組分工、Sprint 時程、技術棧、Git 流程、命名與分層、測試與完成的定義、繳交、密鑰管理 |
| `docs/issue-workflow.md` | Issue 撰寫規範與模板：如何把功能拆成可開發的 issue |
| `spec/erm.dbml` | 業務資料模型（DBML），可貼到 [dbdiagram.io](https://dbdiagram.io) 檢視 ER 圖 |
| `spec/features/*.feature` | 30 個功能的驗收規格（Gherkin），共 452 個例子，以 pytest-bdd 執行 |

### 建議閱讀順序

1. **所有人**：`docs/requirements.md` 第 1～3 節（問題、角色、情境）→ `docs/team-rules.md`
2. **後端**：`docs/architecture.md` → `docs/data-model.md` → `docs/api-design.md` → 自己模組負責的 `spec/features/`
3. **前端**：`docs/api-design.md` → `docs/requirements.md` 第 2.1 節（角色權限）、第 4.7 節（平台限制）
4. **開 issue 前**：`docs/issue-workflow.md`

### 閱讀慣例

- **編號**：FR-xx、BR-xx、NFR-xx 以 `docs/requirements.md` 為準，其他文件與 issue 一律引用這些編號。
- **「需求 4.3」**：指 `docs/requirements.md` 第 4.3 節。
- **文件間引用**：《mediagent 資料模型》＝`docs/data-model.md`、《mediagent API 設計》＝`docs/api-design.md`、《mediagent 系統架構設計》＝`docs/architecture.md`、《mediagent 團隊協作規範》＝`docs/team-rules.md`、《mediagent Issue 撰寫規範》＝`docs/issue-workflow.md`。
- **`#TODO`**：feature 中尚待外部資料查證的規則（如各平台字數算法、圖片尺寸限制）。
- **圖表**：架構文件使用 Mermaid，在 GitHub 或安裝 Mermaid 擴充套件的 VS Code 中可直接顯示。

### 尚待決定

- `docs/requirements.md` 第 10 節：異常通知、幹部自行改密碼、PNG 轉檔等 6 項。
- `docs/api-design.md` 第 5 節：API 層面暫定的處理方式。

規格有疑問或需修改時，請開 `spec-question` issue 討論，決定後再更新文件（見 `docs/team-rules.md`）。
