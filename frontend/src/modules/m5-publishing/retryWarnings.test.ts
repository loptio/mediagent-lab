import { describe, expect, it } from 'vitest'

import type { PublishRecord } from '@/shared/api/endpoints'

import { planRetry } from './retryWarnings'

function record(
  id: number,
  platform: string,
  status: string,
  failure_reason: string | null = null,
  removed = false,
): PublishRecord {
  return {
    id,
    platform_account: { id: id * 10, platform, account_name: `帳號${id}`, removed },
    status,
    published_at: null,
    platform_post_url: null,
    failure_reason,
  }
}

describe('planRetry', () => {
  it('只重送失敗且未移除、授權有效的紀錄', () => {
    const records = [
      record(1, 'discord', 'SUCCEEDED'),
      record(2, 'threads', 'FAILED', 'OTHER'),
      record(3, 'threads', 'FAILED', 'OTHER', true),
      record(4, 'threads', 'FAILED', 'AUTH_EXPIRED'),
    ]
    const plan = planRetry(records, new Set([40]))
    expect(plan.retry.map((r) => r.id)).toEqual([2])
    expect(plan.skipped.map((r) => r.id)).toEqual([1, 3, 4])
  })

  it('Discord 逾時或無法連線時要求先到頻道確認', () => {
    const plan = planRetry([
      record(1, 'discord', 'FAILED', 'TIMEOUT'),
      record(2, 'discord', 'FAILED', 'PLATFORM_UNAVAILABLE'),
      record(3, 'discord', 'FAILED', 'CONTENT_REJECTED'),
      record(4, 'threads', 'FAILED', 'TIMEOUT'),
    ])
    expect(plan.needsChannelCheck.map((r) => r.id)).toEqual([1, 2])
  })
})
