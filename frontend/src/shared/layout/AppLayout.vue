<script setup lang="ts">
import { useQueryClient } from '@tanstack/vue-query'
import { ElMessage, ElMessageBox } from 'element-plus'
import { computed, ref } from 'vue'
import { RouterView, useRoute, useRouter } from 'vue-router'

import { authApi } from '../api/endpoints'
import { useAuthStore } from '../auth'
import { label, ROLE_LABELS } from '../labels'

const auth = useAuthStore()
const route = useRoute()
const router = useRouter()
const queryClient = useQueryClient()
const loggingOut = ref(false)

const menuItems = computed(() =>
  [
    { path: '/posts', title: '貼文', show: true },
    { path: '/platform-accounts', title: '平台帳號', show: true },
    { path: '/users', title: '幹部帳號', show: auth.hasRole('admin') },
    { path: '/audit', title: '稽核紀錄', show: auth.hasRole('admin') },
  ].filter((item) => item.show),
)

const activeMenu = computed(() => '/' + (route.path.split('/')[1] ?? ''))

async function logout() {
  loggingOut.value = true
  try {
    await auth.logout()
  } catch {
    // 登出 API 失敗也一樣清除本機登入狀態
  } finally {
    loggingOut.value = false
    queryClient.clear()
  }
  ElMessage.success('已登出')
  await router.push({ name: 'login' })
}

/** 登出所有裝置（FR-24）：撤銷這個帳號在每一台裝置上的登入，例如手機遺失時使用 */
async function logoutAll() {
  try {
    await ElMessageBox.confirm('會讓這個帳號在所有裝置（包含這一台）都登出。確定嗎？', '登出所有裝置', {
      confirmButtonText: '全部登出',
      cancelButtonText: '取消',
      type: 'warning',
    })
  } catch {
    return
  }
  loggingOut.value = true
  try {
    await authApi.logoutAll()
  } catch {
    // 失敗也清除本機登入狀態；錯誤由 401 處理或稍後重新登入時得知
  } finally {
    loggingOut.value = false
    auth.clear()
    queryClient.clear()
  }
  ElMessage.success('已登出所有裝置')
  await router.push({ name: 'login' })
}

function onUserCommand(command: string) {
  if (command === 'logout') void logout()
  if (command === 'logout-all') void logoutAll()
}
</script>

<template>
  <el-container class="layout">
    <el-header class="layout-header">
      <RouterLink to="/posts" class="brand">mediagent<span>社團貼文同步</span></RouterLink>
      <el-menu mode="horizontal" router :default-active="activeMenu" :ellipsis="false" class="nav">
        <el-menu-item v-for="item in menuItems" :key="item.path" :index="item.path">{{ item.title }}</el-menu-item>
      </el-menu>
      <div class="user">
        <span class="user-name">{{ auth.user?.name }}</span>
        <el-tag size="small" effect="plain">{{ label(ROLE_LABELS, auth.role) }}</el-tag>
        <el-dropdown split-button size="small" trigger="click" @click="logout" @command="onUserCommand">
          {{ loggingOut ? '登出中…' : '登出' }}
          <template #dropdown>
            <el-dropdown-menu>
              <el-dropdown-item command="logout-all">登出所有裝置</el-dropdown-item>
            </el-dropdown-menu>
          </template>
        </el-dropdown>
      </div>
    </el-header>
    <el-main class="layout-main">
      <RouterView />
    </el-main>
  </el-container>
</template>

<style scoped>
.layout {
  min-height: 100vh;
}

.layout-header {
  display: flex;
  align-items: center;
  gap: 24px;
  background: var(--el-bg-color);
  border-bottom: 1px solid var(--el-border-color-light);
  height: 56px;
}

.brand {
  font-weight: 700;
  font-size: 18px;
  color: var(--el-color-primary);
  text-decoration: none;
  white-space: nowrap;
}

.brand span {
  margin-left: 8px;
  font-size: 13px;
  font-weight: 400;
  color: var(--el-text-color-secondary);
}

.nav {
  flex: 1;
  border-bottom: none;
  height: 55px;
}

.user {
  display: flex;
  align-items: center;
  gap: 8px;
  white-space: nowrap;
}

.user-name {
  font-size: 14px;
}

.layout-main {
  padding: 0;
}

@media (max-width: 640px) {
  .brand span,
  .user-name {
    display: none;
  }
}
</style>
