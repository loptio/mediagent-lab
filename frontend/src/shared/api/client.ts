/**
 * API client：所有請求都經過這裡。
 * - 附加 Access Token 與 X-Request-Id
 * - 把後端的 {code, message, request_id} 錯誤轉成 ApiError（訊息已是中文）
 * - 收到 401 時先用 Refresh Token Cookie 換發一次 Access Token 並重送原本的請求；
 *   換發也失敗（登出、停用、超過 7 天）才通知登入狀態清除並導回登入頁
 */

import axios, { AxiosError, type AxiosRequestConfig, type InternalAxiosRequestConfig } from 'axios'

import { ApiError, type ErrorBody } from './errors'

export const API_PREFIX = '/api/v1'

interface AuthHooks {
  getToken: () => string | null
  /** 換發 Access Token，成功回傳 true */
  refresh: () => Promise<boolean>
  onUnauthenticated: () => void
}

let hooks: AuthHooks = {
  getToken: () => null,
  refresh: async () => false,
  onUnauthenticated: () => {},
}

/** 由 main.ts 接上登入狀態，避免 client、store、router 互相 import */
export function installAuthHooks(next: AuthHooks): void {
  hooks = next
}

// 這兩個端點收到 401 代表帳密錯誤或 Refresh Token 無效，不能再拿去換發，否則會無限循環
const NO_REFRESH_PATHS = new Set(['/auth/login', '/auth/refresh'])

interface RetriableConfig extends InternalAxiosRequestConfig {
  _retried?: boolean
}

let refreshing: Promise<boolean> | null = null

/** 同時有好幾個請求收到 401（例如輪詢中 Token 到期）時，只換發一次，大家共用結果 */
function refreshOnce(): Promise<boolean> {
  refreshing ??= hooks
    .refresh()
    .catch(() => false)
    .finally(() => {
      refreshing = null
    })
  return refreshing
}

export const http = axios.create({ baseURL: API_PREFIX, timeout: 20_000 })

http.interceptors.request.use((config) => {
  const token = hooks.getToken()
  if (token) config.headers.set('Authorization', `Bearer ${token}`)
  config.headers.set('X-Request-Id', crypto.randomUUID())
  return config
})

function isErrorBody(data: unknown): data is ErrorBody {
  return typeof data === 'object' && data !== null && typeof (data as ErrorBody).code === 'string'
}

http.interceptors.response.use(
  (response) => response,
  async (error: AxiosError) => {
    const response = error.response
    if (!response) {
      throw new ApiError(0, { code: 'NETWORK_ERROR', message: '' })
    }
    const body: ErrorBody = isErrorBody(response.data)
      ? response.data
      : { code: response.status >= 500 ? 'INTERNAL_ERROR' : 'VALIDATION_ERROR', message: '' }

    if (response.status === 401 && body.code === 'UNAUTHENTICATED') {
      const config = error.config as RetriableConfig | undefined
      const canRefresh = !!config && !NO_REFRESH_PATHS.has(config.url ?? '')
      if (canRefresh && !config._retried && (await refreshOnce())) {
        // 換發成功：用新的 Token 重送一次（request interceptor 會換上新的 Authorization）
        config._retried = true
        return http.request(config)
      }
      if (canRefresh) hooks.onUnauthenticated()
    }
    throw new ApiError(response.status, body)
  },
)

async function request<T>(config: AxiosRequestConfig): Promise<T> {
  const response = await http.request<T>(config)
  return response.data
}

export const api = {
  get: <T>(url: string, params?: Record<string, unknown>) => request<T>({ method: 'GET', url, params }),
  post: <T>(url: string, data?: unknown) => request<T>({ method: 'POST', url, data }),
  put: <T>(url: string, data?: unknown) => request<T>({ method: 'PUT', url, data }),
  patch: <T>(url: string, data?: unknown) => request<T>({ method: 'PATCH', url, data }),
  delete: <T>(url: string) => request<T>({ method: 'DELETE', url }),
}
