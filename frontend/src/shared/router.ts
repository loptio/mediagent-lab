/** 路由與角色守衛（《系統架構設計》§10.2）。路由 meta 標註最低角色；真正的權限檢查在後端。 */

import { ElMessage } from 'element-plus'
import { createRouter, createWebHistory } from 'vue-router'

import { useAuthStore } from './auth'
import type { Role } from './labels'

declare module 'vue-router' {
  interface RouteMeta {
    public?: boolean
    minRole?: Role
    title?: string
  }
}

export const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: '/login',
      name: 'login',
      component: () => import('@/modules/m1-accounts/LoginPage.vue'),
      meta: { public: true, title: '登入' },
    },
    {
      path: '/',
      component: () => import('./layout/AppLayout.vue'),
      children: [
        { path: '', redirect: { name: 'posts' } },
        {
          path: 'posts',
          name: 'posts',
          component: () => import('@/modules/m3-posts/PostListPage.vue'),
          meta: { title: '貼文' },
        },
        {
          path: 'posts/new',
          name: 'post-new',
          component: () => import('@/modules/m3-posts/PostEditPage.vue'),
          meta: { title: '新增貼文' },
        },
        {
          path: 'posts/:id(\\d+)',
          name: 'post-edit',
          component: () => import('@/modules/m3-posts/PostEditPage.vue'),
          props: (route) => ({ id: Number(route.params.id) }),
          meta: { title: '編輯貼文' },
        },
        {
          path: 'platform-accounts',
          name: 'platform-accounts',
          component: () => import('@/modules/m2-platforms/PlatformAccountsPage.vue'),
          meta: { title: '平台帳號' },
        },
        {
          path: 'users',
          name: 'users',
          component: () => import('@/modules/m1-accounts/UsersPage.vue'),
          meta: { title: '幹部帳號', minRole: 'admin' },
        },
        {
          path: 'audit',
          name: 'audit',
          component: () => import('@/modules/audit-query/AuditPage.vue'),
          meta: { title: '稽核紀錄', minRole: 'admin' },
        },
      ],
    },
    { path: '/:pathMatch(.*)*', redirect: { name: 'posts' } },
  ],
})

router.beforeEach(async (to) => {
  const auth = useAuthStore()
  if (to.meta.public) return true
  // 記憶體裡沒有登入狀態（重新整理頁面、從平台授權頁回來）時，先用 Refresh Token Cookie 恢復
  if (!auth.isLoggedIn && !(await auth.restore())) {
    return { name: 'login', query: { redirect: to.fullPath } }
  }
  if (to.meta.minRole && !auth.hasRole(to.meta.minRole)) {
    ElMessage.warning('你的角色沒有權限查看這個頁面')
    return { name: 'posts' }
  }
  return true
})

router.afterEach((to) => {
  document.title = to.meta.title ? `${to.meta.title}｜mediagent` : 'mediagent 社團貼文同步'
})

/** API 回傳 401 且換發 Access Token 也失敗：清除登入狀態，帶著目前頁面導回登入 */
export function redirectToLogin(): void {
  const auth = useAuthStore()
  auth.clear()
  const current = router.currentRoute.value
  if (current.name === 'login') return
  void router.push({ name: 'login', query: { redirect: current.fullPath, expired: '1' } })
}
