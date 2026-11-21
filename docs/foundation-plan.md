# mediagent 骨架與分工計畫書

> **狀態：提案，待全組確認。** 全組確認前不寫任何程式。
> 提案人：趙徊智（由 AI 協助閱讀原始碼與整理；「決定」欄位都是建議，由全組決定）
> 日期：2026-11-21
> 依據：本 repo 的 `docs/` 與 `spec/`（commit `8557a35`）；Postiz 原始碼 `gitroomhq/postiz-app`（commit `6be4874`，2026-11-20）

---

## 1. 這份文件要解決什麼

1. 規格在 11/3 完成，但 repo 裡還沒有程式。原訂 W06～W07 的 Sprint 0（專案骨架、資料庫模型、`openapi.yaml`）沒有人做，所有模組都在等。
2. 規格從來沒有被真正執行過。如果資料模型或流程有設計問題，等寫到一半才發現，修改成本很高。

做法：拿一個已經上線、功能和我們幾乎相同的開源專案 **Postiz**，逐項對照我們的規格，每一項取比較好的做法；兩邊都不適合我們條件的，改用更簡單的做法。再依對照結果決定骨架怎麼做、各模組做什麼。

**結論一句話：功能、資料模型、API 以我們的規格為準；發佈流程與平台串接改採 Postiz 驗證過的做法；另有 5 處改用更適合我們條件的新做法。**

---

## 2. 結論摘要

| 類別 | 項目 |
|---|---|
| **維持我們的設計**（和 Postiz 相同，或比它好） | 核心資料表結構、貼文整體狀態加每平台一筆發佈紀錄、JWT 加 session 表、Argon2 密碼雜湊、憑證加密與金鑰輪替、稽核與變更歷程、Discord 用 Webhook、MockAdapter 加 452 個驗收例子、排程以條件掃描 |
| **改採 Postiz 的做法** | 發佈拆成三步並保存中間狀態、Instagram 用 Instagram Login、平台錯誤分類與有限重試、貼文軟刪除、Discord 訊息連結格式、貼文連結查不到不算失敗 |
| **兩邊都不適合，改用新做法** | 不靠 Temporal 的可接續發佈、排程觸發方式、前後端同源部署、Git 流程簡化、憑證存成加密 JSON |

需要全組決定的事集中在第 11 節。

---

## 3. 對照方法

讀了 Postiz 的這些部分：

| 主題 | 檔案 |
|---|---|
| 資料模型 | `libraries/nestjs-libraries/src/database/prisma/schema.prisma`（1,846 行） |
| 平台介面與共用錯誤處理 | `integrations/social/social.integrations.interface.ts`、`integrations/social.abstract.ts` |
| 平台實作 | `threads.provider.ts`、`instagram.standalone.provider.ts`、`instagram.provider.ts`、`discord.provider.ts` |
| 發佈、更新授權、漏發掃描流程 | `apps/orchestrator/src/workflows/`（`post.workflow.v1.1.2.ts` 等） |
| 登入與加密 | `libraries/helpers/src/auth/auth.service.ts`、`apps/backend/src/services/auth/` |
| 檔案儲存、部署 | `upload/upload.factory.ts`、`var/docker/nginx.conf` |

Postiz 的規模比我們大很多：支援 36 個平台，資料模型裡大部分是我們用不到的功能（付費方案、接案市集、AI 代理）。它必須搭配工作流程引擎 Temporal 才能執行，而且整個專案沒有測試檔。所以不適合整套搬來用，適合的是學它已經踩過坑的地方。

---

## 4. 逐項決策

### 4.1 維持我們的設計

