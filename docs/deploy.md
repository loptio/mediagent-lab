# 部署到 Render + Neon（免費方案）

前後端在同一個 Docker 映像檔、同一個網址（foundation-plan D-06）；資料庫用 Neon PostgreSQL，圖片放在 Neon Object Storage（S3 相容、公開讀取的 bucket，Threads、Instagram 直接從 bucket 網址下載）。

下面的 `<服務網址>` 指 Render 給的網址，例如 `https://mediagent-lab.onrender.com`。

## 1. Neon：建立資料庫

1. 在 [Neon](https://neon.tech/) 建立專案，區域選 Singapore（和 Render 同區，延遲最低）。
2. 在 Dashboard 的 **Connection string** 選 **Direct connection**（不要選 Pooled），複製 `postgresql://…neon.tech/neondb?sslmode=require` 這一串。程式會自動換成需要的驅動，原樣貼上即可。

## 2. Neon Object Storage：圖片用的 bucket

已建立（2026-11-22）：MediAgent 專案的 `production` 分支、新加坡區，bucket `mediagent-media`，存取等級 public_read（平台要能直接下載圖片；建立後不能改）。非機密的值已經寫在 `render.yaml`：

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

1. 在 [Render](https://render.com/) 選 **New → Blueprint**，連結 GitHub 並選 `loptio/mediagent-lab`。Render 會讀 `render.yaml`。
2. 依提示填入標示為需要手動填寫的值：

| 變數 | 填什麼 |
|---|---|
| `DATABASE_URL` | 第 1 步複製的 Neon 連線字串 |
| `CREDENTIAL_ENCRYPTION_KEYS` | 第 3 步產生的金鑰 |
| `OAUTH_REDIRECT_BASE_URL` | `<服務網址>` |
| `FRONTEND_ORIGIN` | `<服務網址>` |
| `S3_ACCESS_KEY_ID`、`S3_SECRET_ACCESS_KEY` | 第 2 步的 `nak_live_…`、`nsk_live_…`（端點、區域、bucket、`MEDIA_BASE_URL` 已寫在 `render.yaml`） |
| `THREADS_APP_ID`、`THREADS_APP_SECRET` | Meta 開發者網站上 Threads 使用情境的值（和本機 `.env` 相同） |

網址要等服務建立後才知道：先隨便填，部署完成後到服務的 **Environment** 改成正確的網址，再按 **Save, rebuild, and deploy**。`JWT_SECRET`、`OAUTH_STATE_SECRET`、`CRON_SECRET` 由 Render 自動產生。

3. 部署完成後打開 `<服務網址>/health`，看到 `{"status":"ok","database":"ok"}` 就成功了。第一次啟動會自動建立資料表。

## 5. 建立第一位管理員

正式環境不能用開發用的種子帳號。在自己的電腦執行（密碼以隱藏輸入詢問，不會出現在畫面或指令紀錄）：

```bash
DATABASE_URL='<第 1 步的 Neon 連線字串>' .venv/bin/python -m seeds.create_admin
```

之後用這個帳號登入 `<服務網址>`，其他幹部帳號在系統裡建立。

## 6. Meta：登記正式環境的回呼網址

在 Meta 開發者網站的 Threads 設定，Redirect Callback URLs 加上：

```
<服務網址>/api/v1/platform-accounts/oauth/callback
```

本機的 `https://localhost:8443/...` 可以保留，兩個都能用。

## 7. 定時觸發：讓排程準時、服務不休眠

Render 免費方案閒置 15 分鐘會休眠，休眠時服務內的排程檢查不會跑。用外部定時服務每 5 分鐘呼叫一次，同時讓服務保持清醒（一個服務一個月約 744 小時，在免費的 750 小時內）。

以 [cron-job.org](https://cron-job.org/)（免費、不需信用卡）為例，建立兩個工作：

| 名稱 | 網址 | 方法 | 頻率 | 標頭 |
|---|---|---|---|---|
| 排程發佈 | `<服務網址>/api/v1/internal/publish-due` | POST | 每 5 分鐘 | `X-Cron-Secret: <Render 的 CRON_SECRET>` |
| 逾時恢復 | `<服務網址>/api/v1/internal/publish-recovery` | POST | 每 10 分鐘 | 同上 |

`CRON_SECRET` 在 Render 服務的 **Environment** 可以看到。

另外在 GitHub repo 的 **Settings → Secrets and variables → Actions** 加上 `APP_URL`（`<服務網址>`）與 `CRON_SECRET`，`.github/workflows/scheduled-publish.yml` 每小時會再補觸發一次，外部服務出問題時也不會漏發。

## 8. 部署後檢查

- 用管理員登入，連結 Discord 頻道與 Threads 帳號，各發一則有圖片的貼文。
- Threads 帶圖發文時，Threads 會從 Neon Object Storage 的公開網址下載圖片（foundation-plan §10 第 3 項，部署後第一次實測）；失敗時在發佈結果（管理員可看到平台錯誤訊息）確認原因。
- 排程一則 5 分鐘後的貼文，確認時間到後幾分鐘內發出。

## 容量與費用

- Neon 免費方案：每個專案 PostgreSQL 1 GB（只放文字資料），Object Storage 另有 5 GB。原圖照上傳的檔案保存（上限 8 MB），以一張 1～3 MB 估算約可存一千多則有圖片的貼文。
- Render、Neon、cron-job.org 都使用免費方案，不需要信用卡。
