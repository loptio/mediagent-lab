/** 登入狀態（Pinia）：只存目前使用者與 Access Token，放在記憶體，不寫進 localStorage。 */

import { defineStore } from 'pinia'
import { computed, ref } from 'vue'

import { authApi, type CurrentUser } from './api/endpoints'
import type { Role } from './labels'

/** 角色高低：管理員 ⊃ 發佈者 ⊃ 撰稿者（與後端 auth.has_role 相同） */
const ROLE_RANK: Record<Role, number> = { writer: 1, publisher: 2, admin: 3 }

export const useAuthStore = defineStore('auth', () => {
  const token = ref<string | null>(null)
  const user = ref<CurrentUser | null>(null)
  const expiresAt = ref<number>(0)

  const isLoggedIn = computed(() => token.value !== null && Date.now() < expiresAt.value)
  const role = computed(() => (user.value?.role ?? null) as Role | null)

  function hasRole(minimum: Role): boolean {
    return role.value !== null && ROLE_RANK[role.value] >= ROLE_RANK[minimum]
  }

  async function login(email: string, password: string): Promise<void> {
    const result = await authApi.login(email, password)
    token.value = result.access_token
    user.value = result.user
    expiresAt.value = Date.now() + result.expires_in * 1000
  }

  function clear(): void {
    token.value = null
    user.value = null
    expiresAt.value = 0
  }

  async function logout(): Promise<void> {
    try {
      await authApi.logout()
    } finally {
      clear()
    }
  }

  return { token, user, role, isLoggedIn, hasRole, login, logout, clear }
})