| 主題 | 我們的規格 | Postiz | 為什麼維持 |
|---|---|---|---|
| 核心資料表 | `user_account`、`platform_account`、`post`、`publish_record` | `User`、`Integration`、`Post` | 結構相同。Postiz 多了「多組織」一層，我們只有一個社團，不需要 |
| 發佈結果 | 貼文有整體狀態（含「部分失敗」），每個平台一筆 `publish_record` | 每個平台一筆 `Post`，沒有整體狀態 | 我們的例外情境（部分失敗後只重試失敗的平台）需要整體狀態 |
| 登入 | JWT 加 session 表，可由伺服器端登出、停用後立即失效 | JWT 放在 Cookie，登出只是清掉 Cookie | 符合 BR-43、NFR-07 |
| 密碼 | Argon2 | bcrypt | 兩者都可以，維持原決定 |
| 平台憑證 | MultiFernet 加密、可輪替金鑰、金鑰與資料庫分開 | AES-256-CBC；加密是後來才補上的，另外需要一個回填舊資料的流程 | 我們從第一天就加密，符合 NFR-02、NFR-06 |
| 稽核 | 5 張只能新增的表，資料庫觸發器保護 | 只有一張錯誤紀錄表 | 課程的安全與可追蹤要求需要；第一版 migration 就建好，功能排在 P1 |
| Discord | 貼上 Webhook 網址，驗證後連結 | 建立 Discord Bot，走 OAuth，再選頻道 | Webhook 不需要申請 App，最容易完成與展示 |
| 測試 | pytest-bdd 執行 452 個驗收例子，CI 一律用 MockAdapter | 沒有測試 | 這是我們比 Postiz 強的地方，也是課程評分項目 |
| 排程掃描 | 查詢「排程時間已到」的貼文，`SKIP LOCKED` | 每則貼文一個計時器，另外每小時掃描一次漏發的貼文 | 用條件查詢，本來就會補上漏掉的貼文，不需要另一個流程 |
| 授權到期 | 不自動更新，由管理員重新連結 | 自動更新 token | MVP 維持原決定（見 D-10） |
| 其他 | BIGINT 主鍵、三級角色、UTC 儲存 | 字串主鍵、兩級角色 | 維持原決定 |

### 4.2 改採 Postiz 的做法

#### D-01 發佈拆成三步，並保存中間狀態

**現在的規格**：《系統架構設計》6.1 已經要求「建立 container 後，先把平台的中途識別碼（`request_ref`）寫進資料庫」。但 7.1 的 Adapter 介面只有一個 `publish()`，一次呼叫做完全部，外面包 30 秒逾時；`request_ref` 要等 `publish()` 回傳才拿得到，6.1 的要求實際上做不到。

**問題**：

1. Threads 官方文件建議，建立 container 後平均等 30 秒再發佈，純文字貼文也是兩步。照現在的規格，真實的 Threads 發佈會經常被判成「發佈逾時」。
2. 逾時被取消時，`publish()` 沒有回傳，container ID 就遺失了。逾時恢復無從確認，只能記成失敗；使用者手動重試時，可能重複發文。

**Postiz 的做法**：拆成三個動作，並訂了四條規則。

| 動作 | 內容 | 能不能重試 |
|---|---|---|
| `postPending` | 建立 container，回傳待處理資料 | 可以：沒發佈的 container 別人看不到 |
| `checkPostStatus` | 只查詢 container 狀態，不改任何東西 | 可以，隨時重試 |
| `finalizePost` | 正式發佈 | **不自動重試**，除非先查過狀態 |

1. 只查詢的動作可以放心重試；會發文的動作不自動重試。
2. 執行發佈之前，先把目前狀態存起來。
3. container 狀態是 `PUBLISHED`，就代表貼文已經發出，不再發佈。這可以防止重複發文。
4. 結果不明時標成「未確認」，交給使用者判斷。

**我們的做法**：採用同樣的三步，Adapter 介面改成：

```python
class PlatformAdapter(Protocol):
    platform: Platform
    capabilities: Capabilities
    def count_chars(self, text: str) -> int: ...
    async def begin(self, credential, content) -> BeginResult: ...
    async def check(self, credential, request_ref: str | None) -> CheckResult: ...
    async def finalize(self, credential, request_ref: str) -> PublishResult: ...
```

- `begin`：建立 container，回傳 `request_ref`。Discord 這類一步就完成的平台，在 `begin` 直接回傳完成結果。
- `check`：只查詢，回傳 `PROCESSING`、`READY`、`PUBLISHED`（含連結）、`FAILED`（含原因）或 `UNKNOWN`。沒有 `request_ref` 時由 Adapter 自己決定能不能確認，不能就回 `UNKNOWN`；引擎不替它判斷。
- `finalize`：正式發佈，只在 `check` 回傳 `READY` 時呼叫。

發佈引擎處理每一筆發佈紀錄的順序：

1. 用一個短交易把 `attempt_started_at` 設為現在。
2. 呼叫 `begin`，**立刻**用一個短交易把 `request_ref` 寫進 `publish_record`。
3. 每 5 秒呼叫一次 `check`，直到 `READY`。
4. 呼叫 `finalize`，寫回結果。

資料表不需要新增欄位：`platform_request_ref` 和 `attempt_started_at` 在《資料模型》5.10 已經有了。

