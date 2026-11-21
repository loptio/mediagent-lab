/** API 錯誤：後端一律回傳 {code, message, detail?, request_id}（《API 設計》§1.3），前端依 code 顯示中文提示。 */

import { PLATFORM_LABELS, type Platform } from '../labels'

export interface ErrorBody {
  code: string
  message: string
  detail?: Record<string, unknown> | null
  request_id?: string
}

/** 錯誤碼 → 中文提示（《API 設計》§4）。沒有列出的錯誤碼改用後端的 message。 */
export const ERROR_MESSAGES: Record<string, string> = {
  NETWORK_ERROR: '無法連線到伺服器，請確認網路後再試一次',
  VALIDATION_ERROR: '輸入的資料格式不正確，請檢查後再試一次',
  TARGET_DUPLICATE: '目標平台帳號重複選擇',
  PLATFORM_REQUIRES_OAUTH: 'Threads 與 Instagram 需要透過平台授權連結',
  UNAUTHENTICATED: '登入已失效，請重新登入',
  LOGIN_FAILED: 'Email 或密碼錯誤，或帳號無法登入',
  FORBIDDEN: '你的角色沒有權限執行這個操作',
  NOT_FOUND: '找不到資料，可能已被刪除',
  EMAIL_TAKEN: '這個 Email 已經有帳號了',
  LAST_ACTIVE_ADMIN: '系統至少要保留一位啟用中的管理員',
  USER_ALREADY_DISABLED: '這個帳號已經是停用狀態',
  USER_NOT_DISABLED: '這個帳號不是停用狀態，不需要啟用',
  USER_NOT_LOCKED: '這個帳號目前沒有被鎖定',
  PLATFORM_ACCOUNT_NAME_TAKEN: '同一個平台已經有相同名稱的帳號',
  PLATFORM_ID_MISMATCH: '授權的平台帳號和原本連結的不是同一個，請用原本的帳號授權',
  POST_NOT_EDITABLE: '只有草稿與已排程的貼文可以修改或刪除',
  POST_NOT_SCHEDULABLE: '只有草稿與已排程的貼文可以設定排程',
  POST_NOT_SCHEDULED: '這則貼文沒有排程',
  POST_NOT_PUBLISHABLE: '只有草稿與已排程的貼文可以立即發佈',
  POST_NOT_RETRYABLE: '只有部分失敗或全部失敗的貼文可以重試',
  IMAGE_ALREADY_ATTACHED: '這則貼文已經有圖片了',
  IMAGE_REQUIRED_BY_INSTAGRAM: '目標包含 Instagram，不能移除圖片；請先取消選擇 Instagram',
  IMAGE_URL_NOT_PUBLIC: 'Threads 與 Instagram 要從公開的 https 網址下載圖片，請管理員設定 MEDIA_BASE_URL 後重新附加圖片',
  PASSWORD_TOO_SHORT: '初始密碼至少要 8 個字元',
  CONTENT_EMPTY: '貼文內容不可為空白',
  CONTENT_TOO_LONG: '貼文超過平台的字數上限',
  IMAGE_FORMAT_INVALID: '圖片必須是完整的 JPEG 檔',
  IMAGE_TOO_LARGE: '圖片不可超過 8,000,000 位元組（約 7.6 MB）',
  IMAGE_DIMENSION_INVALID: '圖片尺寸不符合限制（像素太多或比例不符），請調整後再上傳',
  IMAGE_REQUIRED_FOR_INSTAGRAM: '發到 Instagram 必須附上圖片',
  NO_TARGET: '請至少選擇一個目標平台帳號',
  SCHEDULED_POST_REQUIRES_TARGET: '已排程的貼文至少要保留一個目標平台帳號',
  TARGET_NOT_AVAILABLE: '選擇的平台帳號已被移除',
  TARGET_AUTH_INVALID: '目標平台帳號的授權已失效，請管理員重新連結',
  SCHEDULE_TIME_NOT_FUTURE: '排程時間必須晚於現在',
  SCHEDULE_TIME_NOT_ALIGNED: '排程時間必須是 5 分鐘整，例如 12:00、12:05',
  NOTHING_TO_RETRY: '沒有可以重試的平台帳號',
  WEBHOOK_INVALID: 'Discord Webhook 網址無效，請確認網址是否完整',
  PLATFORM_AUTH_FAILED: '平台授權失敗，請再試一次；Instagram 請在授權視窗只勾選一個專業帳號',
  VERIFICATION_UNAVAILABLE: '暫時無法向平台確認，請稍後再試',
  TOO_MANY_LOGIN_ATTEMPTS: '登入嘗試次數過多，請稍後再試',
  INTERNAL_ERROR: '系統發生未預期的錯誤，請稍後再試',
}

const RETRY_HINTS: Record<string, string> = {
  AUTH_INVALID_SKIPPED: '請管理員重新連結',
  REMOVED_SKIPPED: '帳號已移除，請改用「複製為新草稿」',
}

interface RetryHint {
  account_name?: string
  reason?: string
}

function platformName(value: unknown): string {
  return typeof value === 'string' ? (PLATFORM_LABELS[value as Platform] ?? value) : '平台'
}

/** 把錯誤碼與補充資料組成一句給使用者看的中文提示 */
export function describeError(body: ErrorBody): string {
  const base = ERROR_MESSAGES[body.code] ?? body.message ?? '操作失敗'
  const detail = body.detail ?? {}

  if (body.code === 'CONTENT_TOO_LONG' && typeof detail.limit === 'number') {
    return `貼文超過 ${platformName(detail.platform)} 的字數上限（${detail.length}／${detail.limit}）`
  }
  if (Array.isArray(detail.accounts) && detail.accounts.length > 0) {
    return `${base}：${detail.accounts.join('、')}`
  }
  if (body.code === 'NOTHING_TO_RETRY' && Array.isArray(detail.hints) && detail.hints.length > 0) {
    // detail.hints：[{platform_account_id, account_name, reason}]，reason 為跳過原因代碼
    const tips = (detail.hints as RetryHint[]).map(
      (hint) => `「${hint.account_name ?? '平台帳號'}」${RETRY_HINTS[hint.reason ?? ''] ?? '無法重試'}`,
    )
    return `${base}：${tips.join('；')}`
  }
  return base
}

export class ApiError extends Error {
  readonly status: number
  readonly code: string
  readonly detail: Record<string, unknown> | null
  readonly requestId: string | null

  constructor(status: number, body: ErrorBody) {
    super(describeError(body))
    this.name = 'ApiError'
    this.status = status
    this.code = body.code
    this.detail = body.detail ?? null
    this.requestId = body.request_id ?? null
  }
}

/** 給畫面用：任何錯誤都轉成一句中文 */
export function errorMessage(error: unknown): string {
  if (error instanceof ApiError) return error.message
  return ERROR_MESSAGES.INTERNAL_ERROR
}
