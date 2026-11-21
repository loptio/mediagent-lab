/** 代碼中文對照：《資料模型》§2。畫面一律顯示中文，不直接顯示英文代碼。 */

export type Role = 'admin' | 'publisher' | 'writer'
export type Platform = 'threads' | 'instagram' | 'discord'
export type PostStatus = 'DRAFT' | 'SCHEDULED' | 'PUBLISHING' | 'PUBLISHED' | 'PARTIALLY_FAILED' | 'FAILED'
export type RecordStatus = 'PENDING' | 'SUCCEEDED' | 'FAILED' | 'CANCELLED'
export type FailureReason =
  | 'AUTH_EXPIRED'
  | 'AUTH_INVALID'
  | 'PLATFORM_UNAVAILABLE'
  | 'CONTENT_REJECTED'
  | 'TIMEOUT'
  | 'OTHER'

/** Element Plus 標籤顏色；狀態顏色依團隊規範 §9 */
export type TagType = 'info' | 'primary' | 'warning' | 'success' | 'danger'

export const ROLE_LABELS: Record<Role, string> = {
  admin: '管理員',
  publisher: '發佈者',
  writer: '撰稿者',
}

export const USER_STATUS_LABELS: Record<string, string> = {
  active: '啟用',
  disabled: '停用',
}

export const PLATFORM_LABELS: Record<Platform, string> = {
  threads: 'Threads',
  instagram: 'Instagram',
  discord: 'Discord',
}

export const AUTH_STATUS_LABELS: Record<string, string> = {
  valid: '有效',
  invalid: '失效',
}

export const POST_STATUS_LABELS: Record<PostStatus, string> = {
  DRAFT: '草稿',
  SCHEDULED: '已排程',
  PUBLISHING: '發佈中',
  PUBLISHED: '發佈完成',
  PARTIALLY_FAILED: '部分失敗',
  FAILED: '全部失敗',
}

/** 草稿灰、已排程藍、發佈中橘、發佈完成綠、部分失敗黃、全部失敗紅 */
export const POST_STATUS_TAGS: Record<PostStatus, TagType> = {
  DRAFT: 'info',
  SCHEDULED: 'primary',
  PUBLISHING: 'warning',
  PUBLISHED: 'success',
  PARTIALLY_FAILED: 'warning',
  FAILED: 'danger',
}

export const RECORD_STATUS_LABELS: Record<RecordStatus, string> = {
  PENDING: '待發佈',
  SUCCEEDED: '成功',
  FAILED: '失敗',
  CANCELLED: '已取消',
}

export const RECORD_STATUS_TAGS: Record<RecordStatus, TagType> = {
  PENDING: 'warning',
  SUCCEEDED: 'success',
  FAILED: 'danger',
  CANCELLED: 'info',
}

export const FAILURE_REASON_LABELS: Record<FailureReason, string> = {
  AUTH_EXPIRED: '帳號授權過期',
  AUTH_INVALID: '帳號授權失效',
  PLATFORM_UNAVAILABLE: '平台暫時無法連線',
  CONTENT_REJECTED: '內容不符合平台限制',
  TIMEOUT: '發佈逾時',
  OTHER: '其他',
}

/** 依代碼查中文；遇到對照表沒有的新代碼時顯示「未知」而不是英文代碼 */
export function label(table: Record<string, string>, code: string | null | undefined): string {
  if (!code) return '—'
  return table[code] ?? '未知'
}

export const ACTOR_TYPE_LABELS: Record<string, string> = {
  user: '使用者',
  system: '系統',
}

export const IMAGE_VARIANT_LABELS: Record<string, string> = {
  original: '原圖',
  instagram: 'Instagram 版本',
}

/** 預覽的提醒（BR-46） */
export const PREVIEW_WARNING_LABELS: Record<string, string> = {
  CONTENT_TOO_LONG: '超過字數上限',
  AUTH_INVALID: '授權失效，需重新連結',
  IMAGE_CROPPED: 'Instagram 會使用裁切後的圖片',
}