三條引擎規則，補上原規格沒寫清楚的情況：

- **誰在處理這一筆**：`attempt_started_at` 是「這一次嘗試」開始的時間。立即發佈、排程發佈、重試、恢復流程接手，都會重新設定它。任何執行者看到它距今不到 3 分鐘（D-02 的總時限），就跳過這一筆，避免兩邊同時處理。
- **發文動作逾時或結果不明**（`finalize`，或一步完成的 `begin`）：不重試。有 `request_ref` 就再 `check` 一次，確認已發出就記為成功；否則記為失敗「發佈逾時」，並**保留** `request_ref`。
- **手動重試**：紀錄上有 `request_ref` 時先 `check`。已發出就直接記為成功，不再發文；`READY` 就執行 `finalize`；其他情況清掉 `request_ref`，從 `begin` 重新開始。這樣 Threads 與 Instagram 逾時後重試，不會重複發文。Discord 沒有可查詢的識別碼，仍然依 BR-32 提醒使用者先到平台確認。

#### D-02 逾時的定義

| | 現在的規格 | 建議 |
|---|---|---|
| 單次平台 API 呼叫 | — | 逾時 30 秒 |
| 單筆發佈（含等待平台處理） | 逾時 30 秒 | 總時限 3 分鐘，從 `attempt_started_at` 起算，超過記為失敗、原因「發佈逾時」 |
| 逾時恢復的門檻 | 進入發佈中滿 10 分鐘 | 不變 |

總時限必須小於逾時恢復的門檻。這樣恢復流程接手某一筆紀錄時，原本的背景工作一定已經結束，不會兩邊同時處理同一筆。

「一個平台慢，不影響其他平台」（NFR-03）的要求不變：各平台仍然並行，各自計時。

#### D-03 逾時恢復改成「從保存的步驟接續」

恢復流程對每一筆仍是待發佈的紀錄，一律呼叫 `check`，再依結果處理。有保存下來的 `request_ref` 時，Adapter 可以直接問平台這個 container 的狀態，不用猜：

| `check` 的結果 | 處理 | 變更原因（沿用既有代碼） |
|---|---|---|
| `PUBLISHED` | 記為成功 | `RECOVERY_CONFIRMED_PUBLISHED` |
| `READY`，定時觸發且這一筆還沒自動重試過 | 執行 `finalize` 一次 | `AUTO_RETRY_SUCCEEDED`／`AUTO_RETRY_FAILED` |
| `READY`，已自動重試過，或是服務啟動時的檢查 | 記為失敗「發佈逾時」，不重發 | `RECOVERY_CONFIRMED_NOT_PUBLISHED` |
| `FAILED`（container 處理錯誤或過期） | 記為失敗，原因依 Adapter 回報 | `RECOVERY_CONFIRMED_NOT_PUBLISHED` |
| `PROCESSING`、`UNKNOWN` | 記為失敗「發佈逾時」，不重發；保留 `request_ref` | `RECOVERY_UNCONFIRMED` |

- BR-33 的文字不用改，也不需要新增任何代碼；改的是《系統架構設計》6.2 的處理方式。「服務啟動時不自動重新發佈」的規則維持。
- `發佈逾時恢復.feature` 的 16 個例子不受影響：例子裡的發佈紀錄沒有 `request_ref`，但引擎一律呼叫 `check`，由 MockAdapter 回傳例子設定的結果。
- 恢復流程接手一筆紀錄前，同樣先更新 `attempt_started_at`（D-01 的第一條引擎規則）。
- 順帶清理：《資料模型》2.4 的 `AUTO_RETRY_STARTED` 永遠寫不進去（變更歷程要求狀態必須改變，而自動重試開始時狀態仍是待發佈），也沒有任何驗收例子用到，建議移除。

MockAdapter 與驗收例子句型的對應，確認現有句型都能用三步介面表達：

| 句型 | MockAdapter 的行為 |
|---|---|
| 發佈結果為成功，平台貼文連結為 … | `begin` 成功 → `check` 回 `READY` → `finalize` 回傳連結 |
| 發佈結果為失敗，失敗原因為 … | `finalize` 回傳該失敗原因 |
| 發佈結果為授權失效 | 回傳 `AUTH_INVALID` |
| 發佈逾時 | `begin` 超過時限，引擎記為失敗「發佈逾時」；沒有留下 `request_ref`，所以之後重試會從 `begin` 重新開始 |
| 發佈尚未完成 | 呼叫停住不回應；例子在這個時間點檢查中間狀態（紀錄仍是待發佈、貼文仍是發佈中） |
| 查詢發佈結果為已發佈／未發佈 | `check` 回 `PUBLISHED`／`READY` |
| 無法查詢發佈結果 | `check` 回 `UNKNOWN` |
| （沒有設定查詢結果時） | `check` 預設回 `READY` |
| 收到 N 則貼文 | 成功執行 `finalize`（或一步完成的 `begin`）的次數 |

