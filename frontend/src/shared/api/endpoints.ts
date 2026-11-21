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

export const authApi = {
  login: (email: string, password: string) =>
    api.post<LoginResponse>('/auth/login', { email, password } satisfies Schemas['LoginRequest']),
  me: () => api.get<CurrentUser>('/auth/me'),
  logout: () => api.post<void>('/auth/logout'),
}

export const usersApi = {
  list: () => api.get<Schemas['UserList']>('/users'),
  create: (data: UserCreate) => api.post<UserDetail>('/users', data),
  setStatus: (id: number, status: Schemas['UserStatusUpdate']['status']) =>
    api.put<UserDetail>(`/users/${id}/status`, { status } satisfies Schemas['UserStatusUpdate']),
}

export const platformAccountsApi = {
  list: () => api.get<Schemas['PlatformAccountList']>('/platform-accounts'),
  linkDiscord: (data: PlatformAccountCreate) => api.post<PlatformAccount>('/platform-accounts', data),
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
}
