# 部署到 Render + Neon（免費方案）

前後端在同一個 Docker 映像檔、同一個網址（foundation-plan D-06）；資料庫用 Neon PostgreSQL，圖片放在 Neon Object Storage（S3 相容、公開讀取的 bucket，Threads、Instagram 直接從 bucket 網址下載）。

下面的 `<服務網址>` 指 Render 給的網址，目前是 `https://mediagent-lab.onrender.com`。

這份文件記錄 2026-11-22 第一次部署的實際步驟。登入、密碼、驗證碼、同意條款、複製機密值這些事都由人操作；機密值一律存進密碼管理器，不要貼進對話、程式或 repo。

## 1. Neon：建立資料庫

1. 在 [Neon](https://neon.tech/) 建立專案：PostgreSQL 版本選 **17**（和本機 Docker 相同），區域選 **AWS Asia Pacific (Singapore)**（和 Render 同區，延遲最低）。
2. **Connect** → **Postgres database** 分頁，關閉 **Connection pooling**，複製 `postgresql://…neon.tech/neondb?sslmode=require` 這一串。程式會自動換成需要的驅動，原樣保存即可。

## 2. Neon Object Storage：圖片用的 bucket

1. **Object storage** → **Create bucket**：名稱 `mediagent-media`，權限選 **Public**（平台要能直接下載圖片）。**建立後就不能再改。**
2. **Settings** → **Credentials** → **Create credential**：勾選 `storage:read` 與 `storage:write`，到期日選 **No expiry**。Access key（`nak_live_…`）與 Secret（`nsk_live_…`）**只會顯示一次**，要當場存進密碼管理器。Neon 自動建立的其他憑證用不到，可以撤銷。

已建立（2026-11-22）：MediAgent 專案的 `production` 分支、新加坡區。非機密的值已經寫在 `render.yaml`：

| 本專案的變數 | Neon 後台顯示的名稱 | 值 |
|---|---|---|
| `S3_ENDPOINT_URL` | `AWS_ENDPOINT_URL_S3` | `https://br-polished-meadow-bi41cq8t.storage.c-5.ap-southeast-1.aws.neon.tech` |
| `S3_REGION` | `AWS_REGION` | `ap-southeast-1` |
| `S3_BUCKET` | — | `mediagent-media` |
| `MEDIA_BASE_URL` | — | `https://br-polished-meadow-bi41cq8t.storage.c-5.ap-southeast-1.aws.neon.tech/mediagent-media` |
| `S3_ACCESS_KEY_ID` | `AWS_ACCESS_KEY_ID`（`nak_live_…`） | 你自己保管，填在 Render |
| `S3_SECRET_ACCESS_KEY` | `AWS_SECRET_ACCESS_KEY`（`nsk_live_…`） | 你自己保管，填在 Render |

要在本機試物件儲存時，把上面的值與憑證填進 `.env`，並設 `MEDIA_STORAGE_BACKEND=s3`；平常本機開發維持 `local`。

## 3. 產生平台憑證的加密金鑰

在專案資料夾執行，複製輸出的那一行（之後換金鑰時把新的放前面、舊的用逗號接在後面）：

```bash
.venv/bin/python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

這把金鑰遺失的話，已連結的平台帳號都要重新連結；請另外保存在密碼管理器。

## 4. Render：用 Blueprint 建立服務

1. 在 [Render](https://render.com/) 選 **+ New → Blueprint**（**不要**用 New Web Service 手動建立），選 `loptio/mediagent-lab`。Render 會讀 `render.yaml`。repo 是私有的：授權 GitHub 前先確認瀏覽器登入的是有這個 repo 權限的帳號（`loptio`）。
2. 依提示填入標示為需要手動填寫的值：

| 變數 | 填什麼 |
|---|---|
| `DATABASE_URL` | 第 1 步複製的 Neon 連線字串 |
| `CREDENTIAL_ENCRYPTION_KEYS` | 第 3 步產生的金鑰 |
| `OAUTH_REDIRECT_BASE_URL` | `<服務網址>` |
| `FRONTEND_ORIGIN` | `<服務網址>` |
| `S3_ACCESS_KEY_ID`、`S3_SECRET_ACCESS_KEY` | 第 2 步的 `nak_live_…`、`nsk_live_…`（端點、區域、bucket、`MEDIA_BASE_URL` 已寫在 `render.yaml`） |
| `THREADS_APP_ID`、`THREADS_APP_SECRET` | Meta 開發者網站上 Threads 使用情境的值（和本機 `.env` 相同） |
| `INSTAGRAM_APP_SECRET` | Meta App 本身的應用程式密鑰（App 設定 → 基本資料；不是 Threads 那一組）。`INSTAGRAM_APP_ID`、`INSTAGRAM_LOGIN_CONFIG_ID` 已寫在 `render.yaml` |

網址要等服務建立後才知道：先隨便填，部署完成後到服務的 **Environment** 改成正確的網址，再按 **Save, rebuild, and deploy**。`JWT_SECRET`、`OAUTH_STATE_SECRET`、`CRON_SECRET` 由 Render 自動產生。

3. 部署完成後打開 `<服務網址>/health`，看到 `{"status":"ok","database":"ok"}` 就成功了。第一次啟動會自動建立資料表。部署是否成功以服務頁 **Deploys** 的綠色勾勾與 **Live** 為準；Blueprint 的同步頁可能一直顯示 Running，不用理會。

**服務建立之後才加進 `render.yaml` 的機密變數（`sync: false`），Render 不會詢問。** 要到服務的 **Environment** 手動加上，再按 **Save, rebuild, and deploy**。第一次部署時 `S3_ACCESS_KEY_ID`、`S3_SECRET_ACCESS_KEY`、`INSTAGRAM_APP_SECRET` 就是這樣補上的。

## 5. 建立第一位管理員

正式環境不能用開發用的種子帳號。在自己的電腦執行（密碼以隱藏輸入詢問，不會出現在畫面或指令紀錄）：

```bash
DATABASE_URL='<第 1 步的 Neon 連線字串>' .venv/bin/python -m seeds.create_admin
```

之後用這個帳號登入 `<服務網址>`，其他幹部帳號在系統裡建立。

## 6. Meta：Threads 與 Instagram 的設定

Threads 與 Instagram 在同一個 Meta App。兩邊的回呼網址都是：

```
<服務網址>/api/v1/platform-accounts/oauth/callback
```

**Threads：** Threads 使用情境 → **設定** → **Redirect Callback URLs**，在本機的 `https://localhost:8443/...` 後面加上這個網址（標籤式輸入框：貼上後按 Enter，再按儲存）。兩個網址都能用。

**Instagram**（Instagram API with Unified Login，foundation-plan D-05）：

1. Instagram 帳號要先在 Instagram App 裡轉成專業帳號（創作者或商家都可以）。
2. **使用案例** → **新增使用案例** → **管理 Instagram 上的訊息和內容** → **自訂** → 左側選 **API setup with Unified login**。不要用「包含 Facebook 帳號連結登入」那一套，已經停用，而且需要粉絲專頁。
3. 綁定企業資產管理組合（Business portfolio），沒有就新建一個（免費）。只在開發模式下給測試者使用時，不需要企業驗證。
4. **1. 設定你的應用程式** → **建立新的設定** → **透過範本建立**。範本的權限刪不掉，沒關係；系統只用到發文需要的兩個。
5. **註冊新的導回網址**：填上面的回呼網址並儲存。**Meta 不接受 `https://localhost`**，所以 Instagram 的授權只能在正式環境做。授權時如果出現導回網址不符的錯誤，到 **Facebook Login for Business** → **Settings** 的 **Valid OAuth Redirect URIs** 也加上同一個網址。
6. **2. 產生存取權杖** → **新增帳號**：加入要連結的 Instagram 專業帳號（開發模式下只有加入的帳號能授權）。
7. **把 Instagram 帳號加進企業資產管理組合**（只加成測試帳號還不夠，授權視窗會選不到它）：打開 [Meta 企業設定](https://business.facebook.com/settings)，確認左上角是綁定的那個組合 → **帳戶** → **Instagram 帳戶** → **新增**，用該 Instagram 帳號登入並允許。完成視窗裡「將此主頁加到人員名單」的開關保持關閉。
8. 左下齒輪 **應用程式設定** → **基本資料** → **應用程式密鑰**：這就是 `INSTAGRAM_APP_SECRET`，填到 Render。登入設定 ID 與 App ID 已寫在 `render.yaml`。

連結 Instagram：以管理員登入 `<服務網址>`，在「平台帳號」按「連結 Instagram 帳號」。Meta 的視窗裡：

- 企業資產管理組合選綁定的那一個，Instagram 帳戶只選**一個**專業帳號（分享兩個以上會連結失敗）。
- 範本登入設定把廣告帳戶也列為要分享的資產，選單裡只有「新建廣告帳戶」，略過不了：依畫面建立一個（網站填 `<服務網址>`、貨幣新台幣、時區 Asia/Taipei）。廣告帳戶免費，不投放廣告就不會收費；建立時會同意 Meta 的廣告條款，由操作的人決定。
- 最後的按鈕只按一次，等它導回系統顯示連結成功。Instagram 的權杖預設不會過期，平台帳號列表的授權到期時間顯示「不會過期」。

## 7. 定時觸發：讓排程準時、服務不休眠

Render 免費方案閒置 15 分鐘會休眠，休眠時服務內的排程檢查不會跑。用外部定時服務每 5 分鐘呼叫一次，同時讓服務保持清醒（一個服務一個月約 744 小時，在免費的 750 小時內）。

以 [cron-job.org](https://cron-job.org/)（免費、不需信用卡）為例，建立兩個工作；方法與標頭在每個工作的 **Advanced** 分頁設定：

| 名稱 | 網址 | 方法 | 頻率 | 標頭 |
|---|---|---|---|---|
| 排程發佈 | `<服務網址>/api/v1/internal/publish-due` | POST | 每 5 分鐘 | `X-Cron-Secret: <Render 的 CRON_SECRET>` |
| 逾時恢復 | `<服務網址>/api/v1/internal/publish-recovery` | POST | 每 10 分鐘 | 同上 |

`CRON_SECRET` 在 Render 服務的 **Environment** 可以看到。

另外在 GitHub repo 的 **Settings → Secrets and variables → Actions** 加上 `APP_URL`（`<服務網址>`）與 `CRON_SECRET`，`.github/workflows/scheduled-publish.yml` 每小時會再補觸發一次，外部服務出問題時也不會漏發。

## 8. 部署後檢查

2026-11-22 已在正式環境完成下列檢查：三個平台都連結成功，帶圖貼文同時發到 Discord、Threads、Instagram 都成功，排程貼文準時發出。之後重新部署或改設定時照同樣步驟再檢查一次。

- 用管理員登入，連結 Discord 頻道、Threads 與 Instagram 帳號，各發一則有圖片的貼文。
- Threads、Instagram 帶圖發文時，平台會從 Neon Object Storage 的公開網址下載圖片（foundation-plan §10 第 3 項，部署後第一次實測）；失敗時在發佈結果（管理員可看到平台錯誤訊息）確認原因。Instagram 的錯誤子代碼 `2207052` 代表圖片網址下載不到。
- 排程一則 5 分鐘後的貼文，確認時間到後幾分鐘內發出。

## 9. 之後的維運

- **正式環境是全新的資料庫**：本機連結過的平台帳號不會帶過去，要在正式環境的「平台帳號」重新連結（Discord 貼 Webhook 網址；Threads、Instagram 走授權流程）。
- **Demo 前一週重新連結 Threads**：Threads 的權杖約 60 天到期。Instagram 拿到的是不會過期的系統使用者權杖，不用處理。
- **Meta App 加一位備援管理員**：**應用程式角色** → **角色**，加一位組員當管理員（團隊規範）。
- **Render 網址改變時**，以下都要跟著改：
  - Meta 的兩個回呼網址（Threads、Instagram）
  - Render 的 `OAUTH_REDIRECT_BASE_URL`、`FRONTEND_ORIGIN`
  - GitHub Secret `APP_URL`
  - cron-job.org 兩個工作的網址
- **更換平台憑證的加密金鑰**：新金鑰放最前面，舊金鑰用逗號接在後面，舊資料才解得開。

## 容量與費用

- Neon 免費方案：每個專案 PostgreSQL 1 GB（只放文字資料），Object Storage 另有 5 GB。原圖照上傳的檔案保存（上限 8 MB），以一張 1～3 MB 估算約可存一千多則有圖片的貼文。
- Render、Neon、cron-job.org 都使用免費方案，不需要信用卡。