#### D-04 貼文改成軟刪除

**現在的規格**：真的刪掉貼文，但發佈紀錄要保留原貼文 ID，所以 `publish_record.post_id` 不能設外鍵，會指向不存在的資料。

**Postiz 的做法**：所有主要資料表都用 `deletedAt` 欄位標記刪除。

**我們的做法**：`post` 加上 `deleted_at`。刪除時填入時間，並刪掉 `post_target` 與 `post_image`（圖片檔案沒有其他引用時照樣刪除）。`publish_record.post_id` 可以加回外鍵。

對使用者的行為完全相同：已刪除的貼文查不到、不出現在列表、發佈紀錄仍可用原 ID 查看。`刪除貼文.feature` 的 13 個例子都是從行為驗證，不受影響。要改的是需求 4.3「實際刪除」的文字、《資料模型》5.7 與 5.10、`spec/erm.dbml`。

#### D-05 Instagram 與 Threads 的授權方式

| 平台 | 授權方式 | 申請的權限 |
|---|---|---|
| Threads | Threads 自己的 OAuth | `threads_basic`、`threads_content_publish` |
| Instagram | **Instagram Login**（不經過 Facebook 粉專） | `instagram_business_basic`、`instagram_business_content_publish` |

Postiz 兩種 Instagram 登入都有實作。經 Facebook 登入的版本，授權後還要多一步「選擇粉專」，需要額外的中間狀態；Instagram Login 沒有這一步，也不需要社團有 Facebook 粉專。帳號仍須是專業帳號。

Postiz 另外申請了留言與洞察報告的權限，我們用不到，不申請（NFR-06 最小權限）。兩個平台的長效 token 約 60 天到期。

#### D-11 平台錯誤分類與有限重試

Postiz 每個平台都有一張「平台錯誤訊息 → 錯誤類型」的對照表。我們照同樣方式，各 Adapter 把平台錯誤對應到既有的失敗原因：

| Postiz 的類型 | 我們的失敗原因 |
|---|---|
| `refresh-token`、`disconnect` | `AUTH_INVALID`（並把平台帳號標為失效） |
| `bad-body` | `CONTENT_REJECTED` |
| `retry`、HTTP 429、HTTP 5xx | `PLATFORM_UNAVAILABLE` |

重試規則分兩種呼叫，都在 Adapter 內處理，最多重試 2 次：

| 呼叫 | 哪些是 | 什麼時候自動重試 |
|---|---|---|
| 不會發文的呼叫 | `check`；兩步平台（Threads、Instagram）的 `begin` | 平台明確回應 429 或 5xx |
| 會發文的呼叫 | `finalize`；一步平台（Discord）的 `begin` | 只有 429（平台明確拒收，確定沒發出） |

逾時或結果不明的情況，一律不自動重試，避免重複發文。

#### D-12 Discord 訊息連結

格式為 `https://discord.com/channels/{guild_id}/{channel_id}/{message_id}`，Postiz 用的是同一個格式。送出 Webhook 時加上 `?wait=true`，回應裡有訊息 ID 與頻道 ID；連結帳號時對 Webhook 網址發 GET，可以取得伺服器 ID。這可以解決《API 設計》第 5 節的第 3 項待確認。

另一個細節也採用 Postiz 的做法：貼文發出後才去查連結，如果連結查不到，仍然記為成功，連結留空。

### 4.3 兩邊都不適合，改用新做法

#### D-06 前後端同源部署

- **我們**：前端放 Render Static Site、後端放 Render Web Service，是兩個網域，登入 Cookie 會變成跨站 Cookie。《系統架構設計》第 16 節已經把它列為未解決的風險（Safari 可能擋掉）。
- **Postiz**：前後端是兩個程式，但在 Docker 裡用 nginx 併成同一個網址（`/api/` 給後端，其餘給前端）。
- **建議**：再簡單一點。用一個 Docker 映像檔，建置時把前端編譯成靜態檔，由 FastAPI 一起提供。只有一個服務、一個網址：Cookie 是第一方的，不需要 CORS，部署也少一個服務。本機開發時，Vite 把 `/api` 轉給後端，同樣是同源。

