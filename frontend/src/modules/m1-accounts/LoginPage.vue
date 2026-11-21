<script setup lang="ts">
import type { FormInstance, FormRules } from 'element-plus'
import { reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { errorMessage } from '@/shared/api/errors'
import { useAuthStore } from '@/shared/auth'

const auth = useAuthStore()
const route = useRoute()
const router = useRouter()

const formRef = ref<FormInstance>()
const form = reactive({ email: '', password: '' })
const submitting = ref(false)
const error = ref('')
const expired = route.query.expired === '1'
// 平台授權（OAuth）會整頁離開；回來時若無法用 Cookie 恢復登入，才會停在這裡
const fromOAuth = typeof route.query.redirect === 'string' && route.query.redirect.includes('result=')

const rules: FormRules = {
  email: [{ required: true, message: '請輸入 Email', trigger: 'blur' }],
  password: [{ required: true, message: '請輸入密碼', trigger: 'blur' }],
}

/** 只接受站內路徑，避免登入後被導到外部網站 */
function safeRedirect(value: unknown): string {
  return typeof value === 'string' && value.startsWith('/') && !value.startsWith('//') ? value : '/posts'
}

async function submit() {
  if (!(await formRef.value?.validate().catch(() => false))) return
  submitting.value = true
  error.value = ''
  try {
    await auth.login(form.email, form.password)
    await router.replace(safeRedirect(route.query.redirect))
  } catch (e) {
    error.value = errorMessage(e)
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <div class="login">
    <el-card class="login-card" shadow="never">
      <h1>mediagent</h1>
      <p class="muted">社團貼文一次同步到 Discord、Threads、Instagram</p>
      <el-alert
        v-if="fromOAuth && !error"
        type="info"
        title="已從平台授權頁回來，登入後會顯示連結結果"
        :closable="false"
        show-icon
        class="alert"
      />
      <el-alert
        v-else-if="expired && !error"
        type="warning"
        title="登入已失效，請重新登入"
        :closable="false"
        show-icon
        class="alert"
      />
      <el-alert v-if="error" type="error" :title="error" :closable="false" show-icon class="alert" />
      <el-form ref="formRef" :model="form" :rules="rules" label-position="top" @submit.prevent="submit">
        <el-form-item label="Email" prop="email">
          <el-input v-model="form.email" type="email" autocomplete="username" placeholder="name@club.org" />
        </el-form-item>
        <el-form-item label="密碼" prop="password">
          <el-input v-model="form.password" type="password" autocomplete="current-password" show-password />
        </el-form-item>
        <el-button type="primary" native-type="submit" :loading="submitting" class="submit">登入</el-button>
      </el-form>
    </el-card>
  </div>
</template>

<style scoped>
.login {
  min-height: 100vh;
  display: grid;
  place-items: center;
  padding: 16px;
  box-sizing: border-box;
}

.login-card {
  width: 100%;
  max-width: 380px;
}

h1 {
  margin: 0 0 4px;
  color: var(--el-color-primary);
}

.alert {
  margin: 12px 0;
}

.submit {
  width: 100%;
  margin-top: 8px;
}
</style>