/** 發佈紀錄變更原因（《資料模型》§2.4） */
export const HISTORY_REASON_LABELS: Record<string, string> = {
  SCHEDULE_SET: '設定排程',
  PUBLISH_NOW: '立即發佈',
  TARGET_ADDED: '新增目標平台帳號',
  TARGET_MODIFIED: '修改目標平台帳號',
  TARGET_ACCOUNT_REMOVED: '目標平台帳號已移除',
  SCHEDULE_CANCELLED: '取消排程',
  RESCHEDULED: '重新排程',
  POST_DELETED: '刪除貼文',
  PUBLISH_SUCCEEDED: '發佈貼文：成功',
  PUBLISH_FAILED: '發佈貼文：失敗',
  RETRY_STARTED: '重試發佈：開始',
  RETRY_SUCCEEDED: '重試發佈：成功',
  RETRY_FAILED: '重試發佈：失敗',
  RECOVERY_CONFIRMED_PUBLISHED: '發佈逾時恢復：已確認發佈',
  RECOVERY_CONFIRMED_NOT_PUBLISHED: '發佈逾時恢復：確認未發佈',
  RECOVERY_UNCONFIRMED: '發佈逾時恢復：無法確認',
  AUTO_RETRY_STARTED: '自動重試發佈：開始',
  AUTO_RETRY_SUCCEEDED: '自動重試發佈：成功',
  AUTO_RETRY_FAILED: '自動重試發佈：失敗',
}

/** 稽核操作類型（《資料模型》§2.5） */
export const AUDIT_ACTION_LABELS: Record<string, string> = {
  LOGIN: '登入',
  LOGOUT: '登出',
  LOGOUT_ALL: '登出所有裝置',
  USER_CREATE: '建立幹部帳號',
  USER_ROLE_CHANGE: '調整角色',
  USER_DISABLE: '停用帳號',
  USER_ENABLE: '啟用帳號',
  USER_UNLOCK: '解除鎖定',
  PLATFORM_LINK: '連結平台帳號',
  PLATFORM_RELINK: '重新連結平台帳號',
  PLATFORM_REMOVE: '移除平台帳號',
  POST_PUBLISH: '發佈貼文',
  POST_SCHEDULE: '設定排程',
  SCHEDULE_CANCEL: '取消排程',
  PUBLISH_RETRY: '重試發佈',
  PUBLISH_AUTO_RETRY: '自動重試發佈',
  POST_COPY: '複製為新草稿',
}

/** 稽核查詢的「操作類型」篩選：一般稽核操作，加上登入失敗與平台帳號連結失敗 */
export const AUDIT_FILTER_ACTIONS: Record<string, string> = {
  ...AUDIT_ACTION_LABELS,
  LOGIN_FAILED: '登入失敗',
  LINK_FAILED: '連結平台帳號失敗',
  RELINK_FAILED: '重新連結平台帳號失敗',
}

export const AUDIT_KIND_LABELS: Record<string, string> = {
  audit: '操作',
  login_security: '登入安全',
  platform_auth: '平台授權',
}

export const TARGET_TYPE_LABELS: Record<string, string> = {
  user_account: '使用者帳號',
  platform_account: '平台帳號',
  post: '貼文',
}

export const TARGET_RESULT_STATUS_LABELS: Record<string, string> = {
  SUCCEEDED: '成功',
  FAILED: '失敗',
  NOT_RETRIED: '未重試',
}

export const SKIP_REASON_LABELS: Record<string, string> = {
  ALREADY_SUCCEEDED: '先前已成功',
  AUTH_INVALID_SKIPPED: '授權失效而跳過',
  REMOVED_SKIPPED: '已移除而跳過',
}

export const LOGIN_FAILURE_LABELS: Record<string, string> = {
  WRONG_PASSWORD: '密碼錯誤',
  ACCOUNT_DISABLED: '帳號停用',
  ACCOUNT_LOCKED: '帳號鎖定',
  ACCOUNT_NOT_FOUND: '帳號不存在',
}

export const PLATFORM_AUTH_EVENT_LABELS: Record<string, string> = {
  LINK_FAILED: '連結平台帳號失敗',
  RELINK_FAILED: '重新連結平台帳號失敗',
}

export const PLATFORM_AUTH_FAILURE_LABELS: Record<string, string> = {
  PLATFORM_AUTH_FAILED: '平台授權失敗',
  WEBHOOK_INVALID: 'Webhook 驗證無效',
  VERIFICATION_UNAVAILABLE: '暫時無法驗證',
  PLATFORM_ID_MISMATCH: '平台帳號識別碼不一致',
}
