<script setup lang="ts">
import { useMutation, useQuery, useQueryClient } from '@tanstack/vue-query'
import { ElMessage, ElMessageBox, type FormInstance, type FormRules } from 'element-plus'
import { computed, onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { platformAccountsApi, type PlatformAccount } from '@/shared/api/endpoints'
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

// 用平台授權（OAuth）連結的平台；Discord 用 Webhook
const OAUTH_PLATFORMS = new Set(['threads', 'instagram'])
const OAUTH_LINKS = [
  { platform: 'threads', label: '連結 Threads 帳號' },
  { platform: 'instagram', label: '連結 Instagram 帳號' },
] as const

// ---------- Threads、Instagram：取得授權網址後整頁導向平台（重新連結時帶 platform_account_id） ----------
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
// 有值時是「更換 Webhook」（FR-21 重新連結），沒有值時是新連結
const relinkTarget = ref<PlatformAccount | null>(null)
const discordTitle = computed(() =>
  relinkTarget.value ? `更換「${relinkTarget.value.account_name}」的 Webhook` : '連結 Discord 頻道',
)
const discordRules: FormRules = {
  account_name: [
    {
      validator: (_rule, value: string, callback) =>
        relinkTarget.value || value.trim() ? callback() : callback(new Error('請輸入顯示名稱')),
      trigger: 'blur',
    },
  ],
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

function openDiscord(target: PlatformAccount | null = null) {
  relinkTarget.value = target
  discordForm.account_name = ''
  discordForm.webhook_url = ''
  discordDialog.value = true
}

const discordMutation = useMutation({
  mutationFn: () =>
    relinkTarget.value
      ? platformAccountsApi.relinkDiscord(relinkTarget.value.id, discordForm.webhook_url.trim())
      : platformAccountsApi.linkDiscord({
          platform: 'discord',
          account_name: discordForm.account_name.trim(),
          webhook_url: discordForm.webhook_url.trim(),
        }),
  onSuccess: () => {
    ElMessage.success(relinkTarget.value ? '已更換 Webhook' : '已連結 Discord 頻道')
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

// ---------- 移除（FR-08）：已排程貼文會把這個目標拿掉，只剩這個目標的貼文會改回草稿（BR-23） ----------
const removeMutation = useMutation({
  mutationFn: (account: PlatformAccount) => platformAccountsApi.remove(account.id),
  onSuccess: (_, account) => {
    ElMessage.success(`已移除「${account.account_name}」`)
    void queryClient.invalidateQueries({ queryKey: ['platform-accounts'] })
    void queryClient.invalidateQueries({ queryKey: ['posts'] })
  },
})

async function remove(account: PlatformAccount) {
  try {
    await ElMessageBox.confirm(
      `移除後不能再發文到「${account.account_name}」。草稿與已排程的貼文會拿掉這個目標，只剩這個目標的已排程貼文會改回草稿；已發佈的結果仍會保留。確定要移除嗎？`,
      '移除平台帳號',
      { confirmButtonText: '移除', cancelButtonText: '取消', type: 'warning', confirmButtonClass: 'el-button--danger' },
    )
  } catch {
    return
  }
  removeMutation.mutate(account)
}
</script>

<template>
  <div class="page">
    <div class="page-header">
      <h1>平台帳號</h1>
      <div v-if="isAdmin" class="toolbar">
        <el-button @click="openDiscord()">連結 Discord 頻道</el-button>
        <el-button
          v-for="option in OAUTH_LINKS"
          :key="option.platform"
          type="primary"
          :loading="oauthMutation.isPending.value && oauthMutation.variables.value?.platform === option.platform"
          :disabled="oauthMutation.isPending.value"
          @click="oauthMutation.mutate({ platform: option.platform })"
        >
          {{ option.label }}
        </el-button>
      </div>
    </div>
    <p v-if="isAdmin" class="muted intro">
      連結 Threads 或 Instagram 會前往平台的授權頁，完成後自動回到這裡並顯示結果。Instagram
      授權時請只勾選一個專業帳號。
    </p>

    <el-skeleton v-if="isPending" :rows="4" animated />
    <QueryError v-else-if="isError" :error="error" @retry="refetch()" />
    <el-empty
      v-else-if="data && data.items.length === 0"
      :description="isAdmin ? '尚未連結平台帳號，請先連結 Discord 頻道、Threads 或 Instagram 帳號' : '尚未連結平台帳號，請管理員連結'"
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
      <el-table-column v-if="isAdmin" label="操作" width="200">
        <template #default="{ row }">
          <el-button
            v-if="OAUTH_PLATFORMS.has(row.platform)"
            size="small"
            :type="row.auth_status === 'valid' ? 'default' : 'danger'"
            :loading="oauthMutation.isPending.value && oauthMutation.variables.value?.accountId === row.id"
            @click="oauthMutation.mutate({ platform: row.platform, accountId: row.id })"
          >
            重新連結
          </el-button>
          <el-button
            v-else
            size="small"
            :type="row.auth_status === 'valid' ? 'default' : 'danger'"
            @click="openDiscord(row)"
          >
            更換 Webhook
          </el-button>
          <el-button
            size="small"
            type="danger"
            plain
            :loading="removeMutation.isPending.value && removeMutation.variables.value?.id === row.id"
            @click="remove(row)"
          >
            移除
          </el-button>
        </template>
      </el-table-column>
    </el-table>

    <el-dialog v-model="discordDialog" :title="discordTitle" width="min(480px, 92vw)">
      <el-form ref="discordFormRef" :model="discordForm" :rules="discordRules" label-position="top" @submit.prevent>
        <el-form-item v-if="!relinkTarget" label="顯示名稱" prop="account_name">
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
        <el-button type="primary" :loading="discordMutation.isPending.value" @click="submitDiscord">
          {{ relinkTarget ? '更換' : '連結' }}
        </el-button>
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
