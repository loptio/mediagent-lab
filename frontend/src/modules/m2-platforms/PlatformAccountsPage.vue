<script setup lang="ts">
import { useMutation, useQuery, useQueryClient } from '@tanstack/vue-query'
import { ElMessage, type FormInstance, type FormRules } from 'element-plus'
import { onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { platformAccountsApi } from '@/shared/api/endpoints'
import { ERROR_MESSAGES } from '@/shared/api/errors'
import { useAuthStore } from '@/shared/auth'
import { AUTH_STATUS_LABELS, label, PLATFORM_LABELS } from '@/shared/labels'
import QueryError from '@/shared/QueryError.vue'
import { formatTaipei } from '@/shared/time'

const auth = useAuthStore()
const route = useRoute()
const router = useRouter()
const queryClient = useQueryClient()
const isAdmin = auth.hasRole('admin')

const { data, isPending, isError, error, refetch } = useQuery({
  queryKey: ['platform-accounts'],
  queryFn: platformAccountsApi.list,
})

// ---------- 平台授權導回：後端以 /platform-accounts?result=<結果代碼> 導回（《API 設計》§3.2 #12～13） ----------
const OAUTH_RESULTS: Record<string, string> = {
  linked: '已連結平台帳號',
  relinked: '已重新連結平台帳號',
}

onMounted(() => {
  const result = route.query.result
  if (typeof result !== 'string') return
  if (OAUTH_RESULTS[result]) ElMessage.success(OAUTH_RESULTS[result])
  else ElMessage.error({ message: ERROR_MESSAGES[result] ?? '平台授權沒有完成，請再試一次', duration: 6000 })
  void router.replace({ query: {} })
})

// ---------- Threads：取得授權網址後整頁導向平台 ----------
const oauthMutation = useMutation({
  mutationFn: (args: { platform: string; accountId?: number }) =>
    platformAccountsApi.startOAuth(args.platform, args.accountId),
  onSuccess: ({ authorization_url }) => {
    window.location.assign(authorization_url)
  },
})

// ---------- Discord：輸入 Webhook 網址 ----------
// 放在 script：vue-tsc 會把屬性值裡的「//」誤判，造成假的型別錯誤
const WEBHOOK_PLACEHOLDER = 'https://discord.com/api/webhooks/…'
const discordDialog = ref(false)
const discordFormRef = ref<FormInstance>()
const discordForm = reactive({ account_name: '', webhook_url: '' })
const discordRules: FormRules = {
  account_name: [{ required: true, message: '請輸入顯示名稱', trigger: 'blur' }],
  webhook_url: [
    { required: true, message: '請貼上 Webhook 網址', trigger: 'blur' },
    {
      // 與後端 WEBHOOK_URL_PATTERN 相同（app/m2_platforms/adapters/discord.py）
      pattern: /^https:\/\/(?:discord\.com|discordapp\.com)\/api\/webhooks\/\d+\/[A-Za-z0-9_-]+$/,
      message: '網址格式應為 https://discord.com/api/webhooks/…',
      trigger: 'blur',
    },
  ],
}

function openDiscord() {
  discordForm.account_name = ''
  discordForm.webhook_url = ''
  discordDialog.value = true
}

const discordMutation = useMutation({
  mutationFn: () =>
    platformAccountsApi.linkDiscord({
      platform: 'discord',
      account_name: discordForm.account_name.trim(),
      webhook_url: discordForm.webhook_url.trim(),
    }),
  onSuccess: () => {
    ElMessage.success('已連結 Discord 頻道')
    discordDialog.value = false
    // Webhook 網址等同密碼，用完立即清掉（團隊規範 §9）
    discordForm.webhook_url = ''
    void queryClient.invalidateQueries({ queryKey: ['platform-accounts'] })
  },
})

async function submitDiscord() {
  if (!(await discordFormRef.value?.validate().catch(() => false))) return
  discordMutation.mutate()
}
</script>

<template>
  <div class="page">
    <div class="page-header">
      <h1>平台帳號</h1>
      <div v-if="isAdmin" class="toolbar">
        <el-button @click="openDiscord">連結 Discord 頻道</el-button>
        <el-button
          type="primary"
          :loading="oauthMutation.isPending.value"
          @click="oauthMutation.mutate({ platform: 'threads' })"
        >
          連結 Threads 帳號
        </el-button>
      </div>
    </div>
    <p v-if="isAdmin" class="muted intro">
      連結 Threads 會前往 Threads 授權頁，完成後自動回到這裡（回來後可能需要重新登入）。
    </p>

    <el-skeleton v-if="isPending" :rows="4" animated />
    <QueryError v-else-if="isError" :error="error" @retry="refetch()" />
    <el-empty
      v-else-if="data && data.items.length === 0"
      :description="isAdmin ? '尚未連結平台帳號，請先連結 Discord 頻道或 Threads 帳號' : '尚未連結平台帳號，請管理員連結'"
    />
    <el-table v-else-if="data" :data="data.items" row-key="id">
      <el-table-column label="平台" width="120">
        <template #default="{ row }">{{ label(PLATFORM_LABELS, row.platform) }}</template>
      </el-table-column>
      <el-table-column prop="account_name" label="帳號名稱" min-width="180" />
      <el-table-column label="授權狀態" width="110">
        <template #default="{ row }">
          <el-tag :type="row.auth_status === 'valid' ? 'success' : 'danger'" disable-transitions>
            {{ label(AUTH_STATUS_LABELS, row.auth_status) }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="授權到期" width="160">
        <template #default="{ row }">
          <span v-if="row.auth_expires_at">{{ formatTaipei(row.auth_expires_at) }}</span>
          <span v-else class="muted">不會過期</span>
        </template>
      </el-table-column>
      <el-table-column v-if="isAdmin" label="操作" width="140">
        <template #default="{ row }">
          <el-button
            v-if="row.platform === 'threads'"
            size="small"
            :type="row.auth_status === 'valid' ? 'default' : 'danger'"
            :loading="oauthMutation.isPending.value"
            @click="oauthMutation.mutate({ platform: 'threads', accountId: row.id })"
          >
            重新連結
          </el-button>
        </template>
      </el-table-column>
    </el-table>

    <el-dialog v-model="discordDialog" title="連結 Discord 頻道" width="min(480px, 92vw)">
      <el-form ref="discordFormRef" :model="discordForm" :rules="discordRules" label-position="top" @submit.prevent>
        <el-form-item label="顯示名稱" prop="account_name">
          <el-input v-model="discordForm.account_name" placeholder="例如：社團公告" maxlength="100" />
        </el-form-item>
        <el-form-item label="Webhook 網址" prop="webhook_url">
          <el-input
            v-model="discordForm.webhook_url"
            type="password"
            show-password
            autocomplete="off"
            :placeholder="WEBHOOK_PLACEHOLDER"
          />
          <div class="muted hint">在 Discord 頻道設定 → 整合 → Webhook 建立後複製網址。網址等同密碼，請勿外流。</div>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="discordDialog = false">取消</el-button>
        <el-button type="primary" :loading="discordMutation.isPending.value" @click="submitDiscord">連結</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.intro {
  margin: -8px 0 16px;
}

.hint {
  line-height: 1.5;
  margin-top: 4px;
}
</style>