#### D-07 排程觸發方式

- **我們**：只靠 GitHub Actions 每 5 分鐘呼叫一次後端。GitHub 官方文件說明，排程在尖峰時段可能延遲，甚至被略過；最短間隔也只有 5 分鐘。NFR-01 要求 10 分鐘內開始發佈，有風險。
- **Postiz**：每則貼文一個 Temporal 計時器，必須常駐一套 Temporal，免費方案跑不動。
- **建議**：三層觸發，任何一層成功就會發佈。重複觸發是安全的，因為掃描用 `SKIP LOCKED`。
  1. 服務內每分鐘檢查一次到期的貼文與需要接續的發佈，服務啟動時立刻檢查一次。
  2. 外部監控每 5 分鐘呼叫 `/health`，讓服務不休眠（原本就規劃要用 UptimeRobot）。
  3. GitHub Actions 排程保留，當作備援，呼叫 `/internal/publish-due`。

#### D-08 Git 流程簡化

原規範是 `feature` → `dev` → `main`。剩下的時間約四週，建議取消 `dev`：從 `main` 開 `feature/<模組>-<簡述>`，以 Pull Request 合併回 `main`，CI 通過並有一位其他模組的組員 review 才能合併。共用核心、migration、`openapi.yaml` 維持兩位 review。這也是課程 W10、W11 教的流程。

#### D-09 範圍分級與進度衡量

452 個驗收例子不刪，但分三級排順序（各模組的分級見第 7 節）：

| 等級 | 內容 | 例子數 |
|---|---|---|
| P0 | Demo 主線：登入、建立帳號、連結 Discord、寫貼文、選目標、立即發佈、看結果 | 170 |
| P1 | 圖片與裁切、預覽、排程、重試、Threads 與 Instagram 的連結與真實發文、移除帳號、稽核查詢 | 201 |
| P2 | 逾時恢復的完整例子、重新連結、複製草稿、調整角色、啟用、解除鎖定、登出所有裝置 | 81 |

分級以功能（feature 檔）為單位，只有 `連結平台帳號.feature` 拆開：以 Discord 為主的 7 個例子是 P0，需要 OAuth 流程的 13 個例子是 P1。

P0 的例子不需要等 P1 的功能。例如 `立即發佈.feature` 的 40 個例子，背景都有圖片、目標也包含 Instagram，但圖片是共用測試步驟直接寫進資料庫的，平台一律用 MockAdapter；不需要 M3 的圖片上傳，也不需要真實的 Instagram。

進度用「還有幾個例子標為 pending」衡量：骨架合併時，每個功能的測試檔都已存在，未完成的例子全部標為 pending，CI 從第一天就是綠燈；各模組每完成一組規則，就移除對應的 pending。

#### D-13 憑證存成加密的 JSON

現在的規格把憑證當成一個字串（Token 或 Webhook 網址）。但 Discord 還需要存伺服器 ID 與頻道 ID，之後若要做 token 自動更新也要存更多資料。建議 `credential_encrypted` 存「加密後的 JSON」，內容由各平台的 Adapter 自己定義，其他程式不解讀。資料表不用改。

#### D-10 token 自動更新（維持不做，但預留）

Postiz 會在到期前自動更新 token。我們維持 MVP 不做，由管理員重新連結；Adapter 介面預留 `refresh()`，列為延伸功能。Demo 前一週重新連結的提醒維持。

---

## 5. 規格修改清單

確認後，各項依團隊規範開 `spec-question` issue，再更新文件。

