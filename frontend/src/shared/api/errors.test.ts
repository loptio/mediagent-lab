import { describe, expect, it } from 'vitest'

import { ApiError, describeError, errorMessage } from './errors'

describe('describeError', () => {
  it('錯誤碼轉成中文提示', () => {
    expect(describeError({ code: 'SCHEDULE_TIME_NOT_ALIGNED', message: 'x' })).toContain('5 分鐘整')
  })

  it('沒有對照的錯誤碼改用後端的 message', () => {
    expect(describeError({ code: 'SOMETHING_NEW', message: '後端的說明' })).toBe('後端的說明')
  })

  it('字數超過時帶出平台與字數', () => {
    const text = describeError({
      code: 'CONTENT_TOO_LONG',
      message: 'x',
      detail: { platform: 'threads', limit: 500, length: 542 },
    })
    expect(text).toBe('貼文超過 Threads 的字數上限（542／500）')
  })

  it('授權失效時列出平台帳號名稱', () => {
    const text = describeError({ code: 'TARGET_AUTH_INVALID', message: 'x', detail: { accounts: ['社團公告'] } })
    expect(text).toContain('社團公告')
  })

  it('沒有可重試的紀錄時說明每個平台帳號的原因', () => {
    const text = describeError({
      code: 'NOTHING_TO_RETRY',
      message: 'x',
      detail: {
        hints: [
          { platform_account_id: 1, account_name: '公告', reason: 'AUTH_INVALID_SKIPPED' },
          { platform_account_id: 2, account_name: '舊帳號', reason: 'REMOVED_SKIPPED' },
        ],
      },
    })
    expect(text).toContain('「公告」請管理員重新連結')
    expect(text).toContain('「舊帳號」帳號已移除')
  })
})

describe('ApiError', () => {
  it('保留錯誤碼與 request_id，訊息為中文', () => {
    const error = new ApiError(409, { code: 'EMAIL_TAKEN', message: 'x', request_id: 'abc' })
    expect(error.code).toBe('EMAIL_TAKEN')
    expect(error.requestId).toBe('abc')
    expect(errorMessage(error)).toBe('這個 Email 已經有帳號了')
  })

  it('非 API 錯誤顯示通用訊息', () => {
    expect(errorMessage(new Error('boom'))).toContain('未預期')
  })
})
