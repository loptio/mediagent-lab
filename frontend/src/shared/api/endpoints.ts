/** 各端點的呼叫函式；請求與回應型別一律來自 schema.d.ts（由 openapi-typescript 產生，不手寫）。 */

import { api } from './client'
import type { components } from './schema'

type Schemas = components['schemas']

export type LoginResponse = Schemas['LoginResponse']
export type CurrentUser = Schemas['UserOut']
export type UserDetail = Schemas['UserDetail']
export type UserCreate = Schemas['UserCreate']
export type PlatformAccount = Schemas['PlatformAccountOut']
export type PlatformAccountCreate = Schemas['PlatformAccountCreate']
export type Post = Schemas['PostOut']
export type PostPage = Schemas['PostPage']
export type PostListItem = Schemas['PostListItem']
export type PublishRecords = Schemas['PublishRecordsOut']
export type PublishRecord = Schemas['PublishRecordOut']
export type PublishJobAccepted = Schemas['PublishJobAccepted']
export type PostImage = Schemas['ImageOut']
export type PreviewItem = Schemas['PreviewItem']
export type HistoryItem = Schemas['HistoryItem']
export type EventPage = Schemas['EventPage']
export type AuditEvent = EventPage['items'][number]

export const authApi = {
  login: (email: string, password: string) =>
    api.post<LoginResponse>('/auth/login', { email, password } satisfies Schemas['LoginRequest']),
  /** 用登入時設定的 HttpOnly Cookie 換發 Access Token（不需要帶 body） */
  refresh: () => api.post<Schemas['TokenRefreshed']>('/auth/refresh'),
  me: () => api.get<CurrentUser>('/auth/me'),
  logout: () => api.post<void>('/auth/logout'),
  logoutAll: () => api.post<void>('/auth/logout-all'),
}

export const usersApi = {
  list: () => api.get<Schemas['UserList']>('/users'),
  create: (data: UserCreate) => api.post<UserDetail>('/users', data),
  setStatus: (id: number, status: Schemas['UserStatusUpdate']['status']) =>
    api.put<UserDetail>(`/users/${id}/status`, { status } satisfies Schemas['UserStatusUpdate']),
  setRole: (id: number, role: Schemas['RoleUpdate']['role']) =>
    api.patch<UserDetail>(`/users/${id}`, { role } satisfies Schemas['RoleUpdate']),
  unlock: (id: number) => api.delete<UserDetail>(`/users/${id}/lock`),
}

export const platformAccountsApi = {
  list: () => api.get<Schemas['PlatformAccountList']>('/platform-accounts'),
  linkDiscord: (data: PlatformAccountCreate) => api.post<PlatformAccount>('/platform-accounts', data),
  relinkDiscord: (id: number, webhookUrl: string) =>
    api.put<PlatformAccount>(`/platform-accounts/${id}/credential`, {
      webhook_url: webhookUrl,
    } satisfies Schemas['WebhookRelink']),
  remove: (id: number) => api.delete<void>(`/platform-accounts/${id}`),
  startOAuth: (platform: string, platformAccountId?: number) =>
    api.post<Schemas['OAuthStarted']>('/platform-accounts/oauth-authorizations', {
      platform,
      platform_account_id: platformAccountId ?? null,
    } satisfies Schemas['OAuthStart']),
}

export interface PostListQuery {
  status?: string
  page: number
  page_size: number
}

export const postsApi = {
  list: (query: PostListQuery) => api.get<PostPage>('/posts', { ...query }),
  get: (id: number) => api.get<Post>(`/posts/${id}`),
  create: (content: string) => api.post<Post>('/posts', { content } satisfies Schemas['PostCreate']),
  update: (id: number, content: string) =>
    api.patch<Post>(`/posts/${id}`, { content } satisfies Schemas['PostUpdate']),
  remove: (id: number) => api.delete<void>(`/posts/${id}`),
  setTargets: (id: number, platformAccountIds: number[]) =>
    api.put<Schemas['TargetsOut']>(`/posts/${id}/targets`, {
      platform_account_ids: platformAccountIds,
    } satisfies Schemas['TargetsUpdate']),
  setSchedule: (id: number, scheduledAt: string) =>
    api.put<Post>(`/posts/${id}/schedule`, { scheduled_at: scheduledAt } satisfies Schemas['ScheduleUpdate']),
  cancelSchedule: (id: number) => api.delete<Post>(`/posts/${id}/schedule`),
  publishRecords: (id: number) => api.get<PublishRecords>(`/posts/${id}/publish-records`),
  publish: (id: number, type: Schemas['PublishJobCreate']['type']) =>
    api.post<PublishJobAccepted>(`/posts/${id}/publish-jobs`, { type } satisfies Schemas['PublishJobCreate']),
  history: (id: number) => api.get<Schemas['HistoryOut']>(`/posts/${id}/publish-records/history`),
  preview: (id: number) => api.get<Schemas['PreviewOut']>(`/posts/${id}/preview`),
  copy: (id: number) => api.post<Post>(`/posts/${id}/copies`),
  attachImage: (id: number, file: File) => {
    const form = new FormData()
    form.append('file', file)
    return api.post<PostImage>(`/posts/${id}/image`, form)
  },
  removeImage: (id: number) => api.delete<void>(`/posts/${id}/image`),
}

export interface AuditQuery {
  actor_type?: 'user' | 'system'
  actor_id?: number
  account_id?: number
  action?: string
  from?: string
  to?: string
  page: number
  page_size: number
}

export const auditApi = {
  search: (query: AuditQuery) => api.get<EventPage>('/audit-events', { ...query }),
}