| 編號 | 修改 | 要改的文件 | 驗收例子 |
|---|---|---|---|
| D-01 | Adapter 介面改為 `begin`／`check`／`finalize`；三條引擎規則 | 架構 6.1、7.1、7.2、7.3、9.4、9.5 | 步驟不受影響 |
| D-02 | 30 秒改為單次呼叫逾時；新增單筆總時限 3 分鐘 | 需求 BR-32、NFR-03；架構 1.1、6.1、9.4；`erm.dbml` 的說明文字 | 步驟不受影響；**兩處文字要改**（見下） |
| D-03 | 逾時恢復一律先 `check` 再處理；移除 `AUTO_RETRY_STARTED` | 架構 6.2；資料模型 2.4；需求 4.4.1；`erm.dbml` | 步驟不受影響 |
| D-04 | 貼文軟刪除；`publish_record.post_id` 加外鍵 | 需求 4.3；資料模型 1、4.1、5.7、5.10、8；`erm.dbml` | 步驟不受影響 |
| D-05 | Instagram 用 Instagram Login；兩平台只申請發文權限 | 架構 7.2 | 不受影響 |
| D-06 | 前後端同源部署 | 架構 3.1、3.2、16；API 設計 1.2；團隊規範 3.3、11 | 不受影響 |
| D-07 | 三層排程觸發 | 架構 2、6、15（決策 4） | 不受影響 |
| D-08 | 取消 `dev` 分支 | 團隊規範 4.1、4.4、7.2 | — |
| D-09 | 範圍分級 P0／P1／P2 | 團隊規範 2 | — |
| D-11 | 錯誤分類對照與有限重試 | 架構 7.1 | 不受影響 |
| D-12 | Discord 訊息連結格式 | API 設計 5 | 不受影響 |
| D-13 | 憑證存成加密 JSON | 資料模型 5.4 | 不受影響 |

「步驟不受影響」的依據：驗收例子的步驟都是從行為描述（例如「貼文 P2 不存在」「平台帳號收到 1 則貼文」），沒有寫死內部做法。D-01～D-04 另外核對過 `立即發佈.feature`、`執行排程發佈.feature`、`重試發佈.feature`、`發佈逾時恢復.feature` 與 `刪除貼文.feature`。

D-02 有兩處**說明文字**提到「30 秒」，不是步驟，但 Rule 標題同時是測試的識別名稱，所以要和 D-02 同一張 `spec-question` 一起改：

- `立即發佈.feature` 的 Rule 標題「單一平台帳號發佈逾時（30 秒）不影響其他平台帳號的發佈」
- `發佈逾時恢復.feature` 開頭的說明「單一平台帳號的發佈逾時門檻為 30 秒」

---

## 6. 骨架的範圍

骨架就是《團隊協作規範》2.1 的 Sprint 0 交付物，加上一條最短的示範流程。由趙徊智以 AI 協助完成，放在 `feature/core-foundation` 分支，以 Pull Request 合併進 `main`；PR 說明會註明由 AI 協助。D 的負責人審查後接手維護。

### 6.1 骨架包含

| 項目 | 內容 |
|---|---|
| 專案結構 | 《系統架構設計》3.4 的目錄、`requirements*.txt`、`.env.example`、ruff、mypy |
| 容器 | `Dockerfile`（含前端建置，見 D-06）、`docker-compose.yml` |
| CI | lint、型別檢查、pytest（含 PostgreSQL）、Alembic 單一 head 檢查、Docker build |
| 資料庫 | 全部 ORM models、第一版 migration、限制條件、索引、`global_event_seq`、只能新增的表的觸發器 |
| 共用核心 | 設定、資料庫連線、代碼列舉、錯誤處理與錯誤碼、時鐘、身分驗證與角色檢查、稽核寫入、貼文狀態轉換、發佈紀錄函式、發佈限制檢查的介面、Adapter 介面與 MockAdapter、憑證加解密、圖片儲存介面與本機實作 |
| 測試基礎 | BDD 載入與 pending 機制、39 個共用句型、測試資料工廠；30 個功能各一個測試檔 |
| API 合約 | `docs/openapi.yaml` 初版（依《API 設計》35 個端點） |
| 前端 | 版面、路由與角色守衛、API client、型別產生、代碼中文對照、登入頁、貼文列表頁（唯讀）、貼文編輯頁的空殼 |
| 其他 | 種子資料、`/health`、結構化 Log |

### 6.2 示範流程（只做成功的情況）

登入 → 建立貼文 → 設定目標 → 立即發佈（MockAdapter）→ 查看發佈結果。

每個端點只讓一兩個「成功」的驗收例子通過，目的有兩個：證明整條路是通的，以及讓每個模組有一份可以照著寫的範本（router、service、repository、schemas、測試）。錯誤處理、權限、邊界情況、其餘例子與前端畫面，都由模組負責人完成。

### 6.3 骨架不包含

- 任何真實平台的 Adapter（Discord、Threads、Instagram）
- 各功能的完整規則：骨架合併時，452 個例子中預計只有十幾個通過，其餘標為 pending
- 圖片裁切、OAuth 流程、排程與重試的規則、逾時恢復的各種分支
- 各模組的前端頁面與元件
- 正式環境部署

---

## 7. 各模組的工作

負責人待全組分配。例子數是該模組在各等級的驗收例子數。

