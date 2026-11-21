import { AxiosError, AxiosHeaders, type AxiosResponse, type InternalAxiosRequestConfig } from 'axios'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { api, http, installAuthHooks } from './client'
import { ApiError } from './errors'

/** 假的後端：只有帶著 validToken 的請求成功，其他回 401 UNAUTHENTICATED */
let validToken = 'new-token'
let currentToken: string | null = 'old-token'
const seen: { url?: string; auth?: string }[] = []

function respond(config: InternalAxiosRequestConfig, status: number, data: unknown): AxiosResponse {
  return { config, status, statusText: String(status), headers: {}, data }
}

http.defaults.adapter = async (config) => {
  const auth = AxiosHeaders.from(config.headers).get('Authorization') as string | undefined
  seen.push({ url: config.url, auth })
  if (config.url === '/auth/login') {
    const response = respond(config, 401, { code: 'LOGIN_FAILED', message: 'x' })
    throw new AxiosError('fail', 'ERR_BAD_REQUEST', config, null, response)
  }
  if (auth === `Bearer ${validToken}`) return respond(config, 200, { ok: true })
  const response = respond(config, 401, { code: 'UNAUTHENTICATED', message: 'x' })
  throw new AxiosError('fail', 'ERR_BAD_REQUEST', config, null, response)
}

const refresh = vi.fn<() => Promise<boolean>>()
const onUnauthenticated = vi.fn()

beforeEach(() => {
  seen.length = 0
  validToken = 'new-token'
  currentToken = 'old-token'
  refresh.mockReset()
  onUnauthenticated.mockReset()
  refresh.mockImplementation(async () => {
    currentToken = validToken
    return true
  })
  installAuthHooks({ getToken: () => currentToken, refresh, onUnauthenticated })
})

describe('Access Token 過期時換發', () => {
  it('收到 401 先換發，再用新的 Token 重送一次', async () => {
    await expect(api.get('/posts')).resolves.toEqual({ ok: true })

    expect(refresh).toHaveBeenCalledTimes(1)
    expect(seen.map((r) => r.auth)).toEqual(['Bearer old-token', 'Bearer new-token'])
    expect(onUnauthenticated).not.toHaveBeenCalled()
  })

  it('同時好幾個請求收到 401 時只換發一次', async () => {
    let release!: () => void
    refresh.mockImplementation(
      () =>
        new Promise((resolve) => {
          release = () => {
            currentToken = validToken
            resolve(true)
          }
        }),
    )

    const all = Promise.all([api.get('/posts'), api.get('/platform-accounts'), api.get('/users')])
    await vi.waitFor(() => expect(refresh).toHaveBeenCalled())
    release()

    await expect(all).resolves.toHaveLength(3)
    expect(refresh).toHaveBeenCalledTimes(1)
  })

  it('換發失敗就導回登入，並回傳 UNAUTHENTICATED', async () => {
    refresh.mockResolvedValue(false)

    await expect(api.get('/posts')).rejects.toMatchObject({ status: 401, code: 'UNAUTHENTICATED' })
    expect(onUnauthenticated).toHaveBeenCalledTimes(1)
    expect(seen).toHaveLength(1)
  })

  it('換發成功但重送仍然 401 時不再換發第二次', async () => {
    refresh.mockResolvedValue(true) // 回報成功但 Token 沒變

    await expect(api.get('/posts')).rejects.toBeInstanceOf(ApiError)
    expect(refresh).toHaveBeenCalledTimes(1)
    expect(seen).toHaveLength(2)
    expect(onUnauthenticated).toHaveBeenCalledTimes(1)
  })

  it('登入失敗與換發本身的 401 不觸發換發，也不導回登入', async () => {
    await expect(api.post('/auth/login', {})).rejects.toMatchObject({ code: 'LOGIN_FAILED' })
    await expect(api.post('/auth/refresh')).rejects.toMatchObject({ code: 'UNAUTHENTICATED' })

    expect(refresh).not.toHaveBeenCalled()
    expect(onUnauthenticated).not.toHaveBeenCalled()
  })
})
