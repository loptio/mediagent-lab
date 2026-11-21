/** 稽核紀錄的顯示文字：三種紀錄（audit、login_security、platform_auth）共用欄位，各自的內容轉成中文。 */

import type { AuditEvent } from '@/shared/api/endpoints'
import {
  AUDIT_ACTION_LABELS,
  FAILURE_REASON_LABELS,
  label,
  LOGIN_FAILURE_LABELS,
  PLATFORM_AUTH_EVENT_LABELS,
  PLATFORM_AUTH_FAILURE_LABELS,
  PLATFORM_LABELS,
  POST_STATUS_LABELS,
  SKIP_REASON_LABELS,
  TARGET_RESULT_STATUS_LABELS,
  TARGET_TYPE_LABELS,
} from '@/shared/labels'

export interface NameLookup {
  user: (id: number) => string | undefined
  platformAccount: (id: number) => string | undefined
}

export interface AuditRow {
  key: string
  occurredAt: string
  kind: AuditEvent['kind']
  actor: string
  action: string
  target: string
  /** 貼文可以點過去看 */
  postId: number | null
  details: string[]
}

function accountName(lookup: NameLookup, id: number): string {
  return lookup.platformAccount(id) ?? `平台帳號 #${id}`
}

export function toRow(event: AuditEvent, lookup: NameLookup): AuditRow {
  const base = { key: `${event.kind}-${event.id}`, occurredAt: event.occurred_at, kind: event.kind }

  if (event.kind === 'login_security') {
    return {
      ...base,
      actor: '—',
      action: '登入失敗',
      target: event.account ? `${event.account.name}（${event.account.email}）` : event.attempted_email,
      postId: null,
      details: [`原因：${label(LOGIN_FAILURE_LABELS, event.failure_reason)}`, `輸入的 Email：${event.attempted_email}`],
    }
  }

  if (event.kind === 'platform_auth') {
    const platform = label(PLATFORM_LABELS, event.platform)
    return {
      ...base,
      actor: event.actor.name,
      action: label(PLATFORM_AUTH_EVENT_LABELS, event.event_type),
      target: event.account_name ? `${platform}・${event.account_name}` : platform,
      postId: null,
      details: [`原因：${label(PLATFORM_AUTH_FAILURE_LABELS, event.failure_reason)}`],
    }
  }

  // 一般稽核紀錄
  const { target } = event
  let targetText = `${label(TARGET_TYPE_LABELS, target.type)} #${target.id}`
  if (target.type === 'post') targetText = `貼文 #${target.id}`
  if (target.type === 'user_account') targetText = lookup.user(target.id) ?? targetText
  if (target.type === 'platform_account') targetText = accountName(lookup, target.id)

  const details: string[] = []
  const d = event.details ?? {}
  if (typeof d.result === 'string') details.push(`結果：${label(POST_STATUS_LABELS, d.result)}`)
  if (typeof d.reason === 'string' && d.reason) details.push(`原因：${d.reason}`)
  if (typeof d.related_post_id === 'number') details.push(`相關貼文 #${d.related_post_id}`)
  if (typeof d.scheduled_by === 'number') details.push(`排程設定者：${lookup.user(d.scheduled_by) ?? `#${d.scheduled_by}`}`)
  for (const result of event.target_results ?? []) {
    let text = `${accountName(lookup, result.platform_account_id)}：${label(TARGET_RESULT_STATUS_LABELS, result.status)}`
    if (result.failure_reason) text += `（${label(FAILURE_REASON_LABELS, result.failure_reason)}）`
    if (result.skip_reason) text += `（${label(SKIP_REASON_LABELS, result.skip_reason)}）`
    details.push(text)
  }

  return {
    ...base,
    actor: event.actor_type === 'system' ? '系統' : (event.actor?.name ?? '—'),
    action: label(AUDIT_ACTION_LABELS, event.action),
    target: targetText,
    postId: target.type === 'post' ? target.id : null,
    details,
  }
}