| 模組 | P0 | P1 | P2 | AI 幫不上、要真人做的事 |
|---|---|---|---|---|
| M1 帳號與安全 | 49 | 11 | 32 | 少 |
| M2 平台帳號與串接 | 12 | 30 | 22 | **多**：Meta 開發者 App、測試帳號、真實平台實測 |
| M3 貼文編輯 | 31 | 53 | 11 | 中：物件儲存的圖片要讓平台讀得到 |
| M4 目標與排程 | 38 | 44 | 0 | 少 |
| M5 發佈執行 | 40 | 42 | 16 | 少：全程用 MockAdapter |
| F 前端與稽核查詢 | — | 21 | — | 中：整合各模組的畫面、E2E |
| D DevOps | — | — | — | **多**：部署、網域、監控、金鑰 |

### M1 帳號與安全（端點 1～10）

- P0：登入、登出、建立幹部帳號、查看幹部帳號；`/login`、`/users` 頁面
- P1：停用帳號
- P2：調整角色、啟用帳號、解除鎖定、登出所有裝置
- 骨架已有：帳號與 session 的資料表、驗證與角色檢查、最簡單的登入
- 自己完成：登入失敗的鎖定與 IP 限流、登入安全事件、換發 Token、帳號管理的全部規則

### M2 平台帳號與串接（端點 11～16）

- P0：以 Webhook 連結 Discord（含網址檢查與內網防護，`連結平台帳號.feature` 中的 7 個例子）、查看平台帳號、**Discord 真實 Adapter**；`/platform-accounts` 頁面
- P1：Threads 與 Instagram 的 OAuth 連結（`連結平台帳號.feature` 其餘 13 個例子）、兩個真實 Adapter、移除平台帳號
- P2：重新連結平台帳號
- 骨架已有：Adapter 介面、MockAdapter、憑證加解密
- 自己完成：三個真實 Adapter 的三步發佈與錯誤對照、OAuth 流程、`docs/platform-notes.md`
- 要最早開始：申請 Meta 開發者 App、準備測試帳號、建立 Discord 測試伺服器（第 10 節）

### M3 貼文編輯（端點 17～25）

- P0：建立貼文草稿、修改貼文、查詢貼文列表；貼文列表頁與內容編輯元件
- P1：附加圖片（含 Instagram 裁切）、移除圖片、預覽貼文、刪除貼文、物件儲存的 `MediaStorage` 實作
- P2：複製為新草稿
- 骨架已有：圖片儲存介面與本機實作、發佈限制檢查的介面
- 自己完成：發佈限制檢查的完整規則（字數、圖片、Instagram 必須附圖）、圖片處理

### M4 目標與排程（端點 26～30）

- P0：設定目標平台帳號、查看發佈結果；目標選擇與發佈結果元件
- P1：設定排程、取消排程、`lifecycle` 的兩個跨模組函式（M2 移除帳號、M3 刪除貼文會呼叫）
- 骨架已有：貼文狀態轉換、發佈紀錄的建立與變更歷程
- 自己完成：已排程貼文修改目標時的同步規則、排程時間的規則、變更歷程查詢

### M5 發佈執行（端點 31～33）

- P0：立即發佈的受理規則與背景發佈的各種結果
- P1：執行排程發佈、重試發佈
- P2：逾時恢復的完整例子
- 骨架已有：三步發佈的引擎骨架（只處理全部成功）、排程檢查的掛載點
- 自己完成：單一平台失敗與逾時的處理、授權失效的目標、貼文最終狀態判定、重試規則、接續與恢復的各種分支、稽核中各目標的結果

### F 前端骨架與稽核查詢（端點 34）

- P0：接手前端骨架、整合貼文編輯頁（M3、M4、M5 的元件）、維護 `openapi.yaml` 與型別產生
- P1：稽核查詢的後端與頁面
- P2：Playwright E2E（情境一、情境二、例外情境）

### D DevOps 與共用核心

- P0：審查並接手骨架、維護 CI、**第一次部署到正式環境**（不要等到最後一週）
- P1：物件儲存、外部監控、排程的備援觸發、README
- P2：`runbook.md`、備份演練
- 骨架吸收了 D 原本在 Sprint 0 的大部分工作，建議 D 另外協助 M2 做真實平台實測

---

## 8. 時程

課程週次由教材日期推算（每週二上課），請以實際課表為準。

