/**
 * API client：所有請求都經過這裡。
 * - 附加 Access Token 與 X-Request-Id
 * - 把後端的 {code, message, request_id} 錯誤轉成 ApiError（訊息已是中文）
 * - 401 時通知登入狀態清除並導回登入頁（換發 Token 的 /auth/refresh 尚未提供）
 */

import axios, { AxiosError, type AxiosRequestConfig } from 'axios'

import { ApiError, type ErrorBody } from './errors'

export const API_PREFIX = '/api/v1'

interface AuthHooks {
  getToken: () => string | null
  onUnauthenticated: () => void
}

let hooks: AuthHooks = { getToken: () => null, onUnauthenticated: () => {} }

/** 由 main.ts 接上登入狀態，避免 client、store、router 互相 import */
export function installAuthHooks(next: AuthHooks): void {
  hooks = next
}

const http = axios.create({ baseURL: API_PREFIX, timeout: 20_000 })

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
  (error: AxiosError) => {
    const response = error.response
    if (!response) {
      return Promise.reject(new ApiError(0, { code: 'NETWORK_ERROR', message: '' }))
    }
    const body: ErrorBody = isErrorBody(response.data)
      ? response.data
      : { code: response.status >= 500 ? 'INTERNAL_ERROR' : 'VALIDATION_ERROR', message: '' }
    const apiError = new ApiError(response.status, body)
    // 登入本身的 401 是帳密錯誤，不是登入失效
    if (response.status === 401 && body.code === 'UNAUTHENTICATED') {
      hooks.onUnauthenticated()
    }
    return Promise.reject(apiError)
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
