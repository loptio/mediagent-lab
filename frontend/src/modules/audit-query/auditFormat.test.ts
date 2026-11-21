import { describe, expect, it } from 'vitest'

import type { AuditEvent } from '@/shared/api/endpoints'

import { toRow } from './auditFormat'

const lookup = {
  user: (id: number) => ({ 1: '社長', 3: '公關' })[id],
  platformAccount: (id: number) => ({ 7: 'Instagram・guitar_club' })[id],
}

describe('稽核紀錄轉成中文', () => {
  it('系統執行的排程發佈：結果與各平台帳號的結果', () => {
    const event = {
      kind: 'audit',
      id: 501,
      event_seq: 9821,
      occurred_at: '2026-10-06T04:00:03Z',
      actor_type: 'system',
      actor: null,
      action: 'POST_PUBLISH',
      target: { type: 'post', id: 42 },
      details: { scheduled_by: 3, result: 'PARTIALLY_FAILED' },
      target_results: [
        { platform_account_id: 7, status: 'FAILED', failure_reason: 'PLATFORM_UNAVAILABLE', skip_reason: null },
        { platform_account_id: 9, status: 'NOT_RETRIED', failure_reason: null, skip_reason: 'ALREADY_SUCCEEDED' },
      ],
    } as AuditEvent

    const row = toRow(event, lookup)

    expect(row).toMatchObject({ actor: '系統', action: '發佈貼文', target: '貼文 #42', postId: 42 })
    expect(row.details).toEqual([
      '結果：部分失敗',
      '排程設定者：公關',
      'Instagram・guitar_club：失敗（平台暫時無法連線）',
      '平台帳號 #9：未重試（先前已成功）',
    ])
  })

  it('以使用者帳號為對象的操作顯示姓名', () => {
    const event = {
      kind: 'audit',
      id: 1,
      event_seq: 1,
      occurred_at: '2026-10-06T04:00:00Z',
      actor_type: 'user',
      actor: { id: 1, email: 'admin@club.org', name: '社長' },
      action: 'USER_ROLE_CHANGE',
      target: { type: 'user_account', id: 3 },
      details: {},
      target_results: [],
    } as AuditEvent

    expect(toRow(event, lookup)).toMatchObject({ actor: '社長', action: '調整角色', target: '公關', postId: null })
  })

  it('登入失敗：沒有操作者，顯示原因與輸入的 Email', () => {
    const event = {
      kind: 'login_security',
      id: 2,
      event_seq: 2,
      occurred_at: '2026-10-06T04:00:00Z',
      event_type: 'LOGIN_FAILED',
      failure_reason: 'ACCOUNT_NOT_FOUND',
      attempted_email: 'nobody@club.org',
      account: null,
    } as AuditEvent

    const row = toRow(event, lookup)
    expect(row).toMatchObject({ actor: '—', action: '登入失敗', target: 'nobody@club.org' })
    expect(row.details[0]).toBe('原因：帳號不存在')
  })

  it('平台帳號連結失敗', () => {
    const event = {
      kind: 'platform_auth',
      id: 3,
      event_seq: 3,
      occurred_at: '2026-10-06T04:00:00Z',
      actor_type: 'user',
      actor: { id: 1, email: 'admin@club.org', name: '社長' },
      event_type: 'RELINK_FAILED',
      platform: 'threads',
      account_name: 'club',
      platform_account_id: 5,
      failure_reason: 'PLATFORM_ID_MISMATCH',
    } as AuditEvent

    expect(toRow(event, lookup)).toMatchObject({
      actor: '社長',
      action: '重新連結平台帳號失敗',
      target: 'Threads・club',
      details: ['原因：平台帳號識別碼不一致'],
    })
  })
})
