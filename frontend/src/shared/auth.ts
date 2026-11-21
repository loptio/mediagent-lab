/**
 * 登入狀態（Pinia）：只存目前使用者與 Access Token，放在記憶體，不寫進 localStorage。
 * Refresh Token 由後端放在 HttpOnly Cookie，JavaScript 讀不到；需要時呼叫 /auth/refresh 換發。
 */

import { defineStore } from 'pinia'
import { computed, ref } from 'vue'

import { authApi, type CurrentUser } from './api/endpoints'
import type { Role } from './labels'

/** 角色高低：管理員 ⊃ 發佈者 ⊃ 撰稿者（與後端 auth.has_role 相同） */
const ROLE_RANK: Record<Role, number> = { writer: 1, publisher: 2, admin: 3 }

export const useAuthStore = defineStore('auth', () => {
  const token = ref<string | null>(null)
  const user = ref<CurrentUser | null>(null)

  const isLoggedIn = computed(() => token.value !== null && user.value !== null)
  const role = computed(() => (user.value?.role ?? null) as Role | null)

  function hasRole(minimum: Role): boolean {
    return role.value !== null && ROLE_RANK[role.value] >= ROLE_RANK[minimum]
  }

  async function login(email: string, password: string): Promise<void> {
    const result = await authApi.login(email, password)
    token.value = result.access_token
    user.value = result.user
  }

  /** 用 Refresh Token Cookie 換發 Access Token；登出、停用或超過有效期限時回傳 false */
  async function refresh(): Promise<boolean> {
    try {
      const result = await authApi.refresh()
      token.value = result.access_token
      return true
    } catch {
      return false
    }
  }

  let restoring: Promise<boolean> | null = null

  /** 重新整理頁面、或從平台授權頁回來時，記憶體裡沒有登入狀態：用 Cookie 恢復登入 */
  function restore(): Promise<boolean> {
    restoring ??= (async () => {
      if (!(await refresh())) return false
      try {
        user.value = await authApi.me()
        return true
      } catch {
        clear()
        return false
      }
    })().finally(() => {
      restoring = null
    })
    return restoring
  }

  function clear(): void {
    token.value = null
    user.value = null
  }

  async function logout(): Promise<void> {
    try {
      await authApi.logout()
    } finally {
      clear()
    }
  }

  return { token, user, role, isLoggedIn, hasRole, login, refresh, restore, logout, clear }
})
