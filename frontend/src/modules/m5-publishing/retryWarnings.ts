/**
 * 重試前的提醒（BR-32）：Discord Webhook 沒有「查詢是否已發出」的方法，
 * 失敗原因是逾時或平台無法連線時，訊息可能其實已經送出，重試會重複發文。
 */

import type { PublishRecord } from '@/shared/api/endpoints'

const UNCERTAIN_REASONS = new Set(['TIMEOUT', 'PLATFORM_UNAVAILABLE'])

export interface RetryPlan {
  /** 會重送的紀錄：失敗、帳號未移除且授權有效（與後端重試規則相同，BR-34） */
  retry: PublishRecord[]
  /** 不會重送的紀錄：已成功、帳號已移除或授權失效 */
  skipped: PublishRecord[]
  /** 需要先到 Discord 頻道確認的紀錄 */
  needsChannelCheck: PublishRecord[]
}

export function planRetry(records: PublishRecord[], invalidAccountIds: Set<number> = new Set()): RetryPlan {
  const retry = records.filter(
    (r) => r.status === 'FAILED' && !r.platform_account.removed && !invalidAccountIds.has(r.platform_account.id),
  )
  const skipped = records.filter((r) => !retry.includes(r))
  const needsChannelCheck = retry.filter(
    (r) => r.platform_account.platform === 'discord' && UNCERTAIN_REASONS.has(r.failure_reason ?? ''),
  )
  return { retry, skipped, needsChannelCheck }
}