| 時間 | 目標 |
|---|---|
| 11/21～11/24 | 全組確認第 11 節的決定事項、分配模組。M2 與 D 開始申請帳號（第 10 節） |
| 11/24～11/29（W12） | 完成骨架，以 Pull Request 合併進 `main`；各模組讀自己的工作內容與範本 |
| 11/30～12/6（W13） | **P0**。里程碑 A：正式環境走完主線，Discord 真實發文，Threads 與 Instagram 用 MockAdapter |
| 12/7～12/13（W14） | **P1**。里程碑 B：圖片、排程、重試可用；Threads 與 Instagram 真實發文 |
| 12/14～12/20（W15） | **P2**、整合、E2E、Demo 彩排。12/20 之後只修 bug |
| 12/22（W16） | 期末報告與 Live Demo；標記 `v1.0.0-presentation` |
| 12/23～1/5（W17～W18） | 依回饋修正、Final Report；標記 `v1.0.0` |

時間不夠時的取捨順序：先放棄 P2，再放棄 P1 裡的 Instagram（它帶來圖片裁切與必須附圖的規則），保住 P0 加上排程與 Threads。

---

## 9. Git 流程與 AI 使用原則

- 分支：`feature/<模組>-<簡述>`，從 `main` 開，以 Pull Request 合併回 `main`（D-08）。
- 一張 issue 對應一個 PR；PR 說明寫清楚完成了哪些 Rule、移除了哪些 pending。
- 可以用 AI 寫程式，課程也允許。但每個人的模組要自己做、自己 commit，並且看得懂、說得出為什麼這樣寫：期末報告的組員貢獻表以 commit 與 PR 為證據，W16 的提問也可能問到任何人。
- AI 協助的部分在 PR 說明中註明。骨架的 PR 會註明由 AI 協助建立。

---

## 10. 開工前要先驗證的事

下面這些只能用真實帳號測，結果記錄在 `docs/platform-notes.md`。M2 負責，D 協助。

| # | 要確認的事 | 影響 |
|---|---|---|
| 1 | Threads 的純文字與圖片貼文，container 要等多久才可以發佈 | D-02 的總時限 |
| 2 | 對同一個 container 發佈兩次，平台怎麼回應；狀態是否會變成 `PUBLISHED` | D-03 防重複的依據 |
| 3 | Threads 與 Instagram 能不能讀到物件儲存公開網址上的圖片 | M3 的儲存實作 |
| 4 | Instagram Login 的流程、專業帳號的要求、token 期限 | D-05 |
| 5 | Discord Webhook 加 `?wait=true` 的回應內容、附件上傳 | D-12 |
| 6 | 各平台字數怎麼算。Threads 官方文件說 emoji 以 UTF-8 位元組計算 | 補上驗收例子的 `#TODO` |
| 7 | OAuth 回呼網址是否必須是 HTTPS。Postiz 的程式對非 HTTPS 網址做了特別處理，看起來是必須的 | 本機開發要用隧道，或直接在正式環境測 OAuth |
| 8 | Render 免費方案：每月免費時數夠不夠整月不休眠、背景工作是否正常 | D-06、D-07；不夠時改用自備主機加隧道 |

---

## 11. 需要全組決定的事

| # | 問題 | 建議 |
|---|---|---|
| 1 | 是否同意第 5 節的規格修改（D-01～D-13） | 同意。D-04、D-06、D-08 影響最多人，請特別看過 |
| 2 | 是否同意由 AI 協助建立骨架（第 6 節），其餘由各模組自己完成 | 同意 |
| 3 | 骨架的前端要做到哪裡 | 版面、登入頁、貼文列表頁（唯讀）、編輯頁空殼 |
| 4 | 範圍分級（D-09）與時程（第 8 節） | 同意；每週日檢查 pending 數 |
| 5 | 模組負責人 | 每人選一個；M2 與 D 的真人工作最多，建議互相支援 |
| 6 | 部署平台 | 先用 Render 加 Neon（原規劃）；第 10 節第 8 項不通過時改用自備主機 |
| 7 | Repo 協作者目前是 6 個帳號，README 列了 7 位組員 | 確認是否有人還沒被加入 |

---

## 12. 引用與授權

- Postiz 以 AGPL-3.0 授權。本專案只參考它的設計與它對各平台 API 的用法，**不複製、不逐行翻譯它的程式碼**；所有程式由我們依自己的規格撰寫。
- 期末報告中註明參考了 Postiz 的發佈流程設計。
- Threads 與 Instagram 的 API 行為以 Meta 官方文件與第 10 節的實測結果為準。
