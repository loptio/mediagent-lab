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
